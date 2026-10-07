#!/usr/bin/env python3
"""Control-message sink (stand-in for the E2 node receiving RIC control).

Counts control messages per second per issuing xApp version and flags a
collision whenever two different versions command the same UE within
COLLISION_WINDOW seconds with different PRB ratios: the conflict that the
A/B authority switch is meant to prevent.
"""
import argparse
import asyncio
import csv
import json
import time
from collections import defaultdict

from prometheus_client import Counter, start_http_server

CTRL = Counter("sink_controls_total", "Control messages received", ["src"])
COLL = Counter("sink_collisions_total", "Conflicting commands for one UE")

per_sec = defaultdict(lambda: defaultdict(int))
last_cmd = {}  # ue -> (src, prb_ratio, t)
msg_log = None  # optional per-command log for sub-second handover timing


async def handle(reader, writer, window):
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            cmd = json.loads(line)
            now = time.time()
            sec = int(now)
            src, ue = cmd.get("src", "unknown"), cmd.get("ue")
            per_sec[sec][f"ctrl_{src}"] += 1
            CTRL.labels(src).inc()
            if msg_log is not None:
                msg_log.write(f"{now:.6f},{src},{ue}\n")
            prev = last_cmd.get(ue)
            if prev and prev[0] != src and prev[1] != cmd.get("prb_ratio") \
                    and now - prev[2] <= window:
                per_sec[sec]["collisions"] += 1
                COLL.inc()
            last_cmd[ue] = (src, cmd.get("prb_ratio"), now)
            writer.write(b'{"ack":1}\n')
            await writer.drain()
    except (ConnectionError, json.JSONDecodeError):
        pass
    finally:
        writer.close()


async def writer_loop(path):
    cols = ["timestamp", "ctrl_v1", "ctrl_v2", "collisions"]
    with open(path, "w", newline="", buffering=1) as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        last = int(time.time())
        while True:
            await asyncio.sleep(1)
            cutoff = int(time.time()) - 1
            for sec in range(last + 1, cutoff + 1):
                row = {c: per_sec[sec].get(c, 0) for c in cols}
                row["timestamp"] = sec
                w.writerow(row)
                per_sec.pop(sec, None)
            last = cutoff


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9100)
    p.add_argument("--csv", default="/data/sink.csv")
    p.add_argument("--window", type=float, default=1.0)
    p.add_argument("--metrics-port", type=int, default=9102)
    p.add_argument("--msg-log", default="")
    args = p.parse_args()
    global msg_log
    if args.msg_log:
        msg_log = open(args.msg_log, "w", buffering=1)
        msg_log.write("t,src,ue\n")
    start_http_server(args.metrics_port)
    await asyncio.start_server(lambda r, w: handle(r, w, args.window),
                               "0.0.0.0", args.port)
    print(f"sink listening on {args.port}", flush=True)
    await writer_loop(args.csv)


if __name__ == "__main__":
    asyncio.run(main())
