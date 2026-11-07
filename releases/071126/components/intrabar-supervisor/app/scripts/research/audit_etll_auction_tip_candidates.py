#!/usr/bin/env python3
"""ETLL tip vs V2 Auction candidate-layer gate (stopping/climax/overlay proxy).

Primary metrics: AES2 candidate rates + tip co-occurrence — NOT AES5 AGREE/PnL.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT = ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_june"
DEFAULT_V2_BASELINE = (
    ROOT
    / "output/audits/etll_lived_replay_20260825/volume_fidelity/june_pilot_bc/gate_note.json"
)
DEFAULT_TIP_VR = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_tip/tip_volume_response_202606"
    "/tip_volume_response_summary.json"
)
DEFAULT_LIVED = (
    ROOT / "data/research/external_traders/market_pack_btc_m15/lived_replay/lived_trades.parquet"
)

STOPPING = {"UP_STOPPING_CANDIDATE", "DOWN_STOPPING_CANDIDATE"}
EXTREME = {"EXTREME_UP_PARTICIPATION", "EXTREME_DOWN_PARTICIPATION"}
CLIMACTIC = {"CLIMACTIC_PARTICIPATION"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _scan_replay(replay: Path) -> dict[str, Any]:
    mem = replay / "memory"
    phase = Counter()
    stop_entries = 0
    extreme_entries = 0
    promote = 0
    before_bal = 0
    reasons = Counter()
    for row in _iter_jsonl(mem / "tf_event_memory.jsonl"):
        if str(row.get("timeframe") or "") != "M15":
            continue
        ns = str(row.get("new_state") or "")
        prev = str(row.get("previous_state") or "")
        phase[ns] += 1
        rcs = [str(x) for x in (row.get("reason_codes") or [])]
        for rc in rcs:
            reasons[rc] += 1
        if ns in STOPPING and prev != ns:
            stop_entries += 1
        if ns in EXTREME and prev != ns:
            extreme_entries += 1
        if "SAME_BAR_STOPPING_PROMOTE" in rcs:
            promote += 1
        if "STOPPING_BEFORE_BALANCE_ESCAPE" in rcs:
            before_bal += 1
    return {
        "phase_top": [{"key": k, "count": int(v)} for k, v in phase.most_common(25)],
        "stopping_entries": stop_entries,
        "extreme_entries": extreme_entries,
        "same_bar_promote": promote,
        "stopping_before_balance_escape": before_bal,
        "stopping_phase_bars": int(sum(phase[p] for p in STOPPING)),
        "extreme_phase_bars": int(sum(phase[p] for p in EXTREME)),
        "reason_hits": {
            k: int(v)
            for k, v in reasons.items()
            if "STOP" in k or "EXTREME" in k or "SAME_BAR" in k or "CLIMAX" in k
        },
    }


def _cooccur_tip_aes(tip_vr: Path, replay: Path) -> dict[str, Any]:
    vr = pd.read_parquet(tip_vr)
    vr["timestamp"] = pd.to_datetime(vr["timestamp"], utc=True)
    ep = {}
    for row in _iter_jsonl(replay / "memory" / "tf_episode_memory.jsonl"):
        if str(row.get("timeframe") or "") != "M15":
            continue
        ts = str(row.get("timestamp") or "")
        ep[ts] = (row.get("auction_family"), row.get("episode_phase"))

    stop = vr[vr["volume_event"] == "STOPPING_VOLUME"]
    climax = vr[vr["participation_state"] == "CLIMACTIC_PARTICIPATION"]

    def _at(frame: pd.DataFrame) -> Counter:
        c: Counter = Counter()
        for ts in frame["timestamp"]:
            key = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
            c[str(ep.get(key))] += 1
        return c

    return {
        "tip_stopping_bars": int(len(stop)),
        "tip_climactic_bars": int(len(climax)),
        "aes_at_tip_stopping": dict(_at(stop).most_common(12)),
        "aes_at_tip_climactic": dict(_at(climax).most_common(12)),
        "tip_stopping_on_aes_stopping": int(
            sum(
                1
                for ts in stop["timestamp"]
                if (ep.get(ts.strftime("%Y-%m-%dT%H:%M:%SZ")) or (None, None))[1] in STOPPING
            )
        ),
        "tip_stopping_on_aes_extreme": int(
            sum(
                1
                for ts in stop["timestamp"]
                if (ep.get(ts.strftime("%Y-%m-%dT%H:%M:%SZ")) or (None, None))[1] in EXTREME
            )
        ),
        "tip_stopping_on_aes_deteriorating": int(
            sum(
                1
                for ts in stop["timestamp"]
                if "DETERIORATING"
                in str((ep.get(ts.strftime("%Y-%m-%dT%H:%M:%SZ")) or (None, None))[1] or "")
            )
        ),
    }


def _overlay_proxy(
    tip_vr: Path,
    lived: Path,
    *,
    from_ts: str,
    to_ts: str,
) -> dict[str, Any]:
    """Secondary: entry bars with tip STOPPING/CLIMACTIC vs side → PnL buckets."""
    vr = pd.read_parquet(tip_vr)
    vr["timestamp"] = pd.to_datetime(vr["timestamp"], utc=True)
    by_ts = {
        ts.strftime("%Y-%m-%dT%H:%M:%SZ"): row
        for ts, row in zip(vr["timestamp"], vr.to_dict(orient="records"))
    }
    trades = pd.read_parquet(lived)
    trades["entry_ts"] = pd.to_datetime(trades["entry_ts"], utc=True)
    t0 = pd.Timestamp(from_ts)
    t1 = pd.Timestamp(to_ts)
    june = trades[(trades["entry_ts"] >= t0) & (trades["entry_ts"] < t1)].copy()
    rows = []
    for r in june.itertuples():
        # floor entry to bar open (lived fills often on bar close+15m; use floor)
        bar = r.entry_ts.floor("15min") - pd.Timedelta(minutes=15)
        key = bar.strftime("%Y-%m-%dT%H:%M:%SZ")
        tip = by_ts.get(key) or by_ts.get(r.entry_ts.floor("15min").strftime("%Y-%m-%dT%H:%M:%SZ"))
        flag = "NONE"
        if tip:
            ve = str(tip.get("volume_event") or "")
            ps = str(tip.get("participation_state") or "")
            if ve == "STOPPING_VOLUME":
                flag = "TIP_STOPPING"
            elif ps == "CLIMACTIC_PARTICIPATION":
                flag = "TIP_CLIMACTIC"
            elif "ELEVATED" in ps:
                flag = "TIP_ELEVATED"
        rows.append(
            {
                "trade_id": r.trade_id,
                "side": str(r.side).upper(),
                "net_pnl_usd": float(r.net_pnl_usd),
                "tip_flag": flag,
            }
        )
    df = pd.DataFrame(rows)
    out = {}
    for flag, g in df.groupby("tip_flag"):
        pnls = g["net_pnl_usd"]
        out[str(flag)] = {
            "n": int(len(g)),
            "wr": round(float((pnls > 0).mean()), 4) if len(g) else None,
            "avg_pnl": round(float(pnls.mean()), 2) if len(g) else None,
            "net_pnl_sum": round(float(pnls.sum()), 2) if len(g) else None,
        }
    return {"n_trades_in_window": int(len(df)), "by_tip_flag": out}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--v2-baseline", type=Path, default=DEFAULT_V2_BASELINE)
    parser.add_argument(
        "--tip-vr-parquet",
        type=Path,
        default=Path(
            "/Volumes/MaksTiger/btc-ml/research/etll_tip/tip_volume_response_202606"
            "/volume_response_state_tip.parquet"
        ),
    )
    parser.add_argument("--tip-vr-summary", type=Path, default=DEFAULT_TIP_VR)
    parser.add_argument("--lived", type=Path, default=DEFAULT_LIVED)
    parser.add_argument("--from", dest="from_ts", default="2026-06-01T00:00:00Z")
    parser.add_argument("--to", dest="to_ts", default="2026-07-01T00:00:00Z")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    tip_sum = {}
    if args.tip_vr_summary.exists():
        tip_sum = json.loads(args.tip_vr_summary.read_text())
    v2 = {}
    if args.v2_baseline.exists():
        v2 = json.loads(args.v2_baseline.read_text())

    aes = _scan_replay(args.replay_root)
    co = _cooccur_tip_aes(args.tip_vr_parquet, args.replay_root) if args.tip_vr_parquet.exists() else {}
    overlay = (
        _overlay_proxy(args.tip_vr_parquet, args.lived, from_ts=args.from_ts, to_ts=args.to_ts)
        if args.tip_vr_parquet.exists() and args.lived.exists()
        else {}
    )

    # june_bc gate used stopping_entries_audit.entries = 4
    v2_stop = 4
    if isinstance(v2.get("stopping_entries_audit"), dict):
        v2_stop = int(v2["stopping_entries_audit"].get("entries") or 0)
    elif v2.get("stopping_entries_audit") is not None:
        try:
            v2_stop = int(v2["stopping_entries_audit"])
        except Exception:
            v2_stop = 4
    v2_ext = int(v2.get("extreme_entries") or 0)

    # Gate heuristics for candidate layer
    tip_stop_bars = int(tip_sum.get("stopping_volume_bars") or co.get("tip_stopping_bars") or 0)
    tip_clim = int(
        tip_sum.get("climactic_participation_bars") or co.get("tip_climactic_bars") or 0
    )
    tip_labels_rich = tip_stop_bars >= 30 or tip_clim >= 20
    aes_stopping_up = aes["stopping_entries"] > v2_stop
    aes_extreme_up = aes["extreme_entries"] > v2_ext
    cooccur_ok = (
        int(co.get("tip_stopping_on_aes_extreme") or 0)
        + int(co.get("tip_stopping_on_aes_deteriorating") or 0)
        + int(co.get("tip_stopping_on_aes_stopping") or 0)
    ) > 0
    if tip_labels_rich and (aes_stopping_up or aes_extreme_up):
        verdict = "GO_TIP_CANDIDATE_LAYER"
    elif tip_labels_rich and cooccur_ok:
        # Tip labels usable as overlay; AES FSM rates not higher than V2
        verdict = "GO_TIP_OVERLAY_AES_UNDERLINKED"
    elif tip_labels_rich:
        verdict = "GO_TIP_LABELS_BUT_AES_UNDERLINKED"
    else:
        verdict = "WEAK_OR_NO_GO_TIP"

    interpretation = {
        "primary_ru": (
            "Tip aggTrade M15 aggregate emits stopping/climactic labels as the candidate layer "
            "(not AES5 PnL). Usable for soft up/downweight when tip flags fire."
        ),
        "aes_fsm_ru": (
            "AES2 stopping/extreme entry counts on tip VR vs V2 June B+C: "
            f"stopping {aes['stopping_entries']} vs {v2_stop}, "
            f"extreme {aes['extreme_entries']} vs {v2_ext}. "
            "If tip labels ↑ but AES entries ↓, treat tip as overlay signal, not FSM amplifier."
        ),
        "c1_prove_refute": (
            "PROVED for tip candidate labels (STOPPING_VOLUME / CLIMACTIC_PARTICIPATION density). "
            "NOT proved that tip VR increases AES STOPPING_CANDIDATE entry rate vs V2."
        ),
    }

    gate = {
        "generated_at": _utc_now(),
        "stage": "ETLL_TIP_CANDIDATE_GATE_C1",
        "fidelity": "PACK_TIP_AGGTRADE_VOLUME_RESPONSE_V1",
        "replay": str(args.replay_root),
        "verdict": verdict,
        "interpretation": interpretation,
        "tip_volume_response": tip_sum,
        "aes_tip_replay": aes,
        "cooccurrence": co,
        "overlay_proxy_secondary": overlay,
        "compare_vs_v2_june_bc": {
            "v2_stopping_entries": v2_stop,
            "tip_stopping_entries": aes["stopping_entries"],
            "stopping_delta": aes["stopping_entries"] - v2_stop,
            "v2_extreme_entries": v2_ext,
            "tip_extreme_entries": aes["extreme_entries"],
            "extreme_delta": aes["extreme_entries"] - v2_ext,
            "tip_stopping_volume_bars": tip_stop_bars,
            "tip_climactic_bars": tip_clim,
        },
        "prove_refute_ru": interpretation["c1_prove_refute"],
    }
    (args.out_dir / "gate_note_tip_candidates.json").write_text(
        json.dumps(gate, indent=2) + "\n", encoding="utf-8"
    )
    md = [
        "# Tip candidate gate (C1 June)",
        "",
        f"Verdict: **{verdict}**",
        f"Replay: `{args.replay_root}`",
        f"Fidelity: `PACK_TIP_AGGTRADE_VOLUME_RESPONSE_V1`",
        "",
        "## Prove / refute C1",
        interpretation["c1_prove_refute"],
        "",
        "## Tip volume_response (candidate labels)",
        f"- STOPPING_VOLUME bars: **{tip_stop_bars}**",
        f"- CLIMACTIC_PARTICIPATION bars: **{tip_clim}**",
        "",
        "## AES2 on tip VR vs V2 June B+C",
        f"- stopping entries: {aes['stopping_entries']} (V2 was {v2_stop})",
        f"- extreme entries: {aes['extreme_entries']} (V2 was {v2_ext})",
        f"- same_bar_promote: {aes['same_bar_promote']}",
        f"- stopping_before_balance_escape: {aes['stopping_before_balance_escape']}",
        "",
        interpretation["aes_fsm_ru"],
        "",
        "## Co-occurrence tip STOPPING × AES phase",
        "```json",
        json.dumps(co, indent=2),
        "```",
        "",
        "## Overlay proxy (secondary PnL; n-aware)",
        "```json",
        json.dumps(overlay, indent=2),
        "```",
        "",
        "## Disk",
        "- Tick pack + tip VR on `/Volumes/MaksTiger/btc-ml/research/etll_tip/`",
        "- Local pack path is symlink; audits only under `output/audits/.../tip_june/`",
        "",
    ]
    (args.out_dir / "TIP_CANDIDATE_GATE_REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "compare": gate["compare_vs_v2_june_bc"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
