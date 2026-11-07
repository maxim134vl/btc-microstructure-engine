#!/usr/bin/env python3
"""ETLL volume fidelity Step A verify + Step B volume_response V2 build.

A: confirm pack has native Binance volume/taker (no re-download if present).
B: build AES-compatible volume_response_state from candle_structure + real volume.
Does NOT touch live cognition. Tip/footprint engine is NOT backfilled.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.proxy_planes import (  # noqa: E402
    build_volume_classification,
    synthesize_volume_response,
    synthesize_volume_response_v2,
)

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"
DEFAULT_OUT = ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def verify_step_a(pack: Path) -> dict:
    feed = pd.read_parquet(pack / "feed_m15.parquet")
    candle = pd.read_parquet(pack / "context" / "candle_structure_memory.parquet")
    vol = pd.to_numeric(feed.get("volume"), errors="coerce")
    taker = pd.to_numeric(feed.get("taker_buy_volume"), errors="coerce")
    return {
        "status": "A_DONE" if vol.notna().any() and float(vol.sum()) > 0 else "A_MISSING_VOLUME",
        "n_bars": int(len(feed)),
        "volume_sum": float(vol.fillna(0).sum()),
        "taker_buy_present": bool(taker.notna().any() and float(taker.sum()) > 0),
        "volume_zscore_non_nan_share": float(
            pd.to_numeric(candle.get("volume_zscore"), errors="coerce").notna().mean()
        ),
        "volume_zscore_gt_1_5": int(
            (pd.to_numeric(candle.get("volume_zscore"), errors="coerce") > 1.5).sum()
        ),
        "span": {
            "start": str(pd.to_datetime(feed["timestamp"], utc=True).min()),
            "end": str(pd.to_datetime(feed["timestamp"], utc=True).max()),
        },
    }


def build_step_b(pack: Path, out: Path) -> dict:
    candle = pd.read_parquet(pack / "context" / "candle_structure_memory.parquet")
    proxy = synthesize_volume_response(candle)
    v2 = synthesize_volume_response_v2(candle)
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
    vol_class = classified[class_cols].copy()

    ctx = pack / "context"
    # Keep legacy proxy; write V2 as primary AES name
    proxy.to_parquet(ctx / "volume_response_state_proxy.parquet", index=False)
    v2.to_parquet(ctx / "volume_response_state.parquet", index=False)
    vol_class.to_parquet(ctx / "volume_classification_memory.parquet", index=False)

    full_dir = out / "full_span"
    full_dir.mkdir(parents=True, exist_ok=True)
    v2.to_parquet(full_dir / "volume_response_state.parquet", index=False)
    proxy.to_parquet(full_dir / "volume_response_state_proxy.parquet", index=False)

    # June slice for pilot
    june = out / "june_pilot"
    june.mkdir(parents=True, exist_ok=True)
    ts = pd.to_datetime(v2["timestamp"], utc=True)
    mask = (ts >= "2026-05-28") & (ts < "2026-07-02")
    v2.loc[mask].to_parquet(june / "volume_response_state.parquet", index=False)

    live_expected = {
        "effort_score",
        "result_score",
        "participation_state",
        "unfinished_auction",
        "climax_state",
        "localized_behavior",
    }
    schema_gap = {
        "proxy_columns": sorted(proxy.columns.tolist()),
        "v2_columns": sorted(v2.columns.tolist()),
        "proxy_missing_aes": sorted(live_expected - set(proxy.columns)),
        "v2_missing_aes": sorted(live_expected - set(v2.columns)),
        "v2_fills_aes": sorted(live_expected & set(v2.columns)),
    }
    (out / "schema_gap_proxy_vs_live.json").write_text(
        json.dumps(schema_gap, indent=2) + "\n", encoding="utf-8"
    )

    event_counts = {str(k): int(v) for k, v in v2["volume_event"].value_counts().items()}
    part_counts = {str(k): int(v) for k, v in v2["participation_state"].value_counts().items()}
    climax_counts = {str(k): int(v) for k, v in v2["climax_state"].value_counts().items()}
    class_counts = {str(k): int(v) for k, v in v2["volume_class"].value_counts().items()}

    return {
        "status": "B_BUILT",
        "n_bars": int(len(v2)),
        "n_june_bars": int(mask.sum()),
        "aes_fields_present": schema_gap["v2_fills_aes"],
        "volume_event_counts": event_counts,
        "participation_counts": part_counts,
        "climax_counts": climax_counts,
        "volume_class_counts": class_counts,
        "unfinished_share": float(v2["unfinished_auction"].mean()),
        "mean_effort_score": float(v2["effort_score"].mean()),
        "mean_result_score": float(v2["result_score"].mean()),
        "pack_paths": {
            "volume_response_state": str(ctx / "volume_response_state.parquet"),
            "volume_response_state_proxy": str(ctx / "volume_response_state_proxy.parquet"),
            "volume_classification_memory": str(ctx / "volume_classification_memory.parquet"),
        },
        "schema_gap": schema_gap,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    step_a = verify_step_a(args.pack_dir)
    print(json.dumps({"step_a": step_a}, indent=2), flush=True)
    if step_a["status"] != "A_DONE":
        (out / "README_status.json").write_text(
            json.dumps(
                {
                    "generated_at": _utc_now(),
                    "step_a": step_a,
                    "step_b": {"status": "SKIPPED"},
                    "step_c": {"status": "DEFERRED_AGGTRADE_MONTH"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 2

    step_b = build_step_b(args.pack_dir, out)
    status = {
        "generated_at": _utc_now(),
        "step_a": step_a,
        "step_b": step_b,
        "step_c": {
            "status": "DEFERRED",
            "note": "aggTrade month later; reuse STP2 June tick pack path",
            "tick_pack": str(
                args.pack_dir / "stp2_pilot/tick_pack_202606/tick_pack_manifest.json"
            ),
        },
        "fidelity_label": "PACK_NATIVE_VOLUME_PLUS_VOLUME_RESPONSE_V2",
        "honest_limit": "bar volume + taker delta only; not tip/footprint climax truth",
        "next": "June Auction pilot with volume_response_state.parquet wired",
    }
    (out / "README_status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    # also drop june plan stub
    (out / "aggtrade_month_later").mkdir(parents=True, exist_ok=True)
    (out / "aggtrade_month_later" / "plan.json").write_text(
        json.dumps(status["step_c"], indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"step_b_summary": {k: step_b[k] for k in step_b if k != "schema_gap"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
