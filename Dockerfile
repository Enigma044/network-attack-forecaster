# Network Attack Forecaster: API + dashboard in one image.
#   podman build --format docker -t netforecast .      (or: docker build -t netforecast .)
#   podman run --rm -p 8000:7860 netforecast           → http://localhost:8000

# 1) Build the React dashboard
FROM docker.io/library/node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) Python runtime with CPU-only PyTorch
FROM docker.io/library/python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NETFORECAST_PUBLIC=1 \
    NETFORECAST_MAX_UPLOAD_MB=200 \
    PORT=7860
WORKDIR /app
COPY requirements-deploy.txt ./
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.0 \
 && pip install -r requirements-deploy.txt

# Hugging Face Spaces runs containers as uid 1000
RUN useradd --create-home --uid 1000 app
COPY --chown=app netforecast/ netforecast/
COPY --chown=app artifacts/ artifacts/
COPY --chown=app data/synthetic/ data/synthetic/
COPY --chown=app data/cic2018/ data/cic2018/
COPY --chown=app --from=frontend /app/frontend/dist frontend/dist
USER app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '7860'))" || exit 1
# Listen on IPv4 and IPv6 (an empty host makes uvicorn open one socket per address family),
# so "localhost" works whichever one the browser picks; IPv4 only where the container has no IPv6.
CMD ["sh", "-c", "HOST=0.0.0.0; python -c \"import socket; socket.socket(socket.AF_INET6).bind(('::', 0))\" 2>/dev/null && HOST=; exec uvicorn netforecast.api:app --host \"$HOST\" --port ${PORT}"]
