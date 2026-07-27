# OPS2B — Soft-Fetch Reconnect Activation

**Status:** `OPS2_FRONTEND_RECONNECT_ACTIVATED`  
**UTC quarantine:** `20260727_123030`  
**Branch:** `memory/canonical-system`  
**Activated commit:** `071940b` (`fix: restore OPS frontend after API reconnect`)  
**Quarantine:** `data/quarantine/architecture_recovery/ops2b/20260727_123030/`  
**Mode:** `paper_only=true` · real execution disabled

---

## A. Result

One controlled OPS API blip proved automatic Live Operations recovery without hard refresh or Vite restart. UI returned to **LIVE** with new OPS PID, canonical risk/performance restored, cores unchanged.

---

## B. Candidate Frontend Load

Pre-blip page load `http://127.0.0.1:5173/?ops2b=071940b` (allowed once):

| Check | Result |
| ----- | ------ |
| `src/api/client.ts` via Vite | loaded (`?t=1785154988713`) |
| `startOpsLiveSession` | present |
| `App.tsx` wires session | true |
| legacy `connected` poll gate | absent |
| `DEFAULT_SOFT_FETCH_TIMEOUT_MS` | 5000 |
| first snapshot duration | **2136ms** (accepted; would have aborted under legacy 1500ms) |

---

## C. Preflight

| Item | Value |
| ---- | ----- |
| branch | `memory/canonical-system` |
| HEAD | `071940b` |
| OPS API (old) | 48835 |
| Vite | 66359 |
| pipeline | 4618 |
| manager / traders | 61283–61287 |
| refresher | 84045 |
| `/health` | 200 |
| `/ops/snapshot` | 200 |

---

## D. Baseline Live State

UI **LIVE**: Operational with Limitations; risk/PnL/traders/processes/context visible; ops_backend pid **48835**.

---

## E. OPS Launch Contract

```text
venv/bin/python3 dashboard/backend/run_api.py
BTC_ML_VOLUME_LOCALIZATION_LIVE=1
BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE=1
port 8080
start_new_session=true
log: logs/ops_api_ops2b_activation.log
```

---

## F. Controlled Outage

| Event | UTC |
| ----- | --- |
| stop OPS 48835 | 12:33:07Z |
| OPS count 0 | ~12:33:09Z |
| outage hold | ~8s (≥ one 4s poll) |
| restart | 12:33:16Z |
| `/health` 200 | 12:33:18Z |
| new PID | **71811** |
| count | 1 |

---

## G. Frontend State Transitions

```text
LIVE → (outage RECONNECTING/OFFLINE) → LIVE
```

Same tab URL; no hard refresh. After recovery UI showed ops_backend **71811**.

---

## H. Poll / Retry Behavior

Candidate contract: single timer, 4s reconnect / 8s LIVE heartbeat, bounded backoff. Outage long enough for failed poll; loop continued (recovery occurred).

---

## I. Timeout and Abort Behavior

Post-reconnect snapshot durations: **0.63s, 0.02s, 1.24s** — all &lt; 5s; false 1500ms aborts = **0**. Pre-blip 2.14s success confirms 5s contract.

---

## J. WebSocket Semantics

Candidate: LIVE only after successful snapshot (not bare WS onopen). Live recovery showed full payload + new OPS PID.

---

## K. Automatic Recovery

```text
hard refresh = 0
Vite restart = 0
manual reconnect = 0
```

---

## L. Recovery Latency

| Marker | Time |
| ------ | ---- |
| API ready | 12:33:18Z |
| UI LIVE observed | 12:33:31.212Z |
| **latency** | **~13.2s** |

Bounded retry; not optimized for minimum.

---

## M. Truth Restoration

After LIVE: System Health, processes, traders M15–H4, context, risk, realised/unrealised restored.

---

## N. Risk / Performance Parity

Same-mark after reconnect:

| Gate | Result |
| ---- | ------ |
| closed/open | 100% |
| realised/unrealised | 100% |
| per-TF | 100% |
| manager risk | 100% |

---

## O. Three Post-Reconnect Polls

Same OPS PID **71811**; `generated_at` advances; fetch errors clear; fields populated.

---

## P. Natural M15-Bar Gate

| Field | Value |
| ----- | ----- |
| baseline safe tip | 12:15:00Z |
| accepted tip | 12:30:00Z |
| accepted_at | 12:45:43Z |
| OPS/Vite/core PIDs | unchanged |
| UI | remained LIVE (no reconnect relapse) |

---

## Q. Core / Vite Preservation

Only OPS PID changed (`48835` → `71811`). Vite **66359** and pipeline/manager/traders/refresher unchanged.

---

## R. Last-Known-Good Follow-Up

During outage UI may still blank metrics via `liveConnected=false`. Deferred: `OPS_LAST_GOOD_DATA_RETENTION`. Does **not** block OPS2B.

---

## S. Git / Documentation

Docs-only commit:

```text
docs: record OPS frontend reconnect activation
```

No pushes. Source changes during activation = **0**.

---

## T. Compliance

```text
OPS controlled restarts = 1
duplicate starts = 0
Vite/core/trader restarts = 0
hard refresh after blip = 0
pushes = 0
```

---

## U. Next Step

**VIS2A — FOUR NATIVE TIMEFRAME CHARTS FUNCTIONAL AUDIT** (read-only first):

```text
native candle source per TF
TF-specific context/state source
trade overlay identity contract
global lifecycle strip contract
visualizer data-generation path
```

No chart code changes until VIS2A completes.
