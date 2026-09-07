"""Tests for shadow-only append-only context decision logger."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "live" / "append_context_decision_log.py"

spec = importlib.util.spec_from_file_location("append_context_decision_log", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["append_context_decision_log"] = mod
spec.loader.exec_module(mod)


def _frame(timestamps: list[str], **cols) -> pd.DataFrame:
    n = len(timestamps)
    data: dict = {
        "timestamp": list(pd.to_datetime(timestamps, utc=True)),
        "close": [100.0 + i for i in range(n)],
    }
    for key, value in cols.items():
        if isinstance(value, list):
            data[key] = value
        elif isinstance(value, (pd.Series, pd.Index, pd.DatetimeIndex)):
            data[key] = list(value)
        else:
            data[key] = [value] * n
    return pd.DataFrame(data)


def _sources(tmp_path: Path, *, live_extra: bool = False) -> dict[str, Path]:
    ts = [
        "2026-07-19T12:00:00Z",
        "2026-07-19T12:15:00Z",
        "2026-07-19T12:30:00Z",
    ]
    live_ts = ts + (["2026-07-19T12:45:00Z"] if live_extra else [])
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
        live_ts,
        open=[1.0] * len(live_ts),
        high=[1.0] * len(live_ts),
        low=[1.0] * len(live_ts),
        volume=[1.0] * len(live_ts),
    ).to_parquet(paths["live"], index=False)
    _frame(
        ts,
        auction_episode="ACCEPTANCE_HIGHER",
        episode_status="CONFIRMED",
    ).to_parquet(paths["auction"], index=False)
    _frame(
        ts,
        cognitive_market_state="LOWER_ABSORPTION",
        state_status="CONFIRMED",
        state_direction="LONG",
    ).to_parquet(paths["cognitive"], index=False)
    _frame(
        ts,
        market_context="LONG_CONTEXT",
        context_status="ACTIVE",
    ).to_parquet(paths["final"], index=False)
    _frame(
        ts,
        raw_market_context="LONG_CONTEXT",
        raw_context_status="ACTIVE",
        raw_cognitive_market_state="LOWER_ABSORPTION",
        raw_state_direction="LONG",
        raw_auction_episode="ACCEPTANCE_HIGHER",
        active_market_context="LONG_CONTEXT",
        lifecycle_state="ACTIVE",
        active_context_age_bars=[0, 1, 2],
        active_context_started_at=pd.to_datetime(["2026-07-19T12:00:00Z"] * 3, utc=True),
        invalidation_type="NONE",
        action_allowed=False,
        shadow_only=True,
    ).to_parquet(paths["lifecycle"], index=False)
    paths["runtime"].write_text(
        "\n".join(
            [
                "PIPELINE CYCLE: 1",
                "PIPELINE CYCLE: 2",
                "PIPELINE CYCLE: 10",
                "PIPELINE CYCLE: 1",
                "PIPELINE CYCLE: 5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def _run(paths: dict[str, Path]):
    return mod.run_once(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
    )


def test_creates_decision_log_when_missing(tmp_path: Path):
    paths = _sources(tmp_path)
    assert not paths["log"].exists()
    result = _run(paths)
    assert result["status"] == "APPENDED"
    assert paths["log"].exists()
    frame = pd.read_parquet(paths["log"])
    assert len(frame) == 1
    assert frame.iloc[0]["candle_timestamp"].endswith("12:30:00Z")


def test_appends_only_newer_candle_timestamp(tmp_path: Path):
    paths = _sources(tmp_path)
    first = _run(paths)
    assert first["status"] == "APPENDED"
    # Re-run without newer lifecycle candle → not newer / duplicate.
    second = _run(paths)
    assert second["status"] in {"SKIPPED_DUPLICATE", "SKIPPED_NOT_NEWER"}
    assert second["rows_after"] == 1

    # Advance lifecycle + live by one candle.
    life = pd.read_parquet(paths["lifecycle"])
    extra = life.iloc[[-1]].copy()
    extra["timestamp"] = pd.Timestamp("2026-07-19T12:45:00Z")
    extra["active_context_age_bars"] = 3
    life2 = pd.concat([life, extra], ignore_index=True)
    life2.to_parquet(paths["lifecycle"], index=False)
    live = pd.read_parquet(paths["live"])
    live_extra = live.iloc[[-1]].copy()
    live_extra["timestamp"] = pd.Timestamp("2026-07-19T12:45:00Z")
    pd.concat([live, live_extra], ignore_index=True).to_parquet(paths["live"], index=False)
    for name in ("auction", "cognitive", "final"):
        frame = pd.read_parquet(paths[name])
        row = frame.iloc[[-1]].copy()
        row["timestamp"] = pd.Timestamp("2026-07-19T12:45:00Z")
        pd.concat([frame, row], ignore_index=True).to_parquet(paths[name], index=False)

    third = _run(paths)
    assert third["status"] == "APPENDED"
    assert third["rows_after"] == 2


def test_does_not_duplicate_same_candle_same_hash(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    again = _run(paths)
    assert again["status"] == "SKIPPED_DUPLICATE"
    assert again["rows_after"] == 1


def test_revises_latest_candle_different_hash_with_audit_trail(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)

    life = pd.read_parquet(paths["lifecycle"])
    life.loc[life.index[-1], "active_market_context"] = "SHORT_CONTEXT"
    life.loc[life.index[-1], "lifecycle_state"] = "ACTIVE"
    life.to_parquet(paths["lifecycle"], index=False)

    _run(paths)

    logs = list(tmp_path.rglob("context_decision_log.parquet"))
    assert len(logs) == 1

    written = pd.read_parquet(logs[0])
    assert written.iloc[-1]["active_market_context"] == "SHORT_CONTEXT"

    revision_path = logs[0].with_name("context_decision_log_revisions.jsonl")
    assert revision_path.exists()
    assert revision_path.read_text(encoding="utf-8").strip()



def test_preserves_existing_rows(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    before = pd.read_parquet(paths["log"]).copy()
    # Force not-newer skip
    _run(paths)
    after = pd.read_parquet(paths["log"])
    assert list(before["decision_id"]) == list(after["decision_id"])
    assert list(before["decision_payload_hash"]) == list(after["decision_payload_hash"])


def test_propagates_lifecycle_observe_diagnostics(tmp_path: Path):
    paths = _sources(tmp_path)
    life = pd.read_parquet(paths["lifecycle"])
    idx = life.index[-1]
    life.loc[idx, "active_market_context"] = "OBSERVE"
    life.loc[idx, "lifecycle_state"] = "STALE_COGNITION"
    life.loc[idx, "transition_reason"] = "stale upstream cognition while live candles update (age_minutes=60)"
    life.loc[idx, "lifecycle_state_reason"] = life.loc[idx, "transition_reason"]
    life.loc[idx, "state_entered_at"] = pd.Timestamp("2026-07-19T12:30:00Z")
    life.loc[idx, "state_age_minutes"] = 0.0
    life.loc[idx, "transition_block_reason"] = "STALE_COGNITION"
    life.loc[idx, "cognition_state_age_minutes"] = 240.0
    life.loc[idx, "upstream_cognition_freshness_minutes"] = 60.0
    life.loc[idx, "market_feed_age_minutes"] = 15.0
    life.loc[idx, "market_activity_score"] = 0.42
    life.loc[idx, "observe_escape_candidate"] = False
    life.loc[idx, "observe_block_reason"] = "STALE_COGNITION"
    life.to_parquet(paths["lifecycle"], index=False)

    result = _run(paths)
    assert result["status"] == "APPENDED"
    row = pd.read_parquet(paths["log"]).iloc[0]
    assert row["lifecycle_state"] == "STALE_COGNITION"
    assert row["transition_block_reason"] == "STALE_COGNITION"
    assert row["observe_block_reason"] == "STALE_COGNITION"
    assert float(row["cognition_state_age_minutes"]) == 240.0
    assert float(row["upstream_cognition_freshness_minutes"]) == 60.0
    assert float(row["market_feed_age_minutes"]) == 15.0
    assert float(row["market_activity_score"]) == 0.42
    assert row["signal_eligibility_status"] == "BLOCKED_STALE_COGNITION"
    assert "STALE_COGNITION" in str(row["signal_block_reasons"])
    assert row["paper_action_candidate"] == "NO_TRADE_STALE_COGNITION"
    assert bool(row["paper_signal_write_allowed"]) is False
    assert bool(row["paper_loop_allowed"]) is False


def test_reports_stale_lifecycle_vs_live_feed(tmp_path: Path):
    paths = _sources(tmp_path, live_extra=True)
    result = _run(paths)
    assert result["status"] == "APPENDED"
    frame = pd.read_parquet(paths["log"])
    row = frame.iloc[0]
    # Live ahead of lifecycle is PIPELINE_PENDING, not permanent decision-data stale.
    assert bool(row["decision_stale"]) is False
    assert bool(row["pipeline_pending"]) is True
    assert bool(row["technical_refresh_lag_present"]) is True
    assert row["decision_freshness_status"] == "PIPELINE_PENDING"
    assert bool(row["execution_readiness_blocked"]) is True
    assert float(row["live_to_lifecycle_lag_seconds"]) == 900.0
    assert row["signal_eligibility_status"] == "BLOCKED_PIPELINE_PENDING"


def test_aligned_lifecycle_and_decision_not_stale(tmp_path: Path):
    paths = _sources(tmp_path, live_extra=False)
    result = _run(paths)
    assert result["status"] == "APPENDED"
    row = pd.read_parquet(paths["log"]).iloc[0]
    assert bool(row["decision_stale"]) is False
    assert bool(row["pipeline_pending"]) is False
    assert row["decision_freshness_status"] == "FRESH"
    assert row["candle_timestamp"].endswith("12:30:00Z")


def test_wall_clock_late_append_still_fresh_for_matching_bar(tmp_path: Path):
    paths = _sources(tmp_path, live_extra=False)
    # Build row as-of a later wall clock; data timestamps remain aligned.
    live = pd.read_parquet(paths["live"])
    auction = pd.read_parquet(paths["auction"])
    cognitive = pd.read_parquet(paths["cognitive"])
    final = pd.read_parquet(paths["final"])
    lifecycle = pd.read_parquet(paths["lifecycle"])
    runtime = mod.parse_runtime_cycles(paths["runtime"])
    row = mod.build_decision_row(
        live=live,
        auction=auction,
        cognitive=cognitive,
        final=final,
        lifecycle=lifecycle,
        runtime=runtime,
        source_hash="x",
        written_at=pd.Timestamp("2026-07-19T13:05:00Z"),
    )
    assert bool(row["decision_stale"]) is False
    assert bool(row["pipeline_pending"]) is False
    assert row["decision_freshness_status"] == "FRESH"


def test_classify_lifecycle_ahead_within_grace_is_pipeline_pending():
    out = mod.classify_decision_freshness(
        decision_market_ts="2026-07-19T12:15:00Z",
        lifecycle_ts="2026-07-19T12:30:00Z",
        live_ts="2026-07-19T12:30:00Z",
        now_utc=pd.Timestamp("2026-07-19T12:31:00Z").to_pydatetime(),
        pipeline_grace_seconds=900.0,
    )
    assert out["pipeline_pending"] is True
    assert out["decision_stale"] is False
    assert out["decision_freshness_status"] == "PIPELINE_PENDING"


def test_classify_lifecycle_ahead_beyond_grace_is_stale_decision():
    out = mod.classify_decision_freshness(
        decision_market_ts="2026-07-19T12:00:00Z",
        lifecycle_ts="2026-07-19T12:30:00Z",
        live_ts="2026-07-19T12:30:00Z",
        now_utc=pd.Timestamp("2026-07-19T12:45:00Z").to_pydatetime(),
        pipeline_grace_seconds=900.0,
    )
    assert out["decision_stale"] is True
    assert out["pipeline_pending"] is False
    assert out["decision_freshness_status"] == "STALE_DECISION"


def test_classify_ns_us_timestamp_mismatch_does_not_raise():
    life = pd.Timestamp("2026-07-19T12:30:00Z").as_unit("ns")
    live = pd.Timestamp("2026-07-19T12:30:00Z").as_unit("us")
    out = mod.classify_decision_freshness(
        decision_market_ts=life,
        lifecycle_ts=live,
        live_ts=live,
    )
    assert out["decision_freshness_status"] == "FRESH"
    assert out["decision_stale"] is False


def test_classify_nat_returns_degraded_without_exception():
    out = mod.classify_decision_freshness(
        decision_market_ts=pd.NaT,
        lifecycle_ts="2026-07-19T12:30:00Z",
        live_ts="2026-07-19T12:30:00Z",
    )
    assert out["decision_stale"] is True
    assert out["decision_freshness_status"] == "DEGRADED_MISSING_TIMESTAMPS"


def test_fresh_long_decision_not_blocked_as_stale(tmp_path: Path):
    paths = _sources(tmp_path, live_extra=False)
    result = _run(paths)
    assert result["status"] == "APPENDED"
    row = pd.read_parquet(paths["log"]).iloc[0]
    assert row["active_market_context"] == "LONG_CONTEXT"
    assert bool(row["decision_stale"]) is False
    assert row["signal_eligibility_status"] != "BLOCKED_STALE_CONTEXT"
    assert row["signal_eligibility_status"] != "BLOCKED_PIPELINE_PENDING"


def test_does_not_use_visual_json_as_source():
    src = MODULE_PATH.read_text(encoding="utf-8")
    assert "lifecycle_latest.json" not in src
    assert "visual JSON" in src or "visual_json" in src
    assert "Does NOT use visual JSON" in src or "Do NOT use visual JSON" in src or "never a decision source" in src


def test_safety_flags_always_false_true(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    row = pd.read_parquet(paths["log"]).iloc[0]
    assert bool(row["action_allowed"]) is False
    assert bool(row["shadow_only"]) is True
    assert bool(row["execution_enabled"]) is False
    assert bool(row["orders_created"]) is False
    assert bool(row["paper_orders_created"]) is False
    assert bool(row["visual_json_used_for_execution"]) is False


def test_runtime_cycle_parsing_handles_reset_segments(tmp_path: Path):
    log = tmp_path / "runtime.log"
    log.write_text(
        "\n".join(
            [
                "PIPELINE CYCLE: 1",
                "PIPELINE CYCLE: 50",
                "PIPELINE CYCLE: 1",
                "PIPELINE CYCLE: 2",
                "PIPELINE CYCLE: 9",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    parsed = mod.parse_runtime_cycles(log)
    assert parsed["total_runtime_log_cycles"] == 5
    assert parsed["runtime_segments"] == 2
    assert parsed["pipeline_cycle"] == 9


def test_missing_optional_fields_do_not_crash_logger(tmp_path: Path):
    paths = _sources(tmp_path)
    # Drop optional cognitive columns; logger should still build via lifecycle fallbacks.
    cog = pd.read_parquet(paths["cognitive"])
    cog = cog[["timestamp", "close"]]
    cog.to_parquet(paths["cognitive"], index=False)
    result = _run(paths)
    assert result["status"] == "APPENDED"


def test_missing_required_source_files_fails_safely(tmp_path: Path):
    paths = _sources(tmp_path)
    paths["lifecycle"].unlink()
    with pytest.raises(mod.DecisionLoggerError, match="Missing required source"):
        _run(paths)
    assert not paths["log"].exists()


def test_source_hash_and_decision_hash_stable_for_same_payload(tmp_path: Path):
    paths = _sources(tmp_path)
    live = mod.load_parquet(paths["live"])
    auction = mod.load_parquet(paths["auction"])
    cognitive = mod.load_parquet(paths["cognitive"])
    final = mod.load_parquet(paths["final"])
    lifecycle = mod.load_parquet(paths["lifecycle"])
    runtime = mod.parse_runtime_cycles(paths["runtime"])
    src_hash = mod.source_files_hash(
        [paths["live"], paths["auction"], paths["cognitive"], paths["final"], paths["lifecycle"]]
    )
    written = pd.Timestamp("2026-07-19T13:00:00Z")
    row1 = mod.build_decision_row(
        live=live,
        auction=auction,
        cognitive=cognitive,
        final=final,
        lifecycle=lifecycle,
        runtime=runtime,
        source_hash=src_hash,
        written_at=written,
        runtime_pid=12345,
    )
    row2 = mod.build_decision_row(
        live=live,
        auction=auction,
        cognitive=cognitive,
        final=final,
        lifecycle=lifecycle,
        runtime=runtime,
        source_hash=src_hash,
        written_at=written,
        runtime_pid=12345,
    )
    # decision_id is unique, but payload hash ignores it.
    assert row1["decision_payload_hash"] == row2["decision_payload_hash"]
    assert row1["source_files_hash"] == row2["source_files_hash"]
    assert row1["decision_id"] != row2["decision_id"]


def test_enforce_safety_fields_never_enables_execution():
    row = mod.enforce_safety_fields(
        {
            "action_allowed": True,
            "shadow_only": False,
            "execution_enabled": True,
            "visual_json_used_for_execution": True,
            "orders_created": True,
            "paper_orders_created": True,
        }
    )
    assert row["action_allowed"] is False
    assert row["shadow_only"] is True
    assert row["execution_enabled"] is False
    assert row["visual_json_used_for_execution"] is False
    assert row["orders_created"] is False
    assert row["paper_orders_created"] is False
    assert row["execution_readiness_blocked"] is True


def _extend_sources_with_gap(paths: dict[str, Path], missing_ts: list[str]) -> None:
    """Add lifecycle (+ upstream) bars while leaving decision log without those candles."""
    for name in ("live", "auction", "cognitive", "final", "lifecycle"):
        frame = pd.read_parquet(paths[name])
        extras = []
        for ts in missing_ts:
            row = frame.iloc[[-1]].copy()
            row["timestamp"] = pd.Timestamp(ts)
            if name == "lifecycle" and "active_context_age_bars" in row.columns:
                row["active_context_age_bars"] = int(row["active_context_age_bars"].iloc[0]) + 1
            extras.append(row)
        pd.concat([frame] + extras, ignore_index=True).to_parquet(paths[name], index=False)


def test_backfill_adds_single_missing_timestamp(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    _extend_sources_with_gap(paths, ["2026-07-19T12:45:00Z"])
    # Tip append would add 12:45, but first create an internal gap by appending a later tip.
    # Simulate: existing has 12:30; lifecycle has 12:45 and 13:00; decision only 12:30+13:00.
    for name in ("live", "auction", "cognitive", "final", "lifecycle"):
        frame = pd.read_parquet(paths[name])
        row = frame.iloc[[-1]].copy()
        row["timestamp"] = pd.Timestamp("2026-07-19T13:00:00Z")
        pd.concat([frame, row], ignore_index=True).to_parquet(paths[name], index=False)
    # Append tip 13:00 via live logger (skips filling 12:45).
    tip = _run(paths)
    assert tip["status"] == "APPENDED"
    before = pd.read_parquet(paths["log"])
    assert "2026-07-19T12:45:00Z" not in set(before["candle_timestamp"].astype(str))

    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:45:00Z",
        to_timestamp="2026-07-19T12:45:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 1
    after = pd.read_parquet(paths["log"])
    assert len(after) == len(before) + 1
    assert "2026-07-19T12:45:00Z" in set(after["candle_timestamp"].astype(str))


def test_backfill_restores_consecutive_missing_timestamps(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    gap = ["2026-07-19T12:45:00Z", "2026-07-19T13:00:00Z", "2026-07-19T13:15:00Z"]
    _extend_sources_with_gap(paths, gap)
    for name in ("live", "auction", "cognitive", "final", "lifecycle"):
        frame = pd.read_parquet(paths[name])
        row = frame.iloc[[-1]].copy()
        row["timestamp"] = pd.Timestamp("2026-07-19T13:30:00Z")
        pd.concat([frame, row], ignore_index=True).to_parquet(paths[name], index=False)
    _run(paths)  # tip 13:30
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:45:00Z",
        to_timestamp="2026-07-19T13:15:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 3
    candles = set(pd.read_parquet(paths["log"])["candle_timestamp"].astype(str))
    for ts in gap:
        assert ts in candles


def test_backfill_internal_gap_not_limited_to_tip_only(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    _extend_sources_with_gap(paths, ["2026-07-19T12:45:00Z", "2026-07-19T13:00:00Z"])
    tip = _run(paths)
    assert tip["status"] == "APPENDED"
    assert tip["candle_timestamp"].endswith("13:00:00Z")
    # Internal missing 12:45 remains until backfill.
    frame = pd.read_parquet(paths["log"])
    assert "2026-07-19T12:45:00Z" not in set(frame["candle_timestamp"].astype(str))
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        default_from_existing_min=False,
    )
    assert result["rows_added"] >= 1
    candles = set(pd.read_parquet(paths["log"])["candle_timestamp"].astype(str))
    assert "2026-07-19T12:45:00Z" in candles


def test_backfill_does_not_rewrite_existing_timestamp(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    before = pd.read_parquet(paths["log"]).copy()
    life = pd.read_parquet(paths["lifecycle"])
    life.loc[life.index[-1], "active_market_context"] = "SHORT_CONTEXT"
    life.to_parquet(paths["lifecycle"], index=False)
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:30:00Z",
        to_timestamp="2026-07-19T12:30:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 0
    after = pd.read_parquet(paths["log"])
    assert list(before["decision_id"]) == list(after["decision_id"])
    assert list(before["decision_payload_hash"]) == list(after["decision_payload_hash"])
    assert after.iloc[0]["active_market_context"] == "LONG_CONTEXT"


def test_backfill_idempotent_second_pass(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    _extend_sources_with_gap(paths, ["2026-07-19T12:45:00Z"])
    for name in ("live", "auction", "cognitive", "final", "lifecycle"):
        frame = pd.read_parquet(paths[name])
        row = frame.iloc[[-1]].copy()
        row["timestamp"] = pd.Timestamp("2026-07-19T13:00:00Z")
        pd.concat([frame, row], ignore_index=True).to_parquet(paths[name], index=False)
    _run(paths)
    first = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:45:00Z",
        to_timestamp="2026-07-19T12:45:00Z",
        default_from_existing_min=False,
    )
    assert first["rows_added"] == 1
    mid = pd.read_parquet(paths["log"]).copy()
    second = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:45:00Z",
        to_timestamp="2026-07-19T12:45:00Z",
        default_from_existing_min=False,
    )
    assert second["rows_added"] == 0
    after = pd.read_parquet(paths["log"])
    assert list(mid["decision_id"]) == list(after["decision_id"])
    assert list(mid["decision_payload_hash"]) == list(after["decision_payload_hash"])


def test_backfill_dry_run_does_not_write(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    _extend_sources_with_gap(paths, ["2026-07-19T12:45:00Z"])
    before = paths["log"].read_bytes()
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        dry_run=True,
        from_timestamp="2026-07-19T12:45:00Z",
        to_timestamp="2026-07-19T12:45:00Z",
        default_from_existing_min=False,
    )
    assert result["dry_run"] is True
    assert result["rows_added"] == 1
    assert paths["log"].read_bytes() == before


def test_backfill_respects_max_rows(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    gap = ["2026-07-19T12:45:00Z", "2026-07-19T13:00:00Z", "2026-07-19T13:15:00Z"]
    _extend_sources_with_gap(paths, gap)
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        max_rows=2,
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 2


def test_backfill_from_to_window(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    gap = ["2026-07-19T12:45:00Z", "2026-07-19T13:00:00Z", "2026-07-19T13:15:00Z"]
    _extend_sources_with_gap(paths, gap)
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T13:00:00Z",
        to_timestamp="2026-07-19T13:00:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 1
    candles = set(pd.read_parquet(paths["log"])["candle_timestamp"].astype(str))
    assert "2026-07-19T13:00:00Z" in candles
    assert "2026-07-19T12:45:00Z" not in candles


def test_backfill_historical_observe_not_pipeline_pending(tmp_path: Path):
    paths = _sources(tmp_path, live_extra=True)
    _run(paths)
    # Existing tip may be pending vs live; backfill historical bar must be FRESH/PIT.
    life = pd.read_parquet(paths["lifecycle"])
    # Ensure an earlier lifecycle bar is OBSERVE and missing from log by rebuilding log empty
    # with only later tip present.
    paths["log"].unlink()
    # Keep only last lifecycle decision via tip append.
    _run(paths)
    missing = ["2026-07-19T12:00:00Z", "2026-07-19T12:15:00Z"]
    # Force observe diagnostics on 12:00
    life = pd.read_parquet(paths["lifecycle"])
    mask = life["timestamp"] == pd.Timestamp("2026-07-19T12:00:00Z")
    life.loc[mask, "active_market_context"] = "OBSERVE"
    life.loc[mask, "raw_market_context"] = "OBSERVE"
    life.loc[mask, "lifecycle_state"] = "NO_ACTIVE_CONTEXT"
    life.loc[mask, "observe_block_reason"] = "NO_DIRECTIONAL_CONTEXT"
    life.loc[mask, "transition_block_reason"] = "NONE"
    life.to_parquet(paths["lifecycle"], index=False)
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:00:00Z",
        to_timestamp="2026-07-19T12:15:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 2
    frame = pd.read_parquet(paths["log"])
    hist = frame[frame["candle_timestamp"].astype(str) == "2026-07-19T12:00:00Z"].iloc[0]
    assert hist["decision_freshness_status"] == "FRESH"
    assert bool(hist["pipeline_pending"]) is False
    assert bool(hist["decision_stale"]) is False
    assert str(hist["paper_action_candidate"]).startswith("NO_TRADE")
    assert hist["decision_freshness_status"] != "PIPELINE_PENDING"


def test_backfill_historical_stale_cognition(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    life = pd.read_parquet(paths["lifecycle"])
    # Make 12:15 missing by rewriting log to only 12:30, then backfill 12:15 as STALE_COGNITION.
    tip = pd.read_parquet(paths["log"])
    tip = tip[tip["candle_timestamp"].astype(str).str.endswith("12:30:00Z")]
    tip.to_parquet(paths["log"], index=False)
    mask = life["timestamp"] == pd.Timestamp("2026-07-19T12:15:00Z")
    life.loc[mask, "active_market_context"] = "OBSERVE"
    life.loc[mask, "lifecycle_state"] = "STALE_COGNITION"
    life.loc[mask, "observe_block_reason"] = "STALE_COGNITION"
    life.loc[mask, "transition_block_reason"] = "STALE_COGNITION"
    life.loc[mask, "upstream_cognition_freshness_minutes"] = 60.0
    life.to_parquet(paths["lifecycle"], index=False)
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:15:00Z",
        to_timestamp="2026-07-19T12:15:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 1
    row = pd.read_parquet(paths["log"])
    row = row[row["candle_timestamp"].astype(str) == "2026-07-19T12:15:00Z"].iloc[0]
    assert row["signal_eligibility_status"] == "BLOCKED_STALE_COGNITION"
    assert row["paper_action_candidate"] == "NO_TRADE_STALE_COGNITION"


def test_backfill_historical_candidate_uses_existing_logic(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    tip = pd.read_parquet(paths["log"])
    tip = tip[tip["candle_timestamp"].astype(str).str.endswith("12:30:00Z")]
    tip.to_parquet(paths["log"], index=False)
    life = pd.read_parquet(paths["lifecycle"])
    mask = life["timestamp"] == pd.Timestamp("2026-07-19T12:15:00Z")
    life.loc[mask, "active_market_context"] = "LONG_CONTEXT"
    life.loc[mask, "lifecycle_state"] = "CANDIDATE"
    life.loc[mask, "candidate_context"] = "LONG_CONTEXT"
    life.loc[mask, "candidate_started_at"] = pd.Timestamp("2026-07-19T12:15:00Z")
    life.loc[mask, "observe_block_reason"] = "NONE"
    life.to_parquet(paths["lifecycle"], index=False)
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:15:00Z",
        to_timestamp="2026-07-19T12:15:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 1
    row = pd.read_parquet(paths["log"])
    row = row[row["candle_timestamp"].astype(str) == "2026-07-19T12:15:00Z"].iloc[0]
    assert row["active_market_context"] == "LONG_CONTEXT"
    assert bool(row["decision_stale"]) is False
    assert row["decision_freshness_status"] == "FRESH"


def test_backfill_preserves_existing_stored_decision_stale_true(tmp_path: Path):
    paths = _sources(tmp_path, live_extra=True)
    _run(paths)
    frame = pd.read_parquet(paths["log"])
    # Force historical mislabel stored as True and ensure backfill does not rewrite it.
    frame.loc[frame.index[0], "decision_stale"] = True
    frame.loc[frame.index[0], "decision_payload_hash"] = "KEEP_ME"
    frame.to_parquet(paths["log"], index=False)
    _extend_sources_with_gap(paths, ["2026-07-19T13:00:00Z"])
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T13:00:00Z",
        to_timestamp="2026-07-19T13:00:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 1
    after = pd.read_parquet(paths["log"])
    old = after[after["candle_timestamp"].astype(str).str.endswith("12:30:00Z")].iloc[0]
    assert bool(old["decision_stale"]) is True
    assert old["decision_payload_hash"] == "KEEP_ME"


def test_backfill_gap_detection_ns_us_mismatch(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    life = pd.read_parquet(paths["lifecycle"])
    # Rewrite lifecycle timestamp dtype to us while decision log stays string/ns-compatible.
    life["timestamp"] = pd.to_datetime(life["timestamp"], utc=True).astype("datetime64[us, UTC]")
    extra = life.iloc[[-1]].copy()
    extra["timestamp"] = pd.Timestamp("2026-07-19T12:45:00Z").as_unit("us")
    life2 = pd.concat([life, extra], ignore_index=True)
    life2.to_parquet(paths["lifecycle"], index=False)
    for name in ("live", "auction", "cognitive", "final"):
        frame = pd.read_parquet(paths[name])
        row = frame.iloc[[-1]].copy()
        row["timestamp"] = pd.Timestamp("2026-07-19T12:45:00Z")
        pd.concat([frame, row], ignore_index=True).to_parquet(paths[name], index=False)
    missing = mod.find_missing_lifecycle_timestamps(
        pd.read_parquet(paths["lifecycle"]),
        pd.read_parquet(paths["log"]),
    )
    assert pd.Timestamp("2026-07-19T12:45:00Z") in missing


def test_backfill_nat_excluded_without_exception(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    life = pd.read_parquet(paths["lifecycle"])
    bad = life.iloc[[-1]].copy()
    bad["timestamp"] = pd.NaT
    life2 = pd.concat([life, bad], ignore_index=True)
    life2.to_parquet(paths["lifecycle"], index=False)
    missing = mod.find_missing_lifecycle_timestamps(life2, pd.read_parquet(paths["log"]))
    assert all(pd.notna(ts) for ts in missing)
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        dry_run=True,
        default_from_existing_min=False,
    )
    assert result["status"] == "DRY_RUN"


def test_backfill_duplicate_lifecycle_timestamps_fail_safe(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    life = pd.read_parquet(paths["lifecycle"])
    life2 = pd.concat([life, life.iloc[[-1]]], ignore_index=True)
    life2.to_parquet(paths["lifecycle"], index=False)
    before = paths["log"].read_bytes()
    with pytest.raises(mod.DecisionLoggerError, match="LIFECYCLE_DUPLICATE_TIMESTAMPS"):
        mod.backfill_missing_decisions(
            log_path=paths["log"],
            live_path=paths["live"],
            auction_path=paths["auction"],
            cognitive_path=paths["cognitive"],
            final_path=paths["final"],
            lifecycle_path=paths["lifecycle"],
            runtime_log_path=paths["runtime"],
            default_from_existing_min=False,
        )
    assert paths["log"].read_bytes() == before


def test_decision_row_carries_origin_without_change(tmp_path: Path):
    paths = _sources(tmp_path)
    life = pd.read_parquet(paths["lifecycle"])
    life["context_origin_price"] = 111.0
    life["context_entered_at"] = pd.to_datetime(life["timestamp"], utc=True)
    life["context_episode_id"] = 7
    life["context_direction"] = "LONG_CONTEXT"
    life["context_distance_bps"] = 12.5
    life["context_favorable_distance_bps"] = 12.5
    life["context_adverse_distance_bps"] = 0.0
    life.to_parquet(paths["lifecycle"], index=False)
    result = _run(paths)
    assert result["status"] == "APPENDED"
    row = pd.read_parquet(paths["log"]).iloc[0]
    assert float(row["context_origin_price"]) == 111.0
    assert int(row["context_episode_id"]) == 7
    assert row["context_direction"] == "LONG_CONTEXT"
    assert float(row["context_distance_bps"]) == 12.5


def test_backfill_preserves_point_in_time_origin(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    life = pd.read_parquet(paths["lifecycle"])
    # Make 12:15 missing from log and give it a distinct origin.
    tip = pd.read_parquet(paths["log"])
    tip = tip[tip["candle_timestamp"].astype(str).str.endswith("12:30:00Z")]
    tip.to_parquet(paths["log"], index=False)
    mask = life["timestamp"] == pd.Timestamp("2026-07-19T12:15:00Z")
    life.loc[mask, "context_origin_price"] = 222.0
    life.loc[mask, "context_entered_at"] = pd.Timestamp("2026-07-19T12:15:00Z")
    life.loc[mask, "context_episode_id"] = 9
    life.loc[mask, "context_direction"] = "LONG_CONTEXT"
    life.loc[mask, "context_distance_bps"] = 0.0
    life.loc[mask, "context_favorable_distance_bps"] = 0.0
    life.loc[mask, "context_adverse_distance_bps"] = 0.0
    # Tip bar gets a different origin that must not leak into backfill of 12:15.
    tip_mask = life["timestamp"] == pd.Timestamp("2026-07-19T12:30:00Z")
    life.loc[tip_mask, "context_origin_price"] = 333.0
    life.to_parquet(paths["lifecycle"], index=False)
    result = mod.backfill_missing_decisions(
        log_path=paths["log"],
        live_path=paths["live"],
        auction_path=paths["auction"],
        cognitive_path=paths["cognitive"],
        final_path=paths["final"],
        lifecycle_path=paths["lifecycle"],
        runtime_log_path=paths["runtime"],
        from_timestamp="2026-07-19T12:15:00Z",
        to_timestamp="2026-07-19T12:15:00Z",
        default_from_existing_min=False,
    )
    assert result["rows_added"] == 1
    row = pd.read_parquet(paths["log"])
    row = row[row["candle_timestamp"].astype(str) == "2026-07-19T12:15:00Z"].iloc[0]
    assert float(row["context_origin_price"]) == 222.0
    assert int(row["context_episode_id"]) == 9


def test_existing_decision_rows_not_rewritten_when_origin_added(tmp_path: Path):
    paths = _sources(tmp_path)
    _run(paths)
    before = pd.read_parquet(paths["log"]).copy()
    life = pd.read_parquet(paths["lifecycle"])
    life["context_origin_price"] = 999.0
    life.to_parquet(paths["lifecycle"], index=False)
    again = _run(paths)
    assert again["status"] in {"SKIPPED_DUPLICATE", "SKIPPED_NOT_NEWER"}
    after = pd.read_parquet(paths["log"])
    assert list(before["decision_id"]) == list(after["decision_id"])
    assert list(before["decision_payload_hash"]) == list(after["decision_payload_hash"])


def test_m15_closed_bar_lifecycle_ignores_h4_row_at_same_timestamp():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-07-01T12:00:00Z", "2026-07-01T12:00:00Z", "2026-07-01T12:15:00Z"],
                utc=True,
            ),
            "timeframe": ["M15", "H4", "M15"],
            "active_market_context": ["LONG_CONTEXT", "SHORT_CONTEXT", "LONG_CONTEXT"],
        }
    )
    out = mod.m15_closed_bar_lifecycle(frame)
    assert list(out["active_market_context"]) == ["LONG_CONTEXT", "LONG_CONTEXT"]
    assert int(pd.to_datetime(out["timestamp"], utc=True).duplicated().sum()) == 0
