# Findings and caveats

These findings came up while building and running the experiments. They
matter to anyone reproducing them or building on the mechanisms.

## Service mesh and RIC behaviour

1. **Outlier detection does not work on opaque TCP between sidecars.** Istio
   outlier detection does not eject a failing xApp there. The server-side
   sidecar accepts every connection, so the client side never sees a connect
   failure. In our probe, 50 % of messages timed out for 40 s with no
   ejection. The circuit breaker is therefore MANATEE's telemetry-driven
   controller (`harness/gate.py`, `ansible/canary.yml`).
2. **Authorization changes do not touch connections that are already open.**
   After an Istio `AuthorizationPolicy` change, a revoked xApp kept issuing
   control indefinitely (92 conflicting commands in 40 s). Bounding the
   connection lifetime with
   `DestinationRule.trafficPolicy.connectionPool.tcp.maxConnectionDuration`
   (1 s) forces re-authorization: after about 1 s, 0 commands from the
   revoked version and 0 collisions.
3. **Istio circuit breakers cannot be opened on demand.**
   `connectionPool.tcp.maxConnections: 0` is treated as unset (unlimited). An
   EnvoyFilter setting the Envoy threshold `max_connections: 0` is appended
   after the threshold Istio generates, so Envoy ignores it. Both leave the
   revoked xApp in control (`scripts/probe_cb_switch.sh`,
   `MODE=dr|envoyfilter`).
4. **Mechanisms that do revoke control authority.** Each needs a 1 s
   `maxConnectionDuration` with Istio:
   - sender-side routing of the revoked xApp to an empty subset
     (`MODE=route`, MANATEE's choice);
   - a receiver-side AuthorizationPolicy;
   - a DestinationRule-only variant: plaintext from the revoked xApp against
     a receiver that requires mutual TLS (`MODE=drtls`).

   Without the lifetime bound, every variant leaves the revoked xApp in
   control. Linkerd and Cilium close established connections on a policy
   change and need no lifetime bound.
5. **Istio ambient: attach the policy to the waypoint.** A workload-selector
   AuthorizationPolicy on the receiver is bypassed when traffic goes through
   the namespace waypoint, because the receiver sees the waypoint's identity.
   Attach the policy to the waypoint with `targetRefs`. Right after namespace
   enrolment the waypoint is not yet in the path, so routes do not apply for
   a few seconds.
6. **Cilium cannot split plain TCP by weight.** Cilium 1.18 has no Gateway API
   TCPRoute/GAMMA support for plain TCP, and CiliumEnvoyConfig requires
   kube-proxy replacement. Cilium therefore takes part in the A/B and overhead
   scenarios only.
7. **Acknowledgements do not show which xApp holds control.** With two control
   xApps, the O-RAN SC Routing Manager installs one unqualified route per xApp
   for RIC Control Acknowledge/Failure (12041/12042). Each acknowledgement
   reaches one of the xApps regardless of which xApp sent the request. The
   real-RAN experiment therefore uses the PRB policy applied at the gNB.

## Experiment design

8. **Drop stale control decisions.** While control authority is revoked, the
   xApp must drop stale control decisions. Otherwise it replays a backlog when
   re-enabled (169 commands in 1 s in our first probe). The mock xApp drops
   decisions older than 1 s.
9. **Do not open a connection per message.** A new connection per message
   costs one mTLS handshake per message and saturates near 500 msg/s (about
   7.5 % failures). With 20 messages per connection, the same setup sustains
   1000 msg/s with 0 errors and p95 below 1.1 ms. The 600 msg/s "TCP
   saturation" reported in the first version of the paper came from the
   test client.

## Data caveats

- **Sink files in early E5 runs.** Early runs moved the sink's open files at
  collection time, so later commands were appended to some
  `sink-msgs.csv`/`sink.csv`. `analysis/e4_summary.py` uses only each run's
  own 35 s window.
- **Loss counting in the first E1 campaign.** It recorded only the first
  failed message of a failed connection. `analysis/e1_summary.py` computes
  losses as sent minus answered, which is exact either way.
- **Native baselines get help.** Native release mechanisms in E1/E2 get the
  same telemetry gate and automated rollback as MANATEE. This favours them;
  in practice the rollback would be manual. Their monitor starts one gate
  window (10 s) after the release, so their detection times include that
  settle time.
