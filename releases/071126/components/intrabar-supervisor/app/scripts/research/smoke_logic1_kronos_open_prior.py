#!/usr/bin/env python3
"""Phase 3 smoke: Kronos-mini on closed M15 windows. Not a live S4.1 gate.

  PYTHONPATH=src ./venv/bin/python scripts/research/smoke_logic1_kronos_open_prior.py
  PYTHONPATH=src ./venv/bin/python scripts/research/smoke_logic1_kronos_open_prior.py --offline --n-windows 20

Downloads weights into data/research/kronos/hf_cache on first run.
Does not write timeframe commands. Does not touch hybrid_sizing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.research.logic1_kronos_open_prior import (  # noqa: E402
    features_from_cloud,
    load_candidate_config,
    lookback_is_causal,
)
from btc_ml.research.logic1_kronos_runtime import (  # noqa: E402
    HF_CACHE,
    cloud_for_closed_bar,
    load_m15_ohlcv,
    load_predictor,
    lookback_ohlcv,
    predictor_kwargs_from_config,
    smoke_windows,
)

OUT_DIR = ROOT / "data/research/kronos/smoke"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="Kronos-mini closed-bar smoke")
    parser.add_argument("--n-windows", type=int, default=20)
    parser.add_argument("--n-paths", type=int, default=8)
    parser.add_argument("--lookback-bars", type=int, default=400)
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--bars", type=Path, default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--device", default=None)
    args = parser.parse_args()

    cfg = load_candidate_config()
    model = dict(cfg.get("model") or {})
    pred_len = int((model.get("pred_len_by_tf") or {}).get(str(args.timeframe).upper(), 8))
    bars = load_m15_ohlcv(args.bars)
    cuts = smoke_windows(
        bars,
        timeframe=args.timeframe,
        n_windows=int(args.n_windows),
        lookback_bars=int(args.lookback_bars),
    )
    if not cuts:
        raise SystemExit("no closed-bar windows with full lookback")

    kwargs = predictor_kwargs_from_config(cfg)
    if args.device:
        kwargs["device"] = args.device
    t0 = time.perf_counter()
    predictor = load_predictor(local_files_only=bool(args.offline), **kwargs)
    load_s = time.perf_counter() - t0

    rows: list[dict[str, Any]] = []
    for cut in cuts:
        window = lookback_ohlcv(
            bars,
            source_bar_close=cut,
            timeframe=args.timeframe,
            lookback_bars=int(args.lookback_bars),
        )
        causal = lookback_is_causal(
            window, source_bar_close=cut, timeframe=args.timeframe
        )
        if not causal:
            raise SystemExit(f"look-ahead at {cut}")
        started = time.perf_counter()
        cloud = cloud_for_closed_bar(
            bars,
            source_bar_close=cut,
            timeframe=args.timeframe,
            predictor=predictor,
            lookback_bars=int(args.lookback_bars),
            n_paths=int(args.n_paths),
            pred_len=pred_len,
            temperature=float(model.get("temperature") or 1.0),
            top_p=float(model.get("top_p") or 0.9),
        )
        elapsed = time.perf_counter() - started
        if cloud is None:
            raise SystemExit(f"empty cloud at {cut}")
        terminals = np.asarray(cloud["terminal_close"], dtype=float)
        if terminals.shape != (int(args.n_paths),) or not np.isfinite(terminals).all():
            raise SystemExit(f"bad terminals at {cut}: {terminals}")
        feats = features_from_cloud(
            last_close=float(cloud["last_close"]),
            terminal_close=cloud["terminal_close"],
            terminal_volume=cloud["terminal_volume"],
            lookback_volume_median=float(cloud["lookback_volume_median"] or 0.0),
            lookback_atr=float(cloud["lookback_atr"] or 0.0),
            side="LONG",
        )
        rows.append(
            {
                "source_bar_close": str(pd_ts(cut)),
                "last_close": cloud["last_close"],
                "lookback_bars": cloud["lookback_bars"],
                "n_paths": int(args.n_paths),
                "unique_terminals": int(len(set(np.round(terminals, 8).tolist()))),
                "elapsed_s": round(elapsed, 3),
                **{k: _json_num(v) for k, v in feats.items()},
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "artifact_id": "logic1_kronos_open_prior_smoke",
        "generated_at": _utc(),
        "checkpoint": kwargs["checkpoint"],
        "tokenizer": kwargs["tokenizer"],
        "hf_cache": str(HF_CACHE),
        "offline": bool(args.offline),
        "n_windows": len(rows),
        "n_paths": int(args.n_paths),
        "lookback_bars": int(args.lookback_bars),
        "pred_len": pred_len,
        "load_predictor_s": round(load_s, 3),
        "mean_window_s": round(float(np.mean([r["elapsed_s"] for r in rows])), 3),
        "all_finite": True,
        "all_causal": True,
        "windows": rows,
    }
    out = OUT_DIR / "phase3_m15_smoke.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "windows"}, indent=2))
    print(f"wrote {out}")
    return 0


def pd_ts(value: Any) -> str:
    text = str(value)
    return text.replace("+00:00", "Z")


def _json_num(value: Any) -> Any:
    if isinstance(value, (bool, str)):
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if not np.isfinite(num):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    return round(num, 6)


if __name__ == "__main__":
    raise SystemExit(main())
