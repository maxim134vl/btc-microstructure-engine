#!/usr/bin/env python3
"""Read-only dump of M15 14-15 Sep paper books / commands / lifecycle."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path("/app/data")
EPOCH = "PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442"
START = pd.Timestamp("2026-09-14T07:00:00Z")
END = pd.Timestamp("2026-09-15T10:00:00Z")


def parse_ts(value):
    return pd.to_datetime(value, utc=True, errors="coerce", format="ISO8601")


def main() -> None:
    trades = []
    for line in (ROOT / f"trading/intrabar_paper/{EPOCH}/books/trades.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("timeframe") or "").upper() != "M15":
            continue
        opened = parse_ts(row.get("entry_ts"))
        closed = parse_ts(row.get("exit_ts"))
        if (pd.notna(opened) and START <= opened <= END) or (pd.notna(closed) and START <= closed <= END):
            trades.append(row)
    trades.sort(key=lambda r: r.get("entry_ts") or "")
    print("===TRADES")
    for i, t in enumerate(trades, 1):
        print(
            json.dumps(
                {
                    "label": f"M15_{i}",
                    "trade_id": t.get("trade_id"),
                    "position_id": t.get("position_id"),
                    "side": t.get("side"),
                    "entry_ts": t.get("entry_ts"),
                    "exit_ts": t.get("exit_ts"),
                    "original_exit_ts": t.get("original_exit_ts"),
                    "execution_timestamp": t.get("execution_timestamp"),
                    "decision_available_at": t.get("decision_available_at"),
                    "context_occurrence_timestamp": t.get("context_occurrence_timestamp"),
                    "exit_reason": t.get("exit_reason"),
                    "entry_price": t.get("entry_price"),
                    "exit_price": t.get("exit_price"),
                    "net_pnl_usd": t.get("net_pnl_usd"),
                    "lifecycle_episode_id": t.get("lifecycle_episode_id"),
                    "quantity": t.get("quantity"),
                },
                default=str,
            )
        )

    cmd = pd.read_parquet(ROOT / "trading/manager/timeframe_command_memory.parquet")
    cmd["evaluation_timestamp"] = parse_ts(cmd["evaluation_timestamp"])
    if "created_at" in cmd.columns:
        cmd["created_at"] = parse_ts(cmd["created_at"])
    mask = (cmd["timeframe"] == "M15") & (cmd["evaluation_timestamp"] >= START) & (cmd["evaluation_timestamp"] <= END)
    m = cmd.loc[mask].copy()
    print("===CMD_COUNTS")
    print(m["intent"].value_counts().to_dict())
    act = m[m["intent"].isin(["OPEN_LONG", "OPEN_SHORT", "CLOSE"])].copy()
    if "created_at" in act.columns:
        act = act.sort_values(["evaluation_timestamp", "created_at"])
    else:
        act = act.sort_values(["evaluation_timestamp"])
    print("===ACTION_CMDS", len(act))
    cols = [
        "evaluation_timestamp",
        "created_at",
        "intent",
        "timeframe_direction",
        "timeframe_state",
        "lifecycle_phase",
        "lifecycle_episode_id",
        "timeframe_episode_id",
        "source_bar_open",
        "source_bar_close",
        "reason_codes",
        "exit_reason",
        "action_allowed",
    ]
    extra = [c for c in ["raw_context_status", "context_bar_kind"] if c in act.columns]
    for _, r in act.iterrows():
        payload = {c: (None if pd.isna(r[c]) else r[c]) for c in cols + extra if c in r.index}
        for k, v in list(payload.items()):
            if hasattr(v, "isoformat"):
                payload[k] = v.isoformat().replace("+00:00", "Z")
        print(json.dumps(payload, default=str))

    life = pd.read_parquet(ROOT / "cognition/market_context_lifecycle_memory.parquet")
    life["timestamp"] = parse_ts(life["timestamp"])
    tf_col = "timeframe" if "timeframe" in life.columns else None
    if tf_col:
        life = life[life[tf_col].astype(str).str.upper() == "M15"]
    life = life[(life["timestamp"] >= START) & (life["timestamp"] <= END)].sort_values("timestamp")
    print("===LIFECYCLE", len(life), "cols", list(life.columns))
    keep = [
        c
        for c in [
            "timestamp",
            "timeframe",
            "active_market_context",
            "lifecycle_state",
            "raw_context_status",
            "context_episode_id",
            "active_context_started_at",
        ]
        if c in life.columns
    ]
    for _, r in life.iterrows():
        payload = {c: (None if pd.isna(r[c]) else r[c]) for c in keep}
        for k, v in list(payload.items()):
            if hasattr(v, "isoformat"):
                payload[k] = v.isoformat().replace("+00:00", "Z")
        print(json.dumps(payload, default=str))


if __name__ == "__main__":
    main()
