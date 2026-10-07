#!/usr/bin/env python3
"""watch_ts.py <out.csv> <event> -- <command...>
Runs a streaming command (e.g. kubectl get -w) and appends
"<unix time>,<event>,<line>" to out.csv for every output line. Terminates
its child on SIGTERM so no process keeps the caller's pipes open."""
import signal
import subprocess
import sys
import time

out, event = sys.argv[1], sys.argv[2]
cmd = sys.argv[sys.argv.index("--") + 1:]
child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, text=True, bufsize=1)


def stop(*_):
    child.terminate()
    sys.exit(0)


signal.signal(signal.SIGTERM, stop)
with open(out, "a", buffering=1) as f:
    for line in child.stdout:
        f.write(f"{time.time():.6f},{event},{line.strip()}\n")
