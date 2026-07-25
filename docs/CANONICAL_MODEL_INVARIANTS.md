# Canonical Model Invariants

Rules that future changes must not violate. Derived from architecture canon, shadow-chain contracts, and audited production defects. Read-only audit artifact — not a license to change production.

---

## I1 — No look-ahead

Every feature, memory row, decision, and fill must use only information available at or before the evaluation timestamp. Point-in-time / asof joins must not pull future bars.

## I2 — Source timestamp on every output

Engine outputs, memories, decision rows, and paper events must carry an explicit source/evaluation timestamp (not only file mtime).

## I3 — Missing ≠ NEUTRAL / BALANCE / OBSERVE

Absence of a feature, stale feed, failed engine, or empty join must not silently coerce to BALANCE, NEUTRAL, or OBSERVE unless that coercion is an explicit, logged policy with a distinct code (e.g. `MISSING_INPUT`).

## I4 — Fill ≠ context origin

Paper/live fills are economic events. Context origin is an episode anchor. They must never be treated as interchangeable for PnL or exit math.

## I5 — Context origin immutable inside an episode

Once a lifecycle episode opens with an origin price/time, that origin must not be rewritten by later bars, refreshes, or dashboard rebuilds.

## I6 — Reachable enums

Any state value documented or emitted in enums must be creatable by a live code path under production flags, or explicitly marked DEPRECATED / RESEARCH_ONLY / FLAG_GATED. Precedence must not make a state permanently unreachable.

## I7 — Local vs structural semantics stay separate

Local auction labels (effort/result, acceptance, balance) must not silently become structural regime labels. Dual-axis collapse into one string is forbidden on the trading path unless documented as intentional synthesis with retained axis fields.

## I8 — Research does not write production

Research scripts, candidates, audits, and dual-axis validators write only under `data/research/` (or explicit candidate suffixes). They must not mutate production memories or ledgers unless a separate, explicit production task says so.

## I9 — Feature flag OFF = baseline

With production flags at defaults (`BTC_ML_CONTINUATION_PROGRESSION=0`, PRICE_GATE OFF, etc.), behavior must match the frozen baseline. Flag ON paths must be opt-in and tested.

## I10 — Deterministic decision explanation

Every trading or paper action must map to a decision reason / gate chain that can be reconstructed from logged fields without consulting UI prose.

## I11 — Directional symmetry

Long and short / buyer and seller paths must use symmetric rules unless an asymmetry is explicitly documented and tested. Opposite-direction bugs are S0/S1 until proven intentional.

## I12 — Engines must not silently stop updating

If a registered production engine or memory tip falls behind its cadence beyond threshold, the system must surface skip/error/stale — not continue with a frozen tip disguised as current state.

## I13 — Consumers read the canonical active dataset

Downstream consumers (shadow, decision, paper, dashboard) must read the documented active path for each layer. Deprecated replacements and dual tips are defects until retired.

## I14 — Restart preserves lifecycle and position

Process restart must reload lifecycle episode state and open paper position from durable store. Restart must not invent a new episode origin or drop an open position silently.

## I15 — Two write planes stay explicit

Canonical pipeline memories and shadow-chain memories are separate planes. Merging them without a declared contract is an architectural violation.

## I16 — Paper ≠ exchange

Paper controller may simulate fills; it must never call exchange APIs or rewrite exchange-facing ledgers under the paper path.

## I17 — Event-sparse memories are not bar-continuous

Sparse event tables (e.g. MTF synthesis) must not be treated as dense per-bar truth without an explicit hold/forward policy and freshness semantics.

## I18 — Calibration discipline

Heuristic scores named `*_probability` are not calibrated probabilities until a documented calibration contract says so. Downstream must not treat saturation at 1.0 as certainty.

## I19 — Single active context granularity is declared

If the active context is global (current MVP), that is a declared invariant of the MVP. Introducing per-TF contexts requires an explicit granularity contract — not silent dual writers.

## I20 — Audit artifacts are non-authoritative for trading

CSVs/JSONs under `data/research/full_model_*` and audit docs are diagnostic. They must not become production inputs.

---

## Container-readiness invariants (Patch 2A.1)

These bind future Docker packaging. They do **not** authorize path migrations or compose files in this patch.

### I21 — Configuration via environment / config

Runtime configuration must arrive through environment variables and/or config files. New production components must not depend on the absolute host path `/Users/fontecrypto/...`. Repo root may be derived relative to the entrypoint or via `BTC_ML_ROOT`. Data paths must support an external volume root (`BTC_ML_DATA_ROOT`) without rewriting historical production paths until an explicit migration.

Planned variables:

```text
BTC_ML_ROOT
BTC_ML_DATA_ROOT
BTC_ML_LOG_LEVEL
BTC_ML_RUNTIME_MODE
BTC_ML_CONTEXT_REFRESH_DAEMON
```

### I22 — Long-lived logging to stdout/stderr

Every long-lived process must write primary logs to stdout/stderr, use line-buffered output, flush after important messages, and must not depend solely on a local log file. Logs must include structured timestamp, component name, and cycle/result/error fields.

Target line fields:

```text
timestamp
service
component
level
event
market_timestamp
cycle_id
message
```

### I23 — SIGTERM / SIGINT graceful shutdown

Each long-lived process must handle `SIGTERM` and `SIGINT`: stop accepting new work, finish the current atomic write, release locks, terminate children, exit with a clear code, leave no zombies, and leave no stale PID/lock files.

### I24 — Service healthchecks

Future Compose services must expose healthchecks.

- `model-runtime` healthy only if feed, pipeline, and context refresher are alive; dataset tips within freshness budgets; no duplicate writers; writer metadata updating.
- `ops-dashboard` healthy if the web process answers and runtime status is readable; missing model data is degraded/unhealthy for display, never a reason to write model data.
- `trade-chart` healthy if the web process answers and the read-model is available; absence of trades is not an error.

### I25 — Persistent volumes, not image-local parquet

Durable state lives on named volumes (`model-data`, `model-runtime-state`, `paper-ledger`). Source code and container image layers are not persistent parquet stores.

### I26 — Single context refresh owner

The only recurring production owner of context/lifecycle/decision catch-up is `DEDICATED_CONTEXT_REFRESHER`. Paper controller, visual refresher, and dashboard must not be silent second writers. On-demand refresh shares the same lock.
