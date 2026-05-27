# =============================================================================
# metrics-exporter — multi-stage image
# -----------------------------------------------------------------------------
# stage 1: build wheel cache
# stage 2: minimal runtime layer, non-root
# =============================================================================

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# system deps needed only at build time (some wheels need cc)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --prefix=/install .

# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/install/bin:$PATH \
    PYTHONPATH=/install/lib/python3.12/site-packages

# tini for proper PID-1 signal handling, ca-certs for outbound HTTPS (none today,
# but adds < 200 KB)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        ca-certificates \
        && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /install

# non-root
RUN useradd --create-home --uid 10001 --shell /sbin/nologin btc \
    && mkdir -p /data \
    && chown -R btc:btc /data

USER btc:btc
WORKDIR /app

EXPOSE 9101

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://localhost:9101/healthz',timeout=3).status==200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--", "btc-metrics-exporter"]
