#!/usr/bin/env bash
# A/B control-authority switch on the real RIC path: xDevSM PRB-control xApps
# (prb-xapp-a / prb-xapp-b) -> RMR -> OSC E2Term -> E2 -> srsRAN gNB.
# MANATEE's sender-side mechanism: the existing E2Term RMR VirtualService gets a
# leading rule that routes the revoked xApp (sourceLabels xapp=<name>) to an
# empty subset, and a DestinationRule scoped to the PRB xApps bounds every
# xApp->E2Term connection to 1 s so the established RMR connection is cut.
#   MODE=manatee  (default) sender-side route + 1 s connection lifetime
#   MODE=nolife   sender-side route only (no connection lifetime bound)
#   MODE=none     no mechanism: both xApps hold control (native RIC behaviour)
#   TPUT=1 also records UE downlink throughput (ue_tput.sh) across the run.
#   ab_switch_real.sh <rep>   (results: ~/manatee-rev/results/oib/ab[-MODE]/rep<k>)
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
REP=$1; MODE=${MODE:-manatee}
SUFFIX=""; [ "$MODE" != manatee ] && SUFFIX="-$MODE"; [ -n "${TPUT:-}" ] && SUFFIX="$SUFFIX-tput"
OUT=${RESULTS:-$HOME/manatee-rev/results}/oib/ab$SUFFIX/rep$REP; mkdir -p "$OUT"
E2T=service-ricplt-e2term-rmr-alpha.ricplt.svc.cluster.local
EV=$OUT/events.csv; echo "t,event,detail" > $EV
ev() { echo "$(date +%s.%N),$1,${2:-}" >> $EV; }

apply_dr() {
  kubectl apply -f - >/dev/null <<YAML
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: e2term-ab, namespace: ricxapp}
spec:
  host: $E2T
  workloadSelector: {matchLabels: {app: prb-xapp}}
  trafficPolicy:
    connectionPool: {tcp: {maxConnectionDuration: 1s}}
  subsets:
  - {name: all, labels: {app: ricplt-e2term-alpha}}
  - {name: blocked, labels: {app: ricplt-e2term-alpha, manatee-blocked: "true"}}
YAML
}

block() {  # block <xapp-name>: revoke its control authority
  kubectl apply -f - >/dev/null <<YAML
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: ric-rmr-e2term-vs, namespace: ricplt}
spec:
  hosts: [$E2T]
  tcp:
  - match: [{port: 38000, sourceLabels: {xapp: $1}}]
    route: [{destination: {host: $E2T, subset: blocked, port: {number: 38000}}}]
  - match: [{port: 38000}]
    route: [{destination: {host: $E2T, port: {number: 38000}}}]
YAML
}

restore_vs() {  # original platform VirtualService: back it up before the first run
  kubectl apply -f - >/dev/null <<YAML
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: ric-rmr-e2term-vs, namespace: ricplt}
spec:
  hosts: [$E2T]
  tcp:
  - match: [{port: 38000}]
    route: [{destination: {host: $E2T, port: {number: 38000}}}]
YAML
}

kubectl -n ricxapp delete dr e2term-ab --ignore-not-found >/dev/null
restore_vs
[ "$MODE" = manatee ] && apply_dr
[ "$MODE" != none ] && { block prb-xapp-b; ev blocked prb-xapp-b; }
# Restart both xApps without overlap: with a rolling restart the old pod
# deregisters the xApp name from the xApp Manager after the new one registered.
kubectl -n ricxapp scale deploy/prb-xapp-a deploy/prb-xapp-b --replicas=0 >/dev/null
kubectl -n ricxapp wait --for=delete pod -l app=prb-xapp --timeout=120s >/dev/null 2>&1 || true
kubectl -n ricxapp scale deploy/prb-xapp-a deploy/prb-xapp-b --replicas=1 >/dev/null
kubectl -n ricxapp rollout status deploy/prb-xapp-a deploy/prb-xapp-b --timeout=180s >/dev/null
# Both xApps must be registered and routed (RIC_CONTROL_REQ -> E2Term) before the run.
for i in $(seq 1 30); do
  routes=$(kubectl -n ricplt exec deploy/deployment-ricplt-rtmgr -c container-ricplt-rtmgr -- \
    curl -s http://localhost:3800/ric/v1/getdebuginfo | { grep -o 'mse|12040,service-ricxapp-prb-xapp-[ab]' || true; } | sort -u | wc -l)
  [ "$routes" = 2 ] && break
  sleep 5
done
[ "$routes" = 2 ] || { echo "xApps not routed (routes=$routes)" >&2; exit 2; }
ev routed
UE=$(kubectl -n simran-ue get pod -l app=srsue-ue-0 -o jsonpath='{.items[0].metadata.name}')
TPUT_URL=${TPUT_URL:-http://$(kubectl -n simran-open5gs get svc oran-http-server -o jsonpath='{.spec.clusterIP}'):8080/big.bin}
if [ -n "${TPUT:-}" ]; then
  kubectl -n simran-ue cp "$(dirname "$0")/ue_tput.sh" $UE:/tmp/ue_tput.sh -c ue
  kubectl -n simran-ue exec $UE -c ue -- bash /tmp/ue_tput.sh start "$TPUT_URL"
  ev tput_start
fi
sleep 30                      # first controls
ev phase_a_start
sleep 30
ev switch_start
[ "$MODE" != none ] && block prb-xapp-a
ev switch_applied
sleep 40
ev end
if [ -n "${TPUT:-}" ]; then
  kubectl -n simran-ue exec $UE -c ue -- bash /tmp/ue_tput.sh stop
  kubectl -n simran-ue exec $UE -c ue -- cat /tmp/ue_tput.csv > $OUT/ue-tput.csv
fi
for x in prb-xapp-a prb-xapp-b; do
  kubectl -n ricxapp logs deploy/$x -c $x --since=5m | grep '^ABLOG' > $OUT/$x.ablog || true
done
kubectl -n simran-ran exec deploy/srsran-gnb -c gnb -- sh -c \
  "grep -A3 'Slice-level PRB quota Control Request' /tmp/gnb.log | grep -E 'Control Request|Min PRB'" > $OUT/gnb-prb.log || true
restore_vs
kubectl -n ricxapp delete dr e2term-ab --ignore-not-found >/dev/null
echo "$OUT"
