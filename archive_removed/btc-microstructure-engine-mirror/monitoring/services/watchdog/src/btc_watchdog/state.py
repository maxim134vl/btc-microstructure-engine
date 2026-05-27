"""
In-process state for the watchdog.

- Restart budget: ring buffer of restart timestamps; lookup how many fell in
  the last `window_seconds`.
- Circuit breakers: per-feed open/closed with expiry timestamp.

Kept in memory; on restart the budget resets (intentional — operator restarts
generally signal a fresh start).
"""

from __future__ import annotations

import time
from collections import deque


class RestartBudget:
    def __init__(self, max_per_window: int, window_seconds: int = 3600) -> None:
        self.max = max_per_window
        self.window = window_seconds
        self._events: deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def try_consume(self) -> bool:
        now = time.time()
        self._prune(now)
        if len(self._events) >= self.max:
            return False
        self._events.append(now)
        return True

    def used(self) -> int:
        self._prune(time.time())
        return len(self._events)


class CircuitBreaker:
    """Per-target open/closed with auto-close-after-cooloff."""

    def __init__(self, cooloff_seconds: int) -> None:
        self.cooloff = cooloff_seconds
        self._open_until: dict[str, float] = {}

    def trip(self, target: str) -> None:
        self._open_until[target] = time.time() + self.cooloff

    def is_open(self, target: str) -> bool:
        until = self._open_until.get(target)
        if until is None:
            return False
        if time.time() >= until:
            del self._open_until[target]
            return False
        return True

    def reset(self, target: str) -> bool:
        return self._open_until.pop(target, None) is not None

    def all_open(self) -> dict[str, float]:
        now = time.time()
        return {t: u - now for t, u in self._open_until.items() if u > now}
