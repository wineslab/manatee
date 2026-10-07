#!/usr/bin/env python3
"""Open-loop indication generator (stand-in for the E2 indication stream).

Sends RATE msg/s to TARGET for DURATION seconds. Each message travels on a
connection that carries MSGS_PER_CONN messages; with the default of 1 every
message is a new TCP connection, so L4 weighted routing applies per message.

Writes one CSV row per second with what was observed for each version, and
exposes the same counters to Prometheus for the health gates.
"""
import argparse
import asyncio
import csv
import json
import random
import time
from collections import defaultdict

from prometheus_client import Counter, Histogram, start_http_server

MSGS = Counter("loadgen_msgs_total", "Messages by outcome", ["version", "result"])
LAT = Histogram("loadgen_latency_seconds", "Ack latency", ["version"],
                buckets=(.001, .002, .005, .01, .02, .05, .1, .2, .5, 1.0))

stats = defaultdict(lambda: defaultdict(int))
lat = defaultdict(list)
# Optional per-connection log (connect time, version that answered): gives
# sub-second resolution for weight propagation and rollback.
conn_log = None


def record(sec, version, result, latency=None):
    stats[sec][f"{result}_{version}"] += 1
    MSGS.labels(version, result).inc()
    if latency is not None:
        lat[sec].append(latency)
        LAT.labels(version).observe(latency)


def log_conn(t0, version, result):
    if conn_log is not None:
        conn_log.write(f"{t0:.6f},{version},{result}\n")


async def session(host, port, seqs, timeout, n_ues):
    """One TCP connection carrying len(seqs) messages. If the connection
    fails, the messages it had not delivered yet are recorded as lost with
    the same cause, so sent == answered + lost for every connection."""
    t_open = time.time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        for _ in seqs:
            record(int(t_open), "none", "connfail")
        log_conn(t_open, "none", "connfail")
        return
    first = True
    try:
        for i, seq in enumerate(seqs):
            t0 = time.time()
            msg = {"seq": seq, "ue": random.randrange(n_ues), "ts": t0}
            writer.write((json.dumps(msg) + "\n").encode())
            failure = None
            try:
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout)
                if not line:
                    # Accepted by the proxy but closed by the far end.
                    failure = "reset"
            except (OSError, asyncio.TimeoutError):
                failure = "timeout"
            if failure:
                for _ in seqs[i:]:
                    record(int(t0), "none", failure)
                if first:
                    log_conn(t_open, "none", failure)
                return
            ack = json.loads(line)
            result = "ok" if ack.get("status") == "ok" else "err"
            if first:
                log_conn(t_open, ack.get("ver", "unknown"), result)
                first = False
            record(int(t0), ack.get("ver", "unknown"), result, time.time() - t0)
    finally:
        writer.close()


async def run(args):
    host, port = args.target.split(":")
    port = int(port)
    sem = asyncio.Semaphore(args.max_inflight)
    interval = args.msgs_per_conn / args.rate
    start = time.time()
    seq = 0
    tasks = set()

    async def guarded(seqs):
        async with sem:
            await session(host, port, seqs, args.timeout, args.ues)

    next_t = start
    while time.time() - start < args.duration:
        seqs = list(range(seq, seq + args.msgs_per_conn))
        seq += args.msgs_per_conn
        for s in seqs:
            stats[int(time.time())]["sent"] += 1
        t = asyncio.create_task(guarded(seqs))
        tasks.add(t)
        t.add_done_callback(tasks.discard)
        next_t += interval
        delay = next_t - time.time()
        if delay > 0:
            await asyncio.sleep(delay)
    await asyncio.gather(*tasks, return_exceptions=True)


async def writer_loop(path, stop):
    cols = ["timestamp", "sent", "ok_v1", "ok_v2", "err_v1", "err_v2",
            "timeout_none", "reset_none", "connfail_none", "ok_unknown",
            "lat_mean_ms", "lat_p95_ms"]
    with open(path, "w", newline="", buffering=1) as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        last = int(time.time()) - 1
        while not stop.is_set():
            await asyncio.sleep(1)
            # Flush seconds that are at least timeout+1 s old so late acks count.
            cutoff = int(time.time()) - 3
            for sec in range(last + 1, cutoff + 1):
                row = {c: stats[sec].get(c, 0) for c in cols}
                row["timestamp"] = sec
                ls = sorted(lat.pop(sec, []))
                row["lat_mean_ms"] = round(1000 * sum(ls) / len(ls), 3) if ls else ""
                row["lat_p95_ms"] = round(1000 * ls[int(.95 * (len(ls) - 1))], 3) if ls else ""
                if row["sent"] or any(row[c] for c in cols[2:10]):
                    w.writerow(row)
                stats.pop(sec, None)
            last = cutoff


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--target", required=True)
    p.add_argument("--rate", type=float, default=100)
    p.add_argument("--duration", type=float, default=60)
    p.add_argument("--msgs-per-conn", type=int, default=1)
    p.add_argument("--timeout", type=float, default=1.0)
    p.add_argument("--max-inflight", type=int, default=2000)
    p.add_argument("--ues", type=int, default=64)
    p.add_argument("--csv", default="/data/loadgen.csv")
    p.add_argument("--metrics-port", type=int, default=9102)
    p.add_argument("--conn-log", default="")
    args = p.parse_args()
    global conn_log
    if args.conn_log:
        conn_log = open(args.conn_log, "w", buffering=1 << 16)
        conn_log.write("t,version,result\n")
    start_http_server(args.metrics_port)
    stop = asyncio.Event()
    w = asyncio.create_task(writer_loop(args.csv, stop))
    print(f"loadgen -> {args.target} {args.rate} msg/s for {args.duration}s", flush=True)
    await run(args)
    await asyncio.sleep(4)
    stop.set()
    await w
    if conn_log is not None:
        conn_log.close()
    print("loadgen done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
