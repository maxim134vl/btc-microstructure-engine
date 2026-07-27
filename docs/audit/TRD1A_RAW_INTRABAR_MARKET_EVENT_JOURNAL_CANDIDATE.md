# TRD1A — Raw Intrabar Market Event Journal Candidate

**Status:** `TRD1A_RAW_INTRABAR_EVENT_JOURNAL_CANDIDATE_READY`  
**Mode:** shadow-only · `paper_only=true` · no cognition / trading wiring  
**Evidence:** `data/candidate/architecture_recovery/trd1a_raw_intrabar_event_journal_candidate/`

---

## Architecture

Independent shadow data plane:

```text
Binance spot WS (combined)
  btcusdt@aggTrade + btcusdt@bookTicker
        │
        ▼
RawMarketEventCollector  (scripts/live/raw_market_event_journal_collector.py)
        │
        ├─ normalize (Decimal strings, separated timestamps)
        ├─ duplicate / gap monitors
        ├─ session identity (UUID + reconnect_generation)
        ▼
AtomicJournalWriter → append-only JSONL hour partitions
        │
        ▼
RawEventJournalReader (per-stream deterministic read; no TRD2 merge)
```

Does **not** replace or mutate:

- `live_market_feed.parquet` / `live_market_intrabar_feed.parquet`
- Stage1/2, lifecycle, manager, traders, OPS, visualizer

Production candle collector (`live_binance_feed_v2.py`) and `collector_watchdog.py` were **not** behaviorally changed. Only a back-compat soft-import in `src/btc_ml/feeds/__init__.py` so `src/`-only imports of the new subpackage succeed.

---

## Stream subscriptions

| Stream | Endpoint | Role |
|--------|----------|------|
| `aggTrade` | spot combined WS | trade sequence, event-time price/qty, aggressor side |
| `bookTicker` | spot combined WS | best bid/ask, spread, mid (not context direction) |

**Venue choice:** `wss://stream.binance.com:9443/...` (spot), matching `live_binance_feed_v2`.  
In this environment `fstream.binance.com` delivered `bookTicker` but **zero** `aggTrade`; spot yields both.

SSL posture mirrors the live candle collector (`sslopt cert_reqs=CERT_NONE`) due to intercepting TLS.

---

## Schemas

`schema_version = 1.0.0`

### AGG_TRADE

`schema_version`, `stream_type`, `symbol`, `exchange_event_timestamp`, `exchange_trade_timestamp`, `local_receive_timestamp`, `local_receive_monotonic_ns`, `aggregate_trade_id`, `first_trade_id`, `last_trade_id`, `price`, `quantity`, `quote_quantity`, `buyer_is_market_maker`, `connection_session_id`, `reconnect_generation`, `source_sequence`, `raw_payload_hash`, `ingested_at`

### BOOK_TICKER

`schema_version`, `stream_type`, `symbol`, `exchange_event_timestamp`, `local_receive_timestamp`, `local_receive_monotonic_ns`, `update_id`, `best_bid_price`, `best_bid_quantity`, `best_ask_price`, `best_ask_quantity`, `spread`, `mid_price`, `connection_session_id`, `reconnect_generation`, `source_sequence`, `raw_payload_hash`, `ingested_at`

Missing optional payload fields → `null` (never synthesized). Spot `bookTicker` has no `E` → `exchange_event_timestamp = null`.

---

## Timestamp semantics

UTC wall clock, explicitly separated:

| Field | Meaning |
|-------|---------|
| `exchange_event_timestamp` | Binance `E` if present |
| `exchange_trade_timestamp` | Binance `T` (aggTrade) |
| `local_receive_timestamp` | wall clock at payload arrival (before heavy work) |
| `local_receive_monotonic_ns` | monotonic local order |
| `ingested_at` | normalize/write time |

No generic `timestamp` field.

---

## Ordering / sequence

- **aggTrade:** `aggregate_trade_id` → `exchange_trade_timestamp` → `local_receive_monotonic_ns`
- **bookTicker:** `update_id` → `local_receive_monotonic_ns`
- Cross-stream merge: **deferred to TRD2**

---

## Duplicate handling

- aggTrade: `(symbol, aggregate_trade_id)`
- bookTicker: `(symbol, update_id)`; fallback `(raw_payload_hash, connection_session_id)`
- Duplicates dropped, counted, **not** treated as sequence gaps

---

## Gap detection

- aggTrade: continuous `aggregate_trade_id`; optional trade-id range gaps → `SEQUENCE_GAP_DETECTED` / `EVENT_SEQUENCE_GAP`
- bookTicker: **does not** assume `update_id + 1`; only records rewinds
- Operational journal records connect/disconnect/reconnect/flush/disk_low

---

## Storage

Candidate smoke path:

```text
data/candidate/.../trd1a_.../smoke_journal/
  agg_trade/date=YYYY-MM-DD/hour=HH/*.jsonl
  book_ticker/date=YYYY-MM-DD/hour=HH/*.jsonl
  operational/date=YYYY-MM-DD/hour=HH/*.jsonl
  manifests/<stream>/date=/hour=/batches.jsonl
```

Future production root (not activated): `data/live/raw_market_events/`

Batch policy (measured then set):

| Limit | Default | Rationale |
|-------|---------|-----------|
| max events | 500 | ~33 combined evt/s in smoke |
| max seconds | 2.0 | bound latency to disk |
| max buffered bytes | 512 KiB | memory cap |

Atomic commit: temp → fsync → schema/row-count verify → `os.replace` → manifest append.

---

## Disk estimate

Smoke (~21s spot):

| Metric | Value |
|--------|-------|
| bytes written | ~471 KiB |
| bytes/s | ~22.4 KiB/s |
| **estimated GB/day** | **~1.8** |
| free disk at smoke | ~3.9–4.9 GiB |
| fail-closed floor | 2 GiB (`DISK_LOW`) |

Continuous shadow activation is feasible only with adequate free disk; no automatic deletion of old journals.

---

## Tests

- Unit: 13 passed (normalize, Decimal round-trip, duplicates, sessions, gaps, atomic write, reader, disk-low)
- Integration: 7 passed (interleave, OOO, reconnect, crash temp, corrupt batch, hour/date rollover)
- Total: **20/20**

---

## Smoke results

| Metric | Value |
|--------|-------|
| duration | ~21 s |
| aggTrade events | 26 |
| bookTicker events | 679 |
| duplicates | 0 |
| gaps | 0 |
| session id | present (single session) |
| reader checksums | match |
| precision | preserved (`64969.99000000` style strings) |
| existing PIDs | unchanged |
| downstream consumers | 0 |

---

## Limitations

1. No TRD2 cross-stream merge ordering.
2. No cognition / context / trading consumers.
3. Spot venue only (futures aggTrade unavailable here).
4. Disk headroom tight (~4 GiB free) — keep activation short or expand disk first.
5. In-memory dedupe is process-lifetime (restart may re-see exchange-side duplicates across process boundaries; reader still detects file-level dupes).

---

## Controlled activation plan

1. Confirm free disk ≥ several days × ~1.8 GB/day (or add retention ops).
2. Launch isolated collector to `data/live/raw_market_events/` (or keep candidate path longer).
3. Watch health snapshot + operational journal; do **not** wire Stage1/2/manager.
4. After stable multi-hour shadow, proceed to TRD2 merge-ordering contract.

---

## Modules

| Path | Role |
|------|------|
| `src/btc_ml/feeds/raw_event_journal/` | schemas, normalize, writer, reader, collector |
| `scripts/live/raw_market_event_journal_collector.py` | isolated launcher |
| `tests/feeds/raw_event_journal/` | unit + integration |
