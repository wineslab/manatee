#!/usr/bin/env bash
# Build the harness image on this k3s server and import it on every node
# reachable over SSH (multi-node cluster).
#   build_local_multinode.sh <ssh-host>...
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TAR=$(mktemp --suffix .tar)
docker build -q -t manatee-harness:0.1 "$ROOT/harness" >/dev/null
docker save manatee-harness:0.1 -o "$TAR"
sudo -n k3s ctr images import "$TAR" >/dev/null
for h in "$@"; do ssh "$h" 'sudo -n k3s ctr images import -' < "$TAR" >/dev/null; done
rm -f "$TAR"
echo "imported on $(hostname) $*"
