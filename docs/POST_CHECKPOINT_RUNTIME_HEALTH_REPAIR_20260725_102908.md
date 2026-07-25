# Post-Checkpoint Runtime Health Repair — 2026-07-25

Baseline checkpoint: `3718c0a`, branch `safety/validated-runtime-20260725_083940`,
tag `validated-runtime-s4-patch4_3-20260725_083940`. That branch and tag are left
untouched by this work.

Safety artifacts: `/Users/fontecrypto/btc-ml-safety/post_checkpoint_repair_20260725_102908/`

---

## 1. Index cleanup

The index carried 380 staged paths, so any plain `git commit` would have swept
all of them in.

| | before | after |
|---|---|---|
| staged paths | 380 | 0 |
| working tree content hash changes | — | 0 |
| files missing after cleanup | — | 0 |

Mechanism: `git restore --staged --pathspec-from-file=<NUL list> --pathspec-file-nul`,
applied only to the exact staged set. The working tree was never a restore target.

All 380 paths were sha256-hashed before and after; every hash matched. The
`git status --short` digest does change, but only because the status column flips
from `A `/`M ` to `??`/` M` — 373 paths returned to untracked and 7 to
tracked-modified. File contents are byte-identical.

Artifact: `data/research/post_checkpoint_index_cleanup_20260725_102908.json`

---

## 2. Context root cause — `context_entered_at`

`data/live/context_decision_log.parquet` has 114 columns. Exactly one is stored as
an Arrow timestamp:

```
context_entered_at    timestamp[us, tz=UTC]
```

Every other temporal field (`active_context_started_at`, `candidate_started_at`,
`edge_lookup_cutoff_ts`, …) is a `string`.

The row builder emitted an ISO **string** for it:

```python
"context_entered_at": _iso(_to_utc_ts(life_row.get("context_entered_at"))),
```

While the value was null this was harmless — `_iso(None)` returns `None`, which
concatenates into the existing `datetime64[us, UTC]` column as `NaT`. As soon as a
context was actually active the value became a non-null string, and the concat in
`append_decision` degraded the column to `object`:

```
value types: {'Timestamp', 'NaTType', 'str'}
```

pyarrow then refused the write:

```
ArrowTypeError: ("object of type <class 'str'> cannot be converted to int",
                 'Conversion failed for column context_entered_at with type object')
```

Reproduced exactly in isolation before any code was changed.

### Why the daemon appeared to recover on its own

The last `REFRESH_FAILED` was 10:15:03Z and the next append succeeded at 10:30:46Z —
**before** the fix landed at 10:34:56Z. The recovery was not the fix: the market
context had returned to `OBSERVE`, so `context_entered_at` was null again and the
defect simply stopped being triggered. It was latent, not resolved, and would have
returned with the next active context.

---

## 3. Context repair

Two changes, both in `scripts/live/append_context_decision_log.py`:

1. The row builder now emits a real `pd.Timestamp` (or `None`), matching the
   canonical meaning of the column: a nullable UTC timestamp.
2. `normalize_canonical_timestamp_columns()` runs on the combined frame
   immediately before `write_atomic_parquet`, so a string arriving from any other
   caller can no longer corrupt the column dtype.

Normalization parses **each value independently** rather than inferring one format
for the column, and fails closed on an unparseable non-null value:

```
DecisionLoggerError: INVALID_TIMESTAMP: column=context_entered_at value=...
```

Null stays null, timezone-aware values are converted rather than re-localized, and
empty strings are treated as null.

Verified against production after live cycles resumed:

| check | result |
|---|---|
| schema type | `timestamp[us, tz=UTC]` (unchanged) |
| prefix columns identical | 114 / 114 |
| duplicate candle rows | 0 |
| rows appended by live daemon | 4 (10:30, 10:45, 11:00, 11:15) |

---

## 4. Visual root cause — mixed ISO precision

The archived legacy ledger writes exit timestamps with microseconds; the timeframe
traders write whole seconds. Under pandas 3.0.2, `pd.to_datetime` infers a single
format from the first element:

```python
pd.to_datetime(["2026-07-24T20:20:14.123456Z", "2026-07-25T09:15:00Z"],
               utc=True, errors="coerce")
# -> [Timestamp(...), NaT]
```

`canonical_trade_view.py` used that call in nine places. Because legacy rows sort
first, every S4 exit timestamp became `NaT`, and `reconcile()` counted two genuinely
closed M15/M30 trades as unclosed:

```
unclosed_positions_as_trades = 2
```

The same inference was also applied to entry timestamps, lifecycle timestamps, the
context resolver, the activation boundary, and the sort key used to order trades —
so the defect was not limited to the exit column.

---

## 5. Visual repair

`utc_stamp()` and `utc_series()` are now the single parsing contract for the module:

- strings are parsed with explicit `format="ISO8601"`, per value;
- already-datetime columns are converted, not reparsed;
- everything lands on one UTC-aware nullable datetime type;
- unparseable values become `NaT` rather than a fabricated instant, so a bad value
  can never present itself as a closed trade.

All eight external call sites were routed through these helpers. The Patch 4.3
parity test was re-pointed at the same helpers, because it had independently
reimplemented the defective inference in `test_18_no_future_trade_join`.

Timestamp semantics are unchanged; only the parsing is.

---

## 6. S4 closed trades — before and after

| | before | after |
|---|---|---|
| rows in canonical view | 6 | 7 |
| `unclosed_positions_as_trades` | 2 | 0 |
| M15 closed trade rendered closed | no | yes |
| M30 closed trade rendered closed | no | yes |
| payload `entries`/`exits`/`open` | 4 / 4 / 0 | 7 / 7 / 0 |

The view now carries four legacy archive trades plus M15, M30 and H1 timeframe
trades, all closed, entry strictly before exit, with
`pnl_reconciliation_errors = 0` and `duplicate_visual_trade_ids = 0`.

---

## 7. Runtime recovery

The context refresher was **never restarted** — it spawns the decision logger as a
child process each cycle, so it picked up the fixed file on its own.

The visual refresher was genuinely dead since 08:25:32Z, with four stale PID records
pointing at non-existent processes. Those were backed up and removed, a `--once` run
validated the payload, and the loop was started.

The first loop attempt (pid 3592) died after one cycle. Cause: it was launched with
`nohup … &` and therefore stayed in the launching shell's process group, so it was
killed when that group was torn down — the same mechanism that most likely killed it
at 08:25:32Z. It was relaunched via `start_new_session=True` (setsid), reparented to
pid 1, and has been stable since.

| process | pid | state |
|---|---|---|
| live feed | 93404 | preserved, ppid 1 |
| context refresher | 97695 | preserved, ppid 1, never restarted |
| timeframe manager | 4958 | preserved, ppid 1 |
| trader M15 / M30 / H1 / H4 | 5028 / 5085 / 5130 / 5182 | preserved, ppid 1 |
| visual refresher | 5105 | restarted (was dead), ppid 1 |

### Natural cycle

One full M15 cycle observed end to end:

```
market_tip           2026-07-25T11:15:00Z
context_tip          2026-07-25T11:15:00Z
decision_tip         2026-07-25T11:15:00Z
visual_generated_at  2026-07-25T11:31:17Z
lag_seconds          20.1
```

`REFRESH_SUCCESS` at 11:30:37Z with `added_rows = {final: 1, lifecycle: 1, decision: 1}`,
followed by a `LIVE_OK` visual refresh at 11:30:56Z. Feed, context, decision and
visual are all advancing.

---

## 8. Tests

| suite | result |
|---|---|
| context domain (10 files) | 168 passed, 4 pre-existing failures |
| `test_context_entered_at_timestamp_typing.py` (new) | 15 passed |
| visual domain incl. Patch 4.3 parity | 71 passed, 1 skipped |
| `test_canonical_visual_mixed_precision_timestamps.py` (new) | 18 passed |
| S4 manager / traders / watchdog | 59 passed |

The 4 context failures are in `test_live_decision_log_signal_fields_patch_additive.py`
and are **pre-existing and unrelated**. Confirmed by running that file in a detached
worktree at `3718c0a` without the fix: identical 4 failures. Their fixture pins
`FRESH_TS = "2026-07-20T12:00:00.000000Z"`, now five days stale, so the edge lookup
validity window rejects it with `BLOCKED_LOOKUP_NOT_VALID_FOR_DECISION_TIME`.

### Full collection

`COLLECTION_HANG_LOCALIZED`.

The repository has no pytest configuration at all — no `testpaths`, no
`norecursedirs`. Collection therefore walks the whole tree, including
`archive_removed/`, which holds 13 test-named modules. The stack dump pins the hang
to module-scope work executed at import:

```
archive_removed/btc-microstructure-engine-mirror/historical_liquidation_test.py:84
  -> pandas pct_change -> shift -> __finalize__
```

This is not a product defect and is out of scope here. The obvious follow-up is to
scope collection (`testpaths = tests`) so the archive is never imported. Targeted
suites are unaffected.

---

## 9. Preservation

No change to auction/cognition or MTF semantics, context/lifecycle/decision rules,
manager, command bus, trader logic, independent ledgers, portfolio risk, fill rules,
fees, slippage, P&L formulas, or any dashboard or chart visual design.

```
exchange_calls = 0
real_execution = false
remote_pushes  = 0
```
