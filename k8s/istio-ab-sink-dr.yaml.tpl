# Connection-pool circuit breaking on the E2 control path. Bounding the
# lifetime of every xApp->sink connection forces re-authorization, so a
# revoked xApp loses its established control connection within MAX_CONN_S.
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: sink, namespace: manatee-exp}
spec:
  host: sink.manatee-exp.svc.cluster.local
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnectionDuration: ${MAX_CONN_S}s
        connectTimeout: 500ms
