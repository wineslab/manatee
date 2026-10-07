#!/usr/bin/env bash
# Data-plane abstraction for E5. Sourced by lib.sh; MESH selects the
# implementation, everything else (xApps, load, gate, pipeline) is identical.
#   istio      Istio sidecars, VirtualService weights (MANATEE default)
#   istio-gw   Istio sidecars, Gateway API TCPRoute weights
#   ambient    Istio ambient (ztunnel + waypoint), TCPRoute weights
#   linkerd    Linkerd proxies, TCPRoute weights
#   cilium     Cilium eBPF (A/B and overhead only, no weighted L4 split)
#   none       plain Kubernetes Service (native baselines)
MESH=${MESH:-istio}

mesh_ns_setup() {
  # One key per call: kubectl rejects the whole command if any key is absent.
  for l in istio-injection istio.io/dataplane-mode istio.io/use-waypoint; do
    kubectl label ns $NS $l- >/dev/null 2>&1 || true
  done
  kubectl annotate ns $NS linkerd.io/inject- >/dev/null 2>&1 || true
  if [ $MESH != ambient ]; then
    kubectl -n $NS delete gateway waypoint --ignore-not-found >/dev/null 2>&1 || true
  fi
  case $MESH in
    istio|istio-gw) kubectl label ns $NS istio-injection=enabled --overwrite >/dev/null ;;
    ambient)
      kubectl label ns $NS istio.io/dataplane-mode=ambient --overwrite >/dev/null
      istioctl waypoint apply -n $NS --enroll-namespace --wait >/dev/null ;;
    linkerd) kubectl annotate ns $NS linkerd.io/inject=enabled --overwrite >/dev/null ;;
  esac
}

set_weights() {  # set_weights <w1> <w2>
  case $MESH in
    istio) W1=$1 W2=$2 envsubst < $K8S_DIR/istio-canary.yaml.tpl | kubectl apply -f - >/dev/null ;;
    istio-gw|ambient|linkerd)
      W1=$1 W2=$2 envsubst < $K8S_DIR/gw-tcproute.yaml.tpl | kubectl apply -f - >/dev/null ;;
    # Cilium 1.18 offers no weighted L4 split without kube-proxy replacement
    # (CiliumEnvoyConfig); only an equal split via Service endpoints exists.
    cilium|none)
      [ "$1" = 50 ] || [ "$1" = 100 ] || { echo "MESH=$MESH cannot apply weights $1/$2" >&2; return 1; } ;;
  esac
}

ab_block() {  # ab_block <version> : revoke control authority of that version
  local allowed=v1; [ "$1" = v1 ] && allowed=v2
  case $MESH in
    istio|istio-gw)
      BLOCKED=$1 envsubst < $K8S_DIR/istio-ab-authority.yaml.tpl | kubectl apply -f - >/dev/null ;;
    ambient)
      # VARIANT=selectorpolicy reproduces the workload-selector policy, which
      # the waypoint path silently bypasses (kept as a documented pitfall).
      if [ "${VARIANT:-}" = selectorpolicy ]; then
        BLOCKED=$1 envsubst < $K8S_DIR/istio-ab-authority.yaml.tpl | kubectl apply -f - >/dev/null
      else
        BLOCKED=$1 envsubst < $K8S_DIR/istio-ab-authority-ambient.yaml.tpl | kubectl apply -f - >/dev/null
      fi ;;
    linkerd)
      ALLOWED=$allowed envsubst < $K8S_DIR/linkerd-ab-authority.yaml.tpl | kubectl apply -f - >/dev/null ;;
    cilium)
      BLOCKED=$1 envsubst < $K8S_DIR/cilium-ab-authority.yaml.tpl | kubectl apply -f - >/dev/null ;;
  esac
}

ab_conn_limit() {  # ab_conn_limit <seconds|""> : Istio connection-pool circuit breaker
  # Always on for sidecars (MANATEE configuration); for ambient only in the
  # VARIANT=connlimit runs, where the waypoint enforces the connection lifetime.
  local mesh=$MESH
  [ "$MESH" = ambient ] && [ "${VARIANT:-}" = connlimit ] && mesh=istio
  case $mesh in
    istio|istio-gw)
      if [ -n "$1" ]; then
        MAX_CONN_S=$1 envsubst < $K8S_DIR/istio-ab-sink-dr.yaml.tpl | kubectl apply -f - >/dev/null
      else
        kubectl -n $NS delete dr sink --ignore-not-found >/dev/null
      fi ;;
  esac
}
