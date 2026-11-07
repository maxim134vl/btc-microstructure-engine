#!/usr/bin/env python3
"""ETLL Shadow Auction structure audit (AES2/AES3 primary; AES5 not primary).

Uses existing full-span replay memory. Does not re-run Auction.
Evaluates balance / directional / stopping / failed-break / hierarchy —
NOT final_shadow_verdict vs PnL as primary gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPLAY = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/lived_replay/shadow_lab"
    / "paper_repo/data/trading/shadow_auction/replay"
    / "RPL_b138e142ab9e5ac5_20260826T150642"
)
DEFAULT_OUT = ROOT / "output/audits/etll_lived_replay_20260825/shadow_auction_structure"
DEFAULT_LIVED = (
    ROOT / "data/research/external_traders/market_pack_btc_m15/lived_replay/lived_trades.parquet"
)

STOPPING = {"UP_STOPPING_CANDIDATE", "DOWN_STOPPING_CANDIDATE"}
EXTREME = {"EXTREME_UP_PARTICIPATION", "EXTREME_DOWN_PARTICIPATION"}
FAILED_BREAK = {"FAILED_UPSIDE_BREAK", "FAILED_DOWNSIDE_BREAK"}
ACCEPTANCE = {"ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW"}
RESOLUTION = {"RESOLUTION_UP", "RESOLUTION_DOWN"}
BALANCE_CORE = {
    "BALANCE_FORMING",
    "BALANCE_ESTABLISHED",
    "BALANCE_ROTATION",
    "BALANCE_COMPRESSION",
    "BALANCE_UPPER_PRESSURE",
    "BALANCE_LOWER_PRESSURE",
    "INTERNAL_TRANSFER_SUPPORT",
}
CONTINUATION = {
    "UP_CONTINUATION_ACCEPTED",
    "DOWN_CONTINUATION_ACCEPTED",
    "UP_PRESSURE_EXPANDING",
    "DOWN_PRESSURE_EXPANDING",
    "UP_PRESSURE_ACTIVE",
    "DOWN_PRESSURE_ACTIVE",
}
DETERIORATING = {
    "UP_CONTINUATION_DETERIORATING",
    "DOWN_CONTINUATION_DETERIORATING",
    "POST_UP_STRESS_REACTION",
    "POST_DOWN_STRESS_REACTION",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 4) if d else 0.0


def _top(counter: Counter, n: int = 25) -> list[dict[str, Any]]:
    return [{"key": k, "count": int(v)} for k, v in counter.most_common(n)]


def gate_s0(replay: Path) -> dict[str, Any]:
    mem = replay / "memory"
    files = {
        p.name: sum(1 for _ in open(p, encoding="utf-8"))
        for p in sorted(mem.glob("*.jsonl"))
    }
    # TF breakdown + lookahead from events
    tf_counts: Counter = Counter()
    lookahead = 0
    prev_ts_by_tf: dict[str, pd.Timestamp] = {}
    reason_top: Counter = Counter()
    for row in _iter_jsonl(mem / "tf_event_memory.jsonl"):
        tf = str(row.get("timeframe") or "NA")
        tf_counts[tf] += 1
        for rc in row.get("reason_codes") or []:
            reason_top[str(rc)] += 1
        ts = _parse_ts(row.get("timestamp"))
        if ts is not None and tf in prev_ts_by_tf and ts < prev_ts_by_tf[tf]:
            lookahead += 1
        if ts is not None:
            prev_ts_by_tf[tf] = ts

    cov: Counter = Counter()
    for row in _iter_jsonl(mem / "canonical_checkpoint_memory.jsonl"):
        if row.get("checkpoint_type") == "PAPER_ENTRY":
            cov[str(row.get("coverage_status") or "NA")] += 1

    return {
        "jsonl_counts": files,
        "event_tf_counts": dict(tf_counts),
        "event_lookahead_count": lookahead,
        "paper_entry_coverage": dict(cov),
        "top_reason_codes": _top(reason_top, 30),
        "pass": lookahead == 0 and files.get("tf_episode_memory.jsonl", 0) > 0,
    }


def gate_s1_atlas(replay: Path) -> dict[str, Any]:
    mem = replay / "memory"
    family_by_tf: dict[str, Counter] = defaultdict(Counter)
    phase_by_tf: dict[str, Counter] = defaultdict(Counter)
    transitions_m15: Counter = Counter()
    reasons_m15: Counter = Counter()

    # Path trackers keyed by timeframe
    last_phase: dict[str, str] = {}
    pending_stop: dict[str, dict[str, Any]] = {}
    pending_extreme: dict[str, dict[str, Any]] = {}
    pending_accept: dict[str, dict[str, Any]] = {}

    stop_outcomes: Counter = Counter()
    extreme_outcomes: Counter = Counter()
    accept_outcomes: Counter = Counter()
    balance_edges: Counter = Counter()
    failed_break_count = 0
    acceptance_count = 0
    stopping_entries = 0
    extreme_entries = 0

    n_events = 0
    for row in _iter_jsonl(mem / "tf_event_memory.jsonl"):
        n_events += 1
        tf = str(row.get("timeframe") or "NA")
        prev = str(row.get("previous_state") or "NA")
        new = str(row.get("new_state") or row.get("episode_phase") or "NA")
        fam = str(row.get("auction_family") or "NA")
        phase = str(row.get("episode_phase") or new)
        family_by_tf[tf][fam] += 1
        phase_by_tf[tf][phase] += 1

        if tf == "M15":
            transitions_m15[f"{prev}->{new}"] += 1
            for rc in row.get("reason_codes") or []:
                reasons_m15[str(rc)] += 1
            if prev in BALANCE_CORE or new in BALANCE_CORE or "BALANCE" in prev or "BALANCE" in new:
                balance_edges[f"{prev}->{new}"] += 1
            if new in FAILED_BREAK:
                failed_break_count += 1
            if new in ACCEPTANCE:
                acceptance_count += 1
                pending_accept[tf] = {"phase": new, "ts": row.get("timestamp")}
            if new in STOPPING:
                stopping_entries += 1
                pending_stop[tf] = {"phase": new, "ts": row.get("timestamp")}
            if new in EXTREME:
                extreme_entries += 1
                pending_extreme[tf] = {"phase": new, "ts": row.get("timestamp")}

            # Resolve pending stopping when we leave stopping
            if tf in pending_stop and new not in STOPPING:
                if "INVALIDAT" in " ".join(str(x) for x in (row.get("reason_codes") or [])):
                    stop_outcomes["INVALIDATED"] += 1
                elif new in BALANCE_CORE or new == "TRANSITION" or "BALANCE" in new:
                    stop_outcomes["TO_BALANCE_OR_TRANSITION"] += 1
                elif new in RESOLUTION or new in ACCEPTANCE:
                    stop_outcomes["TO_RESOLUTION_OR_ACCEPTANCE"] += 1
                elif new in CONTINUATION or new in DETERIORATING:
                    stop_outcomes["BACK_TO_DIRECTIONAL"] += 1
                else:
                    stop_outcomes[f"TO_{new}"] += 1
                del pending_stop[tf]

            if tf in pending_extreme and new not in EXTREME:
                if new in CONTINUATION:
                    extreme_outcomes["TO_CONTINUATION"] += 1
                elif new in DETERIORATING or new in STOPPING:
                    extreme_outcomes["TO_DETERIORATING_OR_STOPPING"] += 1
                elif new in BALANCE_CORE or "BALANCE" in new:
                    extreme_outcomes["TO_BALANCE"] += 1
                else:
                    extreme_outcomes[f"TO_{new}"] += 1
                del pending_extreme[tf]

            if tf in pending_accept and new not in ACCEPTANCE:
                if new in RESOLUTION:
                    accept_outcomes["TO_RESOLUTION"] += 1
                elif new in FAILED_BREAK or "FAILED" in new:
                    accept_outcomes["FALSE_ACCEPT_THEN_FAIL"] += 1
                elif new in BALANCE_CORE or "BALANCE" in new:
                    accept_outcomes["BACK_TO_BALANCE"] += 1
                else:
                    accept_outcomes[f"TO_{new}"] += 1
                del pending_accept[tf]

        last_phase[tf] = phase

    # Episode snapshot stats (M15)
    episode_family: Counter = Counter()
    episode_phase: Counter = Counter()
    n_ep_m15 = 0
    time_inside_sum = 0.0
    failed_bo_sum = 0
    failed_bd_sum = 0
    for row in _iter_jsonl(mem / "tf_episode_memory.jsonl"):
        if str(row.get("timeframe") or "") != "M15":
            continue
        n_ep_m15 += 1
        episode_family[str(row.get("auction_family") or "NA")] += 1
        episode_phase[str(row.get("episode_phase") or "NA")] += 1
        try:
            time_inside_sum += float(row.get("time_inside_ratio") or 0.0)
        except (TypeError, ValueError):
            pass
        failed_bo_sum += int(row.get("failed_breakout_count") or 0)
        failed_bd_sum += int(row.get("failed_breakdown_count") or 0)

    # Distinctiveness: not stuck on one phase
    top_phase_share = (
        episode_phase.most_common(1)[0][1] / n_ep_m15 if n_ep_m15 and episode_phase else 1.0
    )
    n_families = len([k for k, v in episode_family.items() if v > 0 and k != "NA"])
    n_transition_edges = len(transitions_m15)
    minority_structure_events = (
        stopping_entries
        + extreme_entries
        + failed_break_count
        + acceptance_count
        + sum(v for k, v in episode_phase.items() if k in CONTINUATION | DETERIORATING | RESOLUTION)
    )

    s1 = {
        "n_events_total": n_events,
        "family_by_tf": {tf: dict(c) for tf, c in family_by_tf.items()},
        "phase_by_tf_top": {
            tf: _top(c, 20) for tf, c in phase_by_tf.items()
        },
        "m15_episode": {
            "n": n_ep_m15,
            "family_counts": dict(episode_family),
            "phase_top": _top(episode_phase, 25),
            "top_phase_share": round(top_phase_share, 4),
            "n_families_present": n_families,
            "avg_time_inside_ratio": round(time_inside_sum / max(n_ep_m15, 1), 6),
            "sum_failed_breakout_count": failed_bo_sum,
            "sum_failed_breakdown_count": failed_bd_sum,
        },
        "m15_transitions_top": _top(transitions_m15, 40),
        "m15_balance_edges_top": _top(balance_edges, 30),
        "m15_reason_codes_top": _top(reasons_m15, 30),
        "stopping": {
            "entries": stopping_entries,
            "resolved_outcomes": dict(stop_outcomes),
            "still_open_at_eof": len(pending_stop),
        },
        "extreme": {
            "entries": extreme_entries,
            "next_outcomes": dict(extreme_outcomes),
            "still_open_at_eof": len(pending_extreme),
            "note": "EXTREME_* is participation flag; code says extreme alone is NOT climax/reversal",
        },
        "failed_break_vs_acceptance": {
            "failed_break_transitions": failed_break_count,
            "acceptance_transitions": acceptance_count,
            "acceptance_next_outcomes": dict(accept_outcomes),
            "still_open_accept_at_eof": len(pending_accept),
        },
    }

    # Gate heuristics (plan: distinguishable regimes + meaningful transitions;
    # dominant INTERNAL_TRANSFER_SUPPORT is a real balance substate, not a fail by itself)
    has_balance = episode_family.get("BALANCE", 0) > 0
    has_directional = (
        episode_family.get("DIRECTIONAL_UP", 0) + episode_family.get("DIRECTIONAL_DOWN", 0)
    ) > 0
    has_transition_fam = episode_family.get("TRANSITION", 0) > 0
    meaningful_paths = (failed_break_count + acceptance_count + extreme_entries + stopping_entries) > 0
    distinct = n_families >= 3 and n_transition_edges >= 10 and meaningful_paths
    s1["gate"] = {
        "distinct_regimes": distinct,
        "n_families_present": n_families,
        "n_m15_transition_edges": n_transition_edges,
        "top_phase_share": round(top_phase_share, 4),
        "minority_structure_events_proxy": int(minority_structure_events),
        "has_balance_and_directional": bool(has_balance and has_directional),
        "has_transition_family": bool(has_transition_fam),
        "stopping_observed": stopping_entries > 0,
        "failed_or_acceptance_observed": (failed_break_count + acceptance_count) > 0,
        "extreme_observed": extreme_entries > 0,
        "pass": bool(distinct and has_balance and has_directional),
        "note": (
            "High INTERNAL_TRANSFER_SUPPORT share is expected balance behavior; "
            "pass requires multi-family + multi-edge + failed_break|acceptance|extreme|stopping"
        ),
    }
    return s1


def gate_s2_hierarchy(replay: Path) -> dict[str, Any]:
    mem = replay / "memory"
    hier_state: Counter = Counter()
    conflict: Counter = Counter()
    lvs: Counter = Counter()
    prop_dir: Counter = Counter()
    relations: Counter = Counter()
    child_exh_within_parent = 0
    parent_flip_after_child_exh = 0
    samples_checked = 0

    # Simplified lead tracker: when m15 in stopping/deteriorating and h1/h4 directional same side
    pending_leads: list[dict[str, Any]] = []
    n = 0
    # Keep last parent families to detect flips
    window: list[dict[str, Any]] = []

    EXH_M15 = STOPPING | DETERIORATING | {
        "POST_UP_STRESS_REACTION",
        "POST_DOWN_STRESS_REACTION",
    }

    for row in _iter_jsonl(mem / "hierarchy_memory.jsonl"):
        n += 1
        hs = str(row.get("hierarchy_state") or "NA")
        hier_state[hs] += 1
        conflict[str(row.get("conflict_state") or "NA")] += 1
        lvs[str(row.get("local_vs_structural_state") or "NA")] += 1
        prop_dir[str(row.get("propagation_direction") or "NA")] += 1
        for key in ("m15_m30_relation", "m30_h1_relation", "h1_h4_relation"):
            relations[str(row.get(key) or "NA")] += 1

        m15_phase = str(row.get("m15_phase") or "")
        h1_fam = str(row.get("h1_family") or "")
        h4_fam = str(row.get("h4_family") or "")
        m15_fam = str(row.get("m15_family") or "")

        if m15_phase in EXH_M15 and (
            h1_fam in {"DIRECTIONAL_UP", "DIRECTIONAL_DOWN"}
            or h4_fam in {"DIRECTIONAL_UP", "DIRECTIONAL_DOWN"}
        ):
            child_exh_within_parent += 1
            pending_leads.append(
                {
                    "i": n,
                    "h1": h1_fam,
                    "h4": h4_fam,
                    "m15": m15_fam,
                }
            )

        window.append({"i": n, "h1": h1_fam, "h4": h4_fam})
        if len(window) > 64:
            window.pop(0)

        # Resolve leads: parent flip within next ~32 snapshots
        still: list[dict[str, Any]] = []
        for lead in pending_leads:
            age = n - int(lead["i"])
            if age <= 0:
                still.append(lead)
                continue
            if age > 32:
                continue  # expired without flip counted
            flipped = (h1_fam != lead["h1"] and lead["h1"] not in {"UNRESOLVED", "NA", ""}) or (
                h4_fam != lead["h4"] and lead["h4"] not in {"UNRESOLVED", "NA", ""}
            )
            if flipped:
                parent_flip_after_child_exh += 1
                samples_checked += 1
            else:
                still.append(lead)
                samples_checked += 1 if age == 32 else 0
        pending_leads = still[-200:]  # bound

    survived = relations.get("PARENT_DIRECTION_SURVIVED_CHILD_REVERSAL", 0)
    unresolved_h = hier_state.get("UNRESOLVED_HIERARCHY", 0)
    multi_balance = hier_state.get("MULTI_TF_BALANCE", 0)
    aligned = sum(v for k, v in hier_state.items() if "ALIGNED" in k)
    conflicted = hier_state.get("CONFLICTED_HIERARCHY", 0)

    s2 = {
        "n_snapshots": n,
        "hierarchy_state_counts": dict(hier_state),
        "hierarchy_state_top": _top(hier_state, 20),
        "conflict_state_counts": dict(conflict),
        "local_vs_structural_counts": dict(lvs),
        "propagation_direction_counts": dict(prop_dir),
        "pair_relations_top": _top(relations, 25),
        "lead_proxy": {
            "child_exhaustion_within_parent_snapshots": child_exh_within_parent,
            "parent_flip_within_32_after_child_exh": parent_flip_after_child_exh,
            "note": "Proxy: M15 stopping/deteriorating while H1/H4 directional; flip = parent family change",
        },
        "parent_survived_child_reversal_relation_count": survived,
    }
    informative = n > 0 and unresolved_h / n < 0.95
    has_structure = (multi_balance + aligned + conflicted) > 0
    s2["gate"] = {
        "not_mostly_unresolved": informative,
        "has_multi_tf_labels": has_structure,
        "pass": bool(informative and has_structure),
        "unresolved_share": round(unresolved_h / max(n, 1), 4),
    }
    return s2


def _asof_episode_index(replay: Path) -> tuple[list[pd.Timestamp], list[dict[str, Any]]]:
    """Build sorted M15 episode timeline for as-of join (compact fields only)."""
    mem = replay / "memory"
    stamps: list[pd.Timestamp] = []
    rows: list[dict[str, Any]] = []
    for row in _iter_jsonl(mem / "tf_episode_memory.jsonl"):
        if str(row.get("timeframe") or "") != "M15":
            continue
        ts = _parse_ts(row.get("timestamp"))
        if ts is None:
            continue
        stamps.append(ts)
        rows.append(
            {
                "timestamp": row.get("timestamp"),
                "auction_family": row.get("auction_family"),
                "episode_phase": row.get("episode_phase"),
                "balance_state": row.get("balance_state"),
                "pressure_side": row.get("pressure_side"),
                "resolution_side": row.get("resolution_side"),
                "balance_support": row.get("balance_support"),
                "up_exhaustion_support": row.get("up_exhaustion_support"),
                "down_exhaustion_support": row.get("down_exhaustion_support"),
                "failed_breakout_count": row.get("failed_breakout_count"),
                "failed_breakdown_count": row.get("failed_breakdown_count"),
                "time_inside_ratio": row.get("time_inside_ratio"),
                "shadow_episode_id": row.get("shadow_episode_id"),
            }
        )
    if stamps and any(stamps[i] > stamps[i + 1] for i in range(len(stamps) - 1)):
        order = sorted(range(len(stamps)), key=lambda i: stamps[i])
        stamps = [stamps[i] for i in order]
        rows = [rows[i] for i in order]
    return stamps, rows


def _asof_lookup(
    stamps: list[pd.Timestamp],
    rows: list[dict[str, Any]],
    ts: pd.Timestamp,
) -> dict[str, Any] | None:
    if not stamps:
        return None
    # binary search last stamp <= ts
    lo, hi = 0, len(stamps) - 1
    best = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if stamps[mid] <= ts:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if best < 0:
        return None
    return rows[best]


def _hold_path_from_episodes(
    stamps: list[pd.Timestamp],
    ep_rows: list[dict[str, Any]],
    entry_ts: pd.Timestamp | None,
    exit_ts: pd.Timestamp | None,
) -> str:
    """Scan M15 episodes in [entry, exit] for failed-break vs acceptance path."""
    if entry_ts is None:
        return "NO_ENTRY_TS"
    # find first index >= entry
    lo, hi = 0, len(stamps) - 1
    start = len(stamps)
    while lo <= hi:
        mid = (lo + hi) // 2
        if stamps[mid] < entry_ts:
            lo = mid + 1
        else:
            start = mid
            hi = mid - 1
    saw_balance = False
    saw_failed = False
    saw_accept = False
    saw_resolution = False
    end_ts = exit_ts if exit_ts is not None else entry_ts + pd.Timedelta(days=7)
    for i in range(start, len(stamps)):
        if stamps[i] > end_ts:
            break
        phase = str(ep_rows[i].get("episode_phase") or "")
        fam = str(ep_rows[i].get("auction_family") or "")
        if fam == "BALANCE" or phase in BALANCE_CORE:
            saw_balance = True
        if phase in FAILED_BREAK:
            saw_failed = True
        if phase in ACCEPTANCE:
            saw_accept = True
        if phase in RESOLUTION:
            saw_resolution = True
    if saw_failed and saw_balance:
        return "BALANCE_THEN_FAILED_BREAK"
    if (saw_accept or saw_resolution) and saw_balance:
        return "BALANCE_THEN_ACCEPTANCE_OR_RESOLUTION"
    if saw_failed:
        return "FAILED_BREAK_SEEN"
    if saw_accept or saw_resolution:
        return "ACCEPTANCE_OR_RESOLUTION_SEEN"
    if saw_balance:
        return "BALANCE_ONLY"
    return "NO_BALANCE_IN_HOLD"


def gate_s3_lived(
    replay: Path,
    lived_path: Path,
    stamps: list[pd.Timestamp],
    ep_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], pd.DataFrame]:
    mem = replay / "memory"
    lived = pd.read_parquet(lived_path)
    lived["entry_ts_norm"] = pd.to_datetime(lived["entry_ts"], utc=True)
    lived["side"] = lived["side"].astype(str).str.upper()
    # Checkpoints key by position_id (trade_id often absent on PAPER_ENTRY)
    by_pos = {
        str(r.position_id): r
        for r in lived.itertuples()
        if getattr(r, "position_id", None) is not None
    }
    by_trade = {
        str(r.trade_id): r for r in lived.itertuples() if getattr(r, "trade_id", None) is not None
    }
    # Hold-path labels from postmortem (retrospective; not live accuracy)
    pm_by_pos: dict[str, dict[str, Any]] = {}
    for row in _iter_jsonl(mem / "postmortem_memory.jsonl"):
        pid = str(row.get("position_id") or "")
        if pid:
            pm_by_pos[pid] = row

    rows_out: list[dict[str, Any]] = []
    cov: Counter = Counter()
    phase_at_entry: Counter = Counter()
    family_at_entry: Counter = Counter()
    hold_path: Counter = Counter()
    hold_path_pm: Counter = Counter()

    for ck in _iter_jsonl(mem / "canonical_checkpoint_memory.jsonl"):
        if ck.get("checkpoint_type") != "PAPER_ENTRY":
            continue
        cov[str(ck.get("coverage_status") or "NA")] += 1
        trade_id = str(ck.get("trade_id") or "")
        position_id = str(ck.get("position_id") or "")
        lived_row = by_pos.get(position_id) if position_id else None
        if lived_row is None and trade_id:
            lived_row = by_trade.get(trade_id)

        snap = ck.get("m15_snapshot") if isinstance(ck.get("m15_snapshot"), dict) else None
        source = "checkpoint_snapshot"
        if snap is None:
            entry_ts = _parse_ts(ck.get("canonical_timestamp"))
            if entry_ts is not None:
                snap = _asof_lookup(stamps, ep_rows, entry_ts)
                source = "asof_episode"
        if snap is None:
            snap = {}
            source = "missing"

        phase = str(snap.get("episode_phase") or "MISSING")
        fam = str(snap.get("auction_family") or "MISSING")
        phase_at_entry[phase] += 1
        family_at_entry[fam] += 1

        pm = pm_by_pos.get(position_id) or {}
        fb_up = int(pm.get("failed_upside_break_count") or 0)
        fb_dn = int(pm.get("failed_downside_break_count") or 0)
        bal_formed = bool(pm.get("balance_formed")) if pm else False
        eventual = str(pm.get("eventual_anchor_resolution") or "NA")
        if pm.get("postmortem_status") != "COMPLETE":
            path_pm = "NO_COMPLETE_POSTMORTEM"
        elif bal_formed and (fb_up + fb_dn) > 0:
            path_pm = "BALANCE_THEN_FAILED_BREAK"
        elif bal_formed and eventual in {
            "ACCEPTED_ABOVE",
            "ACCEPTED_BELOW",
            "RESOLUTION_UP",
            "RESOLUTION_DOWN",
        }:
            path_pm = "BALANCE_THEN_ACCEPTANCE_OR_RESOLUTION"
        elif bal_formed:
            path_pm = "BALANCE_FORMED_OTHER"
        else:
            path_pm = "NO_BALANCE_FORMED"
        hold_path_pm[path_pm] += 1

        entry_ts = _parse_ts(ck.get("canonical_timestamp"))
        exit_ts = None
        if lived_row is not None:
            exit_ts = _parse_ts(getattr(lived_row, "exit_ts", None))
        path_label = _hold_path_from_episodes(stamps, ep_rows, entry_ts, exit_ts)
        hold_path[path_label] += 1

        rec = {
            "trade_id": (
                trade_id
                or (str(getattr(lived_row, "trade_id")) if lived_row is not None else None)
                or pm.get("trade_id")
            ),
            "position_id": position_id
            or (str(getattr(lived_row, "position_id")) if lived_row is not None else None),
            "canonical_side": ck.get("canonical_side"),
            "canonical_timestamp": ck.get("canonical_timestamp"),
            "coverage_status": ck.get("coverage_status"),
            "structure_source": source,
            "auction_family": fam,
            "episode_phase": phase,
            "balance_state": snap.get("balance_state"),
            "pressure_side": snap.get("pressure_side"),
            "balance_support": snap.get("balance_support"),
            "up_exhaustion_support": snap.get("up_exhaustion_support"),
            "down_exhaustion_support": snap.get("down_exhaustion_support"),
            "hold_path_label": path_label,
            "hold_path_postmortem": path_pm,
            "postmortem_status": pm.get("postmortem_status"),
            "retrospective_structure_label": pm.get("retrospective_structure_label"),
            "eventual_anchor_resolution": pm.get("eventual_anchor_resolution"),
            "net_pnl_usd": float(getattr(lived_row, "net_pnl_usd")) if lived_row is not None else None,
            "r_multiple": getattr(lived_row, "r_multiple", None) if lived_row is not None else None,
            "exit_reason": getattr(lived_row, "exit_reason", None) if lived_row is not None else None,
        }
        # regime bucket
        if phase in STOPPING:
            bucket = "STOPPING_CANDIDATE"
        elif phase in FAILED_BREAK:
            bucket = "FAILED_BREAK"
        elif phase in ACCEPTANCE or phase in RESOLUTION:
            bucket = "ACCEPTANCE_OR_RESOLUTION"
        elif fam == "BALANCE" or phase in BALANCE_CORE:
            bucket = "BALANCE"
        elif fam in {"DIRECTIONAL_UP", "DIRECTIONAL_DOWN"}:
            bucket = "DIRECTIONAL"
        elif fam == "TRANSITION" or phase == "TRANSITION":
            bucket = "TRANSITION"
        else:
            bucket = "OTHER_OR_MISSING"
        rec["regime_bucket"] = bucket
        rows_out.append(rec)

    df = pd.DataFrame(rows_out)
    # secondary PnL by regime (not primary gate)
    by_regime = {}
    by_hold = {}
    if len(df) and "net_pnl_usd" in df.columns:
        for bucket, g in df.groupby("regime_bucket"):
            pnls = g["net_pnl_usd"].dropna()
            by_regime[str(bucket)] = {
                "n": int(len(g)),
                "n_with_pnl": int(len(pnls)),
                "wr": round(float((pnls > 0).mean()), 4) if len(pnls) else None,
                "net_pnl_sum": round(float(pnls.sum()), 2) if len(pnls) else None,
                "avg_pnl": round(float(pnls.mean()), 2) if len(pnls) else None,
            }
        for bucket, g in df.groupby("hold_path_label"):
            pnls = g["net_pnl_usd"].dropna()
            by_hold[str(bucket)] = {
                "n": int(len(g)),
                "n_with_pnl": int(len(pnls)),
                "wr": round(float((pnls > 0).mean()), 4) if len(pnls) else None,
                "net_pnl_sum": round(float(pnls.sum()), 2) if len(pnls) else None,
                "avg_pnl": round(float(pnls.mean()), 2) if len(pnls) else None,
            }

    joined = int(df["net_pnl_usd"].notna().sum()) if len(df) else 0
    summary = {
        "n_paper_entry_checkpoints": int(len(df)),
        "n_joined_lived_pnl": joined,
        "coverage_counts": dict(cov),
        "structure_source_counts": dict(Counter(df["structure_source"])) if len(df) else {},
        "family_at_entry": dict(family_at_entry),
        "phase_at_entry_top": _top(phase_at_entry, 25),
        "regime_bucket_counts": dict(Counter(df["regime_bucket"])) if len(df) else {},
        "hold_path_counts": dict(hold_path),
        "hold_path_postmortem_counts": dict(hold_path_pm),
        "secondary_pnl_by_regime": by_regime,
        "secondary_pnl_by_hold_path": by_hold,
        "note_ru": (
            "PnL by regime is SECONDARY context only — not primary prove/refute of structure detectors. "
            "Structure primarily from as-of M15 episode when checkpoint snapshot missing. "
            "hold_path_label from M15 episode scan entry→exit; postmortem mostly incomplete on this pack."
        ),
    }
    summary["gate"] = {
        "joined_ok": joined >= 0.9 * max(len(df), 1),
        "structure_resolved_share": round(
            1.0 - (phase_at_entry.get("MISSING", 0) / max(len(df), 1)), 4
        ),
        "pass": joined >= 0.9 * max(len(df), 1)
        and (1.0 - phase_at_entry.get("MISSING", 0) / max(len(df), 1)) >= 0.8,
    }
    return summary, df


def gate_s4_postmortem(replay: Path) -> dict[str, Any]:
    mem = replay / "memory"
    status: Counter = Counter()
    labels: Counter = Counter()
    resolution: Counter = Counter()
    n_complete_bal = 0
    for row in _iter_jsonl(mem / "postmortem_memory.jsonl"):
        st = str(row.get("postmortem_status") or "NA")
        status[st] += 1
        if st == "COMPLETE" and bool(row.get("balance_formed")):
            n_complete_bal += 1
            labels[str(row.get("retrospective_structure_label") or "NA")] += 1
            resolution[str(row.get("eventual_anchor_resolution") or "NA")] += 1
    return {
        "status_counts": dict(status),
        "n_complete_with_balance_formed": n_complete_bal,
        "retrospective_labels": dict(labels),
        "eventual_anchor_resolution": dict(resolution),
        "informational_only": True,
    }


def build_gate_note(
    *,
    s0: dict[str, Any],
    s1: dict[str, Any],
    s2: dict[str, Any],
    s3: dict[str, Any],
    s4: dict[str, Any],
) -> dict[str, Any]:
    code_can = [
        "AES2 families: UNRESOLVED/DIRECTIONAL_UP/DOWN/BALANCE/TRANSITION",
        "AES2 directional: pressure→expand→extreme→continuation→deteriorating→stopping_candidate→post_stress→resolution",
        "AES2 balance: forming→established→rotation/compression→boundary pressure→expansion attempt→failed_break|acceptance→resolution",
        "AES2 INTERNAL_TRANSFER_SUPPORT (not live accum/distrib)",
        "AES3 multi-TF alignment/conflict/exhaustion/balance/resolution",
        "AES4 coverage freeze only",
        "AES5 trade-relative + postmortem *_LIKE retrospective only",
        "NO FALSE_CLIMAX / CASCADE enums; extreme ≠ climax by design",
    ]
    confirmed = []
    refuted_or_weak = []
    if s1["gate"]["pass"]:
        confirmed.append("S1: AES2 emits distinct balance+directional regimes on M15 ETLL span")
    else:
        refuted_or_weak.append("S1: regimes not distinct enough / missing balance or directional")
    if s1["stopping"]["entries"] == 0:
        refuted_or_weak.append("S1: STOPPING_CANDIDATE never entered on M15 events — stopping path unused on this pack")
    else:
        confirmed.append(f"S1: stopping entries={s1['stopping']['entries']}")
    if s1["extreme"]["entries"] == 0:
        refuted_or_weak.append("S1: EXTREME_* participation never entered on M15 events")
    else:
        confirmed.append(f"S1: extreme entries={s1['extreme']['entries']} (not climax verdict)")
    fb = s1["failed_break_vs_acceptance"]
    if fb["failed_break_transitions"] + fb["acceptance_transitions"] == 0:
        refuted_or_weak.append("S1: no FAILED_BREAK / ACCEPTANCE transitions on M15 events")
    else:
        confirmed.append(
            f"S1: failed_break={fb['failed_break_transitions']} acceptance={fb['acceptance_transitions']}"
        )

    if s2["gate"]["pass"]:
        confirmed.append("S2: hierarchy not stuck on UNRESOLVED; multi-TF labels present")
    else:
        refuted_or_weak.append("S2: hierarchy mostly unresolved / no multi-TF structure labels")

    if s3["gate"]["pass"]:
        confirmed.append("S3: lived join + as-of structure at entry mostly available")
    else:
        refuted_or_weak.append("S3: weak join or missing structure at entry")

    # Overall: structure atlas GO if S0+S1+S2; S3 supports context
    overall = "GO_STRUCTURE_ATLAS"
    if not (s0.get("pass") and s1["gate"]["pass"] and s2["gate"]["pass"]):
        overall = "NO_GO_OR_WEAK_STRUCTURE"
    elif s1["stopping"]["entries"] == 0 and (
        fb["failed_break_transitions"] + fb["acceptance_transitions"] == 0
    ):
        overall = "GO_ATLAS_BUT_KEY_PATHS_UNUSED"

    return {
        "generated_at": _utc_now(),
        "candidate": "SHADOW_AUCTION_STRUCTURE",
        "replay_run_id": "RPL_b138e142ab9e5ac5_20260826T150642",
        "fidelity": "PACK_CANDLE_STRUCTURE_PLUS_VOLUME_RESPONSE_PROXY",
        "primary_metric": "AES2/AES3 structure — NOT AES5 AGREE vs PnL",
        "gates": {
            "S0": s0.get("pass"),
            "S1": s1["gate"],
            "S2": s2["gate"],
            "S3": s3["gate"],
            "S4_informational": True,
        },
        "code_capabilities": code_can,
        "confirmed_on_etll": confirmed,
        "weak_or_unused_on_etll": refuted_or_weak,
        "s4_postmortem": s4,
        "verdict": overall,
        "verdict_ru": (
            "Оценка по структуре аукциона, не по UNRESOLVED AES5. "
            "Смотреть confirmed_on_etll vs weak_or_unused_on_etll."
        ),
    }


def write_human_report(path: Path, gate: dict[str, Any], s1: dict, s2: dict, s3: dict) -> None:
    lines = [
        "# Shadow Auction — structure eval report",
        "",
        f"Generated: {gate['generated_at']}",
        f"Replay: {gate['replay_run_id']}",
        f"Fidelity: {gate['fidelity']}",
        f"Verdict: **{gate['verdict']}**",
        "",
        "## Code capabilities (what it defines)",
        "",
    ]
    for x in gate["code_capabilities"]:
        lines.append(f"- {x}")
    lines += ["", "## Confirmed on ETLL full span", ""]
    for x in gate["confirmed_on_etll"]:
        lines.append(f"- {x}")
    lines += ["", "## Weak / unused on this pack", ""]
    for x in gate["weak_or_unused_on_etll"]:
        lines.append(f"- {x}")
    lines += [
        "",
        "## M15 family mix (episode snapshots)",
        "",
        "```",
        json.dumps(s1["m15_episode"]["family_counts"], indent=2),
        "```",
        "",
        "## Hierarchy top states",
        "",
        "```",
        json.dumps(s2["hierarchy_state_top"][:12], indent=2),
        "```",
        "",
        "## Entry regime buckets (S3, secondary PnL in JSON)",
        "",
        "```",
        json.dumps(s3.get("regime_bucket_counts"), indent=2),
        "```",
        "",
        "## Hold path during trade (M15 episode scan entry→exit)",
        "",
        "```",
        json.dumps(s3.get("hold_path_counts"), indent=2),
        "```",
        "",
        "## Explicit non-claims",
        "",
        "- Does not prove false climax / cascade liquidations (no such labels).",
        "- Does not prove live accumulation/distribution (only postmortem *_LIKE).",
        "- AES5 final_shadow_verdict is not the primary structure score.",
        "- STOPPING_CANDIDATE unused on this ETLL M15 pack (code path exists; not exercised).",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, default=DEFAULT_REPLAY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--lived", type=Path, default=DEFAULT_LIVED)
    args = parser.parse_args()

    replay = args.replay_root
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    print("S0…", flush=True)
    s0 = gate_s0(replay)
    print("S1…", flush=True)
    s1 = gate_s1_atlas(replay)
    print("S2…", flush=True)
    s2 = gate_s2_hierarchy(replay)
    print("as-of index…", flush=True)
    stamps, ep_rows = _asof_episode_index(replay)
    print(f"  M15 episodes indexed: {len(ep_rows)}", flush=True)
    print("S3…", flush=True)
    s3, df = gate_s3_lived(replay, args.lived, stamps, ep_rows)
    print("S4…", flush=True)
    s4 = gate_s4_postmortem(replay)

    atlas = {
        "generated_at": _utc_now(),
        "stage": "AUCTION_STRUCTURE_ATLAS",
        "replay_root": str(replay),
        "S0": s0,
        "S1": {
            "m15_episode": s1["m15_episode"],
            "family_by_tf": s1["family_by_tf"],
            "phase_by_tf_top": s1["phase_by_tf_top"],
            "m15_transitions_top": s1["m15_transitions_top"],
            "m15_balance_edges_top": s1["m15_balance_edges_top"],
            "m15_reason_codes_top": s1["m15_reason_codes_top"],
            "gate": s1["gate"],
        },
        "S2": dict(s2),
    }
    quality = {
        "generated_at": _utc_now(),
        "stopping": s1["stopping"],
        "extreme": s1["extreme"],
        "failed_break_vs_acceptance": s1["failed_break_vs_acceptance"],
        "m15_balance_edges_top": s1["m15_balance_edges_top"],
    }
    s3_path_summary = {
        "generated_at": _utc_now(),
        **s3,
    }
    gate = build_gate_note(s0=s0, s1=s1, s2=s2, s3=s3, s4=s4)

    (out / "auction_structure_atlas.json").write_text(json.dumps(atlas, indent=2) + "\n")
    (out / "auction_structure_stopping_failed_break.json").write_text(
        json.dumps(quality, indent=2) + "\n"
    )
    (out / "auction_structure_x_lived_summary.json").write_text(
        json.dumps(s3_path_summary, indent=2) + "\n"
    )
    if len(df):
        df.to_parquet(out / "auction_structure_x_lived.parquet", index=False)
    (out / "gate_note_structure.json").write_text(json.dumps(gate, indent=2) + "\n")
    write_human_report(out / "STRUCTURE_EVAL_REPORT.md", gate, s1, s2, s3)

    print(json.dumps({"verdict": gate["verdict"], "S0": s0["pass"], "S1": s1["gate"], "S2": s2["gate"], "S3": s3["gate"]}, indent=2))
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
