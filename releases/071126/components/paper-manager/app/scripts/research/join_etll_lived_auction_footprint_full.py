#!/usr/bin/env python3
"""Step C: join lived trades × Shadow Auction structure × footprint VR × price path.

Full ETLL span. Writes under tip_full_footprint/join/.
Goal: logical links between Auction sequences, footprint labels, and lived PnL —
not classical VSA, not flat stopping metrics.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIVED = (
    ROOT / "data/research/external_traders/market_pack_btc_m15/lived_replay/lived_trades.parquet"
)
DEFAULT_STRUCTURE = (
    ROOT
    / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_full_footprint"
    / "structure/auction_structure_x_lived.parquet"
)
DEFAULT_REPLAY = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/lived_replay/shadow_lab"
    / "paper_repo/data/trading/shadow_auction/replay"
    / "RPL_d7f101b055337d97_20260830T193340"
)
DEFAULT_FP_VR = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_tip/footprint_full_etll/volume_response_state_footprint.parquet"
)
DEFAULT_CANDLE = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/context/candle_structure_memory.parquet"
)
DEFAULT_OUT = (
    ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_full_footprint/join"
)

STOPPING = {"UP_STOPPING_CANDIDATE", "DOWN_STOPPING_CANDIDATE"}
EXTREME = {"EXTREME_UP_PARTICIPATION", "EXTREME_DOWN_PARTICIPATION"}
INTERESTING = STOPPING | EXTREME | {
    "FAILED_UPSIDE_BREAK",
    "FAILED_DOWNSIDE_BREAK",
    "ACCEPTANCE_ABOVE",
    "ACCEPTANCE_BELOW",
    "RESOLUTION_UP",
    "RESOLUTION_DOWN",
    "UP_CONTINUATION_DETERIORATING",
    "DOWN_CONTINUATION_DETERIORATING",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_m15_phases(replay: Path) -> pd.DataFrame:
    """Compact M15 phase timeline from hierarchy (one row per bar)."""
    path = replay / "memory" / "hierarchy_memory.jsonl"
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            ts = o.get("m15_timestamp") or o.get("timestamp")
            if not ts:
                continue
            rows.append(
                {
                    "timestamp": ts,
                    "m15_family": o.get("m15_family"),
                    "m15_phase": o.get("m15_phase"),
                    "m30_phase": o.get("m30_phase"),
                    "h1_phase": o.get("h1_phase"),
                    "h4_phase": o.get("h4_phase"),
                }
            )
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return df.reset_index(drop=True)


def _sequence_around(
    phases: pd.DataFrame, *, entry: pd.Timestamp, bars_before: int = 8, bars_after: int = 8
) -> dict[str, Any]:
    if phases.empty or pd.isna(entry):
        return {
            "seq_before": [],
            "seq_after": [],
            "interesting_before": [],
            "interesting_after": [],
            "phase_at_entry": None,
            "family_at_entry": None,
        }
    # nearest bar <= entry
    idx = phases["timestamp"].searchsorted(entry, side="right") - 1
    if idx < 0:
        idx = 0
    lo = max(0, idx - bars_before)
    hi = min(len(phases), idx + bars_after + 1)
    window = phases.iloc[lo:hi]
    before = phases.iloc[lo : idx + 1]
    after = phases.iloc[idx : hi]
    at = phases.iloc[idx]

    def pack(frame: pd.DataFrame) -> list[dict[str, Any]]:
        out = []
        for _, r in frame.iterrows():
            out.append(
                {
                    "ts": r["timestamp"].isoformat().replace("+00:00", "Z"),
                    "family": r.get("m15_family"),
                    "phase": r.get("m15_phase"),
                }
            )
        return out

    def interesting(frame: pd.DataFrame) -> list[str]:
        return [
            f"{r['timestamp'].isoformat().replace('+00:00', 'Z')}|{r['m15_phase']}"
            for _, r in frame.iterrows()
            if str(r.get("m15_phase") or "") in INTERESTING
        ]

    return {
        "seq_before": pack(before),
        "seq_after": pack(after),
        "interesting_before": interesting(before),
        "interesting_after": interesting(after),
        "phase_at_entry": at.get("m15_phase"),
        "family_at_entry": at.get("m15_family"),
        "m30_phase_at_entry": at.get("m30_phase"),
        "h1_phase_at_entry": at.get("h1_phase"),
        "h4_phase_at_entry": at.get("h4_phase"),
        "n_interesting_before": len(interesting(before)),
        "n_interesting_after": len(interesting(after)),
    }


def _price_path(
    candle: pd.DataFrame, *, entry: pd.Timestamp, exit_ts: pd.Timestamp | None, bars: int = 8
) -> dict[str, Any]:
    if candle.empty or pd.isna(entry):
        return {}
    idx = candle["timestamp"].searchsorted(entry, side="right") - 1
    if idx < 0:
        return {}
    lo = max(0, idx - bars)
    hi = min(len(candle), idx + bars + 1)
    pre = candle.iloc[lo : idx + 1]
    post = candle.iloc[idx:hi]
    c0 = float(candle.iloc[idx]["close"])
    out: dict[str, Any] = {
        "entry_close": c0,
        "price_change_pct_before": (
            (c0 / float(pre.iloc[0]["close"]) - 1.0) * 100.0 if len(pre) else np.nan
        ),
        "price_change_pct_after": (
            (float(post.iloc[-1]["close"]) / c0 - 1.0) * 100.0 if len(post) else np.nan
        ),
        "range_pct_before": (
            (float(pre["high"].max()) - float(pre["low"].min())) / c0 * 100.0 if len(pre) else np.nan
        ),
        "range_pct_after": (
            (float(post["high"].max()) - float(post["low"].min())) / c0 * 100.0
            if len(post)
            else np.nan
        ),
    }
    if exit_ts is not None and not pd.isna(exit_ts):
        j = candle["timestamp"].searchsorted(exit_ts, side="right") - 1
        if j >= 0:
            out["exit_close"] = float(candle.iloc[j]["close"])
            out["price_change_pct_entry_to_exit"] = (out["exit_close"] / c0 - 1.0) * 100.0
    return out


def _asof_fp(fp: pd.DataFrame, entry: pd.Timestamp) -> dict[str, Any]:
    if fp.empty or pd.isna(entry):
        return {}
    idx = fp["timestamp"].searchsorted(entry, side="right") - 1
    if idx < 0:
        return {}
    r = fp.iloc[idx]
    keys = [
        "volume_event",
        "participation_state",
        "climax_state",
        "effort_result_state",
        "continuation_quality",
        "volume_class",
        "relative_volume",
        "delta_efficiency",
        "effort_score",
        "result_score",
        "unfinished_auction",
        "upper_rejection",
        "lower_rejection",
        "fp_poc_position",
        "fp_vol_at_high_share",
        "fp_vol_at_low_share",
    ]
    out = {f"fp_{k}": r[k] if k in r.index else None for k in keys}
    out["fp_bar_ts"] = r["timestamp"].isoformat().replace("+00:00", "Z")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lived", type=Path, default=DEFAULT_LIVED)
    parser.add_argument("--structure", type=Path, default=DEFAULT_STRUCTURE)
    parser.add_argument("--replay-root", type=Path, default=DEFAULT_REPLAY)
    parser.add_argument("--fp-vr", type=Path, default=DEFAULT_FP_VR)
    parser.add_argument("--candle", type=Path, default=DEFAULT_CANDLE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bars-before", type=int, default=8)
    parser.add_argument("--bars-after", type=int, default=8)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("load lived…", flush=True)
    lived = pd.read_parquet(args.lived)
    lived["entry_ts"] = pd.to_datetime(lived["entry_ts"], utc=True)
    lived["exit_ts"] = pd.to_datetime(lived["exit_ts"], utc=True)

    print("load structure join…", flush=True)
    struct = pd.read_parquet(args.structure)
    # join key: position_id preferred
    keep = [
        c
        for c in struct.columns
        if c
        in {
            "position_id",
            "trade_id",
            "coverage_status",
            "structure_source",
            "auction_family",
            "episode_phase",
            "balance_state",
            "pressure_side",
            "hold_path_label",
            "hold_path_postmortem",
            "postmortem_status",
            "retrospective_structure_label",
            "eventual_anchor_resolution",
        }
    ]
    merged = lived.merge(struct[keep], on=["position_id", "trade_id"], how="left", suffixes=("", "_s"))

    print("load footprint VR…", flush=True)
    fp = pd.read_parquet(args.fp_vr)
    fp["timestamp"] = pd.to_datetime(fp["timestamp"], utc=True)
    fp = fp.sort_values("timestamp").reset_index(drop=True)

    print("load candles…", flush=True)
    candle = pd.read_parquet(args.candle, columns=["timestamp", "open", "high", "low", "close"])
    candle["timestamp"] = pd.to_datetime(candle["timestamp"], utc=True)
    candle = candle.sort_values("timestamp").reset_index(drop=True)

    print("load M15 auction phases (hierarchy)…", flush=True)
    phases = _load_m15_phases(args.replay_root)
    print(f"phases={len(phases)} lived={len(merged)}", flush=True)

    rows: list[dict[str, Any]] = []
    for i, r in merged.iterrows():
        entry = r["entry_ts"]
        exit_ts = r.get("exit_ts")
        seq = _sequence_around(
            phases, entry=entry, bars_before=args.bars_before, bars_after=args.bars_after
        )
        price = _price_path(candle, entry=entry, exit_ts=exit_ts, bars=args.bars_before)
        fp_row = _asof_fp(fp, entry)
        side = str(r.get("side") or "")
        px_after = price.get("price_change_pct_after")
        aligned = None
        if px_after is not None and not pd.isna(px_after):
            if side.upper() == "LONG":
                aligned = bool(px_after > 0)
            elif side.upper() == "SHORT":
                aligned = bool(px_after < 0)
        rows.append(
            {
                "trade_id": r.get("trade_id"),
                "position_id": r.get("position_id"),
                "side": side,
                "entry_ts": entry.isoformat().replace("+00:00", "Z") if pd.notna(entry) else None,
                "exit_ts": (
                    exit_ts.isoformat().replace("+00:00", "Z")
                    if isinstance(exit_ts, pd.Timestamp) and pd.notna(exit_ts)
                    else None
                ),
                "net_pnl_usd": float(r["net_pnl_usd"]) if pd.notna(r.get("net_pnl_usd")) else None,
                "r_multiple": float(r["r_multiple"]) if pd.notna(r.get("r_multiple")) else None,
                "exit_reason": r.get("exit_reason"),
                "coverage_status": r.get("coverage_status"),
                "auction_family": r.get("auction_family") or seq.get("family_at_entry"),
                "episode_phase": r.get("episode_phase") or seq.get("phase_at_entry"),
                "hold_path_label": r.get("hold_path_label"),
                "hold_path_postmortem": r.get("hold_path_postmortem"),
                "postmortem_status": r.get("postmortem_status"),
                "m30_phase_at_entry": seq.get("m30_phase_at_entry"),
                "h1_phase_at_entry": seq.get("h1_phase_at_entry"),
                "h4_phase_at_entry": seq.get("h4_phase_at_entry"),
                "n_interesting_before": seq.get("n_interesting_before"),
                "n_interesting_after": seq.get("n_interesting_after"),
                "interesting_before": "|".join(seq.get("interesting_before") or []),
                "interesting_after": "|".join(seq.get("interesting_after") or []),
                "seq_before_json": json.dumps(seq.get("seq_before") or [], default=str),
                "seq_after_json": json.dumps(seq.get("seq_after") or [], default=str),
                "price_aligned_8bars_after": aligned,
                **price,
                **fp_row,
            }
        )
        if (i + 1) % 250 == 0:
            print(f"  joined {i+1}/{len(merged)}", flush=True)

    out_df = pd.DataFrame(rows)
    out_path = args.out_dir / "lived_x_auction_x_footprint.parquet"
    out_df.to_parquet(out_path, index=False)

    # summaries
    def pnl_by(col: str, top: int = 12) -> list[dict[str, Any]]:
        if col not in out_df.columns:
            return []
        g = (
            out_df.groupby(col, dropna=False)
            .agg(n=("trade_id", "count"), pnl=("net_pnl_usd", "sum"), win=("net_pnl_usd", lambda s: float((s > 0).mean())))
            .reset_index()
            .sort_values("n", ascending=False)
            .head(top)
        )
        return g.to_dict(orient="records")

    interesting_mask = (out_df["n_interesting_before"].fillna(0) > 0) | (
        out_df["fp_volume_event"].isin(
            ["STOPPING_VOLUME", "ABSORPTION_VOLUME", "EXHAUSTION_VOLUME", "CONTINUATION_VOLUME"]
        )
    )
    summary = {
        "generated_at": _utc_now(),
        "stage": "ETLL_C_LIVED_AUCTION_FOOTPRINT_JOIN",
        "fidelity": "PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1",
        "replay": str(args.replay_root),
        "n_trades": int(len(out_df)),
        "pnl_total": float(out_df["net_pnl_usd"].sum()),
        "coverage_counts": out_df["coverage_status"].value_counts(dropna=False).to_dict(),
        "fp_event_at_entry": pnl_by("fp_volume_event"),
        "fp_participation_at_entry": pnl_by("fp_participation_state"),
        "auction_family_at_entry": pnl_by("auction_family"),
        "episode_phase_at_entry_top": pnl_by("episode_phase", top=15),
        "hold_path_label": pnl_by("hold_path_label"),
        "with_interesting_auction_or_fp": {
            "n": int(interesting_mask.sum()),
            "pnl": float(out_df.loc[interesting_mask, "net_pnl_usd"].sum()),
            "win_rate": float((out_df.loc[interesting_mask, "net_pnl_usd"] > 0).mean())
            if interesting_mask.any()
            else None,
        },
        "price_align_8bars_after": {
            "n_scored": int(out_df["price_aligned_8bars_after"].notna().sum()),
            "align_rate": float(out_df["price_aligned_8bars_after"].dropna().mean())
            if out_df["price_aligned_8bars_after"].notna().any()
            else None,
        },
        "out_path": str(out_path),
        "note_ru": (
            "Стыковка lived × Auction sequences × footprint VR × цена до/после. "
            "Для wiring: смотреть interesting_before/after + fp_volume_event, не только STOPPING count."
        ),
    }
    (args.out_dir / "lived_x_auction_x_footprint_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )

    md = [
        "# C — Lived × Shadow Auction × Footprint (full span)",
        "",
        f"Replay: `{args.replay_root.name}`",
        f"Fidelity: `PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1`",
        f"Trades: **{summary['n_trades']}** | PnL sum: **{summary['pnl_total']:.1f}**",
        "",
        "## Coverage",
        "```json",
        json.dumps(summary["coverage_counts"], indent=2, default=str),
        "```",
        "",
        "## Footprint event at entry (n / pnl / win)",
        "```json",
        json.dumps(summary["fp_event_at_entry"], indent=2, default=str),
        "```",
        "",
        "## Auction family at entry",
        "```json",
        json.dumps(summary["auction_family_at_entry"], indent=2, default=str),
        "```",
        "",
        "## Interesting Auction/FP context",
        f"- trades with interesting phases before OR non-neutral FP: "
        f"**{summary['with_interesting_auction_or_fp']['n']}** "
        f"(pnl={summary['with_interesting_auction_or_fp']['pnl']:.1f}, "
        f"win={summary['with_interesting_auction_or_fp']['win_rate']})",
        f"- price aligned with side over +8 M15 bars: "
        f"**{summary['price_align_8bars_after']['align_rate']}** "
        f"(n={summary['price_align_8bars_after']['n_scored']})",
        "",
        "## Wiring hint (pre-D)",
        "- Use as **context layer**: sequence + footprint labels around lived entries.",
        "- Do not gate on STOPPING count alone (rare by design).",
        "- Next D: decide how this feeds brain/context vs entry filter.",
        "",
        f"Table: `{out_path}`",
        "",
    ]
    (args.out_dir / "C_LIVED_AUCTION_FOOTPRINT_JOIN.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )
    print(json.dumps({"n_trades": summary["n_trades"], "out": str(out_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
