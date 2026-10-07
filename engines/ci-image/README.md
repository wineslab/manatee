# Tekton step image

`kubectl` plus the shared telemetry gate (`harness/gate.py`). The `kubectl`
binary is not committed; fetch it (checksum-verified) and build:

```bash
KV=v1.32.3
curl -sSLO https://dl.k8s.io/release/$KV/bin/linux/amd64/kubectl
echo "$(curl -sSL https://dl.k8s.io/release/$KV/bin/linux/amd64/kubectl.sha256)  kubectl" | sha256sum -c -
cp ../../harness/gate.py .
docker build -t manatee-ci:0.1 .
```
