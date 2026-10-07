FROM python:3.11-slim
RUN pip install --no-cache-dir prometheus_client==0.20.0 aiohttp==3.9.5
WORKDIR /app
COPY xapp_sim.py loadgen.py sink.py ./
ENTRYPOINT ["python3", "-u"]
CMD ["xapp_sim.py"]
