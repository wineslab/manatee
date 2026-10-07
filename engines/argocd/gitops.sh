#!/usr/bin/env bash
# Helpers for the GitOps engine: the driver commits the desired weights and,
# in "webhook" mode, asks ArgoCD to refresh at once (what a Git webhook does);
# in "poll" mode it waits for ArgoCD's own reconciliation loop.
# Credentials of the throwaway in-cluster Gitea created by k8s/engines/gitea.yaml.
GITEA_USER=${GITEA_USER:-manatee}; GITEA_PASS=${GITEA_PASS:-manatee-exp-local}
GIT_URL=${GIT_URL:-http://$GITEA_USER:$GITEA_PASS@$(kubectl -n gitops get svc gitea -o jsonpath='{.spec.clusterIP}'):3000/manatee/xapp-canary.git}
GIT_WORK=${GIT_WORK:-/tmp/manatee-gitops-work}

gitops_init() {  # create the repository with weights 100/0
  local ip; ip=$(kubectl -n gitops get svc gitea -o jsonpath='{.spec.clusterIP}')
  curl -sf -u $GITEA_USER:$GITEA_PASS -X DELETE "http://$ip:3000/api/v1/repos/manatee/xapp-canary" >/dev/null || true
  curl -sf -u $GITEA_USER:$GITEA_PASS -H 'Content-Type: application/json' \
    -d '{"name":"xapp-canary","private":false,"default_branch":"main"}' \
    "http://$ip:3000/api/v1/user/repos" >/dev/null
  rm -rf "$GIT_WORK"; mkdir -p "$GIT_WORK"; cd "$GIT_WORK" || return 1
  git init -q -b main && git config user.email manatee@example.invalid && git config user.name manatee
  W1=100 W2=0 envsubst < "$K8S_DIR/istio-canary.yaml.tpl" > xapp-routing.yaml
  git add . && git commit -qm "weights 100/0" && git remote add origin "$GIT_URL" && git push -q origin main
  cd - >/dev/null
}

gitops_set_weights() {  # gitops_set_weights <w1> <w2> <mode: webhook|poll>
  ( cd "$GIT_WORK" && W1=$1 W2=$2 envsubst < "$K8S_DIR/istio-canary.yaml.tpl" > xapp-routing.yaml &&
    git commit -qam "weights $1/$2" && git push -q origin main )
  if [ "$3" = webhook ]; then
    kubectl -n argocd annotate application xapp-canary argocd.argoproj.io/refresh=normal --overwrite >/dev/null
  fi
}
