# syntax=docker/dockerfile:1
# OPS API image — same runtime base pattern, API-focused CMD.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/src:/app/dashboard/backend \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl procps tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 btcml \
    && useradd --system --uid 10001 --gid btcml --home-dir /app --shell /usr/sbin/nologin btcml

WORKDIR /app

COPY requirements-runtime.txt /tmp/requirements-runtime.txt
COPY dashboard/backend/requirements.txt /tmp/dashboard-requirements.txt
RUN pip install --no-cache-dir \
      -r /tmp/requirements-runtime.txt \
      -r /tmp/dashboard-requirements.txt

COPY pyproject.toml ./
COPY *.py ./
COPY storage ./storage
COPY visual_cognition ./visual_cognition
COPY benchmark ./benchmark
COPY config ./config
COPY src ./src
COPY scripts ./scripts
COPY dashboard/backend ./dashboard/backend
COPY deploy/vps ./deploy/vps

RUN mkdir -p /app/venv/bin /app/data /app/run \
    && ln -sf /usr/local/bin/python3 /app/venv/bin/python \
    && ln -sf /usr/local/bin/python3 /app/venv/bin/python3 \
    && chown -R btcml:btcml /app \
    && PYTHONPATH=/app:/app/src:/app/dashboard/backend \
       python -c "from app.main import app; assert any(getattr(r,'path',None)=='/health' for r in app.routes)"
USER btcml
WORKDIR /app/dashboard/backend
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "run_api.py"]
