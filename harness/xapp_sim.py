#!/usr/bin/env python3
"""Mock xApp used in the revision experiments.

Data path (port 9000): newline-delimited JSON "indications" from the load
generator (stand-in for E2Term -> xApp). Every indication is acknowledged on
the same connection with the xApp version, so the sender can attribute each
message to v1/v2 and measure latency.

Control path: every CONTROL_EVERY indications the xApp emits a control
message to CONTROL_TARGET (stand-in for xApp -> E2Term -> E2 node). This is
the "egress" that the A/B experiments gate.

Fault injection (HTTP on 8080, POST /fault): mode none|error|delay|refuse,
optional delay_ms and after_s. Used to produce a faulty canary.
"""
import asyncio
import json
import os
import random
import time

from prometheus_client import Counter, Gauge, start_http_server
from aiohttp import web

VERSION = os.environ.get("VERSION", "v1")
PORT = int(os.environ.get("PORT", "9000"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9102"))
CONTROL_TARGET = os.environ.get("CONTROL_TARGET", "")
CONTROL_EVERY = int(os.environ.get("CONTROL_EVERY", "10"))
# Strategy knob so that A and B issue different PRB ratios for the same UE.
PRB_RATIO = int(os.environ.get("PRB_RATIO", "50"))
CONTROL_TTL = float(os.environ.get("CONTROL_TTL", "1.0"))

IND = Counter("xapp_indications_total", "Indications received", ["version"])
ACK = Counter("xapp_acks_total", "Acks sent", ["version", "status"])
CTRL = Counter("xapp_controls_total", "Control messages", ["version", "result"])
FAULT = Gauge("xapp_fault_active", "1 while a fault is injected", ["version"])

fault = {"mode": os.environ.get("FAULT_MODE", "none"),
         "delay_ms": float(os.environ.get("FAULT_DELAY_MS", "0")),
         "at": time.time() + float(os.environ.get("FAULT_AFTER_S", "0"))}
control_q: asyncio.Queue = None
server = None


def fault_mode():
    if fault["mode"] != "none" and time.time() >= fault["at"]:
        FAULT.labels(VERSION).set(1)
        return fault["mode"]
    FAULT.labels(VERSION).set(0)
    return "none"


async def handle(reader, writer):
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            msg = json.loads(line)
            IND.labels(VERSION).inc()
            mode = fault_mode()
            if mode == "delay":
                await asyncio.sleep(fault["delay_ms"] / 1000)
            status = "err" if mode == "error" else "ok"
            ack = {"seq": msg.get("seq"), "ver": VERSION, "status": status,
                   "ts": time.time()}
            writer.write((json.dumps(ack) + "\n").encode())
            await writer.drain()
            ACK.labels(VERSION, status).inc()
            if CONTROL_TARGET and msg.get("seq", 0) % CONTROL_EVERY == 0:
                try:
                    control_q.put_nowait((msg.get("ue", 0), time.time()))
                except asyncio.QueueFull:
                    CTRL.labels(VERSION, "dropped").inc()
    except (ConnectionError, json.JSONDecodeError):
        pass
    finally:
        writer.close()


async def control_sender():
    """Keeps one persistent connection to the control sink, like the RMR
    connection to E2Term. A control counts as delivered only when the sink
    acknowledges it (RIC Control Acknowledge); on failure the connection is
    re-established after a short backoff."""
    host, port = CONTROL_TARGET.split(":")
    reader = writer = None
    while True:
        ue, created = await control_q.get()
        # A RAN control decision is stale after CONTROL_TTL; never replay a
        # backlog accumulated while control authority was revoked.
        if time.time() - created > CONTROL_TTL:
            CTRL.labels(VERSION, "expired").inc()
            continue
        cmd = {"src": VERSION, "ue": ue, "prb_ratio": PRB_RATIO,
               "ts": time.time()}
        try:
            if writer is None or writer.is_closing():
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)), 1.0)
            writer.write((json.dumps(cmd) + "\n").encode())
            await asyncio.wait_for(writer.drain(), 1.0)
            if not await asyncio.wait_for(reader.readline(), 1.0):
                raise ConnectionResetError("control connection closed")
            CTRL.labels(VERSION, "acked").inc()
        except (OSError, asyncio.TimeoutError):
            CTRL.labels(VERSION, "failed").inc()
            if writer is not None:
                writer.close()
            reader = writer = None
            await asyncio.sleep(0.2)


async def start_listener():
    global server
    server = await asyncio.start_server(handle, "0.0.0.0", PORT, backlog=4096)


async def post_fault(request):
    body = await request.json()
    fault["mode"] = body.get("mode", "none")
    fault["delay_ms"] = float(body.get("delay_ms", 0))
    fault["at"] = time.time() + float(body.get("after_s", 0))
    # "refuse" closes the data-plane listener so new connections fail.
    if fault["mode"] == "refuse" and server is not None:
        server.close()
    elif fault["mode"] != "refuse" and (server is None or not server.is_serving()):
        await start_listener()
    return web.json_response({"version": VERSION, **fault})


async def healthz(_):
    healthy = fault_mode() == "none"
    return web.json_response({"version": VERSION, "healthy": healthy},
                             status=200 if healthy else 503)


async def main():
    global control_q
    control_q = asyncio.Queue(maxsize=10000)
    start_http_server(METRICS_PORT)
    await start_listener()
    if CONTROL_TARGET:
        asyncio.create_task(control_sender())
    app = web.Application()
    app.add_routes([web.post("/fault", post_fault), web.get("/healthz", healthz)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", HTTP_PORT).start()
    print(f"xapp {VERSION} listening on {PORT}, control -> {CONTROL_TARGET or 'off'}",
          flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    random.seed()
    asyncio.run(main())
