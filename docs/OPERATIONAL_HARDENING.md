# Operational Hardening

**Phase:** 4B  
**Module:** `runtime_hardening.py`

---

## Purpose

Fail-fast operational integrity before runtime loop execution. Invoked automatically by `run.py` unless `--skip-hardening` is passed.

---

## Check Categories

| Check | Description |
|-------|-------------|
| Python version | Requires >= 3.11 |
| Repository root | CWD and `run.py` presence |
| Startup dependencies | pandas, pyarrow, numpy |
| Package imports | `btc_ml`, pipeline, path registry, config |
| Parquet path registry | Category layout, registry integrity |
| Parquet migration | Legacy → `data/` migration, critical file probe |
| Feature flag consistency | Cross-flag validation (discipline, ontology) |
| Config integrity | Unified `config/` layer completeness |
| Replay environment | Replay suites + artifact directories |
| Mirror leakage | Active mirror tree must be absent |
| Legacy shims | Deprecation shims present and valid |

---

## Usage

```bash
python runtime_hardening.py
python run.py --hardening
```

---

## Failure vs Warning

| Severity | Examples |
|----------|----------|
| **FAIL** (blocks startup) | Missing deps, mirror still active, config incomplete, flag contradiction |
| **WARN** (allows startup) | Cold-start parquets absent, cwd mismatch, final validation disabled |

---

## Feature Flag Consistency Rules

- `USE_DISCIPLINED_CONVICTION_AT_RUNTIME=true` requires `ENABLE_PROBABILISTIC_DISCIPLINE=true`
- `USE_LEGACY_CLIMAX_ONTOLOGY=true` with refinement enabled → warning

---

## Integration

`run.py` calls `run_hardening_checks()` before `run_once()` / `run_forever()`.

Verification gate: `scripts/verify_phase4b_hardening.py`
