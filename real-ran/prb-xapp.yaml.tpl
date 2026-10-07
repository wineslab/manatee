# One periodic PRB-control xApp (xDevSM, image angeloferaudo/prb-control-xapp)
# laid out as an xApp Manager onboarded xApp: pod hostname == xApp name and
# Services service-ricxapp-<name>-http/-rmr, so the framework registers with
# the xApp Manager and the Routing Manager pushes it the RIC_CONTROL_REQ route
# to E2Term. Rendered with NAME, VERSION, GNB, UEID, MINR, MAXR, DEDR and
# NODE_SELECTOR. srsRAN applies the
# slice-level PRB quota per UE: -m encodes a gNB-DU UE ID with gNB-CU-UE-F1AP-ID UEID.
apiVersion: v1
kind: ServiceAccount
metadata: {name: ${NAME}, namespace: ricxapp}
---
apiVersion: v1
kind: ConfigMap
metadata: {name: ${NAME}-config, namespace: ricxapp}
data:
  config-file.json: |
    {
      "name": "${NAME}",
      "version": "0.3.0-ab",
      "APP_NAMESPACE": "ricxapp",
      "containers": [{"name": "${NAME}", "image": {"registry": "docker.io",
        "name": "angeloferaudo/prb-control-xapp", "tag": "0.2.0-dev"}}],
      "messaging": {"ports": [
        {"name": "http", "container": "${NAME}", "port": 8080, "description": "http service"},
        {"name": "rmrroute", "container": "${NAME}", "port": 4561, "description": "rmr route port"},
        {"name": "rmrdata", "container": "${NAME}", "port": 4560,
         "rxMessages": ["RIC_SUB_RESP", "RIC_SUB_FAILURE", "RIC_SUB_DEL_RESP", "RIC_CONTROL_ACK", "RIC_CONTROL_FAILURE"],
         "txMessages": ["RIC_SUB_REQ", "RIC_SUB_DEL_REQ", "RIC_CONTROL_REQ"],
         "policies": [1], "description": "rmr data port"}]},
      "controls": {"subscription": {"url": "http://service-ricxapp-${NAME}-http.ricxapp:8080/",
        "clientEndpoint": "service-ricxapp-${NAME}-http"}}
    }
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: ${NAME}, namespace: ricxapp}
spec:
  replicas: 1
  selector: {matchLabels: {app: prb-xapp, version: ${VERSION}}}
  template:
    metadata:
      labels: {app: prb-xapp, version: ${VERSION}, xapp: ${NAME}}
    spec:
      hostname: ${NAME}
      serviceAccountName: ${NAME}
      nodeSelector: ${NODE_SELECTOR}   # e.g. {kubernetes.io/hostname: <node>} or {}
      containers:
      - name: ${NAME}
        image: docker.io/angeloferaudo/prb-control-xapp:0.2.0-dev
        imagePullPolicy: IfNotPresent
        workingDir: /ws
        command: ["python3", "-u", "/ab/rc_xapp_ab.py", "-g", "${GNB}", "-r", "${MINR}", "-x", "${MAXR}", "-y", "${DEDR}", "--period", "1", "--call-process-id", "", "-m", "-u", "${UEID}"]
        env:
        - {name: PLT_NAMESPACE, value: ricplt}
        - {name: CONFIG_FILE, value: /ab/config-file.json}
        # Shared data layer (R-NIB): normally injected by the xApp Manager chart.
        - {name: DBAAS_SERVICE_HOST, value: service-ricplt-dbaas-tcp.ricplt}
        - {name: DBAAS_SERVICE_PORT, value: "6379"}
        # RMR source id must match the sender in the Routing Manager routes
        # (mse|12040,service-ricxapp-<name>-rmr.ricxapp:4560|-1|%meid).
        - {name: RMR_SRC_ID, value: service-ricxapp-${NAME}-rmr.ricxapp}
        ports: [{containerPort: 8080}, {containerPort: 4560}, {containerPort: 4561}]
        volumeMounts:
        - {name: config, mountPath: /ab}
      volumes:
      - name: config
        projected:
          sources:
          - configMap: {name: ${NAME}-config}
          - configMap: {name: prb-xapp-ab-script}
---
apiVersion: v1
kind: Service
metadata: {name: service-ricxapp-${NAME}-http, namespace: ricxapp}
spec:
  selector: {xapp: ${NAME}}
  ports: [{name: http, port: 8080}]
---
apiVersion: v1
kind: Service
metadata: {name: service-ricxapp-${NAME}-rmr, namespace: ricxapp}
spec:
  selector: {xapp: ${NAME}}
  ports:
  - {name: tcp-rmrdata, port: 4560}
  - {name: tcp-rmrroute, port: 4561}
