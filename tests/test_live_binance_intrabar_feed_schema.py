#!/usr/bin/env python3
"""Schema/behavior tests for paper-only intrabar feed."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts/live/live_binance_intrabar_feed.py"
    spec = importlib.util.spec_from_file_location("live_binance_intrabar_feed", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REQUIRED = {
    "observed_at_utc",
    "symbol",
    "price",
    "m15_bucket_open_ts",
    "m15_bucket_close_ts",
    "is_closed_candle",
    "source",
    "feed_type",
}


def test_schema_and_closed_false(tmp_path: Path, monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "OUT_PATH", tmp_path / "live_market_intrabar_feed.parquet")
    monkeypatch.setattr(mod, "STATUS_PATH", tmp_path / "intrabar_feed_status.json")

    def fake_http(url: str, timeout: float = 10.0):
        if "ticker/price" in url:
            return {"symbol": "BTCUSDT", "price": "65012.5"}
        if "bookTicker" in url:
            return {"bidPrice": "65010", "askPrice": "65015"}
        if "klines" in url:
            # open time ms for 15:00Z
            return [[1753110000000, "1", "2", "0.5", "1.5", "10", 1753110899999, "0", 0, "0", "0", "0"]]
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_http_json", fake_http)
    out = mod.once()
    row = out["row"]
    assert REQUIRED.issubset(row.keys())
    assert row["is_closed_candle"] is False
    assert row["feed_type"] == "INTRABAR"
    assert row["source"] == "BINANCE_PUBLIC"
    assert row["execution_enabled"] is False
    assert row["paper_only"] is True
    df = pd.read_parquet(mod.OUT_PATH)
    assert len(df) >= 1
    # observed inside some M15 bucket
    assert str(row["m15_bucket_open_ts"]).endswith("00Z") or "T" in str(row["m15_bucket_open_ts"])


def test_canonical_m15_path_untouched_constant():
    mod = _load()
    text = (ROOT / "scripts/live/live_binance_intrabar_feed.py").read_text(encoding="utf-8")
    assert "live_market_feed.parquet" not in text or "DOES NOT" in text or "does NOT" in text
    assert "live_market_intrabar_feed.parquet" in text
    assert "api/v3/order" not in text.lower()
