# MIGRATION PLAN — `src/btc_ml/`

**Status:** Preparation only — no behavioral logic changes  
**Updated:** 2026-05-26  
**Target:** Production-grade package layout  
**Canonical runtime:** `master_auction_runtime_v1.py` → `btc_ml.orchestration.auction_pipeline`

---

## 1. Principles

1. **Move, don't rewrite** — same functions, new paths
2. **Thin shims** at old paths during transition (deprecation warnings)
3. **No threshold changes** — constants moved as-is to `constants.py`
4. **Stage 2 wiring** — orchestration only, no detection logic edits
5. **One commit per migration phase** — rollback-friendly

---

## 2. Target Structure

```
btc-ml/
├── src/
│   └── btc_ml/
│       ├── __init__.py
│       ├── main.py                    # unified CLI
│       ├── cli.py
│       ├── config.py                  # from runtime_config.py
│       ├── constants.py               # thresholds moved verbatim
│       ├── exceptions.py
│       ├── core/
│       │   └── state/
│       │       ├── manager.py         ← state_manager_v1.py
│       │       └── registry.py
│       ├── repositories/
│       │   └── parquet/
│       │       ├── utils.py           ← parquet_utils.py
│       │       ├── guard.py           ← state_guard.py
│       │       └── writer.py          ← parquet_writer_v2.py
│       ├── services/
│       │   ├── structure/
│       │   │   ├── candle_structure.py
│       │   │   ├── volume_classification.py
│       │   │   └── volume_response.py
│       │   ├── auction/
│       │   │   ├── convergence.py
│       │   │   ├── synthesis.py
│       │   │   ├── reinforcement.py
│       │   │   ├── decay.py
│       │   │   └── climax.py          ← auction_climax_engine_v1.py
│       │   ├── cognition/
│       │   │   ├── runtime.py         ← runtime_cognition_engine_v1.py
│       │   │   ├── probabilistic.py
│       │   │   ├── meta.py            ← adaptive_meta_cognition_engine_v1.py
│       │   │   └── state_transition.py
│       │   └── synthesis/
│       │       ├── multi_timeframe.py ← multi_timeframe_synthesis_engine.py
│       │       └── dataset_builder.py ← multi_timeframe_dataset_builder.py
│       ├── orchestration/
│       │   ├── auction_pipeline.py    ← master_auction_runtime_v1.py loop
│       │   ├── stage2_batch.py        ← research_dataset_builder_v1.py (split later)
│       │   ├── dependency_map.py
│       │   └── dependency_guard.py
│       ├── integrations/
│       │   └── collectors/            ← collectors/*.py
│       ├── schemas/                   ← parquet contracts (new)
│       ├── utils/
│       └── logging/
│           └── setup.py
├── scripts/
│   └── research/                      ← *_backtest_v1.py, visualizers
├── tests/
├── docs/
├── configs/
├── archive_removed/
├── pyproject.toml
└── master_auction_runtime_v1.py       ← shim (temporary)
```

---

## 3. Migration Phases

### Phase 0 — Documentation (current stage) ✅

- [x] `PROJECT_AUDIT.md`
- [x] `docs/PARQUET_DEPENDENCY_MAP.md`
- [x] `docs/CANONICAL_RUNTIME_MAP.md`
- [x] `docs/DUPLICATE_RESOLUTION_PLAN.md`
- [x] `docs/RUNTIME_RESEARCH_BOUNDARY_VIOLATIONS.md`
- [x] This document

### Phase 1 — Package skeleton (no moves yet)

- [ ] Create `src/btc_ml/` with `__init__.py`, `pyproject.toml`
- [ ] Add `[tool.setuptools.packages.find] where = ["src"]`
- [ ] `pip install -e .` works with empty package
- [ ] Add `tests/test_import_smoke.py`

**Commit:** `chore: add src/btc_ml package skeleton`

### Phase 2 — Infrastructure layer

Move without logic changes:

| From (root) | To |
|-------------|-----|
| `runtime_config.py` | `src/btc_ml/config.py` |
| `parquet_utils.py` | `src/btc_ml/repositories/parquet/utils.py` |
| `state_guard.py` | `src/btc_ml/repositories/parquet/guard.py` |
| `state_manager_v1.py` | `src/btc_ml/core/state/manager.py` |
| `runtime_dependency_map.py` | `src/btc_ml/orchestration/dependency_map.py` |
| `runtime_dependency_guard.py` | `src/btc_ml/orchestration/dependency_guard.py` |
| `runtime_state_manager.py` | `src/btc_ml/orchestration/runtime_state.py` |
| `engine_registry.py` | `src/btc_ml/orchestration/engine_registry.py` |

Leave shims at root:

```python
# state_manager_v1.py (shim)
import warnings
warnings.warn("Import from btc_ml.core.state.manager", DeprecationWarning)
from btc_ml.core.state.manager import *  # noqa
```

**Commit:** `refactor: move infrastructure to src/btc_ml`

### Phase 3 — Auction pipeline services

Move engines one group at a time. Each move:

1. Copy file to `services/`
2. Fix imports to absolute `btc_ml.*`
3. Add root shim
4. Run master runtime one cycle
5. Commit

**Order (matches runtime loop):**

```
Group A: structure (candle, volume_class, schema, behavioral_sequence, observer, micro, volume_response)
Group B: auction (climactic, convergence, synthesis)
Group C: cognition (runtime_cognition, reinforcement, probabilistic, decay, state_transition, meta)
Group D: stage2 (climax, multi_timeframe, dataset_builder)
```

**Commit per group:** `refactor: move <group> engines to src/btc_ml`

### Phase 4 — Orchestration extraction

Extract loop from `master_auction_runtime_v1.py`:

```python
# src/btc_ml/orchestration/auction_pipeline.py
PIPELINE = [...]  # unchanged list

def run_once() -> None: ...
def run_forever(sleep_seconds: int = 5) -> None: ...
```

Root shim:

```python
# master_auction_runtime_v1.py
from btc_ml.orchestration.auction_pipeline import run_forever
run_forever()
```

**Commit:** `refactor: extract auction pipeline orchestration`

### Phase 5 — Stage 2 wiring (orchestration only)

Add to pipeline before `runtime_cognition_engine_v1.py`:

```python
# New step — wraps existing batch logic, no threshold changes
"stage2_cognition_batch.py"  # thin wrapper calling research_dataset_builder sections
```

Or schedule as cron between cycles. **Requires separate review** — flagged in `TODO_REVIEW.md`.

**Commit:** `feat: wire stage2 batch into auction pipeline (orchestration only)`

### Phase 6 — Research script relocation

Move to `scripts/research/`:

- All `*_backtest_v1.py`
- `auction_climax_visualizer_v1.py`
- `research/replay/` (already partially organized)

**Commit:** `chore: relocate research scripts`

### Phase 7 — Mirror archive

Execute `docs/DUPLICATE_RESOLUTION_PLAN.md` Phase C.

**Commit:** `chore: archive deprecated btc-microstructure-engine mirror`

### Phase 8 — DevOps alignment

- [ ] `pyproject.toml` with ruff, black, isort, mypy
- [ ] `Makefile`: `make run`, `make test`, `make lint`
- [ ] `.env.example`
- [ ] Update `README.md`
- [ ] Deprecate Docker compose or realign to master auction

**Commit:** `chore: add devops tooling and README`

---

## 4. Import Migration Pattern

**Before:**

```python
from state_manager_v1 import STATE, refresh_state
from parquet_utils import append_state_row
```

**After:**

```python
from btc_ml.core.state.manager import STATE, refresh_state
from btc_ml.repositories.parquet.utils import append_state_row
```

**Shim period:** Both work via root re-exports (2–4 weeks).

---

## 5. Parquet Path Strategy

During migration, **keep parquet files at repo root** (cwd-relative). Do not move parquet until Phase 9.

Phase 9 (future):

```
data/
├── live/
├── memory/
└── research/
```

Update `config.py` with `DATA_ROOT` env var — paths only, no logic.

---

## 6. Testing Gates (each phase)

| Gate | Requirement |
|------|-------------|
| Import smoke | `python -c "import btc_ml"` |
| Pipeline smoke | One `run_once()` without exception |
| Parquet continuity | Last row timestamps advance |
| No shim breakage | Root shims still importable |
| Git clean | One phase = one commit |

---

## 7. Timeline Estimate

| Phase | Effort | Risk |
|-------|--------|------|
| 0 Documentation | Done | Low |
| 1 Skeleton | 2 hours | Low |
| 2 Infrastructure | 4 hours | Medium |
| 3 Services (4 groups) | 2 days | Medium |
| 4 Orchestration | 4 hours | Medium |
| 5 Stage 2 wiring | 1 day | **High** — needs boundary fixes first |
| 6 Research move | 4 hours | Low |
| 7 Mirror archive | 2 hours | Medium |
| 8 DevOps | 1 day | Low |

---

## 8. Rollback

Each phase is one git commit. Rollback:

```bash
git revert HEAD
```

Shims ensure old entry points keep working until explicitly removed.

---

## 9. Out of Scope (this migration)

- Climax threshold recalibration (SELLING vs STOPPING)
- Removing `future_return_3` lookahead
- Fixing `process_auction_climax(dataset)` ignored param
- Docker production realignment
- Schema validation enforcement

These stay in `TODO_REVIEW.md` for post-migration domain review.

---

*See also: `docs/CANONICAL_RUNTIME_MAP.md`, `docs/DUPLICATE_RESOLUTION_PLAN.md`, `docs/RUNTIME_RESEARCH_BOUNDARY_VIOLATIONS.md`*
