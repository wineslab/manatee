#!/usr/bin/env bash
# Probe: how fast does an AuthorizationPolicy change move control authority
# from xApp v1 to v2 on an already-established control connection?
set -euo pipefail
source "$(dirname "$0")/lib.sh"
OUT=${1:-$RESULTS/probe-ab-$(date +%Y%m%d-%H%M%S)}
EV=$DATA/events.csv

reset_jobs
restart_sink
istio_weights 50 50
if [ -n "${MAX_CONN_S:-}" ]; then
  MAX_CONN_S=$MAX_CONN_S envsubst < $K8S_DIR/istio-ab-sink-dr.yaml.tpl | kubectl apply -f - >/dev/null
else
  kubectl -n $NS delete dr sink --ignore-not-found >/dev/null
fi
ab_block v2
sleep 5
echo "t,event,detail" > $EV
for v in v1 v2; do start_loadgen ab-$v xapp-$v.$NS:9000 100 70; done
wait_loadgen_running
log_event $EV loadgen_running
sleep 30
log_event $EV switch_start "block v1"
ab_block v1
log_event $EV switch_applied
wait_loadgen_done 150 ab-v1 ab-v2
collect "$OUT"
echo "$OUT"
