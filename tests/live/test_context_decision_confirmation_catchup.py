"""Confirmation catch-up: rewrite frozen decisions after lifecycle confirms opposite."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "live"))

import append_context_decision_log as logger


def _frame(timestamps: list[str], **cols) -> pd.DataFrame:
    n = len(timestamps)
    data: dict = {
        "timestamp": list(pd.to_datetime(timestamps, utc=True)),
        "close": [100.0 + i for i in range(n)],
    }
    for key, value in cols.items():
        if isinstance(value, list):
            data[key] = value
        else:
            data[key] = [value] * n
    return pd.DataFrame(data)


def _write_sources(tmp_path: Path) -> dict[str, Path]:
    """Lifecycle flips to SHORT ACTIVE on the dump bar; decision log still LONG."""
    ts = [
        "2026-08-10T12:00:00Z",
        "2026-08-10T12:15:00Z",
        "2026-08-10T12:30:00Z",
    ]
    paths = {
        "live": tmp_path / "live_market_feed.parquet",
        "auction": tmp_path / "auction.parquet",
        "cognitive": tmp_path / "cognitive.parquet",
        "final": tmp_path / "final.parquet",
        "lifecycle": tmp_path / "lifecycle.parquet",
        "runtime": tmp_path / "runtime.log",
        "log": tmp_path / "context_decision_log.parquet",
    }
    _frame(
        ts,
        open=1.0,
        high=1.0,
        low=1.0,
        volume=1.0,
    ).to_parquet(paths["live"], index=False)
    _frame(ts, auction_episode="DISTRIBUTION", episode_status="CONFIRMED").to_parquet(
        paths["auction"], index=False
    )
    _frame(
        ts,
        cognitive_market_state="UPPER_DISTRIBUTION",
        state_status="CONFIRMED",
        state_direction="SHORT",
    ).to_parquet(paths["cognitive"], index=False)
    _frame(ts, market_context="SHORT_CONTEXT", context_status="ACTIVE").to_parquet(
        paths["final"], index=False
    )
    _frame(
        ts,
        raw_market_context=["LONG_CONTEXT", "SHORT_CONTEXT", "SHORT_CONTEXT"],
        raw_context_status=["ACTIVE", "ACTIVE", "ACTIVE"],
        raw_cognitive_market_state="UPPER_DISTRIBUTION",
        raw_state_direction="SHORT",
        raw_auction_episode="DISTRIBUTION",
        active_market_context=["LONG_CONTEXT", "SHORT_CONTEXT", "SHORT_CONTEXT"],
        lifecycle_state=["ACTIVE", "ACTIVE", "ACTIVE"],
        active_context_age_bars=[5, 0, 1],
        active_context_started_at=list(
            pd.to_datetime(
                ["2026-08-10T10:00:00Z", "2026-08-10T12:15:00Z", "2026-08-10T12:15:00Z"],
                utc=True,
            )
        ),
        previous_active_market_context=[None, "LONG_CONTEXT", "LONG_CONTEXT"],
        transition_reason=[
            "continuation",
            "confirmed opposite context replaced prior active",
            "continuation",
        ],
        invalidation_type="NONE",
        action_allowed=False,
        shadow_only=True,
    ).to_parquet(paths["lifecycle"], index=False)
    paths["runtime"].write_text("PIPELINE CYCLE: 1\n", encoding="utf-8")

    # Frozen decisions: dump bar still LONG (wrote while opposite was DEVELOPING).
    stale = []
    for i, candle in enumerate(ts):
        row = {column: None for column in logger.DECISION_COLUMNS}
        row.update(
            {
                "candle_timestamp": candle,
                "decision_payload_hash": f"hash-{i}",
                "decision_id": f"decision-{i}",
                "decision_written_at_utc": "2026-08-10T12:32:00Z",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_episode_id": 1023,
                "record_origin": "LIVE",
                "confirmation_catchup": False,
                "decision_stale": False,
                "technical_refresh_lag_present": False,
            }
        )
        stale.append(row)
    pd.DataFrame(stale).to_parquet(paths["log"], index=False)
    return paths


def test_find_confirmation_catchup_timestamps_detects_flip(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)
    lifecycle = pd.read_parquet(paths["lifecycle"])
    existing = pd.read_parquet(paths["log"])
    stamps = logger.find_confirmation_catchup_timestamps(lifecycle, existing)
    assert [ts.isoformat().replace("+00:00", "Z") for ts in stamps] == [
        "2026-08-10T12:15:00Z",
        "2026-08-10T12:30:00Z",
    ]


def test_apply_confirmation_catchup_rewrites_and_is_idempotent(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)
    result = logger.apply_confirmation_catchup(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
    )
    assert result["status"] == "CATCHUP_APPLIED"
    assert result["rows_revised"] == 2
    assert result["rows_before"] == result["rows_after"] == 3

    written = pd.read_parquet(paths["log"]).sort_values("candle_timestamp")
    contexts = list(written["active_market_context"].astype(str))
    assert contexts[0] == "LONG_CONTEXT"
    assert contexts[1] == "SHORT_CONTEXT"
    assert contexts[2] == "SHORT_CONTEXT"
    assert bool(written.iloc[1]["confirmation_catchup"]) is True
    assert written.iloc[1]["record_origin"] == logger.RECORD_ORIGIN_CONFIRMATION_CATCHUP

    revision_path = paths["log"].with_name("context_decision_log_revisions.jsonl")
    revisions = [json.loads(line) for line in revision_path.read_text().splitlines() if line]
    assert len(revisions) == 2
    assert revisions[0]["revision_type"] == "CONFIRMATION_CATCHUP"

    again = logger.apply_confirmation_catchup(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
    )
    assert again["status"] == "NOOP"
    assert again["rows_revised"] == 0


def test_confirmation_catchup_dry_run_does_not_write(tmp_path: Path) -> None:
    paths = _write_sources(tmp_path)
    before = paths["log"].read_bytes()
    result = logger.apply_confirmation_catchup(
        log_path=paths["log"],
        dry_run=True,
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
    )
    assert result["status"] == "DRY_RUN"
    assert result["catchup_candidates"] == 2
    assert paths["log"].read_bytes() == before
