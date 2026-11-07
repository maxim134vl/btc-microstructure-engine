#!/usr/bin/env python3
"""Canonical multi-timeframe availability helpers (Patch 3.1 / 3.2).

Operational availability only. Does not invent market semantics
(NEUTRAL/BALANCE/OBSERVE/NO_STATE) when events are sparse.
Shared by research scripts and the production runtime writer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
CONTRACT_PATH = ROOT / "config" / "multi_timeframe_availability_contract.json"
CANDLE_PATH = ROOT / "data" / "cognition" / "candle_structure_memory.parquet"

TIMEFRAMES = ("M15", "M30", "H1", "H4", "D1")
LIVE_SUPPORTED_TIMEFRAMES = ("M15", "M30", "H1", "H4")
UNSUPPORTED_LIVE_TIMEFRAMES = ("D1",)
RUNTIME_EVALUATION_SET = ("M15", "M30", "H1", "H4", "D1")

PANDAS_RULE = {
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1D",
}

DURATION_S = {
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

AVAILABILITY_STATUSES = (
    "FRESH_EVENT",
    "AVAILABLE_LAST_CONFIRMED",
    "WAITING_FOR_BAR_CLOSE",
    "NO_EVENT_STATE_UNCHANGED",
    "UPSTREAM_STALE",
    "WRITER_STALE",
    "WRITER_DEAD",
    "DATASET_MISSING",
    "SCHEMA_INVALID",
    "TIMEFRAME_DEPRECATED",
    "INSUFFICIENT_HISTORY",
    "TIMEFRAME_NOT_LIVE",
    "UNKNOWN",
)

SCHEMA_VERSION = "mtf_availability_read_model_v1"


class MTFAvailabilityError(RuntimeError):
    """Fail-closed availability / as-of error."""


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def to_utc_ts(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def bar_close_from_open(bar_open: Any, timeframe: str) -> pd.Timestamp:
    open_ts = to_utc_ts(bar_open)
    if open_ts is None:
        raise MTFAvailabilityError(f"invalid bar_open for {timeframe}: {bar_open}")
    if timeframe not in DURATION_S:
        raise MTFAvailabilityError(f"unknown timeframe: {timeframe}")
    return open_ts + pd.Timedelta(seconds=DURATION_S[timeframe])


def is_bar_completed(*, bar_open: Any, timeframe: str, evaluation_timestamp: Any) -> bool:
    eval_ts = to_utc_ts(evaluation_timestamp)
    if eval_ts is None:
        raise MTFAvailabilityError(f"invalid evaluation_timestamp: {evaluation_timestamp}")
    close_ts = bar_close_from_open(bar_open, timeframe)
    return close_ts <= eval_ts


def allow_provisional_unclosed_bar(*, evaluation_mode: str | None) -> bool:
    """Closed-bar pipeline must keep rejecting unclosed bars.

    Only the explicit LIVE1A intrabar path may evaluate provisional open bars.
    """
    return str(evaluation_mode or "").upper() == "PROVISIONAL_INTRABAR"


def load_m15_candles(path: Path = CANDLE_PATH) -> pd.DataFrame:
    if not path.exists():
        raise MTFAvailabilityError(f"DATASET_MISSING: {path}")
    frame = pd.read_parquet(path)
    if "timestamp" not in frame.columns:
        raise MTFAvailabilityError("SCHEMA_INVALID: missing timestamp")
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    if out["timestamp"].duplicated().any():
        raise MTFAvailabilityError("duplicate_source_keys on M15 timestamp")
    return out


def safe_m15_evaluation_timestamp(m15: pd.DataFrame | None = None, *, path: Path = CANDLE_PATH) -> pd.Timestamp:
    """Latest safe completed M15 evaluation point (= latest M15 open tip + 15m)."""
    frame = m15 if m15 is not None else load_m15_candles(path)
    if frame is None or len(frame) == 0:
        raise MTFAvailabilityError("INSUFFICIENT_HISTORY: empty M15")
    tip_open = to_utc_ts(frame["timestamp"].max())
    if tip_open is None:
        raise MTFAvailabilityError("SCHEMA_INVALID: invalid M15 tip")
    return tip_open + pd.Timedelta(seconds=DURATION_S["M15"])


def build_completed_bars(
    m15: pd.DataFrame,
    timeframe: str,
    *,
    evaluation_timestamp: Any | None = None,
) -> pd.DataFrame:
    """Build HTF/M15 bars labeled by BAR_OPEN; keep only bars closed at evaluation."""
    if timeframe not in TIMEFRAMES:
        raise MTFAvailabilityError(f"unknown timeframe: {timeframe}")
    if m15 is None or len(m15) == 0:
        raise MTFAvailabilityError("INSUFFICIENT_HISTORY: empty M15")

    eval_ts = to_utc_ts(evaluation_timestamp) if evaluation_timestamp is not None else None
    base = m15.copy()
    base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True, errors="coerce")
    base = base.dropna(subset=["timestamp"]).sort_values("timestamp")

    if timeframe == "M15":
        keep_cols = [c for c in ("open", "high", "low", "close", "volume", "delta") if c in base.columns]
        bars = base[["timestamp", *keep_cols]].drop_duplicates(subset=["timestamp"]).copy()
    else:
        need = [c for c in ("open", "high", "low", "close", "volume", "delta") if c in base.columns]
        if not {"open", "high", "low", "close"}.issubset(set(need)):
            raise MTFAvailabilityError("SCHEMA_INVALID: OHLC required for HTF aggregate")
        indexed = base.set_index("timestamp")
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }
        if "volume" in need:
            agg["volume"] = "sum"
        if "delta" in need:
            agg["delta"] = "sum"
        bars = indexed.resample(PANDAS_RULE[timeframe]).agg(agg).dropna(subset=["open", "close"]).reset_index()

    bars["bar_open"] = pd.to_datetime(bars["timestamp"], utc=True)
    bars["bar_close"] = bars["bar_open"] + pd.Timedelta(seconds=DURATION_S[timeframe])
    bars["timeframe"] = timeframe
    if eval_ts is not None:
        bars = bars.loc[bars["bar_close"] <= eval_ts].copy()
    return bars.reset_index(drop=True)


def _state_column(frame: pd.DataFrame) -> str | None:
    for col in (
        "auction_state",
        "state",
        "cognitive_market_state",
        "synthesis_state",
        "primary_auction_episode",
        "candle_type",
    ):
        if col in frame.columns:
            return col
    return None


def attach_climax_states(bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Optionally enrich bars with climax auction_state; fail soft to bar geometry only."""
    if bars is None or len(bars) == 0:
        return bars
    try:
        from auction_climax_engine_v1 import process_auction_climax
    except Exception:
        out = bars.copy()
        out["state_asof"] = out.get("candle_type")
        out["state_source"] = "bar_geometry_fallback"
        return out

    dataset = bars.copy()
    try:
        result = process_auction_climax(dataset=dataset, timeframe=timeframe)
        states = result.get("auction_states")
        if states is None or len(states) == 0:
            out = bars.copy()
            out["state_asof"] = None
            out["state_source"] = "climax_empty"
            return out
        state_df = states.copy()
        state_df["timestamp"] = pd.to_datetime(state_df["timestamp"], utc=True, errors="coerce")
        col = _state_column(state_df)
        if col is None:
            out = bars.copy()
            out["state_asof"] = None
            out["state_source"] = "climax_no_state_col"
            return out
        merged = bars.merge(
            state_df[["timestamp", col]].rename(columns={col: "state_asof"}),
            on="timestamp",
            how="left",
        )
        merged["state_source"] = "auction_climax"
        return merged
    except Exception:
        out = bars.copy()
        out["state_asof"] = out["candle_type"] if "candle_type" in out.columns else None
        out["state_source"] = "climax_error_fallback"
        return out


@dataclass
class TimeframeStateAsof:
    timeframe: str
    evaluation_timestamp: str
    state_asof: Any
    source_state_timestamp: str | None
    source_event_timestamp: str | None
    source_bar_close: str | None
    source_bar_open: str | None
    is_new_event: bool
    availability_status: str
    availability_reason: str
    age_seconds: float | None
    age_bars: float | None
    writer_state: str
    source_dataset: str
    source_row_key: str | None
    state_source: str | None = None
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(ts: Any) -> str | None:
    parsed = to_utc_ts(ts)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def classify_availability(
    *,
    timeframe: str,
    evaluation_timestamp: Any,
    last_completed: pd.Series | None,
    previous_completed: pd.Series | None,
    m15_tip: Any,
    writer_state: str,
    contract: dict[str, Any] | None = None,
) -> tuple[str, str, bool]:
    """Return (status, reason, is_new_event)."""
    contract = contract or load_contract()
    tf_cfg = contract["timeframes"][timeframe]
    eval_ts = to_utc_ts(evaluation_timestamp)
    assert eval_ts is not None

    if writer_state == "DEAD":
        return "WRITER_DEAD", "writer_dead", False
    if writer_state == "DEPRECATED":
        return "TIMEFRAME_DEPRECATED", "writer_deprecated", False
    if writer_state in {"NOT_IMPLEMENTED", "NOT_IMPLEMENTED_LIVE"} and timeframe == "D1":
        # Research path may still derive D1 bars; runtime path short-circuits earlier.
        pass

    if last_completed is None or (isinstance(last_completed, float) and pd.isna(last_completed)):
        open_floor = eval_ts.floor(PANDAS_RULE[timeframe])
        m15 = to_utc_ts(m15_tip)
        if m15 is not None and m15 + pd.Timedelta(seconds=900) > open_floor:
            return "WAITING_FOR_BAR_CLOSE", "current_period_not_closed", False
        return "INSUFFICIENT_HISTORY", "no_completed_bar", False

    bar_open = to_utc_ts(last_completed["bar_open"])
    bar_close = to_utc_ts(last_completed["bar_close"])
    assert bar_open is not None and bar_close is not None
    if bar_close > eval_ts:
        return "WAITING_FOR_BAR_CLOSE", "selected_unclosed_bar_rejected", False

    is_new = False
    if previous_completed is not None:
        prev_close = to_utc_ts(previous_completed["bar_close"])
        is_new = prev_close is not None and bar_close > prev_close
    else:
        is_new = True

    state_now = last_completed.get("state_asof")
    state_prev = None
    if previous_completed is not None and "state_asof" in previous_completed.index:
        state_prev = previous_completed.get("state_asof")

    age_s = (eval_ts - bar_close).total_seconds()
    if age_s > float(tf_cfg["max_inherited_age_seconds"]):
        return "UPSTREAM_STALE", "inherited_state_exceeds_max_age", False
    if writer_state == "STALE":
        return "WRITER_STALE", "writer_stale_but_last_confirmed_present", False

    if not is_new:
        return "AVAILABLE_LAST_CONFIRMED", "last_completed_bar_available", False

    if (
        state_now is not None
        and state_prev is not None
        and str(state_now) == str(state_prev)
    ):
        return "NO_EVENT_STATE_UNCHANGED", "new_bar_same_state_label", True
    return "FRESH_EVENT", "completed_bar_closed_at_or_before_evaluation", True


def d1_runtime_declaration(evaluation_timestamp: Any) -> TimeframeStateAsof:
    """Operational declaration only — never promotes research/dashboard D1 state."""
    eval_ts = to_utc_ts(evaluation_timestamp)
    if eval_ts is None:
        raise MTFAvailabilityError(f"invalid evaluation_timestamp: {evaluation_timestamp}")
    return TimeframeStateAsof(
        timeframe="D1",
        evaluation_timestamp=_iso(eval_ts) or "",
        state_asof=None,
        source_state_timestamp=None,
        source_event_timestamp=None,
        source_bar_close=None,
        source_bar_open=None,
        is_new_event=False,
        availability_status="TIMEFRAME_NOT_LIVE",
        availability_reason="NO_LIVE_STAGE2_WRITER",
        age_seconds=None,
        age_bars=None,
        writer_state="NOT_IMPLEMENTED_LIVE",
        source_dataset="NONE",
        source_row_key=None,
        state_source=None,
        schema_version=SCHEMA_VERSION,
    )


def get_timeframe_state_asof(
    timeframe: str,
    evaluation_timestamp: Any,
    *,
    source_dataset: Path | str | None = None,
    m15_frame: pd.DataFrame | None = None,
    writer_state: str = "RUNNING",
    previous_evaluation_timestamp: Any | None = None,
    contract: dict[str, Any] | None = None,
    enrich_climax: bool = True,
    live_runtime: bool = False,
) -> TimeframeStateAsof:
    """Point-in-time timeframe availability + last confirmed state."""
    contract = contract or load_contract()
    if timeframe not in contract["timeframes"]:
        raise MTFAvailabilityError(f"unknown timeframe: {timeframe}")

    eval_ts = to_utc_ts(evaluation_timestamp)
    if eval_ts is None:
        raise MTFAvailabilityError(f"invalid evaluation_timestamp: {evaluation_timestamp}")

    if live_runtime and timeframe == "D1":
        return d1_runtime_declaration(eval_ts)

    src = Path(source_dataset) if source_dataset else CANDLE_PATH
    if not src.exists() and m15_frame is None:
        return TimeframeStateAsof(
            timeframe=timeframe,
            evaluation_timestamp=_iso(eval_ts) or "",
            state_asof=None,
            source_state_timestamp=None,
            source_event_timestamp=None,
            source_bar_close=None,
            source_bar_open=None,
            is_new_event=False,
            availability_status="DATASET_MISSING",
            availability_reason=f"missing {src}",
            age_seconds=None,
            age_bars=None,
            writer_state=writer_state,
            source_dataset=str(src.relative_to(ROOT)) if src.is_absolute() and ROOT in src.parents else str(src),
            source_row_key=None,
        )

    m15 = m15_frame if m15_frame is not None else load_m15_candles(src)
    m15_tip = m15["timestamp"].max() if len(m15) else None

    try:
        bars = build_completed_bars(m15, timeframe, evaluation_timestamp=eval_ts)
    except MTFAvailabilityError as exc:
        status = "SCHEMA_INVALID" if "SCHEMA" in str(exc) else "UNKNOWN"
        if "duplicate_source_keys" in str(exc):
            status = "SCHEMA_INVALID"
        return TimeframeStateAsof(
            timeframe=timeframe,
            evaluation_timestamp=_iso(eval_ts) or "",
            state_asof=None,
            source_state_timestamp=None,
            source_event_timestamp=None,
            source_bar_close=None,
            source_bar_open=None,
            is_new_event=False,
            availability_status=status,
            availability_reason=str(exc),
            age_seconds=None,
            age_bars=None,
            writer_state=writer_state,
            source_dataset=str(src),
            source_row_key=None,
        )

    if enrich_climax and len(bars):
        bars = attach_climax_states(bars, timeframe)

    last = bars.iloc[-1] if len(bars) else None
    prev = None
    if previous_evaluation_timestamp is not None:
        prev_bars = build_completed_bars(m15, timeframe, evaluation_timestamp=previous_evaluation_timestamp)
        if enrich_climax and len(prev_bars):
            prev_bars = attach_climax_states(prev_bars, timeframe)
        if len(prev_bars):
            prev = prev_bars.iloc[-1]
    elif len(bars) >= 2:
        prev = bars.iloc[-2]

    status, reason, is_new = classify_availability(
        timeframe=timeframe,
        evaluation_timestamp=eval_ts,
        last_completed=last,
        previous_completed=prev,
        m15_tip=m15_tip,
        writer_state=writer_state,
        contract=contract,
    )

    if last is None:
        return TimeframeStateAsof(
            timeframe=timeframe,
            evaluation_timestamp=_iso(eval_ts) or "",
            state_asof=None,
            source_state_timestamp=None,
            source_event_timestamp=None,
            source_bar_close=None,
            source_bar_open=None,
            is_new_event=False,
            availability_status=status,
            availability_reason=reason,
            age_seconds=None,
            age_bars=None,
            writer_state=writer_state,
            source_dataset=str(src.relative_to(ROOT)) if src.is_absolute() and str(src).startswith(str(ROOT)) else str(src),
            source_row_key=None,
            state_source=None,
        )

    bar_close = to_utc_ts(last["bar_close"])
    bar_open = to_utc_ts(last["bar_open"])
    age_s = (eval_ts - bar_close).total_seconds() if bar_close is not None else None
    age_bars = (age_s / DURATION_S[timeframe]) if age_s is not None else None
    state_val = last.get("state_asof")

    return TimeframeStateAsof(
        timeframe=timeframe,
        evaluation_timestamp=_iso(eval_ts) or "",
        state_asof=None if pd.isna(state_val) else state_val,
        source_state_timestamp=_iso(bar_open),
        source_event_timestamp=_iso(bar_open),
        source_bar_close=_iso(bar_close),
        source_bar_open=_iso(bar_open),
        is_new_event=bool(is_new),
        availability_status=status,
        availability_reason=reason,
        age_seconds=None if age_s is None else round(float(age_s), 3),
        age_bars=None if age_bars is None else round(float(age_bars), 6),
        writer_state=writer_state,
        source_dataset="data/cognition/candle_structure_memory.parquet",
        source_row_key=_iso(bar_open),
        state_source=None if "state_source" not in last.index else last.get("state_source"),
    )


def assert_complete_evaluation_set(rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    frame = pd.DataFrame(rows) if not isinstance(rows, pd.DataFrame) else rows
    if frame.duplicated(subset=["evaluation_timestamp", "timeframe"]).any():
        raise MTFAvailabilityError("duplicate_evaluation_timeframe_keys")
    if len(frame) != len(RUNTIME_EVALUATION_SET):
        raise MTFAvailabilityError(
            f"incomplete evaluation set: expected {len(RUNTIME_EVALUATION_SET)} rows, got {len(frame)}"
        )
    tfs = set(frame["timeframe"].astype(str))
    if tfs != set(RUNTIME_EVALUATION_SET):
        raise MTFAvailabilityError(f"incomplete evaluation set timeframes: {sorted(tfs)}")
    evals = frame["evaluation_timestamp"].astype(str).unique()
    if len(evals) != 1:
        raise MTFAvailabilityError(f"evaluation set mixed timestamps: {evals}")


def build_runtime_evaluation_rows(
    evaluation_timestamp: Any,
    *,
    m15_frame: pd.DataFrame | None = None,
    previous_evaluation_timestamp: Any | None = None,
    contract: dict[str, Any] | None = None,
    enrich_climax: bool = False,
    generated_at: str | None = None,
) -> list[dict[str, Any]]:
    """Build the atomic five-row runtime set for one safe evaluation timestamp."""
    contract = contract or load_contract()
    eval_ts = to_utc_ts(evaluation_timestamp)
    if eval_ts is None:
        raise MTFAvailabilityError(f"invalid evaluation_timestamp: {evaluation_timestamp}")
    m15 = m15_frame if m15_frame is not None else load_m15_candles()
    writer_map = {
        "M15": "RUNNING",
        "M30": "EVENT_DRIVEN",
        "H1": "EVENT_DRIVEN",
        "H4": "EVENT_DRIVEN",
    }
    gen = generated_at or pd.Timestamp.now(tz="UTC").isoformat().replace("+00:00", "Z")
    rows: list[dict[str, Any]] = []
    for tf in LIVE_SUPPORTED_TIMEFRAMES:
        row = get_timeframe_state_asof(
            tf,
            eval_ts,
            m15_frame=m15,
            writer_state=writer_map[tf],
            previous_evaluation_timestamp=previous_evaluation_timestamp,
            contract=contract,
            enrich_climax=enrich_climax,
            live_runtime=True,
        ).as_dict()
        row["generated_at"] = gen
        rows.append(row)
    d1 = d1_runtime_declaration(eval_ts).as_dict()
    d1["generated_at"] = gen
    rows.append(d1)
    assert_complete_evaluation_set(rows)
    # Fail-closed PIT gates
    for row in rows:
        if row["timeframe"] == "D1":
            continue
        close = to_utc_ts(row.get("source_bar_close"))
        if close is not None and close > eval_ts:
            raise MTFAvailabilityError(
                f"future/unclosed join rejected for {row['timeframe']}: {close} > {eval_ts}"
            )
    return rows


def count_pit_violations(frame: pd.DataFrame) -> dict[str, int]:
    if frame is None or len(frame) == 0:
        return {
            "future_joins": 0,
            "unclosed_bar_joins": 0,
            "duplicate_source_keys": 0,
            "duplicate_evaluation_timeframe_keys": 0,
        }
    work = frame.copy()
    work["evaluation_timestamp"] = pd.to_datetime(work["evaluation_timestamp"], utc=True, errors="coerce")
    work["source_bar_close"] = pd.to_datetime(work.get("source_bar_close"), utc=True, errors="coerce")
    live = work[work["timeframe"].isin(LIVE_SUPPORTED_TIMEFRAMES)]
    future = int((live["source_bar_close"] > live["evaluation_timestamp"]).fillna(False).sum())
    dup_eval = int(work.duplicated(subset=["evaluation_timestamp", "timeframe"]).sum())
    dup_src = 0
    if "source_row_key" in work.columns:
        keyed = work.dropna(subset=["source_row_key"])
        if len(keyed):
            dup_src = int(
                keyed.duplicated(subset=["evaluation_timestamp", "timeframe", "source_row_key"]).sum()
            )
    return {
        "future_joins": future,
        "unclosed_bar_joins": future,
        "duplicate_source_keys": dup_src,
        "duplicate_evaluation_timeframe_keys": dup_eval,
    }
