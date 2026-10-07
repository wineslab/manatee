#!/usr/bin/env bash
# Probe: MANATEE canary with a healthy or a faulty v2.
# Usage: probe_canary.sh <fault_mode:none|error|delay> [rate]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
FAULT=${1:-none}; RATE=${2:-100}
OUT=$RESULTS/probe-canary-$FAULT-$(date +%Y%m%d-%H%M%S)
EV=$DATA/events.csv
reset_jobs
deploy_xapp v1 30
deploy_xapp v2 70 $FAULT 0 1500
kubectl -n $NS rollout status deploy/xapp-v1 deploy/xapp-v2 --timeout=120s >/dev/null
istio_weights 100 0
echo "t,event,detail" > $EV
start_loadgen canary xapp.$NS:9000 $RATE 200
wait_loadgen_running
log_event $EV loadgen_running
sleep 20
run_canary '[10,25,50,75,100]' 20 || true
log_event $EV pipeline_done
wait_loadgen_done 300 canary
collect "$OUT"
echo "$OUT"
