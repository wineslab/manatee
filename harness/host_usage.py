#!/usr/bin/env python3
"""Samples CPU and memory of engine processes that run on the host (outside
the cluster) every 2 s: ansible (ansible-playbook and its workers), gate
(gate.py) and git (the GitOps driver's commits/pushes).
  host_usage.py <out.csv>"""
import os
import sys
import time

CATS = {"ansible": "ansible-playbook", "gate": "gate.py", "git": "git"}
TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def sample():
    out = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
            stat = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
            rss = int(open(f"/proc/{pid}/statm").read().split()[1]) * PAGE
        except OSError:
            continue
        if "host_usage.py" in cmd:
            continue
        for cat, key in CATS.items():
            if key in cmd.split(" ")[0] or (cat != "git" and key in cmd):
                out[pid] = (cat, int(stat[11]) + int(stat[12]), rss)
                break
    return out


prev, t_prev = sample(), time.time()
with open(sys.argv[1], "a", buffering=1) as f:
    if f.tell() == 0:
        f.write("t,category,cpu_m,mem_mi\n")
    while True:
        time.sleep(2)
        cur, t = sample(), time.time()
        agg = {c: [0.0, 0.0] for c in CATS}
        for pid, (cat, ticks, rss) in cur.items():
            d = ticks - prev.get(pid, (cat, ticks, 0))[1] if pid in prev else 0
            agg[cat][0] += 1000 * d / TICK / (t - t_prev)
            agg[cat][1] += rss / 2**20
        for cat, (cpu, mem) in agg.items():
            f.write(f"{t:.3f},{cat},{cpu:.1f},{mem:.1f}\n")
        prev, t_prev = cur, t
