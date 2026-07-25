# Ops Health Semantics

OPS dashboard separates three independent status planes so research gaps and
historical audits no longer paint current live operational health as failed.

## Planes

### A. Live Operational Health

Answers only: is the paper trading runtime working right now?

- required processes (feed, pipeline, context, manager, M15/M30/H1/H4 traders)
- command bus / positions / risk
- active failures and current stalls
- required dataset freshness (with event-driven `CURRENT_UNCHANGED`)
- actionable alerts
- resources (display); sustained critical resource pressure may escalate

Top System Health statuses:

```text
OPERATIONAL
OPERATIONAL_WITH_LIMITATIONS
DEGRADED
FAILED
```

### B. Known Limitations

Non-alarms that describe expected gaps:

- `D1_NOT_LIVE` / `EXPECTED`
- `AUCTION_SYNTHESIS` / `NON_REQUIRED`
- legacy paper controller `MIGRATED` / `NOT_REQUIRED`
- research readiness incomplete
- Toxic Box historical-only

These never create Active Alerts and do not degrade live health by themselves.

### C. Research / Historical

Non-blocking:

- governance missing
- economic validation historical/stale
- shadow unavailable
- drift current metrics unavailable
- Toxic Box historical baseline (3,879 events retained)
- historical failures / stalls (audit only)

Statuses include `RESEARCH_INCOMPLETE`, `MISSING_NON_BLOCKING`, `HISTORICAL_ONLY`,
`NON_BLOCKING`.

## Active Alerts

Only actionable live problems. Explicitly excluded:

- D1 not live
- auction synthesis non-required
- missing governance
- stale economic validation
- missing shadow
- historical Toxic Box
- phantom / excluded modules
- historical failures / stalls

## Paper Controller

After S4 cutover:

```text
Legacy Paper Controller
MIGRATED · NOT REQUIRED
Replaced by independent M15, M30, H1 and H4 traders
```

Absence is not a failure.

## Phantom / Excluded Modules

Shown only under Legacy / Excluded Modules with:

```text
NOT_IN_CANONICAL_RUNTIME
DEPRECATED
HISTORICAL_ONLY
REMOVED
```

Never `Running` / `Receiving Data` / `Failed`. Excluded from engine totals.

## Probabilistic parquet

Event-driven writers may report:

```text
CURRENT
CURRENT_UNCHANGED
DELAYED
STALE
```

`CURRENT_UNCHANGED` means the engine ran, inputs were unchanged, and the last
valid state remains current — not delayed solely by mtime.

## Resources

```text
NORMAL      < 70% sustained
WARNING     70–85% sustained
CRITICAL    > 85% sustained
```

Memory WARNING (e.g. 84%) is not FAILED and does not degrade System Health alone.
Brief CPU peaks do not degrade System Health; sustained critical CPU may.

Runtime Stability:

```text
STABLE
STABLE_WITH_WARNINGS
DEGRADED
```

## Payload

`GET /api/v1/ops/snapshot` includes:

```text
overall_health / health.display_status
status_planes.live_operational_health
status_planes.known_limitations
status_planes.research_validation
status_planes.historical_audit
health_dimensions.runtime | resources | research_validation | historical_audit
runtime_stability
```

## Non-goals

- no trading model / auction / cognition / MTF / manager / trader changes
- no Toxic Box rebuild, Outcome Intelligence, governance implementation, promotion
- no artificial green artifacts for research/historical planes
