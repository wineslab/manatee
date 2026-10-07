#!/usr/bin/env bash
# Run an experiment campaign from a frozen copy of the code tree so the tree
# can keep changing while it runs. Repetitions are the outer loop so slow
# drift of the VM affects every configuration equally.
#   campaign.sh <name> <reps> <script> <arg-sets...>
#   e.g. campaign.sh e1 5 e1_release.sh "manatee none 100" "native-bbm none 100"
set -uo pipefail
NAME=$1; REPS=$2; SCRIPT=$3; shift 3
FROZEN=$HOME/manatee-rev-frozen/$NAME-$(date +%Y%m%d-%H%M%S)
mkdir -p "$(dirname "$FROZEN")"
rsync -a --exclude results --exclude venv "$HOME/manatee-rev/" "$FROZEN/"
export REV_ROOT=$FROZEN RESULTS=$HOME/manatee-rev/results
LOG=$RESULTS/$NAME-campaign.log
mkdir -p "$RESULTS"
echo "$(date -Is) start $NAME reps=$REPS frozen=$FROZEN" >> "$LOG"
for rep in $(seq 1 "$REPS"); do
  for args in "$@"; do
    # shellcheck disable=SC2086
    if out=$(bash "$FROZEN/scripts/$SCRIPT" $args $rep 2>&1 | tail -1); then
      echo "$(date -Is) ok   $args rep$rep $out" >> "$LOG"
    else
      echo "$(date -Is) FAIL $args rep$rep $out" >> "$LOG"
    fi
  done
done
echo "$(date -Is) done $NAME" >> "$LOG"
