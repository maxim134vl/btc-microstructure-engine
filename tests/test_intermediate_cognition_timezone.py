from __future__ import annotations

import pandas as pd
import pytest

import intermediate_cognition_engine_v1 as engine


def _candles(index: pd.DatetimeIndex) -> pd.DataFrame:
    count = len(index)
    return pd.DataFrame(
        {
            "timestamp": index,
            "open": [100.0] * count,
            "high": [101.0] * count,
            "low": [99.0] * count,
            "close": [100.0] * count,
            "delta": [1000.0 if i % 2 == 0 else -1000.0 for i in range(count)],
        }
    )


def test_utc_aware_series_and_microsecond_dtype_remain_utc():
    source = pd.Series(pd.date_range("2026-08-08T10:00:00Z", periods=3, freq="15min"))
    source = source.astype("datetime64[us, UTC]")
    result = engine._utc_timestamp_series(source, source_name="aware_fixture")
    assert str(result.dtype) == "datetime64[us, UTC]"
    assert result.iloc[0] == pd.Timestamp("2026-08-08T10:00:00Z")


def test_plus_three_timestamp_normalizes_to_equivalent_utc_instant():
    plus_three = pd.Series(pd.to_datetime(["2026-08-08T13:00:00+03:00"]))
    result = engine._utc_timestamp_series(plus_three, source_name="aware_plus_three")
    assert result.iloc[0] == pd.Timestamp("2026-08-08T10:00:00Z")


def test_naive_timestamp_requires_explicit_source_contract():
    naive = pd.Series(pd.to_datetime(["2026-08-08 10:00:00"]))
    with pytest.raises(ValueError, match="NAIVE_TIMESTAMP_SOURCE_CONTRACT_REQUIRED"):
        engine._utc_timestamp_series(naive, source_name="unknown_fixture")

    result = engine._utc_timestamp_series(
        naive,
        source_name=engine.CANDLE_SOURCE,
        naive_timestamps_are_utc=True,
    )
    assert result.iloc[0] == pd.Timestamp("2026-08-08T10:00:00Z")


def test_anchor_comparison_equal_before_and_after_boundaries():
    stage2 = engine._prep(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-08-08T10:00:00Z", "2026-08-08T11:00:00Z"]
                ),
                "synthesis_state": ["FIRST", "SECOND"],
                "trigger_event": ["A", "B"],
                "persistence": [1, 1],
            }
        ),
        source_name=engine.RUNTIME_COGNITION_SOURCE,
    )
    assert engine._stage2_anchor(stage2, pd.Timestamp("2026-08-08T09:59:59Z")) is None
    assert engine._stage2_anchor(stage2, pd.Timestamp("2026-08-08T10:00:00Z"))["anchor_stage2_state"] == "FIRST"
    assert engine._stage2_anchor(stage2, pd.Timestamp("2026-08-08T10:59:59Z"))["anchor_stage2_state"] == "FIRST"
    assert engine._stage2_anchor(stage2, pd.Timestamp("2026-08-08T11:00:00Z"))["anchor_stage2_state"] == "SECOND"


def test_equivalent_timezones_do_not_change_cognition_classification():
    utc_index = pd.date_range("2026-08-08T10:00:00Z", periods=10, freq="15min")
    plus_three_index = utc_index.tz_convert("+03:00")
    utc_candidates = engine.detect_candidates(_candles(utc_index), thresholds=engine.LEGACY_THRESHOLDS)
    plus_three_candidates = engine.detect_candidates(
        _candles(plus_three_index),
        thresholds=engine.LEGACY_THRESHOLDS,
    )
    assert utc_candidates
    assert [row["intermediate_state"] for row in utc_candidates] == [
        row["intermediate_state"] for row in plus_three_candidates
    ]
    assert [row["severity"] for row in utc_candidates] == [
        row["severity"] for row in plus_three_candidates
    ]
    assert [row["timestamp"] for row in utc_candidates] == [
        row["timestamp"] for row in plus_three_candidates
    ]


def test_current_like_engine_run_completes_without_trading_artifact_writes(monkeypatch):
    candles = _candles(pd.date_range("2026-08-08 10:00:00", periods=10, freq="15min"))
    volume = pd.DataFrame(
        {
            "timestamp": candles["timestamp"],
            "volume_class": ["normal"] * len(candles),
        }
    )
    runtime = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-08-08T10:00:00Z"]),
            "synthesis_state": ["AUCTION_BALANCED"],
            "trigger_event": ["NONE"],
            "persistence": [1],
        }
    )
    frames = {
        engine.CANDLE_SOURCE: candles,
        engine.VOLUME_CLASS_SOURCE: volume,
        engine.RUNTIME_COGNITION_SOURCE: runtime,
        engine.MEMORY_PATH: pd.DataFrame(),
    }
    requested: list[str] = []
    writes: list[str] = []

    def read(path: str) -> pd.DataFrame:
        requested.append(path)
        return frames[path].copy()

    monkeypatch.setattr(engine, "safe_read_parquet", read)
    monkeypatch.setattr(
        "parquet_utils.atomic_parquet_write",
        lambda _frame, path, *args, **kwargs: writes.append(str(path)),
    )
    engine.run()

    assert set(requested) <= set(frames)
    assert writes == [engine.MEMORY_PATH]
    assert not any("trading" in path or "execution" in path for path in writes)
