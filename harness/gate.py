#!/usr/bin/env python3
"""Telemetry health gate shared by every pipeline engine in the experiments.

Polls Prometheus every --interval seconds for --hold seconds and exits:
  0  healthy for the whole hold period
  1  first violation (error ratio or p95 latency above threshold)
  2  Prometheus unreachable / no data for the whole hold
Prints one JSON line per evaluation so the driver can log detection time.

Prometheus is reached through the API-server service proxy by default
(kubectl get --raw), or directly with --prom-url from inside the cluster.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request

PROXY = "/api/v1/namespaces/istio-system/services/prometheus:9090/proxy/api/v1/query"


def query(args, q):
    qs = urllib.parse.urlencode({"query": q})
    if args.prom_url:
        with urllib.request.urlopen(f"{args.prom_url}/api/v1/query?{qs}", timeout=3) as r:
            body = json.load(r)
    else:
        out = subprocess.run(["kubectl", "get", "--raw", f"{PROXY}?{qs}"],
                             capture_output=True, text=True, timeout=5)
        body = json.loads(out.stdout)
    res = body["data"]["result"]
    if not res:
        return None
    v = float(res[0]["value"][1])
    return None if v != v else v  # NaN -> None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hold", type=float, default=20)
    p.add_argument("--interval", type=float, default=2)
    p.add_argument("--window", default="10s")
    p.add_argument("--max-error-ratio", type=float, default=0.01)
    p.add_argument("--max-p95-ms", type=float, default=50)
    p.add_argument("--prom-url", default="")
    args = p.parse_args()
    w = args.window
    # "or vector(0)": with no failures the numerator has no series at all.
    q_err = (f'(sum(rate(loadgen_msgs_total{{result!="ok"}}[{w}])) or vector(0)) / '
             f'sum(rate(loadgen_msgs_total[{w}]))')
    q_p95 = (f'1000 * histogram_quantile(0.95, '
             f'sum(rate(loadgen_latency_seconds_bucket[{w}])) by (le))')
    end = time.time() + args.hold
    seen_data = False
    while True:
        t = time.time()
        try:
            err, p95 = query(args, q_err), query(args, q_p95)
        except Exception as e:  # noqa: BLE001 - any failure is "no data"
            err = p95 = None
            print(json.dumps({"t": t, "error": str(e)}), flush=True)
        seen_data |= err is not None
        bad = (err is not None and err > args.max_error_ratio) or \
              (p95 is not None and p95 > args.max_p95_ms)
        print(json.dumps({"t": t, "err_ratio": err, "p95_ms": p95,
                          "healthy": not bad}), flush=True)
        if bad:
            sys.exit(1)
        if time.time() >= end:
            sys.exit(0 if seen_data else 2)
        time.sleep(max(0, args.interval - (time.time() - t)))


if __name__ == "__main__":
    main()
