"""Build causal zone catalogs for STP2 candidate decisions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from . import DEFAULT_TICK_SIZE, LOOKBACK_BARS_BY_TF, TF_SECONDS
from .bars import build_bars_from_trades, closed_bars_before
from .profile import build_exact_candle_volume_profile
from .reaction import (
    REACTION_THRESHOLDS,
    prove_zone_reaction,
    zone_age_ok,
    zone_invalidated_by_path,
)
from .significance import classify_bars_shadow
from .timeutil import iso, parse_ts
from .trades import load_agg_trades
from .zones import extract_zones


STRENGTH = {"CLIMAX": 3, "STOPPING": 2, "HIGH_AVERAGE_VOLUME": 1, "NORMAL": 0, "LOW_SMALL": -1}


def load_causal_trades(*, repo, decision_ts: datetime, timeframe: str, cache: dict | None = None) -> pd.DataFrame:
    tf = str(timeframe).upper()
    tf_s = TF_SECONDS[tf]
    lookback = int(LOOKBACK_BARS_BY_TF.get(tf, 24))
    start = decision_ts - timedelta(seconds=tf_s * (lookback + 2))
    key = (tf, start.isoformat(), decision_ts.isoformat())
    if cache is not None and key in cache:
        return cache[key]
    trades = load_agg_trades(repo=repo, start=start, end=decision_ts)
    if cache is not None:
        cache[key] = trades
    return trades


def build_candidate_catalog(
    *,
    repo,
    timeframe: str,
    side: str,
    decision_ts: datetime,
    entry: float,
    trade_cache: dict | None = None,
) -> dict[str, Any]:
    """Exact bars + shadow classes + profiles + reaction-annotated zones for one TF."""
    tf = str(timeframe).upper()
    tf_s = TF_SECONDS[tf]
    trades = load_causal_trades(repo=repo, decision_ts=decision_ts, timeframe=tf, cache=trade_cache)
    bars_raw = build_bars_from_trades(trades, timeframe=tf, causal_cutoff=decision_ts)
    classified = classify_bars_shadow(bars_raw)
    closed = closed_bars_before(classified, decision_ts=decision_ts)

    # Reaction path uses exact trades already loaded (BBO optional / too heavy for backfill).
    # Prefer a light trade subsample if dense.
    events = trades
    if events is not None and not events.empty and len(events) > 200000:
        events = events.iloc[:: max(1, len(events) // 200000)].copy()

    zone_rows: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    significant_count = 0
    exact_profiles = 0

    for bar in closed:
        cls = bar.get("shadow_volume_class")
        if cls in {"CLIMAX", "STOPPING", "HIGH_AVERAGE_VOLUME"}:
            significant_count += 1
        if not zone_age_ok(
            source_candle_open=parse_ts(bar["open_timestamp"]),
            decision_ts=decision_ts,
            timeframe=tf,
            age_policy="ZONE_AGE_8_BARS",
            tf_seconds=tf_s,
        ):
            continue
        if cls not in {"CLIMAX", "STOPPING", "HIGH_AVERAGE_VOLUME"}:
            continue

        open_ts = parse_ts(bar["open_timestamp"])
        natural_close = parse_ts(bar["natural_close_timestamp"])
        if open_ts is None or natural_close is None:
            continue
        causal_cutoff = min(natural_close, decision_ts)
        if causal_cutoff > decision_ts:
            continue
        candle_trades = trades[
            (trades["_ts"] >= pd.Timestamp(open_ts)) & (trades["_ts"] <= pd.Timestamp(causal_cutoff))
        ] if trades is not None and not trades.empty else pd.DataFrame()
        profile = build_exact_candle_volume_profile(
            candle_trades,
            candle_start=open_ts,
            causal_cutoff=causal_cutoff,
            tick_size=DEFAULT_TICK_SIZE,
        )
        if not profile.get("ok"):
            continue
        exact_profiles += 1
        profiles.append(
            {
                "source_candle_id": bar["candle_id"],
                "timeframe": tf,
                "classification": cls,
                "classification_mode": bar.get("classification_mode"),
                **{k: profile.get(k) for k in ("poc_price", "total_base_volume", "conservation_ok", "trade_count")},
            }
        )
        zones = extract_zones(profile)
        created_at = natural_close
        for z in zones:
            bullish_ok = float(z["upper_boundary"]) < entry
            bearish_ok = float(z["lower_boundary"]) > entry
            # Lazy reaction bag; seed preferred threshold status only (research speed).
            reactions: dict[str, dict[str, Any]] = {}
            pref_bull = prove_zone_reaction(
                zone=z,
                direction="BULLISH",
                events=events,
                zone_created_at=created_at,
                decision_ts=decision_ts,
                threshold_id="REACTION_100_ZONE_WIDTH",
                zone_timeframe=tf,
                expected_timeframe=tf,
            )
            pref_bear = prove_zone_reaction(
                zone=z,
                direction="BEARISH",
                events=events,
                zone_created_at=created_at,
                decision_ts=decision_ts,
                threshold_id="REACTION_100_ZONE_WIDTH",
                zone_timeframe=tf,
                expected_timeframe=tf,
            )
            reactions["BULLISH::REACTION_100_ZONE_WIDTH"] = pref_bull
            reactions["BEARISH::REACTION_100_ZONE_WIDTH"] = pref_bear
            invalidated_bull = zone_invalidated_by_path(
                zone=z,
                direction="BULLISH",
                events=events,
                zone_created_at=created_at,
                decision_ts=decision_ts,
            )
            invalidated_bear = zone_invalidated_by_path(
                zone=z,
                direction="BEARISH",
                events=events,
                zone_created_at=created_at,
                decision_ts=decision_ts,
            )
            pref = pref_bull if pref_bull.get("status") == "PROVEN" else pref_bear
            zone_rows.append(
                {
                    "zone_id": f"{bar['candle_id']}|{z['zone_method']}|{z['lower_boundary']}|{z['upper_boundary']}",
                    "timeframe": tf,
                    "source_candle_id": bar["candle_id"],
                    "source_candle_open": bar["open_timestamp"],
                    "classification": cls,
                    "classification_mode": bar.get("classification_mode"),
                    "lower_boundary": z["lower_boundary"],
                    "upper_boundary": z["upper_boundary"],
                    "POC": z["peak_volume_price"],
                    "peak_volume_price": z["peak_volume_price"],
                    "base_volume": z["base_volume"],
                    "quote_volume": z["quote_volume"],
                    "volume_share": z["share_of_candle_volume"],
                    "buy_aggressor_volume": z["buy_aggressor_volume"],
                    "sell_aggressor_volume": z["sell_aggressor_volume"],
                    "zone_method": z["zone_method"],
                    "created_at": iso(created_at),
                    "causal_cutoff": iso(causal_cutoff),
                    "reaction_status": (pref or {}).get("status") or "INSUFFICIENT_EVENT_HISTORY",
                    "reactions": reactions,
                    "_reaction_events": events,
                    "_zone_created_at": created_at,
                    "_decision_ts": decision_ts,
                    "invalidated_bullish": invalidated_bull,
                    "invalidated_bearish": invalidated_bear,
                    "bullish_location_ok": bullish_ok,
                    "bearish_location_ok": bearish_ok,
                    "volume_class": cls,
                }
            )

    return {
        "trades": trades,
        "bars": classified,
        "closed_bars": closed,
        "zones": zone_rows,
        "profiles": profiles,
        "significant_count": significant_count,
        "exact_profiles": exact_profiles,
        "events_for_reaction": "agg_trade",
    }


def select_usable_zone(
    *,
    zones: list[dict[str, Any]],
    role: str,  # PROTECTIVE | TARGET
    side: str,
    entry: float,
    volume_class_policy: str,
    zone_method: str,
    reaction_threshold_id: str,
    zone_age_policy: str,
    decision_ts: datetime,
    timeframe: str,
) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
    from .significance import class_allowed_shadow

    tf_s = TF_SECONDS[str(timeframe).upper()]
    side_u = str(side).upper()
    want_dir = None
    if role == "PROTECTIVE":
        want_dir = "BULLISH" if side_u == "LONG" else "BEARISH"
    else:
        want_dir = "BEARISH" if side_u == "LONG" else "BULLISH"

    cands: list[tuple[float, dict[str, Any], dict[str, Any], bool]] = []
    for z in zones:
        if z.get("zone_method") != zone_method:
            continue
        if not class_allowed_shadow(z.get("volume_class") or z.get("classification"), volume_class_policy):
            continue
        open_ts = parse_ts(z.get("source_candle_open"))
        if open_ts is None:
            continue
        if not zone_age_ok(
            source_candle_open=open_ts,
            decision_ts=decision_ts,
            timeframe=timeframe,
            age_policy=zone_age_policy,
            tf_seconds=tf_s,
        ):
            continue
        if role == "PROTECTIVE":
            if side_u == "LONG" and not z.get("bullish_location_ok"):
                continue
            if side_u == "SHORT" and not z.get("bearish_location_ok"):
                continue
        else:
            if side_u == "LONG" and not z.get("bearish_location_ok"):
                continue
            if side_u == "SHORT" and not z.get("bullish_location_ok"):
                continue

        react_key = f"{want_dir}::{reaction_threshold_id}"
        reactions = z.setdefault("reactions", {})
        if react_key not in reactions:
            created = z.get("_zone_created_at") or parse_ts(z.get("created_at"))
            events = z.get("_reaction_events")
            if created is None or events is None:
                react = {"status": "INSUFFICIENT_EVENT_HISTORY"}
            else:
                react = prove_zone_reaction(
                    zone=z,
                    direction=want_dir,
                    events=events,
                    zone_created_at=created,
                    decision_ts=decision_ts,
                    threshold_id=reaction_threshold_id,
                    zone_timeframe=str(z.get("timeframe") or timeframe),
                    expected_timeframe=timeframe,
                )
            reactions[react_key] = react
        react = reactions.get(react_key) or {"status": "INSUFFICIENT_EVENT_HISTORY"}
        invalidated = z.get("invalidated_bullish") if want_dir == "BULLISH" else z.get("invalidated_bearish")
        # If invalidated after proven reaction, still ok only if reaction occurred first — prove_zone_reaction handles before-reaction invalidation.
        if invalidated and react.get("status") != "PROVEN":
            react = {**react, "status": "INVALIDATED_BEFORE_REACTION"}

        usable = (
            react.get("status") == "PROVEN"
            and str(z.get("timeframe")).upper() == str(timeframe).upper()
            and (z.get("volume_class") or z.get("classification")) in {"CLIMAX", "STOPPING", "HIGH_AVERAGE_VOLUME"}
            and not (invalidated and react.get("status") != "PROVEN")
        )
        if role == "PROTECTIVE":
            dist = (
                entry - float(z["upper_boundary"])
                if side_u == "LONG"
                else float(z["lower_boundary"]) - entry
            )
        else:
            dist = (
                float(z["lower_boundary"]) - entry
                if side_u == "LONG"
                else entry - float(z["upper_boundary"])
            )
        if dist < 0:
            continue
        cands.append((dist, z, react, usable))

    if not cands:
        return None, {"status": "NOT_TOUCHED"}, False

    # Prefer usable; then nearest; then significance; then fresher
    cands.sort(
        key=lambda t: (
            0 if t[3] else 1,
            t[0],
            -STRENGTH.get(str(t[1].get("volume_class") or t[1].get("classification")), 0),
            str(t[1].get("source_candle_open") or ""),
        )
    )
    # Among nearest distance among usable-first group
    best = cands[0]
    # Re-rank nearest among same usability tier
    tier = [c for c in cands if c[3] == best[3]]
    tier.sort(
        key=lambda t: (
            t[0],
            -STRENGTH.get(str(t[1].get("volume_class") or t[1].get("classification")), 0),
            # fresher = larger open timestamp string works for ISO
            str(t[1].get("source_candle_open") or ""),
        )
    )
    # fresher should win ties: reverse open sort
    best_dist = tier[0][0]
    tied = [c for c in tier if abs(c[0] - best_dist) < 1e-12]
    tied.sort(
        key=lambda t: (
            -STRENGTH.get(str(t[1].get("volume_class") or t[1].get("classification")), 0),
            str(t[1].get("source_candle_open") or ""),
        ),
        reverse=False,
    )
    # fresher = max open timestamp
    tied.sort(
        key=lambda t: (
            -STRENGTH.get(str(t[1].get("volume_class") or t[1].get("classification")), 0),
            -(pd.Timestamp(t[1].get("source_candle_open")).timestamp() if t[1].get("source_candle_open") else 0),
        )
    )
    z, react, usable = tied[0][1], tied[0][2], tied[0][3]
    return z, react, usable
