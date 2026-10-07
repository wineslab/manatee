#!/usr/bin/env bash
# E5: identical canary, A/B and overhead scenarios on different data planes.
# MESH (istio | istio-gw | ambient | linkerd | cilium) selects the data plane;
# xApps, load, gate and the MANATEE Ansible pipeline are unchanged.
#
#   MESH=linkerd e5_mesh.sh <scenario> <fault> <rep>
#     scenario  canary    5-step canary under the telemetry gate (fault none|error)
#               ab        control-authority switch from v1 to v2
#               overhead  steady 50/50 split, latency and proxy resource usage
set -euo pipefail
source "$(dirname "$0")/lib.sh"
SCEN=$1; FAULT=$2; REP=$3
RATE=${RATE:-1000}; MPC=${MPC:-10}
# VARIANT tags configuration variants of one data plane (e.g. connlimit).
OUT=$RESULTS/e5/$MESH${VARIANT:+-$VARIANT}/$SCEN/$FAULT/rep$REP
EV=$DATA/events.csv

proxy_usage() {  # sample data-plane CPU/memory every 5 s into proxy-usage.csv
  echo "t,namespace,pod,container,cpu_m,mem_mi" > $DATA/proxy-usage.csv
  while true; do
    t=$(now)
    for ns in $NS istio-system linkerd kube-system; do
      kubectl top pod -n $ns --containers --no-headers 2>/dev/null |
        awk -v t=$t -v ns=$ns '{gsub("m","",$3); gsub("Mi","",$4); print t","ns","$1","$2","$3","$4}'
    done >> $DATA/proxy-usage.csv
    sleep 5
  done
}

reset_jobs
clean_xapps
kubectl -n $NS delete vs,dr --all --ignore-not-found >/dev/null 2>&1 || true
kubectl -n $NS delete tcproute --all --ignore-not-found >/dev/null 2>&1 || true
kubectl -n $NS delete authorizationpolicy.security.istio.io,ciliumnetworkpolicy --all --ignore-not-found >/dev/null 2>&1 || true
kubectl -n $NS delete authorizationpolicy.policy.linkerd.io,server.policy.linkerd.io --all --ignore-not-found >/dev/null 2>&1 || true
setup_base
# Fail fast if the namespace is not enrolled in the intended data plane.
pod_containers=$(kubectl -n $NS get pod -l app=sink -o jsonpath='{.items[0].spec.containers[*].name} {.items[0].spec.initContainers[*].name}')
case $MESH in
  istio|istio-gw) [[ $pod_containers == *istio-proxy* ]] ;;
  linkerd) [[ $pod_containers == *linkerd-proxy* && $pod_containers != *istio-proxy* ]] ;;
  ambient|cilium) [[ $pod_containers != *istio-proxy* && $pod_containers != *linkerd-proxy* ]] ;;
esac || { echo "sink containers '$pod_containers' do not match MESH=$MESH" >&2; exit 3; }
sudo -n rm -f $DATA/*.csv $DATA/*.log
echo "t,event,detail" > $EV
proxy_usage </dev/null >/dev/null 2>&1 & USAGE=$!
trap 'kill $USAGE 2>/dev/null || true' EXIT

case $SCEN in
  canary)
    deploy_xapp v1 30
    deploy_xapp v2 70 $FAULT 0 150
    [ $MESH = istio ] && istio_weights 100 0 || set_weights 100 0
    # Let the initial 100/0 route take effect (ambient enrols the waypoint
    # asynchronously); pre-release v2 traffic is reported by the analysis.
    sleep 15
    start_loadgen e5 xapp.$NS:9000 $RATE 220 $MPC
    wait_loadgen_running
    log_event $EV loadgen_running
    sleep 20
    log_event $EV release_start
    run_canary '[10,25,50,75,100]' 20 || true
    log_event $EV release_done
    wait_loadgen_done 600 e5 ;;
  ab)
    restart_sink
    deploy_xapp v1 30
    deploy_xapp v2 70
    if [ "${VARIANT:-}" = noconnlimit ]; then ab_conn_limit ""; else ab_conn_limit "${MAX_CONN_S:-1}"; fi
    ab_block v2
    sleep 5
    for v in v1 v2; do start_loadgen ab-$v xapp-$v.$NS:9000 100 70 $MPC; done
    wait_loadgen_running
    log_event $EV loadgen_running
    sleep 30
    log_event $EV switch_start
    ab_block v1
    log_event $EV switch_applied
    wait_loadgen_done 300 ab-v1 ab-v2 ;;
  overhead)
    deploy_xapp v1 30
    deploy_xapp v2 70
    if [ $MESH = istio ]; then istio_weights 50 50; else set_weights 50 50; fi
    start_loadgen e5 xapp.$NS:9000 $RATE 90 $MPC
    wait_loadgen_running
    log_event $EV loadgen_running
    wait_loadgen_done 300 e5 ;;
esac
kill $USAGE 2>/dev/null || true
collect "$OUT"
echo "$OUT"
