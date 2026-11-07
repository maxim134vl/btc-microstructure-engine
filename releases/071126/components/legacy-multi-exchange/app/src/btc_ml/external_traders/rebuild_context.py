"""Rebuild historical BTC M15 context into the ETLL market pack (shadow chain).

Writes ONLY under the pack directory. Does not touch live data/cognition.
Fidelity note: volume_response / stage-2 tip planes are not historically
backfilled — auction quality is OHLCV-degraded vs live tip stack.
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
    synthesize_cognition_triggers,
    synthesize_volume_response,
)

ROOT = Path(__file__).resolve().parents[3]
CONTEXT_VERSION = "btc_m15_historical_context_v2_proxy"


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


def _build_m15_availability(bars: pd.DataFrame) -> pd.DataFrame:
    """Minimal MTF-availability schema for M15 lived clock."""
    generated = _utc_now()
    work = bars.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp").reset_index(drop=True)
    open_ts = work["timestamp"]
    close_ts = open_ts + pd.Timedelta(minutes=15)
    return pd.DataFrame(
        {
            "evaluation_timestamp": close_ts,
            "timeframe": "M15",
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
            "source_dataset": "market_pack_btc_m15/feed_m15",
            "source_row_key": open_ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "schema_version": "mtf_availability_read_model_v1",
            "generated_at": generated,
        }
    )


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

    # 1b) OHLCV proxy planes (stand-in for tip-only volume_response / cognition)
    volume_response = synthesize_volume_response(candle)
    cognition_proxy = synthesize_cognition_triggers(candle)
    volume_path = out_dir / "volume_response_state_proxy.parquet"
    cognition_proxy_path = out_dir / "cognition_triggers_proxy.parquet"
    volume_response.to_parquet(volume_path, index=False)
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
                "BINANCE_NATIVE_VOLUME_SHADOW_CHAIN"
                if has_real_taker
                else "OHLCV_SHADOW_CHAIN_WITH_PROXY_PLANES"
            ),
            "taker_buy_volume_from_binance": bool(has_real_taker),
            "volume_response_historical_tip_engine": False,
            "volume_response_proxy": True,
            "cognition_triggers_proxy": True,
            "note_ru": (
                "Свечи и taker buy volume с Binance API. "
                "volume_response tip-engine исторически не прогоняли — "
                "используется proxy поверх реального delta/volume. "
                "Live cognition не трогали."
                if has_real_taker
                else (
                    "Контекст собран shadow-цепочкой от BTC M15 свечей. "
                    "volume_response и cognition triggers — исторический proxy."
                )
            ),
        },
        "artifacts": {
            "candle_structure_memory": str(candle_path),
            "volume_response_state_proxy": str(volume_path),
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
