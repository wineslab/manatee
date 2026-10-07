#!/usr/bin/env bash
# A/B control-authority switch implemented as a circuit breaker on the xApp's
# outbound (RMR-like) control path, instead of an AuthorizationPolicy on the
# receiver. Everything is enforced in the sending xApp's own sidecar
# (workloadSelector), which is where an RMR sender's TCP connection to E2Term
# leaves the pod.
#
#   MODE=dr           DestinationRule connectionPool.tcp.maxConnections 0 for
#                     the xApp without authority, unlimited for the holder
#   MODE=envoyfilter  Envoy circuit_breakers threshold max_connections 0 on the
#                     sidecar's outbound sink cluster (EnvoyFilter); the
#                     DestinationRule only bounds connection lifetime
#   MODE=drtls        DestinationRule only: the receiver requires mTLS
#                     (PeerAuthentication STRICT) and the revoked xApp's
#                     DestinationRule disables TLS, so its connections fail
#   MODE=route        VirtualService on the sink host routes the revoked
#                     xApp (sourceLabels) to an empty subset, so its
#                     connections fail at its own sidecar (no healthy upstream)
# RMR keeps its TCP connection open, so maxConnectionDuration bounds how long
# an established connection survives a breaker change.
#
#   MODE=envoyfilter probe_cb_switch.sh <lifetime_s|none> <rep>
set -euo pipefail
source "$(dirname "$0")/lib.sh"
LIFETIME=$1; REP=$2; MODE=${MODE:-dr}
OUT=$RESULTS/cbtest/$MODE-life$LIFETIME/rep$REP
EV=$DATA/events.csv

dr_yaml() {  # dr_yaml <version> <max_connections>
  local life=""
  [ "$LIFETIME" != none ] && life="maxConnectionDuration: ${LIFETIME}s, "
  cat <<EOF
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: cb-$1, namespace: $NS}
spec:
  host: sink.$NS.svc.cluster.local
  workloadSelector: {matchLabels: {version: $1}}
  trafficPolicy:
    connectionPool: {tcp: {${life}maxConnections: $2, connectTimeout: 500ms}}
EOF
}

envoyfilter_yaml() {  # envoyfilter_yaml <version>
  cat <<EOF
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata: {name: cb-open-$1, namespace: $NS}
spec:
  workloadSelector: {labels: {version: $1}}
  configPatches:
  - applyTo: CLUSTER
    match:
      context: SIDECAR_OUTBOUND
      cluster: {service: sink.$NS.svc.cluster.local, portNumber: 9100}
    patch:
      operation: MERGE
      value:
        circuit_breakers:
          thresholds:
          - {priority: DEFAULT, max_connections: 0, max_pending_requests: 0, max_requests: 0}
EOF
}

route_yaml() {  # route_yaml <blocked-version>
  local life=""
  # Istio rejects an empty trafficPolicy, so the field is only set with a lifetime.
  [ "$LIFETIME" != none ] && life="trafficPolicy: {connectionPool: {tcp: {maxConnectionDuration: ${LIFETIME}s}}}"
  cat <<EOF
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: sink-route, namespace: $NS}
spec:
  host: sink.$NS.svc.cluster.local
  $life
  subsets:
  - {name: all, labels: {app: sink}}
  - {name: blocked, labels: {app: sink, manatee-blocked: "true"}}
---
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: sink-route, namespace: $NS}
spec:
  hosts: [sink.$NS.svc.cluster.local]
  tcp:
  - match: [{sourceLabels: {version: $1}}]
    route: [{destination: {host: sink.$NS.svc.cluster.local, subset: blocked}}]
  - route: [{destination: {host: sink.$NS.svc.cluster.local, subset: all}}]
EOF
}

drtls_yaml() {  # drtls_yaml <version> <ISTIO_MUTUAL|DISABLE>
  local life=""
  [ "$LIFETIME" != none ] && life="connectionPool: {tcp: {maxConnectionDuration: ${LIFETIME}s}}, "
  cat <<EOF
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: cb-$1, namespace: $NS}
spec:
  host: sink.$NS.svc.cluster.local
  workloadSelector: {matchLabels: {version: $1}}
  trafficPolicy: {${life}tls: {mode: $2}}
EOF
}

breaker() {  # breaker <version> <open|closed>
  if [ "$MODE" = drtls ]; then
    # DestinationRule-only revocation: the receiver requires mTLS, so the
    # revoked xApp's sidecar, told to send plaintext, is rejected.
    if [ "$2" = open ]; then drtls_yaml $1 DISABLE; else drtls_yaml $1 ISTIO_MUTUAL; fi |
      kubectl apply -f - >/dev/null
    return 0
  fi
  if [ "$MODE" = route ]; then
    if [ "$2" = open ]; then route_yaml $1 | kubectl apply -f - >/dev/null; fi
    return 0
  fi
  if [ "$MODE" = dr ]; then
    if [ "$2" = open ]; then dr_yaml $1 0; else dr_yaml $1 1000000; fi | kubectl apply -f - >/dev/null
  else
    dr_yaml $1 1000000 | kubectl apply -f - >/dev/null
    if [ "$2" = open ]; then
      envoyfilter_yaml $1 | kubectl apply -f - >/dev/null
    else
      kubectl -n $NS delete envoyfilter cb-open-$1 --ignore-not-found >/dev/null
    fi
  fi
}

reset_jobs
kubectl -n $NS delete authorizationpolicy.security.istio.io,dr,vs,envoyfilter --all --ignore-not-found >/dev/null
sudo -n rm -f $DATA/*.csv $DATA/*.log
kubectl -n $NS delete peerauthentication --all --ignore-not-found >/dev/null
if [ "$MODE" = drtls ]; then
  kubectl apply -f - >/dev/null <<EOF
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata: {name: sink-strict, namespace: $NS}
spec:
  selector: {matchLabels: {app: sink}}
  mtls: {mode: STRICT}
EOF
fi
restart_sink
echo "t,event,detail" > $EV
breaker v1 closed
breaker v2 open
sleep 5
for v in v1 v2; do start_loadgen ab-$v xapp-$v.$NS:9000 100 70 10; done
wait_loadgen_running
log_event $EV loadgen_running
sleep 30
log_event $EV switch_start
breaker v1 open
breaker v2 closed
log_event $EV switch_applied
wait_loadgen_done 300 ab-v1 ab-v2
# Istio TCP metrics carry Envoy response flags: UO = upstream overflow (breaker
# open), DT = max connection duration reached.
for v in v1 v2; do
  kubectl -n $NS exec deploy/xapp-$v -c istio-proxy -- pilot-agent request GET stats 2>/dev/null |
    grep -E "^istiocustom.istio_tcp_connections_(opened|closed)_total" |
    grep "destination_service_name.sink" |
    sed -E "s/^istiocustom.(istio_tcp_connections_[a-z]+_total).*response_flags\.([^.]+)\..*: ([0-9]+)$/$v \1 flags=\2 \3/" \
    >> $DATA/envoy-stats.log || true
done
collect "$OUT"
echo "$OUT"
