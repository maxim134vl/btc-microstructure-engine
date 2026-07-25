# Intrabar Feed Stability Gate

Generated: `2026-07-21T18:15:16.217785Z`

- gate_status: **PASS**
- ready_for_paper_controller: **True**
- reason_if_fail: `None`
- parent_shell_exited: `True`
- post_shell_wait_seconds: `90`

## Feed
- status_start / status_end: `RUNNING` → `RUNNING`
- pid_start / pid_end: `856` → `856`
- rows_start / rows_end / rows_added: `20` → `26` (+6)
- max_seconds_since_latest_row: `24.209706`
- estimated_cadence_seconds: `64.219802`
- stale_count: `0`
- duplicate_count: `0`
- orphan_count: `0`
- healthcheck_fail_count: `0`

## Controller
- paper_controller_running: `False`
- paper_controller_started: `false`

## Safety
- paper_ledger_write: false
- execution_enabled: false
- exchange_order_api_used: false
- safety_status: PASS

## Next
APPROVE_START_PAPER_CONTROLLER_WITH_STABLE_INTRABAR_FEED_NO_REAL_EXECUTION
