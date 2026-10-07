#!/usr/bin/env python3
"""Per-run metrics for E3 (orchestration engines driving the same canary).

Reads results/e3/<engine>/<fault>/rep<k>/ (events.csv with API-server
vs_weight timestamps, conns-e3.csv, loadgen-e3.csv, engine-usage.csv).

  first_actuation_s  release_start -> first weight change visible in the API
  step_overhead_s    mean (interval between consecutive weight increases - hold)
  full_traffic_s     release_start -> weight 100 visible in the API (healthy)
  detect_to_api_s    first faulty connection -> weight 0 visible in the API
  last_faulty_s      first faulty connection -> last connection served by v2
  faulty_msgs        messages answered by the faulty v2
  engine_cpu_m       mean CPU (millicores) of the engine's namespaces during the run
  engine_mem_mi      mean memory (MiB) of the engine's namespaces during the run
  host_cpu_m         mean CPU of the engine's processes on the host (Ansible and
  host_mem_mi        gate; gate and git for the GitOps driver), from
                     host-usage-*.csv sampled by harness/host_usage.py
"""
import csv
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HOLD = 20
HOST_CATS = {"ansible": {"ansible", "gate"}, "argocd-webhook": {"gate", "git"},
             "argocd-poll": {"gate", "git"}}
HOST_USAGE = []  # (t, category, cpu_m, mem_mi), loaded in main()

ENGINE_NS = {"ansible": [], "tekton": ["tekton-pipelines", "manatee-ci"],
             "argocd-webhook": ["argocd", "gitops"], "argocd-poll": ["argocd", "gitops"],
             "argo-rollouts": ["argo-rollouts"]}


def weights(events):
    out = []
    for e in events:
        if e["event"] == "vs_weight" and e["detail"].strip().isdigit():
            w = int(e["detail"])
            if not out or out[-1][1] != w:
                out.append((float(e["t"]), w))
    return out


def run_metrics(run, engine, fault):
    events = list(csv.DictReader(open(run / "events.csv")))
    first = {}
    for e in events:
        first.setdefault(e["event"], float(e["t"]))
    t0 = first["release_start"]
    ws = [(t, w) for t, w in weights(events) if t >= t0]
    m = {}
    if ws:
        m["first_actuation_s"] = ws[0][0] - t0
    ups = [b[0] - a[0] - HOLD for a, b in zip(ws, ws[1:]) if b[1] > a[1]]
    if ups:
        m["step_overhead_s"] = st.mean(ups)
    conns = list(csv.DictReader(open(run / "conns-e3.csv")))
    if fault == "none":
        full = [t for t, w in ws if w == 100]
        m["full_traffic_s"] = full[0] - t0 if full else None
        m["promoted"] = int(bool(full))
    else:
        bad = [float(c["t"]) for c in conns if c["version"] == "v2"]
        back = [t for t, w in ws if w == 0]
        if bad:
            m["detect_to_api_s"] = (back[0] - bad[0]) if back else None
            m["last_faulty_s"] = bad[-1] - bad[0]
        m["rolled_back"] = int(bool(back))
        rows = list(csv.DictReader(open(run / "loadgen-e3.csv")))
        m["faulty_msgs"] = sum(int(r["ok_v2"]) + int(r["err_v2"]) for r in rows)
    cats = HOST_CATS.get(engine)
    t_end = first.get("release_done")
    if cats and t_end and HOST_USAGE:
        per_t = defaultdict(lambda: [0.0, 0.0])
        for t, c, cpu, mem in HOST_USAGE:
            if t0 <= t <= t_end and c in cats:
                per_t[t][0] += cpu
                per_t[t][1] += mem
        if per_t:
            m["host_cpu_m"] = st.mean(v[0] for v in per_t.values())
            m["host_mem_mi"] = st.mean(v[1] for v in per_t.values())
    usage = run / "engine-usage.csv"
    nss = ENGINE_NS[engine]
    if nss and usage.exists():
        per_t = defaultdict(lambda: [0.0, 0.0])
        for r in csv.DictReader(open(usage)):
            if r["namespace"] in nss and r["cpu_m"].isdigit():
                per_t[r["t"]][0] += float(r["cpu_m"])
                per_t[r["t"]][1] += float(r["mem_mi"])
        if per_t:
            m["engine_cpu_m"] = st.mean(v[0] for v in per_t.values())
            m["engine_mem_mi"] = st.mean(v[1] for v in per_t.values())
    return m


def main(root):
    root = Path(root)
    for f in list(root.parent.glob("host-usage-*.csv")) + list(root.glob("host-usage-*.csv")):
        for r in csv.DictReader(open(f)):
            HOST_USAGE.append((float(r["t"]), r["category"], float(r["cpu_m"]), float(r["mem_mi"])))
    rows, groups = [], defaultdict(list)
    for run in sorted(root.glob("*/*/rep*")):
        engine, fault, rep = run.parts[-3:]
        if rep == "rep0":
            continue  # smoke runs
        try:
            m = run_metrics(run, engine, fault)
        except (FileNotFoundError, KeyError) as e:
            print(f"skip {run}: {e}", file=sys.stderr)
            continue
        rows.append({"engine": engine, "fault": fault, "rep": rep[3:], **m})
        groups[(engine, fault)].append(m)
    keys = ["engine", "fault", "rep"] + sorted({k for r in rows for k in r} - {"engine", "fault", "rep"})
    with open(root / "e3_runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    summary = []
    for (engine, fault), ms in sorted(groups.items()):
        row = {"engine": engine, "fault": fault, "n": len(ms)}
        for k in sorted({k for m in ms for k in m}):
            vals = [m[k] for m in ms if m.get(k) is not None]
            if vals:
                row[f"{k}_mean"] = round(st.mean(vals), 3)
                row[f"{k}_std"] = round(st.stdev(vals), 3) if len(vals) > 1 else 0
        summary.append(row)
        print(row)
    skeys = []
    for r in summary:
        skeys += [k for k in r if k not in skeys]
    with open(root / "e3_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=skeys)
        w.writeheader()
        w.writerows(summary)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/e3")
