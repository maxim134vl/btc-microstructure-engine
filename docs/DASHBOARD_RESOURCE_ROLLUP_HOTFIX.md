# Dashboard Resource Rollup Hotfix

## Problem

1. Memory pressure (e.g. 84%) was rolling into top **System Health** as Degraded /
   `OPERATIONAL_WITH_WARNINGS` with `primary_reason: Resource warning: memory N%`.
2. **Research / Validation** showed **Degraded** even when backend status was `ATTENTION`
   (governance missing, economic stale, shadow missing, toxic legacy).

## Root causes

### A. Resource → System Health

| Layer | Detail |
|---|---|
| Backend JSON | `health.display_status=OPERATIONAL_WITH_WARNINGS`, `health.primary_reason=Resource warning: memory …` |
| Backend | `resource_health_status` → `resources.status=DEGRADED`; `derive_system_health_level` rolled resources into system; `ops_monitor` overwrote `primary_reason` |
| Frontend | `resolveHealthLevel(…, OPERATIONAL_WITH_WARNINGS)` → tone/key `degraded` → label **Degraded** |
| Verdict | **Backend rollup + frontend mapper** |

### B. Research / Validation → Degraded

| Layer | Detail |
|---|---|
| Backend JSON | `health_dimensions.research_validation.status=ATTENTION` (correct) |
| Frontend | `resolveHealthDimensionStatus("ATTENTION")` → `system("degraded")` → label **Degraded** |
| Verdict | **Frontend mapper only** |

## Fix

- `derive_system_health_level`: runtime only; ignore resources (including CRITICAL).
- `_build_system_health`: do not add host memory/disk into critical health reasons.
- `ops_monitor`: never replace `primary_reason` with resource warning.
- `resolveHealthLevel`: `OPERATIONAL_WITH_WARNINGS` → Operational.
- `resolveHealthDimensionStatus`: ATTENTION / INCOMPLETE / STALE / MISSING_DATA → label ATTENTION|INCOMPLETE (not Degraded).

Resource cards and `health_dimensions.resources` unchanged.

## Out of scope

Model, pipeline, execution, feed, context viewer/refresher, retrain, benchmark.
