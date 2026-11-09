ARG ACCEPTED_BASE
FROM ${ACCEPTED_BASE}
COPY --chown=0:0 --chmod=644 files/auction_parquet_io.py /app/auction_parquet_io.py
COPY --chown=0:0 --chmod=644 files/auction_synthesis_engine_v1.py /app/auction_synthesis_engine_v1.py
COPY --chown=0:0 --chmod=644 files/engine_worker.py /app/engine_worker.py
COPY --chown=0:0 --chmod=644 files/live_feed_paths.py /app/live_feed_paths.py
COPY --chown=0:0 --chmod=644 files/runtime_engine_guard.py /app/runtime_engine_guard.py
COPY --chown=0:0 --chmod=644 files/canonical_candle_lane.py /app/src/btc_ml/runtime/canonical_candle_lane.py
COPY --chown=0:0 --chmod=644 files/pipeline.py /app/src/btc_ml/runtime/pipeline.py
COPY --chown=0:0 --chmod=644 files/state_manager_v1.py /app/state_manager_v1.py
COPY --chown=0:0 --chmod=644 files/path_registry.py /app/storage/path_registry.py
ENV PYTHONFAULTHANDLER=1
