# Runbook

Step-by-step procedures keyed by alert / situation. Every Prometheus rule's
`annotations.runbook` field points to an anchor in this file.

## How to read this doc

- One section per procedure.
- Steps are numbered, copy-paste-able.
- Diagnostic queries are in PromQL / LogQL.
- "Verify" steps confirm the issue is resolved.

---

## #runtime-stalled

**Alert**: `RuntimeStalled`. `btc_runtime_last_iter_age_seconds > 120` for 2 min.

Steps:

1. Confirm scope — is just runtime stalled, or are collectors also dead?
   - PromQL: `up{job=~"collector.*"}` — all should be 1
2. Tail runtime logs: `make logs SVC=pipeline --tail=500`
3. Look for the **last successful iteration log line** (search for `iter complete`)
4. After that line, the first ERROR / WARN is the cause
5. Common cases:
   - **OOM kill** → check `docker inspect btc_pipeline | grep OOMKilled` — bump mem limit
   - **Stuck on file read** → may be holding a parquet lock; check `lsof` from another container or restart the collector that owns the file
   - **Genuine code regression** → roll back to last known-good image tag
6. Restart: `make restart-svc SVC=pipeline`
7. **Verify**: monitor-ui `RUNTIME` pill turns green within 60s; `btc_runtime_last_iter_age_seconds` drops below 30

---

## #parquet-stale

**Alert**: `ParquetStale{file="X"}`. Parquet has not been written in N seconds.

Steps:

1. Identify producer for the file (see `infra/prometheus/parquet-producers.yml`)
2. `make logs SVC=<producer-container> --tail=300`
3. If producer is dead → restart it (`make restart-svc SVC=<name>`)
4. If producer is alive but quiet → upstream feed is dead:
   - For binance-feed: check `wss://stream.binance.com` reachability from inside the container
   - For multi-exchange: check ccxt rate limits
5. **Verify**: `btc_parquet_age_seconds{file="X"}` drops below threshold within 60s

---

## #parquet-schema-invalid

**Alert**: `ParquetSchemaInvalid{file="X"}`.

Steps:

1. metrics-exporter publishes the failing schema diff in its logs:
   `make logs SVC=metrics-exporter | grep "schema.invalid"`
2. The exporter compares against an allowlist in `metrics-exporter/src/config.py` → `EXPECTED_COLUMNS`
3. If the producer changed its schema legitimately → update the allowlist + bump VERSION
4. If a corrupt write happened → quarantine the file:
   ```
   docker run --rm -v btc_engine_data:/d alpine mv /d/X.parquet /d/X.broken.parquet
   ```
5. Restart the producer to regenerate
6. **Verify**: `btc_parquet_schema_valid{file="X"} == 1`

---

## #feed-disconnected

**Alert**: `FeedDisconnected{exchange="…"}`.

Steps:

1. Tail the feed: `make logs SVC=<feed-svc> --tail=200`
2. If it's a controlled reconnect → wait 30s, watchdog will not act unless storm
3. If reconnects/min > 10 → **reconnect storm**, see [#reconnect-storm](#reconnect-storm)
4. If upstream is genuinely down → check exchange status page; nothing to do but wait
5. Optionally silence the alert with TTL = expected outage

---

## #reconnect-storm

**Alert**: `ReconnectStorm{feed="…"}`. rate > N reconnects per 5 min.

Steps:

1. watchdog automatically trips its circuit breaker after the threshold → restart attempts pause for 15 min
2. Investigate:
   - Are we IP-banned? Check upstream response codes in logs
   - Are we hitting rate limits? Some exchanges return 429 on WS subscribe spam
3. If banned → switch outbound IP (deploy via a different region) and reset the breaker:
   `curl -X POST http://localhost:9103/api/circuit/reset?feed=<name>`
4. **Verify**: `rate(btc_feed_reconnects_total[5m])` falls below threshold

---

## #disk-low

**Alert**: `DiskLow{mountpoint="/data"}`. Free < 15%.

Steps:

1. Identify largest parquets:
   ```
   docker run --rm -v btc_engine_data:/d alpine sh -c 'du -h /d | sort -h | tail -20'
   ```
2. Determine if rotation is allowed:
   - `intraday_flow.parquet` is append-only; trimming = losing history
   - Some research outputs in `/data/research/` are regeneratable
3. If safe to trim, use the rotation tool:
   `make data-rotate FILE=research_output_xyz.parquet KEEP_DAYS=30`
4. If genuinely full → expand the underlying volume:
   - bind-mount on host → resize the FS / move to bigger disk
   - swarm CSI volume → resize via CSI driver
5. **Verify**: `node_filesystem_avail_bytes{mountpoint="/data"}` rises above threshold

---

## #feature-nan-explosion

**Alert**: `FeatureNaNExplosion{feature="…"}`. Ratio > 1% over last 2000 rows.

Steps:

1. metrics-exporter logs the offending feature names + ratios at WARN level
2. Read the latest rows:
   ```
   docker run --rm -v btc_engine_data:/d -w /d python:3.12-slim \
     sh -c 'pip install pandas pyarrow -q && python -c "import pandas as pd; df=pd.read_parquet(\"<file>\"); print(df.tail(50).describe())"'
   ```
3. NaN sources:
   - Division by zero in an engine (look at recent engine changes)
   - Upstream NaN propagating from feed (check raw flow parquet)
   - Schema migration where new column hasn't backfilled
4. Fix at the engine producing the feature; restart that engine
5. **Verify**: `btc_feature_nan_ratio{feature="X"}` falls below 0.01

---

## #manual-data-rotate

Manually rotate / archive a parquet file.

```
make data-rotate FILE=<basename.parquet> KEEP_DAYS=30
```

Implemented in `scripts/data-rotate.sh`. Creates a timestamped tarball in
`/data/archive/`.

---

## #upgrade-prometheus

```
1. Edit .env → PROMETHEUS_VERSION=vX.Y.Z
2. make build
3. (Optional) snapshot TSDB
4. make restart-svc SVC=prometheus
5. make smoke
```

---

## #upgrade-engine

(Refers to the data-plane engine image, not observability stack.)

```
1. Edit ../docker-compose.yml or Dockerfile in the engine
2. cd .. && docker compose build
3. cd monitoring && make restart-svc SVC=pipeline
4. make smoke
```

---

## #backup-restore

Per-volume tarball backup + restore is already provided by the engine's
`../deploy.sh backup` / `restore`. For Prometheus and Loki:

```
make backup-obs    # writes ./backups/obs-YYYYMMDD.tgz
make restore-obs FILE=./backups/obs-….tgz
```

---

## Adding a new alert

1. Add a `alert:` block to the appropriate file in `infra/prometheus/rules/`
2. Run `make prom-reload`
3. Run `make alert-test ALERT=YourNewAlert` to dry-run
4. Add a section to this file with the same name as the alert
5. Point `annotations.runbook: docs/RUNBOOK.md#youralertname`
