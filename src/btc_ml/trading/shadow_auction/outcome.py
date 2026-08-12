"""AES5 case outcome attribution — chronological Shadow vs canonical paper trade.

Timing counterfactual is SAME_CANONICAL_EXIT_TIMING_ONLY. No Shadow stop/TP/sizing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .checkpoint import ShadowHistoryIndex
from .verdict import (
    VERDICT_OPPOSITE,
    VERDICT_REJECT,
    VERDICT_SUPPORT,
    VERDICT_UNRESOLVED,
    VERDICT_WAIT,
    interpret_state,
)

FINAL_AGREE = "AGREE"
FINAL_AGREE_LATE = "AGREE_DIRECTION_LATE"
FINAL_TOO_LATE = "SHADOW_TOO_LATE"
FINAL_REJECT = "REJECT_CANONICAL"
FINAL_OPPOSITE = "OPPOSITE"
FINAL_UNRESOLVED = "UNRESOLVED"

COUNTERFACTUAL_TYPE = "SAME_CANONICAL_EXIT_TIMING_ONLY"

LABEL_WIN_AGREE = "CANONICAL_WIN_SHADOW_AGREE"
LABEL_WIN_REJECT = "CANONICAL_WIN_SHADOW_REJECT"
LABEL_LOSS_REJECT = "CANONICAL_LOSS_SHADOW_REJECT"
LABEL_LOSS_AGREE = "CANONICAL_LOSS_SHADOW_AGREE"
LABEL_BETTER_ENTRY = "SHADOW_BETTER_ENTRY"
LABEL_WORSE_ENTRY = "CANONICAL_BETTER_ENTRY"
LABEL_NO_DIFF = "NO_ENTRY_PRICE_DIFFERENCE"
LABEL_AVOIDED = "SHADOW_AVOIDED_LOSS"
LABEL_MISSED = "SHADOW_MISSED_WIN"
LABEL_OPPOSITE_BETTER = "SHADOW_OPPOSITE_BETTER"
LABEL_NO_MEANINGFUL = "NO_MEANINGFUL_DIFFERENCE"
LABEL_UNRESOLVED = "UNRESOLVED_OUTCOME"

# Outcome schema evolution: v2 adds causal MFE/MAE after first Shadow SUPPORT.
OUTCOME_SCHEMA_VERSION = 2
MFE_MAE_BASIS_EVENT = "EVENT_TIME_PRICE_PATH"
MFE_MAE_BASIS_INSUFFICIENT = "INSUFFICIENT_CAUSAL_PRICE_PATH"
MFE_MAE_REASON_NO_SUPPORT = "NO_SHADOW_SUPPORT"
MFE_MAE_REASON_NO_PATH = "NO_CAUSAL_PRICE_PATH_PROVIDED"
MFE_MAE_REASON_EMPTY_WINDOW = "EMPTY_POST_CONFIRMATION_PRICE_WINDOW"
MFE_MAE_REASON_MISSING_SUPPORT_PRICE = "MISSING_SUPPORT_PRICE"
MFE_MAE_REASON_MISSING_TIMESTAMPS = "MISSING_CONFIRMATION_OR_CLOSE_TIMESTAMP"


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _age(a: str | None, b: str | None) -> float | None:
    pa, pb = _parse_ts(a), _parse_ts(b)
    if pa is None or pb is None:
        return None
    return (pa - pb).total_seconds()


def deterministic_outcome_id(case_id: str, close_checkpoint_id: str) -> str:
    return "OUT_" + hashlib.sha1(f"AES5|{case_id}|{close_checkpoint_id}".encode()).hexdigest()[:20]


def entry_improvement(side: str, canonical_entry: float, support_price: float) -> float:
    if str(side).upper() == "LONG":
        return float(canonical_entry) - float(support_price)
    return float(support_price) - float(canonical_entry)


def entry_delta_bps(canonical_entry: float, improvement: float) -> float:
    if abs(float(canonical_entry)) < 1e-12:
        return 0.0
    return float(improvement) / float(canonical_entry) * 10000.0


def timing_same_exit_pnl(
    *,
    side: str,
    support_price: float,
    exit_price: float,
    quantity: float | None,
) -> float:
    qty = 1.0 if quantity is None else float(quantity)
    if str(side).upper() == "LONG":
        return qty * (float(exit_price) - float(support_price))
    return qty * (float(support_price) - float(exit_price))


def _null_mfe_mae(*, basis: str, reason: str) -> dict[str, Any]:
    return {
        "mfe_after_confirmation": None,
        "mae_after_confirmation": None,
        "mfe_after_confirmation_bps": None,
        "mae_after_confirmation_bps": None,
        "mfe_mae_basis": basis,
        "mfe_mae_reason": reason,
    }


def compute_mfe_mae_after_confirmation(
    *,
    side: str,
    support_price: float | None,
    support_ts: str | None,
    close_ts: str | None,
    causal_price_path: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Descriptive MFE/MAE after first Shadow SUPPORT through canonical close.

    Requires an event-time causal price path. Candle high/low that overlaps
    pre-confirmation time is intentionally rejected (do not approximate).
    """
    if support_ts is None or support_price is None:
        return _null_mfe_mae(
            basis=MFE_MAE_BASIS_INSUFFICIENT,
            reason=MFE_MAE_REASON_NO_SUPPORT if support_ts is None else MFE_MAE_REASON_MISSING_SUPPORT_PRICE,
        )
    start = _parse_ts(support_ts)
    end = _parse_ts(close_ts)
    if start is None or end is None:
        return _null_mfe_mae(
            basis=MFE_MAE_BASIS_INSUFFICIENT,
            reason=MFE_MAE_REASON_MISSING_TIMESTAMPS,
        )
    if not causal_price_path:
        return _null_mfe_mae(
            basis=MFE_MAE_BASIS_INSUFFICIENT,
            reason=MFE_MAE_REASON_NO_PATH,
        )

    prices: list[float] = []
    for point in causal_price_path:
        ts = _parse_ts(point.get("timestamp"))
        if ts is None:
            continue
        # Inclusive confirmation → inclusive canonical close; never before confirmation.
        if ts < start or ts > end:
            continue
        raw = point.get("price")
        if raw is None:
            continue
        try:
            prices.append(float(raw))
        except (TypeError, ValueError):
            continue

    if not prices:
        return _null_mfe_mae(
            basis=MFE_MAE_BASIS_INSUFFICIENT,
            reason=MFE_MAE_REASON_EMPTY_WINDOW,
        )

    px0 = float(support_price)
    hi = max(prices)
    lo = min(prices)
    side_u = str(side).upper()
    if side_u == "LONG":
        mfe = hi - px0
        mae = px0 - lo
    else:
        mfe = px0 - lo
        mae = hi - px0
    bps_den = abs(px0)
    mfe_bps = None if bps_den < 1e-12 else (mfe / bps_den) * 10000.0
    mae_bps = None if bps_den < 1e-12 else (mae / bps_den) * 10000.0
    return {
        "mfe_after_confirmation": mfe,
        "mae_after_confirmation": mae,
        "mfe_after_confirmation_bps": mfe_bps,
        "mae_after_confirmation_bps": mae_bps,
        "mfe_mae_basis": MFE_MAE_BASIS_EVENT,
        "mfe_mae_reason": None,
    }


def interpret_chrono_row(
    *,
    canonical_side: str,
    canonical_tf: str,
    tf_row: Mapping[str, Any] | None,
    hier_row: Mapping[str, Any] | None,
) -> str:
    if tf_row is None:
        return VERDICT_UNRESOLVED
    verdict, _ = interpret_state(
        canonical_side=canonical_side,
        family=tf_row.get("auction_family"),
        phase=tf_row.get("episode_phase"),
        hierarchy_state=None if hier_row is None else hier_row.get("hierarchy_state"),
        coverage_status="COMPLETE",
        anchor_coverage="AVAILABLE",
    )
    return verdict


@dataclass
class ChronoHit:
    timestamp: str
    price: float | None
    verdict: str
    family: str | None
    phase: str | None
    hierarchy_state: str | None
    reason_codes: list[str] = field(default_factory=list)


def trade_fields_from_raw(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy only existing canonical/paper fields. Never invent PnL or R."""
    if not raw:
        return {}
    out: dict[str, Any] = {}
    mapping = (
        ("entry_price", "entry_price"),
        ("exit_price", "exit_price"),
        ("close_price", "exit_price"),
        ("quantity", "quantity"),
        ("qty", "quantity"),
        ("gross_pnl_usd", "gross_pnl"),
        ("gross_pnl", "gross_pnl"),
        ("net_pnl_usd", "net_pnl"),
        ("net_pnl", "net_pnl"),
        ("fees", "fees"),
        ("slippage", "slippage"),
        ("r_multiple", "r_multiple"),
        ("canonical_R", "r_multiple"),
        ("exit_reason", "exit_reason"),
        ("side", "side"),
    )
    for src, dst in mapping:
        if dst in out:
            continue
        if src in raw and raw[src] is not None:
            out[dst] = raw[src]
    return out


def scan_first_hits(
    *,
    canonical_side: str,
    canonical_tf: str,
    after_ts: str,
    before_ts: str | None,
    index: ShadowHistoryIndex,
    prices_by_ts: Mapping[str, float] | None = None,
    extra_rows: Sequence[Mapping[str, Any]] | None = None,
    as_of_ts: str | None = None,
) -> tuple[dict[str, ChronoHit | None], int]:
    """First SUPPORT/REJECT/OPPOSITE after after_ts, strictly chronological, no lookahead."""
    after = _parse_ts(after_ts)
    before = _parse_ts(before_ts) if before_ts else None
    as_of = _parse_ts(as_of_ts) if as_of_ts else None
    tf = canonical_tf.upper()
    rows = list(index.tf_rows.get(tf, []))
    if extra_rows:
        rows = rows + [dict(r) for r in extra_rows]
    rows.sort(key=lambda r: str(r.get("timestamp") or ""))
    found: dict[str, ChronoHit | None] = {
        VERDICT_SUPPORT: None,
        VERDICT_REJECT: None,
        VERDICT_OPPOSITE: None,
    }
    lookahead = 0
    for row in rows:
        ts = str(row.get("timestamp") or "")
        rts = _parse_ts(ts)
        if rts is None or after is None:
            continue
        if rts <= after:
            continue
        if as_of is not None and rts > as_of:
            lookahead += 1
            continue
        if before is not None and rts > before:
            lookahead += 1
            continue  # do not use future-of-close for first_* before close
        hier = index.asof_hierarchy(ts)
        verdict = interpret_chrono_row(
            canonical_side=canonical_side,
            canonical_tf=tf,
            tf_row=row,
            hier_row=hier,
        )
        if verdict in found and found[verdict] is None:
            price = None
            if prices_by_ts and ts in prices_by_ts:
                price = prices_by_ts[ts]
            elif row.get("price") is not None:
                try:
                    price = float(row["price"])
                except (TypeError, ValueError):
                    price = None
            found[verdict] = ChronoHit(
                timestamp=ts,
                price=price,
                verdict=verdict,
                family=row.get("auction_family"),
                phase=row.get("episode_phase"),
                hierarchy_state=None if hier is None else hier.get("hierarchy_state"),
            )
        if all(found.values()):
            break
    return found, lookahead


def final_shadow_verdict(
    *,
    context_verdict: str | None,
    entry_verdict: str | None,
    first_support_ts: str | None,
    close_ts: str | None,
    had_reject: bool,
    had_opposite: bool,
) -> str:
    ctx = context_verdict or VERDICT_UNRESOLVED
    ent = entry_verdict or VERDICT_UNRESOLVED
    if VERDICT_SUPPORT in {ctx, ent}:
        return FINAL_AGREE
    if had_opposite and ent == VERDICT_OPPOSITE:
        return FINAL_OPPOSITE
    if first_support_ts and close_ts:
        fs, cl = _parse_ts(first_support_ts), _parse_ts(close_ts)
        if fs and cl and fs > cl:
            return FINAL_TOO_LATE
        if fs and cl and fs <= cl and ent in {VERDICT_WAIT, VERDICT_UNRESOLVED}:
            return FINAL_AGREE_LATE
        if fs and cl and fs <= cl and ent == VERDICT_SUPPORT:
            return FINAL_AGREE
    if first_support_ts and not close_ts and ent in {VERDICT_WAIT, VERDICT_UNRESOLVED}:
        return FINAL_AGREE_LATE
    if ent == VERDICT_OPPOSITE or had_opposite and not first_support_ts:
        return FINAL_OPPOSITE
    if ent == VERDICT_REJECT or (had_reject and not first_support_ts):
        return FINAL_REJECT
    if ent in {VERDICT_UNRESOLVED, None} and ctx == VERDICT_UNRESOLVED:
        return FINAL_UNRESOLVED
    return FINAL_UNRESOLVED


def build_outcome(
    *,
    case_id: str,
    context_ckp: Mapping[str, Any] | None,
    entry_ckp: Mapping[str, Any] | None,
    close_ckp: Mapping[str, Any] | None,
    context_verdict: Mapping[str, Any] | None,
    entry_verdict: Mapping[str, Any] | None,
    index: ShadowHistoryIndex,
    canonical_trade: Mapping[str, Any] | None = None,
    chrono_prices: Mapping[str, float] | None = None,
    extra_anchor_rows: Sequence[Mapping[str, Any]] | None = None,
    causal_price_path: Sequence[Mapping[str, Any]] | None = None,
    logic_version: str = "AES_V1",
    logic_fingerprint: str = "",
    outcome_schema_version: int = OUTCOME_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build immutable case outcome. Post-mortem data must not be passed in."""
    side = (
        (entry_ckp or close_ckp or context_ckp or {}).get("canonical_side")
        or (canonical_trade or {}).get("side")
    )
    tf = str((entry_ckp or close_ckp or context_ckp or {}).get("canonical_timeframe") or "M15")
    ctx_v = None if context_verdict is None else str(context_verdict.get("checkpoint_verdict"))
    ent_v = None if entry_verdict is None else str(entry_verdict.get("checkpoint_verdict"))
    entry_ts = None if entry_ckp is None else entry_ckp.get("canonical_timestamp")
    ctx_ts = None if context_ckp is None else context_ckp.get("canonical_timestamp")
    close_ts = None if close_ckp is None else close_ckp.get("canonical_timestamp")
    trade = dict(canonical_trade or {})
    entry_price = trade.get("entry_price")
    if entry_price is None and entry_ckp is not None:
        entry_price = entry_ckp.get("entry_price")
    close_price = trade.get("exit_price")
    if close_price is None and close_ckp is not None:
        close_price = close_ckp.get("close_price")
    qty = trade.get("quantity")
    net = trade.get("net_pnl_usd") if "net_pnl_usd" in trade else trade.get("net_pnl")
    gross = trade.get("gross_pnl_usd") if "gross_pnl_usd" in trade else trade.get("gross_pnl")
    r_mult = trade.get("r_multiple") if "r_multiple" in trade else trade.get("canonical_R")
    exit_reason = trade.get("exit_reason")
    if exit_reason is None and close_ckp is not None:
        exit_reason = close_ckp.get("close_reason")

    lookahead = 0
    empty = {VERDICT_SUPPORT: None, VERDICT_REJECT: None, VERDICT_OPPOSITE: None}
    if ctx_ts or entry_ts:
        hits_after_ctx, la_ctx = scan_first_hits(
            canonical_side=str(side or ""),
            canonical_tf=tf,
            after_ts=str(ctx_ts or entry_ts or ""),
            before_ts=None,
            index=index,
            prices_by_ts=chrono_prices,
            extra_rows=extra_anchor_rows,
        )
        lookahead += la_ctx
    else:
        hits_after_ctx = empty
    if entry_ts:
        hits_after_entry, la_ent = scan_first_hits(
            canonical_side=str(side or ""),
            canonical_tf=tf,
            after_ts=str(entry_ts or ""),
            before_ts=None,
            index=index,
            prices_by_ts=chrono_prices,
            extra_rows=extra_anchor_rows,
        )
        lookahead += la_ent
    else:
        hits_after_entry = empty

    # Confirmation uses first SUPPORT after entry, or entry itself if already SUPPORT.
    first_support: ChronoHit | None = None
    confirmation_delay = None
    if ent_v == VERDICT_SUPPORT and entry_ts:
        first_support = ChronoHit(
            timestamp=str(entry_ts),
            price=None if entry_price is None else float(entry_price),
            verdict=VERDICT_SUPPORT,
            family=None if entry_verdict is None else entry_verdict.get("anchor_family"),
            phase=None if entry_verdict is None else entry_verdict.get("anchor_phase"),
            hierarchy_state=None if entry_verdict is None else entry_verdict.get("hierarchy_state"),
        )
        confirmation_delay = 0.0
    elif hits_after_entry.get(VERDICT_SUPPORT):
        first_support = hits_after_entry[VERDICT_SUPPORT]
        confirmation_delay = _age(first_support.timestamp, str(entry_ts))

    first_reject = hits_after_entry.get(VERDICT_REJECT)
    first_opposite = hits_after_entry.get(VERDICT_OPPOSITE)
    first_inv = None
    if ent_v == VERDICT_SUPPORT:
        candidates = [h for h in (first_reject, first_opposite) if h is not None]
        if candidates:
            first_inv = sorted(candidates, key=lambda h: h.timestamp)[0]

    final = final_shadow_verdict(
        context_verdict=ctx_v,
        entry_verdict=ent_v,
        first_support_ts=None if first_support is None else first_support.timestamp,
        close_ts=None if close_ts is None else str(close_ts),
        had_reject=first_reject is not None or ent_v == VERDICT_REJECT,
        had_opposite=first_opposite is not None or ent_v == VERDICT_OPPOSITE,
    )

    reasons: list[str] = []
    if ent_v == VERDICT_SUPPORT:
        reasons.append("ANCHOR_SUPPORTS_CANONICAL")
    if first_support and ent_v != VERDICT_SUPPORT:
        reasons.append("SHADOW_CONFIRMATION_AFTER_ENTRY")
    if first_reject:
        reasons.append("SHADOW_REJECTION_AFTER_ENTRY")
    if first_opposite:
        reasons.append("SHADOW_OPPOSITE_AFTER_ENTRY")

    try:
        net_f = None if net is None else float(net)
    except (TypeError, ValueError):
        net_f = None
    if net_f is not None and net_f > 0:
        reasons.append("CANONICAL_WIN")
    elif net_f is not None and net_f < 0:
        reasons.append("CANONICAL_LOSS")
    elif net_f == 0:
        reasons.append("CANONICAL_FLAT")

    improvement = None
    delta_bps = None
    timing_pnl = None
    support_px = None if first_support is None else first_support.price
    try:
        entry_px = None if entry_price is None else float(entry_price)
        exit_px = None if close_price is None else float(close_price)
    except (TypeError, ValueError):
        entry_px = None
        exit_px = None
    if support_px is not None and entry_px is not None and ent_v == VERDICT_WAIT:
        improvement = entry_improvement(str(side), entry_px, support_px)
        delta_bps = entry_delta_bps(entry_px, improvement)
        if improvement > 0:
            reasons.append("WAIT_IMPROVED_ENTRY")
        elif improvement < 0:
            reasons.append("WAIT_WORSENED_ENTRY")
    elif support_px is not None and entry_px is not None and confirmation_delay not in {None, 0.0}:
        improvement = entry_improvement(str(side), entry_px, support_px)
        delta_bps = entry_delta_bps(entry_px, improvement)
    if support_px is not None and exit_px is not None:
        try:
            qty_f = None if qty is None else float(qty)
        except (TypeError, ValueError):
            qty_f = None
        timing_pnl = timing_same_exit_pnl(
            side=str(side), support_price=support_px, exit_price=exit_px, quantity=qty_f
        )

    secondary: list[str] = []
    primary = LABEL_UNRESOLVED
    agreeish = final in {FINAL_AGREE, FINAL_AGREE_LATE}
    rejectish = ent_v in {VERDICT_REJECT, VERDICT_OPPOSITE} or final in {FINAL_REJECT, FINAL_OPPOSITE}

    if net_f is not None and net_f > 0 and agreeish:
        primary = LABEL_WIN_AGREE
    elif net_f is not None and net_f < 0 and agreeish:
        primary = LABEL_LOSS_AGREE
    elif net_f is not None and net_f < 0 and rejectish:
        primary = LABEL_LOSS_REJECT
        secondary.append(LABEL_AVOIDED)
        reasons.append("FILTER_WOULD_AVOID_LOSS")
    elif net_f is not None and net_f > 0 and rejectish:
        primary = LABEL_WIN_REJECT
        secondary.append(LABEL_MISSED)
        reasons.append("FILTER_WOULD_MISS_WIN")
    elif final == FINAL_UNRESOLVED:
        primary = LABEL_UNRESOLVED
    else:
        primary = LABEL_NO_MEANINGFUL

    if improvement is not None:
        if improvement > 0:
            secondary.append(LABEL_BETTER_ENTRY)
        elif improvement < 0:
            secondary.append(LABEL_WORSE_ENTRY)
        else:
            secondary.append(LABEL_NO_DIFF)

    if ent_v == VERDICT_OPPOSITE and entry_px is not None and exit_px is not None:
        moved_with_shadow = (exit_px < entry_px) if str(side).upper() == "LONG" else (exit_px > entry_px)
        if moved_with_shadow:
            secondary.append(LABEL_OPPOSITE_BETTER)

    coverage = (close_ckp or entry_ckp or context_ckp or {}).get("coverage_status")
    close_id = None if close_ckp is None else str(close_ckp.get("checkpoint_id") or "")
    if first_support is None:
        mfe_mae = _null_mfe_mae(
            basis=MFE_MAE_BASIS_INSUFFICIENT,
            reason=MFE_MAE_REASON_NO_SUPPORT,
        )
    else:
        # Window is locked to first SUPPORT → canonical close. Post-mortem must not
        # extend or rewrite this excursion measurement.
        mfe_mae = compute_mfe_mae_after_confirmation(
            side=str(side or ""),
            support_price=None if first_support.price is None else float(first_support.price),
            support_ts=first_support.timestamp,
            close_ts=None if close_ts is None else str(close_ts),
            causal_price_path=causal_price_path,
        )
    return {
        "outcome_id": deterministic_outcome_id(case_id, close_id or case_id),
        "shadow_case_id": case_id,
        "outcome_schema_version": int(outcome_schema_version),
        "context_checkpoint_id": None if context_ckp is None else context_ckp.get("checkpoint_id"),
        "entry_checkpoint_id": None if entry_ckp is None else entry_ckp.get("checkpoint_id"),
        "close_checkpoint_id": None if close_ckp is None else close_ckp.get("checkpoint_id"),
        "canonical_side": side,
        "canonical_timeframe": tf,
        "context_verdict": ctx_v,
        "entry_verdict": ent_v,
        "final_shadow_verdict": final,
        "canonical_entry_timestamp": entry_ts,
        "canonical_entry_price": entry_px,
        "canonical_close_timestamp": close_ts,
        "canonical_close_price": exit_px,
        "canonical_exit_reason": exit_reason,
        "canonical_gross_pnl": None if gross is None else gross,
        "canonical_net_pnl": net_f,
        "canonical_R": r_mult,
        "first_support_timestamp": None if first_support is None else first_support.timestamp,
        "first_support_price": None if first_support is None else first_support.price,
        "first_reject_timestamp": None if first_reject is None else first_reject.timestamp,
        "first_reject_price": None if first_reject is None else first_reject.price,
        "first_opposite_timestamp": None if first_opposite is None else first_opposite.timestamp,
        "first_opposite_price": None if first_opposite is None else first_opposite.price,
        "first_invalidation_timestamp": None if first_inv is None else first_inv.timestamp,
        "first_invalidation_price": None if first_inv is None else first_inv.price,
        "confirmation_delay_sec": confirmation_delay,
        "entry_improvement": improvement,
        "entry_delta_bps": delta_bps,
        "timing_counterfactual_same_exit_pnl": timing_pnl,
        "counterfactual_type": COUNTERFACTUAL_TYPE,
        "mfe_after_confirmation": mfe_mae["mfe_after_confirmation"],
        "mae_after_confirmation": mfe_mae["mae_after_confirmation"],
        "mfe_after_confirmation_bps": mfe_mae["mfe_after_confirmation_bps"],
        "mae_after_confirmation_bps": mfe_mae["mae_after_confirmation_bps"],
        "mfe_mae_basis": mfe_mae["mfe_mae_basis"],
        "mfe_mae_reason": mfe_mae["mfe_mae_reason"],
        "primary_outcome_label": primary,
        "secondary_outcome_labels": secondary,
        "coverage_status": coverage,
        "reason_codes": sorted(set(reasons)),
        "logic_version": logic_version,
        "logic_fingerprint": logic_fingerprint,
        "created_at": _iso_now(),
        # Debug/research only — not a trading policy.
        "aes5_stop_policy": None,
        "aes5_tp_policy": None,
        "aes5_lookahead_skipped": lookahead,
        "first_support_after_context_timestamp": (
            None if not hits_after_ctx.get(VERDICT_SUPPORT) else hits_after_ctx[VERDICT_SUPPORT].timestamp
        ),
    }


@dataclass
class OutcomeEngine:
    logic_version: str = "AES_V1"
    logic_fingerprint: str = ""
    index: ShadowHistoryIndex = field(default_factory=ShadowHistoryIndex)
    _seen: dict[str, str] = field(default_factory=dict)
    closed_cases_evaluated: int = 0
    duplicate_suppressed: int = 0
    payload_conflicts: int = 0
    canonical_wins_shadow_agree: int = 0
    canonical_losses_shadow_reject: int = 0
    shadow_avoided_loss_count: int = 0
    shadow_missed_win_count: int = 0
    shadow_better_entry_count: int = 0
    canonical_better_entry_count: int = 0
    last_outcome_id: str | None = None
    lookahead_violations: int = 0

    def ingest(self, record: Mapping[str, Any]) -> dict[str, Any]:
        oid = str(record.get("outcome_id") or "")
        payload_hash = hashlib.sha1(
            json.dumps({k: v for k, v in record.items() if k != "created_at"}, sort_keys=True, default=str).encode()
        ).hexdigest()
        if oid in self._seen:
            if self._seen[oid] == payload_hash:
                self.duplicate_suppressed += 1
                return {"written": False, "duplicate": True, "payload_conflict": False, "record": dict(record)}
            self.payload_conflicts += 1
            return {"written": False, "duplicate": False, "payload_conflict": True, "record": dict(record)}
        self._seen[oid] = payload_hash
        self.closed_cases_evaluated += 1
        self.last_outcome_id = oid
        lab = record.get("primary_outcome_label")
        secs = list(record.get("secondary_outcome_labels") or [])
        if lab == LABEL_WIN_AGREE:
            self.canonical_wins_shadow_agree += 1
        if lab == LABEL_LOSS_REJECT:
            self.canonical_losses_shadow_reject += 1
        if LABEL_AVOIDED in secs:
            self.shadow_avoided_loss_count += 1
        if LABEL_MISSED in secs:
            self.shadow_missed_win_count += 1
        if LABEL_BETTER_ENTRY in secs:
            self.shadow_better_entry_count += 1
        if LABEL_WORSE_ENTRY in secs:
            self.canonical_better_entry_count += 1
        if len(self._seen) > 10000:
            keys = list(self._seen.keys())[-5000:]
            self._seen = {k: self._seen[k] for k in keys}
        return {"written": True, "duplicate": False, "payload_conflict": False, "record": dict(record)}

    def health_fields(self) -> dict[str, Any]:
        return {
            "closed_cases_evaluated": self.closed_cases_evaluated,
            "canonical_wins_shadow_agree": self.canonical_wins_shadow_agree,
            "canonical_losses_shadow_reject": self.canonical_losses_shadow_reject,
            "shadow_avoided_loss_count": self.shadow_avoided_loss_count,
            "shadow_missed_win_count": self.shadow_missed_win_count,
            "shadow_better_entry_count": self.shadow_better_entry_count,
            "canonical_better_entry_count": self.canonical_better_entry_count,
            "last_outcome_id": self.last_outcome_id,
        }

    def restore(self, path) -> int:
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return 0
        n = 0
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                oid = row.get("outcome_id")
                if not oid:
                    continue
                self._seen[str(oid)] = hashlib.sha1(
                    json.dumps({k: v for k, v in row.items() if k != "created_at"}, sort_keys=True, default=str).encode()
                ).hexdigest()
                n += 1
        return n
