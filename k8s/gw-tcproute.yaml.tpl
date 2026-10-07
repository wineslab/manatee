# Mesh-neutral canary routing (Gateway API GAMMA): the same resource is
# implemented by Istio sidecars, Istio ambient waypoints and Linkerd.
# Rendered with W1, W2.
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TCPRoute
metadata: {name: xapp, namespace: manatee-exp}
spec:
  parentRefs:
  - {group: "", kind: Service, name: xapp, port: 9000}
  rules:
  - backendRefs:
    - {name: xapp-v1, port: 9000, weight: ${W1}}
    - {name: xapp-v2, port: 9000, weight: ${W2}}
