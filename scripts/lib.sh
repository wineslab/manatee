#!/usr/bin/env bash
# Shared helpers for the revision experiments. Source from the k8s/ directory.
export KUBECONFIG=${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}
for d in "$HOME"/istio-*/bin "$HOME/.local/bin"; do [ -d "$d" ] && PATH=$d:$PATH; done
export PATH
# REV_ROOT: code tree (frozen copy during campaigns); RESULTS: output root.
REV_ROOT=${REV_ROOT:-$HOME/manatee-rev}
RESULTS=${RESULTS:-$HOME/manatee-rev/results}
export REV_ROOT RESULTS
NS=manatee-exp
# PIN_NODE: on multi-node clusters keep every experiment pod (and the
# hostPath data directory) on one node.
if [ -n "${PIN_NODE:-}" ]; then
  NODE_SELECTOR="{\"kubernetes.io/hostname\": \"$PIN_NODE\"}"
else
  NODE_SELECTOR="{}"
fi
export NODE_SELECTOR
export LOADGEN_RESTART=${LOADGEN_RESTART:-Never}
# Never: one attempt (a rerun would overwrite the CSVs); OnFailure: retry init races.
[ "$LOADGEN_RESTART" = OnFailure ] && export LOADGEN_BACKOFF=3 || export LOADGEN_BACKOFF=0
DATA=/var/lib/manatee-exp/current
K8S_DIR=${K8S_DIR:-$REV_ROOT/k8s}

now() { date +%s.%N; }

log_event() {  # log_event <events.csv> <name> [detail]
  echo "$(now),$2,${3:-}" >> "$1"
}

reset_jobs() {
  kubectl -n $NS delete job -l app=loadgen --ignore-not-found --wait >/dev/null
  kubectl -n $NS wait --for=delete pod -l app=loadgen --timeout=60s >/dev/null 2>&1 || true
}

setup_base() {  # namespace, service accounts, sink and Services
  kubectl apply -f $K8S_DIR/base.yaml >/dev/null
  mesh_ns_setup
  kubectl -n $NS patch deploy sink --type merge \
    -p "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":$NODE_SELECTOR}}}}" >/dev/null
  kubectl -n $NS rollout status deploy/sink --timeout=120s >/dev/null
}

restart_sink() {
  kubectl -n $NS rollout restart deploy/sink >/dev/null
  kubectl -n $NS rollout status deploy/sink --timeout=90s >/dev/null
}

CHART=${CHART:-$REV_ROOT/charts/xapp-sim}

helm_xapp() {  # helm_xapp <release> <version> <prb_ratio> [fault_mode] [fault_after_s] [fault_delay_ms] [replicas]
  helm upgrade --install "$1" "$CHART" -n $NS --wait --timeout 180s \
    --set version=$2 --set prbRatio=$3 --set fault.mode=${4:-none} \
    --set fault.afterS=${5:-0} --set fault.delayMs=${6:-0} --set replicas=${7:-1} \
    --set-json "nodeSelector=$NODE_SELECTOR" >/dev/null
}

deploy_xapp() {  # deploy_xapp <version> <prb_ratio> [fault_mode] [fault_after_s] [fault_delay_ms]
  helm_xapp xapp-$1 "$@"
}

undeploy_xapp() {  # undeploy_xapp <release>
  helm uninstall "$1" -n $NS --wait --timeout 120s >/dev/null 2>&1 || true
}

clean_xapps() {  # remove every xApp release and any pre-Helm deployment
  for r in $(helm list -n $NS -q); do undeploy_xapp "$r"; done
  kubectl -n $NS delete deploy -l app=xapp --ignore-not-found --wait >/dev/null
  kubectl -n $NS wait --for=delete pod -l app=xapp --timeout=90s >/dev/null 2>&1 || true
}

mesh_routing_off() {  # plain Service routing (round robin per connection)
  kubectl -n $NS delete vs xapp --ignore-not-found >/dev/null
  kubectl -n $NS delete dr xapp --ignore-not-found >/dev/null
}

start_loadgen() {  # start_loadgen <run> <target> <rate> <duration> [msgs_per_conn]
  RUN=$1 TARGET=$2 RATE=$3 DURATION=$4 MPC=${5:-1} \
    envsubst < $K8S_DIR/loadgen-job.yaml.tpl | kubectl apply -f - >/dev/null
}

wait_loadgen_running() {  # wait until every loadgen pod reports Ready
  kubectl -n $NS wait --for=condition=ready pod -l app=loadgen --timeout=90s >/dev/null
}

wait_loadgen_done() {  # wait_loadgen_done <timeout_s> <run>...
  local t=$1; shift
  for r in "$@"; do
    kubectl -n $NS wait --for=condition=complete job/loadgen-$r --timeout=${t}s >/dev/null
  done
}

set_fault() {  # set_fault <version> <mode> [after_s] [delay_ms]
  kubectl -n $NS exec deploy/xapp-v1 -c xapp -- python3 -c "
import urllib.request, json
req = urllib.request.Request('http://xapp-$1:8080/fault',
    data=json.dumps({'mode': '$2', 'after_s': ${3:-0}, 'delay_ms': ${4:-0}}).encode(),
    headers={'Content-Type': 'application/json'})
print(urllib.request.urlopen(req).read().decode())" 2>/dev/null
}

run_canary() {  # run_canary <steps-json> <hold_s> : MANATEE Ansible pipeline
  ${ANSIBLE_PLAYBOOK:-ansible-playbook} $REV_ROOT/ansible/canary.yml \
    -e "steps=$1" -e hold_s=$2 > $DATA/ansible.log 2>&1
}

istio_weights() {  # istio_weights <w1> <w2>
  W1=$1 W2=$2 envsubst < $K8S_DIR/istio-canary.yaml.tpl | kubectl apply -f - >/dev/null
}


# Data-plane specific operations (set_weights, ab_block, ...).
source "$REV_ROOT/scripts/mesh.sh"

collect() {  # collect <dest_dir> : move CSVs of the run out of the shared hostPath
  sudo -n mkdir -p "$1"
  # Copy then unlink: the sink keeps its files open, and a plain mv would let
  # it append the next run's commands to this run's copy.
  sudo -n sh -c "cp $DATA/*.csv $DATA/*.log '$1'/ 2>/dev/null; rm -f $DATA/*.csv $DATA/*.log; true"
  sudo -n chown -R "$(id -u):$(id -g)" "$RESULTS"
}
