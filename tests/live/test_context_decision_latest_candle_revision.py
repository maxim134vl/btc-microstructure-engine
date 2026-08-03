from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "live"))

import append_context_decision_log as logger


def make_row(
    candle: str,
    payload_hash: str,
    context: str,
    episode: str,
    written_at: str,
) -> dict:
    row = {column: None for column in logger.DECISION_COLUMNS}
    row.update(
        {
            "candle_timestamp": candle,
            "decision_payload_hash": payload_hash,
            "decision_id": f"decision-{payload_hash}",
            "decision_written_at_utc": written_at,
            "active_market_context": context,
            "lifecycle_episode_id": episode,
            "record_origin": "LIVE",
            "decision_stale": False,
            "technical_refresh_lag_present": False,
        }
    )
    return row


def test_latest_candle_can_be_revised_with_audit_record(tmp_path: Path) -> None:
    log_path = tmp_path / "context_decision_log.parquet"

    first = make_row(
        "2026-08-02T21:45:00Z",
        "old-hash",
        "LONG_CONTEXT",
        "941",
        "2026-08-02T21:46:00Z",
    )
    corrected = make_row(
        "2026-08-02T21:45:00Z",
        "new-hash",
        "SHORT_CONTEXT",
        "942",
        "2026-08-02T21:47:00Z",
    )

    assert logger.append_decision(first, log_path=log_path)["status"] == "APPENDED"

    result = logger.append_decision(corrected, log_path=log_path)
    assert result["status"] == "REVISED_LATEST_CANDLE"

    written = pd.read_parquet(log_path)
    assert len(written) == 1
    assert written.iloc[0]["active_market_context"] == "SHORT_CONTEXT"
    assert str(written.iloc[0]["lifecycle_episode_id"]) == "942"

    revision_path = tmp_path / "context_decision_log_revisions.jsonl"
    revisions = revision_path.read_text(encoding="utf-8").splitlines()
    assert len(revisions) == 1

    revision = json.loads(revisions[0])
    assert revision["old_decision_payload_hash"] == "old-hash"
    assert revision["new_decision_payload_hash"] == "new-hash"


def test_historical_candle_revision_remains_forbidden(tmp_path: Path) -> None:
    log_path = tmp_path / "context_decision_log.parquet"

    logger.append_decision(
        make_row(
            "2026-08-02T21:45:00Z",
            "first-hash",
            "LONG_CONTEXT",
            "941",
            "2026-08-02T21:46:00Z",
        ),
        log_path=log_path,
    )
    logger.append_decision(
        make_row(
            "2026-08-02T22:00:00Z",
            "second-hash",
            "SHORT_CONTEXT",
            "942",
            "2026-08-02T22:01:00Z",
        ),
        log_path=log_path,
    )

    with pytest.raises(
        logger.DecisionLoggerError,
        match="HISTORICAL_MUTATION_CONFLICT",
    ):
        logger.append_decision(
            make_row(
                "2026-08-02T21:45:00Z",
                "forbidden-hash",
                "SHORT_CONTEXT",
                "942",
                "2026-08-02T22:02:00Z",
            ),
            log_path=log_path,
        )
