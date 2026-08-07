from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd


ROOT = Path.cwd()
MODULE_PATH = Path(
    os.environ.get(
        "M15_LOGGER_MODULE_PATH",
        str(ROOT / "scripts/live/append_context_decision_log.py"),
    )
)

_spec = importlib.util.spec_from_file_location(
    "append_context_decision_log_m15_regression",
    MODULE_PATH,
)
assert _spec is not None and _spec.loader is not None
logger = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = logger
_spec.loader.exec_module(logger)


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "candle_timestamp": "2026-08-06T04:45:00Z",
                "decision_written_at_utc": "2026-08-06T05:01:54Z",
                "decision_id": "short-before",
                "active_market_context": "SHORT_CONTEXT",
                "candidate_context": None,
            },
            {
                "candle_timestamp": "2026-08-06T05:00:00Z",
                "decision_written_at_utc": "2026-08-06T05:16:59Z",
                "decision_id": "long-current",
                "active_market_context": "LONG_CONTEXT",
                "candidate_context": None,
            },
            {
                "candle_timestamp": "2026-08-06T05:15:00Z",
                "decision_written_at_utc": "2026-08-06T05:31:54Z",
                "decision_id": "short-future",
                "active_market_context": "SHORT_CONTEXT",
                "candidate_context": None,
            },
        ]
    )


def test_previous_decision_lookup_is_strictly_causal() -> None:
    history = _history()

    prev_0500 = logger.previous_decision_before(
        history,
        "2026-08-06T05:00:00Z",
    )
    assert prev_0500 is not None
    assert prev_0500["decision_id"] == "short-before"
    assert prev_0500["active_market_context"] == "SHORT_CONTEXT"

    prev_0515 = logger.previous_decision_before(
        history,
        "2026-08-06T05:15:00Z",
    )
    assert prev_0515 is not None
    assert prev_0515["decision_id"] == "long-current"
    assert prev_0515["active_market_context"] == "LONG_CONTEXT"


def test_previous_lookup_never_uses_future_row_for_backfill_gap() -> None:
    history = pd.DataFrame(
        [
            {
                "candle_timestamp": "2026-08-06T04:45:00Z",
                "decision_written_at_utc": "2026-08-06T05:01:54Z",
                "decision_id": "past",
                "active_market_context": "SHORT_CONTEXT",
            },
            {
                "candle_timestamp": "2026-08-06T05:15:00Z",
                "decision_written_at_utc": "2026-08-06T05:31:54Z",
                "decision_id": "future",
                "active_market_context": "SHORT_CONTEXT",
            },
        ]
    )

    prev = logger.previous_decision_before(
        history,
        "2026-08-06T05:00:00Z",
    )
    assert prev is not None
    assert prev["decision_id"] == "past"


def test_latest_candle_revision_does_not_use_itself_as_previous() -> None:
    history = _history()

    prev = logger.previous_decision_before(
        history,
        "2026-08-06T05:00:00Z",
    )

    assert prev is not None
    assert prev["decision_id"] == "short-before"
    assert prev["decision_id"] != "long-current"


def test_live_run_once_passes_strict_previous_decision(tmp_path, monkeypatch) -> None:
    current = pd.Timestamp("2026-08-06T05:00:00Z")

    source = tmp_path / "source.parquet"
    pd.DataFrame({"timestamp": [current]}).to_parquet(source, index=False)

    decision_log = tmp_path / "context_decision_log.parquet"
    _history().to_parquet(decision_log, index=False)

    runtime_log = tmp_path / "runtime.log"
    runtime_log.write_text("", encoding="utf-8")

    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return {
            "decision_id": "new-decision",
            "candle_timestamp": "2026-08-06T05:00:00Z",
            "decision_payload_hash": "test-hash",
        }

    monkeypatch.setattr(logger, "build_context_decision_row", fake_builder)
    monkeypatch.setattr(
        logger,
        "append_decision",
        lambda row, log_path: {"status": "TEST_APPEND"},
    )
    monkeypatch.setattr(logger, "parse_runtime_cycles", lambda path: {})
    monkeypatch.setattr(logger, "source_files_hash", lambda paths: "test-source-hash")

    logger.run_once(
        log_path=decision_log,
        live_path=source,
        auction_path=source,
        cognitive_path=source,
        final_path=source,
        lifecycle_path=source,
        runtime_log_path=runtime_log,
    )

    previous = captured.get("previous_decision")
    assert previous is not None
    assert previous["decision_id"] == "short-before"
    assert previous["active_market_context"] == "SHORT_CONTEXT"
