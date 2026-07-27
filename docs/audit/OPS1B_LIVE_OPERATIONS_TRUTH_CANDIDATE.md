# OPS1B — Live Operations Truth Candidate

**Status:** `OPS1B_LIVE_OPERATIONS_TRUTH_CANDIDATE_READY`  
**UTC:** 2026-07-27  
**Branch:** `memory/canonical-system`  
**Base HEAD:** `bd4c267`  
**Mode:** candidate only — no OPS API / pipeline / manager / trader restart

---

## A. Result

Isolated OPS runtime-truth candidate restores active conditional pipeline parsing (26 live steps), section failure isolation, PID-based runtime age, and process/trader/context truth without touching core runtime or restarting OPS API PID `22716`.

## B. Core Runtime Health

| Role | PID | Status |
| ---- | --- | ------ |
| pipeline | 4618 | ALIVE (unchanged) |
| OPS API | 22716 | ALIVE (unchanged; not restarted) |
| manager | 61283 | ALIVE |
| M15–H4 traders | 61284–61287 | ALIVE |
| visual refresher | 84045 | ALIVE |

`pipeline restarts = 0`, `OPS API restarts = 0`, `manager/trader restarts = 0`.

## C. Baseline Failure Reproduction

Top-level-only AST walk against current `pipeline.py`:

```text
top_level_CANONICAL_PIPELINE_found = false
→ RuntimeError: CANONICAL_PIPELINE not found
```

| Field | Value |
| ----- | ----- |
| exception type | `RuntimeError` |
| message | `CANONICAL_PIPELINE not found` |
| source | `ops_dashboard_runtime_truth.parse_canonical_pipeline` |
| blast radius (ops_monitor fail-close) | `processes=[]`, `timeframe_traders={}`, `context_chain={}` |

Evidence: `data/candidate/architecture_recovery/ops1b_live_operations_truth_candidate/baseline_failure.json`  
Diagnosis: `docs/audit/OPS1A_LIVE_OPERATIONS_TRUTH_DIAGNOSIS.md`

## D. Conditional Pipeline Contract

Resolver walks nested `if` / `else`, finds `CANONICAL_PIPELINE = builder_call()`, resolves only safe builders:

- `canonical_pipeline_with_stage2_synthesis_inputs_candidate`
- `canonical_pipeline_with_volume_localization_candidate`

No `eval` / `exec` / `import pipeline.py`.

## E. Active Branch Resolution

| Flags | Builder | Steps |
| ----- | ------- | ----: |
| `STAGE2=1` (live) | `…_stage2_synthesis_inputs_candidate` | 26 |
| `STAGE2=0` (isolated) | `…_volume_localization_candidate` | 21 |

## F. Pipeline Metadata

`pipeline_metadata.py` loads exclusively via `resolve_active_canonical_pipeline()`:

- `active_builder`, `active_flags`
- `ordered_engine_names`, `total_engine_count = len(…)`
- `required_engine_names` / `required_engine_count` (3 health gates)
- `informational_engine_names`, `ignored_by_health`
- no hardcoded `expected 20`

## G. Engine Count and Order

Live: **26** steps; order preserved from builder composition (candle → volume_localization → … → stage2 / runtime cognition / reinforcement / probabilistic).

## H. Phantom Engines

`volume_localization_engine_v1.py` removed from `PHANTOM_ENGINES` while active in resolved pipeline. Remaining phantoms are legacy modules absent from active list.

## I. Failure Isolation

`build_runtime_truth_snapshot()` builds independent sections. Injected parser failure → `section_errors.pipeline_metadata` set; processes / traders / context remain populated. Global empty fail-close removed from the truth builder (live OPS still needs OPS1C reload to pick this up).

## J. Process Truth

Candidate finds pipeline `4618`, manager `61283`, M15–H4 `61284–61287` with `role/pid/alive/create_time/uptime_seconds/command`.

## K. Timeframe Trader Truth

`timeframe_traders` contains M15/M30/H1/H4 with pid/alive + book tip / open position fields already in contract.

## L. Context Chain

Independently restored after isolation fix:

| Field | Status |
| ----- | ------ |
| lifecycle_tip | RESTORED |
| final_context_tip / safe_upstream_tip | RESTORED |
| decision_tip | present key; value may be null when source empty |
| trading_state / market_state / bias / intent | OUTSIDE_CURRENT_CONTRACT / absent keys (not invented) |

## M. Manager / Portfolio Fields

| Field | Class |
| ----- | ----- |
| manager process | RESTORED |
| command tip / per-TF commands | RESTORED |
| command bus | RESTORED |
| open risk / realized / unrealized PnL | OUTSIDE_CURRENT_CONTRACT or SOURCE as already exposed — not recalculated |

## N. Runtime Uptime

```text
runtime_uptime_seconds = now - Process(pipeline_pid).create_time()
source = pipeline_pid_create_time
host_boot_time_substituted = false
```

Missing PID → `null` + `PIPELINE_PID_UNAVAILABLE`.

## O. Health Semantics

Candidate `overall_health = OPERATIONAL_WITH_LIMITATIONS` (D1 not live; auction_synthesis known non-required limitation) — not forced to `HEALTHY`.  
`runtime_truth_unavailable` no longer applies to candidate builder (`section_errors={}`).

Deferred (unchanged alert policy; would need 3rd production file): `OPS-HEALTH-ALERT-CONTRACT-MISMATCH`.

## P. Candidate Parity

| Field | Canonical | Candidate |
| ----- | --------: | --------: |
| pipeline PID | 4618 | 4618 |
| pipeline steps | 26 | 26 |
| manager alive | true | true |
| M15–H4 alive | true | true |
| runtime uptime | PID age | PID age (~2.7h) |

`process/trader/pipeline step parity = 100%`.

## Q. Resilience Scenarios

| Scenario | Result |
| -------- | ------ |
| A current conditional | 26 steps, no exception |
| B alt flags | 21 steps, vol-loc builder |
| C parser injection | metadata UNKNOWN; processes/traders/context kept |
| D missing PID | uptime null; no host boot |
| E active volume_localization | phantom = false |

## R. Tests

- `tests/test_ops1b_live_operations_truth_candidate.py` (new)
- `tests/test_patch4_2_ops_dashboard_runtime_truth.py` (aligned to dynamic counts / isolation)

`54 passed` (ops1b + patch4.2).

## S. Production Scope

```text
production files changed = 2
  1. ops_dashboard_runtime_truth.py
  2. dashboard/backend/app/pipeline_metadata.py
pipeline.py = 0
manager/traders/frontend = 0
```

Frontend still shows required-gate `3/3` vs total 26 until a later OPS UI stage — recorded as follow-up (no frontend change in OPS1B).

## T. Git Commit

Local only: `fix: restore OPS truth from active pipeline metadata`  
Gitea/GitHub push: **NOT PERFORMED**

## U. Compliance

```text
pipeline restarts = 0
OPS API restarts = 0
manager/trader restarts = 0
live OPS writes = 0
trading writes = 0
Gitea push = NOT PERFORMED
GitHub push = NOT PERFORMED
```

## V. Next Step

**OPS1C — controlled OPS API-only activation** (restart only PID `22716`; leave core/manager/traders running).

---

## Artifacts

```text
data/candidate/architecture_recovery/ops1b_live_operations_truth_candidate/
  baseline_failure.json
  resolved_pipeline_metadata.json
  candidate_runtime_truth.json
  process_truth.json
  timeframe_traders.json
  context_chain.json
  candidate_parity.json
```
