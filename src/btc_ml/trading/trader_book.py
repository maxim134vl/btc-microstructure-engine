"""Isolated per-timeframe paper book (S4.1).

Each timeframe owns its own directory. No shared positions parquet, so one
trader can never overwrite another trader's current position.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .paper_core import (
    ORDER_COLUMNS,
    POSITION_COLUMNS,
    SIGNAL_COLUMNS,
    TRADE_COLUMNS,
)

ROOT = Path(__file__).resolve().parents[3]

PRODUCTION_BOOKS_ROOT = ROOT / "data" / "trading" / "timeframe_traders"
CANDIDATE_BOOKS_ROOT = ROOT / "data" / "research" / "s4_1_candidate_timeframe_traders"

CLOSED_TRADE_COLUMNS = [
    "trade_id",
    "timeframe",
    "position_id",
    "command_id",
    "lifecycle_episode_id",
    "side",
    "quantity",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "exit_price",
    "stop_loss_price",
    "take_profit_price",
    "notional_usd",
    "risk_amount_usd",
    "fees_usd",
    "slippage_usd",
    "gross_pnl_usd",
    "net_pnl_usd",
    "r_multiple",
    "exit_reason",
    "entry_fill_id",
    "exit_fill_id",
    "paper_only",
    "execution_enabled",
    "metadata_json",
]


def repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    sidecar = path.with_suffix(path.suffix + ".meta.json")
    atomic_write_json(
        sidecar,
        {
            "dataset_path": repo_relative(path),
            "rows": int(len(frame)),
            "columns": list(frame.columns),
            "metadata_origin": "TIMEFRAME_TRADER_WRITER",
            "paper_only": True,
            "execution_enabled": False,
        },
    )


def read_parquet(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame(columns=columns)
    for col in columns:
        if col not in frame.columns:
            frame[col] = None
    return frame


@dataclass(frozen=True)
class TraderBook:
    timeframe: str
    root: Path

    @classmethod
    def production(cls, timeframe: str) -> "TraderBook":
        return cls(timeframe=timeframe, root=PRODUCTION_BOOKS_ROOT / timeframe)

    @classmethod
    def candidate(cls, timeframe: str) -> "TraderBook":
        return cls(timeframe=timeframe, root=CANDIDATE_BOOKS_ROOT / timeframe)

    # --- paths ---------------------------------------------------------------
    @property
    def signals(self) -> Path:
        return self.root / "signals.parquet"

    @property
    def orders(self) -> Path:
        return self.root / "orders.parquet"

    @property
    def fills(self) -> Path:
        return self.root / "fills.parquet"

    @property
    def positions(self) -> Path:
        return self.root / "positions.parquet"

    @property
    def trades(self) -> Path:
        return self.root / "trades.parquet"

    @property
    def controller_state(self) -> Path:
        return self.root / "controller_state.json"

    @property
    def runtime_status(self) -> Path:
        return self.root / "runtime_status.json"

    def all_paths(self) -> dict[str, Path]:
        return {
            "signals": self.signals,
            "orders": self.orders,
            "fills": self.fills,
            "positions": self.positions,
            "trades": self.trades,
            "controller_state": self.controller_state,
            "runtime_status": self.runtime_status,
        }

    # --- frames --------------------------------------------------------------
    def signals_frame(self) -> pd.DataFrame:
        return read_parquet(self.signals, SIGNAL_COLUMNS + ["timeframe", "command_id"])

    def orders_frame(self) -> pd.DataFrame:
        return read_parquet(self.orders, ORDER_COLUMNS + ["timeframe", "command_id"])

    def fills_frame(self) -> pd.DataFrame:
        return read_parquet(self.fills, TRADE_COLUMNS + ["timeframe", "command_id"])

    def positions_frame(self) -> pd.DataFrame:
        return read_parquet(self.positions, POSITION_COLUMNS + ["timeframe", "command_id"])

    def trades_frame(self) -> pd.DataFrame:
        return read_parquet(self.trades, CLOSED_TRADE_COLUMNS)

    # --- state ---------------------------------------------------------------
    def load_controller_state(self) -> dict[str, Any]:
        if not self.controller_state.exists():
            return {
                "timeframe": self.timeframe,
                "processed_command_ids": [],
                "last_command_id": None,
                "last_command_evaluation_timestamp": None,
                "cursor_evaluation_timestamp": None,
                "open_position_id": None,
                "cycles": 0,
            }
        try:
            payload = json.loads(self.controller_state.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def save_controller_state(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.controller_state, payload)

    def open_position(self) -> dict[str, Any] | None:
        frame = self.positions_frame()
        if not len(frame):
            return None
        open_rows = frame[frame["status"].astype(str).str.upper() == "OPEN"]
        if not len(open_rows):
            return None
        return open_rows.iloc[-1].to_dict()

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
