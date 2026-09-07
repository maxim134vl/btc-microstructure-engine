"""Serve the frozen Hybrid sizing model at LIVE1B entry time.

The multiplier scales the sleeve risk budget already computed by the canonical
engine. It never opens, blocks, or closes a trade. If anything is missing the
multiplier is 1.0 and the engine proceeds unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ARTIFACTS = ROOT / "config" / "trading" / "hybrid_sizing"
LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
TIMEFRAMES = ("M15", "M30", "H1", "H4")
TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}
# Book win rate on the freeze sample; used only to turn predicted p into an EV
# ratio. Clip bounds, not this scale, are what keep size in 0.5–1.5.
BOOK_WIN_RATE = 0.7153


@dataclass(frozen=True)
class SizingDecision:
    multiplier: float
    probability: float | None
    reason: str
    features: dict[str, Any]


def _fallback(reason: str, features: dict[str, Any] | None = None) -> SizingDecision:
    return SizingDecision(1.0, None, f"fallback:{reason}", features or {})


def _ts(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def cross_tf_features(meta: dict[str, Any], *, own_tf: str, own_dir: str) -> dict[str, Any]:
    """Same explosion the training matrix used on manager cross_timeframe_metadata."""
    own_dir_u = str(own_dir or "").upper()
    row: dict[str, Any] = {}
    agree = disagree = neutral = 0
    n_active = 0
    for tf in TIMEFRAMES:
        slot = meta.get(tf) or {}
        direction = slot.get("direction")
        row[f"xtf_{tf}_direction"] = direction
        row[f"xtf_{tf}_availability"] = slot.get("availability")
        row[f"xtf_{tf}_phase"] = slot.get("lifecycle_phase")
        if str(slot.get("lifecycle_phase") or "") == "ACTIVE":
            n_active += 1
        if tf == own_tf:
            continue
        if direction in (None, "NON_DIRECTIONAL"):
            neutral += 1
        elif str(direction).upper() == own_dir_u:
            agree += 1
        else:
            disagree += 1
    row["xtf_agree_n"] = agree
    row["xtf_disagree_n"] = disagree
    row["xtf_neutral_n"] = neutral
    row["xtf_active_n"] = n_active
    row["xtf_net_agreement"] = agree - disagree
    return row


def last_closed_ohlc(
    feed: pd.DataFrame,
    *,
    timeframe: str,
    cutoff: pd.Timestamp,
) -> dict[str, float] | None:
    """OHLC of the last bar of `timeframe` that had fully closed by cutoff.

    Live feed is M15 bars keyed on bar OPEN. A bar opening at T with length L is
    knowable only once T+L <= cutoff — the same rule the training matrix used.
    Higher timeframes are resampled from those M15 bars.
    """
    minutes = TF_MINUTES.get(str(timeframe).upper())
    if minutes is None or feed is None or feed.empty or "timestamp" not in feed.columns:
        return None
    ts = pd.to_datetime(feed["timestamp"], utc=True, errors="coerce")
    frame = feed.loc[ts.notna()].copy()
    frame["_open"] = ts.loc[ts.notna()]
    limit = cutoff - pd.Timedelta(minutes=minutes)
    frame = frame.loc[frame["_open"] <= limit]
    if frame.empty:
        return None
    if minutes == 15:
        row = frame.sort_values("_open").iloc[-1]
        return {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
    rule = f"{minutes}min"
    frame["_bucket"] = frame["_open"].dt.floor(rule)
    grouped = (
        frame.sort_values("_open")
        .groupby("_bucket", sort=True)
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    )
    if grouped.empty:
        return None
    row = grouped.iloc[-1]
    close_px = float(row["close"])
    if close_px <= 0:
        return None
    return {
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": close_px,
    }


def ev_multiplier(
    probability: float,
    *,
    avg_win_r: float,
    avg_loss_r: float,
    clip_lo: float,
    clip_hi: float,
    ev_scale_r: float,
) -> float | None:
    if not (0.0 < probability < 1.0) or ev_scale_r <= 0:
        return None
    expected = probability * avg_win_r + (1.0 - probability) * avg_loss_r
    return float(min(clip_hi, max(clip_lo, expected / ev_scale_r)))


class HybridSizer:
    def __init__(self, artifacts_dir: Path | None = None, *, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else DEFAULT_ARTIFACTS
        self.contract: dict[str, Any] = {}
        self._model: Any = None
        self._feed: pd.DataFrame | None = None
        self._feed_mtime: float | None = None
        self._load_error: str | None = None
        if self.enabled:
            self._load()

    def _load(self) -> None:
        contract_path = self.artifacts_dir / "feature_contract.json"
        model_path = self.artifacts_dir / "sizing_model.cbm"
        try:
            self.contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._load_error = f"contract:{exc}"
            return
        try:
            from catboost import CatBoostClassifier
        except ImportError as exc:
            self._load_error = f"catboost:{exc}"
            return
        try:
            model = CatBoostClassifier()
            model.load_model(str(model_path))
            self._model = model
        except Exception as exc:  # noqa: BLE001 — fail-open is the contract
            self._load_error = f"model:{exc}"

    def _read_feed(self, path: Path) -> pd.DataFrame | None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if self._feed is not None and self._feed_mtime == mtime:
            return self._feed
        try:
            feed = pd.read_parquet(path, columns=["timestamp", "open", "high", "low", "close"])
        except Exception:  # noqa: BLE001
            return None
        self._feed = feed
        self._feed_mtime = mtime
        return feed

    def decide(
        self,
        command: dict[str, Any],
        *,
        side: str,
        timeframe: str,
        stop_loss_bps: float,
        take_profit_bps: float,
        feed_path: Path | None = None,
    ) -> SizingDecision:
        if not self.enabled:
            return _fallback("disabled")
        if self._model is None:
            return _fallback(self._load_error or "no_model")

        feats = self.contract.get("features") or {}
        order: list[str] = list(feats.get("order") or [])
        cats: list[str] = list(feats.get("categorical") or [])
        if not order:
            return _fallback("empty_contract")

        meta = _parse_meta(command.get("cross_timeframe_metadata"))
        if not meta:
            return _fallback("missing_xtf")

        own_tf = str(timeframe or command.get("timeframe") or "").upper()
        own_dir = str(command.get("timeframe_direction") or side or "").upper()
        if own_dir in {"OPEN_LONG", "LONG_CONTEXT"}:
            own_dir = "LONG"
        elif own_dir in {"OPEN_SHORT", "SHORT_CONTEXT"}:
            own_dir = "SHORT"
        row = cross_tf_features(meta, own_tf=own_tf, own_dir=own_dir)

        cutoff = _ts(command.get("source_bar_close") or command.get("evaluation_timestamp"))
        started = _ts(command.get("context_started_at"))
        if cutoff is None:
            return _fallback("missing_cutoff", row)

        row["f_stop_distance_bps"] = float(stop_loss_bps)
        row["f_rr_ratio"] = float(take_profit_bps) / float(stop_loss_bps) if stop_loss_bps else None
        row["f_is_long"] = 1 if str(side).upper() == "LONG" else 0
        try:
            row["f_portfolio_open_risk_usd"] = float(command.get("portfolio_open_risk_usd") or 0.0)
        except (TypeError, ValueError):
            row["f_portfolio_open_risk_usd"] = 0.0
        if started is not None:
            age_min = (cutoff - started).total_seconds() / 60.0
            row["f_context_age_min"] = age_min
            row["f_context_age_bars"] = age_min / TF_MINUTES.get(own_tf, 15)
        else:
            row["f_context_age_min"] = None
            row["f_context_age_bars"] = None
        row["f_hour_utc"] = int(cutoff.hour)
        row["f_dow"] = int(cutoff.dayofweek)

        feed = self._read_feed(Path(feed_path) if feed_path else LIVE_FEED)
        ohlc = last_closed_ohlc(feed, timeframe=own_tf, cutoff=cutoff) if feed is not None else None
        if ohlc is None or ohlc["close"] <= 0:
            return _fallback("missing_ohlc", row)
        close = ohlc["close"]
        row["f_high_vs_close_bps"] = (ohlc["high"] - close) / close * 10_000.0
        row["f_low_vs_close_bps"] = (ohlc["low"] - close) / close * 10_000.0
        row["f_open_vs_close_bps"] = (ohlc["open"] - close) / close * 10_000.0

        values: list[Any] = []
        cat_idx: list[int] = []
        for i, name in enumerate(order):
            value = row.get(name)
            if name in cats:
                text = "NA" if value is None else str(value)
                if text in {"None", "nan", "<NA>", ""}:
                    text = "NA"
                values.append(text)
                cat_idx.append(i)
            else:
                if value is None:
                    return _fallback(f"missing:{name}", row)
                values.append(float(value))

        try:
            from catboost import Pool

            proba = self._model.predict_proba(Pool([values], cat_features=cat_idx))[0][1]
        except Exception as exc:  # noqa: BLE001
            return _fallback(f"predict:{exc}", row)

        sizing = self.contract.get("sizing") or {}
        avg_win = float(sizing.get("avg_win_r") or 0.0)
        avg_loss = float(sizing.get("avg_loss_r") or 0.0)
        clip_lo = float(sizing.get("clip_lo") or 0.5)
        clip_hi = float(sizing.get("clip_hi") or 1.5)
        ev_scale = float(sizing.get("ev_scale_r") or (avg_win * BOOK_WIN_RATE + avg_loss * (1.0 - BOOK_WIN_RATE)))
        multiplier = ev_multiplier(
            float(proba),
            avg_win_r=avg_win,
            avg_loss_r=avg_loss,
            clip_lo=clip_lo,
            clip_hi=clip_hi,
            ev_scale_r=ev_scale,
        )
        if multiplier is None:
            return _fallback("probability_out_of_range", row)
        return SizingDecision(float(multiplier), float(proba), "model", row)


def load_sizer(*, cfg_raw: dict[str, Any] | None = None, repo_root: Path | None = None) -> HybridSizer:
    raw = (cfg_raw or {}).get("hybrid_sizing") or {}
    enabled = bool(raw.get("enabled", True))
    root = Path(repo_root) if repo_root else ROOT
    rel = raw.get("artifacts_dir") or "config/trading/hybrid_sizing"
    artifacts = Path(str(rel))
    if not artifacts.is_absolute():
        artifacts = root / artifacts
    return HybridSizer(artifacts, enabled=enabled)
