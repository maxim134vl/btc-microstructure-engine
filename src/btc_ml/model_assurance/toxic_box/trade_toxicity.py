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


def _parse_timestamp(
    value: Any,
):
    from datetime import (
        datetime,
        timezone,
    )

    raw = str(
        value
        if value is not None
        else ""
    ).strip()

    if not raw:
        return None

    try:
        parsed = datetime.fromisoformat(
            raw.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def _same_timestamp(
    left: Any,
    right: Any,
    *,
    tolerance_ms: float = 0.1,
) -> bool:
    left_ts = _parse_timestamp(left)
    right_ts = _parse_timestamp(right)

    if left_ts is None or right_ts is None:
        return False

    return (
        abs(
            (
                left_ts - right_ts
            ).total_seconds()
        )
        <= tolerance_ms / 1000.0
    )


def _action(
    row: dict[str, Any],
) -> str:
    return str(
        row.get("action")
        or ""
    ).upper()


def _timeframe(
    row: dict[str, Any],
) -> str:
    return str(
        row.get("timeframe")
        or ""
    ).upper()


def _side(
    row: dict[str, Any],
) -> str:
    return str(
        row.get("side")
        or row.get("direction")
        or ""
    ).upper()


def _deduplicate_fills(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[
        dict[str, Any]
    ] = []
    seen: set[str] = set()

    for index, row in enumerate(rows):
        fill_id = str(
            row.get("fill_id")
            or ""
        )

        identity = (
            fill_id
            if fill_id
            else f"ROW_{index}_{id(row)}"
        )

        if identity in seen:
            continue

        seen.add(identity)
        result.append(row)

    return result


def _resolve_entry_fill_candidates(
    *,
    trade: dict[str, Any],
    position_rows: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    fills_by_id: dict[str, dict[str, Any]],
    fills_by_command: dict[
        str,
        list[dict[str, Any]],
    ],
    fills_by_order: dict[
        str,
        list[dict[str, Any]],
    ],
    orders_by_command: dict[
        str,
        list[dict[str, Any]],
    ],
) -> list[dict[str, Any]]:
    candidates: list[
        dict[str, Any]
    ] = []

    direct_fill_id = str(
        trade.get("entry_fill_id")
        or ""
    )

    if (
        direct_fill_id
        and direct_fill_id
        in fills_by_id
    ):
        candidates.append(
            fills_by_id[
                direct_fill_id
            ]
        )

    direct_order_id = str(
        trade.get("entry_order_id")
        or ""
    )

    if direct_order_id:
        candidates.extend(
            fills_by_order.get(
                direct_order_id,
                [],
            )
        )

    direct_command_id = str(
        trade.get("entry_command_id")
        or ""
    )

    if direct_command_id:
        candidates.extend(
            fills_by_command.get(
                direct_command_id,
                [],
            )
        )

        for order in (
            orders_by_command.get(
                direct_command_id,
                [],
            )
        ):
            candidates.extend(
                fills_by_order.get(
                    str(
                        order.get("order_id")
                        or ""
                    ),
                    [],
                )
            )

    trade_tf = _timeframe(trade)
    trade_side = _side(trade)

    for position in position_rows:
        fill_id = str(
            position.get(
                "entry_fill_id"
            )
            or ""
        )

        if (
            fill_id
            and fill_id
            in fills_by_id
        ):
            candidates.append(
                fills_by_id[fill_id]
            )

        command_id = str(
            position.get(
                "entry_command_id"
            )
            or ""
        )

        if command_id:
            candidates.extend(
                fills_by_command.get(
                    command_id,
                    [],
                )
            )

            for order in (
                orders_by_command.get(
                    command_id,
                    [],
                )
            ):
                candidates.extend(
                    fills_by_order.get(
                        str(
                            order.get(
                                "order_id"
                            )
                            or ""
                        ),
                        [],
                    )
                )

        opened_at = position.get(
            "opened_at"
        )

        if opened_at:
            candidates.extend(
                [
                    fill
                    for fill in fills
                    if _action(fill)
                    == "ENTRY"
                    and _timeframe(fill)
                    == trade_tf
                    and _side(fill)
                    == trade_side
                    and _same_timestamp(
                        fill.get("ts"),
                        opened_at,
                    )
                ]
            )

    exact_candidates = [
        fill
        for fill in _deduplicate_fills(
            candidates
        )
        if _action(fill)
        == "ENTRY"
    ]

    if exact_candidates:
        return exact_candidates

    # Compatibility for legacy rows without position/order lineage.
    # Returning the complete fallback set is safe:
    # one candidate is usable, multiple candidates become AMBIGUOUS.
    fallback_candidates = [
        fill
        for fill in fills
        if _action(fill)
        == "ENTRY"
        and _timeframe(fill)
        == trade_tf
        and _side(fill)
        == trade_side
    ]

    return _deduplicate_fills(
        fallback_candidates
    )


def _resolve_exit_fill_candidates(
    *,
    trade: dict[str, Any],
    position_rows: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    fills_by_id: dict[str, dict[str, Any]],
    fills_by_command: dict[
        str,
        list[dict[str, Any]],
    ],
    fills_by_order: dict[
        str,
        list[dict[str, Any]],
    ],
    orders_by_command: dict[
        str,
        list[dict[str, Any]],
    ],
) -> list[dict[str, Any]]:
    candidates: list[
        dict[str, Any]
    ] = []

    for fill_field in (
        "exit_fill_id",
        "closing_fill_id",
    ):
        fill_id = str(
            trade.get(fill_field)
            or ""
        )

        if (
            fill_id
            and fill_id
            in fills_by_id
        ):
            candidates.append(
                fills_by_id[fill_id]
            )

    for order_field in (
        "exit_order_id",
        "closing_order_id",
    ):
        order_id = str(
            trade.get(order_field)
            or ""
        )

        if order_id:
            candidates.extend(
                fills_by_order.get(
                    order_id,
                    [],
                )
            )

    for command_field in (
        "exit_command_id",
        "closing_command_id",
    ):
        command_id = str(
            trade.get(command_field)
            or ""
        )

        if not command_id:
            continue

        candidates.extend(
            fills_by_command.get(
                command_id,
                [],
            )
        )

        for order in (
            orders_by_command.get(
                command_id,
                [],
            )
        ):
            candidates.extend(
                fills_by_order.get(
                    str(
                        order.get("order_id")
                        or ""
                    ),
                    [],
                )
            )

    trade_tf = _timeframe(trade)
    trade_side = _side(trade)
    exit_ts = trade.get("exit_ts")

    if exit_ts:
        candidates.extend(
            [
                fill
                for fill in fills
                if _action(fill)
                == "EXIT"
                and _timeframe(fill)
                == trade_tf
                and _side(fill)
                == trade_side
                and _same_timestamp(
                    fill.get("ts"),
                    exit_ts,
                )
            ]
        )

    for position in position_rows:
        for fill_field in (
            "exit_fill_id",
            "closing_fill_id",
        ):
            fill_id = str(
                position.get(fill_field)
                or ""
            )

            if (
                fill_id
                and fill_id
                in fills_by_id
            ):
                candidates.append(
                    fills_by_id[fill_id]
                )

        for command_field in (
            "exit_command_id",
            "closing_command_id",
        ):
            command_id = str(
                position.get(
                    command_field
                )
                or ""
            )

            if not command_id:
                continue

            candidates.extend(
                fills_by_command.get(
                    command_id,
                    [],
                )
            )

            for order in (
                orders_by_command.get(
                    command_id,
                    [],
                )
            ):
                candidates.extend(
                    fills_by_order.get(
                        str(
                            order.get(
                                "order_id"
                            )
                            or ""
                        ),
                        [],
                    )
                )

        closed_at = position.get(
            "closed_at"
        )

        if closed_at:
            candidates.extend(
                [
                    fill
                    for fill in fills
                    if _action(fill)
                    == "EXIT"
                    and _timeframe(fill)
                    == trade_tf
                    and _side(fill)
                    == trade_side
                    and _same_timestamp(
                        fill.get("ts"),
                        closed_at,
                    )
                ]
            )

    exact_candidates = [
        fill
        for fill in _deduplicate_fills(
            candidates
        )
        if _action(fill)
        == "EXIT"
    ]

    if exact_candidates:
        return exact_candidates

    # Compatibility for legacy rows without position/order lineage.
    # Returning the complete fallback set is safe:
    # one candidate is usable, multiple candidates become AMBIGUOUS.
    fallback_candidates = [
        fill
        for fill in fills
        if _action(fill)
        == "EXIT"
        and _timeframe(fill)
        == trade_tf
        and _side(fill)
        == trade_side
    ]

    return _deduplicate_fills(
        fallback_candidates
    )


def _select_entry_position_row(
    *,
    position_rows: list[dict[str, Any]],
    entry_fill: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not position_rows:
        return None

    fill_id = str(
        (entry_fill or {}).get(
            "fill_id"
        )
        or ""
    )
    command_id = str(
        (entry_fill or {}).get(
            "command_id"
        )
        or ""
    )
    fill_ts = (
        (entry_fill or {}).get("ts")
    )

    matched: list[
        dict[str, Any]
    ] = []

    for position in position_rows:
        if (
            fill_id
            and str(
                position.get(
                    "entry_fill_id"
                )
                or ""
            )
            == fill_id
        ):
            matched.append(position)
            continue

        if (
            command_id
            and str(
                position.get(
                    "entry_command_id"
                )
                or ""
            )
            == command_id
        ):
            matched.append(position)
            continue

        if (
            fill_ts
            and _same_timestamp(
                position.get("opened_at"),
                fill_ts,
            )
        ):
            matched.append(position)

    if matched:
        return matched[0]

    entry_rows = [
        position
        for position in position_rows
        if position.get(
            "entry_fill_id"
        )
        or position.get(
            "entry_command_id"
        )
        or position.get(
            "entry_context_event_id"
        )
        or position.get(
            "opened_at"
        )
    ]

    return (
        entry_rows[0]
        if entry_rows
        else position_rows[0]
    )


def _same_active_binding(
    row: dict[str, Any],
    active: dict[str, Any],
) -> bool:
    return (
        str(
            row.get("paper_epoch_id")
            or ""
        )
        == str(
            active.get("paper_epoch_id")
            or ""
        )
        and str(
            row.get("registry_record_id")
            or ""
        )
        == str(
            active.get("registry_record_id")
            or ""
        )
    )


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
    positions = [p for p in books.read_all("positions") if str(p.get("paper_epoch_id") or "") == epoch_id]

    cmds_by_id = {
        str(command.get("command_id")):
            command
        for command in commands
        if command.get("command_id")
    }

    positions_by_id: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for position in positions:
        position_id = str(
            position.get("position_id")
            or ""
        )

        if position_id:
            positions_by_id.setdefault(
                position_id,
                [],
            ).append(position)

    orders_by_command: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for order in orders:
        command_id = str(
            order.get("command_id")
            or ""
        )

        if command_id:
            orders_by_command.setdefault(
                command_id,
                [],
            ).append(order)

    fills_by_id: dict[
        str,
        dict[str, Any],
    ] = {}
    fills_by_command: dict[
        str,
        list[dict[str, Any]],
    ] = {}
    fills_by_order: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for fill in fills:
        fill_id = str(
            fill.get("fill_id")
            or ""
        )
        command_id = str(
            fill.get("command_id")
            or ""
        )
        order_id = str(
            fill.get("order_id")
            or ""
        )

        if fill_id:
            fills_by_id[fill_id] = fill

        if command_id:
            fills_by_command.setdefault(
                command_id,
                [],
            ).append(fill)

        if order_id:
            fills_by_order.setdefault(
                order_id,
                [],
            ).append(fill)

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

        position_id = str(
            trade.get("position_id")
            or ""
        )
        position_rows = (
            positions_by_id.get(
                position_id,
                [],
            )
        )

        entry_fill_candidates = (
            _resolve_entry_fill_candidates(
                trade=trade,
                position_rows=position_rows,
                fills=fills,
                fills_by_id=fills_by_id,
                fills_by_command=
                    fills_by_command,
                fills_by_order=
                    fills_by_order,
                orders_by_command=
                    orders_by_command,
            )
        )
        exit_fill_candidates = (
            _resolve_exit_fill_candidates(
                trade=trade,
                position_rows=position_rows,
                fills=fills,
                fills_by_id=fills_by_id,
                fills_by_command=
                    fills_by_command,
                fills_by_order=
                    fills_by_order,
                orders_by_command=
                    orders_by_command,
            )
        )

        entry_fill = (
            entry_fill_candidates[0]
            if len(
                entry_fill_candidates
            )
            == 1
            else None
        )
        exit_fill = (
            exit_fill_candidates[0]
            if len(
                exit_fill_candidates
            )
            == 1
            else None
        )

        if not entry_fill_candidates:
            not_evaluable[
                "TRADE_ENTRY_FILL_MISSING"
            ] = (
                not_evaluable.get(
                    "TRADE_ENTRY_FILL_MISSING",
                    0,
                )
                + 1
            )
        elif len(
            entry_fill_candidates
        ) > 1:
            not_evaluable[
                "TRADE_ENTRY_FILL_AMBIGUOUS"
            ] = (
                not_evaluable.get(
                    "TRADE_ENTRY_FILL_AMBIGUOUS",
                    0,
                )
                + 1
            )

        if not exit_fill_candidates:
            not_evaluable[
                "TRADE_EXIT_FILL_MISSING"
            ] = (
                not_evaluable.get(
                    "TRADE_EXIT_FILL_MISSING",
                    0,
                )
                + 1
            )
        elif len(
            exit_fill_candidates
        ) > 1:
            not_evaluable[
                "TRADE_EXIT_FILL_AMBIGUOUS"
            ] = (
                not_evaluable.get(
                    "TRADE_EXIT_FILL_AMBIGUOUS",
                    0,
                )
                + 1
            )

        entry_position = (
            _select_entry_position_row(
                position_rows=
                    position_rows,
                entry_fill=entry_fill,
            )
        )

        ctx_id = (
            trade.get(
                "context_event_id"
            )
            or (
                entry_position
                or {}
            ).get(
                "entry_context_event_id"
            )
        )

        entry_command = None

        if entry_fill is not None:
            command_id = str(
                entry_fill.get(
                    "command_id"
                )
                or ""
            )

            if command_id:
                entry_command = (
                    cmds_by_id.get(
                        command_id
                    )
                )

        if (
            entry_command is None
            and entry_position
        ):
            command_id = str(
                entry_position.get(
                    "entry_command_id"
                )
                or ""
            )

            if command_id:
                entry_command = (
                    cmds_by_id.get(
                        command_id
                    )
                )

        if not ctx_id and entry_command:
            ctx_id = entry_command.get(
                "context_event_id"
            )

        episode = (
            (
                entry_position
                or {}
            ).get(
                "lifecycle_episode_id"
            )
            or trade.get(
                "lifecycle_episode_id"
            )
        )

        if (
            not ctx_id
            or not episode
            or not tf
            or not trade.get(
                "paper_epoch_id"
            )
        ):
            _emit(
                branch="TRADE",
                subtype=(
                    "TRD_ENTRY_WITHOUT_CONTEXT"
                    if not ctx_id
                    else "TRD_LINEAGE_INCOMPLETE"
                ),
                severity="CRITICAL",
                status="CONFIRMED",
                subject_event_at=(
                    (
                        entry_position
                        or {}
                    ).get(
                        "opened_at"
                    )
                    or (
                        entry_fill
                        or {}
                    ).get("ts")
                    or trade.get(
                        "exit_ts"
                    )
                ),
                timeframe=tf,
                direction=side,
                context_event_id=ctx_id,
                lifecycle_episode_id=
                    episode,
                trade_id=trade_id,
                position_id=position_id,
                subject_id=trade_id,
                expected_value=[
                    "context_event_id",
                    "lifecycle_episode_id",
                    "timeframe",
                    "paper_epoch_id",
                ],
                observed_value={
                    "context_event_id":
                        ctx_id,
                    "entry_lifecycle_episode_id":
                        episode,
                    "trade_lifecycle_episode_id":
                        trade.get(
                            "lifecycle_episode_id"
                        ),
                    "timeframe":
                        tf,
                    "paper_epoch_id":
                        trade.get(
                            "paper_epoch_id"
                        ),
                    "entry_fill_id": (
                        entry_fill.get(
                            "fill_id"
                        )
                        if entry_fill
                        else None
                    ),
                },
            )

        # Validate only fills proven to belong to this exact trade.
        resolved_fills: list[
            tuple[
                dict[str, Any],
                str,
            ]
        ] = []

        if entry_fill is not None:
            resolved_fills.append(
                (
                    entry_fill,
                    "ENTRY",
                )
            )

        if exit_fill is not None:
            resolved_fills.append(
                (
                    exit_fill,
                    "EXIT",
                )
            )

        for fill, action in resolved_fills:
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

    events = [
        event
        for event in read_jsonl(
            events_path
        )
        if event.get("branch")
        == "TRADE"
        and _same_active_binding(
            event,
            active,
        )
    ]
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
