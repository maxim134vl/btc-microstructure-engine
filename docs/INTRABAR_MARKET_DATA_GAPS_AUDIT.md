# Intrabar Market Data Gaps Audit

Generated: `2026-07-21T19:10:22Z`

## Summary

- rows: `77`
- gap_count (>120s): `4`
- max_gap_seconds: `1495.532788`
- latest_row_age_seconds: `47.467826`
- fallback_snapshot_usage: `0`
- on_demand_refresh_count: `0`
- snapshot_unavailable_blocks: `0`

## Stale incidents

- `{"kind": "GAP_GT_120S", "gap_seconds": 220.490952, "from_utc": "2026-07-21T17:15:05.745232Z", "to_utc": "2026-07-21T17:18:46.236184Z"}`
- `{"kind": "GAP_GT_120S", "gap_seconds": 152.569224, "from_utc": "2026-07-21T17:20:59.228567Z", "to_utc": "2026-07-21T17:23:31.797791Z"}`
- `{"kind": "GAP_GT_120S", "gap_seconds": 434.641427, "from_utc": "2026-07-21T17:26:33.200812Z", "to_utc": "2026-07-21T17:33:47.842239Z"}`
- `{"kind": "GAP_GT_120S", "gap_seconds": 1495.532788, "from_utc": "2026-07-21T17:39:11.069951Z", "to_utc": "2026-07-21T18:04:06.602739Z"}`

## Heartbeat

- present: `False`
- feed_status: `None`
- consecutive_errors: `None`

## Supervisor recoveries

- recovery_attempted: `False`
- recovery_success: `False`
- recovery_reason: `None`

## Safety

- paper_only: true
- execution_enabled: false
