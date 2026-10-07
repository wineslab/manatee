# Step image for the Tekton engine: kubectl + the shared telemetry gate.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends gettext-base && rm -rf /var/lib/apt/lists/*
COPY kubectl /usr/local/bin/kubectl
COPY gate.py /usr/local/bin/gate.py
RUN chmod +x /usr/local/bin/kubectl
