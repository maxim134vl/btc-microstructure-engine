"""Trade Toxicity branch (MODEL-4) — observational / non-blocking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from btc_ml.model_assurance.toxic_box.common import append_unique, base_event, read_jsonl
from btc_ml.trading.intrabar_paper.books import EpochBooks


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_matches(fill: float | None, ref: float | None, *, tol: float = 1e-8) -> bool:
    if fill is None or ref is None:
        return False
    return abs(float(fill) - float(ref)) <= tol


def evaluate_trade_toxicity(
    *,
    active: dict[str, Any],
    books: EpochBooks,
    economic_evaluations: list[dict[str, Any]],
    config: dict[str, Any],
    max_bbo_age_ms: float,
    events_path: Path,
    existing_ids: set[str],
) -> dict[str, Any]:
    trade_cfg = config.get("trade") or {}
    severe_r = float(trade_cfg.get("severe_loss_r_lte", -1.25))
    risk_tol = float(trade_cfg.get("risk_tolerance_usd", 0.01))

    epoch_id = str(active.get("paper_epoch_id") or "")
    trades = [
        t
        for t in books.read_all("trades")
        if str(t.get("paper_epoch_id") or "") == epoch_id
        and str(t.get("status") or "").upper() == "CLOSED"
    ]
    fills = [f for f in books.read_all("fills") if str(f.get("paper_epoch_id") or "") == epoch_id]
    orders = [o for o in books.read_all("orders") if str(o.get("paper_epoch_id") or "") == epoch_id]
    commands = [c for c in books.read_all("commands") if str(c.get("paper_epoch_id") or "") == epoch_id]

    fills_by_trade_side: dict[str, list[dict[str, Any]]] = {}
    # Fills don't always carry trade_id; join via order/command/timeframe+side+ts loosely
    cmds_by_id = {str(c.get("command_id")): c for c in commands if c.get("command_id")}
    orders_by_id = {str(o.get("order_id")): o for o in orders if o.get("order_id")}

    econ_by_trade = {
        str(e.get("trade_id")): e
        for e in economic_evaluations
        if str(e.get("paper_epoch_id") or "") == epoch_id
        and str(e.get("registry_record_id") or "") == str(active.get("registry_record_id") or "")
    }

    created = 0
    candidates = 0
    confirmed = 0
    evaluable = 0
    not_evaluable: dict[str, int] = {}
    last_event_at = None

    def _emit(**kwargs: Any) -> None:
        nonlocal created, candidates, confirmed, last_event_at
        row = base_event(active=active, **kwargs)
        if append_unique(events_path, row, existing_ids=existing_ids):
            created += 1
            if row["status"] == "CANDIDATE":
                candidates += 1
            elif row["status"] == "CONFIRMED":
                confirmed += 1
            last_event_at = row["detected_at"]

    for trade in trades:
        trade_id = str(trade.get("trade_id") or "")
        if not trade_id:
            continue
        evaluable += 1
        side = str(trade.get("side") or trade.get("direction") or "").upper()
        tf = str(trade.get("timeframe") or "").upper()

        # Lineage
        ctx_id = trade.get("context_event_id")
        episode = trade.get("lifecycle_episode_id")
        if not ctx_id or not episode or not tf or not trade.get("paper_epoch_id"):
            # Try enrich from entry command via position signals — if still missing, breach
            related_cmds = [
                c
                for c in commands
                if str(c.get("timeframe") or "").upper() == tf
                and str(c.get("side") or "").upper() == side
                and str(c.get("action") or "").upper() == "ENTRY"
            ]
            if related_cmds and not ctx_id:
                ctx_id = related_cmds[-1].get("context_event_id")
            if related_cmds and not episode:
                episode = related_cmds[-1].get("lifecycle_episode_id") or trade.get("lifecycle_episode_id")
            if not ctx_id or not episode or not tf or not trade.get("paper_epoch_id"):
                _emit(
                    branch="TRADE",
                    subtype="TRD_ENTRY_WITHOUT_CONTEXT" if not ctx_id else "TRD_LINEAGE_INCOMPLETE",
                    severity="CRITICAL",
                    status="CONFIRMED",
                    subject_event_at=trade.get("exit_ts") or trade.get("entry_ts"),
                    timeframe=tf,
                    direction=side,
                    context_event_id=ctx_id,
                    lifecycle_episode_id=episode,
                    trade_id=trade_id,
                    position_id=trade.get("position_id"),
                    subject_id=trade_id,
                    expected_value=["context_event_id", "lifecycle_episode_id", "timeframe", "paper_epoch_id"],
                    observed_value={
                        "context_event_id": ctx_id,
                        "lifecycle_episode_id": episode,
                        "timeframe": tf,
                        "paper_epoch_id": trade.get("paper_epoch_id"),
                    },
                )

        # Entry/exit fills for this trade timeframe/side near timestamps
        entry_fills = [
            f
            for f in fills
            if str(f.get("action") or "").upper() == "ENTRY"
            and str(f.get("timeframe") or "").upper() == tf
            and str(f.get("side") or "").upper() == side
        ]
        exit_fills = [
            f
            for f in fills
            if str(f.get("action") or "").upper() == "EXIT"
            and str(f.get("timeframe") or "").upper() == tf
            and str(f.get("side") or "").upper() == side
        ]
        entry_fill = entry_fills[-1] if entry_fills else None
        exit_fill = exit_fills[-1] if exit_fills else None

        # Wrong-side fill
        for fill, action in ((entry_fill, "ENTRY"), (exit_fill, "EXIT")):
            if fill is None:
                not_evaluable[f"TRADE_{action}_FILL_MISSING"] = not_evaluable.get(f"TRADE_{action}_FILL_MISSING", 0) + 1
                continue
            fill_px = _f(fill.get("paper_fill_price") or fill.get("gross_entry_price") or fill.get("gross_exit_price"))
            bid = _f(fill.get("fill_bid") if fill.get("fill_bid") is not None else fill.get("best_bid"))
            ask = _f(fill.get("fill_ask") if fill.get("fill_ask") is not None else fill.get("best_ask"))
            if fill_px is None or bid is None or ask is None:
                not_evaluable[f"TRADE_{action}_BBO_MISSING"] = not_evaluable.get(f"TRADE_{action}_BBO_MISSING", 0) + 1
                continue
            if action == "ENTRY":
                expected = ask if side == "LONG" else bid
                ok = _price_matches(fill_px, expected)
            else:
                expected = bid if side == "LONG" else ask
                ok = _price_matches(fill_px, expected)
            if not ok:
                _emit(
                    branch="TRADE",
                    subtype="TRD_WRONG_SIDE_FILL",
                    severity="CRITICAL",
                    status="CONFIRMED",
                    subject_event_at=fill.get("ts"),
                    timeframe=tf,
                    direction=side,
                    trade_id=trade_id,
                    position_id=trade.get("position_id"),
                    order_id=fill.get("order_id"),
                    fill_id=fill.get("fill_id"),
                    subject_id=f"{trade_id}|{action}",
                    expected_value=expected,
                    observed_value={"fill": fill_px, "bid": bid, "ask": ask, "action": action},
                )

            # Stale BBO
            age = _f(fill.get("bbo_age_ms"))
            if age is None:
                not_evaluable["TRADE_BBO_AGE_MISSING"] = not_evaluable.get("TRADE_BBO_AGE_MISSING", 0) + 1
            elif age > float(max_bbo_age_ms):
                _emit(
                    branch="TRADE",
                    subtype="TRD_STALE_BBO_USED",
                    severity="CRITICAL",
                    status="CONFIRMED",
                    subject_event_at=fill.get("ts"),
                    timeframe=tf,
                    direction=side,
                    trade_id=trade_id,
                    fill_id=fill.get("fill_id"),
                    subject_id=f"{trade_id}|{action}|STALE",
                    expected_value=f"<={max_bbo_age_ms}",
                    observed_value=age,
                    threshold={"max_bbo_age_ms": max_bbo_age_ms},
                )

            # Future BBO: bbo_receive_monotonic_ns <= command_monotonic_ns
            bbo_mono = fill.get("bbo_receive_monotonic_ns")
            cmd_id = fill.get("command_id")
            cmd = cmds_by_id.get(str(cmd_id)) if cmd_id else None
            cmd_mono = None
            if cmd is not None:
                cmd_mono = cmd.get("command_monotonic_ns")
            if cmd_mono is None:
                cmd_mono = fill.get("command_monotonic_ns") or fill.get("trigger_monotonic_ns")
            if bbo_mono is None or cmd_mono is None:
                not_evaluable["TRADE_BBO_CAUSALITY_FIELDS_MISSING"] = (
                    not_evaluable.get("TRADE_BBO_CAUSALITY_FIELDS_MISSING", 0) + 1
                )
            else:
                try:
                    if int(bbo_mono) > int(cmd_mono):
                        _emit(
                            branch="TRADE",
                            subtype="TRD_FUTURE_BBO_USED",
                            severity="CRITICAL",
                            status="CONFIRMED",
                            subject_event_at=fill.get("ts"),
                            timeframe=tf,
                            direction=side,
                            trade_id=trade_id,
                            fill_id=fill.get("fill_id"),
                            subject_id=f"{trade_id}|{action}|FUTURE_BBO",
                            expected_value="bbo_receive_monotonic_ns <= command_monotonic_ns",
                            observed_value={"bbo": bbo_mono, "command": cmd_mono},
                        )
                except (TypeError, ValueError):
                    not_evaluable["TRADE_BBO_CAUSALITY_PARSE"] = not_evaluable.get("TRADE_BBO_CAUSALITY_PARSE", 0) + 1

            # Explicit next-bar/close fill source
            src = str(
                fill.get("execution_source")
                or fill.get("fill_source")
                or fill.get("paper_entry_basis")
                or ""
            ).upper()
            if any(tok in src for tok in ("CANDLE_CLOSE", "NEXT_BAR", "NEXT_COMPLETED_BAR", "BAR_CLOSE")):
                _emit(
                    branch="TRADE",
                    subtype="TRD_NEXT_BAR_OR_CLOSE_FILL",
                    severity="CRITICAL",
                    status="CONFIRMED",
                    subject_event_at=fill.get("ts"),
                    timeframe=tf,
                    direction=side,
                    trade_id=trade_id,
                    fill_id=fill.get("fill_id"),
                    subject_id=f"{trade_id}|{action}|CLOSE_FILL",
                    expected_value="BBO_INTRABAR",
                    observed_value=src,
                )

        # Risk breach vs configured budget on trade
        risk = _f(trade.get("risk_amount_usd"))
        allowed = _f(trade.get("allowed_risk_budget_usd") or trade.get("max_risk_usd"))
        if risk is None:
            not_evaluable["TRADE_RISK_MISSING"] = not_evaluable.get("TRADE_RISK_MISSING", 0) + 1
        elif allowed is not None and risk > allowed + risk_tol:
            _emit(
                branch="TRADE",
                subtype="TRD_RISK_BREACH",
                severity="CRITICAL",
                status="CONFIRMED",
                subject_event_at=trade.get("exit_ts"),
                timeframe=tf,
                direction=side,
                trade_id=trade_id,
                subject_id=f"{trade_id}|RISK",
                expected_value=allowed,
                observed_value=risk,
                threshold={"risk_tolerance_usd": risk_tol},
            )

        # Economic evaluation candidates / reconciliation
        econ = econ_by_trade.get(trade_id)
        if econ is None:
            not_evaluable["TRADE_ECON_EVAL_MISSING"] = not_evaluable.get("TRADE_ECON_EVAL_MISSING", 0) + 1
        else:
            if str(econ.get("pnl_reconciliation_status") or "") == "MISMATCH":
                _emit(
                    branch="TRADE",
                    subtype="TRD_PNL_RECONCILIATION_MISMATCH",
                    severity="WARNING",
                    status="CONFIRMED",
                    subject_event_at=econ.get("evaluated_at") or trade.get("exit_ts"),
                    timeframe=tf,
                    direction=side,
                    trade_id=trade_id,
                    subject_id=f"{trade_id}|PNL",
                    expected_value=econ.get("canonical_net_pnl_usd"),
                    observed_value=econ.get("net_pnl_usd"),
                    threshold={"pnl_difference_usd": econ.get("pnl_difference_usd")},
                )
            r_mult = _f(econ.get("realized_r_multiple"))
            if r_mult is not None and r_mult <= severe_r:
                _emit(
                    branch="TRADE",
                    subtype="TRD_SEVERE_LOSS",
                    severity="WATCH",
                    status="CANDIDATE",
                    subject_event_at=econ.get("evaluated_at") or trade.get("exit_ts"),
                    timeframe=tf,
                    direction=side,
                    trade_id=trade_id,
                    subject_id=f"{trade_id}|SEVERE",
                    expected_value=f">{severe_r}",
                    observed_value=r_mult,
                    threshold={"severe_loss_r_lte": severe_r},
                )
            net = _f(econ.get("net_pnl_usd"))
            gross = _f(econ.get("gross_pnl_usd"))
            fees = _f(econ.get("total_fee_usd")) or 0.0
            slip = _f(econ.get("total_slippage_usd")) or 0.0
            if net is not None and gross is not None and net < 0 and (fees + slip) > abs(gross):
                _emit(
                    branch="TRADE",
                    subtype="TRD_COST_DOMINATED",
                    severity="WATCH",
                    status="CANDIDATE",
                    subject_event_at=econ.get("evaluated_at") or trade.get("exit_ts"),
                    timeframe=tf,
                    direction=side,
                    trade_id=trade_id,
                    subject_id=f"{trade_id}|COST",
                    expected_value="costs <= abs(gross)",
                    observed_value={"net": net, "gross": gross, "fees": fees, "slippage": slip},
                )

    # Duplicate episode entry
    episode_entries: dict[str, list[str]] = {}
    for c in commands:
        if str(c.get("action") or "").upper() != "ENTRY":
            continue
        ep = str(c.get("lifecycle_episode_id") or "")
        tf = str(c.get("timeframe") or "")
        if not ep:
            continue
        key = f"{tf}|{ep}"
        episode_entries.setdefault(key, []).append(str(c.get("command_id")))
    for key, ids in episode_entries.items():
        if len(ids) > 1:
            tf, ep = key.split("|", 1)
            _emit(
                branch="TRADE",
                subtype="TRD_DUPLICATE_EPISODE_ENTRY",
                severity="CRITICAL",
                status="CONFIRMED",
                subject_event_at=None,
                timeframe=tf,
                lifecycle_episode_id=ep,
                subject_id=key,
                expected_value=1,
                observed_value=len(ids),
                evidence={"command_ids": ids},
            )

    events = [e for e in read_jsonl(events_path) if e.get("branch") == "TRADE"]
    return {
        "trades_seen": len(trades),
        "trades_evaluable": evaluable,
        "toxic_candidates": sum(1 for e in events if e.get("status") == "CANDIDATE"),
        "confirmed_events": sum(1 for e in events if e.get("status") == "CONFIRMED"),
        "created_this_pass": created,
        "not_evaluable_checks": not_evaluable,
        "last_trade_event_at": last_event_at or (events[-1].get("detected_at") if events else None),
        "events": events,
    }
