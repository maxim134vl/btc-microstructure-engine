# Live Decision Log Freshness / Cadence Readiness Audit

Generated: `2026-07-20T17:06:44.347745Z`

This audit is read-only. It verifies whether the live decision log is fresh enough and has sufficient post-lookup-cutoff cadence to feed the paper signal adapter after the logger lookup integration patch. It does not write or backfill the live decision log, does not write paper signal events, does not mutate paper ledgers, does not fit or retrain any model, does not run live refresh, does not start paper trading, does not enable execution, and does not call any exchange API.

## Decision

- status: `LIVE_DECISION_LOG_FRESHNESS_CADENCE_READINESS_BLOCKED_WITH_LIMITATIONS`
- qa_status: `PASS_WITH_LIMITATIONS`
- run_readiness_status: `NOT_READY_TO_RUN_PAPER_TRADING`
- next_recommended_step: `USER_APPROVAL_FOR_SINGLE_LIVE_CONTEXT_REFRESH_AND_DECISION_LOG_APPEND_NO_PAPER_SIGNAL`

## Prerequisites

- logger_lookup_patch_ready: `True`
- adapter_contract_ready: `True`
- corrected_lookup_ready: `True`

## Inventory

- decision_log_rows: `8`
- earliest_decision_ts_utc: `2026-07-19T13:15:00Z`
- latest_decision_ts_utc: `2026-07-19T18:00:00Z`
- latest_context: `OBSERVE`
- latest_is_stale: `True`
- corrected_lookup_snapshot_id: `corrected_lagged_edge_lookup_02062bba5f9c767f`
- lookup_cutoff_ts_utc: `2026-07-20T12:45:00Z`
- inventory_status: `PASS_WITH_LIMITATIONS`

## Lookup cutoff

- decisions_after_lookup_cutoff_count: `0`
- live_lookup_cadence_ready: `False`
- lookup_cutoff_check_status: `PASS_WITH_LIMITATIONS`

## Latest decision

- latest_before_lookup_cutoff: `True`
- latest_is_directional: `False`
- latest_has_confidence: `False`
- latest_has_expected_edge_bps: `False`
- latest_adapter_eligible_now: `False`
- signal_block_reasons: `['STALE_CONTEXT', 'OBSERVE_CONTEXT', 'LOOKUP_NOT_VALID_FOR_DECISION_TIME', 'MISSING_CONFIDENCE', 'MISSING_EXPECTED_EDGE']`
- latest_decision_check_status: `PASS_WITH_LIMITATIONS`

## Gap / cadence

- median_interval_minutes: `15.0`
- max_interval_minutes: `150.0`
- gap_count_over_expected_interval: `2`
- last_gap_minutes_to_now_utc: `1386.7391292666666`
- cadence_after_patch_available: `False`
- cadence_ready_for_paper_signal: `False`
- gap_check_status: `PASS_WITH_LIMITATIONS`

## Signal fields

- signal_fields_check_status: `PASS`
- rows_with_paper_signal_write_allowed_true: `0`
- rows_with_paper_loop_allowed_true: `0`

## Adapter readiness

- adapter_readiness_now: `False`
- adapter_not_ready_reasons: `['NO_DECISIONS_AFTER_LOOKUP_CUTOFF', 'LATEST_DECISION_STALE', 'LATEST_DECISION_OBSERVE', 'LIVE_DECISION_CADENCE_NOT_PROVEN_AFTER_PATCH']`
- adapter_readiness_check_status: `PASS_WITH_LIMITATIONS`

## Required refresh plan

- refresh_required: `True`
- required_next_operation: `SINGLE_LIVE_CONTEXT_REFRESH_AND_DECISION_LOG_APPEND_DRY_RUN_OR_APPROVED_ONE_SHOT`
- live_decision_log_write_allowed_now: `False`
- paper_signal_write_allowed_now: `False`
- paper_loop_allowed_now: `False`
- required_refresh_plan_status: `PASS`

## Safety

- logger_script_mutated_by_audit: `False`
- live_decision_log_mutated_by_audit: `False`
- corrected_lookup_mutated_by_audit: `False`
- paper_ledgers_mutated_by_audit: `False`
- no_write_safety_status: `PASS`
