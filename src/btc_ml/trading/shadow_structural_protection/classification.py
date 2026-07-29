"""Causal volume classification and reaction evidence readers."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from . import CANONICAL_VOLUME_CLASSES, SIGNIFICANT_CLASSES, TF_SECONDS
from .timeutil import candle_open, iso

REACTION_STATUSES = (
    "PROVEN",
    "MISSING",
    "NOT_CANONICALLY_AVAILABLE",
    "WRONG_TIMEFRAME",
    "FUTURE_EVIDENCE_REJECTED",
    "AMBIGUOUS",
)


def load_volume_classification(repo: Path) -> pd.DataFrame:
    path = repo / "data" / "cognition" / "volume_classification_memory.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["_ts"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df[df["_ts"].notna()].copy()


def classify_source_candle(
    vc: pd.DataFrame,
    *,
    timeframe: str,
    candle_open_ts: datetime,
    decision_ts: datetime,
) -> dict[str, Any]:
    """Attach canonical volume_class for same-TF candle if causally available.

    Fact: volume_classification_memory is M15-cadence (900s) with no timeframe column.
    Non-M15 timeframes therefore cannot claim same-TF classification from this artifact.
    """
    tf = str(timeframe).upper()
    base = {
        "timeframe": tf,
        "source_candle_open": iso(candle_open_ts),
        "volume_class": None,
        "volume_class_raw": None,
        "classification_timestamp": None,
        "status": "MISSING",
        "source_artifact": "data/cognition/volume_classification_memory.parquet",
    }
    if vc is None or vc.empty:
        base["status"] = "NOT_CANONICALLY_AVAILABLE"
        return base
    if tf != "M15":
        base["status"] = "WRONG_TIMEFRAME"
        base["detail"] = "volume_classification_memory is M15-only (900s bars, no TF column)"
        return base

    rows = vc[vc["_ts"] == pd.Timestamp(candle_open_ts)]
    if rows.empty:
        rows = vc[(vc["_ts"] <= pd.Timestamp(decision_ts)) & (vc["_ts"] == pd.Timestamp(candle_open_ts))]
    if rows.empty:
        base["status"] = "MISSING"
        return base
    row = rows.iloc[-1]
    class_ts = row["_ts"].to_pydatetime()
    if class_ts > decision_ts:
        base["status"] = "FUTURE_EVIDENCE_REJECTED"
        return base
    raw = str(row.get("volume_class") or "").lower()
    mapped = CANONICAL_VOLUME_CLASSES.get(raw)
    base.update(
        {
            "volume_class_raw": raw,
            "volume_class": mapped,
            "classification_timestamp": iso(class_ts),
            "status": "VALID" if mapped else "MISSING",
            "significant": bool(mapped in SIGNIFICANT_CLASSES) if mapped else False,
        }
    )
    return base


def class_allowed(volume_class: str | None, policy: str) -> bool:
    if not volume_class:
        return False
    if policy == "CLIMAX_ONLY":
        return volume_class == "CLIMAX"
    if policy == "CLIMAX_OR_STOPPING":
        return volume_class in {"CLIMAX", "STOPPING"}
    if policy == "ALL_CANONICAL_SIGNIFICANT":
        return volume_class in SIGNIFICANT_CLASSES
    return False


def reaction_evidence(
    repo: Path,
    *,
    timeframe: str,
    candle_open_ts: datetime,
    decision_ts: datetime,
    side: str,
    zone_role: str,  # PROTECTIVE | TARGET
) -> dict[str, Any]:
    """Use volume_response effort_result_state / localized_behavior if causal + same TF."""
    path = repo / "data" / "cognition" / "volume_response_state.parquet"
    out = {
        "status": "NOT_CANONICALLY_AVAILABLE",
        "reaction_direction": None,
        "reaction_source": None,
        "reaction_timestamp": None,
        "effort_result_state": None,
        "localized_behavior": None,
    }
    if not path.exists():
        return out
    df = pd.read_parquet(path)
    if "source_timeframe" not in df.columns or "source_candle_timestamp" not in df.columns:
        return out
    df["_candle"] = pd.to_datetime(df["source_candle_timestamp"], utc=True, errors="coerce")
    df["_ts"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    tf = str(timeframe).upper()

    # Future evidence rejected if any matching candle row is after decision.
    future = df[
        (df["source_timeframe"].astype(str).str.upper() == tf)
        & (df["_candle"] == pd.Timestamp(candle_open_ts))
        & (df["_ts"].notna())
        & (df["_ts"] > pd.Timestamp(decision_ts))
    ]
    rows = df[
        (df["source_timeframe"].astype(str).str.upper() == tf)
        & (df["_candle"] == pd.Timestamp(candle_open_ts))
        & (df["_ts"].notna())
        & (df["_ts"] <= pd.Timestamp(decision_ts))
    ]
    if rows.empty:
        # Wrong TF present for same candle but not this TF?
        other = df[
            (df["_candle"] == pd.Timestamp(candle_open_ts))
            & (df["_ts"].notna())
            & (df["_ts"] <= pd.Timestamp(decision_ts))
            & (df["source_timeframe"].astype(str).str.upper() != tf)
        ]
        if not other.empty:
            out["status"] = "WRONG_TIMEFRAME"
            out["detail"] = "reaction row exists only on different timeframe"
            return out
        if not future.empty:
            out["status"] = "FUTURE_EVIDENCE_REJECTED"
            return out
        out["status"] = "MISSING"
        return out

    row = rows.sort_values("_ts").iloc[-1]
    effort = str(row.get("effort_result_state") or "")
    loc = str(row.get("localized_behavior") or "")
    direction = _infer_reaction_direction(effort=effort, localized=loc, side=side, zone_role=zone_role)
    status = "PROVEN" if direction else "AMBIGUOUS"
    out.update(
        {
            "status": status,
            "reaction_direction": direction,
            "reaction_source": "volume_response_state.effort_result_state+localized_behavior",
            "reaction_timestamp": iso(row["_ts"].to_pydatetime()),
            "effort_result_state": effort or None,
            "localized_behavior": loc or None,
        }
    )
    return out


def reaction_is_proven(react: dict[str, Any] | None) -> bool:
    return bool(react) and str(react.get("status") or "") == "PROVEN"


def _infer_reaction_direction(*, effort: str, localized: str, side: str, zone_role: str) -> str | None:
    """Map existing canonical response labels to UP/DOWN without inventing new classes."""
    e = effort.upper()
    loc = localized.lower()
    want_up = (str(side).upper() == "LONG" and zone_role == "PROTECTIVE") or (
        str(side).upper() == "SHORT" and zone_role == "TARGET"
    )
    want_down = not want_up

    up_hints = ("ABSORPTION_RESPONSE", "BUYER", "SUPPORT", "LOWER_ABSORPTION")
    down_hints = ("DISTRIBUTION", "SELLER", "REJECTION", "UPPER", "SUPPLY")
    hay = f"{e} {loc}".upper()
    up_hit = any(h in hay for h in up_hints)
    down_hit = any(h in hay for h in down_hints)
    if up_hit and down_hit:
        return None
    if up_hit and want_up:
        return "UP"
    if down_hit and want_down:
        return "DOWN"
    # Explicit absorption response is directional only when role wants that side.
    if "ABSORPTION_RESPONSE" in e and not down_hit:
        return "UP" if want_up else None
    return None


def prior_closed_candle_open(decision_ts: datetime, timeframe: str) -> datetime:
    """Last fully closed candle open strictly before decision."""
    tf_s = TF_SECONDS[str(timeframe).upper()]
    open_now = candle_open(decision_ts, tf_s)
    if decision_ts > open_now:
        return open_now - timedelta(seconds=tf_s)
    return open_now - timedelta(seconds=tf_s)
