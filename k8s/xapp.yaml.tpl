# One xApp version. Rendered with VERSION, PRB_RATIO, CONTROL_TARGET and the
# optional FAULT_MODE / FAULT_AFTER_S / FAULT_DELAY_MS used for faulty canaries.
apiVersion: apps/v1
kind: Deployment
metadata:
  name: xapp-${VERSION}
  namespace: manatee-exp
  labels: {app: xapp, version: ${VERSION}}
spec:
  replicas: 1
  selector: {matchLabels: {app: xapp, version: ${VERSION}}}
  template:
    metadata:
      labels: {app: xapp, version: ${VERSION}}
      annotations: {prometheus.io/scrape: "true", prometheus.io/port: "9102"}
    spec:
      serviceAccountName: xapp-${VERSION}
      terminationGracePeriodSeconds: 5
      containers:
      - name: xapp
        image: manatee-harness:0.1
        imagePullPolicy: Never
        args: ["xapp_sim.py"]
        env:
        - {name: VERSION, value: "${VERSION}"}
        - {name: PRB_RATIO, value: "${PRB_RATIO}"}
        - {name: CONTROL_TARGET, value: "${CONTROL_TARGET}"}
        - {name: CONTROL_EVERY, value: "10"}
        - {name: FAULT_MODE, value: "${FAULT_MODE}"}
        - {name: FAULT_AFTER_S, value: "${FAULT_AFTER_S}"}
        - {name: FAULT_DELAY_MS, value: "${FAULT_DELAY_MS}"}
        ports: [{containerPort: 9000}, {containerPort: 8080}, {containerPort: 9102}]
        # Readiness only checks the admin port so that injected data-path
        # faults are handled by MANATEE, not by Kubernetes endpoint removal.
        readinessProbe:
          tcpSocket: {port: 8080}
          periodSeconds: 2
        resources:
          requests: {cpu: 250m, memory: 64Mi}
          limits: {cpu: "1", memory: 256Mi}
