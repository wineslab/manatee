#!/usr/bin/env python3
"""Writes revision-plots.ipynb: the revision figures in the layout of the
existing paper notebooks (same style cells: Set2 colour map, Computer Modern
via LaTeX, 20 pt), one section per experiment, figures shown inline.

  python3 make_notebook.py <out.ipynb>
"""
import sys

import nbformat as nbf

STYLE_IMPORTS = """import sys
import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path
from IPython.display import Image, display

sys.path.insert(0, "analysis")
import plots

RES, OUT = Path("results"), Path("figures")"""

SET_COLOR_MAP = '''def set_color_map(plt, cm: str) -> bool:
    """
    Sets the colormap for the specified plot:
        - https://matplotlib.org/stable/tutorials/colors/colormaps.html
    """
    # to change default color cycle
    plt.rcParams["image.cmap"] = cm
    colormaps = plt.cm.__dict__
    if cm in colormaps:
        plt.rcParams["axes.prop_cycle"] = plt.cycler(color=colormaps[cm].colors)
        return True
    else:
        return False'''

RC = """mpl.rcParams.update(
    {
        "pgf.texsystem": "pdflatex",
        "font.family": "serif",
        "font.serif": "Computer Modern Roman",
        "text.usetex": True,
        "pgf.rcfonts": False,
        "font.size": 20,
    }
)
use_pgf = True
plt.rcParams["text.usetex"] = True"""

SECTIONS = [
    ("E1/E2 — Release mechanisms vs the O-RAN SC baseline",
     "Share of traffic served by v2 after the release (1000 msg/s, one run, "
     "5 s moving average), then the per-mechanism summary over 5 runs.",
     ['plots.e1_timeline(RES, OUT, "none")', 'display(Image(OUT / "fig_e1_timeline_none.png"))',
      'plots.e1_timeline(RES, OUT, "error")', 'display(Image(OUT / "fig_e1_timeline_error.png"))',
      'plots.e1_bars(RES, OUT)', 'display(Image(OUT / "fig_e1_bars.png"))']),
    ("E3 — Orchestration engines",
     "Same canary driven by Ansible (MANATEE), Tekton, ArgoCD and Argo Rollouts "
     "(10 runs each; ArgoCD with default polling only in the table).",
     ['plots.e3_engines(RES, OUT)', 'display(Image(OUT / "fig_e3_engines.png"))']),
    ("E4 — A/B control-authority switch (emulated control path)",
     "Control commands received at the E2 side per xApp, six data-plane configurations, "
     "and the supplementary figure with every variant including circuit breakers.",
     ['plots.e4_ab(RES, OUT)', 'display(Image(OUT / "fig_e4_ab.png"))',
      'plots.e4_ab(RES, OUT, spec=plots.AB_PANELS_ALL, name="fig_e4_ab_all")',
      'display(Image(OUT / "fig_e4_ab_all.png"))']),
    ("E4 — A/B switch on the real RAN (xDevSM + OSC RIC + srsRAN)",
     "UE downlink throughput across the switch and the PRB policy the srsRAN gNB "
     "applied at each control (xApp A: max 30 % PRB, xApp B: max 90 % PRB).",
     ['plots.e4_real(RES, OUT)', 'display(Image(OUT / "fig_e4_real_ran.png"))']),
    ("E5 — Data-plane overhead",
     "Latency and data-plane CPU under a steady 50/50 split at 1000 msg/s.",
     ['plots.e5_overhead(RES, OUT)', 'display(Image(OUT / "fig_e5_overhead.png"))']),
]


def main(path):
    nb = nbf.v4.new_notebook()
    cells = [nbf.v4.new_markdown_cell(
                 "# MANATEE revision — figures\n\nGenerated from `results/` by `analysis/plots.py` "
                 "(same style as the other notebooks in `~/manatee`). Re-run all cells after "
                 "copying new results."),
             nbf.v4.new_code_cell(STYLE_IMPORTS),
             nbf.v4.new_code_cell(SET_COLOR_MAP),
             nbf.v4.new_code_cell('set_color_map(plt, "Set2")'),
             nbf.v4.new_code_cell(RC)]
    for title, text, code in SECTIONS:
        cells.append(nbf.v4.new_markdown_cell(f"## {title}\n\n{text}"))
        for i in range(0, len(code), 2):
            cells.append(nbf.v4.new_code_cell("\n".join(code[i:i + 2])))
    nb["cells"] = cells
    nbf.write(nb, path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "revision-plots.ipynb")
