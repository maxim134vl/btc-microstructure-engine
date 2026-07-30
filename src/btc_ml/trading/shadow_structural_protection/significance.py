"""SHADOW_VOLUME_SIGNIFICANCE_V1 — per-timeframe causal volume classification."""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import SIGNIFICANT_CLASSES
from .classification import CANONICAL_VOLUME_CLASSES, load_volume_classification
from .timeutil import iso, parse_ts

CLASSIFICATION_MODE = "SHADOW_RESEARCH"
CLASSIFICATION_MODEL = "SHADOW_VOLUME_SIGNIFICANCE_V1"

SHADOW_CLASSES = ("CLIMAX", "STOPPING", "HIGH_AVERAGE_VOLUME", "NORMAL", "LOW_SMALL")

SIGNIFICANCE_PARAMS = {
    "rolling_window_bars": 20,
    "min_history_bars": 5,
    "volume_climax_pct": 95.0,
    "volume_stopping_pct": 85.0,
    "volume_high_avg_pct": 70.0,
    "volume_low_pct": 30.0,
    "stopping_requires_wick_frac": 0.45,
    "stopping_requires_close_loc_long": 0.55,
    "stopping_requires_close_loc_short": 0.45,
    "climax_requires_range_pct": 70.0,
    "normalization": "rolling_percentile_and_mad",
}


def _mad(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    med = float(series.median())
    return float((series - med).abs().median())


def classify_bars_shadow(
    bars: list[dict[str, Any]],
    *,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Classify each closed bar using only prior+current same-TF causal history."""
    cfg = {**SIGNIFICANCE_PARAMS, **(params or {})}
    window = int(cfg["rolling_window_bars"])
    min_hist = int(cfg["min_history_bars"])
    out: list[dict[str, Any]] = []
    hist_vol: list[float] = []
    hist_range: list[float] = []

    for bar in bars:
        if bar.get("incomplete"):
            row = {
                **bar,
                "shadow_volume_class": None,
                "classification_mode": CLASSIFICATION_MODE,
                "classification_model": CLASSIFICATION_MODEL,
                "classification_status": "INCOMPLETE_BAR",
                "significant": False,
            }
            out.append(row)
            continue

        vol = float(bar["base_volume"])
        rng = float(bar["range"])
        # Rolling history excludes future; includes current for percentile of "current vs recent".
        hist_vol.append(vol)
        hist_range.append(rng)
        vol_win = hist_vol[-window:]
        range_win = hist_range[-window:]
        if len(vol_win) < min_hist:
            row = {
                **bar,
                "shadow_volume_class": "NORMAL",
                "classification_mode": CLASSIFICATION_MODE,
                "classification_model": CLASSIFICATION_MODEL,
                "classification_status": "INSUFFICIENT_HISTORY",
                "significant": False,
                "volume_percentile": None,
                "range_percentile": None,
                "volume_mad": None,
            }
            out.append(row)
            continue

        vs = pd.Series(vol_win, dtype=float)
        rs = pd.Series(range_win, dtype=float)
        vol_pct = float(vs.rank(pct=True).iloc[-1] * 100.0)
        range_pct = float(rs.rank(pct=True).iloc[-1] * 100.0)
        vol_mad = _mad(vs.iloc[:-1]) if len(vs) > 1 else 0.0

        close_loc = float(bar.get("close_location") or 0.5)
        upper_wick = float(bar.get("upper_wick") or 0.0)
        lower_wick = float(bar.get("lower_wick") or 0.0)
        wick_frac = 0.0 if rng <= 0 else max(upper_wick, lower_wick) / rng

        label = "NORMAL"
        if vol_pct >= float(cfg["volume_climax_pct"]) and range_pct >= float(cfg["climax_requires_range_pct"]):
            label = "CLIMAX"
        elif vol_pct >= float(cfg["volume_stopping_pct"]) and wick_frac >= float(cfg["stopping_requires_wick_frac"]):
            # Stopping: high effort, rejection wick, close away from extreme
            if lower_wick >= upper_wick and close_loc >= float(cfg["stopping_requires_close_loc_long"]):
                label = "STOPPING"
            elif upper_wick > lower_wick and close_loc <= float(cfg["stopping_requires_close_loc_short"]):
                label = "STOPPING"
            elif vol_pct >= float(cfg["volume_high_avg_pct"]):
                label = "HIGH_AVERAGE_VOLUME"
        elif vol_pct >= float(cfg["volume_high_avg_pct"]):
            label = "HIGH_AVERAGE_VOLUME"
        elif vol_pct <= float(cfg["volume_low_pct"]):
            label = "LOW_SMALL"

        out.append(
            {
                **bar,
                "shadow_volume_class": label,
                "classification_mode": CLASSIFICATION_MODE,
                "classification_model": CLASSIFICATION_MODEL,
                "classification_status": "VALID",
                "significant": label in SIGNIFICANT_CLASSES,
                "volume_percentile": vol_pct,
                "range_percentile": range_pct,
                "volume_mad": vol_mad,
                "params_fingerprint_fields": {
                    "rolling_window_bars": window,
                    "volume_climax_pct": cfg["volume_climax_pct"],
                    "volume_stopping_pct": cfg["volume_stopping_pct"],
                    "volume_high_avg_pct": cfg["volume_high_avg_pct"],
                    "volume_low_pct": cfg["volume_low_pct"],
                },
            }
        )
    return out


def m15_parity_report(
    *,
    repo,
    shadow_bars: list[dict[str, Any]],
    decision_ts=None,
) -> dict[str, Any]:
    """Compare SHADOW_VOLUME_SIGNIFICANCE_V1 vs canonical M15 labels (research only)."""
    vc = load_volume_classification(repo)
    confusion: dict[str, dict[str, int]] = {}
    agreement = 0
    disagreement = 0
    compared = 0
    class_hits = {c: {"agree": 0, "disagree": 0, "canonical_count": 0} for c in SHADOW_CLASSES}

    for bar in shadow_bars:
        if str(bar.get("timeframe") or "").upper() != "M15":
            continue
        if bar.get("incomplete"):
            continue
        open_ts = parse_ts(bar.get("open_timestamp"))
        if open_ts is None or vc is None or vc.empty:
            continue
        if decision_ts is not None and pd.Timestamp(open_ts) > pd.Timestamp(decision_ts):
            continue
        rows = vc[vc["_ts"] == pd.Timestamp(open_ts)]
        if rows.empty:
            continue
        raw = str(rows.iloc[-1].get("volume_class") or "").lower()
        canon = CANONICAL_VOLUME_CLASSES.get(raw)
        if not canon:
            # map high_average etc already; unknown stay as upper
            canon = raw.upper() if raw else None
        if not canon:
            continue
        shadow = str(bar.get("shadow_volume_class") or "NORMAL")
        compared += 1
        confusion.setdefault(canon, {})
        confusion[canon][shadow] = confusion[canon].get(shadow, 0) + 1
        if canon == shadow:
            agreement += 1
            if canon in class_hits:
                class_hits[canon]["agree"] += 1
                class_hits[canon]["canonical_count"] += 1
        else:
            disagreement += 1
            if canon in class_hits:
                class_hits[canon]["disagree"] += 1
                class_hits[canon]["canonical_count"] += 1

    rate = (agreement / compared) if compared else None
    # Systemic contradiction: among significant canonical labels, agreement < 20% with n>=10
    blocked = False
    for key in ("CLIMAX", "STOPPING", "HIGH_AVERAGE_VOLUME", "LOW_SMALL"):
        c = class_hits.get(key) or {}
        n = int(c.get("canonical_count") or 0)
        if n >= 10 and int(c.get("agree") or 0) / n < 0.2:
            blocked = True

    return {
        "classification_mode": CLASSIFICATION_MODE,
        "classification_model": CLASSIFICATION_MODEL,
        "compared": compared,
        "agreement": agreement,
        "disagreement": disagreement,
        "agreement_rate": rate,
        "confusion": confusion,
        "per_class": class_hits,
        "parity_blocked": blocked,
        "status": "SHADOW_STP2_BLOCKED_CLASSIFICATION_PARITY_FAILURE" if blocked else "SHADOW_RESEARCH_PARITY_OK",
    }


def class_allowed_shadow(volume_class: str | None, policy: str) -> bool:
    if not volume_class:
        return False
    if policy == "CLIMAX_ONLY":
        return volume_class == "CLIMAX"
    if policy == "CLIMAX_OR_STOPPING":
        return volume_class in {"CLIMAX", "STOPPING"}
    if policy == "ALL_CANONICAL_SIGNIFICANT":
        return volume_class in SIGNIFICANT_CLASSES
    return False
