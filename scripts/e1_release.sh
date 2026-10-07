#!/usr/bin/env bash
# E1/E2: replace a running xApp v1 with v2 under load, with one of four
# release mechanisms, optionally with a faulty v2.
#
#   e1_release.sh <mechanism> <fault> <rate> <rep>
#     mechanism  manatee       MANATEE canary, Ansible + Istio weights + gate
#                native-bbm    O-RAN SC xApp Manager style: undeploy v1, deploy v2
#                native-mbb    deploy v2 next to v1 (equal round-robin), undeploy v1
#                native-rolling Kubernetes rolling update of one Deployment
#     fault      none | error | delay   (v2 acks errors / adds 150 ms)
#
# Native mechanisms get the same telemetry gate as MANATEE, run as a monitor
# after the release, and an automated rollback, so detection is identical and
# only the release mechanism differs.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
MECH=$1; FAULT=$2; RATE=$3; REP=$4
# Messages per TCP connection: RMR keeps connections open, so the split is
# applied per connection; 20 keeps per-connection handshakes negligible.
MPC=${MPC:-20}
OUT=$RESULTS/e1/$MECH/$FAULT/r$RATE/rep$REP
EV=$DATA/events.csv
STEPS='[10,25,50,75,100]'; HOLD=20
OBSERVE=$(( 5 * HOLD ))   # native observation time = canary duration
LOAD_S=$(( 20 + OBSERVE + 60 ))
GATE="python3 $REV_ROOT/harness/gate.py --interval 2 --window 10s"
# Native releases: the post-release monitor starts one gate window after the
# release, so the switchover itself (counted separately as lost messages)
# does not make the gate roll back a healthy v2.
SETTLE=10

reset_jobs
clean_xapps
MESH=istio setup_base
case $MECH in
  manatee)
    deploy_xapp v1 30
    deploy_xapp v2 70 $FAULT 0 150
    istio_weights 100 0 ;;
  native-rolling)
    mesh_routing_off
    helm_xapp xapp v1 30 none 0 0 4 ;;
  *)
    mesh_routing_off
    deploy_xapp v1 30 ;;
esac

echo "t,event,detail" > $EV
start_loadgen e1 xapp.$NS:9000 $RATE $LOAD_S $MPC
wait_loadgen_running
log_event $EV loadgen_running
sleep 20

gate_or_rollback() {  # gate_or_rollback <rollback-cmd...>
  sleep $SETTLE
  if $GATE --hold $OBSERVE > $DATA/gate.log 2>&1; then
    log_event $EV gate_pass
  else
    log_event $EV gate_fail
    log_event $EV rollback_start
    "$@"
    log_event $EV rollback_done
    return 1
  fi
}

rollback_bbm() { undeploy_xapp xapp-v2; deploy_xapp v1 30; }
rollback_rolling() { helm rollback xapp -n $NS --wait >/dev/null; }

ok=0
case $MECH in
  manatee)
    log_event $EV release_start
    run_canary "$STEPS" $HOLD && ok=1
    log_event $EV release_done
    [ $ok = 1 ] && undeploy_xapp xapp-v1 && log_event $EV v1_removed ;;
  native-bbm)
    log_event $EV release_start
    undeploy_xapp xapp-v1; log_event $EV v1_removed
    deploy_xapp v2 70 $FAULT 0 150; log_event $EV v2_ready
    log_event $EV release_done
    gate_or_rollback rollback_bbm || true ;;
  native-mbb)
    log_event $EV release_start
    deploy_xapp v2 70 $FAULT 0 150; log_event $EV v2_ready
    if gate_or_rollback undeploy_xapp xapp-v2; then
      undeploy_xapp xapp-v1; log_event $EV v1_removed
    fi
    log_event $EV release_done ;;
  native-rolling)
    log_event $EV release_start
    helm_xapp xapp v2 70 $FAULT 0 150 4; log_event $EV rollout_done
    log_event $EV release_done
    gate_or_rollback rollback_rolling || true ;;
esac

wait_loadgen_done 600 e1
collect "$OUT"
echo "$OUT"
