#!/usr/bin/env python3
"""LaTeX tables for E1/E2 (release mechanisms) and E3 (engines) from the
summary CSVs written by e1_summary.py and e3_summary.py.

  python3 tables.py <results_dir> <out_dir>
writes tab_e1_release.tex and tab_e3_engines.tex (tabular only).
"""
import csv
import sys
from pathlib import Path

MECH = [("manatee", r"\oursol{} canary"), ("native-bbm", "Undeploy, then deploy"),
        ("native-mbb", "Deploy beside, then undeploy"), ("native-rolling", "Rolling update")]
ENGINE = [("ansible", r"Ansible (\oursol)"), ("tekton", "Tekton"),
          ("argocd-webhook", "ArgoCD (webhook)"), ("argocd-poll", "ArgoCD (polling)"),
          ("argo-rollouts", "Argo Rollouts")]


def load(path):
    return list(csv.DictReader(open(path))) if path.exists() else []


def pm(row, key, digits=1, scale=1.0):
    m, s = row.get(f"{key}_mean"), row.get(f"{key}_std")
    if m in (None, ""):
        return "--"
    return f"${float(m) * scale:.{digits}f} \\pm {float(s or 0) * scale:.{digits}f}$"


def e1(res):
    rows = load(res / "e1" / "e1_summary.csv")
    find = lambda m, f, r: next((x for x in rows if x["mechanism"] == m and x["fault"] == f
                                 and x["rate"] == r), {})
    out = [r"\begin{tabular}{lccccc}", r"\hline",
           r" & \multicolumn{2}{c}{\textbf{Healthy v2}} & \multicolumn{2}{c}{\textbf{Faulty v2 (errors)}} & \\",
           r"\textbf{Mechanism} & \textbf{Lost msgs} & \textbf{To 100\,\% v2 (s)} & "
           r"\textbf{Msgs to faulty v2} & \textbf{Peak share (\%)} & \textbf{Actions} \\",
           r"\hline"]
    for rate in ("100", "1000"):
        out.append(rf"\multicolumn{{6}}{{l}}{{\emph{{{rate} msg/s}}}} \\")
        for key, label in MECH:
            h, f = find(key, "none", rate), find(key, "error", rate)
            if not h:
                continue
            out.append(f"{label} & {pm(h, 'lost', 0)} & {pm(h, 'switch_s', 1)} & "
                       f"{pm(f, 'faulty_served', 0)} & {pm(f, 'peak_exposure', 0, 100)} & "
                       f"{pm(f, 'actions', 0)} \\\\")
    out += [r"\hline", r"\end{tabular}"]
    return "\n".join(out)


def e3(res):
    rows = load(res / "e3" / "e3_summary.csv")
    find = lambda e, f: next((x for x in rows if x["engine"] == e and x["fault"] == f), {})
    out = [r"\begin{tabular}{lcccccc}", r"\hline",
           r"\textbf{Engine} & \textbf{First change (s)} & \textbf{Per step (s)} & "
           r"\textbf{To 100\,\% (s)} & \textbf{Rollback (s)} & \textbf{Msgs to faulty v2} & "
           r"\textbf{Memory (MiB)} \\", r"\hline"]
    for key, label in ENGINE:
        h, f = find(key, "none"), find(key, "error")
        if not h:
            continue
        mem = sum(float(h.get(k) or 0) for k in ("engine_mem_mi_mean", "host_mem_mi_mean"))
        out.append(f"{label} & {pm(h, 'first_actuation_s', 2)} & {pm(h, 'step_overhead_s', 2)} & "
                   f"{pm(h, 'full_traffic_s', 1)} & {pm(f, 'detect_to_api_s', 1)} & "
                   f"{pm(f, 'faulty_msgs', 0)} & ${mem:.0f}$ \\\\")
    out += [r"\hline", r"\end{tabular}"]
    return "\n".join(out)


def main():
    res, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    (out / "tab_e1_release.tex").write_text(e1(res) + "\n")
    (out / "tab_e3_engines.tex").write_text(e3(res) + "\n")


if __name__ == "__main__":
    main()
