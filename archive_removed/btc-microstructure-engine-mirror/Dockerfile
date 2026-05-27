# =====================================================================
# BTC microstructure engine — shared runtime image
# =====================================================================
# All services (collectors, pipeline orchestrator, dashboard) share one
# image. Per-service command is set in docker-compose.yml.
#
# Layout inside the container:
#   /app   - source code (read-only at runtime)
#   /data  - working directory + persisted parquet store (named volume)
#   /logs  - optional log directory (named volume)
#
# At container start, entrypoint.sh symlinks all .py files and engine
# subdirs from /app into /data so the existing code (which reads/writes
# parquet files by bare filename and `os.system`s sibling .py scripts)
# works unchanged with /data as the working dir.
# =====================================================================

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

# system deps: build toolchain for any wheels that need compiling,
# libgomp for xgboost, curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libgomp1 \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# install python deps first (cache-friendly layer)
COPY requirements-docker.txt /app/requirements-docker.txt
RUN pip install -r /app/requirements-docker.txt

# now copy source
COPY . /app

# entrypoint script
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# non-root user
RUN useradd --create-home --uid 1000 btc \
    && mkdir -p /data /logs \
    && chown -R btc:btc /data /logs /app
USER btc

WORKDIR /data

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python3", "/app/autonomous_runtime_v2.py"]
