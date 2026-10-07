#!/usr/bin/env python3
"""Figures for the revision, in the style of the existing paper notebooks
(Set2 palette, Computer Modern via LaTeX, 20 pt, dotted grid).

  python3 plots.py <results_dir> <out_dir> [--no-tex]

fig_e1_timeline_<fault>.pdf  share of traffic served by v2 (and lost msg/s)
                             after the release, one line per mechanism
fig_e1_bars.pdf              faulty messages served, recovery time, lost
                             messages per mechanism
fig_e3_engines.pdf           actuation, per-step overhead and rollback time
                             per orchestration engine
fig_e4_ab.pdf                control commands per second from v1/v2 around
                             the authority switch, per data plane (replaces
                             the A/B figure with measured egress)
fig_e5_overhead.pdf          p95 latency and data-plane CPU per data plane
"""
import csv
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

MECH_LABEL = {"manatee": "MANATEE canary", "native-bbm": "Undeploy/deploy (OSC)",
              "native-mbb": "Deploy/undeploy (RR)", "native-rolling": "K8s rolling update"}
ENGINE_LABEL = {"ansible": "Ansible (MANATEE)", "tekton": "Tekton",
                "argocd-webhook": "ArgoCD (webhook)", "argocd-poll": "ArgoCD (poll)",
                "argo-rollouts": "Argo Rollouts"}
# Paper figure: one panel per data-plane configuration (6 panels).
AB_PANELS = [("e5/istio-noconnlimit/ab/none", "(a) Istio sidecar, policy only"),
             ("cbtest/route-life1", "(b) Istio sidecar, MANATEE"),
             ("e5/ambient-waypointpolicy/ab/none", "(c) Istio ambient, policy only"),
             ("e5/ambient-connlimit/ab/none", "(d) Istio ambient + conn. lifetime"),
             ("e5/linkerd/ab/none", "(e) Linkerd"),
             ("e5/cilium/ab/none", "(f) Cilium (eBPF)")]
# Supplementary figure: every variant measured, including the negative results.
AB_PANELS_ALL = AB_PANELS + [
             ("e5/istio/ab/none", "Istio sidecar, receiver policy + lifetime"),
             ("cbtest/route-lifenone", "Istio sidecar, sender route, no lifetime"),
             ("cbtest/dr-life1", "Istio sidecar, DR maxConnections 0 + lifetime"),
             ("cbtest/envoyfilter-life1", "Istio sidecar, Envoy breaker 0 + lifetime"),
             ("cbtest/drtls-life1", "Istio sidecar, DR-only (TLS) + lifetime"),
             ("e5/ambient-selectorpolicy/ab/none", "Istio ambient, selector policy")]
MESH_LABEL = {"istio": "Istio sidecar", "ambient": "Istio ambient",
              "linkerd": "Linkerd", "cilium": "Cilium"}


def style(tex):
    plt.rcParams["axes.prop_cycle"] = plt.cycler(color=plt.cm.Set2.colors)
    mpl.rcParams.update({"font.family": "serif", "font.size": 20,
                         "font.serif": "Computer Modern Roman", "text.usetex": tex})


def grid(ax):
    ax.grid(visible=True, color="grey", linestyle="dotted", linewidth=0.2)


def read(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def first_event(run, name):
    for e in read(run / "events.csv"):
        if e["event"] == name:
            return float(e["t"])
    return None


def save(fig, out, name):
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(out / f"{name}.{ext}", dpi=300, bbox_inches="tight")
    plt.close(fig)


def rolling(y, k=5):
    """Centred moving average; per-second shares are noisy at ~50 conn/s."""
    if len(y) < k:
        return y
    pad = k // 2
    ext = [y[0]] * pad + list(y) + [y[-1]] * pad
    return [sum(ext[i:i + k]) / k for i in range(len(y))]


def e1_timeline(res, out, fault, rate="1000", rep="rep1"):
    fig, ax = plt.subplots(figsize=(10, 5))
    for mech, label in MECH_LABEL.items():
        run = res / "e1" / mech / fault / f"r{rate}" / rep
        if not (run / "loadgen-e1.csv").exists():
            continue
        t0 = first_event(run, "release_start")
        rows = read(run / "loadgen-e1.csv")
        x, y = [], []
        for r in rows:
            sent = int(r["sent"])
            v2 = int(r["ok_v2"]) + int(r["err_v2"])
            if sent:
                x.append(int(r["timestamp"]) - t0)
                y.append(100 * v2 / sent)
        ax.plot(x, rolling(y), label=label, linewidth=2)
    ax.set_xlim(-10, 140)
    ax.set_ylim(-2, 102)
    ax.set_xlabel("Time since release start (s)")
    ax.set_ylabel(("Traffic to faulty v2" if fault != "none" else "Traffic to v2") + r" (\%)"
                  if mpl.rcParams["text.usetex"] else "Traffic to v2 (%)")
    grid(ax)
    ax.legend(fontsize=12, loc="best")
    save(fig, out, f"fig_e1_timeline_{fault}")


def summary(path):
    return read(path) if path.exists() else []


def bars(ax, groups, series, ylabel, log=False):
    """groups: x labels; series: list of (label, means, stds)."""
    width = 0.8 / max(1, len(series))
    x = np.arange(len(groups))
    for i, (label, means, stds) in enumerate(series):
        ax.bar(x + (i - (len(series) - 1) / 2) * width, means, width, yerr=stds,
               capsize=4, label=label)
    ax.set_xticks(x)
    ax.set_xticklabels(groups, fontsize=13, rotation=15)
    ax.set_ylabel(ylabel)
    if log:
        ax.set_yscale("log")
    grid(ax)


def e1_bars(res, out):
    rows = summary(res / "e1" / "e1_summary.csv")
    if not rows:
        return
    mechs = [m for m in MECH_LABEL if any(r["mechanism"] == m for r in rows)]
    labels = [MECH_LABEL[m].replace(" (", "\n(") for m in mechs]

    def get(fault, rate, key):
        means, stds = [], []
        for m in mechs:
            r = next((r for r in rows if r["mechanism"] == m and r["fault"] == fault
                      and r["rate"] == rate), {})
            means.append(float(r.get(f"{key}_mean") or 0))
            stds.append(float(r.get(f"{key}_std") or 0))
        return means, stds

    fig, axes = plt.subplots(1, 3, figsize=(24, 5))
    bars(axes[0], labels, [(f"{f}, {r} msg/s", *get(f, r, "faulty_served"))
                           for f in ("error", "delay") for r in ("100", "1000")],
         "Msgs served by faulty v2", log=True)
    peak = lambda f, r: tuple([100 * v for v in vals] for vals in get(f, r, "peak_exposure"))
    bars(axes[1], labels, [(f"{f}, {r} msg/s", *peak(f, r))
                           for f in ("error", "delay") for r in ("100", "1000")],
         "Peak traffic to faulty v2 (\\%)" if mpl.rcParams["text.usetex"] else "Peak traffic to faulty v2 (%)")
    bars(axes[2], labels, [(f"healthy, {r} msg/s", *get("none", r, "lost"))
                           for r in ("100", "1000")], "Lost messages (healthy v2)")
    axes[0].legend(fontsize=11)
    axes[2].legend(fontsize=11)
    save(fig, out, "fig_e1_bars")


def e3_engines(res, out):
    rows = summary(res / "e3" / "e3_summary.csv")
    if not rows:
        return
    # ArgoCD with default polling (minutes per step) stays in the table only;
    # on a common axis it would flatten every other engine.
    engines = [e for e in ENGINE_LABEL if e != "argocd-poll"
               and any(r["engine"] == e for r in rows)]
    labels = [ENGINE_LABEL[e].replace(" (", "\n(") for e in engines]

    def get(fault, key):
        means, stds = [], []
        for e in engines:
            r = next((r for r in rows if r["engine"] == e and r["fault"] == fault), {})
            means.append(float(r.get(f"{key}_mean") or 0))
            stds.append(float(r.get(f"{key}_std") or 0))
        return means, stds

    fig, axes = plt.subplots(1, 3, figsize=(27, 5.5))
    bars(axes[0], labels, [("first weight change", *get("none", "first_actuation_s")),
                           ("overhead per step", *get("none", "step_overhead_s")),
                           ("rollback", *get("error", "detect_to_api_s"))], "Time (s)")
    axes[0].legend(fontsize=12, loc="upper left")
    x = np.arange(len(engines))
    for ax, key, ylabel in ((axes[1], "cpu_m", "CPU (millicores)"),
                            (axes[2], "mem_mi", "Memory (MiB)")):
        incl, incl_s = get("none", f"engine_{key}")
        host, host_s = get("none", f"host_{key}")
        ax.bar(x, incl, 0.6, yerr=incl_s, capsize=4, label="in cluster")
        ax.bar(x, host, 0.6, bottom=incl, yerr=host_s, capsize=4, hatch="//",
               label="on the host")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=13, rotation=15)
        ax.set_ylabel(ylabel)
        grid(ax)
    axes[1].legend(fontsize=12, loc="upper left")
    save(fig, out, "fig_e3_engines")


def e4_ab(res, out, rep="rep1", spec=None, name="fig_e4_ab"):
    spec = spec or AB_PANELS
    cols = 3
    rows_n = (len(spec) + cols - 1) // cols
    fig, axes = plt.subplots(rows_n, cols, figsize=(8 * cols, 4.6 * rows_n), squeeze=False,
                             sharey=True)
    fig.subplots_adjust(hspace=0.55, wspace=0.08)
    for ax, (path, title) in zip(axes.flat, spec):
        run = res / path / rep
        ax.set_title(title, fontsize=15)
        ax.set_xlabel("Time since authority switch (s)")
        ax.set_xlim(-21, 31)
        grid(ax)
        if not (run / "sink.csv").exists():
            ax.text(0.5, 0.5, "measurement pending", transform=ax.transAxes,
                    ha="center", va="center", fontsize=14, color="grey")
            continue
        t0 = first_event(run, "switch_start")
        data = [r for r in read(run / "sink.csv") if t0 - 20 <= int(r["timestamp"]) <= t0 + 30]
        x = [int(r["timestamp"]) - t0 for r in data]
        # B dashed so that both stay visible when both versions hold control.
        ax.plot(x, [int(r["ctrl_v1"]) for r in data], label="control from xApp A (v1)", linewidth=2.5)
        ax.plot(x, [int(r["ctrl_v2"]) for r in data], label="control from xApp B (v2)",
                linewidth=2.5, linestyle="--")
        ax.bar(x, [int(r["collisions"]) for r in data], color="tab:red", alpha=0.5,
               label="conflicting commands")
        ax.axvline(0, color="darkred", linestyle=":", linewidth=1.5)
    for ax in axes[:, 0]:
        ax.set_ylabel("Commands/s")
    for ax in list(axes.flat)[len(spec):]:
        ax.axis("off")
    handles, labels = next((a.get_legend_handles_labels() for a in axes.flat
                            if a.get_legend_handles_labels()[0]), ([], []))
    fig.legend(handles, labels, loc="upper center", ncol=3, fontsize=14,
               bbox_to_anchor=(0.5, 1.02 + 0.02 * (2 - rows_n)))
    save(fig, out, name)


def gnb_policy_times(path):
    """(unix time, owner) for every slice PRB policy the srsRAN gNB applied;
    owner from the Min PRB Policy Ratio (A=10, B=60)."""
    import re
    from datetime import datetime, timezone
    ts = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)")
    out, t = [], None
    for line in open(path):
        m = ts.match(line)
        if m and "Control Request" in line:
            t = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc).timestamp()
        elif "Min PRB Policy Ratio" in line and t is not None:
            out.append((t, {10: "A", 60: "B"}.get(int(line.split(":")[-1]), "?")))
            t = None
    return out


def e4_real(res, out, rep="rep1"):
    """Real RAN (xDevSM PRB xApps, OSC RIC, srsRAN gNB + srsUE): UE downlink
    throughput across the authority switch, and the PRB policy applied by the
    gNB at each control (A: max 30 %, B: max 90 % of PRBs)."""
    panels = [("oib/ab-none-tput", "Native RIC (no mechanism)"),
              ("oib/ab-tput", "MANATEE (sender route + 1 s lifetime)")]
    panels = [(res / p / rep, t) for p, t in panels if (res / p / rep / "ue-tput.csv").exists()]
    if not panels:
        return
    fig, axes = plt.subplots(1, len(panels), figsize=(11 * len(panels), 5), squeeze=False, sharey=True)
    colors = plt.cm.Set2.colors
    for ax, (run, title) in zip(axes[0], panels):
        t0 = first_event(run, "switch_start")
        rows = [(float(t) - t0, int(b)) for t, b in csv.reader(open(run / "ue-tput.csv"))]
        # 1 s bins of the 0.5 s samples
        bins = {}
        for t, b in rows:
            bins.setdefault(int(t // 1), 0)
            bins[int(t // 1)] += b
        xs = sorted(k for k in bins if -30 <= k <= 39)
        ax.plot(xs, rolling([bins[k] * 8 / 1e6 for k in xs], 3), color="black", linewidth=2.2,
                label="UE downlink throughput")
        # One marker row per xApp (A above B), so both stay visible when the
        # gNB applies both policies in the same second.
        for t, o in gnb_policy_times(run / "gnb-prb.log"):
            if -30 <= t - t0 <= 40:
                ax.plot(t - t0, 0.13 if o == "A" else 0.05, marker="|", markersize=16, mew=2.5,
                        transform=ax.get_xaxis_transform(), color=colors[0] if o == "A" else colors[1])
        ax.plot([], [], marker="|", ls="", markersize=14, mew=2.5, color=colors[0],
                label="policy of xApp A applied (max 30 \\% PRB)" if mpl.rcParams["text.usetex"] else "policy of xApp A applied (max 30% PRB)")
        ax.plot([], [], marker="|", ls="", markersize=14, mew=2.5, color=colors[1],
                label="policy of xApp B applied (max 90 \\% PRB)" if mpl.rcParams["text.usetex"] else "policy of xApp B applied (max 90% PRB)")
        ax.axvline(0, color="darkred", linestyle=":", linewidth=1.5)
        ax.set_title(title, fontsize=17)
        ax.set_xlabel("Time since authority switch (s)")
        ax.set_xlim(-30, 40)
        ax.set_ylim(-4, 24)   # bottom band holds the policy marker rows
        ax.set_yticks([0, 5, 10, 15, 20])
        grid(ax)
    axes[0][0].set_ylabel("Throughput (Mbit/s)")
    axes[0][0].legend(fontsize=13, loc="center left")
    save(fig, out, "fig_e4_real_ran")


def e5_overhead(res, out):
    rows = [r for r in summary(res / "e5" / "e5_summary.csv") if r["scenario"] == "overhead"]
    if not rows:
        return
    meshes = [m for m in MESH_LABEL if any(r["mesh"] == m for r in rows)]
    get = lambda k: ([float(next(r for r in rows if r["mesh"] == m)[f"{k}_mean"]) for m in meshes],
                     [float(next(r for r in rows if r["mesh"] == m)[f"{k}_std"]) for m in meshes])
    fig, axes = plt.subplots(1, 2, figsize=(20, 5))
    labels = [MESH_LABEL[m] for m in meshes]
    bars(axes[0], labels, [("mean", *get("mean_ms")), ("p95", *get("p95_ms"))], "Latency (ms)")
    axes[0].legend(fontsize=12)
    bars(axes[1], labels, [("data-plane CPU (millicores)", *get("dp_cpu_m"))], "CPU (millicores)")
    save(fig, out, "fig_e5_overhead")


def main():
    res, out = Path(sys.argv[1]), Path(sys.argv[2])
    style("--no-tex" not in sys.argv)
    for fault in ("none", "error", "delay"):
        e1_timeline(res, out, fault)
    e1_bars(res, out)
    e3_engines(res, out)
    e4_ab(res, out)
    e4_ab(res, out, spec=AB_PANELS_ALL, name="fig_e4_ab_all")
    e5_overhead(res, out)
    e4_real(res, out)


if __name__ == "__main__":
    main()
