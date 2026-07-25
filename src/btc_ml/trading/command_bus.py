"""Append-only timeframe command bus (S4.1).

Immutable prefix: existing rows are never rewritten. Duplicate commands are
rejected by deterministic ``command_id``. Each trader consumes only its own
timeframe slice via its own cursor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .trader_book import atomic_write_json, atomic_write_parquet, read_parquet

ROOT = Path(__file__).resolve().parents[3]

COMMAND_SCHEMA_VERSION = "timeframe_manager_command_v1"

PRODUCTION_COMMAND_MEMORY = ROOT / "data" / "trading" / "manager" / "timeframe_command_memory.parquet"
PRODUCTION_LATEST_SNAPSHOT = ROOT / "data" / "runtime" / "timeframe_manager_latest.json"
PRODUCTION_MANAGER_STATE = ROOT / "data" / "trading" / "manager" / "manager_state.json"
PRODUCTION_PORTFOLIO_SUMMARY = ROOT / "data" / "trading" / "manager" / "portfolio_summary.json"

CANDIDATE_COMMAND_MEMORY = ROOT / "data" / "research" / "s4_1_candidate_manager_commands.parquet"
CANDIDATE_LATEST_SNAPSHOT = ROOT / "data" / "research" / "s4_1_candidate_manager_latest.json"
CANDIDATE_MANAGER_STATE = ROOT / "data" / "research" / "s4_1_candidate_manager_state.json"
CANDIDATE_PORTFOLIO_SUMMARY = ROOT / "data" / "research" / "s4_1_candidate_portfolio_summary.json"

COMMAND_COLUMNS = [
    "command_id",
    "manager_cycle_id",
    "schema_version",
    "asset",
    "timeframe",
    "evaluation_timestamp",
    "source_bar_open",
    "source_bar_close",
    "source_state_timestamp",
    "source_event_timestamp",
    "timeframe_state",
    "timeframe_direction",
    "availability_status",
    "lifecycle_episode_id",
    "lifecycle_phase",
    "intent",
    "action_allowed",
    "reason_codes",
    "exit_reason",
    "confidence",
    "alignment_score",
    "persistence_score",
    "structural_rank",
    "location_bias",
    "requested_risk_usd",
    "approved_risk_usd",
    "portfolio_open_risk_usd",
    "stop_reference",
    "invalidation_reference",
    "command_ttl_seconds",
    "cross_timeframe_metadata",
    "created_at",
    "source_lineage",
    "paper_only",
    "execution_enabled",
    # Additive identity fields (nullable; legacy rows remain readable without them)
    "decision_id",
    "context_id",
    "canonical_episode_id",
    "timeframe_episode_id",
    "source_decision_timestamp",
    "lineage_lookup_status",
]

VALID_INTENTS = ("OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE", "NO_ACTION")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def classify_command_lineage(command: dict[str, Any]) -> str:
    """Runtime classification only — does not rewrite historical rows."""
    value = command.get("decision_id")
    if value is None:
        return "LEGACY_NO_DECISION_ID"
    try:
        if pd.isna(value):
            return "LEGACY_NO_DECISION_ID"
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "<na>"}:
        return "LEGACY_NO_DECISION_ID"
    return "HAS_DECISION_ID"


@dataclass(frozen=True)
class CommandBusPaths:
    memory: Path
    latest: Path
    manager_state: Path
    portfolio_summary: Path

    @classmethod
    def production(cls) -> "CommandBusPaths":
        return cls(
            PRODUCTION_COMMAND_MEMORY,
            PRODUCTION_LATEST_SNAPSHOT,
            PRODUCTION_MANAGER_STATE,
            PRODUCTION_PORTFOLIO_SUMMARY,
        )

    @classmethod
    def candidate(cls) -> "CommandBusPaths":
        return cls(
            CANDIDATE_COMMAND_MEMORY,
            CANDIDATE_LATEST_SNAPSHOT,
            CANDIDATE_MANAGER_STATE,
            CANDIDATE_PORTFOLIO_SUMMARY,
        )


class CommandBus:
    def __init__(self, paths: CommandBusPaths) -> None:
        self.paths = paths

    # --- read ----------------------------------------------------------------
    def frame(self) -> pd.DataFrame:
        return read_parquet(self.paths.memory, COMMAND_COLUMNS)

    def existing_command_ids(self) -> set[str]:
        frame = self.frame()
        if not len(frame):
            return set()
        return set(frame["command_id"].astype(str).tolist())

    def timeframe_commands(self, timeframe: str) -> pd.DataFrame:
        frame = self.frame()
        if not len(frame):
            return frame
        return frame[frame["timeframe"].astype(str).str.upper() == str(timeframe).upper()].reset_index(drop=True)

    def pending_for_timeframe(
        self,
        timeframe: str,
        *,
        processed_command_ids: set[str],
        after_evaluation_timestamp: Any = None,
    ) -> list[dict[str, Any]]:
        frame = self.timeframe_commands(timeframe)
        if not len(frame):
            return []
        stamps = pd.to_datetime(frame["evaluation_timestamp"], utc=True, errors="coerce")
        frame = frame.assign(_ts=stamps).sort_values("_ts")
        if after_evaluation_timestamp is not None:
            boundary = pd.Timestamp(after_evaluation_timestamp)
            boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
            frame = frame[frame["_ts"] >= boundary]
        out: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            record = {k: v for k, v in row.to_dict().items() if k != "_ts"}
            if str(record.get("command_id")) in processed_command_ids:
                continue
            out.append(record)
        return out

    # --- write ---------------------------------------------------------------
    def append(self, commands: list[dict[str, Any]]) -> dict[str, Any]:
        existing = self.frame()
        known = set(existing["command_id"].astype(str).tolist()) if len(existing) else set()
        fresh: list[dict[str, Any]] = []
        duplicates: list[str] = []
        for command in commands:
            command_id = str(command.get("command_id"))
            if command_id in known:
                duplicates.append(command_id)
                continue
            known.add(command_id)
            fresh.append({col: command.get(col) for col in COMMAND_COLUMNS})
        if fresh:
            new_frame = pd.DataFrame(fresh, columns=COMMAND_COLUMNS)
            if len(existing):
                base = existing.copy()
                for col in COMMAND_COLUMNS:
                    if col not in base.columns:
                        base[col] = None
                base = base[COMMAND_COLUMNS]
                out = pd.concat([base, new_frame], ignore_index=True)
            else:
                out = new_frame
            atomic_write_parquet(self.paths.memory, out)
        return {
            "appended": len(fresh),
            "duplicates_rejected": len(duplicates),
            "duplicate_command_ids": duplicates,
            "total_rows": int(len(existing) + len(fresh)),
        }

    def write_latest_snapshot(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.paths.latest, payload)

    def load_manager_state(self) -> dict[str, Any]:
        if not self.paths.manager_state.exists():
            return {"cycles": 0, "timeframes": {}, "last_manager_cycle_id": None}
        try:
            import json

            payload = json.loads(self.paths.manager_state.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"cycles": 0, "timeframes": {}}
        except Exception:
            return {"cycles": 0, "timeframes": {}}

    def save_manager_state(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.paths.manager_state, payload)

    def write_portfolio_summary(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.paths.portfolio_summary, payload)
