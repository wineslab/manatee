#!/usr/bin/env python3
"""A/B switch on the real RIC path (xDevSM PRB xApps -> OSC E2Term -> srsRAN).

Per run (results/oib/ab/rep<k>/):
  prb-xapp-a.ablog / prb-xapp-b.ablog   ABLOG,<t>,<send|ack|fail>,<xapp>,...
  gnb-prb.log                           srsRAN "Slice-level PRB quota Control
                                        Request" lines followed by "Min PRB ..."
  events.csv                            switch_start, ...

Times relative to switch_start. The gNB-side owner of each applied control is
identified by its Min PRB Policy Ratio (A=10, B=60).
  a_last_ack_s / b_first_ack_s   last ack to A / first ack to B (xApp side)
  gnb_last_a_s / gnb_first_b_s   last policy from A / first from B applied at gNB
  gnb_overlap_s                  max(0, gnb_last_a - gnb_first_b)
  gnb_both_seconds               seconds after the switch in which the gNB
                                 applied policies from both xApps (conflict)
  a_after / b_before             policies from A applied after the switch /
                                 from B before it (should be 0)
"""
import csv
import re
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

OWNER = {10: "A", 60: "B"}
TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)")


def gnb_policies(path):
    out, t = [], None
    for line in open(path):
        m = TS.match(line)
        if m and "Control Request" in line:
            t = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc).timestamp()
        elif "Min PRB Policy Ratio" in line and t is not None:
            out.append((t, OWNER.get(int(line.split(":")[-1]), "?")))
            t = None
    return out


def acks(path):
    return [float(r[1]) for r in csv.reader(open(path)) if len(r) > 2 and r[2] == "ack"]


def run_metrics(run):
    ev = {e["event"]: float(e["t"]) for e in csv.DictReader(open(run / "events.csv"))}
    t0, t_end = ev["switch_start"], ev["end"]
    pol = [(t - t0, o) for t, o in gnb_policies(run / "gnb-prb.log") if ev["phase_a_start"] <= t <= t_end]
    a = [t - t0 for t in acks(run / "prb-xapp-a.ablog")]
    b = [t - t0 for t in acks(run / "prb-xapp-b.ablog")]
    ga = [t for t, o in pol if o == "A"]
    gb = [t for t, o in pol if o == "B"]
    m = {"a_last_ack_s": max((t for t in a if t <= t_end - t0), default=None),
         "b_first_ack_s": min((t for t in b if t >= 0), default=None),
         "gnb_last_a_s": max(ga, default=None), "gnb_first_b_s": min((t for t in gb if t >= 0), default=None),
         "a_after": sum(1 for t in ga if t > 0), "b_before": sum(1 for t in gb if t < 0),
         "policies_applied": len(pol)}
    if m["gnb_last_a_s"] is not None and m["gnb_first_b_s"] is not None:
        m["gnb_overlap_s"] = max(0.0, m["gnb_last_a_s"] - m["gnb_first_b_s"])
    secs = {}
    for t, o in pol:
        if t >= 0:
            secs.setdefault(int(t), set()).add(o)
    m["gnb_both_seconds"] = sum(1 for s in secs.values() if {"A", "B"} <= s)
    return m


def main(root):
    runs = sorted(Path(root).glob("rep*"))
    ms = []
    for r in runs:
        m = run_metrics(r)
        ms.append(m)
        print(r.name, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()})
    if len(ms) > 1:
        for k in ms[0]:
            vals = [m[k] for m in ms if m.get(k) is not None]
            if vals:
                sd = st.stdev(vals) if len(vals) > 1 else 0.0
                print(f"{k}: {st.mean(vals):.3f} ± {sd:.3f} (n={len(vals)})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/oib/ab")
