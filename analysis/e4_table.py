#!/usr/bin/env python3
"""LaTeX table for the A/B control-authority switch (E4), one row per
configuration, mean ± std over repetitions (smoke runs rep0 excluded).

  python3 e4_table.py <results_dir> > tab_e4_ab.tex
"""
import statistics as st
import sys
from pathlib import Path

from e4_summary import run_metrics

ROWS = [
    ("Istio sidecar", "receiver policy only", "e5/istio-noconnlimit/ab/none"),
    ("Istio sidecar", "receiver policy + lifetime", "e5/istio/ab/none"),
    ("Istio sidecar", "DR maxConnections 0 + lifetime", "cbtest/dr-life1"),
    ("Istio sidecar", "Envoy breaker 0 + lifetime", "cbtest/envoyfilter-life1"),
    ("Istio sidecar", "DR plaintext vs. STRICT mTLS + lifetime", "cbtest/drtls-life1"),
    ("Istio sidecar", "sender route only", "cbtest/route-lifenone"),
    ("Istio sidecar", r"\textbf{sender route + lifetime (MANATEE)}", "cbtest/route-life1"),
    ("Istio ambient", "selector policy", "e5/ambient-selectorpolicy/ab/none"),
    ("Istio ambient", "waypoint policy only", "e5/ambient-waypointpolicy/ab/none"),
    ("Istio ambient", "waypoint policy + lifetime", "e5/ambient-connlimit/ab/none"),
    ("Linkerd", "receiver policy", "e5/linkerd/ab/none"),
    ("Cilium", "eBPF network policy", "e5/cilium/ab/none"),
]
WINDOW = 35  # seconds after the switch covered by the measurement


def fmt(vals, digits=2):
    if not vals:
        return "--"
    m = st.mean(vals)
    s = st.stdev(vals) if len(vals) > 1 else 0.0
    return f"${m:.{digits}f} \\pm {s:.{digits}f}$"


def main(res):
    res = Path(res)
    print(r"\begin{tabular}{llcccc}")
    print(r"\hline")
    print(r"\textbf{Data plane} & \textbf{Revocation mechanism} & $n$ & "
          r"\textbf{Revoked last (s)} & \textbf{New first (s)} & \textbf{Collisions} \\")
    print(r"\hline")
    for plane, mech, path in ROWS:
        runs = sorted(p for p in (res / path).glob("rep*") if p.name != "rep0")
        ms = []
        for r in runs:
            try:
                ms.append(run_metrics(r))
            except (FileNotFoundError, KeyError):
                pass
        if not ms:
            print(f"{plane} & {mech} & 0 & \\multicolumn{{3}}{{c}}{{pending}} \\\\")
            continue
        last = [m["last_old_s"] for m in ms]
        # A revoked xApp still sending at the end of the window was never revoked.
        last_s = (rf"$\geq {WINDOW}$ (never)" if min(last) > WINDOW - 1 else fmt(last))
        never_blocked = min(m["pre_new"] for m in ms) > 0
        first_s = ("never blocked" if never_blocked else
                   fmt([m["first_new_s"] for m in ms if m["first_new_s"] is not None]))
        print(f"{plane} & {mech} & {len(ms)} & {last_s} & {first_s} & "
              f"{fmt([m['collisions'] for m in ms], 1)} \\\\")
    print(r"\hline")
    print(r"\end{tabular}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results")
