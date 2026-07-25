# Model-Runtime Process Contract (Future)

**Patch 2A.1:** specification only — supervisor **not** implemented.

## Entrypoint

```text
scripts/ops/model_runtime_ctl.sh
```

(or a future Python supervisor with identical commands)

## Commands

```text
start
stop
restart
status
foreground
```

## Managed children

- feed watchdog
- canonical pipeline
- context refresher
- paper controller (only when explicitly allowed)

## Docker foreground

```bash
scripts/ops/model_runtime_ctl.sh foreground
```

Must:

1. Stay as PID 1 or under a proper init.
2. Emit combined component logs on stdout (structured lines).
3. On SIGTERM/SIGINT: stop accepting work, finish atomic writes, release locks, terminate children, clear PID/lock files, exit cleanly.
4. Return non-zero if a critical model component dies.

Until this supervisor exists, macOS ops start components individually (`collector_watchdog`, `run.py`, `context_refresh_daemon_ctl.sh`).
