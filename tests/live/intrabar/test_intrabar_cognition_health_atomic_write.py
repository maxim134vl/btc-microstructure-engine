"""Concurrency regression for LIVE1A cognition health atomic writes."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from btc_ml.live.intrabar.atomic_json import atomic_write_json


def test_atomic_write_json_uses_unique_temp_not_shared_suffix(tmp_path: Path):
    target = tmp_path / "intrabar_cognition_health.json"
    atomic_write_json(target, {"ok": True})
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {"ok": True}
    assert not (tmp_path / "intrabar_cognition_health.tmp").exists()
    temps = list(tmp_path.glob(".intrabar_cognition_health.json.*.tmp"))
    assert temps == []


def test_concurrent_health_writes_do_not_raise_or_leak(tmp_path: Path):
    target = tmp_path / "intrabar_cognition_health.json"
    errors: list[BaseException] = []
    lock = threading.Lock()

    def write_one(seq: int) -> None:
        try:
            atomic_write_json(
                target,
                {
                    "service": "intrabar_cognition",
                    "seq": seq,
                    "thread": threading.get_ident(),
                },
            )
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write_one, range(64)))

    assert errors == []
    assert target.exists()
    raw = target.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload["service"] == "intrabar_cognition"
    assert isinstance(payload["seq"], int)
    assert 0 <= payload["seq"] < 64
    assert not raw.strip().endswith(",")
    leaked = list(tmp_path.glob(".intrabar_cognition_health.json.*.tmp"))
    assert leaked == []
    assert not (tmp_path / "intrabar_cognition_health.tmp").exists()


def test_failed_write_cleans_temp_and_preserves_target(tmp_path: Path, monkeypatch):
    target = tmp_path / "intrabar_cognition_health.json"
    atomic_write_json(target, {"ok": 1})
    original = target.read_bytes()

    def boom_replace(src, dst):
        raise FileNotFoundError(src)

    monkeypatch.setattr("btc_ml.live.intrabar.atomic_json.os.replace", boom_replace)

    with pytest.raises(FileNotFoundError):
        atomic_write_json(target, {"ok": 2})

    assert target.read_bytes() == original
    leaked = list(tmp_path.glob(".intrabar_cognition_health.json.*.tmp"))
    assert leaked == []
