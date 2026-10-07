# Linkerd equivalent of the A/B control-authority gate: only the xApp that
# holds control (ALLOWED) may connect to the sink's control port.
apiVersion: policy.linkerd.io/v1beta3
kind: Server
metadata: {name: sink-ctrl, namespace: manatee-exp}
spec:
  podSelector: {matchLabels: {app: sink}}
  port: 9100
  proxyProtocol: opaque
---
apiVersion: policy.linkerd.io/v1alpha1
kind: MeshTLSAuthentication
metadata: {name: ab-holder, namespace: manatee-exp}
spec:
  identities: ["xapp-${ALLOWED}.manatee-exp.serviceaccount.identity.linkerd.cluster.local"]
---
apiVersion: policy.linkerd.io/v1alpha1
kind: AuthorizationPolicy
metadata: {name: ab-authority, namespace: manatee-exp}
spec:
  targetRef: {group: policy.linkerd.io, kind: Server, name: sink-ctrl}
  requiredAuthenticationRefs:
  - {group: policy.linkerd.io, kind: MeshTLSAuthentication, name: ab-holder}
