"""AES5 checkpoint verdicts, chronological outcomes, and post-mortems."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from btc_ml.trading.shadow_auction.checkpoint import (
    COV_NO_SHADOW,
    COV_STALE,
    CheckpointLinker,
    ShadowHistoryIndex,
    TF_MISSING,
    TF_STALE,
)
from btc_ml.trading.shadow_auction.engine import ShadowAuctionAES2
from btc_ml.trading.shadow_auction.evaluation import Aes5Evaluator
from btc_ml.trading.shadow_auction.hierarchy import HierarchyEngine, TfStateView
from btc_ml.trading.shadow_auction.hierarchy_states import (
    HIER_MULTI_TF_RESOLUTION_DOWN,
    HIER_MULTI_TF_RESOLUTION_UP,
    HIER_STRUCTURAL_DOWN_ALIGNED,
    HIER_STRUCTURAL_UP_ALIGNED,
    HIER_TRANSITION_PROPAGATING_TO_HIGHER_TF,
)
from btc_ml.trading.shadow_auction.outcome import (
    COUNTERFACTUAL_TYPE,
    FINAL_AGREE,
    FINAL_AGREE_LATE,
    FINAL_TOO_LATE,
    LABEL_AVOIDED,
    LABEL_BETTER_ENTRY,
    LABEL_LOSS_AGREE,
    LABEL_LOSS_REJECT,
    LABEL_MISSED,
    LABEL_WIN_AGREE,
    LABEL_WIN_REJECT,
    LABEL_WORSE_ENTRY,
    OutcomeEngine,
    build_outcome,
    entry_delta_bps,
    entry_improvement,
    scan_first_hits,
    timing_same_exit_pnl,
)
from btc_ml.trading.shadow_auction.postmortem import (
    LABEL_ACCUMULATION,
    LABEL_DISTRIBUTION,
    LABEL_REACCUMULATION,
    LABEL_REDISTRIBUTION,
    LABEL_UNRESOLVED_BALANCE,
    STATUS_INSUFFICIENT,
    STATUS_WAITING,
    PostmortemEngine,
    build_postmortem,
    deterministic_postmortem_id,
    retrospective_label,
)
from btc_ml.trading.shadow_auction.states import (
    FAMILY_BALANCE,
    FAMILY_DIRECTIONAL_DOWN,
    FAMILY_DIRECTIONAL_UP,
    FAMILY_TRANSITION,
    PHASE_BALANCE_ESTABLISHED,
    PHASE_DOWN_CONTINUATION_ACCEPTED,
    PHASE_RESOLUTION_DOWN,
    PHASE_RESOLUTION_UP,
    PHASE_TRANSITION,
    PHASE_UP_CONTINUATION_ACCEPTED,
)
from btc_ml.trading.shadow_auction.verdict import (
    VERDICT_OPPOSITE,
    VERDICT_REJECT,
    VERDICT_SUPPORT,
    VERDICT_UNRESOLVED,
    VERDICT_WAIT,
    VerdictEngine,
    deterministic_verdict_id,
    interpret_checkpoint,
)

REPO = Path(__file__).resolve().parents[3]
REAL_VOLUME = Path("/Volumes/MaksTiger")
REAL_DATA_ROOT = REAL_VOLUME / "btc-ml" / "shadow_auction"

T0 = "2026-08-11T10:00:00Z"
T_CTX = "2026-08-11T10:01:00Z"
T_ENT = "2026-08-11T10:07:00Z"
T_SUP = "2026-08-11T10:13:00Z"
T_SUP2 = "2026-08-11T10:20:00Z"
T_REJ = "2026-08-11T10:15:00Z"
T_OPP = "2026-08-11T10:16:00Z"
T_CLOSE = "2026-08-11T11:00:00Z"
T_AFTER = "2026-08-11T12:00:00Z"
T_AFTER2 = "2026-08-11T13:00:00Z"


def _snap(family: str, phase: str, ts: str = T0, episode: str = "epA"):
    return {
        "timeframe": "M15",
        "shadow_episode_id": episode,
        "auction_family": family,
        "episode_phase": phase,
        "timestamp": ts,
        "shadow_state_timestamp": ts,
        "logic_version": "AES_V1",
        "logic_fingerprint": "fp",
    }


def _ckp(
    *,
    cid: str,
    case: str = "CASE_X",
    ctype: str = "PAPER_ENTRY",
    side: str = "LONG",
    tf: str = "M15",
    ts: str = T_ENT,
    family: str = FAMILY_DIRECTIONAL_UP,
    phase: str = PHASE_UP_CONTINUATION_ACCEPTED,
    hier: str | None = HIER_STRUCTURAL_UP_ALIGNED,
    coverage: str = "COMPLETE",
    anchor_cov: str = "AVAILABLE",
    entry_price: float | None = None,
    close_price: float | None = None,
    close_reason: str | None = None,
    episode: str = "epA",
    trade_id: str | None = None,
    position_id: str | None = None,
):
    key = f"{tf.lower()}_snapshot"
    payload = {
        "checkpoint_id": cid,
        "shadow_case_id": case,
        "checkpoint_type": ctype,
        "canonical_side": side,
        "canonical_timeframe": tf,
        "canonical_timestamp": ts,
        "coverage_status": coverage,
        "m15_coverage_status": anchor_cov if tf == "M15" else "AVAILABLE",
        "m30_coverage_status": "AVAILABLE",
        "h1_coverage_status": "AVAILABLE",
        "h4_coverage_status": "AVAILABLE",
        "hierarchy_coverage_status": "AVAILABLE" if hier else "MISSING",
        "m15_snapshot": None,
        "m30_snapshot": None,
        "h1_snapshot": None,
        "h4_snapshot": None,
        key: _snap(family, phase, ts=ts, episode=episode),
        "hierarchy_snapshot": None
        if hier is None
        else {
            "hierarchy_state": hier,
            "local_vs_structural_state": "STRUCTURAL_MULTI_TF",
            "propagation_depth": 0,
        },
        "entry_price": entry_price,
        "close_price": close_price,
        "close_reason": close_reason,
        "trade_id": trade_id,
        "position_id": position_id,
        "logic_version": "AES_V1",
        "logic_fingerprint": "fp",
    }
    return payload


def _row(ts: str, family: str, phase: str, *, price: float | None = None, tf: str = "M15"):
    row = {
        "timestamp": ts,
        "timeframe": tf,
        "shadow_episode_id": f"{tf}_{ts}",
        "auction_family": family,
        "episode_phase": phase,
        "logic_version": "AES_V1",
        "logic_fingerprint": "fp",
    }
    if price is not None:
        row["price"] = price
    return row


def _hier(ts: str, state: str, depth: int = 0):
    return {
        "timestamp": ts,
        "hierarchy_state": state,
        "propagation_depth": depth,
        "local_vs_structural_state": "STRUCTURAL_MULTI_TF",
        "logic_version": "AES_V1",
        "logic_fingerprint": "fp",
        "snapshot_id": f"H_{ts}_{state}",
    }


def _verdict(ckp):
    return interpret_checkpoint(ckp)


def test_01_long_support_at_entry():
    ckp = _ckp(cid="CKP_SUP_L", side="LONG", family=FAMILY_DIRECTIONAL_UP, phase=PHASE_UP_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_UP_ALIGNED)
    row = _verdict(ckp)
    assert row["checkpoint_verdict"] == VERDICT_SUPPORT
    assert "ANCHOR_SUPPORTS_CANONICAL" in row["reason_codes"]


def test_02_short_support_mirror():
    ckp = _ckp(cid="CKP_SUP_S", side="SHORT", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED)
    row = _verdict(ckp)
    assert row["checkpoint_verdict"] == VERDICT_SUPPORT


def test_03_wait_in_balance():
    ckp = _ckp(cid="CKP_BAL", side="LONG", family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED, hier=HIER_STRUCTURAL_UP_ALIGNED)
    assert _verdict(ckp)["checkpoint_verdict"] == VERDICT_WAIT


def test_04_wait_in_transition():
    ckp = _ckp(cid="CKP_TR", side="LONG", family=FAMILY_TRANSITION, phase=PHASE_TRANSITION, hier=HIER_TRANSITION_PROPAGATING_TO_HIGHER_TF)
    assert _verdict(ckp)["checkpoint_verdict"] == VERDICT_WAIT


def test_05_long_rejected_by_down_continuation():
    ckp = _ckp(cid="CKP_REJ_L", side="LONG", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED)
    assert _verdict(ckp)["checkpoint_verdict"] == VERDICT_REJECT


def test_06_short_rejected_mirror():
    ckp = _ckp(cid="CKP_REJ_S", side="SHORT", family=FAMILY_DIRECTIONAL_UP, phase=PHASE_UP_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_UP_ALIGNED)
    assert _verdict(ckp)["checkpoint_verdict"] == VERDICT_REJECT


def test_07_long_opposite_resolution():
    ckp = _ckp(cid="CKP_OPP_L", side="LONG", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_RESOLUTION_DOWN, hier=HIER_MULTI_TF_RESOLUTION_DOWN)
    assert _verdict(ckp)["checkpoint_verdict"] == VERDICT_OPPOSITE


def test_08_short_opposite_mirror():
    ckp = _ckp(cid="CKP_OPP_S", side="SHORT", family=FAMILY_DIRECTIONAL_UP, phase=PHASE_RESOLUTION_UP, hier=HIER_MULTI_TF_RESOLUTION_UP)
    assert _verdict(ckp)["checkpoint_verdict"] == VERDICT_OPPOSITE


def test_09_missing_coverage_unresolved():
    ckp = _ckp(cid="CKP_MISS", coverage=COV_NO_SHADOW, anchor_cov=TF_MISSING)
    ckp["m15_snapshot"] = None
    assert _verdict(ckp)["checkpoint_verdict"] == VERDICT_UNRESOLVED
    stale = _ckp(cid="CKP_STALE", coverage=COV_STALE, anchor_cov=TF_STALE)
    assert _verdict(stale)["checkpoint_verdict"] == VERDICT_UNRESOLVED


def test_10_context_wait_entry_support():
    ctx = _ckp(cid="CKP_C10", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED)
    ent = _ckp(cid="CKP_E10", ctype="PAPER_ENTRY", ts=T_ENT, family=FAMILY_DIRECTIONAL_UP, phase=PHASE_UP_CONTINUATION_ACCEPTED, entry_price=100.0)
    close = _ckp(cid="CKP_X10", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=110.0, close_reason="TP")
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ctx),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0, "quantity": 1},
    )
    assert out["context_verdict"] == VERDICT_WAIT
    assert out["entry_verdict"] == VERDICT_SUPPORT
    frozen = dict(out)
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        index=ShadowHistoryIndex(),
        extra_anchor_rows=[_row(T_AFTER, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP)],
    )
    assert frozen["context_verdict"] == VERDICT_WAIT
    assert frozen["entry_verdict"] == VERDICT_SUPPORT
    assert pm["eventual_anchor_resolution"] in {"UP", "UNRESOLVED"}


def test_11_context_support_entry_reject():
    ctx = _ckp(cid="CKP_C11", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_DIRECTIONAL_UP, phase=PHASE_UP_CONTINUATION_ACCEPTED)
    ent = _ckp(cid="CKP_E11", ctype="PAPER_ENTRY", ts=T_ENT, family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED, entry_price=100.0)
    close = _ckp(cid="CKP_X11", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=90.0)
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ctx),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 90.0, "net_pnl": -10.0},
    )
    assert out["context_verdict"] == VERDICT_SUPPORT
    assert out["entry_verdict"] == VERDICT_REJECT


def _chrono_case(*, extra, entry_v, trade, side="LONG", entry_price=100.0):
    ctx = _ckp(cid="CKP_C", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED, side=side)
    ent = _ckp(
        cid="CKP_E",
        ctype="PAPER_ENTRY",
        ts=T_ENT,
        side=side,
        family=entry_v[0],
        phase=entry_v[1],
        hier=entry_v[2],
        entry_price=entry_price,
    )
    close = _ckp(cid="CKP_X", ctype="PAPER_CLOSE", ts=T_CLOSE, side=side, close_price=trade.get("exit_price"), close_reason=trade.get("exit_reason"))
    idx = ShadowHistoryIndex()
    return build_outcome(
        case_id="CASE_X",
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ctx),
        entry_verdict=_verdict(ent),
        index=idx,
        canonical_trade=trade,
        extra_anchor_rows=extra,
    )


def test_12_first_support_chronological():
    extra = [
        _row(T_SUP, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=99.0),
        _row(T_SUP2, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP, price=90.0),
    ]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0, "quantity": 1},
    )
    assert out["first_support_timestamp"] == T_SUP
    assert out["first_support_price"] == 99.0


def test_13_first_rejection_chronological():
    extra = [
        _row(T_REJ, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED, price=101.0),
        _row(T_SUP2, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED, price=105.0),
    ]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 90.0, "net_pnl": -10.0},
    )
    assert out["first_reject_timestamp"] == T_REJ
    assert out["first_invalidation_timestamp"] == T_REJ


def test_14_first_opposite_chronological():
    idx = ShadowHistoryIndex()
    idx.ingest_hierarchy_row(_hier(T_OPP, HIER_MULTI_TF_RESOLUTION_DOWN, depth=2))
    idx.ingest_hierarchy_row(_hier(T_SUP2, HIER_MULTI_TF_RESOLUTION_DOWN, depth=3))
    ctx = _ckp(cid="CKP_C14", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_DIRECTIONAL_UP, phase=PHASE_UP_CONTINUATION_ACCEPTED)
    ent = _ckp(cid="CKP_E14", ctype="PAPER_ENTRY", ts=T_ENT, family=FAMILY_DIRECTIONAL_UP, phase=PHASE_UP_CONTINUATION_ACCEPTED, entry_price=100.0)
    close = _ckp(cid="CKP_X14", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=90.0)
    extra = [
        _row(T_OPP, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN, price=98.0),
        _row(T_SUP2, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN, price=80.0),
    ]
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ctx),
        entry_verdict=_verdict(ent),
        index=idx,
        canonical_trade={"entry_price": 100.0, "exit_price": 90.0, "net_pnl": -10.0},
        extra_anchor_rows=extra,
    )
    assert out["first_opposite_timestamp"] == T_OPP


def test_15_confirmation_delay_zero():
    ent = _ckp(cid="CKP_E15", entry_price=100.0)
    close = _ckp(cid="CKP_X15", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=110.0)
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=None,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=None,
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0},
    )
    assert out["entry_verdict"] == VERDICT_SUPPORT
    assert out["confirmation_delay_sec"] == 0.0
    assert out["first_support_timestamp"] == T_ENT


def test_16_confirmation_after_entry():
    extra = [_row(T_SUP, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=99.0)]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0, "quantity": 1},
    )
    assert out["final_shadow_verdict"] == FINAL_AGREE_LATE
    assert out["confirmation_delay_sec"] == 360.0


def test_17_confirmation_after_close_too_late():
    extra = [_row(T_AFTER, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=120.0)]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0},
    )
    assert out["final_shadow_verdict"] == FINAL_TOO_LATE
    assert out["first_support_timestamp"] == T_AFTER


def test_18_canonical_win_shadow_agree():
    ent = _ckp(cid="CKP_E18", entry_price=100.0)
    close = _ckp(cid="CKP_X18", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=110.0)
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=None,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ent),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 12.5, "quantity": 1},
    )
    assert out["final_shadow_verdict"] == FINAL_AGREE
    assert out["primary_outcome_label"] == LABEL_WIN_AGREE


def test_19_canonical_loss_shadow_agree():
    ent = _ckp(cid="CKP_E19", entry_price=100.0)
    close = _ckp(cid="CKP_X19", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=90.0)
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=None,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ent),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 90.0, "net_pnl": -8.0},
    )
    assert out["primary_outcome_label"] == LABEL_LOSS_AGREE


def test_20_canonical_loss_shadow_reject_avoided():
    ent = _ckp(cid="CKP_E20", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED, entry_price=100.0)
    close = _ckp(cid="CKP_X20", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=90.0)
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=None,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ent),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 90.0, "net_pnl": -10.0},
    )
    assert out["entry_verdict"] == VERDICT_REJECT
    assert out["primary_outcome_label"] == LABEL_LOSS_REJECT
    assert LABEL_AVOIDED in out["secondary_outcome_labels"]
    assert "FILTER_WOULD_AVOID_LOSS" in out["reason_codes"]


def test_21_canonical_win_shadow_reject_missed():
    ent = _ckp(cid="CKP_E21", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED, entry_price=100.0)
    close = _ckp(cid="CKP_X21", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=110.0)
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=None,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ent),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0},
    )
    assert out["primary_outcome_label"] == LABEL_WIN_REJECT
    assert LABEL_MISSED in out["secondary_outcome_labels"]
    assert "FILTER_WOULD_MISS_WIN" in out["reason_codes"]


def test_22_wait_better_long_entry():
    extra = [_row(T_SUP, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=99.0)]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0, "quantity": 1},
    )
    assert out["entry_improvement"] == pytest.approx(1.0)
    assert LABEL_BETTER_ENTRY in out["secondary_outcome_labels"]
    assert "WAIT_IMPROVED_ENTRY" in out["reason_codes"]


def test_23_wait_worse_long_entry():
    extra = [_row(T_SUP, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=102.0)]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0, "quantity": 1},
    )
    assert out["entry_improvement"] == pytest.approx(-2.0)
    assert LABEL_WORSE_ENTRY in out["secondary_outcome_labels"]


def test_24_short_timing_mirror():
    better = entry_improvement("SHORT", 100.0, 101.0)
    worse = entry_improvement("SHORT", 100.0, 99.0)
    assert better == pytest.approx(1.0)
    assert worse == pytest.approx(-1.0)
    assert entry_improvement("LONG", 100.0, 99.0) == pytest.approx(better)
    extra = [_row(T_SUP, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED, price=101.0)]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_DOWN_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 90.0, "net_pnl": 10.0, "quantity": 1, "side": "SHORT"},
        side="SHORT",
        entry_price=100.0,
    )
    assert out["entry_improvement"] == pytest.approx(1.0)
    assert LABEL_BETTER_ENTRY in out["secondary_outcome_labels"]


def test_25_same_exit_counterfactual():
    extra = [_row(T_SUP, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=99.0)]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0, "quantity": 2},
    )
    assert out["counterfactual_type"] == COUNTERFACTUAL_TYPE
    assert out["timing_counterfactual_same_exit_pnl"] == pytest.approx(2.0 * (110.0 - 99.0))
    assert timing_same_exit_pnl(side="LONG", support_price=99.0, exit_price=110.0, quantity=2) == pytest.approx(22.0)
    assert timing_same_exit_pnl(side="SHORT", support_price=101.0, exit_price=90.0, quantity=2) == pytest.approx(22.0)


def test_26_no_stop_tp_simulation():
    ent = _ckp(cid="CKP_E26", entry_price=100.0)
    close = _ckp(cid="CKP_X26", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=110.0)
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=None,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ent),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0},
    )
    assert out["aes5_stop_policy"] is None
    assert out["aes5_tp_policy"] is None
    src = Path(__file__).resolve().parents[3] / "src" / "btc_ml" / "trading" / "shadow_auction"
    for name in ("verdict.py", "outcome.py", "postmortem.py", "evaluation.py"):
        text = (src / name).read_text(encoding="utf-8")
        assert "trailing_stop" not in text
        assert "virtual_equity" not in text
        assert "sklearn" not in text
        assert "catboost" not in text


def test_27_post_close_episode_unresolved():
    close = _ckp(cid="CKP_X27", ctype="PAPER_CLOSE", ts=T_CLOSE, family=FAMILY_DIRECTIONAL_UP, phase=PHASE_UP_CONTINUATION_ACCEPTED)
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=None,
        entry_ckp=_ckp(cid="CKP_E27"),
        close_ckp=close,
        index=ShadowHistoryIndex(),
        now_ts=T_AFTER,
    )
    assert pm["postmortem_status"] == STATUS_WAITING
    assert pm["eventual_anchor_resolution"] == "UNRESOLVED"


def test_28_down_balance_up_accumulation_like():
    ctx = _ckp(cid="CKP_C28", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED)
    ent = _ckp(cid="CKP_E28", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED)
    close = _ckp(cid="CKP_X28", ctype="PAPER_CLOSE", ts=T_CLOSE, family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED)
    extra = [
        _row(T_AFTER, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _row(T_AFTER2, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP),
    ]
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        index=ShadowHistoryIndex(),
        extra_anchor_rows=extra,
        now_ts=T_AFTER2,
    )
    assert pm["retrospective_structure_label"] == LABEL_ACCUMULATION
    assert pm["postmortem_status"] == "COMPLETE"
    assert pm["eventual_anchor_resolution"] == "UP"


def test_29_up_balance_down_distribution_like():
    ctx = _ckp(cid="CKP_C29", ctype="CONTEXT_START", ts=T_CTX)
    ent = _ckp(cid="CKP_E29")
    close = _ckp(cid="CKP_X29", ctype="PAPER_CLOSE", ts=T_CLOSE)
    extra = [
        _row(T_AFTER, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _row(T_AFTER2, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN),
    ]
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        index=ShadowHistoryIndex(),
        extra_anchor_rows=extra,
        now_ts=T_AFTER2,
    )
    assert pm["retrospective_structure_label"] == LABEL_DISTRIBUTION
    assert pm["eventual_anchor_resolution"] == "DOWN"


def test_30_up_balance_up_reaccumulation_like():
    ctx = _ckp(cid="CKP_C30", ctype="CONTEXT_START", ts=T_CTX)
    extra = [
        _row(T_AFTER, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _row(T_AFTER2, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP),
    ]
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=ctx,
        entry_ckp=_ckp(cid="CKP_E30"),
        close_ckp=_ckp(cid="CKP_X30", ctype="PAPER_CLOSE", ts=T_CLOSE),
        index=ShadowHistoryIndex(),
        extra_anchor_rows=extra,
        now_ts=T_AFTER2,
    )
    assert pm["retrospective_structure_label"] == LABEL_REACCUMULATION


def test_31_down_balance_down_redistribution_like():
    ctx = _ckp(cid="CKP_C31", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED)
    extra = [
        _row(T_AFTER, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED),
        _row(T_AFTER2, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN),
    ]
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=ctx,
        entry_ckp=_ckp(cid="CKP_E31", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED),
        close_ckp=_ckp(cid="CKP_X31", ctype="PAPER_CLOSE", ts=T_CLOSE, family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED),
        index=ShadowHistoryIndex(),
        extra_anchor_rows=extra,
        now_ts=T_AFTER2,
    )
    assert pm["retrospective_structure_label"] == LABEL_REDISTRIBUTION


def test_32_unresolved_balance():
    extra = [_row(T_AFTER, FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED)]
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=_ckp(cid="CKP_C32", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED),
        entry_ckp=_ckp(cid="CKP_E32", family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED),
        close_ckp=_ckp(cid="CKP_X32", ctype="PAPER_CLOSE", ts=T_CLOSE, family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED),
        index=ShadowHistoryIndex(),
        extra_anchor_rows=extra,
        now_ts=T_AFTER,
    )
    assert pm["retrospective_structure_label"] == LABEL_UNRESOLVED_BALANCE
    assert pm["postmortem_status"] == STATUS_WAITING


def test_33_propagation_depth_stored():
    idx = ShadowHistoryIndex()
    idx.ingest_hierarchy_row(_hier(T_ENT, HIER_STRUCTURAL_UP_ALIGNED, depth=1))
    idx.ingest_hierarchy_row(_hier(T_AFTER, HIER_MULTI_TF_RESOLUTION_UP, depth=3))
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=_ckp(cid="CKP_C33", ctype="CONTEXT_START", ts=T_CTX),
        entry_ckp=_ckp(cid="CKP_E33"),
        close_ckp=_ckp(cid="CKP_X33", ctype="PAPER_CLOSE", ts=T_CLOSE),
        index=idx,
        extra_anchor_rows=[_row(T_AFTER, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP)],
        now_ts=T_AFTER,
    )
    assert pm["max_propagation_depth"] == 3


def test_34_future_postmortem_cannot_alter_entry_verdict():
    ctx = _ckp(cid="CKP_C34", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED)
    ent = _ckp(cid="CKP_E34", family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED, entry_price=100.0)
    close = _ckp(cid="CKP_X34", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=110.0)
    extra = [_row(T_SUP, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=99.0)]
    out = build_outcome(
        case_id="CASE_X",
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ctx),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0},
        extra_anchor_rows=extra,
    )
    assert out["entry_verdict"] == VERDICT_WAIT
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        index=ShadowHistoryIndex(),
        extra_anchor_rows=[_row(T_AFTER2, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP)],
        now_ts=T_AFTER2,
    )
    assert out["entry_verdict"] == VERDICT_WAIT
    assert pm["eventual_anchor_resolution"] == "UP"
    assert out["context_verdict"] == VERDICT_WAIT


def test_35_future_postmortem_cannot_alter_first_support():
    extra = [
        _row(T_SUP, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=99.0),
        _row(T_AFTER2, FAMILY_DIRECTIONAL_UP, PHASE_RESOLUTION_UP, price=50.0),
    ]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0, "quantity": 1},
    )
    first = out["first_support_timestamp"]
    pm = build_postmortem(
        case_id="CASE_X",
        trade_id=None,
        position_id=None,
        context_ckp=_ckp(cid="CKP_C", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED),
        entry_ckp=_ckp(cid="CKP_E", family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED),
        close_ckp=_ckp(cid="CKP_X", ctype="PAPER_CLOSE", ts=T_CLOSE),
        index=ShadowHistoryIndex(),
        extra_anchor_rows=extra,
        now_ts=T_AFTER2,
    )
    assert first == T_SUP
    assert out["first_support_timestamp"] == T_SUP
    assert pm["eventual_resolution_timestamp"] == T_AFTER2


def test_36_no_lookahead_chronological_evaluator():
    ckp = _ckp(cid="CKP_E36", ts=T_ENT, family=FAMILY_DIRECTIONAL_UP, phase=PHASE_UP_CONTINUATION_ACCEPTED)
    frozen = copy.deepcopy(ckp)
    idx = ShadowHistoryIndex()
    idx.ingest_tf_row(_row(T_AFTER, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN))
    row = interpret_checkpoint(ckp)
    assert row["checkpoint_verdict"] == VERDICT_SUPPORT
    assert ckp == frozen
    hits, skipped = scan_first_hits(
        canonical_side="LONG",
        canonical_tf="M15",
        after_ts=T0,
        before_ts=None,
        index=idx,
        as_of_ts=T_ENT,
    )
    assert hits[VERDICT_OPPOSITE] is None
    assert skipped >= 1


def test_37_aes2_immutability():
    aes2 = ShadowAuctionAES2()
    before = {tf: (e.state.auction_family, e.state.episode_phase, e.state.shadow_episode_id) for tf, e in aes2.engines.items()}
    ev = Aes5Evaluator()
    ev.evaluate_checkpoint(_ckp(cid="CKP_IMM2"))
    after = {tf: (e.state.auction_family, e.state.episode_phase, e.state.shadow_episode_id) for tf, e in aes2.engines.items()}
    assert before == after


def test_38_aes3_immutability():
    hier = HierarchyEngine()
    hier.ingest_tf_state(TfStateView("M15", T0, "e1", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED))
    before = (hier.last_snapshot.snapshot_id if hier.last_snapshot else None, hier.last_hierarchy_timestamp)
    Aes5Evaluator().evaluate_checkpoint(_ckp(cid="CKP_IMM3"))
    assert (hier.last_snapshot.snapshot_id if hier.last_snapshot else None, hier.last_hierarchy_timestamp) == before


def test_39_aes4_immutability():
    linker = CheckpointLinker(index=ShadowHistoryIndex())
    before = linker.last_checkpoint_id
    payload = _ckp(cid="CKP_IMM4")
    original = copy.deepcopy(payload)
    interpret_checkpoint(payload)
    assert payload == original
    assert linker.last_checkpoint_id == before


def test_40_deterministic_ids():
    ckp = _ckp(cid="CKP_DET")
    assert deterministic_verdict_id("CKP_DET") == deterministic_verdict_id("CKP_DET")
    a = interpret_checkpoint(ckp)
    b = interpret_checkpoint(ckp)
    assert a["verdict_id"] == b["verdict_id"]
    assert deterministic_postmortem_id("CASE_X") == deterministic_postmortem_id("CASE_X")


def test_41_duplicate_suppression():
    eng = VerdictEngine()
    ckp = _ckp(cid="CKP_DUP")
    r1 = eng.ingest(ckp)
    r2 = eng.ingest(ckp)
    assert r1["written"] and not r1["duplicate"]
    assert r2["duplicate"] and not r2["written"]
    assert eng.duplicate_suppressed == 1


def test_42_payload_conflict():
    eng = VerdictEngine()
    ckp = _ckp(cid="CKP_CONF", side="LONG")
    assert eng.ingest(ckp)["written"]
    # Same checkpoint_id / verdict_id, different frozen snapshot → conflict.
    ckp2 = _ckp(cid="CKP_CONF", side="SHORT", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED, hier=HIER_STRUCTURAL_DOWN_ALIGNED)
    r2 = eng.ingest(ckp2)
    assert r2["payload_conflict"]
    assert not r2["written"]
    out_eng = OutcomeEngine()
    ent = _ckp(cid="CKP_E42", entry_price=100.0)
    close = _ckp(cid="CKP_X42", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=110.0)
    rec = build_outcome(
        case_id="CASE_X",
        context_ckp=None,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ent),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 110.0, "net_pnl": 10.0},
    )
    assert out_eng.ingest(rec)["written"]
    rec2 = dict(rec)
    rec2["canonical_net_pnl"] = 999.0
    r = out_eng.ingest(rec2)
    assert r["payload_conflict"]


def test_43_restart_idempotency(tmp_path: Path):
    eng = VerdictEngine()
    ckp = _ckp(cid="CKP_RST")
    r1 = eng.ingest(ckp)
    path = tmp_path / "checkpoint_verdict_memory.jsonl"
    path.write_text(json.dumps(r1["record"]) + "\n", encoding="utf-8")
    eng2 = VerdictEngine()
    eng2.restore(path)
    r2 = eng2.ingest(ckp)
    assert r2["duplicate"]
    cache_n = 0
    from btc_ml.trading.shadow_auction.cache import BoundedCache

    cache = BoundedCache(max_items=8)
    for i in range(100):
        cache.set(f"k{i}", i)
        cache_n = len(cache)
    assert cache_n == 8


def test_44_external_ssd_only():
    from btc_ml.trading.shadow_auction.memory import Aes5MemoryWriter
    from btc_ml.trading.shadow_auction.storage import ShadowAuctionStore, is_real_mounted_volume

    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger volume not mounted")
    # Isolate pytest writes under replay/ — never pollute live memory JSONL.
    pytest_root = REAL_DATA_ROOT / "replay" / "_aes5_pytest"
    store = ShadowAuctionStore(
        data_root=pytest_root,
        volume_root=REAL_VOLUME,
        min_free_bytes=1024,
        repo=REPO,
    )
    writer = Aes5MemoryWriter(store)
    row = interpret_checkpoint(_ckp(cid="CKP_EXT_AES5"))
    out = writer.write_verdict(row)
    path = store.data_root / "memory" / "checkpoint_verdict_memory.jsonl"
    assert out["written"]
    assert path.exists()
    assert str(path).startswith(str(REAL_DATA_ROOT / "replay"))
    assert "shadow_auction/memory/checkpoint_verdict_memory" not in str(path).replace(
        str(REAL_DATA_ROOT / "replay"), ""
    )


def test_45_canonical_isolation_on_aes5_failure():
    from btc_ml.trading.shadow_auction.memory import Aes5MemoryWriter

    class BoomStore:
        data_root = Path("/tmp")
        write_errors = 0

        def append_jsonl(self, *a, **k):
            raise RuntimeError("disk full")

    writer = Aes5MemoryWriter(BoomStore())  # type: ignore[arg-type]
    paper_cfg = REPO / "config" / "intrabar_paper_execution.json"
    before = paper_cfg.read_text(encoding="utf-8") if paper_cfg.exists() else ""
    with pytest.raises(RuntimeError):
        writer.write_verdict(interpret_checkpoint(_ckp(cid="CKP_ISO5")))
    after = paper_cfg.read_text(encoding="utf-8") if paper_cfg.exists() else ""
    assert before == after


def test_symmetry_entry_delta_bps():
    long_imp = entry_improvement("LONG", 10000.0, 9990.0)
    short_imp = entry_improvement("SHORT", 10000.0, 10010.0)
    assert long_imp == pytest.approx(short_imp)
    assert entry_delta_bps(10000.0, long_imp) == pytest.approx(10.0)


def test_retrospective_label_helper():
    assert retrospective_label([FAMILY_DIRECTIONAL_DOWN, FAMILY_BALANCE, "UP"]) == LABEL_ACCUMULATION
    assert retrospective_label([FAMILY_DIRECTIONAL_UP, FAMILY_BALANCE, "DOWN"]) == LABEL_DISTRIBUTION
    assert retrospective_label([FAMILY_DIRECTIONAL_UP, FAMILY_BALANCE, "UP"]) == LABEL_REACCUMULATION
    assert retrospective_label([FAMILY_DIRECTIONAL_DOWN, FAMILY_BALANCE, "DOWN"]) == LABEL_REDISTRIBUTION
    assert retrospective_label([FAMILY_DIRECTIONAL_UP, FAMILY_BALANCE]) == LABEL_UNRESOLVED_BALANCE


def test_stale_coverage_postmortem_insufficient():
    idx = ShadowHistoryIndex()
    idx.ingest_tf_row(_row(T_AFTER2, FAMILY_DIRECTIONAL_DOWN, PHASE_RESOLUTION_DOWN))
    pm = build_postmortem(
        case_id="CASE_STALE",
        trade_id=None,
        position_id=None,
        context_ckp=_ckp(cid="CKP_CS", ctype="CONTEXT_START", ts=T_CTX, coverage=COV_STALE, anchor_cov=TF_STALE),
        entry_ckp=_ckp(cid="CKP_ES", coverage=COV_STALE, anchor_cov=TF_STALE),
        close_ckp=_ckp(cid="CKP_XS", ctype="PAPER_CLOSE", ts=T_CLOSE, coverage=COV_STALE, anchor_cov=TF_STALE),
        index=idx,
        now_ts=T_AFTER2,
    )
    assert pm["postmortem_status"] == STATUS_INSUFFICIENT
    assert pm["eventual_anchor_resolution"] == "UNRESOLVED"
    assert pm["retrospective_structure_label"] is None


def test_aes4_checkpoint_not_mutated_by_verdict():
    from btc_ml.trading.shadow_auction.canonical_lifecycle import CanonicalLifecycleEvent

    idx = ShadowHistoryIndex()
    idx.ingest_tf_row(_row(T0, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED))
    linker = CheckpointLinker(index=idx, logic_version="AES_V1", logic_fingerprint="fp")
    ev = CanonicalLifecycleEvent(
        checkpoint_type="CONTEXT_START",
        canonical_timestamp=T_CTX,
        canonical_event_id="CTX_AES5_ISO",
        canonical_timeframe="M15",
        canonical_side="LONG",
        linkage_method="EXACT_ID",
    )
    res = linker.build_checkpoint(ev)
    original = copy.deepcopy(res.checkpoint)
    interpret_checkpoint(res.checkpoint)
    assert res.checkpoint == original


# --- §31 MFE / MAE after first Shadow SUPPORT (AES5 completeness) ---


def _support_entry_outcome(*, side="LONG", entry_price=100.0, exit_price=110.0, path=None, entry_ts=T_ENT):
    ctx = _ckp(
        cid="CKP_MFE_C",
        ctype="CONTEXT_START",
        ts=T_CTX,
        family=FAMILY_DIRECTIONAL_UP if side == "LONG" else FAMILY_DIRECTIONAL_DOWN,
        phase=PHASE_UP_CONTINUATION_ACCEPTED if side == "LONG" else PHASE_DOWN_CONTINUATION_ACCEPTED,
        side=side,
    )
    ent = _ckp(
        cid="CKP_MFE_E",
        ctype="PAPER_ENTRY",
        ts=entry_ts,
        side=side,
        family=FAMILY_DIRECTIONAL_UP if side == "LONG" else FAMILY_DIRECTIONAL_DOWN,
        phase=PHASE_UP_CONTINUATION_ACCEPTED if side == "LONG" else PHASE_DOWN_CONTINUATION_ACCEPTED,
        hier=HIER_STRUCTURAL_UP_ALIGNED if side == "LONG" else HIER_STRUCTURAL_DOWN_ALIGNED,
        entry_price=entry_price,
    )
    close = _ckp(
        cid="CKP_MFE_X",
        ctype="PAPER_CLOSE",
        ts=T_CLOSE,
        side=side,
        close_price=exit_price,
    )
    return build_outcome(
        case_id="CASE_MFE",
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ctx),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": entry_price, "exit_price": exit_price, "net_pnl": exit_price - entry_price, "side": side},
        causal_price_path=path,
    )


def test_mfe_mae_long_confirmation_at_entry():
    from btc_ml.trading.shadow_auction.outcome import MFE_MAE_BASIS_EVENT, OUTCOME_SCHEMA_VERSION

    path = [
        {"timestamp": T_ENT, "price": 100.0},
        {"timestamp": "2026-08-11T10:30:00Z", "price": 108.0},
        {"timestamp": "2026-08-11T10:45:00Z", "price": 97.0},
        {"timestamp": T_CLOSE, "price": 105.0},
    ]
    out = _support_entry_outcome(side="LONG", entry_price=100.0, exit_price=105.0, path=path)
    assert out["outcome_schema_version"] == OUTCOME_SCHEMA_VERSION
    assert out["mfe_mae_basis"] == MFE_MAE_BASIS_EVENT
    assert out["mfe_after_confirmation"] == pytest.approx(8.0)
    assert out["mae_after_confirmation"] == pytest.approx(3.0)
    assert out["mfe_after_confirmation_bps"] == pytest.approx(800.0)
    assert out["mae_after_confirmation_bps"] == pytest.approx(300.0)


def test_mfe_mae_short_confirmation_at_entry():
    from btc_ml.trading.shadow_auction.outcome import MFE_MAE_BASIS_EVENT

    path = [
        {"timestamp": T_ENT, "price": 100.0},
        {"timestamp": "2026-08-11T10:30:00Z", "price": 92.0},
        {"timestamp": "2026-08-11T10:45:00Z", "price": 104.0},
        {"timestamp": T_CLOSE, "price": 95.0},
    ]
    out = _support_entry_outcome(side="SHORT", entry_price=100.0, exit_price=95.0, path=path)
    assert out["mfe_mae_basis"] == MFE_MAE_BASIS_EVENT
    assert out["mfe_after_confirmation"] == pytest.approx(8.0)
    assert out["mae_after_confirmation"] == pytest.approx(4.0)


def test_mfe_mae_confirmation_after_entry():
    extra = [_row(T_SUP, FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED, price=101.0)]
    path = [
        {"timestamp": T_SUP, "price": 101.0},
        {"timestamp": "2026-08-11T10:40:00Z", "price": 110.0},
        {"timestamp": "2026-08-11T10:50:00Z", "price": 99.0},
        {"timestamp": T_CLOSE, "price": 108.0},
    ]
    out = _chrono_case(
        extra=extra,
        entry_v=(FAMILY_BALANCE, PHASE_BALANCE_ESTABLISHED, HIER_STRUCTURAL_UP_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 108.0, "net_pnl": 8.0, "quantity": 1},
    )
    # _chrono_case does not pass causal path — rebuild with path
    ctx = _ckp(cid="CKP_C", ctype="CONTEXT_START", ts=T_CTX, family=FAMILY_BALANCE, phase=PHASE_BALANCE_ESTABLISHED)
    ent = _ckp(
        cid="CKP_E",
        ctype="PAPER_ENTRY",
        ts=T_ENT,
        family=FAMILY_BALANCE,
        phase=PHASE_BALANCE_ESTABLISHED,
        hier=HIER_STRUCTURAL_UP_ALIGNED,
        entry_price=100.0,
    )
    close = _ckp(cid="CKP_X", ctype="PAPER_CLOSE", ts=T_CLOSE, close_price=108.0)
    out = build_outcome(
        case_id="CASE_MFE_LATE",
        context_ckp=ctx,
        entry_ckp=ent,
        close_ckp=close,
        context_verdict=_verdict(ctx),
        entry_verdict=_verdict(ent),
        index=ShadowHistoryIndex(),
        canonical_trade={"entry_price": 100.0, "exit_price": 108.0, "net_pnl": 8.0},
        extra_anchor_rows=extra,
        causal_price_path=path,
    )
    assert out["first_support_timestamp"] == T_SUP
    assert out["mfe_after_confirmation"] == pytest.approx(9.0)
    assert out["mae_after_confirmation"] == pytest.approx(2.0)


def test_mfe_mae_ignores_price_before_confirmation_and_after_close():
    path = [
        {"timestamp": "2026-08-11T10:05:00Z", "price": 200.0},  # before confirmation
        {"timestamp": T_ENT, "price": 100.0},
        {"timestamp": "2026-08-11T10:30:00Z", "price": 106.0},
        {"timestamp": T_CLOSE, "price": 104.0},
        {"timestamp": T_AFTER, "price": 50.0},  # after close
    ]
    out = _support_entry_outcome(path=path)
    assert out["mfe_after_confirmation"] == pytest.approx(6.0)
    assert out["mae_after_confirmation"] == pytest.approx(0.0)


def test_mfe_mae_no_support_null():
    from btc_ml.trading.shadow_auction.outcome import (
        MFE_MAE_BASIS_INSUFFICIENT,
        MFE_MAE_REASON_NO_SUPPORT,
    )

    # Entry already REJECT vs LONG — no Shadow SUPPORT confirmation exists.
    out = _chrono_case(
        extra=[_row(T_REJ, FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED, price=101.0)],
        entry_v=(FAMILY_DIRECTIONAL_DOWN, PHASE_DOWN_CONTINUATION_ACCEPTED, HIER_STRUCTURAL_DOWN_ALIGNED),
        trade={"entry_price": 100.0, "exit_price": 90.0, "net_pnl": -10.0},
    )
    assert out["entry_verdict"] == VERDICT_REJECT
    assert out["first_support_timestamp"] is None
    assert out["mfe_after_confirmation"] is None
    assert out["mae_after_confirmation"] is None
    assert out["mfe_mae_basis"] == MFE_MAE_BASIS_INSUFFICIENT
    assert out["mfe_mae_reason"] == MFE_MAE_REASON_NO_SUPPORT


def test_mfe_mae_insufficient_causal_path():
    from btc_ml.trading.shadow_auction.outcome import (
        MFE_MAE_BASIS_INSUFFICIENT,
        MFE_MAE_REASON_NO_PATH,
    )

    out = _support_entry_outcome(path=None)
    assert out["mfe_after_confirmation"] is None
    assert out["mae_after_confirmation"] is None
    assert out["mfe_mae_basis"] == MFE_MAE_BASIS_INSUFFICIENT
    assert out["mfe_mae_reason"] == MFE_MAE_REASON_NO_PATH


def test_mfe_mae_postmortem_cannot_extend_window():
    """Future post-close path points must not change MFE/MAE (window ends at close)."""
    path_locked = [
        {"timestamp": T_ENT, "price": 100.0},
        {"timestamp": "2026-08-11T10:30:00Z", "price": 107.0},
        {"timestamp": T_CLOSE, "price": 105.0},
    ]
    path_with_future = path_locked + [{"timestamp": T_AFTER2, "price": 150.0}]
    a = _support_entry_outcome(path=path_locked)
    b = _support_entry_outcome(path=path_with_future)
    assert a["mfe_after_confirmation"] == b["mfe_after_confirmation"] == pytest.approx(7.0)
    assert a["mae_after_confirmation"] == b["mae_after_confirmation"]


def test_mfe_mae_long_short_symmetry():
    long_path = [
        {"timestamp": T_ENT, "price": 100.0},
        {"timestamp": "2026-08-11T10:30:00Z", "price": 110.0},
        {"timestamp": "2026-08-11T10:45:00Z", "price": 95.0},
        {"timestamp": T_CLOSE, "price": 102.0},
    ]
    # Mirror around support for SHORT: up moves become down moves.
    short_path = [
        {"timestamp": T_ENT, "price": 100.0},
        {"timestamp": "2026-08-11T10:30:00Z", "price": 90.0},
        {"timestamp": "2026-08-11T10:45:00Z", "price": 105.0},
        {"timestamp": T_CLOSE, "price": 98.0},
    ]
    long_out = _support_entry_outcome(side="LONG", path=long_path)
    short_out = _support_entry_outcome(side="SHORT", path=short_path)
    assert long_out["mfe_after_confirmation"] == pytest.approx(short_out["mfe_after_confirmation"])
    assert long_out["mae_after_confirmation"] == pytest.approx(short_out["mae_after_confirmation"])


def test_activity_intensity_diagnostic_non_semantic():
    """§27 activity_intensity exists as diagnostic; AES2 transitions ignore it."""
    from btc_ml.trading.shadow_auction.features import FeatureEngine
    from btc_ml.trading.shadow_auction.observation import BarObservation

    eng = FeatureEngine(window=4)
    obs = BarObservation(
        timestamp=T0,
        timeframe="M15",
        source_event_id="M15|activity|0",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
        volume_zscore=2.0,
        delta=4.0,
    )
    snap = eng.update(obs)
    assert "activity_intensity" in snap.to_dict()
    assert 0.0 <= snap.activity_intensity <= 1.0
    assert snap.activity_intensity == pytest.approx(0.5 * snap.volume_intensity + 0.5 * snap.delta_intensity)
