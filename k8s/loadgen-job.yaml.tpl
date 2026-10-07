# Indication generator. Rendered with RUN, TARGET, RATE, DURATION, MPC and
# NODE_SELECTOR ("{}" or a hostname selector on multi-node clusters) and
# LOADGEN_RESTART (Never; OnFailure where istio-cni init can race on Job pods).
apiVersion: batch/v1
kind: Job
metadata:
  name: loadgen-${RUN}
  namespace: manatee-exp
  labels: {app: loadgen}
spec:
  backoffLimit: ${LOADGEN_BACKOFF}
  ttlSecondsAfterFinished: 600
  template:
    metadata:
      labels: {app: loadgen}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9102"
        # Let the Job complete: istio-proxy exits with the main container.
        proxy.istio.io/config: '{"holdApplicationUntilProxyStarts": true}'
        sidecar.istio.io/nativeSidecar: "true"
        config.alpha.linkerd.io/proxy-enable-native-sidecar: "true"
    spec:
      serviceAccountName: loadgen
      restartPolicy: ${LOADGEN_RESTART}
      nodeSelector: ${NODE_SELECTOR}
      containers:
      - name: loadgen
        image: manatee-harness:0.1
        imagePullPolicy: Never
        args: ["loadgen.py", "--target", "${TARGET}", "--rate", "${RATE}",
               "--duration", "${DURATION}", "--msgs-per-conn", "${MPC}",
               "--csv", "/data/loadgen-${RUN}.csv",
               "--conn-log", "/data/conns-${RUN}.csv"]
        resources:
          requests: {cpu: "1", memory: 128Mi}
          limits: {cpu: "2", memory: 512Mi}
        volumeMounts: [{name: data, mountPath: /data}]
      volumes:
      - name: data
        hostPath: {path: /var/lib/manatee-exp/current, type: DirectoryOrCreate}
