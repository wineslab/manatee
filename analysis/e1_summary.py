#!/usr/bin/env python3
"""Per-run metrics for E1/E2 (release mechanism comparison).

Reads results/e1/<mechanism>/<fault>/r<rate>/rep<k>/{loadgen-e1.csv,events.csv}
and writes one row per run plus a per-configuration summary (mean, std).

Metrics, all measured from release_start:
  lost            messages sent but never answered (timeout, reset, refused)
  faulty_served   messages answered by the faulty v2 (fault != none)
  peak_exposure   highest 5 s share of traffic served by faulty v2
  detect_s        first faulty-served second -> gate_fail event
  recover_s       first faulty-served second -> last faulty-served second
  switch_s        (healthy runs) release_start -> first second with v1 == 0
                  for good, i.e. the time the operator waits for the change
  max_gap_s       longest run of seconds in which nothing was answered
  actions         operator commands the mechanism needs (static, see below)
"""
import csv
import statistics as st
import sys
from pathlib import Path

# Operator commands per release (+ per rollback): MANATEE is one pipeline
# trigger; the native flows are the helm/xApp Manager calls listed in the
# experiment script.
ACTIONS = {"manatee": (1, 0), "native-bbm": (2, 2), "native-mbb": (2, 1),
           "native-rolling": (1, 1)}


def load(run):
    rows = list(csv.DictReader(open(run / "loadgen-e1.csv")))
    for r in rows:
        for k, v in r.items():
            r[k] = float(v) if v not in ("", None) else 0.0
    events = {}
    for e in csv.DictReader(open(run / "events.csv")):
        events.setdefault(e["event"], float(e["t"]))
    return rows, events


def metrics(run, mech, fault):
    rows, ev = load(run)
    t0 = ev["release_start"]
    after = [r for r in rows if r["timestamp"] >= int(t0)]
    # Lost = sent - answered. Robust to the early loadgen that recorded only
    # the first failed message of a connection carrying several messages.
    answered = lambda r: r["ok_v1"] + r["ok_v2"] + r["err_v1"] + r["err_v2"] + r["ok_unknown"]
    lost = max(0.0, sum(r["sent"] - answered(r) for r in after))
    m = {"lost": lost}
    if fault != "none":
        served = [r for r in after if r["ok_v2"] + r["err_v2"] > 0]
        m["faulty_served"] = sum(r["ok_v2"] + r["err_v2"] for r in after)
        # Share of traffic served by v2 over a 5 s rolling window (at 100 msg/s
        # with 20 msgs per connection a single second holds only 5 connections),
        # capped at 1 because a message may be answered in the next second.
        shares = []
        for i in range(len(after) - 4):
            win = after[i:i + 5]
            sent = sum(r["sent"] for r in win)
            if sent:
                shares.append(sum(r["ok_v2"] + r["err_v2"] for r in win) / sent)
        m["peak_exposure"] = min(1.0, max(shares, default=0))
        if served:
            first, last = served[0]["timestamp"], served[-1]["timestamp"]
            m["detect_s"] = ev["gate_fail"] - first if "gate_fail" in ev else None
            m["recover_s"] = last + 1 - first
        m["rolled_back"] = int("gate_fail" in ev)
    else:
        v1_secs = [r["timestamp"] for r in after if r["ok_v1"] > 0]
        m["switch_s"] = (v1_secs[-1] + 1 - t0) if v1_secs else 0.0
        m["promoted"] = int(all(r["ok_v1"] == 0 for r in after[-10:]))
    gap = best = 0
    for r in after:
        answered = r["ok_v1"] + r["ok_v2"] + r["err_v1"] + r["err_v2"]
        gap = gap + 1 if r["sent"] and answered == 0 else 0
        best = max(best, gap)
    m["max_gap_s"] = best
    release, rollback = ACTIONS[mech]
    m["actions"] = release + (rollback if m.get("rolled_back") else 0)
    return m


def main(root):
    root = Path(root)
    per_run, groups = [], {}
    for run in sorted(root.glob("*/*/r*/rep*")):
        mech, fault, rate, rep = run.parts[-4:]
        try:
            m = metrics(run, mech, fault)
        except (FileNotFoundError, KeyError) as e:
            print(f"skip {run}: {e}", file=sys.stderr)
            continue
        key = (mech, fault, rate[1:])
        per_run.append({"mechanism": mech, "fault": fault, "rate": rate[1:],
                        "rep": rep[3:], **m})
        groups.setdefault(key, []).append(m)
    cols = sorted({k for r in per_run for k in r})
    lead = ["mechanism", "fault", "rate", "rep"]
    with open(root / "e1_runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=lead + [c for c in cols if c not in lead])
        w.writeheader()
        w.writerows(per_run)
    summary = []
    for (mech, fault, rate), ms in sorted(groups.items()):
        row = {"mechanism": mech, "fault": fault, "rate": rate, "n": len(ms)}
        for k in sorted({k for m in ms for k in m}):
            vals = [m[k] for m in ms if m.get(k) is not None]
            if vals:
                row[f"{k}_mean"] = round(st.mean(vals), 3)
                row[f"{k}_std"] = round(st.stdev(vals), 3) if len(vals) > 1 else 0
        summary.append(row)
    keys = []
    for r in summary:
        keys += [k for k in r if k not in keys]
    with open(root / "e1_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(summary)
    for r in summary:
        print(r)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/e1")
