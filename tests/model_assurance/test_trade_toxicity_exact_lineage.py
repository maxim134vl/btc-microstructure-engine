from __future__ import annotations

from pathlib import Path

from btc_ml.model_assurance.toxic_box import (
    trade_toxicity as tt,
)


class MemoryBooks:
    def __init__(
        self,
        rows: dict[
            str,
            list[dict],
        ],
    ) -> None:
        self.rows = rows

    def read_all(
        self,
        name: str,
    ) -> list[dict]:
        return list(
            self.rows.get(
                name,
                [],
            )
        )


ACTIVE = {
    "registry_record_id": "REG_NEW",
    "model_id": "MODEL",
    "model_version": "V1",
    "runtime_fingerprint": "RUNTIME",
    "trading_contract_fingerprint": "CONTRACT",
    "paper_epoch_id": "EPOCH_NEW",
    "paper_only": True,
    "real_execution": False,
}


def _fill(
    *,
    fill_id: str,
    command_id: str,
    order_id: str,
    action: str,
    ts: str,
    price: float,
) -> dict:
    return {
        "fill_id": fill_id,
        "command_id": command_id,
        "order_id": order_id,
        "action": action,
        "paper_epoch_id": "EPOCH_NEW",
        "timeframe": "M15",
        "side": "LONG",
        "ts": ts,
        "paper_fill_price": price,
        "best_bid": 100.0,
        "best_ask": 101.0,
        "fill_bid": 100.0,
        "fill_ask": 101.0,
        "bbo_age_ms": 1.0,
        "bbo_receive_monotonic_ns": 10,
        "trigger_monotonic_ns": 20,
        "execution_source": "BBO_INTRABAR",
    }


def _trade(
    *,
    trade_id: str,
    position_id: str,
    episode: str,
    exit_ts: str,
) -> dict:
    return {
        "trade_id": trade_id,
        "position_id": position_id,
        "paper_epoch_id": "EPOCH_NEW",
        "status": "CLOSED",
        "timeframe": "M15",
        "side": "LONG",
        "lifecycle_episode_id": episode,
        "exit_ts": exit_ts,
        "risk_amount_usd": 100.0,
        "max_risk_usd": 100.0,
    }


def _position_rows(
    *,
    position_id: str,
    episode: str,
    context_id: str,
    entry_fill_id: str,
    entry_command_id: str,
    opened_at: str,
    closed_at: str,
) -> list[dict]:
    return [
        {
            "position_id": position_id,
            "paper_epoch_id": "EPOCH_NEW",
            "status": "OPEN",
            "timeframe": "M15",
            "side": "LONG",
            "lifecycle_episode_id": episode,
            "entry_context_event_id": context_id,
            "entry_fill_id": entry_fill_id,
            "entry_command_id": entry_command_id,
            "opened_at": opened_at,
        },
        {
            "position_id": position_id,
            "paper_epoch_id": "EPOCH_NEW",
            "status": "CLOSED",
            "timeframe": "M15",
            "side": "LONG",
            "lifecycle_episode_id": episode,
            "closed_at": closed_at,
        },
    ]


def test_each_trade_uses_its_own_exact_fills(
    tmp_path: Path,
) -> None:
    fills = [
        _fill(
            fill_id="F1_ENTRY",
            command_id="C1_ENTRY",
            order_id="O1_ENTRY",
            action="ENTRY",
            ts="2026-08-01T00:00:00Z",
            price=100.0,
        ),
        _fill(
            fill_id="F1_EXIT",
            command_id="C1_EXIT",
            order_id="O1_EXIT",
            action="EXIT",
            ts="2026-08-01T01:00:00Z",
            price=100.0,
        ),
        _fill(
            fill_id="F2_ENTRY",
            command_id="C2_ENTRY",
            order_id="O2_ENTRY",
            action="ENTRY",
            ts="2026-08-01T02:00:00Z",
            price=101.0,
        ),
        _fill(
            fill_id="F2_EXIT",
            command_id="C2_EXIT",
            order_id="O2_EXIT",
            action="EXIT",
            ts="2026-08-01T03:00:00Z",
            price=100.0,
        ),
    ]

    positions = (
        _position_rows(
            position_id="P1",
            episode="EP1",
            context_id="CTX1",
            entry_fill_id="F1_ENTRY",
            entry_command_id="C1_ENTRY",
            opened_at="2026-08-01T00:00:00Z",
            closed_at="2026-08-01T01:00:00Z",
        )
        + _position_rows(
            position_id="P2",
            episode="EP2",
            context_id="CTX2",
            entry_fill_id="F2_ENTRY",
            entry_command_id="C2_ENTRY",
            opened_at="2026-08-01T02:00:00Z",
            closed_at="2026-08-01T03:00:00Z",
        )
    )

    commands = [
        {
            "command_id": "C1_ENTRY",
            "action": "ENTRY",
            "paper_epoch_id": "EPOCH_NEW",
            "timeframe": "M15",
            "side": "LONG",
            "context_event_id": "CTX1",
            "command_monotonic_ns": 20,
        },
        {
            "command_id": "C1_EXIT",
            "action": "EXIT",
            "paper_epoch_id": "EPOCH_NEW",
            "timeframe": "M15",
            "side": "LONG",
            "command_monotonic_ns": 20,
        },
        {
            "command_id": "C2_ENTRY",
            "action": "ENTRY",
            "paper_epoch_id": "EPOCH_NEW",
            "timeframe": "M15",
            "side": "LONG",
            "context_event_id": "CTX2",
            "command_monotonic_ns": 20,
        },
        {
            "command_id": "C2_EXIT",
            "action": "EXIT",
            "paper_epoch_id": "EPOCH_NEW",
            "timeframe": "M15",
            "side": "LONG",
            "command_monotonic_ns": 20,
        },
    ]

    orders = [
        {
            "order_id": fill["order_id"],
            "command_id": fill["command_id"],
            "action": fill["action"],
            "paper_epoch_id": "EPOCH_NEW",
            "timeframe": "M15",
            "side": "LONG",
        }
        for fill in fills
    ]

    books = MemoryBooks(
        {
            "trades": [
                _trade(
                    trade_id="T1",
                    position_id="P1",
                    episode="EP1",
                    exit_ts="2026-08-01T01:00:00Z",
                ),
                _trade(
                    trade_id="T2",
                    position_id="P2",
                    episode="EP2",
                    exit_ts="2026-08-01T03:00:00Z",
                ),
            ],
            "fills": fills,
            "orders": orders,
            "commands": commands,
            "positions": positions,
        }
    )

    result = tt.evaluate_trade_toxicity(
        active=ACTIVE,
        books=books,
        economic_evaluations=[],
        config={
            "trade": {
                "severe_loss_r_lte": -1.25,
                "risk_tolerance_usd": 0.01,
            }
        },
        max_bbo_age_ms=1000.0,
        events_path=(
            tmp_path
            / "events.jsonl"
        ),
        existing_ids=set(),
    )

    wrong_side = [
        event
        for event in result["events"]
        if event.get("subtype")
        == "TRD_WRONG_SIDE_FILL"
    ]

    assert [
        (
            event.get("trade_id"),
            event.get("fill_id"),
        )
        for event in wrong_side
    ] == [
        (
            "T1",
            "F1_ENTRY",
        )
    ]

    not_evaluable = (
        result[
            "not_evaluable_checks"
        ]
    )

    assert (
        not_evaluable.get(
            "TRADE_ENTRY_FILL_MISSING",
            0,
        )
        == 0
    )
    assert (
        not_evaluable.get(
            "TRADE_ENTRY_FILL_AMBIGUOUS",
            0,
        )
        == 0
    )
    assert (
        not_evaluable.get(
            "TRADE_EXIT_FILL_MISSING",
            0,
        )
        == 0
    )
    assert (
        not_evaluable.get(
            "TRADE_EXIT_FILL_AMBIGUOUS",
            0,
        )
        == 0
    )


def test_ambiguous_fill_is_not_validated_as_exact(
    tmp_path: Path,
) -> None:
    entry_one = _fill(
        fill_id="F_ENTRY_A",
        command_id="C_ENTRY_A",
        order_id="O_ENTRY_A",
        action="ENTRY",
        ts="2026-08-01T00:00:00Z",
        price=100.0,
    )
    entry_two = _fill(
        fill_id="F_ENTRY_B",
        command_id="C_ENTRY_B",
        order_id="O_ENTRY_B",
        action="ENTRY",
        ts="2026-08-01T00:00:00Z",
        price=101.0,
    )
    exit_fill = _fill(
        fill_id="F_EXIT",
        command_id="C_EXIT",
        order_id="O_EXIT",
        action="EXIT",
        ts="2026-08-01T01:00:00Z",
        price=100.0,
    )

    books = MemoryBooks(
        {
            "trades": [
                _trade(
                    trade_id="T1",
                    position_id="P1",
                    episode="EP1",
                    exit_ts="2026-08-01T01:00:00Z",
                )
            ],
            "fills": [
                entry_one,
                entry_two,
                exit_fill,
            ],
            "orders": [],
            "commands": [],
            "positions": [
                {
                    "position_id": "P1",
                    "paper_epoch_id": "EPOCH_NEW",
                    "status": "OPEN",
                    "timeframe": "M15",
                    "side": "LONG",
                    "lifecycle_episode_id": "EP1",
                    "entry_context_event_id": "CTX1",
                    "opened_at": "2026-08-01T00:00:00Z",
                },
                {
                    "position_id": "P1",
                    "paper_epoch_id": "EPOCH_NEW",
                    "status": "CLOSED",
                    "timeframe": "M15",
                    "side": "LONG",
                    "lifecycle_episode_id": "EP1",
                    "closed_at": "2026-08-01T01:00:00Z",
                },
            ],
        }
    )

    result = tt.evaluate_trade_toxicity(
        active=ACTIVE,
        books=books,
        economic_evaluations=[],
        config={
            "trade": {
                "severe_loss_r_lte": -1.25,
                "risk_tolerance_usd": 0.01,
            }
        },
        max_bbo_age_ms=1000.0,
        events_path=(
            tmp_path
            / "events.jsonl"
        ),
        existing_ids=set(),
    )

    assert (
        result[
            "not_evaluable_checks"
        ][
            "TRADE_ENTRY_FILL_AMBIGUOUS"
        ]
        == 1
    )

    assert not [
        event
        for event in result["events"]
        if event.get("subtype")
        == "TRD_WRONG_SIDE_FILL"
        and event.get("trade_id")
        == "T1"
        and event.get("fill_id")
        in {
            "F_ENTRY_A",
            "F_ENTRY_B",
        }
    ]
