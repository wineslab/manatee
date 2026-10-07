#!/usr/bin/env bash
# set_weights.sh <w1> <w2> : apply canary weights through the data plane
# selected by MESH (see mesh.sh). Called by the Ansible pipeline.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
set_weights "$1" "$2"
