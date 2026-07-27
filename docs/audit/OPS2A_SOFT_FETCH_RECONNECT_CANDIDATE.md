# OPS2A — Soft-Fetch Reconnect Candidate

**Status:** `OPS2A_SOFT_FETCH_RECONNECT_CANDIDATE_READY`  
**Branch:** `memory/canonical-system`  
**Basis:** VIS1D `VIS1D_API_ACTIVATED_UI_RECONNECT_DEFECT` (`b740264`)  
**Evidence:** `data/candidate/architecture_recovery/ops2a_soft_fetch_reconnect/`  
**Live OPS API:** untouched (PID `48835` / current) · Vite not restarted

---

## A. Result

Narrow frontend candidate restores automatic Live Operations recovery after temporary OPS API unavailability. Offline latch clears on first successful fetch. Backend / adapters / visualizer unchanged.

---

## B. Baseline Reproduction

Proven in mock harness (`baseline legacy latch` test):

| Step | Result |
| ---- | ------ |
| Snapshot work takes ~1.8s | realistic vs observed truth-build max ~1.86s |
| Legacy `softFetch` timeout 1500ms | **aborts** |
| Outcome | `null` / timeout — UI cannot upgrade |

Live symptom (VIS1D): API 200 + canonical PnL while Vite showed `LIVE DATA UNAVAILABLE`.

---

## C. Root Cause

| Code | Where | Effect |
| ---- | ----- | ------ |
| `TIMEOUT_TOO_AGGRESSIVE` | `softFetchOpsSnapshot` default 1500ms | Aborts legitimate cold/full snapshot builds |
| `POLLING_STOPS_AFTER_ERROR` | `App.tsx` poll gated on `connected` | HTTP recovery skipped when WS latched connected |
| `OFFLINE_FALLBACK_LATCHED` | `tryLive` failure path | No bounded reconnect state machine |
| WS `onopen` → `onStatus(true)` | `connectOps` | Connected without snapshot payload |

---

## D. Current Fetch Lifecycle (before)

```text
App mount
→ softFetch(1500)
→ on success: setConnected + connectOps
→ poll every 8s only if !connected
→ WS onopen sets connected=true (no payload)
```

| Layer | File | Function | State |
| ----- | ---- | -------- | ----- |
| Poll | `App.tsx` | `setInterval` | gated by `connected` |
| Soft fetch | `client.ts` | `softFetchOpsSnapshot` | AbortController 1500ms |
| WS | `client.ts` | `connectOps` | onopen→connected |
| UI | `OpsUnifiedDashboard.tsx` | `liveConnected` | offline banner |

---

## E. New Reconnect State Machine

```text
LIVE → transient failure → RECONNECTING → success → LIVE
LIVE → repeated failures → OFFLINE → success → LIVE
```

Success always: clear error/offline, replace payload, `onConnected(true)`, `last` generation wins.

Helper: `startOpsLiveSession()` in `client.ts`; `App.tsx` mounts/stops it only.

---

## F. Retry Contract

| Param | Value |
| ----- | ----- |
| reconnect poll | 4000ms |
| LIVE heartbeat | 8000ms |
| max backoff | 15000ms |
| single timer | yes |
| supersede in-flight | abort + new generation |
| tight loop | no |

---

## G. AbortController Contract

One request → one controller → timeout cleared in `finally` → never reused. Superseded polls abort prior request; `aborted` reason does not count as offline failure.

---

## H. Timeout Analysis

| Metric | Value |
| ------ | ----- |
| legacy | 1500ms |
| observed truth-build max | ~1.86s |
| warm HTTP p50 | ~12ms |
| **new default** | **5000ms** |

Not an arbitrary 10–30s. Separates timeout defect from reconnect-state defect (both fixed).

---

## I. Offline-State Reset

`OFFLINE` / `RECONNECTING` clear on first success. Banner `LIVE DATA UNAVAILABLE` only while `liveConnected=false`. Follow-up (optional): `OPS_LAST_GOOD_DATA_RETENTION` to show stale metrics under RECONNECTING banner without dashes.

---

## J. Race Protection

Request generation ID: late failure/abort cannot overwrite a newer success (HTTP or WS snapshot).

---

## K. Schema Preservation

No API field renames. UI still reads risk / realised-unrealised / traders / context / processes.

---

## L. Tests

```text
tests/opsSoftFetchReconnect.test.ts  12 passed
tests/opsUnifiedDisplay.test.ts      15 passed
total 27 failed 0
```

---

## M. Production Scope

| File | Role |
| ---- | ---- |
| `dashboard/frontend/src/api/client.ts` | softFetch + session + WS contract |
| `dashboard/frontend/src/App.tsx` | wire `startOpsLiveSession` |

Backend / adapters / visualizer / Vite config: **0**.

---

## N. Git

```text
fix: restore OPS frontend after API reconnect
```

No Gitea/GitHub push.

---

## O. Compliance

```text
frontend production files = 2
test files = 1
backend changes = 0
process / OPS / Vite restarts = 0
trading writes = 0
pushes = 0
```

---

## P. Next Step

**OPS2B — controlled frontend-only reconnect activation**

```text
live UI → controlled OPS API blip → automatic frontend recovery
pipeline/manager/trader restart = 0
OPS API restart ≤ 1 controlled blip
Vite restart = 0
```

Only after OPS2B → **VIS2A** four native timeframe charts functional audit.
