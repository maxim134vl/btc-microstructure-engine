#!/usr/bin/env python3
"""Tests for intrabar market data gap audit."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "scripts" / "research" / "audit_intrabar_market_data_gaps.py"

spec = importlib.util.spec_from_file_location("audit_intrabar_market_data_gaps", MOD)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
sys.modules["audit_intrabar_market_data_gaps"] = audit
spec.loader.exec_module(audit)


def test_gap_audit_detects_gt_120s(tmp_path: Path, monkeypatch):
    pq = tmp_path / "feed.parquet"
    t0 = datetime(2026, 7, 21, 18, 0, tzinfo=timezone.utc)
    rows = [
        {"observed_at_utc": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "price": 1.0},
        {
            "observed_at_utc": (t0 + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price": 2.0,
        },
        {
            "observed_at_utc": (t0 + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price": 3.0,
        },
    ]
    pd.DataFrame(rows).to_parquet(pq, index=False)
    info = audit.detect_gaps(pq, threshold=120.0)
    assert info["gap_count"] >= 1
    assert info["max_gap_seconds"] >= 240

    monkeypatch.setattr(audit, "FEED_PATH", pq)
    monkeypatch.setattr(audit, "HEARTBEAT_PATH", tmp_path / "hb.json")
    monkeypatch.setattr(audit, "SUPERVISOR_PATH", tmp_path / "sup.json")
    monkeypatch.setattr(audit, "CYCLES_PATH", tmp_path / "cycles.parquet")
    monkeypatch.setattr(audit, "OUT_JSON", tmp_path / "out.json")
    monkeypatch.setattr(audit, "OUT_MD", tmp_path / "out.md")
    payload = audit.audit()
    assert payload["gap_count"] >= 1
    audit.write_md(payload)
    assert (tmp_path / "out.md").exists()
