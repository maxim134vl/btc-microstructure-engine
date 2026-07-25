# Feed Watchdog Restart Contract

**Patch:** 2A
**Tag:** `20260724_120015`
**Code:** `collector_watchdog.py`
**Tests:** `tests/test_collector_watchdog_restart_contract.py`

## Problem (Patch 1 evidence)

1. `SIGTERM` left the feed child in **zombie** state.
2. Watchdog treated the PID as alive via `kill(0)` / existence alone.
3. Restart therefore stalled until a manual watchdog-only bounce.
4. A non-venv / bare Cellar interpreter lacked `websocket` and could not start the feed.

## Canonical interpreter

Watchdog **must** launch collectors with:

```text
/Users/fontecrypto/btc-ml/venv/bin/python
```

Rules:

- Prefer `BTC_ML_COLLECTOR_PYTHON` only if it is under `<repo>/venv/`.
- Default to `<repo>/venv/bin/python` (then `python3`).
- **Do not** use bare `python` / `python3`, Homebrew/Cellar path strings, or `sys.executable` when that would select a non-venv interpreter.
- On macOS the venv entrypoint may *resolve* to a Cellar binary; that is allowed **only** when the argv path itself is under `<repo>/venv/`. Process listings may still show the Cellar `txt` path — that is not a contract violation if launch used the venv path.

## Preflight (before spawn)

Fail closed (no start, no infinite loop) unless all succeed:

1. Interpreter exists and is executable.
2. Interpreter is not a forbidden bare Cellar/system path.
3. `import websocket` succeeds under that interpreter.
4. Feed entrypoint script exists.
5. Repo cwd exists.

Structured failure reasons are recorded; restart backoff still applies so a bad environment cannot storm.

## Process classification

Watchdog distinguishes at least:

| State | Treated as live feed? |
| --- | --- |
| running / sleeping (expected cmd + parent) | yes |
| stopped | no |
| zombie | **no** |
| missing | no |
| stale PID reused by another process / wrong cmdline | no |
| wrong parent (orphan when watchdog expects ownership) | no |

Zombie handling:

1. Classify child dead.
2. Reap via parent `waitpid` semantics when possible.
3. Clear stale PID state.
4. Start **exactly one** new child after stop/reap.
5. Confirm launch interpreter is the venv path.
6. Prevent duplicate writers (stop extras before start).

Stop sequence: `SIGTERM` → bounded wait → `SIGKILL` if needed → reap.

## Restart backoff

State file: `data/live/collector_restart_state.json`

Policy:

- attempt counter in a sliding window
- minimum delay + bounded exponential backoff
- window max attempts
- explicit block reason `RESTART_STORM_BLOCKED`

Heartbeat / metadata failures must **not** block a valid restart.

## Ops notes

- Start watchdog detached so it survives the launching shell.
- After code load, verify topology: one watchdog → one feed child; no orphan `ppid=1` feed.
- Watchdog-only bounce must preserve collector architecture (registry + heartbeats), not invent a second feed launcher.

## Tests covered

1. Canonical venv selected
2. Bare Cellar rejected
3. Missing websocket blocks start
4. Zombie classified dead
5. Stale PID / wrong process rejected
6. Duplicate feed prevented
7. One restart → one child
8. Restart storm blocked
9. Missing entrypoint blocked
10. Valid running child not restarted
11. SIGTERM timeout handled
12. Metadata failure does not affect restart
13. Watchdog-only bounce preserves architecture
