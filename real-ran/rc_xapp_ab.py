# Copyright the xDevSM authors (wineslab/xDevSM-xapps-examples), Apache-2.0.
# Modified for MANATEE: periodic control instead of a single request, send and
# acknowledgement logging, optional RIC Call Process ID override, and support
# for both 0.2.0-dev and 0.3.0-dev of the framework. See THIRD_PARTY_NOTICES.md.
"""Periodic variant of the xDevSM PRB-control xApp (prb_control_xapp/rc_xapp.py,
image angeloferaudo/prb-control-xapp, tags 0.2.0-dev and 0.3.0-dev) for the
real-RAN A/B experiment. 0.2.0-dev is used: the E2SM-RC decoder of 0.3.0-dev
segfaults on the RAN function definitions of the OAI and srsRAN gNBs tested.

The upstream xApp sends one RIC Control Request (E2SM-RC slice-level PRB
quota, control action 6) and terminates on the RIC Control Acknowledge. For
an A/B test both versions must keep controlling, so this script runs the same
setup and calls the same RadioResourceAllocationControl.send() every
--period seconds instead of terminating. The xDevSM framework is unchanged.

Every send (with its RMR state) and every acknowledgement is printed as
  ABLOG,<unix time>,<send|ack|fail>,<xapp name>,<detail>
so that kubectl logs gives the per-xApp control timeline.
"""
import argparse
import inspect
import signal
import sys
import time

sys.path.insert(0, "/ws")  # image working directory: setup_imports, config/
import setup_imports  # noqa: F401  (adds xDevSM to the path, as upstream)
from ricxappframe.rmr import rmr

from xDevSM.handlers.xDevSM_rmr_xapp import xDevSMRMRXapp
from xDevSM.decorators.rc.rc_radio_resource_alloc_control import RadioResourceAllocationControl

NAME = "unknown"
_orig_send = rmr.rmr_send_msg


def ablog(event, detail=""):
    print(f"ABLOG,{time.time():.6f},{event},{NAME},{detail}", flush=True)


def _logged_send(vctx, sbuf):
    """Record the RMR state of every RIC Control Request (0 = RMR_OK). The
    message type is read before sending: RMR may return a different buffer."""
    is_ctrl = sbuf.contents.mtype == 12040
    out = _orig_send(vctx, sbuf)
    if is_ctrl:
        ablog("send", f"rmr_state={out.contents.state}")
    return out


rmr.rmr_send_msg = _logged_send


def main(args):
    global NAME
    xapp_gen = xDevSMRMRXapp("0.0.0.0")
    NAME = xapp_gen.get_xapp_name()
    logger = xapp_gen.logger
    # 0.3.0-dev added http_port to the decorator; 0.2.0-dev does not take it.
    extra = {}
    if "http_port" in inspect.signature(RadioResourceAllocationControl.__init__).parameters:
        extra["http_port"] = xapp_gen.http_port
    rc_xapp = RadioResourceAllocationControl(xapp_gen,
                                             logger=logger,
                                             server=xapp_gen.server,
                                             xapp_name=xapp_gen.get_xapp_name(),
                                             rmr_port=xapp_gen.rmr_port,
                                             **extra,
                                             mrc=xapp_gen._mrc,
                                             pltnamespace=xapp_gen.get_pltnamespace(),
                                             app_namespace=xapp_gen.get_app_namespace(),
                                             plmn_identity=args.plmn,
                                             sst=args.sst,
                                             sd=args.sd,
                                             min_prb_policy_ratio=args.min_prb_policy_ratio,
                                             max_prb_policy_ratio=args.max_prb_policy_ratio,
                                             dedicated_prb_policy_ratio=args.dedicated_prb_policy_ratio,
                                             ue_id_type=args.mock_du_ue_id,
                                             ue_id=args.ue_id)
    xapp_gen.register_handler(rc_xapp.handle)
    # Callback registration was renamed between 0.2.0-dev and 0.3.0-dev.
    reg_suc = getattr(rc_xapp, "register_control_ack_suc_callback", None) or \
        rc_xapp.register_rc_control_ack_suc_callback
    reg_fail = getattr(rc_xapp, "register_control_ack_fail_callback", None) or \
        rc_xapp.register_rc_control_ack_fail_callback
    reg_suc(lambda *a, **k: ablog("ack"))
    reg_fail(lambda *a, **k: ablog("fail"))
    signal.signal(signal.SIGINT, rc_xapp.terminate)
    signal.signal(signal.SIGTERM, rc_xapp.terminate)

    xapp_gen.run(thread=True)
    time.sleep(10)  # waiting for registrations, as upstream

    gnb, gnb_info = xapp_gen.get_selected_e2node_info(args.gnb_target)
    if not gnb:
        logger.info("[Main] no E2 node available, terminating")
        rc_xapp.terminate(signal.SIGTERM, None)
        return
    if args.call_process_id is not None:
        # srsRAN rejects a RIC Call Process ID when its RC control service does
        # not define one (call_process_id_format 0); xDevSM always sends b"1".
        orig = rc_xapp.send_control_request_rmr
        cpid = args.call_process_id.encode()
        rc_xapp.send_control_request_rmr = \
            lambda *a, **k: orig(*a, **{**k, "call_process_id": cpid})
    ran_function_description = rc_xapp.get_ran_function_description(json_ran_info=gnb_info)
    ablog("ready", f"gnb={gnb.inventory_name},ratios={args.min_prb_policy_ratio}/"
                   f"{args.max_prb_policy_ratio}/{args.dedicated_prb_policy_ratio}")
    while True:
        t0 = time.time()
        rc_xapp.send(e2_node_id=gnb.inventory_name,
                     ran_func_dsc=ran_function_description,
                     ue_id_struct=None,
                     control_action_id=6)  # slice-level PRB quota, as upstream
        time.sleep(max(0.0, args.period - (time.time() - t0)))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description="periodic prb xApp")
    p.add_argument("-p", "--plmn", type=str, default="00F110")
    p.add_argument("-s", "--sst", type=int, default=1)
    p.add_argument("-d", "--sd", type=int, default=1)
    p.add_argument("-r", "--min_prb_policy_ratio", type=int, default=20)
    p.add_argument("-x", "--max_prb_policy_ratio", type=int, default=80)
    p.add_argument("-y", "--dedicated_prb_policy_ratio", type=int, default=5)
    p.add_argument("-g", "--gnb_target", type=str)
    p.add_argument("-m", "--mock_du_ue_id", action="store_true")
    p.add_argument("-u", "--ue_id", type=int, default=1)
    p.add_argument("--period", type=float, default=1.0)
    p.add_argument("--call-process-id", default=None,
                   help="override the RIC Call Process ID ('' to send none)")
    main(p.parse_args())
