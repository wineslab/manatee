#!/usr/bin/env python3
"""Per-run metrics for E5 (same scenarios on different data planes).

results/e5/<mesh>/<scenario>/<fault>/rep<k>/

canary:
  split_err_pp      mean |observed v2 share - target| per step (percentage
                    points), observed from 2 s after the step to the next one
  first_v2_s        weight 0->10 applied -> first connection answered by v2
  detect_s          first connection answered by faulty v2 -> gate_fail
  rollback_prop_s   rollback applied -> last connection answered by v2
  faulty_msgs       messages answered by the faulty v2 after release_start
  pre_release_v2    connections answered by v2 before release_start, while
                    the route said 100/0 (route not yet in force)
overhead (steady 50/50 split, 1000 msg/s):
  p50_ms, p95_ms    medians of the per-second latency percentiles
  dp_cpu_m, dp_mem_mi  data-plane CPU/memory (proxies, ztunnel, waypoint,
                    Cilium agent/Envoy), mean of 5 s samples
The ab scenario is summarised by e4_summary.py.
"""
import csv
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

DP_CONTAINERS = {"istio-proxy", "linkerd-proxy", "istio-proxy-waypoint"}
DP_PODS = ("ztunnel", "waypoint", "cilium-", "cilium-envoy")


def events(run):
    return [(float(e["t"]), e["event"], e["detail"]) for e in csv.DictReader(open(run / "events.csv"))]


def canary(run, fault):
    ev = events(run)
    rows = {int(r["timestamp"]): r for r in csv.DictReader(open(run / "loadgen-e5.csv"))}
    conns = [(float(c["t"]), c["version"]) for c in csv.DictReader(open(run / "conns-e5.csv"))]
    steps = [(t, int(d)) for t, e, d in ev if e == "step"]
    ends = [t for t, e, _ in ev if e in ("step", "rollback_applied", "release_done")]
    m = {}
    errs = []
    for t, w in steps:
        nxt = min([x for x in ends if x > t + 1], default=t + 20)
        secs = [rows[s] for s in range(int(t) + 2, int(nxt)) if s in rows]
        ok = sum(int(r["ok_v1"]) + int(r["ok_v2"]) + int(r["err_v2"]) for r in secs)
        if ok:
            share = 100 * sum(int(r["ok_v2"]) + int(r["err_v2"]) for r in secs) / ok
            errs.append(abs(share - w))
    if errs:
        m["split_err_pp"] = st.mean(errs)
    if steps:
        first = [c for c, v in conns if v == "v2" and c >= steps[0][0]]
        if first:
            m["first_v2_s"] = first[0] - steps[0][0]
    t_rel = next(t for t, e, _ in ev if e == "release_start")
    m["pre_release_v2"] = sum(1 for c, v in conns if v == "v2" and c < t_rel)
    if fault != "none":
        v2 = [c for c, v in conns if v == "v2" and c >= t_rel]
        fail = [t for t, e, _ in ev if e == "gate_fail"]
        rb = [t for t, e, _ in ev if e == "rollback_applied"]
        if v2 and fail:
            m["detect_s"] = fail[0] - v2[0]
        if v2 and rb:
            m["rollback_prop_s"] = max(0.0, v2[-1] - rb[0])
        m["faulty_msgs"] = sum(int(r["ok_v2"]) + int(r["err_v2"])
                               for s, r in rows.items() if s >= int(t_rel))
    return m


def overhead(run):
    rows = list(csv.DictReader(open(run / "loadgen-e5.csv")))[5:-5]
    p50 = sorted(float(r["lat_mean_ms"]) for r in rows if r["lat_mean_ms"])
    p95 = sorted(float(r["lat_p95_ms"]) for r in rows if r["lat_p95_ms"])
    m = {"mean_ms": p50[len(p50) // 2], "p95_ms": p95[len(p95) // 2]}
    usage = run / "proxy-usage.csv"
    if usage.exists():
        per_t = defaultdict(lambda: [0.0, 0.0])
        for r in csv.DictReader(open(usage)):
            dp = r["container"] in DP_CONTAINERS or r["pod"].startswith(DP_PODS)
            if dp and r["cpu_m"].isdigit():
                per_t[r["t"]][0] += float(r["cpu_m"])
                per_t[r["t"]][1] += float(r["mem_mi"])
        if per_t:
            m["dp_cpu_m"] = st.mean(v[0] for v in per_t.values())
            m["dp_mem_mi"] = st.mean(v[1] for v in per_t.values())
    return m


def main(root):
    root = Path(root)
    groups = defaultdict(list)
    for run in sorted(root.glob("*/*/*/rep*")):
        mesh, scen, fault, rep = run.parts[-4:]
        if rep == "rep0" or scen == "ab":
            continue
        try:
            m = canary(run, fault) if scen == "canary" else overhead(run)
        except (FileNotFoundError, KeyError, ValueError) as e:
            print(f"skip {run}: {e}", file=sys.stderr)
            continue
        groups[(mesh, scen, fault)].append(m)
    summary = []
    for (mesh, scen, fault), ms in sorted(groups.items()):
        row = {"mesh": mesh, "scenario": scen, "fault": fault, "n": len(ms)}
        for k in sorted({k for m in ms for k in m}):
            vals = [m[k] for m in ms if m.get(k) is not None]
            row[f"{k}_mean"] = round(st.mean(vals), 3)
            row[f"{k}_std"] = round(st.stdev(vals), 3) if len(vals) > 1 else 0
        summary.append(row)
        print(row)
    keys = []
    for r in summary:
        keys += [k for k in r if k not in keys]
    with open(root / "e5_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(summary)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/e5")
