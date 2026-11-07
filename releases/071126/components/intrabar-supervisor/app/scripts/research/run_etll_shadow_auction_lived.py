#!/usr/bin/env python3
"""ETLL: Shadow Auction AES6 replay on pack context + lived paper events.

Writes under data/trading/shadow_auction/etll_lived_m15_lab (AES write boundary).
Reports under pack lived_replay/shadow_lab/reports.
Does not touch live cognition or live shadow_auction/memory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.shadow_lab import (  # noqa: E402
    EPOCH_ID,
    adapt_lived_books_to_jsonl,
    ensure_lab_dirs,
    pack_paths,
)
from btc_ml.trading.shadow_auction.canonical_lifecycle import (  # noqa: E402
    iter_paper_closes,
    iter_paper_entries,
)
from btc_ml.trading.shadow_auction.replay import ReplayRunner  # noqa: E402

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"


def _link_pack_cognition(
    paths: dict[Path, Path] | dict,
    *,
    volume_response: Path | None = None,
    volume_classification: Path | None = None,
) -> None:
    """Expose pack context as paper_repo/data/cognition for AES source_adapter."""
    cog = paths["paper_repo"] / "data" / "cognition"
    cog.mkdir(parents=True, exist_ok=True)
    ctx = paths["context"]
    # Prefer explicit override (tip pilot), then AES-native V2, then thin proxy.
    if volume_response is not None and volume_response.exists():
        volume_src = volume_response
    else:
        volume_src = ctx / "volume_response_state.parquet"
        if not volume_src.exists():
            volume_src = ctx / "volume_response_state_proxy.parquet"
    class_src = None
    if volume_classification is not None and volume_classification.exists():
        class_src = volume_classification
    elif (ctx / "volume_classification_memory.parquet").exists():
        class_src = ctx / "volume_classification_memory.parquet"
    mapping = {
        "candle_structure_memory.parquet": ctx / "candle_structure_memory.parquet",
        "volume_response_state.parquet": volume_src,
    }
    if class_src is not None:
        mapping["volume_classification_memory.parquet"] = class_src
    for name, src in mapping.items():
        dest = cog / name
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        if src.exists():
            dest.symlink_to(src.resolve())


def _fidelity_label(pack_dir: Path, *, volume_response: Path | None = None) -> str:
    if volume_response is not None:
        name = volume_response.name.lower()
        path_l = str(volume_response).lower()
        if "footprint" in name or "footprint" in path_l:
            return "PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1"
        if "tip" in name:
            return "PACK_TIP_AGGTRADE_VOLUME_RESPONSE_V1"
        if volume_response.exists():
            return "PACK_CUSTOM_VOLUME_RESPONSE"
    v2 = pack_dir / "context" / "volume_response_state.parquet"
    if v2.exists():
        return "PACK_NATIVE_VOLUME_PLUS_VOLUME_RESPONSE_V2"
    return "PACK_CANDLE_STRUCTURE_PLUS_VOLUME_RESPONSE_PROXY"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--from", dest="from_ts", default="2023-12-17T00:00:00Z")
    parser.add_argument("--to", dest="to_ts", default="2026-07-25T00:00:00Z")
    parser.add_argument("--warmup-from", default=None)
    parser.add_argument("--skip-adapt", action="store_true")
    parser.add_argument("--limit-trades", type=int, default=None, help="Also limit adapted books")
    parser.add_argument(
        "--volume-response",
        type=Path,
        default=None,
        help="Override volume_response parquet (e.g. tip aggregate on MaksTiger)",
    )
    parser.add_argument(
        "--volume-classification",
        type=Path,
        default=None,
        help="Optional override for volume_classification_memory.parquet",
    )
    args = parser.parse_args()

    paths = pack_paths(args.pack_dir)
    ensure_lab_dirs(paths)
    if not args.skip_adapt:
        adapt_lived_books_to_jsonl(pack_dir=args.pack_dir, limit_trades=args.limit_trades)
    _link_pack_cognition(
        paths,
        volume_response=args.volume_response,
        volume_classification=args.volume_classification,
    )

    cfg_path = paths["lab"] / "shadow_auction_config.json"
    fidelity = _fidelity_label(args.pack_dir, volume_response=args.volume_response)
    vol_src = (
        str(args.volume_response.resolve())
        if args.volume_response and args.volume_response.exists()
        else str(
            (args.pack_dir / "context" / "volume_response_state.parquet")
            if (args.pack_dir / "context" / "volume_response_state.parquet").exists()
            else (args.pack_dir / "context" / "volume_response_state_proxy.parquet")
        )
    )
    cfg = {
        "shadow_name": "AUCTION_EPISODE_SHADOW",
        "logic_version": "AES_V1",
        "schema_version": 1,
        "observer_only": True,
        "enforcement_enabled": False,
        "storage_mode": "repo_local",
        # Relative to paper_repo (ReplayRunner.create repo=); NOT absolute nested path.
        "data_root": "data/trading/shadow_auction",
        "min_free_bytes": 0,
        "pid_file": str(paths["lab"] / "shadow_auction.pid"),
        "health_interval_s": 2.0,
        "poll_interval_s": 1.0,
        "aes2_enabled": True,
        "aes3_enabled": True,
        "aes4_enabled": True,
        "aes5_enabled": True,
        "aes2": {
            "window_bars": {"M15": 8, "M30": 8, "H1": 6, "H4": 4},
            "extreme_volume_z": 1.5,
            "strong_efficiency": 0.55,
            "weak_efficiency": 0.28,
            "strong_effort": 0.55,
            "balance_min_bars": 4,
            "balance_support_enter": 0.55,
            "balance_max_net_disp_ratio": 0.40,
            "acceptance_bars_beyond": 2,
            "reaction_retrace_ratio": 0.35,
            "deterioration_effort_rise": 0.05,
            "deterioration_result_drop": 0.05,
        },
        "aes3": {
            "stale_cadence_sec": {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400},
            "stale_multiplier": 2.0,
            "propagation_history": 16,
        },
        "aes5": {"horizon_sec": 1209600},
        "aes6": {"storage_warning_bytes": 0, "storage_critical_bytes": 0},
        "etll": {
            "pack_dir": str(args.pack_dir),
            "fidelity": fidelity,
            "external_trades_used": False,
            "volume_response_source": vol_src,
        },
    }
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    paper_repo = paths["paper_repo"]
    lifecycle_events = list(iter_paper_entries(paper_repo, epoch_id=EPOCH_ID)) + list(
        iter_paper_closes(paper_repo, epoch_id=EPOCH_ID)
    )

    # repo=paper_repo so load_m15_observations reads pack cognition symlinks and
    # ReplayRunner performs M15→HTF aggregation (skipped when observations= are passed).
    runner = ReplayRunner.create(
        repo=paper_repo,
        config_path=cfg_path,
        evaluation_from=args.from_ts,
        evaluation_to=args.to_ts,
        warmup_from=args.warmup_from or args.from_ts,
        observations=None,
        lifecycle_events=lifecycle_events,
    )
    result = runner.run()
    summary = {
        "stage": "ETLL_SHADOW_AUCTION_LIVED",
        "status": "AUCTION_REPLAY_DONE" if result.get("ok", True) else "AUCTION_REPLAY_FAILED",
        "replay": result,
        "lifecycle_event_count": len(lifecycle_events),
        "data_root": str(paths["shadow_auction"]),
        "replay_root": str(runner.replay_root),
        "config": str(cfg_path),
        "fidelity": cfg["etll"]["fidelity"],
        "external_trades_used": False,
    }
    (paths["reports"] / "shadow_auction_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0 if summary["status"] == "AUCTION_REPLAY_DONE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
