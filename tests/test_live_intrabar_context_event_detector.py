#!/usr/bin/env python3
"""Tests for live intrabar context event detector."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts/live/live_intrabar_context_event_detector.py"
    spec = importlib.util.spec_from_file_location("live_intrabar_context_event_detector", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_intrabar_context_event_detector"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed(tmp_path: Path, *, with_intrabar: bool = True) -> None:
    cog = tmp_path / "data/cognition"
    live = tmp_path / "data/live"
    cog.mkdir(parents=True)
    live.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "timestamp": "2026-07-21T15:00:00Z",
                "active_market_context": "OBSERVE",
                "lifecycle_state": "NO_ACTIVE_CONTEXT",
            },
            {
                "timestamp": "2026-07-21T15:15:00Z",
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "active_context_started_at": "2026-07-21T15:15:00Z",
            },
        ]
    ).to_parquet(cog / "market_context_lifecycle_memory.parquet", index=False)
    pd.DataFrame({"timestamp": ["2026-07-21T15:00:00Z", "2026-07-21T15:15:00Z"], "close": [1.0, 1.1]}).to_parquet(
        live / "live_market_feed.parquet", index=False
    )
    if with_intrabar:
        pd.DataFrame(
            [
                {
                    "observed_at_utc": "2026-07-21T15:15:07.123456Z",
                    "symbol": "BTCUSDT",
                    "price": 65010.0,
                    "m15_bucket_open_ts": "2026-07-21T15:15:00Z",
                    "m15_bucket_close_ts": "2026-07-21T15:30:00Z",
                    "is_closed_candle": False,
                    "source": "BINANCE_PUBLIC",
                    "feed_type": "INTRABAR",
                }
            ]
        ).to_parquet(live / "live_market_intrabar_feed.parquet", index=False)


def test_detector_uses_intrabar_observed_at(tmp_path: Path):
    mod = _load()
    _seed(tmp_path, with_intrabar=True)
    df = mod.build_intrabar_context_events(root=tmp_path)
    assert not df.empty
    row = df.iloc[-1].to_dict()
    assert str(row["event_detected_at"]).startswith("2026-07-21T15:15:07")
    assert row["provisional"] is True
    assert "PROVISIONAL" in str(row["no_repaint_basis"])
    assert float(row["intrabar_price"]) == 65010.0
    out = mod.write_events(df, root=tmp_path)
    assert out == tmp_path / "data/live/intrabar_context_events.parquet"
    assert "cognition" not in out.parts


def test_writes_only_live_intrabar_events(tmp_path: Path):
    mod = _load()
    _seed(tmp_path, with_intrabar=False)
    df = mod.build_intrabar_context_events(root=tmp_path)
    assert not df.empty
    out = mod.write_events(df, root=tmp_path)
    assert out.exists()
    assert not list((tmp_path / "data/cognition").glob("intrabar*"))


def test_no_cognition_write_on_main(tmp_path: Path):
    mod = _load()
    _seed(tmp_path, with_intrabar=True)
    before = {p.name for p in (tmp_path / "data/cognition").iterdir()}
    assert mod.main(root=tmp_path) == 0
    after = {p.name for p in (tmp_path / "data/cognition").iterdir()}
    assert before == after
    assert (tmp_path / "data/live/intrabar_context_events.parquet").exists()


def test_provisional_clearly_marked(tmp_path: Path):
    mod = _load()
    _seed(tmp_path, with_intrabar=True)
    df = mod.build_intrabar_context_events(root=tmp_path)
    assert bool(df.iloc[-1]["provisional"]) is True
    snap = json.loads(df.iloc[-1]["evidence_snapshot"])
    assert "live_market_intrabar_feed" in snap["evidence_fields"] or "observed_at_utc_inside_m15_bucket" in snap[
        "evidence_fields"
    ]
