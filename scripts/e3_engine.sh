#!/usr/bin/env bash
# E3: the same canary (steps 10/25/50/75/100 %, 20 s holds, identical
# telemetry gate and rollback) driven by different orchestration engines.
#
#   e3_engine.sh <engine> <fault> <rep>
#     engine  ansible         MANATEE (Ansible playbook)
#             tekton          Tekton Pipeline, one TaskRun per step (AutoRAN-style CI)
#             argocd-webhook  GitOps: commit weights, ArgoCD refresh on push (5G-CT-style)
#             argocd-poll     GitOps: commit weights, ArgoCD default reconciliation
#             argo-rollouts   Argo Rollouts canary with background analysis
#     fault   none | error
#
# A watcher timestamps every VirtualService weight change seen by the API
# server, so engine actuation time is measured the same way for every engine.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
source "$REV_ROOT/engines/argocd/gitops.sh"
ENGINE=$1; FAULT=$2; REP=$3
RATE=${RATE:-1000}; MPC=${MPC:-10}; HOLD=20
OUT=$RESULTS/e3/$ENGINE/$FAULT/rep$REP
EV=$DATA/events.csv
case $ENGINE in argocd-poll) LOAD_S=1300 ;; *) LOAD_S=220 ;; esac
GATE="python3 $REV_ROOT/harness/gate.py --interval 2 --window 10s --max-error-ratio 0.01 --max-p95-ms 50"

cleanup_engines() {
  kubectl -n argocd delete application xapp-canary --cascade=orphan --ignore-not-found >/dev/null
  kubectl -n $NS delete rollout xapp --ignore-not-found --wait >/dev/null
  kubectl -n $NS delete analysisrun --all --ignore-not-found >/dev/null
  kubectl -n manatee-ci delete pipelinerun --all --ignore-not-found >/dev/null
  kubectl -n $NS delete vs xapp --ignore-not-found >/dev/null
  kubectl -n $NS delete dr xapp --ignore-not-found >/dev/null
}

render_rollout() {  # render_rollout <version> <fault>
  VERSION=$1 PRB_RATIO=30 FAULT_MODE=$2 \
    envsubst < $REV_ROOT/engines/argo-rollouts/rollout.yaml.tpl | kubectl apply -f - >/dev/null
}

vs_weight() { kubectl -n $NS get vs xapp -o jsonpath='{.spec.tcp[0].route[1].weight}' 2>/dev/null; }

wait_vs_weight() {  # wait_vs_weight <w2> <timeout_s>
  local end=$(( $(date +%s) + $2 ))
  while [ "$(vs_weight)" != "$1" ]; do
    [ "$(date +%s)" -ge $end ] && return 1
    sleep 0.2
  done
}

reset_jobs
clean_xapps
cleanup_engines
MESH=istio setup_base
sudo -n rm -f $DATA/*.csv $DATA/*.log
echo "t,event,detail" > $EV
case $ENGINE in
  argo-rollouts)
    render_rollout v1 none
    kubectl -n $NS wait --for=jsonpath='{.status.phase}'=Healthy rollout/xapp --timeout=180s >/dev/null ;;
  *)
    deploy_xapp v1 30
    deploy_xapp v2 70 $FAULT 0 150
    istio_weights 100 0 ;;
esac
if [[ $ENGINE == argocd-* ]]; then
  gitops_init
  kubectl apply -f $REV_ROOT/engines/argocd/application.yaml >/dev/null
  kubectl -n argocd wait --for=jsonpath='{.status.sync.status}'=Synced application/xapp-canary --timeout=120s >/dev/null
fi

# API-server view of the canary weight, and engine resource usage.
python3 $REV_ROOT/harness/watch_ts.py $EV vs_weight -- \
  kubectl -n $NS get vs xapp -w -o jsonpath='{.spec.tcp[0].route[1].weight}{"\n"}' \
  </dev/null >/dev/null 2>&1 &
WATCH=$!
( echo "t,namespace,pod,cpu_m,mem_mi" > $DATA/engine-usage.csv
  while true; do
    t=$(now)
    for ns in argocd tekton-pipelines argo-rollouts gitops manatee-ci; do
      kubectl top pod -n $ns --no-headers 2>/dev/null |
        awk -v t=$t -v ns=$ns '{gsub("m","",$2); gsub("Mi","",$3); print t","ns","$1","$2","$3}'
    done >> $DATA/engine-usage.csv
    sleep 5
  done ) </dev/null >/dev/null 2>&1 &
USAGE=$!
trap 'kill $WATCH $USAGE 2>/dev/null || true' EXIT

start_loadgen e3 xapp.$NS:9000 $RATE $LOAD_S $MPC
wait_loadgen_running
log_event $EV loadgen_running
sleep 20
log_event $EV release_start

case $ENGINE in
  ansible)
    run_canary '[10,25,50,75,100]' $HOLD || true ;;
  tekton)
    kubectl create -f - >/dev/null <<EOF
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata: {generateName: xapp-canary-, namespace: manatee-ci}
spec:
  pipelineRef: {name: xapp-canary}
  params: [{name: hold, value: "$HOLD"}]
  taskRunTemplate:
    serviceAccountName: canary-runner
    podTemplate: {nodeSelector: $NODE_SELECTOR}
EOF
    until s=$(kubectl -n manatee-ci get pipelinerun -o jsonpath='{.items[0].status.conditions[0].status}') &&
          [ "$s" = True ] || [ "$s" = False ]; do sleep 1; done ;;
  argocd-webhook|argocd-poll)
    mode=${ENGINE#argocd-}
    failed=0
    for w2 in 10 25 50 75 100; do
      log_event $EV step_request $w2
      gitops_set_weights $((100 - w2)) $w2 $mode
      wait_vs_weight $w2 600 && log_event $EV step $w2
      if $GATE --hold $HOLD > $DATA/gate.log 2>&1; then
        log_event $EV gate_pass $w2
      else
        log_event $EV gate_fail $w2; failed=1; break
      fi
    done
    if [ $failed = 1 ]; then
      log_event $EV rollback_applied_request 0
      gitops_set_weights 100 0 $mode
      wait_vs_weight 0 600 && log_event $EV rollback_applied 0
    else
      log_event $EV promoted
    fi ;;
  argo-rollouts)
    render_rollout v2 $FAULT
    until p=$(kubectl -n $NS get rollout xapp -o jsonpath='{.status.phase}') &&
          { [ "$p" = Healthy ] && [ "$(kubectl -n $NS get rollout xapp -o jsonpath='{.status.stableRS}')" = \
              "$(kubectl -n $NS get rollout xapp -o jsonpath='{.status.currentPodHash}')" ]; } || [ "$p" = Degraded ]; do
      sleep 1
    done
    [ "$p" = Degraded ] && log_event $EV rollback_applied || log_event $EV promoted ;;
esac
log_event $EV release_done

wait_loadgen_done 1500 e3
kill $WATCH $USAGE 2>/dev/null || true
kubectl -n manatee-ci get pipelinerun -o yaml > $DATA/pipelinerun.log 2>/dev/null || true
kubectl -n $NS get rollout xapp -o yaml > $DATA/rollout.log 2>/dev/null || true
collect "$OUT"
echo "$OUT"
