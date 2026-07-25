# Context Refresher Negative Sleep Hotfix

## Problem

`run_context_refresh_daemon.py` crashed with:

```text
ValueError: sleep length must be non-negative
```

at the post-cycle interruptible sleep that used wall-clock chunking:

```python
end = time.time() + interval_s
while time.time() < end and not _STOP:
    time.sleep(min(0.5, end - time.time()))
```

## Fix

- Schedule waits with `time.monotonic()` deadline arithmetic (`plan_schedule_wait`).
- On interval overrun: emit `REFRESH_INTERVAL_OVERRUN`, skip missed slots, sleep until the next future deadline.
- Use interruptible `threading.Event.wait` (SIGTERM/SIGINT).
- Never pass a negative timeout to sleep/wait.

Refresh classification, lifecycle, decision, and output schema are unchanged.
