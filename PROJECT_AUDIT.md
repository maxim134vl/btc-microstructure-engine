# PROJECT AUDIT — btc-ml

**Date:** 2026-05-26  
**Auditor role:** Staff Engineer / Solution Architect (production-readiness review)  
**Repository:** `/Users/fontecrypto/btc-ml`  
**Scope:** Full static audit before production refactor (Stage 1)

---

## Executive Summary

`btc-ml` is a **behavioral market microstructure / auction cognition system** built as a **flat collection of ~1,008 Python scripts** coordinated primarily through **Parquet memory files**, not through a Python package architecture.

The repository is **not production-grade today** in structure, despite containing working runtime components. Main blockers:

| Severity | Issue |
|----------|-------|
| **Critical** | **278 `.py` files in repo root** — no `src/` package, no clear ownership |
| **Critical** | **237 duplicate filenames** between root and `btc-microstructure-engine/` (**12 diverged**) |
| **Critical** | **4 competing orchestrators** with conflicting documentation |
| **High** | **Parquet-as-database** without schema registry enforcement at runtime |
| **High** | **God-file** `research_dataset_builder_v1.py` (1,781 lines) |
| **High** | **Lookahead / research logic** mixed into runtime paths (`future_return_3`, ignored `dataset` args) |
| **Medium** | `os.system()` orchestration, SSL disabled in collectors, sparse tests |
| **Medium** | Documentation drift (`SYSTEM_MAP` vs `README_RUNTIME` vs Docker compose) |

**Verdict:** Project is a **working research + prototype runtime**, not yet an engineering-grade repository. Refactor should **reorganize without rewriting domain logic**, with canonical paths for production vs research.

---

## Architectural Decisions (Approved 2026-05-26)

The following decisions supersede conflicting notes elsewhere in this document:

| Decision | Resolution |
|----------|------------|
| **Canonical runtime** | `master_auction_runtime_v1.py` |
| **Canonical source tree** | Repository root — `btc-microstructure-engine/` is **deprecated mirror** |
| **Production direction** | Stage 2 auction cognition: climax → MTF synthesis → runtime cognition → reinforcement → probabilistic → adaptive meta cognition |
| **Diverged duplicates (12)** | **Root versions canonical** — no merge required |
| **Behavioral logic** | **Frozen** during refactor — no threshold/calibration changes |
| **Refactor scope** | Consolidation, duplicate planning, runtime canonicalization, dependency/parquet mapping only |

**Deliverables from this decision set:**

- `docs/PARQUET_DEPENDENCY_MAP.md`
- `docs/CANONICAL_RUNTIME_MAP.md`
- `docs/DUPLICATE_RESOLUTION_PLAN.md`
- `docs/MIGRATION_PLAN_SRC_BTC_ML.md`
- `docs/RUNTIME_RESEARCH_BOUNDARY_VIOLATIONS.md`

**Deprecated (do not extend):** `autonomous_runtime_v2`, `run_canonical_pipeline`, `behavioral_runtime_loop_v1`, entire `btc-microstructure-engine/` mirror tree.

---

## 1. Current Structure

### 1.1 Top-level layout (observed)

```
btc-ml/                          (~2.0 GB total, mostly data/venv/parquet)
├── 278 × *.py                   ← unstructured root scripts (CRITICAL)
├── 153 × *.parquet              ← runtime memory / datasets
├── venv/                        ← local virtualenv (should not be committed)
├── btc-microstructure-engine/   ← near-full mirror (~237 duplicate .py names)
├── collectors/                  ← exchange data collectors
├── engines/                     ← legacy ML/narrative engines (14 loop scripts)
├── runtime/                     ← alternate orchestrators (canonical README path)
├── research/                    ← replay, backtests, analysis
├── archive/                     ← legacy cognition, mutation, reinforcement
├── legacy/                      ← old behavioral agents
├── tools/                       ← debug + patch scripts
├── docs/                        ← partial architecture docs
├── models/                      ← ML artifacts
├── datasets/                    ← dataset storage
├── memory/                      ← memory artifacts
├── registry/                    ← registry files
├── state/                       ← state artifacts
├── runtime-dashboard/           ← Node dashboard (node_modules present)
├── btc-auction-runtime/         ← separate subproject
└── requirements.txt             ← pip freeze (no pyproject.toml)
```

### 1.2 Scale metrics

| Metric | Count |
|--------|------:|
| Python files (excl. venv) | 1,008 |
| Root-level `.py` | 278 |
| Parquet files | 153 |
| Duplicate basenames (root ∩ microstructure-engine) | 237 |
| Identical duplicates | 225 |
| **Diverged duplicates** | **12** |
| Files with `if __name__ == "__main__"` | ~15 |
| Circular Python import cycles detected | 0 |

### 1.3 Intended target structure (from refactor spec)

Not yet implemented. Current repo does **not** match the target `src/project_name/` layout.

---

## 2. What the Project Does (Business Context)

The system ingests **live crypto market data** (primarily Binance 15m), builds **candle/microstructure features**, detects **behavioral auction states** (climax, convergence, synthesis, reinforcement), maintains **persistent parquet memory**, and runs **probabilistic cognition layers** for regime interpretation.

Two parallel product visions coexist:

1. **Auction cognition pipeline** — Wyckoff-style auction intelligence (`master_auction_runtime_v1.py`, climax, multi-TF synthesis, runtime cognition).
2. **Microstructure state machine** — geometry → localization → test recognition → defended liquidity (`run_canonical_pipeline.py`, Docker `autonomous_runtime_v2.py`).

These were never fully merged.

---

## 3. Entry Points

### 3.1 Production (Docker — `btc-microstructure-engine/`)

| Entry | Type | Purpose |
|-------|------|---------|
| `autonomous_runtime_v2.py` | `while True` (60s) | **Primary Docker pipeline** — 15 engines |
| `live_binance_feed_v2.py` | websocket loop | Writes `live_market_feed.parquet` |
| `collectors/multi_exchange_collector.py` | loop | Cross-exchange flow |
| `collectors/orderbook_collector.py` | loop | Orderbook snapshots |
| `collectors/liquidation_collector.py` | loop | Liquidations |
| `collectors/oi_collector.py` | loop | Open interest |
| Monitoring services (`monitoring/services/*/app.py`) | HTTP | Metrics, alerts, watchdog, health API |

### 3.2 Documented but not in Docker

| Entry | Docs claim | Status |
|-------|------------|--------|
| `runtime/run_canonical_pipeline.py` | README canonical (6-step v2) | Manual only |
| `master_auction_runtime_v1.py` | SYSTEM_MAP primary (16 engines) | Manual only — **Stage 2 focus** |
| `behavioral_runtime_loop_v1.py` | Behavioral sub-pipeline | Legacy parallel |
| `runtime/live_engine_runner.py` | ML inference chain | Legacy |

### 3.3 Research / batch

| Entry | Purpose |
|-------|---------|
| `research_dataset_builder_v1.py` | **God-file** — builds master research dataset + cognition export |
| `multi_timeframe_synthesis_engine.py` | Multi-TF behavioral synthesis |
| `auction_climax_engine_v1.py` | Climax detection (standalone + imported) |
| `multi_timeframe_dataset_builder.py` | TF aggregation helper |
| `runtime_cognition_engine_v1.py` | Loads cognition memory → STATE |
| `probabilistic_auction_engine_v1.py` | Probabilistic regime scoring |
| `research/replay/*.py` | Historical replay scripts |
| `*_backtest_v1.py` (50+ at root) | One-off backtests |

### 3.4 Invocation pattern

Most scripts use **top-level execution** (`while True` at module scope or inline batch logic), not `if __name__ == "__main__"`. Only ~15 files guard `__main__`.

---

## 4. Canonical Pipelines (Conflicting)

### Pipeline A — Docker production (`autonomous_runtime_v2.py`)

```
candle_geometry_incremental_v3
→ volume_localization_incremental_v3
→ test_recognition_engine_v1
→ defended_liquidity_engine_v1
→ live_volume_flow_engine_v1
→ flow_liquidity_interaction_engine_v3
→ intent_validation_engine_v1
→ live_mutation_runtime_engine_v1      ⚠ lives in archive/mutation_legacy/
→ cognitive_confidence_engine_v1
→ temporal_decay_engine_v2
→ volatility_adaptive_engine_v1
→ htf_structure_engine_v1
→ htf_ltf_context_engine_v1
→ fractal_memory_engine_v1
→ predictive_sequence_engine_v1
```

### Pipeline B — Auction cognition (`master_auction_runtime_v1.py`)

```
candle_structure_engine_v1
→ volume_classification_engine_v1
→ schema_validation_engine_v1
→ behavioral_sequence_memory_v1
→ behavioral_volume_observer_v1
→ microstructure_candle_engine_v1
→ volume_response_engine_v1
→ climactic_behavior_engine_v1
→ auction_convergence_engine_v1
→ auction_synthesis_engine_v1
→ runtime_cognition_engine_v1          ← root only
→ auction_reinforcement_engine_v1
→ probabilistic_auction_engine_v1
→ auction_decay_engine_v1
→ state_transition_engine_v1
→ adaptive_meta_cognition_engine_v1
```

### Pipeline C — README canonical (`runtime/run_canonical_pipeline.py`)

```
candle_geometry_engine_v2
→ volume_localization_engine_v2
→ test_recognition_engine_v1
→ defended_liquidity_engine_v1
→ perception_context_integration_v1
→ contextual_memory_loader_v2
```

**Documentation conflict:** `docs/SYSTEM_MAP.md` names Pipeline B as primary; `README_RUNTIME.md` names Pipeline C; Docker runs Pipeline A.

---

## 5. Dependency Map

### 5.1 Python import graph (sparse)

Real coupling is **Parquet I/O**, not Python imports. Hub modules:

```
state_manager_v1          (12 importers)  → STATE singleton, loads parquet at import
parquet_utils             (7 importers)   → safe read/append
engine_registry           (4 importers)   → eager import of 4 engines
state_guard               (4 importers)   → dedup persistence
runtime_dependency_map    (1 importer)    → partial parquet DAG
runtime_dependency_guard  (1 importer)    → gate engines on parquet freshness
```

**Multi-TF research chain (root only, acyclic):**

```
research_dataset_builder_v1
  → multi_timeframe_synthesis_engine
    → multi_timeframe_dataset_builder
      → auction_climax_engine_v1
        → state_manager_v1
```

**Engine registry hub (load-time side effects):**

```
master_auction_runtime_v1 → engine_registry
engine_registry → adaptive_meta_cognition_engine_v1
               → probabilistic_auction_engine_v1
               → auction_reinforcement_engine_v1
               → auction_convergence_engine_v1
```

### 5.2 Parquet dependency map (partial — from `runtime_dependency_map.py`)

```
volume_response_state.parquet ──→ auction_synthesis_engine_v1
htf_structure_memory.parquet  ──→ auction_synthesis_engine_v1
htf_ltf_context_memory.parquet ─→ auction_synthesis_engine_v1

auction_synthesis_memory.parquet ──→ probabilistic_auction_engine_v1
auction_reinforcement_memory.parquet → probabilistic_auction_engine_v1

auction_synthesis_memory.parquet ──→ state_transition_engine_v1
probabilistic_auction_memory.parquet → state_transition_engine_v1

auction_convergence_memory.parquet ──→ auction_decay_engine_v1
auction_reinforcement_memory.parquet → auction_decay_engine_v1
```

**Note:** `docs/PARQUET_DEPENDENCY_MAP.md` is **empty**. Full parquet graph is not documented.

### 5.3 Key memory files (STATE registry)

From `state_manager_v1.py`:

| Key | Parquet file |
|-----|--------------|
| `candle_structure` | `candle_structure_memory.parquet` |
| `auction_synthesis` | `auction_synthesis_memory.parquet` |
| `auction_convergence` | `auction_convergence_memory.parquet` |
| `auction_reinforcement` | `auction_reinforcement_memory.parquet` |
| `volume_response` | `volume_response_state.parquet` |
| `behavioral_sequence` | `behavioral_sequence_memory.parquet` |
| `probabilistic_auction` | `probabilistic_auction_memory.parquet` |
| `adaptive_meta_cognition` | `adaptive_meta_cognition_state.parquet` |

Stage 2 additions (root only):

| File | Purpose |
|------|---------|
| `multi_timeframe_synthesis.parquet` | MTF synthesis output |
| `runtime_cognition_memory.parquet` | Cognition export for runtime |

---

## 6. God-Files (largest / highest risk)

| Lines | File | Risk |
|------:|------|------|
| 1,781 | `research_dataset_builder_v1.py` | Monolithic batch script, mixed concerns, root-only |
| 988 | `volume_response_engine_v1.py` | Large engine, duplicated |
| 964 | `behavioral_volume_observer_v1.py` | Large engine, duplicated |
| 832 | `auction_climax_engine_v1.py` | Domain + debug prints + distribution loop |
| 644 | `collectors/multi_exchange_collector.py` | Collector complexity |
| 497 | `probabilistic_auction_engine_v1.py` | **12 diverged** vs engine copy |

---

## 7. Tightly Coupled Modules

| Coupling type | Modules | Mechanism |
|---------------|---------|-----------|
| Shared mutable state | All engines → `state_manager_v1.STATE` | Import-time parquet load + `refresh_state()` |
| Orchestration | `master_auction_runtime_v1` → 16 scripts | subprocess / registry / os.system |
| Persistence contract | Engines → `parquet_utils`, `state_guard` | Implicit column schemas |
| Research chain | MTF builder → climax → synthesis → cognition | Sequential imports + inline execution |
| Duplicate tree | root ↔ `btc-microstructure-engine/` | Same module names, 12 diverged |

---

## 8. Architecture Problems

### 8.1 No package boundary

- No `src/`, no installable package, no absolute import root.
- `sys.path[0]` (cwd) determines which duplicate module loads.

### 8.2 Parquet-as-database anti-pattern

- 153 parquet files act as mutable runtime DB.
- No unified schema validation at write time (partial `schema_validation_engine_v1`).
- Append-only patterns vary (`append_state_row`, direct `to_parquet`, overwrite).
- Race conditions possible if multiple processes write same file.

### 8.3 Orchestrator fragmentation

Four runtimes without single owner:

1. `autonomous_runtime_v2.py` (Docker)
2. `master_auction_runtime_v1.py` (auction cognition)
3. `runtime/run_canonical_pipeline.py` (README)
4. `behavioral_runtime_loop_v1.py` (behavioral)

### 8.4 Research / production boundary blurred

- `future_return_3` in climax stopping volume (lookahead).
- `process_auction_climax(dataset, timeframe)` ignores `dataset`, reads `STATE["candle_structure"]`.
- Debug `print()` inside library functions.
- `research_dataset_builder_v1.py` runs at import/top-level in some paths.

### 8.5 Version proliferation

Multiple evolution branches with no deprecation:

- `initiative_memory_engine_v1` … `v9`
- `flow_liquidity_interaction_engine_v1` … `v3`
- `autonomous_runtime_v1` / `v2`
- `temporal_decay_engine_v1` / `v2`
- `clean_stopping_test_v1` … `v3`

---

## 9. Bad Practices (observed)

| Practice | Examples | Impact |
|----------|----------|--------|
| Top-level `while True` | Most orchestrators/collectors | Not import-safe, hard to test |
| `os.system("python3 ...")` | `autonomous_runtime_v1/v2`, backups | Shell injection surface, no exit code handling |
| Module-level side effects | `state_manager_v1.refresh_state()` at import | Import = I/O |
| Placeholder paths | ~~`your_dataset.parquet`~~ (fixed) | Runtime crashes |
| Missing `__main__` guards | Most scripts | Accidental execution on import |
| Sparse formatting | Extra blank lines per operator | 800-line files with ~200 lines of logic |
| Magic thresholds | `0.80`, `0.45`, `1.20` hardcoded | No central constants |
| Duplicate code | 225 identical files × 2 trees | Drift risk (12 already diverged) |
| Empty docs | `docs/PARQUET_DEPENDENCY_MAP.md` | Operational blindness |

---

## 10. Circular Imports

**Static analysis result: 0 cycles detected.**

Latent cycle risks:

1. `engine_registry` eager imports — if any engine imports registry back, cycle forms.
2. `research_dataset_builder_v1` top-level execution — if synthesis imports builder, cycle forms.
3. Duplicate module shadowing — not a cycle but causes wrong-module bugs.

---

## 11. Duplication

### 11.1 Root vs `btc-microstructure-engine/` (237 files)

**12 diverged files (highest risk):**

| File | Root lines | Engine lines |
|------|----------:|-------------:|
| `state_manager_v1.py` | 96 | 74 |
| `master_auction_runtime_v1.py` | 187 | 119 |
| `probabilistic_auction_engine_v1.py` | 497 | 323 |
| `auction_reinforcement_engine_v1.py` | 424 | 259 |
| `auction_convergence_engine_v1.py` | 317 | 261 |
| `volume_response_engine_v1.py` | 988 | 937 |
| `auction_decay_engine_v1.py` | 229 | 247 |
| `auction_synthesis_engine_v1.py` | 325 | 305 |
| `behavioral_sequence_memory_v1.py` | 285 | 276 |
| `candle_structure_engine_v1.py` | 353 | 351 |
| `live_binance_feed_v2.py` | 362 | 263 |
| `state_transition_engine_v1.py` | 304 | 238 |

### 11.2 Root-only Stage 2 modules (not duplicated)

- `auction_climax_engine_v1.py`
- `multi_timeframe_synthesis_engine.py`
- `multi_timeframe_dataset_builder.py`
- `research_dataset_builder_v1.py`
- `runtime_cognition_engine_v1.py`
- `parquet_utils.py`, `runtime_config.py`, `runtime_cache.py`
- `state_guard.py`, `runtime_dependency_*`

---

## 12. Dead Code & Cleanup Candidates

### 12.1 Explicit archive (safe to relocate to `archive_removed/`)

- `archive/` — legacy cognition orchestrators v1–v4, mutation, reinforcement, predictive
- `legacy/` — behavioral agent v1–v8, unified agent v1–v4
- `legacy_archive/`

### 12.2 Backup files (12 at root — delete or archive)

```
*_backup.py, *_backup2.py
master_auction_runtime_v1_backup.py
master_auction_runtime_v1_backup2.py
live_binance_feed_v2_backup.py
collectors/*_backup.py
behavioral_sequence_memory_v1_backup.py
behavioral_sequence_memory_v1_incremental_backup.py
```

### 12.3 Generated inventory snapshots (not runtime)

```
project_structure.txt, python_files.txt, python_sizes.txt
top_python_sizes.txt, parquet_inventory.txt, directories_snapshot.txt
(duplicated under btc-microstructure-engine/)
```

### 12.4 Superseded runtimes

- `autonomous_runtime_v1.py` → superseded by v2
- `master_auction_runtime_v1_backup*.py`
- `archive/legacy_cognition/live_cognitive_orchestrator_v1–v4.py`
- `initiative_memory_engine_v1–v9` (keep one canonical or archive rest)

### 12.5 Broken / suspect

- `research_lab.py` — reported indentation bug in loop body
- `live_mutation_runtime_engine_v1.py` — in `archive/` but still called by Docker prod pipeline

---

## 13. Naming Problems

| Pattern | Issue |
|---------|-------|
| `*_v1.py`, `*_v2.py`, … `*_v9.py` | No registry of which version is canonical |
| Mixed suffixes | `_engine_v1`, `_backtest_v1`, `_visualizer_v1` all at same root level |
| Misleading names | `realtime_streaming_engine_v1.py` — replays parquet, not live stream |
| Duplicate basenames | 237 files exist in two locations |

---

## 14. Dependency Problems

- `requirements.txt` is a **full pip freeze** (~100+ packages) with no separation dev/prod.
- No `pyproject.toml`, no pinned version strategy, no optional extras.
- Jupyter, streamlit, altair in same env as runtime — bloat + attack surface.
- No `constraints.txt` or dependabot.

---

## 15. Security Findings (preview — full report in Stage 6)

| Category | Status |
|----------|--------|
| Hardcoded API keys / secrets in source | **None found** |
| `eval` / `exec` | **None found** |
| `os.system()` | **10+ files** — medium risk |
| SSL verification disabled | **5 collector patterns** |
| CORS `*` + credentials | `monitoring_api_v1.py` |
| Dynamic subprocess script names | `master_auction_runtime_v1.py` pipeline |
| `.env` handling | Examples only; `.env` gitignored |

---

## 16. Logging Problems

- No unified logging module — **`print()` everywhere**.
- No log levels, no structured logs, no rotation config in app code.
- Docker monitoring stack has proper logging; **engines do not**.

---

## 17. Suspicious / High-Risk Locations

| Location | Concern |
|----------|---------|
| `auction_climax_engine_v1.py` | SELLING/STOPPING merge; `future_return_3` lookahead; ignores `dataset` param |
| `state_manager_v1.py` (2 versions) | Diverged STATE keys — root has `candle_structure`, engine copy may not |
| `research_dataset_builder_v1.py` | God-file; runs entire Stage 2 inline |
| `autonomous_runtime_v2.py` | Calls engine in `archive/mutation_legacy/` |
| `engine_registry.py` | Eager heavy imports at module load |
| `probabilistic_auction_engine_v1.py` | Was missing `__main__` (fixed); conviction math can exceed 1.0 |

---

## 18. Refactoring Risks

| Risk | Mitigation |
|------|------------|
| Breaking parquet schemas on move | Schema registry + migration scripts first |
| Wrong duplicate loaded after restructure | Single `src/` package; delete mirror tree |
| Runtime downtime during migration | Keep legacy entrypoints as thin wrappers |
| Business logic drift | Do not change thresholds during structural refactor |
| Stage 2 climax logic | Defer to post-audit (user requested) |
| Docker prod uses different pipeline than Stage 2 | Explicit `PRODUCTION_PIPELINE` vs `RESEARCH_PIPELINE` env flag |

---

## 19. Proposed Target Architecture

```
src/btc_ml/
├── main.py                    # unified CLI entry
├── cli.py
├── config.py                  # env-based settings
├── constants.py               # thresholds (climax, synthesis)
├── core/
│   ├── state/                 # STATE registry, refresh
│   └── exceptions.py
├── services/
│   ├── auction/               # climax, convergence, synthesis, reinforcement
│   ├── cognition/             # runtime cognition, probabilistic, meta
│   ├── microstructure/        # geometry, localization, test recognition
│   └── synthesis/             # multi-TF synthesis
├── repositories/
│   └── parquet/               # parquet_utils, append_state_row, schemas
├── models/                    # dataclasses for auction states
├── schemas/                   # parquet column contracts
├── integrations/
│   └── collectors/            # binance, orderbook, oi, liquidations
├── orchestration/
│   ├── production_pipeline.py # autonomous v2 (or merged canonical)
│   ├── auction_pipeline.py    # master auction runtime
│   └── research_pipeline.py   # dataset builder chain
└── logging/
    └── setup.py

scripts/                       # one-off research backtests (moved from root)
archive_removed/               # backups, legacy, snapshots
tests/
docs/
configs/
```

### Pipeline ownership (recommended)

| Pipeline | Owner module | Environment |
|----------|--------------|-------------|
| Data collection | `integrations/collectors` | production |
| Auction cognition (Stage 2) | `orchestration/auction_pipeline.py` | research → production |
| Microstructure v2 | `orchestration/production_pipeline.py` | production Docker |
| Backtests | `scripts/research/` | dev only |

---

## 20. Migration Candidates

### Move to `src/btc_ml/` (core — keep logic, change path)

- `state_manager_v1.py` → `core/state/manager.py`
- `parquet_utils.py` → `repositories/parquet/utils.py`
- `state_guard.py` → `repositories/parquet/guard.py`
- `auction_climax_engine_v1.py` → `services/auction/climax.py`
- `multi_timeframe_synthesis_engine.py` → `services/synthesis/multi_timeframe.py`
- `runtime_cognition_engine_v1.py` → `services/cognition/runtime.py`
- `probabilistic_auction_engine_v1.py` → `services/cognition/probabilistic.py`
- `master_auction_runtime_v1.py` → `orchestration/auction_pipeline.py`

### Move to `scripts/research/`

- All `*_backtest_v1.py` (~50+ files)
- `research_dataset_builder_v1.py` (after split)
- `auction_climax_visualizer_v1.py`

### Move to `archive_removed/`

- 12 `*_backup*.py` files
- `archive/`, `legacy/` contents
- Inventory snapshot `.txt` files
- Superseded `initiative_memory_engine_v1–v8` (keep v9 or latest only)

### Delete after verification

- Duplicate `btc-microstructure-engine/` tree (after merging into `src/`)
- `venv/` from git if tracked
- `runtime-dashboard/node_modules/` if tracked

---

## 21. Recommended Refactor Phases (Stages 2–10 preview)

| Stage | Deliverable | Priority |
|-------|-------------|----------|
| 2 | `docs/BUSINESS_ANALYSIS.md` | P0 |
| 3 | Create `src/btc_ml/` skeleton + move core modules | P0 |
| 4 | PEP8 tooling (ruff, black, isort) | P1 |
| 5 | `docs/DEAD_CODE_REPORT.md` + archive_removed | P1 |
| 6 | `docs/SECURITY_REVIEW.md` + fix SSL/CORS/os.system | P1 |
| 7 | `tests/` smoke + pytest | P1 |
| 8 | `docs/CODE_REVIEW.md` | P2 |
| 9 | pyproject.toml, Makefile, Docker unify | P1 |
| 10 | README, CHANGELOG, TODO_REVIEW | P0 |

---

## 22. Immediate Actions (before code moves)

1. **Declare canonical source tree:** root vs `btc-microstructure-engine/` — recommend **root → src/**, deprecate mirror.
2. **Declare canonical runtime:** align Docker, README, SYSTEM_MAP to one orchestrator (or two: `production` + `research`).
3. **Freeze threshold changes** — structural refactor only until climax audit completes.
4. **Populate `docs/PARQUET_DEPENDENCY_MAP.md`** — required for safe moves.
5. **Add `TODO_REVIEW.md`** — track diverged 12 files and mutation-in-prod mismatch.

---

## 23. Open Questions for Product Owner

1. Which pipeline is **production truth** today: Docker A, Auction B, or README C?
2. Is Stage 2 (climax + MTF synthesis + runtime cognition) intended to **replace** or **augment** Docker pipeline?
3. Can `btc-microstructure-engine/` be deleted after merge, or is Docker bound to that path?
4. Research lookahead (`future_return_3`) — allowed in research-only mode only?
5. Which `initiative_memory_engine_v*` is canonical?

---

## Appendix A — Existing Documentation Inventory

| File | Status |
|------|--------|
| `README_RUNTIME.md` | Partial — describes Pipeline C only |
| `docs/SYSTEM_MAP.md` | Stale (2026-05-14) — Pipeline B |
| `docs/RUNTIME_TOPOLOGY.md` | Exists — needs cross-check |
| `docs/ENGINE_CONTRACT.md` | Exists |
| `docs/MIGRATION_STATUS.md` | Exists |
| `docs/PARQUET_DEPENDENCY_MAP.md` | **Empty** |
| `migration_audit_notes.md` | Informal notes — still accurate |

---

## Appendix B — Audit Methodology

- Static file tree analysis (`find`, line counts)
- Import graph via regex (1,008 files)
- Subagent exploration: entry points, security grep, duplication MD5
- Runtime verification of Stage 2 scripts (prior session)
- Circular import DFS on flat module names
- Manual review of orchestrators and STATE registry

---

*End of Stage 1 audit. Next step: Stage 2 `docs/BUSINESS_ANALYSIS.md` and `TODO_REVIEW.md`.*
