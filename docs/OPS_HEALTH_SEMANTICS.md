# Ops Health Semantics

Stage 13 separates three independent status layers so research gaps and
historical audits no longer paint current Runtime Health as degraded.

## Layers

### A. Runtime Health

Current infrastructure only:

- runtime / API / feed / websocket / collectors
- pipeline cycling
- failed engines (required)
- **current** stalls/timeouts (last 15 minutes)
- active runtime failures
- required datasets live
- actionable alerts

Statuses: `OPERATIONAL` | `DEGRADED` | `CRITICAL`

### B. Research / Validation Completeness

Does **not** degrade Runtime Health:

- `GOVERNANCE_MISSING` / promotion NO
- economic `STALE_VALIDATION / HISTORICAL`
- shadow `MISSING_DATA`
- toxic `LEGACY_ONLY / STALE`
- missing classic ML metrics
- benchmark diagnostics can still be CURRENT

Status: `OPERATIONAL` | `ATTENTION` | `STALE` | `MISSING_DATA`

### C. Historical Audit

Informational:

- historical failure counts
- historical stalls/timeouts (older than 15 minutes)
- latest historical failure / stall timestamps
- dependency skip history

Status: `INFORMATIONAL` | `ATTENTION`

## System Health

Top System Health uses **runtime + critical resources only**.

- Soft memory pressure (e.g. 84%) → Resource Warning / `OPERATIONAL_WITH_WARNINGS`
- Does **not** become degraded because governance is missing
- Does **not** become degraded because toxic is legacy-only
- Does **not** become degraded because economic validation is stale
- Does **not** become degraded because shadow metrics are missing
- Does **not** become degraded because historical failures exist

## Current vs historical stalls

| Class | Rule |
|---|---|
| Current | TIMESTAMP within 15 minutes, or live required engine TIMEOUT count |
| Historical | Older TIMEOUT / STALL_DETECTED in blocking chain |

UI:

- `Current stalls/timeouts: 0` → Runtime Stability Operational
- `Historical stalls/timeouts: 1` → Historical Audit only
- Never show `Stalls & timeouts 1 Lagging` for historical-only events

## Toxic top status

- `ELEVATED` only when **current** toxic metrics exist and breach rate thresholds
- `LEGACY_ONLY / STALE` when benchmark has no toxic fields and parquet baseline is historical
- Legacy baseline alone must never show `TOXIC Elevated`

## Economic / Shadow / Governance

| Signal | Layer | Runtime impact |
|---|---|---|
| Economic stale | Research | none |
| Shadow MISSING_DATA | Research | none |
| Governance missing | Research (blocks promotion) | none |

## Resource Warning

Resources card may show Memory Degraded at ≥75% memory.

That is a **resource** warning, separate from Runtime Health Operational.

## Payload

`GET /api/v1/ops/snapshot` includes:

```text
health_dimensions:
  runtime: { status, reason, current_failures_count, ... }
  resources: { status, cpu_pct, memory_pct, disk_pct, reason }
  research_validation: { status, governance_status, economic_status, shadow_status, toxic_status, reason }
  historical_audit: { status, historical_failures_count, historical_stalls_count, ... }
```

## Non-goals

- no model / retrain / pipeline / execution changes
- no market-context refresher changes
- no benchmark producer changes
- does not hide real current failures
