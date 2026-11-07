#!/usr/bin/env python3
"""Phase 4: Kronos-mini OPEN overlay on the running VPS paper epoch.

Uses PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442 + NeoQuasar/Kronos-mini from
the local HF cache. Does not read ETLL_HYBRID_TICK archive. Does not write
timeframe_manager. Holdout stays sealed.

  PYTHONPATH=src ./venv/bin/python scripts/research/overlay_logic1_kronos_live_epoch.py
  PYTHONPATH=src ./venv/bin/python scripts/research/overlay_logic1_kronos_live_epoch.py --skip-snapshot
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.research.logic1_kronos_live_book import (  # noqa: E402
    KLINES_DIR,
    LIVE_EPOCH_ID,
    attach_live_kronos_clouds,
    build_live_open_events,
    download_klines,
    load_klines,
    scoring_frame,
    snapshot_live_epoch,
)
from btc_ml.research.logic1_kronos_open_prior import (  # noqa: E402
    ALLOW_ALL,
    load_candidate_config,
    score_policy,
)
from btc_ml.research.logic1_kronos_runtime import load_predictor, predictor_kwargs_from_config  # noqa: E402

OUT_DIR = ROOT / "data/research/kronos/live_overlay"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def grid_policies(space: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [k for k, val in space.items() if isinstance(val, list)]
    out: list[dict[str, Any]] = []
    for combo in itertools.product(*[space[k] for k in keys]):
        policy = dict(ALLOW_ALL)
        policy.update({k: v for k, v in zip(keys, combo)})
        out.append(policy)
    return out


def ensure_klines(timeframes: list[str], *, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    bars: dict[str, pd.DataFrame] = {}
    for tf in timeframes:
        frame = load_klines(tf)
        need = frame.empty
        if not need:
            tmin = pd.to_datetime(frame["timestamp"], utc=True).min()
            tmax = pd.to_datetime(frame["timestamp"], utc=True).max()
            need = bool(tmin > start or tmax < (end - pd.Timedelta(days=2)))
        if need:
            frame = download_klines(tf, start=start, end=end)
        bars[tf] = frame
    return bars


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        num = float(value)
        return None if not np.isfinite(num) else round(num, 6)
    if value is None or isinstance(value, str):
        return value
    return str(value)


def main() -> int:
    cfg = load_candidate_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-snapshot", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--online", action="store_true", help="allow HF fetch; default uses local cache")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--n-paths", type=int, default=int(cfg["model"].get("sample_count") or 8))
    parser.add_argument("--lookback-bars", type=int, default=int(cfg["model"].get("lookback_bars") or 400))
    args = parser.parse_args()

    if str(cfg["reference_book"]["paper_epoch_id"]) != LIVE_EPOCH_ID:
        raise SystemExit(
            f"config epoch {cfg['reference_book']['paper_epoch_id']} is not the running {LIVE_EPOCH_ID}"
        )
    if "ETLL_HYBRID" in str(cfg["data_roots"].get("archive") or ""):
        # archive key may still exist as history; live overlay must not use it.
        pass

    snap = Path(args.snapshot) if args.snapshot else None
    if not args.skip_snapshot:
        snap = snapshot_live_epoch(snap)
    elif snap is None:
        snap = ROOT / "data/research/kronos/live_epoch_snapshot"
    events = build_live_open_events(snap)
    if events.empty:
        raise SystemExit("no eligible live closed OPENs")
    scored = scoring_frame(events)
    tfs = sorted(scored["timeframe"].astype(str).str.upper().unique())
    first_cut = pd.to_datetime(scored["source_bar_close_ts"], utc=True).min()
    start = first_cut - pd.Timedelta(days=80)
    end = pd.Timestamp.now(tz="UTC")
    bars_by_tf = ensure_klines(tfs, start=start, end=end)

    kwargs = predictor_kwargs_from_config(cfg)
    kwargs["device"] = args.device
    predictor = load_predictor(local_files_only=not bool(args.online), **kwargs)
    featured = attach_live_kronos_clouds(
        scored,
        bars_by_tf,
        predictor,
        lookback_bars=int(args.lookback_bars),
        n_paths=int(args.n_paths),
    )
    baseline = score_policy(featured, ALLOW_ALL, min_keep_frac=0.0)
    space = dict(cfg["policy_object"]["search_space"])
    min_keep = float(space.pop("min_keep_frac", cfg["scoring"].get("min_keep_frac") or 0.35))
    ranked: list[dict[str, Any]] = []
    for policy in grid_policies(space):
        result = score_policy(featured, policy, min_keep_frac=min_keep)
        ranked.append({"policy": policy, **result})
    ranked.sort(key=lambda row: (row.get("delta_total_r") is None, -(row.get("delta_total_r") or -1e9)))
    legal = [row for row in ranked if row.get("rejected") is None]
    best = legal[0] if legal else ranked[0]
    walkforward_possible = len(featured) >= 200
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_path = OUT_DIR / "live_open_matrix.parquet"
    featured = featured.copy()
    if "reason_codes" in featured.columns:
        featured["reason_codes"] = featured["reason_codes"].map(
            lambda v: json.dumps(v) if not isinstance(v, str) else v
        )
    featured.to_parquet(matrix_path, index=False)
    report = {
        "artifact_id": "logic1_kronos_live_overlay",
        "generated_at": _utc(),
        "paper_epoch_id": LIVE_EPOCH_ID,
        "checkpoint": kwargs["checkpoint"],
        "snapshot": str(snap),
        "klines": str(KLINES_DIR),
        "n_closed_eligible": int(len(events)),
        "n_scored": int(len(featured)),
        "n_instant_protective_excluded": int(events["instant_protective_bug"].sum()) if "instant_protective_bug" in events.columns else 0,
        "kronos_ok_frac": round(float(featured["kronos_ok"].mean()), 4) if len(featured) else 0.0,
        "walkforward_possible": walkforward_possible,
        "holdout": "SEALED_NOT_OPENED",
        "etll_archive_used": False,
        "baseline": baseline,
        "best": best,
        "win_delta_r": cfg["scoring"]["win_delta_r"],
        "declared_win": bool(
            walkforward_possible
            and best.get("rejected") is None
            and float(best.get("delta_total_r") or 0) > float(cfg["scoring"]["win_delta_r"])
        ),
        "top5": ranked[:5],
        "timeframes": featured["timeframe"].astype(str).value_counts().to_dict(),
        "matrix": str(matrix_path),
    }
    out = OUT_DIR / "phase4_live_overlay.json"
    out.write_text(json.dumps(json_ready(report), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "top5"}, indent=2, default=str))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
