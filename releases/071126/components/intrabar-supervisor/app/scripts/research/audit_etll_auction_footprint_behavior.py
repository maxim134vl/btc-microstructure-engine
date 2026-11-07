#!/usr/bin/env python3
"""June Auction behavior on footprint VR vs V2 / tip-aggregate.

Focus: how AES2 phases move with footprint evidence — not VSA eight, not flat AGREE.
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
DEFAULT_OUT = ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_june_footprint"
DEFAULT_FP_VR = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_tip/footprint_202606/volume_response_state_footprint.parquet"
)
DEFAULT_FP_FEAT = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_tip/footprint_202606/m15_footprint_features.parquet"
)
DEFAULT_V2_GATE = (
    ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/june_pilot_bc/gate_note.json"
)
DEFAULT_TIP_GATE = (
    ROOT
    / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_june/gate_note_tip_candidates.json"
)

STOPPING = {"UP_STOPPING_CANDIDATE", "DOWN_STOPPING_CANDIDATE"}
EXTREME = {"EXTREME_UP_PARTICIPATION", "EXTREME_DOWN_PARTICIPATION"}
DETER = {"UP_CONTINUATION_DETERIORATING", "DOWN_CONTINUATION_DETERIORATING"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _scan_aes(replay: Path) -> dict[str, Any]:
    mem = replay / "memory"
    phase = Counter()
    stop_e = extreme_e = promote = before_bal = 0
    reasons = Counter()
    transitions: list[dict] = []
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
            stop_e += 1
            transitions.append(
                {
                    "ts": row.get("timestamp"),
                    "from": prev,
                    "to": ns,
                    "reasons": rcs,
                    "kind": "STOPPING_ENTRY",
                }
            )
        if ns in EXTREME and prev != ns:
            extreme_e += 1
            if len(transitions) < 40 or "EXTREME" in ",".join(rcs):
                transitions.append(
                    {
                        "ts": row.get("timestamp"),
                        "from": prev,
                        "to": ns,
                        "reasons": rcs,
                        "kind": "EXTREME_ENTRY",
                    }
                )
        if "SAME_BAR_STOPPING_PROMOTE" in rcs:
            promote += 1
        if "STOPPING_BEFORE_BALANCE_ESCAPE" in rcs:
            before_bal += 1
    return {
        "phase_top": [{"key": k, "count": int(v)} for k, v in phase.most_common(20)],
        "stopping_entries": stop_e,
        "extreme_entries": extreme_e,
        "same_bar_promote": promote,
        "stopping_before_balance_escape": before_bal,
        "stopping_phase_bars": int(sum(phase[p] for p in STOPPING)),
        "extreme_phase_bars": int(sum(phase[p] for p in EXTREME)),
        "deteriorating_phase_bars": int(sum(phase[p] for p in DETER)),
        "reason_hits": {
            k: int(v)
            for k, v in reasons.items()
            if any(x in k for x in ("STOP", "EXTREME", "SAME_BAR", "CLIMAX", "EXHAUST"))
        },
        "sample_transitions": transitions[:25],
    }


def _episodes(
    *,
    replay: Path,
    fp_vr: Path,
    fp_feat: Path,
    n: int = 8,
) -> list[dict]:
    """Concrete bars: footprint STOPPING/CLIMACTIC + AES phase at that bar."""
    vr = pd.read_parquet(fp_vr)
    vr["timestamp"] = pd.to_datetime(vr["timestamp"], utc=True)
    feat = pd.read_parquet(fp_feat) if fp_feat.exists() else None
    if feat is not None:
        feat["timestamp"] = pd.to_datetime(feat["timestamp"], utc=True)
        feat = feat.set_index("timestamp")

    ep = {}
    for row in _iter_jsonl(replay / "memory" / "tf_episode_memory.jsonl"):
        if str(row.get("timeframe") or "") != "M15":
            continue
        ep[str(row.get("timestamp") or "")] = {
            "family": row.get("auction_family"),
            "phase": row.get("episode_phase"),
        }

    interesting = vr[
        (vr["volume_event"] == "STOPPING_VOLUME")
        | (vr["participation_state"] == "CLIMACTIC_PARTICIPATION")
        | (vr["unfinished_auction"] == True)  # noqa: E712
    ].copy()
    interesting = interesting.sort_values("relative_volume", ascending=False).head(n * 3)

    out = []
    for r in interesting.itertuples():
        key = r.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        aes = ep.get(key) or {}
        # prefer stopping/climactic that land on AES extreme/deter/stopping
        phase = str(aes.get("phase") or "")
        score = 0
        if r.volume_event == "STOPPING_VOLUME":
            score += 3
        if r.participation_state == "CLIMACTIC_PARTICIPATION":
            score += 2
        if phase in STOPPING | EXTREME | DETER:
            score += 4
        fp = {}
        if feat is not None and r.timestamp in feat.index:
            fr = feat.loc[r.timestamp]
            if isinstance(fr, pd.DataFrame):
                fr = fr.iloc[0]
            fp = {
                "poc_position": float(fr.get("fp_poc_position") or 0),
                "vol_at_high": float(fr.get("fp_vol_at_high_share") or 0),
                "vol_at_low": float(fr.get("fp_vol_at_low_share") or 0),
                "delta_eff": float(fr.get("fp_delta_efficiency") or 0),
                "upper_rej": bool(fr.get("fp_upper_rejection")),
                "lower_rej": bool(fr.get("fp_lower_rejection")),
                "unfinished": bool(fr.get("fp_unfinished")),
            }
        out.append(
            {
                "score": score,
                "timestamp": key,
                "fp_volume_event": r.volume_event,
                "fp_participation": r.participation_state,
                "fp_climax": r.climax_state,
                "fp_effort": round(float(r.effort_score), 3),
                "fp_result": round(float(r.result_score), 3),
                "fp_details": fp,
                "aes_family": aes.get("family"),
                "aes_phase": aes.get("phase"),
                "story_ru": _story(r.volume_event, r.participation_state, phase, fp),
            }
        )
    out.sort(key=lambda x: -x["score"])
    # unique timestamps
    seen = set()
    uniq = []
    for e in out:
        if e["timestamp"] in seen:
            continue
        seen.add(e["timestamp"])
        uniq.append({k: v for k, v in e.items() if k != "score"})
        if len(uniq) >= n:
            break
    return uniq


def _story(ve: str, part: str, phase: str, fp: dict) -> str:
    bits = []
    if ve == "STOPPING_VOLUME":
        bits.append("footprint STOPPING (объём на краю + rejection/слабый delta)")
    if part == "CLIMACTIC_PARTICIPATION":
        bits.append("CLIMACTIC participation")
    if fp.get("unfinished"):
        bits.append("POC не принят close")
    if fp.get("vol_at_high", 0) >= 0.28:
        bits.append(f"vol@high={fp['vol_at_high']:.2f}")
    if fp.get("vol_at_low", 0) >= 0.28:
        bits.append(f"vol@low={fp['vol_at_low']:.2f}")
    bits.append(f"AES→{phase or 'n/a'}")
    return "; ".join(bits)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--fp-vr", type=Path, default=DEFAULT_FP_VR)
    parser.add_argument("--fp-feat", type=Path, default=DEFAULT_FP_FEAT)
    parser.add_argument("--v2-gate", type=Path, default=DEFAULT_V2_GATE)
    parser.add_argument("--tip-gate", type=Path, default=DEFAULT_TIP_GATE)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    aes = _scan_aes(args.replay_root)
    fp_sum = {}
    sp = args.out_dir / "footprint_volume_response_summary.json"
    if sp.exists():
        fp_sum = json.loads(sp.read_text())
    v2 = json.loads(args.v2_gate.read_text()) if args.v2_gate.exists() else {}
    tip = json.loads(args.tip_gate.read_text()) if args.tip_gate.exists() else {}

    v2_stop = 4
    if isinstance(v2.get("stopping_entries_audit"), dict):
        v2_stop = int(v2["stopping_entries_audit"].get("entries") or 0)
    v2_ext = int(v2.get("extreme_entries") or 0)
    tip_stop = int((tip.get("aes_tip_replay") or {}).get("stopping_entries") or tip.get("compare_vs_v2_june_bc", {}).get("tip_stopping_entries") or 0)
    tip_ext = int((tip.get("aes_tip_replay") or {}).get("extreme_entries") or tip.get("compare_vs_v2_june_bc", {}).get("tip_extreme_entries") or 0)

    episodes = _episodes(replay=args.replay_root, fp_vr=args.fp_vr, fp_feat=args.fp_feat, n=8)

    report = {
        "generated_at": _utc_now(),
        "stage": "ETLL_JUNE_AUCTION_FOOTPRINT_BEHAVIOR",
        "fidelity": "PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1",
        "replay": str(args.replay_root),
        "footprint_vr_summary": fp_sum,
        "aes_footprint_replay": aes,
        "compare": {
            "v2_june_bc_stopping_entries": v2_stop,
            "tip_aggregate_stopping_entries": tip_stop,
            "footprint_stopping_entries": aes["stopping_entries"],
            "v2_june_bc_extreme_entries": v2_ext,
            "tip_aggregate_extreme_entries": tip_ext,
            "footprint_extreme_entries": aes["extreme_entries"],
        },
        "episodes": episodes,
        "read_ru": (
            "Смотрим, как AES2 реагирует на exact footprint (POC/edge volume/rejection), "
            "не на классическую VSA-восьмёрку. Сравнение — с V2 June B+C и tip-aggregate June."
        ),
    }
    (args.out_dir / "behavior_note_footprint.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )

    md = [
        "# June Auction + Footprint — поведение",
        "",
        f"Replay: `{args.replay_root}`",
        f"Fidelity: `PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1`",
        "",
        "## Footprint → AES labels (вход)",
        f"- STOPPING_VOLUME bars: {fp_sum.get('stopping_volume_bars')}",
        f"- CLIMACTIC bars: {fp_sum.get('climactic_participation_bars')}",
        f"- unfinished (POC≠close): {fp_sum.get('unfinished_bars')}",
        "",
        "## AES2 entries (June)",
        f"| источник | stopping entries | extreme entries |",
        f"|---|---:|---:|",
        f"| V2 June B+C | {v2_stop} | {v2_ext} |",
        f"| Tip aggregate | {tip_stop} | {tip_ext} |",
        f"| **Footprint** | **{aes['stopping_entries']}** | **{aes['extreme_entries']}** |",
        "",
        f"- same_bar_promote: {aes['same_bar_promote']}",
        f"- stopping_before_balance_escape: {aes['stopping_before_balance_escape']}",
        "",
        "## Эпизоды (footprint сигнал → AES фаза)",
        "",
    ]
    for e in episodes:
        md.append(f"### `{e['timestamp']}`")
        md.append(f"- {e['story_ru']}")
        md.append(
            f"- VR: event=`{e['fp_volume_event']}` part=`{e['fp_participation']}` "
            f"climax=`{e['fp_climax']}` effort={e['fp_effort']} result={e['fp_result']}"
        )
        md.append(f"- AES: `{e['aes_family']}` / `{e['aes_phase']}`")
        if e.get("fp_details"):
            md.append(f"- FP detail: `{json.dumps(e['fp_details'])}`")
        md.append("")
    md += [
        "## Reason codes (фильтр STOP/EXTREME)",
        "```json",
        json.dumps(aes.get("reason_hits"), indent=2),
        "```",
        "",
        report["read_ru"],
        "",
    ]
    (args.out_dir / "FOOTPRINT_AUCTION_BEHAVIOR.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"compare": report["compare"], "n_episodes": len(episodes)},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
