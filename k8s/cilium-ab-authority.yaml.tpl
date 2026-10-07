# Cilium equivalent of the A/B control-authority gate, enforced in eBPF:
# the sink accepts control connections only from the xApp in control.
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: {name: ab-authority, namespace: manatee-exp}
spec:
  endpointSelector: {matchLabels: {app: sink}}
  # Any ingress policy puts the sink in default-deny, so allow the namespace
  # explicitly; the deny rule below takes precedence for the blocked xApp.
  ingress:
  - fromEndpoints: [{matchLabels: {}}]
  ingressDeny:
  - fromEndpoints:
    - matchLabels: {app: xapp, version: ${BLOCKED}}
    toPorts:
    - ports: [{port: "9100", protocol: TCP}]
