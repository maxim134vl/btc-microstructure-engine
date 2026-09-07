# syntax=docker/dockerfile:1
# Reusable Python 3.11 runtime image for canonical BTC-ML VPS full-model services.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
        procps \
        tini \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 btcml \
    && useradd --system --uid 10001 --gid btcml --home-dir /app --shell /usr/sbin/nologin btcml

WORKDIR /app

# Runtime deps first (layer cache)
COPY requirements-runtime.txt /tmp/requirements-runtime.txt
COPY requirements-hl-vault.txt /tmp/requirements-hl-vault.txt
COPY dashboard/backend/requirements.txt /tmp/dashboard-requirements.txt
RUN pip install --no-cache-dir \
      -r /tmp/requirements-runtime.txt \
      -r /tmp/dashboard-requirements.txt \
      -r /tmp/requirements-hl-vault.txt \
      websocket-client==1.7.0

# Production code + config only (see root .dockerignore).
# Root-level *.py modules are still imported by LIVE1A cognition (parquet_utils,
# build_*_memory, etc.) — copy them explicitly.
COPY pyproject.toml README_RUNTIME.md ./
COPY *.py ./
COPY storage ./storage
COPY config ./config
COPY src ./src
COPY scripts ./scripts
COPY dashboard/backend ./dashboard/backend
COPY apps/context_visualizer ./apps/context_visualizer
COPY deploy/vps ./deploy/vps

# Host collectors / ctl scripts expect <repo>/venv/bin/python. Provide a
# stable path that points at the image interpreter (read-only root FS).
RUN mkdir -p /app/venv/bin \
    && ln -sf /usr/local/bin/python3 /app/venv/bin/python \
    && ln -sf /usr/local/bin/python3 /app/venv/bin/python3 \
    && mkdir -p /app/data /app/run /app/logs /app/output /app/artifacts /app/reports \
    && chown -R btcml:btcml /app \
    && python -c "from btc_ml.live.intrabar.cognition_pipeline import IntrabarCognitionEngine" \
    && python -c "from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine" \
    && python -c "from btc_ml.trading.hybrid_sizing import load_sizer" \
    && python -c "from btc_ml.trading.shadow_economic_correlation.engine import ShadowEconomicCorrelationEngine" \
    && python -c "from btc_ml.trading.shadow_structural_protection.engine import StructuralProtectionEngine" \
    && python -c "from btc_ml.trading.shadow_structural_protection.be33 import StpBe33Engine"

USER btcml

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-c", "print('btc-ml-vps-runtime image ready'); raise SystemExit(1)"]
