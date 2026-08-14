"""Exclusive pid lock prevents a second writer of the same role."""

from __future__ import annotations

from pathlib import Path

import pytest

from btc_ml.runtime.single_instance import AlreadyRunningError, acquire_pid_lock


def test_second_acquire_fails_while_first_lock_is_held(tmp_path: Path) -> None:
    path = tmp_path / "role.lock"
    first = acquire_pid_lock(path)
    try:
        with pytest.raises(AlreadyRunningError):
            acquire_pid_lock(path)
    finally:
        first.release()
    second = acquire_pid_lock(path)
    second.release()
