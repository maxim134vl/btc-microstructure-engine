# Deployment Runtime Guide

**Phase:** 4B — Final Normalization & Operational Hardening  
**Status:** Canonical operational baseline

---

## Quick Start

```bash
# One-time bootstrap (venv, deps, data layout, hardening)
./scripts/bootstrap_runtime.sh

# Canonical runtime loop
./run.sh

# Single pipeline pass
./run.sh --once

# Phase 4B verification gate
./run.sh --verify-4b
```

---

## Canonical Entrypoints

| Command | Purpose |
|---------|---------|
| `./run.sh` | Production runtime loop (17-step pipeline) |
| `python run.py` | Same as above (direct Python) |
| `python run.py --once` | Single pass |
| `python run.py --hardening` | Operational checks only |
| `python run.py --verify-4b` | Full Phase 4B gate |

**Deprecated (shim + warning):**

- `master_auction_runtime_v1.py` → redirects to canonical pipeline
- `autonomous_runtime_v1.py`, `autonomous_runtime_v2.py`
- `behavioral_runtime_orchestrator_v1.py`

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `BTC_ML_DATA_ROOT` | `data` | Parquet storage root |
| `PYTHON` | `python3` | Bootstrap interpreter |
| `ENABLE_PROBABILISTIC_DISCIPLINE` | `false` | Phase 1B discipline |
| `ENABLE_ONTOLOGY_REFINEMENT` | `true` | Phase 3A ontology |
| `ENABLE_ONTOLOGY_STABILIZATION` | `true` | Phase 3B stabilization |
| `ENABLE_ADVERSARIAL_DIAGNOSTICS` | `false` | Phase 2B adversarial |
| `ENABLE_FINAL_VALIDATION` | `true` | Phase 4A replay gate |

See `docs/OPERATIONAL_HARDENING.md` for full flag inventory.

---

## Package Layout

```
run.py / run.sh              # Canonical entry
src/btc_ml/                  # Package skeleton + shims
storage/path_registry.py     # Parquet path truth
config/                      # Unified configuration
data/                        # Canonical parquet storage
artifacts/ reports/ replays/ # Non-parquet outputs
```

---

## Installation

```bash
pip install -e .
pip install -r requirements-runtime.txt   # minimal
# or
pip install -r requirements.txt           # full lockfile
```

---

## Verification Gates

```bash
venv/bin/python3 scripts/verify_phase4b_hardening.py
venv/bin/python3 scripts/final_repo_audit.py
venv/bin/python3 runtime_hardening.py
```

---

## Out of Scope (Frozen)

- Ontology redesign
- Execution / PnL optimization
- Autonomous trading
- Self-modifying systems

See `docs/FINAL_PLATFORM_FREEZE.md` for the full freeze baseline.
