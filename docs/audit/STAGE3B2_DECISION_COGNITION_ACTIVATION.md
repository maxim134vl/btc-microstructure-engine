# Stage 3B2 — Controlled Live Activation (Decision Cognition Bridge)

**Status:** `STAGE3B2_ACTIVATION_ROLLED_BACK`  
**UTC date:** 2026-07-26  
**Branch:** `memory/canonical-system`  
**Activation commit attempted:** `063e03d` — `fix: prepare current decision cognition from auction state`  
**Rollback commit:** `739d57a` — `Revert "fix: prepare current decision cognition from auction state"`  
**Private Gitea tip (unchanged):** `713ef3b`  
**GitHub push:** NOT PERFORMED

## A. Result

Activation of Path B decision-cognition bridge failed first-cycle gate:

```text
runtime_cognition_engine_v1.py → exit 1
ValueError: merge on datetime64[us, UTC] and datetime64[us] for key 'timestamp'
```

`stage2_cognition_runtime_v1.py` succeeded on first cycle and briefly produced current evaluation snapshots (`LATEST COGNITION TIMESTAMP: 2026-07-26 19:15:00+00:00` with preserved lineage `2026-07-25 08:45:00` and auction carry `STRUCTURAL_COMPRESSION`). Downstream `runtime_cognition_engine_v1` then failed inside `enrich_alignment_status()` (`runtime_integrity.py`) when merging tz-aware evaluation timestamps against naive MTF event timestamps.

Per Stage 3B2 contract (no production source edits), activation was rolled back. No second activation attempt.

## B. Pre-Activation Stage 1–2 Health

| Check | Result |
| --- | --- |
| `localization_join_status` | `EXACT_FRESH_MATCH` (last 20) |
| Flow tip | `2026-07-26 19:15:00Z` (= candle tip) |
| Liquidity clusters | current-market relevant (live zones) |
| Interaction | tip fresh; recent non-neutral present (`compression_inside_liquidity`) |
| HTF / HTF-LTF | fresh with known 1-bar lag |
| Auction synthesis | executing; tip wall-clock advancing; last valid `STRUCTURAL_COMPRESSION` |
| Pipeline | PID `61126`, 26 steps, count=1 |

## C. Activation Mechanism

Restart-only (no new flag). Proven necessary:

| Fact | Value |
| --- | --- |
| Process start | Sun Jul 26 20:39:36 2026 (local) |
| Commit `063e03d` time | 2026-07-26 22:25:42 +0300 |
| Pre-restart cognition tip | `2026-07-25 08:45` |
| Pre-restart MTF tip | `2026-07-25 08:45` |

## D. Source Scope

```text
source changes during Stage 3B2 activation window = 0
```

Production edits during activation: none. Rollback used `git revert 063e03d` only.

## E. Tests

Relevant suites (excluding known live-parity flake): **77 passed**.

Deferred irrelevant failure:

```text
tests/test_stage2b11a_flow_interaction_candidate.py::test_interaction_v3_historical_label_parity
```

Reads root `liquidity_clusters_memory.parquet` vs live cognition clusters; not caused by `063e03d`.

## F. Launch Contract

Unchanged proven contract:

- Cellar Python 3.11
- `run.py`
- `Popen(..., start_new_session=True)`
- stdout/stderr → `logs/runtime_stack/runtime.log`
- PID file → `logs/runtime_stack/runtime.pid`

## G. Dual-Start Protection

```text
pre-stop count = 1
post-stop count = 0
post-start count = 1
duplicate starts = 0
```

## H. Old / New Pipeline PID

| Role | PID |
| --- | --- |
| Pre-activation | `61126` |
| Activation attempt | `33374` (PPID=1) |
| Post-rollback Stage 2 | `36571` (PPID=1) |

## I. Runtime Flags

Unchanged throughout:

```text
BTC_ML_ENGINE_EXECUTION_MODE=persistent_worker
BTC_ML_VOLUME_LOCALIZATION_LIVE=1
BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE=1
BTC_ML_CONTINUATION_PROGRESSION=0
```

## J. Pre-Activation Artifact Snapshot

Quarantine (copy, not move):

```text
data/quarantine/architecture_recovery/stage3b2/20260726_193817/
```

Key pre tips:

| Artifact | Rows | Tip |
| --- | --- | --- |
| multi_timeframe_synthesis | 167 | 2026-07-25 08:45 |
| runtime_cognition_memory | 167 | 2026-07-25 08:45 |
| candle_structure | 6999 | 2026-07-26 19:15 |
| auction_synthesis | 898 | 2026-07-26 19:30:37 wall-clock |

## K. First Full Cycle

| Engine | Status |
| --- | --- |
| `stage2_cognition_runtime_v1` | SUCCESS — evaluation tip advanced to candle tip |
| `runtime_cognition_engine_v1` | **FAILED** — tz merge in `enrich_alignment_status` |
| Pipeline steps | 26 |
| Gate | `STAGE3B2_FIRST_CYCLE_FAILURE` → rollback |

## L–T. Gates Not Completed

Three natural M15 bars, writer-order end-state, consumer multi-bar proof, and Gitea push were **not** executed after first-cycle failure.

Observed before rollback (informational):

- stage2 wrote ~6995 evaluation rows with lineage preserved and auction carry
- MTF event tip remained `2026-07-25 08:45` (no fabricated climax)
- failure was consumer/alignment merge dtype, not fabricated events

## U. Context / Trading Safety

No Stage 3B2 fixes to context/lifecycle/traders. Paper-only flags preserved on manager/traders. Historical trading books not rewritten by activation tooling.

## V. Preserved Processes

Feeds, watchdog, refreshers, manager, M15–H4 traders, OPS, Vite remained up across activation/rollback. Pipeline was the only deliberate restart target.

## W. Deferred Issues

See `docs/audit/DEFERRED_ISSUES_REGISTER.md` additions for Stage 3B2.

## X. Git / Private Gitea

| Action | Result |
| --- | --- |
| Local revert | `739d57a` |
| Gitea push | NOT PERFORMED |
| GitHub push | NOT PERFORMED |

## Y. Compliance

```text
pipeline intentional restarts (activation) = 1
rollback relaunch = 1
duplicate starts = 0
other deliberate restarts = 0
source changes during activation = 0
GitHub push = NOT PERFORMED
```

## Z. Next Step

Do **not** proceed to Stage 4.

Next candidate work (outside this activation stage) must fix timezone normalization before `enrich_alignment_status` merge (or equivalent fail-closed path) without fabricating climax/MTF events — then re-attempt activation as a new stage with explicit scope.

Candidate commit remains in history at `063e03d` for reference; live HEAD after rollback is `739d57a` (Stage 2 integrated synthesis still live).
