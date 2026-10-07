# MANATEE canary routing on the xApp data path. Rendered with W1, W2.
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: xapp, namespace: manatee-exp}
spec:
  host: xapp.manatee-exp.svc.cluster.local
  subsets:
  - {name: v1, labels: {version: v1}}
  - {name: v2, labels: {version: v2}}
---
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: xapp, namespace: manatee-exp}
spec:
  hosts: [xapp.manatee-exp.svc.cluster.local]
  tcp:
  - match: [{port: 9000}]
    route:
    - destination: {host: xapp.manatee-exp.svc.cluster.local, subset: v1, port: {number: 9000}}
      weight: ${W1}
    - destination: {host: xapp.manatee-exp.svc.cluster.local, subset: v2, port: {number: 9000}}
      weight: ${W2}
