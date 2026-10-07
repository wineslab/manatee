#!/usr/bin/env bash
# Run on the experiment driver: copy the experiment tree to a target
# VM, rebuild the harness image there and import it into k3s.
# Usage: sync_and_build.sh <ssh-host> [--no-build]
set -euo pipefail
HOST=$1
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ssh "$HOST" 'mkdir -p ~/manatee-rev'
tar czf - -C "$ROOT" harness k8s scripts ansible charts 2>/dev/null | ssh "$HOST" 'tar xzf - -C ~/manatee-rev'
if [ "${2:-}" != "--no-build" ]; then
  ssh "$HOST" 'cd ~/manatee-rev/harness && docker build -q -t manatee-harness:0.1 . >/dev/null &&
    docker save manatee-harness:0.1 | sudo -n k3s ctr images import - >/dev/null &&
    (kubectl -n manatee-exp rollout restart deploy >/dev/null 2>&1 || true) &&
    (kubectl -n manatee-exp rollout status deploy --timeout=120s >/dev/null 2>&1 || true) &&
    echo "image rebuilt on $(hostname)"'
fi
