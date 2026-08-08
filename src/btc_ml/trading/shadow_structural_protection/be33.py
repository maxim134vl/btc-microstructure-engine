"""Observe-only STP_BE33 partial-take and economic break-even policy."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any, Iterable

from btc_ml.trading.intrabar_paper.config import IntrabarPaperConfig, load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.economics import closed_trade_economics
from btc_ml.trading.intrabar_paper.execution_market_wal import EVENT_AGG_TRADE, SOURCE_BINANCE_FUTURES

from .paths import assert_shadow_write_path, shadow_root

getcontext().prec = 28

POLICY_ID = "STP_BE33"
POLICY_VERSION = "STP_BE33_V1"
STATE_OPEN_FULL = "OPEN_FULL"
STATE_BE_PROTECTED = "BE_PROTECTED"
STATE_CLOSED = "CLOSED"
STATE_CLOSED_WITHOUT_PARTIAL = "CLOSED_WITHOUT_PARTIAL"
CONTEXT_EXITS = frozenset({"CONTEXT_END", "CONTEXT_FLIP", "CONTEXT_EXIT"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            return None
        if abs(number) > 10_000_000_000:
            number /= 1000.0
        return datetime.fromtimestamp(number, tz=timezone.utc)
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def event_timestamp(event: dict[str, Any]) -> datetime | None:
    return (
        parse_timestamp(event.get("exchange_trade_timestamp"))
        or parse_timestamp(event.get("exchange_event_timestamp"))
        or parse_timestamp(event.get("local_receive_timestamp"))
        or parse_timestamp(event.get("durable_append_timestamp"))
    )


def partial_trigger_price(*, side: str, entry_price: float, take_price: float) -> float:
    entry = Decimal(str(entry_price))
    take = Decimal(str(take_price))
    side_u = str(side).upper()
    if side_u == "LONG" and take > entry:
        return float(entry + (take - entry) / Decimal(3))
    if side_u == "SHORT" and take < entry:
        return float(entry - (entry - take) / Decimal(3))
    raise ValueError(f"INVALID_{side_u}_TAKE_GEOMETRY")


def split_one_third(quantity: float) -> tuple[float, float]:
    """Follow the canonical full-float policy using one deterministic Decimal split."""
    original = Decimal(str(quantity))
    if original <= 0:
        raise ValueError("INVALID_QUANTITY")
    partial = original / Decimal(3)
    return float(partial), float(original - partial)


def solve_economic_break_even(
    *,
    cfg: IntrabarPaperConfig,
    side: str,
    entry_price: float,
    quantity: float,
    risk_amount_usd: float,
    tolerance_usd: float = 1e-8,
) -> tuple[float, dict[str, Any]]:
    """Invert canonical stop-close economics until remaining net PnL is zero."""
    side_u = str(side).upper()

    def economics(price: float) -> dict[str, Any]:
        return closed_trade_economics(
            cfg=cfg,
            side=side_u,
            entry_price=entry_price,
            exit_price=price,
            quantity=quantity,
            risk_amount_usd=risk_amount_usd,
            exit_reason="SL",
        )

    entry = float(entry_price)
    if side_u == "LONG":
        low, high = entry, entry * 1.01
        while float(economics(high)["net_pnl_usd"]) < 0:
            high = entry + 2.0 * (high - entry)
    elif side_u == "SHORT":
        low, high = max(entry * 0.99, 1e-12), entry
        while float(economics(low)["net_pnl_usd"]) < 0:
            low = max(entry - 2.0 * (entry - low), 1e-12)
            if low <= 1e-12 and float(economics(low)["net_pnl_usd"]) < 0:
                raise ValueError("ECONOMIC_BREAK_EVEN_UNSOLVABLE")
    else:
        raise ValueError(f"INVALID_SIDE:{side}")

    result = economics(entry)
    price = entry
    for _ in range(100):
        price = (low + high) / 2.0
        result = economics(price)
        net = float(result["net_pnl_usd"])
        if abs(net) <= tolerance_usd:
            break
        if side_u == "LONG":
            low, high = (price, high) if net < 0 else (low, price)
        else:
            low, high = (low, price) if net < 0 else (price, high)
    return price, result


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_policy_manifest(*, policy_effective_at: str) -> dict[str, Any]:
    core = {
        "schema_version": "stp_be33_policy_manifest_v1",
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "policy_effective_at": policy_effective_at,
        "source_position_contract": "NEW_CANONICAL_PAPER_POSITIONS_ONLY",
        "trigger_source": "BINANCE_FUTURES_AGG_TRADE_DURABLE_EXECUTION_WAL",
        "partial_fraction": "1/3_ORIGINAL_QUANTITY",
        "remaining_fraction": "2/3_ORIGINAL_QUANTITY",
        "partial_execution_price": "IMMUTABLE_PARTIAL_TRIGGER_PRICE",
        "economic_break_even": "INVERSE_CANONICAL_CLOSED_TRADE_ECONOMICS_STOP_EXIT",
        "quantity_precision": "CANONICAL_FULL_FLOAT64_DECIMAL_SPLIT_NO_LOT_ROUNDING",
        "canonical_write_capability": False,
        "live1b_command_capability": False,
        "real_execution_capability": False,
    }
    return {**core, "policy_fingerprint": _fingerprint(core)}


class JsonStore:
    """Fsync append-only journal and atomic small JSON views inside shadow root."""

    def __init__(self, root: Path, *, repo: Path) -> None:
        self.repo = Path(repo)
        self.root = assert_shadow_write_path(Path(root), repo=self.repo)
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_path = assert_shadow_write_path(self.root / "events.jsonl", repo=self.repo)
        self.outcomes_path = assert_shadow_write_path(self.root / "outcomes.jsonl", repo=self.repo)
        self.checkpoint_path = assert_shadow_write_path(self.root / "checkpoint.json", repo=self.repo)
        self.health_path = assert_shadow_write_path(self.root / "health.json", repo=self.repo)
        self.events_path.touch(exist_ok=True)
        self.outcomes_path.touch(exist_ok=True)

    @staticmethod
    def read_jsonl(path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not path.exists():
            return rows
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    @staticmethod
    def append_jsonl(path: Path, row: dict[str, Any]) -> None:
        data = (json.dumps(row, sort_keys=True, default=str) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def write_json(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def read_checkpoint(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}


class ReadOnlyWal:
    """Read LIVE1B events without creating directories, state, or source files."""

    def __init__(self, root: Path) -> None:
        self.events_path = Path(root) / "events.jsonl"
        self._cursor_bytes = 0
        self._cached_last_offset = 0

    def _read_from_cursor(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.events_path.open("rb") as handle:
            handle.seek(self._cursor_bytes)
            while True:
                line_start = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    handle.seek(line_start)
                    break
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                    self._cached_last_offset = max(
                        self._cached_last_offset,
                        int(row.get("wal_offset") or 0),
                    )
            self._cursor_bytes = handle.tell()
        return rows

    def iter_from_offset(self, offset: int) -> Iterable[dict[str, Any]]:
        requested = int(offset)
        if requested >= self._cached_last_offset:
            rows = self._read_from_cursor()
        else:
            # Historical causal lookup must not rewind the hot tail cursor.
            rows = JsonStore.read_jsonl(self.events_path)
        return iter(sorted(
            (row for row in rows if int(row.get("wal_offset") or 0) > requested),
            key=lambda row: int(row.get("wal_offset") or 0),
        ))

    @property
    def last_offset(self) -> int:
        # Consume only bytes appended since the prior read.
        list(self.iter_from_offset(self._cached_last_offset))
        return self._cached_last_offset


@dataclass(frozen=True)
class CanonicalClose:
    position_id: str
    timestamp: datetime
    timestamp_raw: str
    price: float
    reason: str
    net_pnl_usd: float | None


class StpBe33Engine:
    """Read canonical books and WAL; write only STP_BE33 shadow state."""

    def __init__(
        self,
        *,
        repo: Path,
        epoch_id: str | None = None,
        policy_effective_at: str | None = None,
        store_root: Path | None = None,
    ) -> None:
        self.repo = Path(repo)
        self.cfg = load_intrabar_paper_config(repo_root=self.repo)
        self.epoch_id = epoch_id or self._active_epoch_id()
        self.epoch_root = self.repo / "data" / "trading" / "intrabar_paper" / self.epoch_id
        self.books_root = self.epoch_root / "books"
        self.wal = ReadOnlyWal(self.epoch_root / "execution_market_wal")
        policy_root = assert_shadow_write_path(shadow_root(self.repo) / "stp_be33", repo=self.repo)
        policy_root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = assert_shadow_write_path(policy_root / "policy_manifest.json", repo=self.repo)
        self.manifest = self._load_or_create_manifest(policy_effective_at)
        self.policy_effective_at = parse_timestamp(self.manifest["policy_effective_at"])
        if self.policy_effective_at is None:
            raise RuntimeError("STP_BE33_INVALID_EFFECTIVE_AT")
        self.store = JsonStore(store_root or policy_root / "epochs" / self.epoch_id, repo=self.repo)
        self.states: dict[str, dict[str, Any]] = {}
        self.event_ids: set[str] = set()
        self.outcome_ids: set[str] = set()
        self.ignored_position_ids: set[str] = set()
        self.last_processed_wal_offset = 0
        self._rebuild()

    def _active_epoch_id(self) -> str:
        path = self.repo / "data" / "trading" / "paper_epochs" / "active.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        epoch_id = str(payload.get("paper_epoch_id") or "").strip()
        if not epoch_id:
            raise RuntimeError("STP_BE33_ACTIVE_EPOCH_MISSING")
        return epoch_id

    def _load_or_create_manifest(self, effective_at: str | None) -> dict[str, Any]:
        if self.manifest_path.exists():
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if (payload.get("policy_id"), payload.get("policy_version")) != (POLICY_ID, POLICY_VERSION):
                raise RuntimeError("STP_BE33_MANIFEST_MISMATCH")
            if effective_at and parse_timestamp(effective_at) != parse_timestamp(payload.get("policy_effective_at")):
                raise RuntimeError("STP_BE33_EFFECTIVE_AT_IMMUTABLE")
            return payload
        payload = build_policy_manifest(policy_effective_at=effective_at or utc_now())
        JsonStore.write_json(self.manifest_path, payload)
        return payload

    def _rows(self, table: str) -> list[dict[str, Any]]:
        return JsonStore.read_jsonl(self.books_root / f"{table}.jsonl")

    def _rebuild(self) -> None:
        for event in JsonStore.read_jsonl(self.store.events_path):
            if event.get("event_id"):
                self.event_ids.add(str(event["event_id"]))
            state = event.get("position_after")
            if isinstance(state, dict) and state.get("canonical_position_id"):
                self.states[str(state["canonical_position_id"])] = state
        for outcome in JsonStore.read_jsonl(self.store.outcomes_path):
            if outcome.get("outcome_id"):
                self.outcome_ids.add(str(outcome["outcome_id"]))
        checkpoint = self.store.read_checkpoint()
        self.last_processed_wal_offset = int(checkpoint.get("last_processed_wal_offset") or 0)
        self.ignored_position_ids = set(checkpoint.get("ignored_position_ids") or [])
        # Do not derive the global checkpoint from a single position event: replay
        # must re-offer an interrupted WAL event to every open shadow position.
        self._reconcile_missing_outcomes()

    def _append_event(
        self,
        event_type: str,
        state: dict[str, Any],
        key: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = f"{POLICY_ID}|{self.epoch_id}|{state['canonical_position_id']}|{key}"
        if event_id in self.event_ids:
            return self.states.get(str(state["canonical_position_id"]), state)
        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "recorded_at": utc_now(),
            "policy_id": POLICY_ID,
            "policy_version": POLICY_VERSION,
            "policy_fingerprint": self.manifest["policy_fingerprint"],
            "paper_epoch_id": self.epoch_id,
            "canonical_position_id": state["canonical_position_id"],
            "position_after": state,
            **(extra or {}),
        }
        JsonStore.append_jsonl(self.store.events_path, payload)
        self.event_ids.add(event_id)
        self.states[str(state["canonical_position_id"])] = state
        return state

    def _entry_rows(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        for row in self._rows("positions"):
            position_id = str(row.get("position_id") or "")
            if position_id and position_id not in entries and all(row.get(k) is not None for k in ("entry_price", "quantity", "opened_at")):
                entries[position_id] = row
        return entries

    def _latest_positions(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._rows("positions"):
            if row.get("position_id"):
                latest[str(row["position_id"])] = row
        return latest

    def _canonical_closes(self) -> dict[str, CanonicalClose]:
        closes: dict[str, CanonicalClose] = {}
        for row in self._rows("trades"):
            position_id = str(row.get("position_id") or "")
            raw_ts = str(row.get("exit_ts") or row.get("closed_at") or "")
            timestamp = parse_timestamp(raw_ts)
            try:
                price = float(row.get("exit_price"))
            except (TypeError, ValueError):
                continue
            if not position_id or timestamp is None or price <= 0:
                continue
            net = row.get("net_pnl_usd")
            closes[position_id] = CanonicalClose(
                position_id, timestamp, raw_ts, price,
                str(row.get("exit_reason") or "CANONICAL_EXIT").upper(),
                float(net) if net is not None else None,
            )
        return closes

    def _offset_before(self, opened_at: datetime) -> int:
        prior = 0
        for event in self.wal.iter_from_offset(0):
            timestamp = event_timestamp(event)
            if timestamp is not None and timestamp >= opened_at:
                return max(0, int(event.get("wal_offset") or 0) - 1)
            prior = int(event.get("wal_offset") or prior)
        return prior

    def discover_new_positions(self) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        latest = self._latest_positions()
        for position_id, source in self._entry_rows().items():
            if position_id in self.states or position_id in self.ignored_position_ids:
                continue
            opened_at = parse_timestamp(source.get("opened_at"))
            if opened_at is None or opened_at < self.policy_effective_at:
                self.ignored_position_ids.add(position_id)
                continue
            if str(latest.get(position_id, source).get("status") or "").upper() != "OPEN":
                self.ignored_position_ids.add(position_id)
                continue
            side = str(source.get("side") or "").upper()
            entry = float(source.get("entry_price") or 0.0)
            quantity = float(source.get("quantity") or 0.0)
            stop = float(source.get("stop_loss_price") or 0.0)
            take = float(source.get("take_profit_price") or 0.0)
            partial_quantity, remaining_quantity = split_one_third(quantity)
            state = {
                "policy_id": POLICY_ID,
                "policy_version": POLICY_VERSION,
                "policy_fingerprint": self.manifest["policy_fingerprint"],
                "paper_epoch_id": self.epoch_id,
                "canonical_position_id": position_id,
                "timeframe": str(source.get("timeframe") or "").upper(),
                "side": side,
                "entry_price": entry,
                "original_quantity": quantity,
                "original_stop": stop,
                "original_take": take,
                "opened_at": source.get("opened_at"),
                "context_event_id": source.get("entry_context_event_id"),
                "context_provenance": {
                    "entry_context_event_id": source.get("entry_context_event_id"),
                    "lifecycle_episode_id": source.get("lifecycle_episode_id"),
                },
                "risk_amount_usd": float(source.get("risk_amount_usd") or source.get("risk_budget_usd") or 0.0),
                "partial_trigger_price": partial_trigger_price(side=side, entry_price=entry, take_price=take),
                "partial_quantity": partial_quantity,
                "remaining_quantity": remaining_quantity,
                "partial_taken": False,
                "economic_break_even_price": None,
                "shadow_stop": stop,
                "state": STATE_OPEN_FULL,
                "state_history": [STATE_OPEN_FULL],
                "source_wal_offset": self._offset_before(opened_at),
            }
            self._append_event(
                "STP_BE33_POSITION_OPENED", state, "OPEN",
                {"policy_effective_at": self.manifest["policy_effective_at"]},
            )
            actions.append({"status": "STP_BE33_POSITION_OPENED", "canonical_position_id": position_id})
        return actions

    @staticmethod
    def _crosses(state: dict[str, Any], price: float, level: str) -> bool:
        value = float(state[level])
        if level == "shadow_stop":
            return price <= value if state["side"] == "LONG" else price >= value
        return price >= value if state["side"] == "LONG" else price <= value

    @staticmethod
    def _provenance(event: dict[str, Any]) -> dict[str, Any]:
        timestamp = event_timestamp(event)
        return {
            "trigger_agg_trade_id": event.get("aggregate_trade_id"),
            "trigger_source_event_id": event.get("source_event_id"),
            "execution_market_wal_offset": int(event.get("wal_offset") or 0),
            "trigger_timestamp": timestamp.isoformat().replace("+00:00", "Z") if timestamp else None,
            "trigger_market_price": float(event.get("price") or 0.0),
            "trigger_source": "BINANCE_FUTURES_AGG_TRADE_DURABLE_EXECUTION_WAL",
        }

    def _partial(self, state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        if state.get("partial_taken"):
            return state
        partial_econ = closed_trade_economics(
            cfg=self.cfg,
            side=state["side"],
            entry_price=state["entry_price"],
            exit_price=state["partial_trigger_price"],
            quantity=state["partial_quantity"],
            risk_amount_usd=state["risk_amount_usd"],
            exit_reason="PARTIAL_TAKE",
        )
        remaining_risk = state["risk_amount_usd"] * state["remaining_quantity"] / state["original_quantity"]
        be_price, be_econ = solve_economic_break_even(
            cfg=self.cfg,
            side=state["side"],
            entry_price=state["entry_price"],
            quantity=state["remaining_quantity"],
            risk_amount_usd=remaining_risk,
        )
        provenance = self._provenance(event)
        updated = {
            **state,
            "state": STATE_BE_PROTECTED,
            "state_history": [*state["state_history"], "PARTIAL_TRIGGERED", "PARTIAL_CLOSED", STATE_BE_PROTECTED],
            "partial_taken": True,
            "partial_trigger_timestamp": provenance["trigger_timestamp"],
            "partial_trigger_agg_trade_id": provenance["trigger_agg_trade_id"],
            "partial_trigger_source_event_id": provenance["trigger_source_event_id"],
            "partial_trigger_wal_offset": provenance["execution_market_wal_offset"],
            "partial_trigger_market_price": provenance["trigger_market_price"],
            "partial_exit_price": state["partial_trigger_price"],
            "partial_gross_pnl_usd": partial_econ["gross_pnl_usd"],
            "partial_fees_usd": partial_econ["fees_usd"],
            "partial_slippage_usd": partial_econ["slippage_usd"],
            "partial_net_pnl_usd": partial_econ["net_pnl_usd"],
            "partial_r_contribution": partial_econ["r_multiple"],
            "stop_before": state["shadow_stop"],
            "economic_break_even_price": be_price,
            "stop_after": be_price,
            "shadow_stop": be_price,
            "economic_break_even_validation_net_pnl_usd": be_econ["net_pnl_usd"],
            "economic_assumptions": {
                "economics_source": self.cfg.economics_source,
                "entry_fee_bps": self.cfg.entry_fee_bps,
                "exit_fee_bps": self.cfg.exit_fee_bps,
                "entry_slippage_bps": self.cfg.entry_slippage_bps,
                "stop_exit_slippage_bps": self.cfg.stop_exit_slippage_bps,
                "remaining_risk_amount_usd": remaining_risk,
            },
        }
        return self._append_event(
            "STP_BE33_STOP_MOVED", updated,
            f"PARTIAL:{provenance['trigger_agg_trade_id']}",
            {**provenance, "reason": "PARTIAL_1_3_REACHED", "state_transition_path": [STATE_OPEN_FULL, "PARTIAL_TRIGGERED", "PARTIAL_CLOSED", STATE_BE_PROTECTED]},
        )

    def _close(
        self,
        state: dict[str, Any],
        *,
        reason: str,
        price: float,
        timestamp: str,
        key: str,
        provenance: dict[str, Any],
        canonical_net: float | None = None,
    ) -> dict[str, Any]:
        partial_taken = bool(state.get("partial_taken"))
        quantity = state["remaining_quantity"] if partial_taken else state["original_quantity"]
        econ = closed_trade_economics(
            cfg=self.cfg,
            side=state["side"],
            entry_price=state["entry_price"],
            exit_price=price,
            quantity=quantity,
            risk_amount_usd=state["risk_amount_usd"],
            exit_reason="SL" if reason == "BE_STOP" else reason,
        )
        total_net = float(state.get("partial_net_pnl_usd") or 0.0) + float(econ["net_pnl_usd"])
        difference = total_net - canonical_net if canonical_net is not None else None
        notional = abs(state["entry_price"] * state["original_quantity"])
        terminal = STATE_CLOSED if partial_taken else STATE_CLOSED_WITHOUT_PARTIAL
        updated = {
            **state,
            "state": terminal,
            "state_history": [*state["state_history"], terminal],
            "closed_at": timestamp,
            "final_exit_reason": reason,
            "final_exit_price": price,
            "remaining_gross_pnl_usd": econ["gross_pnl_usd"],
            "remaining_fees_usd": econ["fees_usd"],
            "remaining_slippage_usd": econ["slippage_usd"],
            "remaining_net_pnl_usd": econ["net_pnl_usd"],
            "total_net_pnl_usd": total_net,
            "total_R": total_net / state["risk_amount_usd"] if state["risk_amount_usd"] else 0.0,
            "canonical_net_pnl_usd": canonical_net,
            "net_difference_vs_canonical_usd": difference,
            "net_difference_vs_canonical_bps": difference / notional * 10_000.0 if difference is not None and notional else None,
            "close_provenance": provenance,
        }
        updated = self._append_event("STP_BE33_POSITION_CLOSED", updated, key, provenance)
        self._append_outcome(updated)
        return updated

    def _append_outcome(self, state: dict[str, Any]) -> None:
        comparison_tag = "CANONICAL_COMPARISON" if state.get("canonical_net_pnl_usd") is not None else "INITIAL"
        outcome_id = f"{POLICY_ID}|{self.epoch_id}|{state['canonical_position_id']}|OUTCOME|{comparison_tag}"
        if outcome_id in self.outcome_ids:
            return
        fields = (
            "timeframe", "side", "entry_price", "original_quantity", "original_stop", "original_take",
            "partial_trigger_price", "partial_trigger_timestamp", "partial_trigger_agg_trade_id",
            "partial_trigger_source_event_id", "partial_trigger_wal_offset", "partial_exit_price",
            "partial_gross_pnl_usd", "partial_fees_usd", "partial_slippage_usd", "partial_net_pnl_usd",
            "remaining_quantity", "stop_before", "economic_break_even_price", "stop_after",
            "final_exit_reason", "final_exit_price", "remaining_gross_pnl_usd", "remaining_fees_usd",
            "remaining_slippage_usd", "remaining_net_pnl_usd", "total_net_pnl_usd", "total_R",
            "canonical_net_pnl_usd", "net_difference_vs_canonical_usd", "net_difference_vs_canonical_bps",
        )
        outcome = {
            "outcome_id": outcome_id,
            "policy_id": POLICY_ID,
            "policy_version": POLICY_VERSION,
            "policy_fingerprint": self.manifest["policy_fingerprint"],
            "canonical_position_id": state["canonical_position_id"],
            "partial_quantity": state["partial_quantity"] if state.get("partial_taken") else 0.0,
            "terminal_state": state["state"],
            "recorded_at": utc_now(),
            **{field: state.get(field) for field in fields},
        }
        JsonStore.append_jsonl(self.store.outcomes_path, outcome)
        self.outcome_ids.add(outcome_id)

    def _reconcile_missing_outcomes(self) -> None:
        for state in self.states.values():
            if state.get("state") in {STATE_CLOSED, STATE_CLOSED_WITHOUT_PARTIAL}:
                self._append_outcome(state)

    def _attach_canonical_comparison(self, state: dict[str, Any], close: CanonicalClose) -> dict[str, Any]:
        if state.get("canonical_net_pnl_usd") is not None or close.net_pnl_usd is None:
            return state
        total_net = float(state["total_net_pnl_usd"])
        difference = total_net - close.net_pnl_usd
        notional = abs(state["entry_price"] * state["original_quantity"])
        updated = {
            **state,
            "canonical_net_pnl_usd": close.net_pnl_usd,
            "net_difference_vs_canonical_usd": difference,
            "net_difference_vs_canonical_bps": difference / notional * 10_000.0 if notional else None,
        }
        updated = self._append_event(
            "STP_BE33_CANONICAL_COMPARISON_ATTACHED", updated,
            f"COMPARISON:{close.timestamp_raw}",
            {"canonical_exit_timestamp": close.timestamp_raw, "canonical_exit_reason": close.reason},
        )
        self._append_outcome(updated)
        return updated

    def _canonical_close(self, state: dict[str, Any], close: CanonicalClose) -> dict[str, Any]:
        return self._close(
            state,
            reason=close.reason,
            price=close.price,
            timestamp=close.timestamp_raw,
            key=f"CANONICAL:{close.reason}:{close.timestamp_raw}",
            provenance={"trigger_source": "CANONICAL_PAPER_TRADE", "canonical_exit_timestamp": close.timestamp_raw},
            canonical_net=close.net_pnl_usd,
        )

    def process_wal(self) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        closes = self._canonical_closes()
        for event in self.wal.iter_from_offset(self.last_processed_wal_offset):
            offset = int(event.get("wal_offset") or 0)
            self.last_processed_wal_offset = max(self.last_processed_wal_offset, offset)
            if event.get("event_type") != EVENT_AGG_TRADE or event.get("source") != SOURCE_BINANCE_FUTURES:
                continue
            timestamp = event_timestamp(event)
            price = float(event.get("price") or 0.0)
            if timestamp is None or price <= 0:
                continue
            for position_id, state in list(self.states.items()):
                if state.get("state") not in {STATE_OPEN_FULL, STATE_BE_PROTECTED} or offset <= int(state["source_wal_offset"]):
                    continue
                close = closes.get(position_id)
                if close and close.timestamp <= timestamp and (
                    state["state"] == STATE_OPEN_FULL or close.reason in CONTEXT_EXITS | {"TP", "TAKE_PROFIT"}
                ):
                    state = self._canonical_close(state, close)
                    actions.append({"status": state["state"], "canonical_position_id": position_id})
                    continue
                provenance = self._provenance(event)
                if self._crosses(state, price, "shadow_stop"):
                    state = self._close(
                        state,
                        reason="BE_STOP" if state.get("partial_taken") else "SL",
                        price=state["shadow_stop"],
                        timestamp=str(provenance["trigger_timestamp"]),
                        key=f"STOP:{event.get('aggregate_trade_id')}",
                        provenance=provenance,
                        canonical_net=close.net_pnl_usd if close else None,
                    )
                    actions.append({"status": state["state"], "canonical_position_id": position_id})
                    continue
                if state["state"] == STATE_OPEN_FULL and self._crosses(state, price, "partial_trigger_price"):
                    state = self._partial(state, event)
                    actions.append({"status": "PARTIAL_CLOSED_BE_PROTECTED", "canonical_position_id": position_id})
                if self._crosses(state, price, "original_take"):
                    state = self._close(
                        state,
                        reason="TP",
                        price=state["original_take"],
                        timestamp=str(provenance["trigger_timestamp"]),
                        key=f"TP:{event.get('aggregate_trade_id')}",
                        provenance=provenance,
                        canonical_net=close.net_pnl_usd if close else None,
                    )
                    actions.append({"status": state["state"], "canonical_position_id": position_id})
        return actions

    def reconcile_canonical_closes(self) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for position_id, close in self._canonical_closes().items():
            state = self.states.get(position_id)
            if not state:
                continue
            if state.get("state") in {STATE_CLOSED, STATE_CLOSED_WITHOUT_PARTIAL}:
                updated = self._attach_canonical_comparison(state, close)
                if updated is not state:
                    actions.append({"status": "CANONICAL_COMPARISON_ATTACHED", "canonical_position_id": position_id})
                continue
            if state["state"] == STATE_OPEN_FULL or close.reason in CONTEXT_EXITS | {"TP", "TAKE_PROFIT"}:
                state = self._canonical_close(state, close)
                actions.append({"status": state["state"], "canonical_position_id": position_id})
        return actions

    def _save_checkpoint(self) -> None:
        JsonStore.write_json(self.store.checkpoint_path, {
            "schema_version": "stp_be33_checkpoint_v1",
            "policy_id": POLICY_ID,
            "policy_version": POLICY_VERSION,
            "paper_epoch_id": self.epoch_id,
            "last_processed_wal_offset": self.last_processed_wal_offset,
            "ignored_position_ids": sorted(self.ignored_position_ids),
            "updated_at": utc_now(),
        })

    def metrics(self) -> dict[str, Any]:
        states = list(self.states.values())
        latest_outcomes: dict[str, dict[str, Any]] = {}
        for row in JsonStore.read_jsonl(self.store.outcomes_path):
            if row.get("canonical_position_id"):
                latest_outcomes[str(row["canonical_position_id"])] = row
        outcomes = list(latest_outcomes.values())
        comparisons = [float(row["net_difference_vs_canonical_usd"]) for row in outcomes if row.get("net_difference_vs_canonical_usd") is not None]
        canonical = [float(row["canonical_net_pnl_usd"]) for row in outcomes if row.get("canonical_net_pnl_usd") is not None]
        equity = peak = drawdown = 0.0
        for outcome in outcomes:
            equity += float(outcome.get("total_net_pnl_usd") or 0.0)
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        partial_count = sum(bool(state.get("partial_taken")) for state in states)
        return {
            "positions_observed": len(states),
            "partial_trigger_reached": partial_count,
            "partial_trigger_rate": partial_count / len(states) if states else 0.0,
            "be_stops_hit": sum(row.get("final_exit_reason") == "BE_STOP" for row in outcomes),
            "tp_after_partial": sum(row.get("final_exit_reason") == "TP" and bool(row.get("partial_trigger_timestamp")) for row in outcomes),
            "canonical_exit_before_partial": sum(not row.get("partial_trigger_timestamp") for row in outcomes),
            "total_net_pnl_stp_be33": sum(float(row.get("total_net_pnl_usd") or 0.0) for row in outcomes),
            "total_net_pnl_canonical_baseline": sum(canonical) if canonical else None,
            "difference_usd": sum(comparisons) if comparisons else None,
            "difference_bps": sum(float(row.get("net_difference_vs_canonical_bps") or 0.0) for row in outcomes if row.get("net_difference_vs_canonical_bps") is not None),
            "average_R": sum(float(row.get("total_R") or 0.0) for row in outcomes) / len(outcomes) if outcomes else 0.0,
            "maximum_drawdown_usd": drawdown,
            "prevented_loss_usd": sum(max(0.0, value) for value in comparisons),
            "missed_upside_usd": sum(max(0.0, -value) for value in comparisons),
        }

    def write_health(self) -> dict[str, Any]:
        health = {
            "status": "STP_BE33_RUNNING_SHADOW_ONLY",
            "updated_at": utc_now(),
            "policy_id": POLICY_ID,
            "policy_version": POLICY_VERSION,
            "policy_fingerprint": self.manifest["policy_fingerprint"],
            "policy_effective_at": self.manifest["policy_effective_at"],
            "paper_epoch_id": self.epoch_id,
            "last_processed_wal_offset": self.last_processed_wal_offset,
            "wal_last_offset": self.wal.last_offset,
            "canonical_write_capability": False,
            "live1b_command_capability": False,
            "real_execution_capability": False,
            "trigger_source": "BINANCE_FUTURES_AGG_TRADE_DURABLE_EXECUTION_WAL",
            "metrics": self.metrics(),
        }
        JsonStore.write_json(self.store.health_path, health)
        return health

    def poll_once(self) -> dict[str, Any]:
        actions = self.discover_new_positions()
        actions.extend(self.process_wal())
        actions.extend(self.reconcile_canonical_closes())
        self._save_checkpoint()
        return {"actions": actions, "health": self.write_health()}
