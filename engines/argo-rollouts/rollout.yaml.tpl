# Argo Rollouts engine for E3 (dedicated progressive-delivery controller).
# The controller owns the xApp pods, shifts the Istio TCP route weights and
# aborts (weight back to 0) as soon as the background analysis fails.
# Rendered with VERSION, PRB_RATIO, FAULT_MODE, NODE_SELECTOR.
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata: {name: xapp-health, namespace: manatee-exp}
spec:
  metrics:
  - name: error-ratio
    interval: 2s
    failureLimit: 0
    successCondition: result[0] <= 0.01
    provider:
      prometheus:
        address: http://prometheus.istio-system:9090
        query: (sum(rate(loadgen_msgs_total{result!="ok"}[10s])) or vector(0)) / sum(rate(loadgen_msgs_total[10s]))
  - name: p95-latency-ms
    interval: 2s
    failureLimit: 0
    successCondition: result[0] <= 50
    provider:
      prometheus:
        address: http://prometheus.istio-system:9090
        query: 1000 * histogram_quantile(0.95, sum(rate(loadgen_latency_seconds_bucket[10s])) by (le))
---
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: xapp, namespace: manatee-exp}
spec:
  host: xapp.manatee-exp.svc.cluster.local
  subsets:
  - {name: stable, labels: {app: xapp}}
  - {name: canary, labels: {app: xapp}}
---
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: xapp, namespace: manatee-exp}
spec:
  hosts: [xapp.manatee-exp.svc.cluster.local]
  tcp:
  - match: [{port: 9000}]
    route:
    - destination: {host: xapp.manatee-exp.svc.cluster.local, subset: stable, port: {number: 9000}}
      weight: 100
    - destination: {host: xapp.manatee-exp.svc.cluster.local, subset: canary, port: {number: 9000}}
      weight: 0
---
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata: {name: xapp, namespace: manatee-exp}
spec:
  replicas: 1
  revisionHistoryLimit: 2
  selector: {matchLabels: {app: xapp}}
  strategy:
    canary:
      trafficRouting:
        istio:
          virtualService:
            name: xapp
            tcpRoutes: [{port: 9000}]
          destinationRule: {name: xapp, canarySubsetName: canary, stableSubsetName: stable}
      analysis:
        templates: [{templateName: xapp-health}]
        startingStep: 0
      steps:
      - setWeight: 10
      - pause: {duration: 20s}
      - setWeight: 25
      - pause: {duration: 20s}
      - setWeight: 50
      - pause: {duration: 20s}
      - setWeight: 75
      - pause: {duration: 20s}
      - setWeight: 100
      - pause: {duration: 20s}
  template:
    metadata:
      labels: {app: xapp, version: "${VERSION}"}
      annotations: {prometheus.io/scrape: "true", prometheus.io/port: "9102"}
    spec:
      serviceAccountName: xapp-v1
      terminationGracePeriodSeconds: 5
      nodeSelector: ${NODE_SELECTOR}
      containers:
      - name: xapp
        image: manatee-harness:0.1
        imagePullPolicy: Never
        args: ["xapp_sim.py"]
        env:
        - {name: VERSION, value: "${VERSION}"}
        - {name: PRB_RATIO, value: "${PRB_RATIO}"}
        - {name: CONTROL_TARGET, value: "sink.manatee-exp:9100"}
        - {name: FAULT_MODE, value: "${FAULT_MODE}"}
        - {name: FAULT_DELAY_MS, value: "150"}
        ports: [{containerPort: 9000}, {containerPort: 8080}, {containerPort: 9102}]
        readinessProbe:
          tcpSocket: {port: 8080}
          periodSeconds: 2
        resources:
          requests: {cpu: 250m, memory: 64Mi}
          limits: {cpu: "1", memory: 256Mi}
