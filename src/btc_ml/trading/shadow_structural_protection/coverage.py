"""STP2.1 coverage / metric integrity helpers (observe-only)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from . import CAUSAL_LOOKBACK_HOURS_BY_TF, TIMEFRAMES
from .bars import build_bars_from_trades
from .catalog import causal_lookback_start
from .timeutil import iso, parse_ts
from .trades import load_agg_trades


FAMILY_BASELINE = "BASELINE"
FAMILY_STRUCTURAL_SL_ONLY = "STRUCTURAL_SL_ONLY"
FAMILY_STRUCTURAL_TP_ONLY = "STRUCTURAL_TP_ONLY"
FAMILY_FULL_STRUCTURAL = "FULL_STRUCTURAL"
FAMILY_OTHER = "OTHER"


def policy_family(policy_id: str | None) -> str:
    pid = str(policy_id or "")
    if pid == "BASELINE_CANONICAL":
        return FAMILY_BASELINE
    if pid.startswith("STRUCTURAL_SL_CANONICAL_TP"):
        return FAMILY_STRUCTURAL_SL_ONLY
    if pid.startswith("CANONICAL_SL_STRUCTURAL_TP"):
        return FAMILY_STRUCTURAL_TP_ONLY
    if "STRUCTURAL_SL_STRUCTURAL_TP" in pid or pid.startswith("STRUCTURAL_SL_TP"):
        return FAMILY_FULL_STRUCTURAL
    return FAMILY_OTHER


def empty_tf_counts() -> dict[str, int]:
    return {tf: 0 for tf in TIMEFRAMES}


def empty_family_matrix() -> dict[str, dict[str, int]]:
    families = (
        FAMILY_BASELINE,
        FAMILY_STRUCTURAL_SL_ONLY,
        FAMILY_STRUCTURAL_TP_ONLY,
        FAMILY_FULL_STRUCTURAL,
        FAMILY_OTHER,
    )
    return {tf: {fam: 0 for fam in families} for tf in TIMEFRAMES}


def summarize_execute_breakdown(decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_tf = empty_tf_counts()
    by_family = {
        FAMILY_BASELINE: 0,
        FAMILY_STRUCTURAL_SL_ONLY: 0,
        FAMILY_STRUCTURAL_TP_ONLY: 0,
        FAMILY_FULL_STRUCTURAL: 0,
        FAMILY_OTHER: 0,
    }
    by_tf_family = empty_family_matrix()
    for d in decisions:
        if d.get("action") != "EXECUTE_STRUCTURAL":
            continue
        tf = str(d.get("timeframe") or "")
        fam = policy_family(d.get("policy_id"))
        if tf in by_tf:
            by_tf[tf] += 1
        by_family[fam] = int(by_family.get(fam, 0)) + 1
        if tf in by_tf_family:
            by_tf_family[tf][fam] = int(by_tf_family[tf].get(fam, 0)) + 1
    return {
        "by_timeframe": by_tf,
        "by_policy_family": by_family,
        "by_timeframe_and_family": by_tf_family,
    }


def prove_baseline_only_when_no_same_tf_structural(
    *,
    decisions: Sequence[Mapping[str, Any]],
    unique_usable_protective_by_tf: Mapping[str, int],
    unique_usable_target_by_tf: Mapping[str, int],
) -> dict[str, Any]:
    """Prove M15/H1 (any TF) EXECUTEs are baseline-only when no same-TF structural evidence."""
    proof: dict[str, Any] = {}
    for tf in TIMEFRAMES:
        tf_exec = [
            d
            for d in decisions
            if d.get("action") == "EXECUTE_STRUCTURAL" and str(d.get("timeframe") or "") == tf
        ]
        families = {policy_family(d.get("policy_id")) for d in tf_exec}
        # Prefer unique zone counters; fall back to decision-row usable flags (same manifest).
        decision_prot = sum(1 for d in decisions if str(d.get("timeframe") or "") == tf and d.get("protective_zone_usable"))
        decision_targ = sum(1 for d in decisions if str(d.get("timeframe") or "") == tf and d.get("target_zone_usable"))
        structural_usable = int(unique_usable_protective_by_tf.get(tf, 0)) + int(
            unique_usable_target_by_tf.get(tf, 0)
        )
        if structural_usable == 0:
            structural_usable = decision_prot + decision_targ
        structural_exec = sorted(f for f in families if f != FAMILY_BASELINE and f != FAMILY_OTHER)
        baseline_only = (not tf_exec) or (families <= {FAMILY_BASELINE})
        ok = True
        reason = "NO_EXECUTE_ROWS"
        if tf_exec and structural_usable == 0:
            ok = baseline_only
            reason = (
                "BASELINE_ONLY_AS_EXPECTED_NO_SAME_TF_STRUCTURAL_EVIDENCE"
                if ok
                else "STRUCTURAL_EXECUTE_WITHOUT_SAME_TF_USABLE_EVIDENCE"
            )
        elif tf_exec and structural_usable > 0:
            reason = "SAME_TF_STRUCTURAL_EVIDENCE_PRESENT"
            ok = True
        proof[tf] = {
            "execute_count": len(tf_exec),
            "families": sorted(families),
            "unique_usable_protective": int(unique_usable_protective_by_tf.get(tf, 0)),
            "unique_usable_target": int(unique_usable_target_by_tf.get(tf, 0)),
            "decision_protective_usable_flags": decision_prot,
            "decision_target_usable_flags": decision_targ,
            "structural_usable_zones": structural_usable,
            "baseline_only": baseline_only,
            "structural_execute_families": structural_exec,
            "proof_ok": ok,
            "reason": reason,
        }
    overall_ok = all(v.get("proof_ok") for v in proof.values())
    return {"by_timeframe": proof, "proof_ok": overall_ok}


def aggregate_target_absence(audits: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(audits)
    if not rows:
        return {
            "candidate_audits": 0,
            "verdict_counts": {},
            "overall_verdict": "NO_CANDIDATES",
            "legitimate_absence": True,
            "search_or_catalog_defect": False,
        }
    counts: dict[str, int] = defaultdict(int)
    for a in rows:
        counts[str(a.get("verdict") or "UNKNOWN")] += 1
    defect = any(str(a.get("verdict") or "").startswith("SEARCH_OR_CATALOG_DEFECT") for a in rows)
    legitimate = not defect
    if defect:
        overall = "SEARCH_OR_CATALOG_DEFECT_PRESENT"
    elif all(
        str(a.get("verdict") or "").startswith("LEGITIMATE_ABSENCE") for a in rows
    ):
        overall = "LEGITIMATE_ABSENCE_ACROSS_CANDIDATES"
    else:
        overall = "MIXED_OR_UNKNOWN"
    return {
        "candidate_audits": len(rows),
        "verdict_counts": dict(counts),
        "overall_verdict": overall,
        "legitimate_absence": legitimate,
        "search_or_catalog_defect": defect,
        "samples": list(rows)[-8:],
    }


def recompute_absolute_bar_coverage(
    *,
    repo,
    candidate_snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Unique exact bars for the absolute raw-event interval spanning active-manifest candidates."""
    if not candidate_snapshots:
        return {
            "absolute_interval_start": None,
            "absolute_interval_end": None,
            "trade_events_loaded": 0,
            "total_reconstructed_bars_by_timeframe": empty_tf_counts(),
            "unique_closed_bars_by_timeframe": empty_tf_counts(),
            "candidate_window_bars_sum_by_timeframe": empty_tf_counts(),
            "candidate_mix_by_timeframe": empty_tf_counts(),
            "explanation": "No active-manifest candidates yet.",
        }

    decisions: list[datetime] = []
    starts: list[datetime] = []
    mix = empty_tf_counts()
    window_sum = empty_tf_counts()
    unique_window: dict[str, set[str]] = {tf: set() for tf in TIMEFRAMES}

    for snap in candidate_snapshots:
        tf = str(snap.get("timeframe") or "")
        dts = parse_ts(snap.get("decision_timestamp") or snap.get("decision_ts"))
        if dts is None or tf not in TIMEFRAMES:
            continue
        mix[tf] = int(mix.get(tf, 0)) + 1
        decisions.append(dts)
        starts.append(causal_lookback_start(dts, tf))
        window_sum[tf] = int(window_sum.get(tf, 0)) + int(snap.get("bars_built") or 0)
        for cid in snap.get("closed_candle_ids") or []:
            unique_window[tf].add(str(cid))

    if not decisions:
        return {
            "absolute_interval_start": None,
            "absolute_interval_end": None,
            "trade_events_loaded": 0,
            "total_reconstructed_bars_by_timeframe": empty_tf_counts(),
            "unique_closed_bars_by_timeframe": empty_tf_counts(),
            "candidate_window_bars_sum_by_timeframe": window_sum,
            "candidate_mix_by_timeframe": mix,
            "explanation": "Candidates lacked parseable decision timestamps.",
        }

    abs_start = min(starts)
    abs_end = max(decisions)
    trades = load_agg_trades(repo=repo, start=abs_start, end=abs_end)
    total = empty_tf_counts()
    unique_closed = empty_tf_counts()
    for tf in TIMEFRAMES:
        bars = build_bars_from_trades(trades, timeframe=tf, causal_cutoff=abs_end, start=abs_start)
        closed = [b for b in bars if not b.get("incomplete")]
        total[tf] = len(bars)
        unique_closed[tf] = len({b["candle_id"] for b in closed})

    explanation = (
        "Health historically summed per-candidate bars_built (candidate-window sum), not unique "
        "absolute bars. Candidate mix and any stale bars_built=1 snapshots inflate/deflate that sum; "
        "absolute unique closed bars for the same raw-event interval are reported separately."
    )
    return {
        "absolute_interval_start": iso(abs_start),
        "absolute_interval_end": iso(abs_end),
        "lookback_hours_by_timeframe": dict(CAUSAL_LOOKBACK_HOURS_BY_TF),
        "trade_events_loaded": 0 if trades is None else int(len(trades)),
        "total_reconstructed_bars_by_timeframe": total,
        "unique_closed_bars_by_timeframe": unique_closed,
        "unique_closed_bars_seen_in_candidate_windows_by_timeframe": {
            tf: len(unique_window[tf]) for tf in TIMEFRAMES
        },
        "candidate_window_bars_sum_by_timeframe": window_sum,
        "candidate_mix_by_timeframe": mix,
        "explanation": explanation,
    }


def coverage_integrity_ok(
    *,
    m15_parity: Mapping[str, Any] | None,
    execute_proof: Mapping[str, Any] | None,
    target_audit: Mapping[str, Any] | None,
    bar_coverage: Mapping[str, Any] | None,
    lookback_by_tf: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    parity = dict(m15_parity or {})
    if int(parity.get("compared") or 0) == 0 and parity.get("status") == "SHADOW_RESEARCH_PARITY_OK":
        blockers.append("M15_PARITY_OK_WITH_COMPARED_0")
    if parity and int(parity.get("compared") or 0) == 0:
        if parity.get("status") != "NOT_EVALUABLE_INSUFFICIENT_OVERLAP" and not parity.get("parity_blocked"):
            blockers.append("M15_PARITY_STATUS_NOT_NOT_EVALUABLE")
    if execute_proof is not None and not execute_proof.get("proof_ok", True):
        blockers.append("BASELINE_ONLY_EXECUTE_PROOF_FAILED")
    if target_audit is not None and target_audit.get("search_or_catalog_defect"):
        blockers.append("TARGET_USABLE_SEARCH_OR_CATALOG_DEFECT")
    if not bar_coverage or not bar_coverage.get("explanation"):
        blockers.append("BAR_COVERAGE_MISSING")
    if lookback_by_tf is not None:
        for tf in TIMEFRAMES:
            row = lookback_by_tf.get(tf) if isinstance(lookback_by_tf, Mapping) else None
            if row is None:
                continue
            # Only require coverage_ok when that TF has candidates
            pass
    return (len(blockers) == 0), blockers
