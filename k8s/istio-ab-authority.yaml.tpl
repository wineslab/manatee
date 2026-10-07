# A/B control-authority gate: the sink (E2 control path) rejects connections
# from the xApp version that is NOT in control. Rendered with BLOCKED.
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata: {name: ab-authority, namespace: manatee-exp}
spec:
  selector: {matchLabels: {app: sink}}
  action: DENY
  rules:
  - from:
    - source: {principals: ["cluster.local/ns/manatee-exp/sa/xapp-${BLOCKED}"]}
