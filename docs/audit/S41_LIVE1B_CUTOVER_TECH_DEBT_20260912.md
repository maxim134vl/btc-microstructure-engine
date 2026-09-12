# S4.1 → LIVE1B cutover: remaining technical debt

Date: 2026-09-12  
Status: **cutover live**; residual ops debt only  
Contract: `S41_LIVE1B_CHAIN_V1`  
Epoch: `PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442` (unchanged)

Production path is:

```text
closed-bar cognition + volume class
  → S4.1 TimeframeManager (sole entry)
  → command-bus
  → LIVE1B books / local BBO / TP-SL
```

LIVE1A journal is observe-only. Chart bands follow overlay `entry_source=s41_command_bus` → parquet lifecycle episodes.

Shipped: `2ed7b46`, `cf8f80f`. Volume overlay/activation/cursor persisted without bootstrap.

## Open

| ID | Symptom | Why it remains | Do not |
| --- | --- | --- | --- |
| S41-LIVE1B-RESTART-GAP | After paper-manager recreate, execution market stays `RECOVERING` with `entry_allowed=false` while REST backfill walks a large aggTrade gap. Each recovered trade fsyncs WAL. ~10^5 ids can take hours. OPEN waits on `HEALTHY`. | Correct safety gate. Speed is the debt. | Do not skip the gap to force OPEN. Do not run `bootstrap_vps_environment.py --allow-existing` on this volume. |
| S41-LIVE1B-PUBLIC-WS-PONG | `live1b-futures-public_error:ping/pong timed out` during recovery; public WS drops, then reconnects with a new gap. | Transport flapping widens the backfill window. | Do not disable the BBO age / HEALTHY entry gate. |
| S41-LIVE1B-CURSOR-CLOBBER | A running consumer `_save()` can rewrite `consume_after` from in-memory state and undo a volume persist. Mitigated: stop process, persist, start. Code now takes `later_iso(file, overlay)`. | Restart procedure must still stop the writer first. | Do not persist cursor while the old paper-manager is still polling. |
| S41-LIVE1B-PRE-ENTRY-BACKFILL-SL | REST gap-recovery can print prices from before `opened_at`. Live H4 SL on 2026-09-11 used an aggTrade whose tape time was pre-entry. | Engine skips `trade_ts < opened_at`. Processor now forwards `backfill` on provenance. Test locks it. Watch live fills after the next HEALTHY. | Do not restore journal as entry_source to “avoid” backfill SLs. |

## Closed in this cutover

- Journal START/FLIP no longer fill when `entry_source=s41_command_bus`.
- Same `lifecycle_episode_id` does not re-OPEN after TP/SL/CLOSE.
- Atomic FLIP emits CLOSE then opposite OPEN in one cycle.
- Overlay/activation on the live volume match the image: S4.1 is entry authority.
- Cursor floor no longer rolls back below overlay (`later_iso`).

## Do not restore

`MIN_ACTIVE_CONTEXT_HOLD_BARS=3`, bar-count anti-saw, M15 inheritance onto M30/H1/H4, journal OPEN/FLIP/END fills, wait-one-bar OPEN.

## Diagram

Regenerate the path poster:

```bash
MPLCONFIGDIR=/tmp/mpl-s41 venv/bin/python scripts/ops/render_s41_live1b_path_diagram.py
```

Output: `/Users/fontecrypto/Downloads/s41_live1b_entry_path.png`
