#!/bin/bash
# Runs inside the srsUE pod: continuous downlink (HTTP download of the
# simulated-ran-e2e test server's file through tun_srsue) and a 0.5 s sampler
# of the tun interface rx byte counter.  ue_tput.sh start <url> | stop
# Both loops are detached (setsid, no inherited stdio) so kubectl exec returns.
# stop matches the loops by their command line (this script's own command line,
# "bash /tmp/ue_tput.sh stop", does not contain the patterns); start always
# stops leftovers first, so exactly one downlink and one sampler run at a time.
stop_all() {
  pkill -f 'statistics/rx_bytes' 2>/dev/null
  pkill -f 'curl --interface tun_srsue' 2>/dev/null
  sleep 0.2
}
case $1 in
  start)
    stop_all
    setsid bash -c 'while true; do curl --interface tun_srsue -s -o /dev/null --max-time 600 "$0"; done' \
      "$2" </dev/null >/dev/null 2>&1 &
    setsid bash -c 'prev=$(cat /sys/class/net/tun_srsue/statistics/rx_bytes)
      while true; do sleep 0.5; b=$(cat /sys/class/net/tun_srsue/statistics/rx_bytes)
        echo "$(date +%s.%N),$(( b - prev ))"; prev=$b; done' </dev/null >/tmp/ue_tput.csv 2>/dev/null &
    ;;
  stop)
    stop_all ;;
esac
