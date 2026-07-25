# Context Decision Log Snapshot Archive

## 1. Purpose

Provide an append-only, immutable snapshot archive of `data/live/context_decision_log.parquet` so future no-repaint audits can compare historical snapshots against the current decision log.

## 2. Why snapshot archive is needed

The No-Repaint Audit can verify payload-hash recalculation on the current file, but without historical snapshots it cannot prove that earlier rows were never rewritten. Snapshot archive closes that gap for **cross-time** comparison.

## 3. What it proves

- A specific decision-log file bytes SHA256 was observed at archive time.
- A byte-identical parquet copy was preserved under `data/live/context_decision_log_snapshots/`.
- Manifest metadata records rows, candle range, duplicate/hash conflict counts, and execution-safety flags at archive time.
- Future audits can compare old snapshot candle/`decision_payload_hash` pairs against the current log.

## 4. What it does not prove

- Live statistical quality of decisions.
- Model outcome quality.
- Automated refresh cadence.
- Execution readiness.
- That future writers will continue appending correctly (process discipline still required).

**Required statement:** This archive strengthens no-repaint evidence but does not enable execution. Execution remains blocked.

## 5. File layout

```text
data/live/context_decision_log.parquet                  # source (never mutated by archive)
data/live/context_decision_log_snapshots/
  context_decision_log_snapshot_<UTC>_<SHORT_SHA>.parquet
  manifest.jsonl                                        # append-only
  latest_snapshot.json                                  # atomic pointer
logs/decision_log_snapshot_archive.log
```

## 6. Manifest schema

Each `manifest.jsonl` line includes:

- identity: `snapshot_id`, `created_at_utc`, `source_path`, `snapshot_path`
- hashes: `source_file_sha256`, `snapshot_file_sha256`
- coverage: `rows`, `unique_candle_timestamps`, first/latest candle and written-at timestamps
- integrity: `duplicate_candle_count`, `duplicate_different_hash_count`, `mutation_conflict_count`
- field presence: payload/source/schema/logger hash/version flags
- safety: action/shadow/execution/orders/visual flags
- versions: `archive_schema_version`, `archive_script_version`

## 7. How to run

```bash
venv/bin/python scripts/live/archive_context_decision_log_snapshot.py --once
# or
make decision-log-snapshot-archive
```

Default behavior skips creating another snapshot when `source_file_sha256` already exists in the manifest (`SKIPPED_DUPLICATE_SOURCE_SHA`). Use `--force` only when an intentional duplicate archive is required.

## 8. Safety guarantees

- Does not rewrite `context_decision_log.parquet`
- Does not overwrite existing snapshot parquet files
- Manifest is append-only JSONL
- Snapshot and `latest_snapshot.json` writes use temp-file + rename
- Execution remains disabled; archive does not place orders

## 9. Limitations

- Archive is manual / once-mode (not wired into runtime-stack auto-start)
- Duplicate source SHA is skipped by default
- Missing decision log returns `MISSING_DECISION_LOG` without traceback
- Strict no-repaint proof still depends on future audit comparison runs

## 10. Execution status

- `execution_readiness = BLOCKED`
- Snapshot archive is observation/safety infrastructure only
