"""Rebuild historical BTC M15 context into the ETLL market pack (shadow chain).

Writes ONLY under the pack directory. Does not touch live data/cognition.
Historical pack rebuild uses OHLCV proxy — volume_response / stage-2 tip
planes are not backfilled there.

Live M30/H1/H4 lifecycle is separate: it rolls live M15 volume classifiers
onto each closed higher-TF bar, then runs the same auction chain. It does
not copy M15 LONG/SHORT onto those timeframes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from btc_ml.external_traders.candle_structure import build_candle_structure
from btc_ml.external_traders.proxy_planes import (
    build_volume_classification,
    synthesize_cognition_triggers,
    synthesize_volume_response,
    synthesize_volume_response_v2,
)
from btc_ml.external_traders.tf_market_pack import resample_m15_feed_to_tf

ROOT = Path(__file__).resolve().parents[3]
CONTEXT_VERSION = "btc_m15_historical_context_v3_native_volume"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_script(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    # Ensure relative imports inside scripts resolve if any.
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


TF_BAR_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}


def _build_tf_availability(bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Minimal MTF-availability schema for one TF lived clock."""
    tf = str(timeframe or "").upper()
    minutes = TF_BAR_MINUTES.get(tf, 15)
    generated = _utc_now()
    work = bars.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp").reset_index(drop=True)
    open_ts = work["timestamp"]
    close_ts = open_ts + pd.Timedelta(minutes=minutes)
    tf_lower = tf.lower()
    return pd.DataFrame(
        {
            "evaluation_timestamp": close_ts,
            "timeframe": tf,
            "state_asof": close_ts,
            "source_state_timestamp": close_ts,
            "source_event_timestamp": close_ts,
            "source_bar_open": open_ts,
            "source_bar_close": close_ts,
            "is_new_event": True,
            "availability_status": "FRESH_EVENT",
            "availability_reason": "historical_pack_bar_close",
            "age_seconds": 0.0,
            "age_bars": 0.0,
            "writer_state": "HISTORICAL_PACK",
            "source_dataset": f"market_pack_btc_{tf_lower}/feed_{tf_lower}",
            "source_row_key": open_ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "schema_version": "mtf_availability_read_model_v1",
            "generated_at": generated,
        }
    )


def _build_m15_availability(bars: pd.DataFrame) -> pd.DataFrame:
    """Minimal MTF-availability schema for M15 lived clock."""
    return _build_tf_availability(bars, "M15")


def rebuild_btc_m15_historical_context(
    *,
    pack_dir: Path,
    limit_bars: int | None = None,
) -> dict[str, Any]:
    feed_path = pack_dir / "feed_m15.parquet"
    if not feed_path.exists():
        raise FileNotFoundError(feed_path)

    feed = pd.read_parquet(feed_path)
    feed["timestamp"] = pd.to_datetime(feed["timestamp"], utc=True, errors="coerce")
    feed = feed.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    has_real_taker = (
        "taker_buy_volume" in feed.columns and pd.to_numeric(feed["taker_buy_volume"], errors="coerce").notna().any()
    )
    if limit_bars is not None and limit_bars > 0:
        feed = feed.iloc[: int(limit_bars)].copy()

    out_dir = pack_dir / "context"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) candle structure
    candle = build_candle_structure(feed)
    candle_path = out_dir / "candle_structure_memory.parquet"
    candle.to_parquet(candle_path, index=False)

    # 1b) volume planes: keep thin proxy for A/B; write AES-native V2 as primary
    volume_response_proxy = synthesize_volume_response(candle)
    volume_response = synthesize_volume_response_v2(candle)
    cognition_proxy = synthesize_cognition_triggers(candle)
    classified = build_volume_classification(candle)
    class_cols = [
        c
        for c in (
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "buy_volume",
            "sell_volume",
            "delta",
            "close_position",
            "body",
            "spread",
            "upper_wick",
            "lower_wick",
            "volume_zscore",
            "spread_zscore",
            "volume_class",
            "candle_type",
        )
        if c in classified.columns
    ]
    volume_class = classified[class_cols].copy()
    volume_proxy_path = out_dir / "volume_response_state_proxy.parquet"
    volume_path = out_dir / "volume_response_state.parquet"
    volume_class_path = out_dir / "volume_classification_memory.parquet"
    cognition_proxy_path = out_dir / "cognition_triggers_proxy.parquet"
    volume_response_proxy.to_parquet(volume_proxy_path, index=False)
    volume_response.to_parquet(volume_path, index=False)
    volume_class.to_parquet(volume_class_path, index=False)
    cognition_proxy.to_parquet(cognition_proxy_path, index=False)

    # 2) auction episodes
    auction_mod = _load_script(
        "etll_build_auction_episode_memory",
        ROOT / "scripts/research/build_auction_episode_memory.py",
    )
    empty = pd.DataFrame()
    auction = auction_mod.build_auction_episode_rows(
        frames={
            "candles": candle,
            "live": feed,
            "volume_response": volume_response,
            "convergence": empty,
            "probabilistic": empty,
            "cognition": cognition_proxy,
            "cognition_composite": empty,
        }
    )
    auction_path = out_dir / "auction_episode_memory.parquet"
    auction.to_parquet(auction_path, index=False)

    # 3) cognitive state
    cog_mod = _load_script(
        "etll_build_cognitive_market_state_memory",
        ROOT / "scripts/research/build_cognitive_market_state_memory.py",
    )
    cognitive = cog_mod.build_cognitive_market_state_rows(auction)
    cognitive_path = out_dir / "cognitive_market_state_memory.parquet"
    cognitive.to_parquet(cognitive_path, index=False)

    # 4) final market context
    final_mod = _load_script(
        "etll_build_final_market_context_memory",
        ROOT / "scripts/research/build_final_market_context_memory.py",
    )
    final_ctx = final_mod.build_final_market_context_rows(cognitive)
    final_path = out_dir / "final_market_context_memory.parquet"
    final_ctx.to_parquet(final_path, index=False)

    # 5) lifecycle
    life_mod = _load_script(
        "etll_build_market_context_lifecycle_memory",
        ROOT / "scripts/research/build_market_context_lifecycle_memory.py",
    )
    lifecycle = life_mod.build_lifecycle_memory(
        final_ctx,
        auction_frame=auction,
        cognition_frame=None,
        evaluation_frame=cognitive,
    )
    episodes = life_mod.build_lifecycle_episodes(lifecycle)
    lifecycle_path = out_dir / "market_context_lifecycle_memory.parquet"
    episodes_path = out_dir / "market_context_lifecycle_episodes.parquet"
    lifecycle.to_parquet(lifecycle_path, index=False)
    episodes.to_parquet(episodes_path, index=False)

    # 6) availability clock (M15)
    availability = _build_m15_availability(feed)
    availability_path = out_dir / "multi_timeframe_availability_memory.parquet"
    availability.to_parquet(availability_path, index=False)

    def _span(frame: pd.DataFrame, col: str = "timestamp") -> dict[str, Any]:
        if frame is None or len(frame) == 0 or col not in frame.columns:
            return {"rows": 0, "start": None, "end": None}
        ts = pd.to_datetime(frame[col], utc=True, errors="coerce").dropna()
        if ts.empty:
            return {"rows": int(len(frame)), "start": None, "end": None}
        return {
            "rows": int(len(frame)),
            "start": ts.min().isoformat().replace("+00:00", "Z"),
            "end": ts.max().isoformat().replace("+00:00", "Z"),
        }

    ctx_counts: dict[str, int] = {}
    if len(lifecycle) and "active_market_context" in lifecycle.columns:
        ctx_counts = {
            str(k): int(v)
            for k, v in lifecycle["active_market_context"].astype(str).value_counts().items()
        }

    report = {
        "context_version": CONTEXT_VERSION,
        "generated_at": _utc_now(),
        "pack_dir": str(pack_dir),
        "limit_bars": limit_bars,
        "fidelity": {
            "mode": (
                "BINANCE_NATIVE_VOLUME_PLUS_VOLUME_RESPONSE_V2"
                if has_real_taker
                else "OHLCV_SHADOW_CHAIN_WITH_PROXY_PLANES"
            ),
            "taker_buy_volume_from_binance": bool(has_real_taker),
            "volume_response_historical_tip_engine": False,
            "volume_response_proxy_legacy_kept": True,
            "volume_response_v2_aes": True,
            "cognition_triggers_proxy": True,
            "note_ru": (
                "Свечи и taker buy volume с Binance API. "
                "volume_response_state.parquet = AES V2 (effort/result/participation) "
                "из bar volume+delta; tip-engine / footprint не бэкфиллили. "
                "proxy parquet оставлен для A/B. Live cognition не трогали."
                if has_real_taker
                else (
                    "Контекст собран shadow-цепочкой от BTC M15 свечей. "
                    "volume_response и cognition triggers — исторический proxy."
                )
            ),
        },
        "artifacts": {
            "candle_structure_memory": str(candle_path),
            "volume_response_state": str(volume_path),
            "volume_response_state_proxy": str(volume_proxy_path),
            "volume_classification_memory": str(volume_class_path),
            "cognition_triggers_proxy": str(cognition_proxy_path),
            "auction_episode_memory": str(auction_path),
            "cognitive_market_state_memory": str(cognitive_path),
            "final_market_context_memory": str(final_path),
            "market_context_lifecycle_memory": str(lifecycle_path),
            "market_context_lifecycle_episodes": str(episodes_path),
            "multi_timeframe_availability_memory": str(availability_path),
        },
        "spans": {
            "feed": _span(feed),
            "candle_structure": _span(candle),
            "auction": _span(auction),
            "cognitive": _span(cognitive),
            "final_context": _span(final_ctx),
            "lifecycle": _span(lifecycle),
            "availability": _span(availability, "evaluation_timestamp"),
            "episodes_rows": int(len(episodes)),
        },
        "lifecycle_active_market_context_counts": ctx_counts,
        "status": "CONTEXT_READY",
        "live_cognition_touched": False,
    }
    report_path = out_dir / "historical_context_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["artifacts"]["report"] = str(report_path)

    # Update pack manifest status if present.
    manifest_path = pack_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        manifest["status"] = "CONTEXT_READY_LIVED_REPLAY_PENDING"
        manifest["context"] = {
            "dir": str(out_dir),
            "report": str(report_path),
            "context_version": CONTEXT_VERSION,
            "generated_at": report["generated_at"],
        }
        manifest["next_step_ru"] = (
            "Контекст готов. Следующий шаг — lived replay модели на M15 "
            "(наши сделки по истории), затем сравнение с чужими BTC сделками."
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report


def rebuild_btc_tf_historical_context(
    *,
    pack_dir: Path,
    timeframe: str,
    limit_bars: int | None = None,
) -> dict[str, Any]:
    """Rebuild historical context for M30/H1/H4 pack (tagged lifecycle per TF)."""
    tf = str(timeframe or "").upper()
    tf_lower = tf.lower()
    feed_path = pack_dir / f"feed_{tf_lower}.parquet"
    if not feed_path.exists():
        raise FileNotFoundError(feed_path)

    feed = pd.read_parquet(feed_path)
    feed["timestamp"] = pd.to_datetime(feed["timestamp"], utc=True, errors="coerce")
    feed = feed.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    has_real_taker = (
        "taker_buy_volume" in feed.columns and pd.to_numeric(feed["taker_buy_volume"], errors="coerce").notna().any()
    )
    if limit_bars is not None and limit_bars > 0:
        feed = feed.iloc[: int(limit_bars)].copy()

    out_dir = pack_dir / "context"
    out_dir.mkdir(parents=True, exist_ok=True)
    context_version = f"btc_{tf_lower}_historical_context_v1_native_volume"

    candle = build_candle_structure(feed)
    candle_path = out_dir / "candle_structure_memory.parquet"
    candle.to_parquet(candle_path, index=False)

    volume_response_proxy = synthesize_volume_response(candle)
    volume_response = synthesize_volume_response_v2(candle)
    cognition_proxy = synthesize_cognition_triggers(candle)
    classified = build_volume_classification(candle)
    class_cols = [
        c
        for c in (
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "buy_volume",
            "sell_volume",
            "delta",
            "close_position",
            "body",
            "spread",
            "upper_wick",
            "lower_wick",
            "volume_zscore",
            "spread_zscore",
            "volume_class",
            "candle_type",
        )
        if c in classified.columns
    ]
    volume_class = classified[class_cols].copy()
    volume_proxy_path = out_dir / "volume_response_state_proxy.parquet"
    volume_path = out_dir / "volume_response_state.parquet"
    volume_class_path = out_dir / "volume_classification_memory.parquet"
    cognition_proxy_path = out_dir / "cognition_triggers_proxy.parquet"
    volume_response_proxy.to_parquet(volume_proxy_path, index=False)
    volume_response.to_parquet(volume_path, index=False)
    volume_class.to_parquet(volume_class_path, index=False)
    cognition_proxy.to_parquet(cognition_proxy_path, index=False)

    auction_mod = _load_script(
        "etll_build_auction_episode_memory",
        ROOT / "scripts/research/build_auction_episode_memory.py",
    )
    empty = pd.DataFrame()
    auction = auction_mod.build_auction_episode_rows(
        frames={
            "candles": candle,
            "live": feed,
            "volume_response": volume_response,
            "convergence": empty,
            "probabilistic": empty,
            "cognition": cognition_proxy,
            "cognition_composite": empty,
        }
    )
    auction_path = out_dir / "auction_episode_memory.parquet"
    auction.to_parquet(auction_path, index=False)

    cog_mod = _load_script(
        "etll_build_cognitive_market_state_memory",
        ROOT / "scripts/research/build_cognitive_market_state_memory.py",
    )
    cognitive = cog_mod.build_cognitive_market_state_rows(auction)
    cognitive_path = out_dir / "cognitive_market_state_memory.parquet"
    cognitive.to_parquet(cognitive_path, index=False)

    final_mod = _load_script(
        "etll_build_final_market_context_memory",
        ROOT / "scripts/research/build_final_market_context_memory.py",
    )
    final_ctx = final_mod.build_final_market_context_rows(cognitive)
    final_path = out_dir / "final_market_context_memory.parquet"
    final_ctx.to_parquet(final_path, index=False)

    life_mod = _load_script(
        "etll_build_market_context_lifecycle_memory",
        ROOT / "scripts/research/build_market_context_lifecycle_memory.py",
    )
    lifecycle = life_mod.build_lifecycle_memory(
        final_ctx,
        auction_frame=auction,
        cognition_frame=None,
        evaluation_frame=cognitive,
    )
    episodes = life_mod.build_lifecycle_episodes(lifecycle)
    lifecycle["timeframe"] = tf
    if len(episodes):
        episodes = episodes.copy()
        episodes["timeframe"] = tf

    lifecycle_path = out_dir / "market_context_lifecycle_memory.parquet"
    episodes_path = out_dir / "market_context_lifecycle_episodes.parquet"
    lifecycle.to_parquet(lifecycle_path, index=False)
    episodes.to_parquet(episodes_path, index=False)

    availability = _build_tf_availability(feed, tf)
    availability_path = out_dir / "multi_timeframe_availability_memory.parquet"
    availability.to_parquet(availability_path, index=False)

    def _span(frame: pd.DataFrame, col: str = "timestamp") -> dict[str, Any]:
        if frame is None or len(frame) == 0 or col not in frame.columns:
            return {"rows": 0, "start": None, "end": None}
        ts = pd.to_datetime(frame[col], utc=True, errors="coerce").dropna()
        if ts.empty:
            return {"rows": int(len(frame)), "start": None, "end": None}
        return {
            "rows": int(len(frame)),
            "start": ts.min().isoformat().replace("+00:00", "Z"),
            "end": ts.max().isoformat().replace("+00:00", "Z"),
        }

    ctx_counts: dict[str, int] = {}
    if len(lifecycle) and "active_market_context" in lifecycle.columns:
        ctx_counts = {
            str(k): int(v)
            for k, v in lifecycle["active_market_context"].astype(str).value_counts().items()
        }

    report = {
        "context_version": context_version,
        "timeframe": tf,
        "generated_at": _utc_now(),
        "pack_dir": str(pack_dir),
        "limit_bars": limit_bars,
        "fidelity": {
            "mode": (
                "BINANCE_NATIVE_VOLUME_PLUS_VOLUME_RESPONSE_V2"
                if has_real_taker
                else "OHLCV_SHADOW_CHAIN_WITH_PROXY_PLANES"
            ),
            "taker_buy_volume_from_binance": bool(has_real_taker),
            "volume_response_historical_tip_engine": False,
            "volume_response_v2_aes": True,
            "lifecycle_timeframe_tagged": True,
        },
        "artifacts": {
            "candle_structure_memory": str(candle_path),
            "volume_response_state": str(volume_path),
            "auction_episode_memory": str(auction_path),
            "cognitive_market_state_memory": str(cognitive_path),
            "final_market_context_memory": str(final_path),
            "market_context_lifecycle_memory": str(lifecycle_path),
            "market_context_lifecycle_episodes": str(episodes_path),
            "multi_timeframe_availability_memory": str(availability_path),
        },
        "spans": {
            "feed": _span(feed),
            "lifecycle": _span(lifecycle),
            "availability": _span(availability, "evaluation_timestamp"),
            "episodes_rows": int(len(episodes)),
        },
        "lifecycle_active_market_context_counts": ctx_counts,
        "status": "CONTEXT_READY",
        "live_cognition_touched": False,
    }
    report_path = out_dir / "historical_context_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["artifacts"]["report"] = str(report_path)

    manifest_path = pack_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        manifest["status"] = "CONTEXT_READY_LIVED_REPLAY_PENDING"
        manifest["context"] = {
            "dir": str(out_dir),
            "report": str(report_path),
            "context_version": context_version,
            "generated_at": report["generated_at"],
        }
        manifest["next_step_ru"] = f"Контекст {tf} готов. Следующий шаг — lived replay на {tf}."
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report


HIGHER_TIMEFRAMES = ("M30", "H1", "H4")
_M15_OHLCV = ("timestamp", "open", "high", "low", "close", "volume")
_LIVE_VOLUME_RESPONSE = ROOT / "data" / "cognition" / "volume_response_state.parquet"
_LIVE_CONVERGENCE = ROOT / "data" / "reinforcement" / "auction_convergence_memory.parquet"
_LIVE_PROBABILISTIC = ROOT / "data" / "probabilistic" / "probabilistic_auction_memory.parquet"
_LIVE_COGNITION = ROOT / "data" / "cognition" / "runtime_cognition_memory.parquet"
_LIVE_COGNITION_COMPOSITE = ROOT / "data" / "cognition" / "runtime_cognition_composite.parquet"
_SALIENT_SKIP = frozenset(
    {
        "",
        "UNKNOWN",
        "NONE",
        "NAN",
        "NULL",
        "NEUTRAL_VOLUME",
        "NO_CLIMAX",
        "BALANCED_RESPONSE",
        "NEUTRAL",
        "MIDDLE",
    }
)


def _read_optional_parquet(path: Path) -> pd.DataFrame:
    if path is None or not path.exists() or not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _last_salient(values: pd.Series) -> Any:
    cleaned: list[str] = []
    raw: list[Any] = []
    for value in values.tolist():
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        text = str(value).strip()
        if not text:
            continue
        raw.append(value)
        cleaned.append(text.upper())
    salient = [raw[i] for i, token in enumerate(cleaned) if token not in _SALIENT_SKIP]
    if salient:
        return salient[-1]
    return raw[-1] if raw else None


def rollup_m15_frame_to_tf(
    m15: pd.DataFrame,
    tf_bars: pd.DataFrame,
    *,
    timeframe: str,
) -> pd.DataFrame:
    """Map M15 classifier rows onto closed higher-TF bars.

    Does not copy M15 LONG/SHORT. Categorical fields keep the last salient
    event inside the TF bar; relative_volume is max; delta is sum.
    """
    tf = str(timeframe or "").upper()
    minutes = TF_BAR_MINUTES.get(tf)
    if minutes is None or minutes <= 15:
        raise ValueError(f"unsupported target timeframe: {tf}")
    if m15 is None or not len(m15) or "timestamp" not in m15.columns:
        return pd.DataFrame()
    if tf_bars is None or not len(tf_bars) or "timestamp" not in tf_bars.columns:
        return pd.DataFrame()
    work = m15.copy()
    work["_ts"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["_ts"])
    if not len(work):
        return pd.DataFrame()
    work["_tf_open"] = work["_ts"].dt.floor(f"{int(minutes)}min")
    numeric_max = [c for c in ("relative_volume", "relative_spread") if c in work.columns]
    numeric_sum = [c for c in ("delta",) if c in work.columns]
    cat_cols = [
        c
        for c in (
            "volume_event",
            "climax_state",
            "effort_result_state",
            "volume_class",
            "localized_behavior",
            "continuation_quality",
            "participation_state",
            "convergence_state",
            "auction_regime",
            "trigger_event",
            "location_bias",
            "tier1_trigger_event",
            "tier1_location_bias",
        )
        if c in work.columns
    ]
    last_num = [
        c
        for c in ("distribution_probability", "absorption_probability")
        if c in work.columns
    ]
    grouped = work.groupby("_tf_open", sort=True)
    rows: list[dict[str, Any]] = []
    for tf_open, grp in grouped:
        rec: dict[str, Any] = {"timestamp": pd.Timestamp(tf_open)}
        for col in cat_cols:
            rec[col] = _last_salient(grp[col])
        for col in numeric_max:
            series = pd.to_numeric(grp[col], errors="coerce")
            rec[col] = None if series.dropna().empty else float(series.max())
        for col in numeric_sum:
            series = pd.to_numeric(grp[col], errors="coerce").fillna(0.0)
            rec[col] = float(series.sum())
        for col in last_num:
            series = pd.to_numeric(grp[col], errors="coerce").dropna()
            rec[col] = None if series.empty else float(series.iloc[-1])
        rows.append(rec)
    if not rows:
        return pd.DataFrame()
    rolled = pd.DataFrame(rows)
    tf_ts = pd.to_datetime(tf_bars["timestamp"], utc=True, errors="coerce")
    out = pd.DataFrame({"timestamp": tf_ts.dropna().drop_duplicates().sort_values()})
    out = out.merge(rolled, on="timestamp", how="left")
    return out


def build_independent_tf_lifecycle(
    feed: pd.DataFrame,
    *,
    timeframe: str,
    volume_response_m15: pd.DataFrame | None = None,
    convergence_m15: pd.DataFrame | None = None,
    probabilistic_m15: pd.DataFrame | None = None,
    cognition_m15: pd.DataFrame | None = None,
    cognition_composite_m15: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Same auction→cognitive→final→lifecycle chain as TF historical packs.

    Runs on that TF's closed bars only. Tags ``timeframe``. Does not copy M15
    lifecycle rows onto M30/H1/H4. Live M15 volume classifiers are rolled onto
    the TF bar when present; OHLCV proxy is the fallback only.
    """
    tf = str(timeframe or "").upper()
    if tf not in HIGHER_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {tf}")
    auction_mod = _load_script(
        "etll_build_auction_episode_memory",
        ROOT / "scripts/research/build_auction_episode_memory.py",
    )
    cog_mod = _load_script(
        "etll_build_cognitive_market_state_memory",
        ROOT / "scripts/research/build_cognitive_market_state_memory.py",
    )
    final_mod = _load_script(
        "etll_build_final_market_context_memory",
        ROOT / "scripts/research/build_final_market_context_memory.py",
    )
    life_mod = _load_script(
        "etll_build_market_context_lifecycle_memory",
        ROOT / "scripts/research/build_market_context_lifecycle_memory.py",
    )
    candle = build_candle_structure(feed)
    if volume_response_m15 is None:
        volume_response_m15 = _read_optional_parquet(_LIVE_VOLUME_RESPONSE)
    if convergence_m15 is None:
        convergence_m15 = _read_optional_parquet(_LIVE_CONVERGENCE)
    if probabilistic_m15 is None:
        probabilistic_m15 = _read_optional_parquet(_LIVE_PROBABILISTIC)
    if cognition_m15 is None:
        cognition_m15 = _read_optional_parquet(_LIVE_COGNITION)
    if cognition_composite_m15 is None:
        cognition_composite_m15 = _read_optional_parquet(_LIVE_COGNITION_COMPOSITE)

    volume_response = rollup_m15_frame_to_tf(volume_response_m15, candle, timeframe=tf)
    used_live_volume = bool(
        volume_response is not None
        and len(volume_response)
        and "volume_event" in volume_response.columns
        and bool(volume_response["volume_event"].notna().any())
    )
    if not used_live_volume:
        volume_response = synthesize_volume_response_v2(candle)
    cognition_proxy = rollup_m15_frame_to_tf(cognition_m15, candle, timeframe=tf)
    if cognition_proxy is None or not len(cognition_proxy) or "trigger_event" not in cognition_proxy.columns:
        cognition_proxy = synthesize_cognition_triggers(candle)
    else:
        missing_trig = cognition_proxy["trigger_event"].isna().all()
        if missing_trig:
            cognition_proxy = synthesize_cognition_triggers(candle)
    convergence = rollup_m15_frame_to_tf(convergence_m15, candle, timeframe=tf)
    probabilistic = rollup_m15_frame_to_tf(probabilistic_m15, candle, timeframe=tf)
    cognition_composite = rollup_m15_frame_to_tf(cognition_composite_m15, candle, timeframe=tf)
    auction = auction_mod.build_auction_episode_rows(
        frames={
            "candles": candle,
            "live": feed,
            "volume_response": volume_response,
            "convergence": convergence,
            "probabilistic": probabilistic,
            "cognition": cognition_proxy,
            "cognition_composite": cognition_composite,
        }
    )
    cognitive = cog_mod.build_cognitive_market_state_rows(auction)
    final_ctx = final_mod.build_final_market_context_rows(cognitive)
    lifecycle = life_mod.build_lifecycle_memory(
        final_ctx,
        auction_frame=auction,
        cognition_frame=None,
        evaluation_frame=cognitive,
    )
    episodes = life_mod.build_lifecycle_episodes(lifecycle)
    lifecycle = lifecycle.copy()
    lifecycle["timeframe"] = tf
    lifecycle["lifecycle_source"] = (
        "INDEPENDENT_CLOSED_BAR_VOLUME" if used_live_volume else "INDEPENDENT_OHLCV_PROXY"
    )
    if len(episodes):
        episodes = episodes.copy()
        episodes["timeframe"] = tf
        episodes["lifecycle_source"] = lifecycle["lifecycle_source"].iloc[0]
    return lifecycle, episodes


def _tag_m15(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "timeframe" not in out.columns:
        out["timeframe"] = "M15"
    else:
        tf = out["timeframe"].astype(str).str.upper()
        out = out.loc[tf.eq("M15")].copy()
    if "lifecycle_source" not in out.columns:
        out["lifecycle_source"] = "LIVE_SHADOW_CHAIN"
    else:
        out["lifecycle_source"] = out["lifecycle_source"].fillna("LIVE_SHADOW_CHAIN")
        blank = out["lifecycle_source"].astype(str).str.strip().isin(("", "nan", "None", "NONE"))
        out.loc[blank, "lifecycle_source"] = "LIVE_SHADOW_CHAIN"
    return out


def extend_m15_lifecycle_with_independent_higher_timeframes(
    *,
    m15_lifecycle: pd.DataFrame,
    m15_episodes: pd.DataFrame,
    feed_m15: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep M15 rows bit-identical (plus timeframe tag); append independent M30/H1/H4.

    Missing/empty M15 bars skip higher TFs instead of failing the M15 chain.
    A single TF builder error is skipped the same way.
    """
    m15_life = _tag_m15(m15_lifecycle)
    m15_ep = _tag_m15(m15_episodes) if m15_episodes is not None and len(m15_episodes) else m15_episodes
    parts_life = [m15_life]
    parts_ep = [m15_ep] if m15_ep is not None and len(m15_ep) else []
    if feed_m15 is None or not len(feed_m15):
        if parts_ep:
            return m15_life, pd.concat(parts_ep, ignore_index=True, sort=False)
        return m15_life, m15_episodes
    volume_response_m15 = _read_optional_parquet(_LIVE_VOLUME_RESPONSE)
    convergence_m15 = _read_optional_parquet(_LIVE_CONVERGENCE)
    probabilistic_m15 = _read_optional_parquet(_LIVE_PROBABILISTIC)
    cognition_m15 = _read_optional_parquet(_LIVE_COGNITION)
    cognition_composite_m15 = _read_optional_parquet(_LIVE_COGNITION_COMPOSITE)
    for tf in HIGHER_TIMEFRAMES:
        try:
            feed_tf = resample_m15_feed_to_tf(feed_m15, tf)
            if feed_tf is None or not len(feed_tf):
                continue
            life_tf, ep_tf = build_independent_tf_lifecycle(
                feed_tf,
                timeframe=tf,
                volume_response_m15=volume_response_m15,
                convergence_m15=convergence_m15,
                probabilistic_m15=probabilistic_m15,
                cognition_m15=cognition_m15,
                cognition_composite_m15=cognition_composite_m15,
            )
        except Exception as exc:  # noqa: BLE001 — do not fail the live M15 parquet chain
            print(f"WARN skip {tf} independent lifecycle: {exc}", file=sys.stderr)
            continue
        if life_tf is not None and len(life_tf):
            parts_life.append(life_tf)
        if ep_tf is not None and len(ep_tf):
            parts_ep.append(ep_tf)
    life = pd.concat(parts_life, ignore_index=True, sort=False)
    life["_sort"] = pd.to_datetime(life["timestamp"], utc=True, errors="coerce")
    life = life.sort_values(["_sort", "timeframe"]).drop(columns=["_sort"]).reset_index(drop=True)
    if parts_ep:
        episodes = pd.concat(parts_ep, ignore_index=True, sort=False)
        if "end_time" in episodes.columns:
            episodes["_sort"] = pd.to_datetime(episodes["end_time"], utc=True, errors="coerce")
            episodes = episodes.sort_values(["_sort", "timeframe"]).drop(columns=["_sort"]).reset_index(drop=True)
    else:
        episodes = m15_episodes
    return life, episodes


def load_m15_closed_bars_for_resample(root: Path | None = None) -> pd.DataFrame:
    """Union every available closed-bar M15 OHLCV source.

    Book packs resampled the full M15 feed. Live must not rebuild higher-TF
    lifecycle from whichever single snapshot file happens to come first.
    Overlapping timestamps keep candle-structure columns (taker/derived).
    Extra timestamps from the live feed / partitions are appended.
    """
    base = Path(root) if root is not None else ROOT
    needed = set(_M15_OHLCV)
    ranked: list[tuple[int, pd.DataFrame]] = []

    def _maybe_add(path: Path, rank: int) -> None:
        if not path.exists() or not path.is_file():
            return
        try:
            frame = pd.read_parquet(path)
        except Exception:
            return
        if needed.issubset(set(frame.columns)):
            ranked.append((rank, frame))

    _maybe_add(base / "data" / "cognition" / "candle_structure_memory.parquet", 0)
    _maybe_add(base / "data" / "live" / "live_market_feed.parquet", 1)
    _maybe_add(base / "data" / "live" / "latest.parquet", 1)
    partition_dir = base / "data" / "live" / "partitions"
    if partition_dir.is_dir():
        for path in sorted(partition_dir.glob("*.parquet")):
            if path.name == "latest.parquet":
                continue
            _maybe_add(path, 2)
    if not ranked:
        raise FileNotFoundError("no M15 OHLCV closed-bar feed for higher-TF resample")
    parts: list[pd.DataFrame] = []
    for rank, frame in ranked:
        work = frame.copy()
        work["_src_rank"] = rank
        parts.append(work)
    out = pd.concat(parts, ignore_index=True, sort=False)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp"])
    out = out.sort_values(["timestamp", "_src_rank"], kind="mergesort")
    out = out.drop_duplicates(subset=["timestamp"], keep="first").drop(columns=["_src_rank"])
    return out.sort_values("timestamp").reset_index(drop=True)
