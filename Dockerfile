FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Gate-B leg ③: a container that answers TCP but cannot read dreamer.db used
# to read as "up" on every dashboard. The probe hits GET /health, which does
# one SELECT 1 and returns 503/degraded when the DB is gone.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "scripts/health_probe.py"]
CMD ["python", "serve.py"]
