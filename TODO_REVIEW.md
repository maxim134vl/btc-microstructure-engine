# TODO_REVIEW — Manual Review Required

Items flagged during Stage 1 audit (`PROJECT_AUDIT.md`) that need **human decision** before automated refactor.

---

## P0 — Architecture decisions (block refactor)

- [ ] **Canonical runtime:** Choose one — Docker `autonomous_runtime_v2`, `master_auction_runtime_v1`, or `run_canonical_pipeline`
- [ ] **Canonical source tree:** Root vs `btc-microstructure-engine/` — recommend merge to `src/btc_ml/` and remove mirror
- [ ] **Stage 2 scope:** Is auction cognition pipeline (climax + MTF synthesis + runtime cognition) the new production path?
- [ ] **Mutation engine in Docker:** `live_mutation_runtime_engine_v1.py` lives in `archive/mutation_legacy/` but is in prod compose — remove or restore?

---

## P0 — Diverged duplicate files (12) — pick canonical version

| File | Action needed |
|------|---------------|
| `state_manager_v1.py` | Root has `candle_structure`; engine copy differs (74 vs 96 lines) |
| `master_auction_runtime_v1.py` | Root has cognition step + dependency guard |
| `probabilistic_auction_engine_v1.py` | Root 497 lines vs engine 323 lines |
| `auction_reinforcement_engine_v1.py` | Diff review |
| `auction_convergence_engine_v1.py` | Diff review |
| `volume_response_engine_v1.py` | Diff review |
| `auction_decay_engine_v1.py` | Diff review |
| `auction_synthesis_engine_v1.py` | Diff review |
| `behavioral_sequence_memory_v1.py` | Diff review |
| `candle_structure_engine_v1.py` | Diff review |
| `live_binance_feed_v2.py` | Diff review |
| `state_transition_engine_v1.py` | Diff review |

---

## P1 — Domain logic (defer until after full audit)

- [ ] **Climax separation:** SELLING_CLIMAX vs STOPPING_VOLUME merge in same cluster — redesign effort/result discriminators
- [ ] **`process_auction_climax(dataset, timeframe)`** ignores `dataset` — use passed dataset or remove param
- [ ] **`future_return_3`** in stopping volume — research-only or replace with live-safe signals
- [ ] **`conviction_probability`** can exceed 1.0 in probabilistic engine — verify intentional

---

## P1 — Security fixes (low risk, can automate)

- [ ] Replace `os.system()` with `subprocess.run([...])` in orchestrators
- [ ] Re-enable SSL verification in collectors (`verify=False` patterns)
- [ ] Fix CORS in `monitoring_api_v1.py` (`allow_origins=["*"]` + `allow_credentials=True`)

---

## P2 — Cleanup candidates (verify imports first)

- [ ] Move 12 `*_backup*.py` to `archive_removed/`
- [ ] Move `archive/`, `legacy/` to `archive_removed/`
- [ ] Remove inventory snapshot `.txt` files from repo root
- [ ] Consolidate `initiative_memory_engine_v1–v9` — keep one canonical version
- [ ] Fix or remove broken `research_lab.py`

---

## P2 — Documentation gaps

- [ ] Populate empty `docs/PARQUET_DEPENDENCY_MAP.md`
- [ ] Reconcile `docs/SYSTEM_MAP.md` vs `README_RUNTIME.md` vs Docker compose
- [ ] Add root `README.md` (only `README_RUNTIME.md` exists today)

---

*Updated: 2026-05-26 — Stage 1 audit*
