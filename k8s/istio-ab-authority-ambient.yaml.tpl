# Ambient variant of the A/B control-authority gate. Traffic to the sink goes
# through the namespace waypoint, so the sink's ztunnel only sees the
# waypoint's identity: the policy must be attached to the waypoint
# (targetRefs on the sink Service) to match the xApp service account.
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata: {name: ab-authority, namespace: manatee-exp}
spec:
  targetRefs:
  - {kind: Service, group: "", name: sink}
  action: DENY
  rules:
  - from:
    - source: {principals: ["cluster.local/ns/manatee-exp/sa/xapp-${BLOCKED}"]}
