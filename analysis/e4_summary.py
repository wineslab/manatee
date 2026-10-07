#!/usr/bin/env python3
"""Per-run metrics for the A/B control-authority switch (E4, and E5 'ab').

Reads <run>/sink-msgs.csv (one line per control command received) and
events.csv (switch_start). Only the run's own load window is used
(switch_start + WINDOW_S): early runs moved the sink's open files at collect
time, so later commands kept being appended to them. Times are relative to
switch_start:
  last_old_s     last command from the revoked version (v1)
  first_new_s    first command from the new holder (v2)
  overlap_s      max(0, last_old - first_new): both versions in control
  gap_s          max(0, first_new - last_old): nobody in control
  collisions     conflicting commands for one UE after the switch (sink.csv)
  leaked_old     commands from v1 accepted after the switch
  pre_new        commands from v2 accepted in the 20 s before the switch
                 (> 0 means the mechanism never blocked v2 at all)
"""
import csv
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path


WINDOW_S = 35  # load runs ~40 s past the switch


def run_metrics(run):
    ev = {e["event"]: float(e["t"]) for e in csv.DictReader(open(run / "events.csv"))}
    t0 = ev["switch_start"]
    all_msgs = [(float(r["t"]), r["src"]) for r in csv.DictReader(open(run / "sink-msgs.csv"))]
    msgs = [(t, s) for t, s in all_msgs if t0 <= t <= t0 + WINDOW_S]
    pre_new = sum(1 for t, s in all_msgs if s == "v2" and t0 - 20 <= t < t0)
    old = [t - t0 for t, s in msgs if s == "v1" and t >= t0]
    new = [t - t0 for t, s in msgs if s == "v2" and t >= t0]
    last_old = old[-1] if old else 0.0
    first_new = new[0] if new else None
    m = {"last_old_s": last_old, "first_new_s": first_new,
         "leaked_old": len(old), "pre_new": pre_new}
    if first_new is not None:
        m["overlap_s"] = max(0.0, last_old - first_new)
        m["gap_s"] = max(0.0, first_new - last_old)
    rows = list(csv.DictReader(open(run / "sink.csv")))
    m["collisions"] = sum(int(r["collisions"]) for r in rows
                          if int(t0) <= int(r["timestamp"]) <= t0 + WINDOW_S)
    return m


def main(paths):
    groups = defaultdict(list)
    for root in paths:
        for ev in sorted(Path(root).rglob("events.csv")):
            run = ev.parent
            if not (run / "sink-msgs.csv").exists():
                continue
            try:
                m = run_metrics(run)
            except KeyError:
                continue
            groups[str(run.parent)].append(m)
    for cfg, ms in sorted(groups.items()):
        row = {"config": cfg, "n": len(ms)}
        for k in ms[0]:
            vals = [m[k] for m in ms if m.get(k) is not None]
            if vals:
                row[k] = f"{st.mean(vals):.3f}±{(st.stdev(vals) if len(vals) > 1 else 0):.3f}"
        print(row)


if __name__ == "__main__":
    main(sys.argv[1:] or ["results"])
