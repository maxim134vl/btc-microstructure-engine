"""Exact decision→command→trader→order→fill→position→trade lineage (no fuzzy windows).

Join policy:
- decision ↔ command: exact equality on (bar_open, timeframe) OR (bar_close, timeframe)
  where timeframe is mapped from decision.source_timeframe → M15/M30/H1/H4.
  This is NOT a time window; unmatched rows stay UNRESOLVED_MISSING_KEY / COMMAND_NOT_PRODUCED.
- command ↔ trader books: exact command_id.
- order ↔ fill: exact paper_order_id.
- fill/position/trade: exact position_id / fill ids / command_id.

Never rewrites live ledgers. Writes only candidate lineage index.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
DECISION_LOG = REPO / "data" / "live" / "context_decision_log.parquet"
COMMAND_BUS = REPO / "data" / "trading" / "manager" / "timeframe_command_memory.parquet"
TRADER_ROOT = REPO / "data" / "trading" / "timeframe_traders"
DEFAULT_OUT = REPO / "data" / "candidate" / "validation_plane"

TF_MAP = {"15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4", "M15": "M15", "M30": "M30", "H1": "H1", "H4": "H4"}

LINEAGE_STATUSES = (
    "LINKED_TO_TRADE",
    "LINKED_TO_OPEN_POSITION",
    "NO_ACTION_EXPECTED",
    "RISK_BLOCKED",
    "DUPLICATE_SUPPRESSED",
    "COMMAND_NOT_PRODUCED",
    "COMMAND_NOT_CONSUMED",
    "ORDER_NOT_CREATED",
    "UNRESOLVED_MISSING_KEY",
    "LEGACY_TRADE_NO_CANONICAL_DECISION",
)


def deterministic_id(*parts: object) -> str:
    payload = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def _load_books(trader_root: Path = TRADER_ROOT) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for kind in ("signals", "orders", "fills", "positions", "trades"):
        frames = []
        for tf_dir in sorted(trader_root.glob("*")):
            path = tf_dir / f"{kind}.parquet"
            if path.exists():
                frame = pd.read_parquet(path)
                if len(frame):
                    frames.append(frame)
        out[kind] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return out


def _expected_no_action(action: str, eligibility: str, context: str) -> bool:
    a = (action or "").upper()
    e = (eligibility or "").upper()
    c = (context or "").upper()
    if a in {"NO_TRADE_OBSERVE", "NO_ACTION", "NONE"} or c == "OBSERVE":
        return True
    if a.startswith("NO_TRADE"):
        return True
    if e.startswith("BLOCKED_OBSERVE"):
        return True
    return False


def _risk_blocked(eligibility: str) -> bool:
    e = (eligibility or "").upper()
    return e.startswith("BLOCKED") and "OBSERVE" not in e


def _duplicate(eligibility: str, action: str) -> bool:
    blob = f"{eligibility} {action}".upper()
    return "DUPLICATE" in blob or "SUPPRESS" in blob


def build_decision_trade_lineage(
    *,
    decision_log: Path = DECISION_LOG,
    command_bus: Path = COMMAND_BUS,
    trader_root: Path = TRADER_ROOT,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> tuple[pd.DataFrame, dict]:
    if not decision_log.exists():
        return pd.DataFrame(), {"status": "DECISION_LOG_MISSING"}

    decisions = pd.read_parquet(decision_log)
    decisions["candle_timestamp"] = _utc(decisions["candle_timestamp"])
    decisions["candle_close_time_utc"] = _utc(decisions.get("candle_close_time_utc", pd.Series(dtype="datetime64[ns, UTC]")))
    if start is not None:
        s = pd.Timestamp(start)
        s = s.tz_localize("UTC") if s.tzinfo is None else s.tz_convert("UTC")
        decisions = decisions[decisions["candle_timestamp"] >= s]
    if end is not None:
        e = pd.Timestamp(end)
        e = e.tz_localize("UTC") if e.tzinfo is None else e.tz_convert("UTC")
        decisions = decisions[decisions["candle_timestamp"] <= e]
    decisions = decisions.copy()
    decisions["tf"] = decisions["source_timeframe"].map(TF_MAP)

    commands = pd.read_parquet(command_bus) if command_bus.exists() else pd.DataFrame()
    if len(commands):
        commands = commands.copy()
        commands["evaluation_timestamp"] = _utc(commands["evaluation_timestamp"])
        commands["source_bar_open"] = _utc(commands.get("source_bar_open", pd.Series(dtype="datetime64[ns, UTC]")))
        commands["source_bar_close"] = _utc(commands.get("source_bar_close", pd.Series(dtype="datetime64[ns, UTC]")))

    books = _load_books(trader_root)
    signals, orders, fills, positions, trades = (
        books["signals"],
        books["orders"],
        books["fills"],
        books["positions"],
        books["trades"],
    )

    # Index trading spine by command_id (exact)
    def by_cmd(frame: pd.DataFrame, col: str = "command_id") -> dict[str, pd.Series]:
        if frame is None or len(frame) == 0 or col not in frame.columns:
            return {}
        return {str(k): g.iloc[0] for k, g in frame.groupby(col, sort=False)}

    orders_by_cmd = by_cmd(orders)
    fills_by_cmd = by_cmd(fills)
    positions_by_cmd = by_cmd(positions)
    trades_by_cmd = by_cmd(trades)
    signals_by_cmd = by_cmd(signals)

    # Exact decision→command candidates via bar open / close + timeframe
    cmd_open_idx: dict[tuple[Any, str], list[pd.Series]] = {}
    cmd_close_idx: dict[tuple[Any, str], list[pd.Series]] = {}
    if len(commands):
        for _, crow in commands.iterrows():
            tf = str(crow.get("timeframe") or "")
            open_ts = crow.get("source_bar_open")
            close_ts = crow.get("source_bar_close")
            eval_ts = crow.get("evaluation_timestamp")
            if pd.notna(open_ts):
                cmd_open_idx.setdefault((pd.Timestamp(open_ts), tf), []).append(crow)
            # evaluation_timestamp aligns with bar close in observed data
            for key_ts in (close_ts, eval_ts):
                if pd.notna(key_ts):
                    cmd_close_idx.setdefault((pd.Timestamp(key_ts), tf), []).append(crow)

    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows: list[dict[str, Any]] = []
    linked_decision_ids: set[str] = set()

    for _, drow in decisions.iterrows():
        decision_id = str(drow.get("decision_id"))
        tf = drow.get("tf")
        action = str(drow.get("paper_action_candidate") or "")
        eligibility = str(drow.get("signal_eligibility_status") or "")
        context = str(drow.get("active_market_context") or "")
        open_ts = drow.get("candle_timestamp")
        close_ts = drow.get("candle_close_time_utc")

        matched: list[pd.Series] = []
        join_key = None
        if tf and pd.notna(open_ts):
            matched = cmd_open_idx.get((pd.Timestamp(open_ts), str(tf)), [])
            if matched:
                join_key = "exact_source_bar_open+timeframe"
        if not matched and tf and pd.notna(close_ts):
            matched = cmd_close_idx.get((pd.Timestamp(close_ts), str(tf)), [])
            if matched:
                join_key = "exact_source_bar_close_or_eval+timeframe"

        # Prefer non-NO_ACTION command if multiple exact matches (still exact keys only)
        command = None
        if matched:
            ranked = sorted(
                matched,
                key=lambda r: 0 if str(r.get("intent") or "").upper() not in {"NO_ACTION", "HOLD"} else 1,
            )
            command = ranked[0]

        command_id = str(command["command_id"]) if command is not None else None
        intent = str(command["intent"]) if command is not None else None
        signal = signals_by_cmd.get(command_id) if command_id else None
        order = orders_by_cmd.get(command_id) if command_id else None
        fill = fills_by_cmd.get(command_id) if command_id else None
        position = positions_by_cmd.get(command_id) if command_id else None
        trade = trades_by_cmd.get(command_id) if command_id else None

        # CLOSE commands hold trade.command_id; OPEN may only appear on position.opening_decision_id
        if trade is None and command_id and len(trades):
            # exact: trades.command_id == command_id already covered; also opening_decision_id
            if len(positions) and "opening_decision_id" in positions.columns:
                pos_open = positions[positions["opening_decision_id"].astype(str) == command_id]
                if len(pos_open):
                    position = pos_open.iloc[0]
                    pid = position.get("position_id")
                    if pid is not None and len(trades) and "position_id" in trades.columns:
                        tr = trades[trades["position_id"].astype(str) == str(pid)]
                        if len(tr):
                            trade = tr.iloc[0]

        # Open position without closed trade
        open_pos = None
        if position is not None and trade is None:
            status_pos = str(position.get("status") or position.get("position_status") or "").upper()
            if "OPEN" in status_pos or pd.isna(position.get("closed_at", None)):
                open_pos = position

        # Disposition
        if _duplicate(eligibility, action):
            status = "DUPLICATE_SUPPRESSED"
            reason = eligibility or action
        elif trade is not None:
            status = "LINKED_TO_TRADE"
            reason = "exact_command_id_or_position_id_chain"
            linked_decision_ids.add(decision_id)
        elif open_pos is not None:
            status = "LINKED_TO_OPEN_POSITION"
            reason = "exact_command_id_position"
        elif _risk_blocked(eligibility):
            status = "RISK_BLOCKED"
            reason = eligibility
        elif command is None and _expected_no_action(action, eligibility, context):
            status = "NO_ACTION_EXPECTED"
            reason = "OBSERVE_OR_NO_TRADE_NO_COMMAND"
        elif command is None:
            # directional intent without exact command key
            if action.startswith("INTENT_"):
                status = "COMMAND_NOT_PRODUCED"
                reason = "NO_EXACT_BAR_TIMEFRAME_COMMAND_KEY"
            else:
                status = "UNRESOLVED_MISSING_KEY"
                reason = "NO_DECISION_ID_OR_EPISODE_FK_TO_COMMAND_BUS"
        elif intent in {"NO_ACTION", "HOLD"} and _expected_no_action(action, eligibility, context):
            status = "NO_ACTION_EXPECTED"
            reason = f"command_intent={intent}"
        elif order is None and intent in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}:
            if signal is None:
                status = "COMMAND_NOT_CONSUMED"
                reason = "command_id_absent_from_signals"
            else:
                status = "ORDER_NOT_CREATED"
                reason = "command_id_absent_from_orders"
        elif order is not None and fill is None:
            status = "ORDER_NOT_CREATED"
            reason = "order_without_fill"
        else:
            status = "UNRESOLVED_MISSING_KEY"
            reason = "command_present_but_trade_chain_incomplete"

        paper_order_id = order.get("paper_order_id") if order is not None else None
        fill_id = None
        if fill is not None:
            fill_id = fill.get("paper_trade_id") or fill.get("fill_id")
        if trade is not None:
            fill_id = fill_id or trade.get("entry_fill_id") or trade.get("exit_fill_id")

        rows.append(
            {
                "lineage_id": deterministic_id("lineage", decision_id, command_id or "NO_COMMAND"),
                "decision_id": decision_id,
                "context_id": None
                if drow.get("context_episode_id") is None or pd.isna(drow.get("context_episode_id"))
                else str(drow.get("context_episode_id")),
                "lifecycle_id": None
                if drow.get("lifecycle_episode_id") is None or pd.isna(drow.get("lifecycle_episode_id"))
                else str(drow.get("lifecycle_episode_id")),
                "manager_command_id": command_id,
                "trader_decision_id": signal.get("signal_id") if signal is not None else None,
                "order_id": paper_order_id,
                "fill_id": fill_id,
                "position_id": (
                    trade.get("position_id")
                    if trade is not None
                    else position.get("position_id")
                    if position is not None
                    else None
                ),
                "trade_id": trade.get("trade_id") if trade is not None else None,
                "timeframe": tf,
                "decision_timestamp": open_ts,
                "decision_action": action,
                "decision_context": context,
                "signal_eligibility_status": eligibility,
                "command_intent": intent,
                "join_method": join_key or "none",
                "lineage_status": status,
                "disposition_reason": reason,
                "realized_trade_pnl": float(trade["net_pnl_usd"])
                if trade is not None and pd.notna(trade.get("net_pnl_usd"))
                else None,
                "hypothetical_only": trade is None,
                "fuzzy_time_window_used": False,
                "source_lineage": "capability_gap_phase1|exact_joins_only",
                "created_at": created,
            }
        )

    # Legacy trades without canonical decision (exact: trade.command_id not linked above)
    used_trade_ids = {r["trade_id"] for r in rows if r["trade_id"]}
    if len(trades):
        for _, trow in trades.iterrows():
            tid = trow.get("trade_id")
            if tid in used_trade_ids:
                continue
            cid = str(trow.get("command_id") or "")
            rows.append(
                {
                    "lineage_id": deterministic_id("lineage_trade_orphan", tid),
                    "decision_id": None,
                    "context_id": None,
                    "lifecycle_id": None
                    if trow.get("lifecycle_episode_id") is None or pd.isna(trow.get("lifecycle_episode_id"))
                    else str(trow.get("lifecycle_episode_id")),
                    "manager_command_id": cid or None,
                    "trader_decision_id": None,
                    "order_id": None,
                    "fill_id": trow.get("entry_fill_id") or trow.get("exit_fill_id"),
                    "position_id": trow.get("position_id"),
                    "trade_id": tid,
                    "timeframe": trow.get("timeframe"),
                    "decision_timestamp": trow.get("entry_ts"),
                    "decision_action": None,
                    "decision_context": None,
                    "signal_eligibility_status": None,
                    "command_intent": None,
                    "join_method": "trade_without_decision_fk",
                    "lineage_status": "LEGACY_TRADE_NO_CANONICAL_DECISION",
                    "disposition_reason": "trade.command_id_has_no_decision_id_fk",
                    "realized_trade_pnl": float(trow["net_pnl_usd"])
                    if pd.notna(trow.get("net_pnl_usd"))
                    else None,
                    "hypothetical_only": False,
                    "fuzzy_time_window_used": False,
                    "source_lineage": "capability_gap_phase1|exact_joins_only",
                    "created_at": created,
                }
            )

    frame = pd.DataFrame(rows)
    if len(frame):
        before = len(frame)
        frame = frame.drop_duplicates(subset=["lineage_id"], keep="last").reset_index(drop=True)
        duplicates = before - len(frame)
        # Homogeneous dtypes for parquet (decision timestamps vs trade entry_ts strings)
        frame["decision_timestamp"] = pd.to_datetime(frame["decision_timestamp"], utc=True, errors="coerce")
        for col in (
            "decision_id",
            "context_id",
            "lifecycle_id",
            "manager_command_id",
            "trader_decision_id",
            "order_id",
            "fill_id",
            "position_id",
            "trade_id",
            "timeframe",
            "decision_action",
            "decision_context",
            "signal_eligibility_status",
            "command_intent",
            "join_method",
            "lineage_status",
            "disposition_reason",
        ):
            if col in frame.columns:
                frame[col] = frame[col].astype("string")
    else:
        duplicates = 0

    status_counts = frame["lineage_status"].value_counts().to_dict() if len(frame) else {}
    decision_rows = frame[frame["decision_id"].notna()] if len(frame) else frame
    coverage = {
        "total_decisions": int(decision_rows["decision_id"].nunique()) if len(decision_rows) else 0,
        "linked_to_closed_trades": int((decision_rows["lineage_status"] == "LINKED_TO_TRADE").sum())
        if len(decision_rows)
        else 0,
        "linked_to_open_positions": int((decision_rows["lineage_status"] == "LINKED_TO_OPEN_POSITION").sum())
        if len(decision_rows)
        else 0,
        "expected_no_action": int((decision_rows["lineage_status"] == "NO_ACTION_EXPECTED").sum())
        if len(decision_rows)
        else 0,
        "risk_blocked": int((decision_rows["lineage_status"] == "RISK_BLOCKED").sum()) if len(decision_rows) else 0,
        "command_not_produced": int((decision_rows["lineage_status"] == "COMMAND_NOT_PRODUCED").sum())
        if len(decision_rows)
        else 0,
        "command_not_consumed": int((decision_rows["lineage_status"] == "COMMAND_NOT_CONSUMED").sum())
        if len(decision_rows)
        else 0,
        "order_not_created": int((decision_rows["lineage_status"] == "ORDER_NOT_CREATED").sum())
        if len(decision_rows)
        else 0,
        "unresolved": int((decision_rows["lineage_status"] == "UNRESOLVED_MISSING_KEY").sum())
        if len(decision_rows)
        else 0,
        "legacy_trades_without_decision": int((frame["lineage_status"] == "LEGACY_TRADE_NO_CANONICAL_DECISION").sum())
        if len(frame)
        else 0,
        "disposition_coverage_pct": 100.0
        if len(decision_rows) == 0
        else 100.0
        * (
            1.0
            - (
                (decision_rows["lineage_status"].isna().sum())
                / max(len(decision_rows), 1)
            )
        ),
        "status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "fuzzy_time_window_used": False,
        "duplicates": int(duplicates),
    }
    # Every decision must have explicit status
    if len(decision_rows):
        assert decision_rows["lineage_status"].notna().all()
        coverage["disposition_coverage_pct"] = 100.0

    meta = {
        "status": "OK",
        "coverage": coverage,
        "join_policy": {
            "decision_to_command": "exact (source_bar_open|source_bar_close|evaluation_timestamp) + timeframe",
            "command_to_books": "exact command_id",
            "order_to_fill": "exact paper_order_id (via command_id spine)",
            "fuzzy_windows": False,
            "lifecycle_episode_id_bridge": "DISABLED — namespace mismatch float vs TF:N",
        },
    }
    return frame, meta


def write_decision_trade_lineage(
    out_dir: Path = DEFAULT_OUT,
    **kwargs: Any,
) -> dict:
    frame, meta = build_decision_trade_lineage(**kwargs)
    frame2, _ = build_decision_trade_lineage(**kwargs)
    idempotent = (frame["lineage_id"].tolist() if len(frame) else []) == (
        frame2["lineage_id"].tolist() if len(frame2) else []
    )
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "component": "decision_trade_lineage_candidate",
        "meta": meta,
        "invariants": {
            "fuzzy_time_window_used": False,
            "deterministic_ids": True,
            "idempotent": idempotent,
            "duplicates": meta.get("coverage", {}).get("duplicates", 0),
            "disposition_coverage_pct": meta.get("coverage", {}).get("disposition_coverage_pct"),
            "ledgers_rewritten": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "decision_trade_lineage_candidate.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)
    status_path = out_dir / "decision_trade_lineage_status.json"
    status_path.write_text(json.dumps(status, indent=2, default=str) + "\n", encoding="utf-8")
    status["output_parquet"] = str(path)
    status["output_status"] = str(status_path)
    status["rows"] = int(len(frame))
    status["coverage"] = meta.get("coverage", {})
    return status
