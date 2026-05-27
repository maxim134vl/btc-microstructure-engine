# Canonical Runtime Bootstrap

**Phase:** 4B  
**Script:** `scripts/bootstrap_runtime.sh`

---

## What Bootstrap Does

1. Creates `venv/` if missing
2. Upgrades pip, wheel, setuptools
3. Installs editable package (`pip install -e .`)
4. Installs runtime dependencies (`requirements-runtime.txt` or full `requirements.txt`)
5. Creates `data/` category directories
6. Migrates legacy root parquets → `data/`
7. Runs `runtime_hardening.py`

---

## Usage

```bash
./scripts/bootstrap_runtime.sh
```

### Overrides

```bash
PYTHON=python3.11 VENV=.venv ./scripts/bootstrap_runtime.sh
```

---

## Post-Bootstrap

```bash
./run.sh                  # start runtime
./run.sh --verify-4b      # Phase 4B gate
```

---

## Reproducible Deployment Checklist

- [ ] Clone repository
- [ ] Run `bootstrap_runtime.sh`
- [ ] Confirm hardening PASS
- [ ] Run `verify_phase4b_hardening.py`
- [ ] Start with `./run.sh --once` for smoke test
- [ ] Enable production loop with `./run.sh`

---

## Dependencies

| File | Role |
|------|------|
| `pyproject.toml` | Package metadata + core deps |
| `requirements-runtime.txt` | Minimal runtime set |
| `requirements.txt` | Full development lockfile |

---

## Data Root Override

```bash
export BTC_ML_DATA_ROOT=/var/lib/btc-ml/data
./scripts/bootstrap_runtime.sh
```

See `docs/PARQUET_STORAGE_TOPOLOGY.md`.
