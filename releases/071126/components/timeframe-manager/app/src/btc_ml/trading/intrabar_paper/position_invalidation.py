"""Administrative invalidation for bug-generated paper positions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .books import EpochBooks
from .performance_eligibility import (
    INVALIDATION_REASON_SYSTEM_BUG,
    POSITION_STATUS_VOID,
    is_void_position_row,
)


BUG_CAUSE_REPLAY_CATCH_UP = (
    "Historical M15 CONTEXT_START was replayed after service disruption while the "
    "signal age (791.88s) remained inside the 900s stale window and the prior M15 "
    "position had closed seconds earlier."
)

BUG_CAUSE_MISSED_FLIP = (
    "Canonical M15 context later changed SHORT to LONG during downtime, but the "
    "materialization bridge was offline and pre-Fix-2 recovery logic rejected the "
    "historical transition after restart."
)

SYSTEM_CORRECTION_TELEGRAM_TEXT = """Обнаружена и исправлена техническая ошибка по позиции M15.

Позиция была открыта некорректно после повторной обработки старого сигнала M15. На момент повторной обработки сигналу было около 13 минут, поэтому он формально еще проходил действовавший 15-минутный фильтр устаревания. За несколько секунд до этого предыдущая позиция M15 закрылась, и система ошибочно разрешила новый вход по старому сигналу.

Позже контекст M15 корректно изменился с SHORT на LONG, однако во время сбоя это изменение не дошло до торгового контура. Старый механизм восстановления после перезапуска также не позволял восстановить пропущенное изменение контекста.

Позиция M15 признана технически невалидной и исключена из P&L и всей торговой статистики. Ее результат не считается результатом торговой стратегии.

Исправлены механизмы повторной обработки старых сигналов и восстановления пропущенных изменений контекста после перезапуска."""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def latest_position_row(books: EpochBooks, position_id: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for row in books.read_all("positions"):
        if str(row.get("position_id") or "") == position_id:
            latest = dict(row)
    return latest


def build_system_correction_telegram_event(
    *,
    position_id: str,
    timeframe: str,
    invalidated_at: str,
    invalidation_reason: str = INVALIDATION_REASON_SYSTEM_BUG,
) -> dict[str, Any]:
    tf = str(timeframe or "M15").upper()
    if tf.startswith("M15_"):
        tf = "M15"
    return {
        "event_type": "SYSTEM_CORRECTION",
        "severity": "WARNING",
        "channel": "telegram",
        "timeframe": tf,
        "position_id": position_id,
        "invalidated_at": invalidated_at,
        "invalidation_reason": invalidation_reason,
        "strategy_pnl_included": False,
        "statistics_included": False,
        "message": SYSTEM_CORRECTION_TELEGRAM_TEXT,
    }


def invalidate_open_position(
    books: EpochBooks,
    *,
    position_id: str,
    invalidation_reason: str = INVALIDATION_REASON_SYSTEM_BUG,
    invalidation_detail: str | None = None,
    invalidated_at: str | None = None,
    bug_cause: str | None = None,
    emit_telegram_event: bool = True,
) -> dict[str, Any]:
    """Administratively void an OPEN position without creating a strategy trade close."""
    current = latest_position_row(books, position_id)
    if current is None:
        raise ValueError(f"position not found: {position_id}")
    if is_void_position_row(current):
        raise ValueError(f"position already void: {position_id}")
    if str(current.get("status") or "").upper() != "OPEN":
        raise ValueError(
            f"position {position_id} is not OPEN (status={current.get('status')!r})"
        )

    ts = invalidated_at or _utc_iso()
    void_row = dict(current)
    void_row.update(
        {
            "status": POSITION_STATUS_VOID,
            "invalidated_at": ts,
            "invalidation_reason": invalidation_reason,
            "invalidation_detail": invalidation_detail
            or "Bug-generated replay entry excluded from strategy performance.",
            "bug_cause": bug_cause or BUG_CAUSE_REPLAY_CATCH_UP,
            "strategy_pnl_included": False,
            "statistics_included": False,
            "void_class": "SYSTEM_BUG",
            "original_status": "OPEN",
            "closed_at": None,
            "exit_price": None,
            "exit_reason": None,
        }
    )
    books.append("positions", void_row)

    audit_row = {
        "metric_type": "POSITION_INVALIDATION",
        "position_id": position_id,
        "timeframe": void_row.get("timeframe"),
        "status": POSITION_STATUS_VOID,
        "invalidated_at": ts,
        "invalidation_reason": invalidation_reason,
        "invalidation_detail": void_row.get("invalidation_detail"),
        "bug_cause": void_row.get("bug_cause"),
        "entry_context_event_id": void_row.get("entry_context_event_id"),
        "entry_price": void_row.get("entry_price"),
        "entry_ts": void_row.get("opened_at"),
        "side": void_row.get("side"),
        "quantity": void_row.get("quantity"),
        "lifecycle_episode_id": void_row.get("lifecycle_episode_id"),
        "strategy_pnl_included": False,
        "statistics_included": False,
    }
    books.append("metrics", audit_row)

    telegram_event: dict[str, Any] | None = None
    if emit_telegram_event:
        telegram_event = build_system_correction_telegram_event(
            position_id=position_id,
            timeframe=str(void_row.get("timeframe") or "M15"),
            invalidated_at=ts,
            invalidation_reason=invalidation_reason,
        )
        books.append(
            "metrics",
            {
                "metric_type": "SYSTEM_CORRECTION",
                **telegram_event,
            },
        )

    return {
        "position": void_row,
        "audit": audit_row,
        "telegram_event": telegram_event,
    }


def production_m15_8_invalidation_plan() -> dict[str, Any]:
    """One-time production migration plan (documentation only; not executed here)."""
    return {
        "position_id": "pos_74dd6b85bdc2434a",
        "epoch_id": "PER_TF_EQUITY_1PCT_V1_20260802_155305",
        "books_root": "data/trading/intrabar_paper/PER_TF_EQUITY_1PCT_V1_20260802_155305/books",
        "files_to_append": [
            "positions.jsonl",
            "metrics.jsonl",
        ],
        "files_must_not_append": [
            "trades.jsonl",
            "fills.jsonl",
            "orders.jsonl",
        ],
        "expected_latest_position_status_before": "OPEN",
        "expected_latest_position_status_after": "VOID",
        "invalidation_reason": INVALIDATION_REASON_SYSTEM_BUG,
        "operator_timeframe_label": "M15",
        "internal_diagnostic_label": "M15_8",
        "restart_required_after": True,
        "notes": [
            "Append-only VOID restatement on positions.jsonl; do not rewrite history.",
            "Emit SYSTEM_CORRECTION metrics/Telegram event after invalidation.",
            "Deploy Fix 1 / Fix 2 before or with invalidation rollout.",
            "After restart, recovered M15 FLIP must not close voided exposure.",
        ],
    }
