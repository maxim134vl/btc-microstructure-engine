"""Per-timeframe capital sleeves for LIVE1B PER_TIMEFRAME_REALIZED_EQUITY."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TIMEFRAMES = ("M15", "M30", "H1", "H4")
SLEEVES_FILENAME = "sleeves.json"
DEFAULT_INITIAL = 100_000.0
DEFAULT_RISK_PCT = 1.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class SleeveState:
    timeframe: str
    initial_equity_usd: float
    cumulative_realized_net_pnl_usd: float
    risk_pct_per_trade: float
    open_position_id: str | None
    open_position_risk_usd: float
    closed_trades_count: int
    last_realized_update_at: str | None
    epoch_id: str

    @property
    def current_equity_usd(self) -> float:
        return float(self.initial_equity_usd) + float(self.cumulative_realized_net_pnl_usd)

    @property
    def next_risk_budget_usd(self) -> float:
        return float(self.current_equity_usd) * float(self.risk_pct_per_trade) / 100.0

    @property
    def available_risk_usd(self) -> float:
        if self.open_position_id:
            return 0.0
        return float(self.next_risk_budget_usd)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["current_equity_usd"] = self.current_equity_usd
        d["next_risk_budget_usd"] = self.next_risk_budget_usd
        d["available_risk_usd"] = self.available_risk_usd
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SleeveState":
        return cls(
            timeframe=str(raw["timeframe"]).upper(),
            initial_equity_usd=float(raw["initial_equity_usd"]),
            cumulative_realized_net_pnl_usd=float(raw.get("cumulative_realized_net_pnl_usd") or 0.0),
            risk_pct_per_trade=float(raw.get("risk_pct_per_trade") or DEFAULT_RISK_PCT),
            open_position_id=raw.get("open_position_id"),
            open_position_risk_usd=float(raw.get("open_position_risk_usd") or 0.0),
            closed_trades_count=int(raw.get("closed_trades_count") or 0),
            last_realized_update_at=raw.get("last_realized_update_at"),
            epoch_id=str(raw.get("epoch_id") or ""),
        )


@dataclass
class SleeveLedger:
    epoch_id: str
    sleeves: dict[str, SleeveState] = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def initialize(
        cls,
        *,
        epoch_id: str,
        epoch_root: Path,
        initial_equity_usd: float = DEFAULT_INITIAL,
        risk_pct_per_trade: float = DEFAULT_RISK_PCT,
        timeframes: tuple[str, ...] = TIMEFRAMES,
        risk_pct_by_timeframe: dict[str, float] | None = None,
    ) -> "SleeveLedger":
        risk_map = {
            str(tf).upper(): float((risk_pct_by_timeframe or {}).get(tf, risk_pct_per_trade))
            for tf in timeframes
        }
        sleeves = {
            tf: SleeveState(
                timeframe=tf,
                initial_equity_usd=float(initial_equity_usd),
                cumulative_realized_net_pnl_usd=0.0,
                risk_pct_per_trade=float(risk_map[tf]),
                open_position_id=None,
                open_position_risk_usd=0.0,
                closed_trades_count=0,
                last_realized_update_at=None,
                epoch_id=epoch_id,
            )
            for tf in timeframes
        }
        ledger = cls(epoch_id=epoch_id, sleeves=sleeves, path=epoch_root / SLEEVES_FILENAME)
        ledger.save()
        return ledger

    @classmethod
    def load(cls, epoch_root: Path) -> "SleeveLedger | None":
        path = Path(epoch_root) / SLEEVES_FILENAME
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        sleeves_raw = raw.get("sleeves") or {}
        sleeves = {
            str(tf).upper(): SleeveState.from_dict(row)
            for tf, row in sleeves_raw.items()
        }
        return cls(epoch_id=str(raw.get("epoch_id") or ""), sleeves=sleeves, path=path)

    def save(self) -> None:
        if self.path is None:
            raise ValueError("sleeve ledger path not set")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "per_tf_equity_sleeves_v1",
            "epoch_id": self.epoch_id,
            "updated_at": _utc_now(),
            "sleeves": {tf: s.to_dict() for tf, s in sorted(self.sleeves.items())},
            "master": self.master_snapshot(),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def get(self, timeframe: str) -> SleeveState:
        tf = str(timeframe).upper()
        if tf not in self.sleeves:
            raise KeyError(tf)
        return self.sleeves[tf]

    def mark_open(self, timeframe: str, position_id: str, risk_usd: float) -> None:
        s = self.get(timeframe)
        s.open_position_id = position_id
        s.open_position_risk_usd = float(risk_usd)
        self.save()

    def clear_open(self, timeframe: str) -> None:
        s = self.get(timeframe)
        s.open_position_id = None
        s.open_position_risk_usd = 0.0
        self.save()

    def apply_realized_net_pnl(self, timeframe: str, net_pnl_usd: float, *, at: str | None = None) -> SleeveState:
        """Apply closed-trade net PnL (fees/slippage already inside net)."""
        s = self.get(timeframe)
        s.cumulative_realized_net_pnl_usd = float(s.cumulative_realized_net_pnl_usd) + float(net_pnl_usd)
        s.closed_trades_count = int(s.closed_trades_count) + 1
        s.last_realized_update_at = at or _utc_now()
        s.open_position_id = None
        s.open_position_risk_usd = 0.0
        self.save()
        return s

    def apply_realized_net_pnl_adjustment(
        self,
        timeframe: str,
        net_pnl_delta_usd: float,
        *,
        at: str | None = None,
    ) -> SleeveState:
        """Apply a PnL correction delta without incrementing closed trade count."""
        s = self.get(timeframe)
        s.cumulative_realized_net_pnl_usd = float(s.cumulative_realized_net_pnl_usd) + float(net_pnl_delta_usd)
        s.last_realized_update_at = at or _utc_now()
        self.save()
        return s

    def sync_open_from_positions(self, open_positions: list[dict[str, Any]]) -> None:
        """Restart recovery: align open markers with books without rewriting PnL."""
        by_tf = {str(p.get("timeframe") or "").upper(): p for p in open_positions}
        dirty = False
        for tf, sleeve in self.sleeves.items():
            pos = by_tf.get(tf)
            if pos is None:
                if sleeve.open_position_id is not None or sleeve.open_position_risk_usd:
                    sleeve.open_position_id = None
                    sleeve.open_position_risk_usd = 0.0
                    dirty = True
            else:
                pid = str(pos.get("position_id") or "")
                risk = float(pos.get("risk_amount_usd") or 0.0)
                if sleeve.open_position_id != pid or sleeve.open_position_risk_usd != risk:
                    sleeve.open_position_id = pid
                    sleeve.open_position_risk_usd = risk
                    dirty = True
        if dirty:
            self.save()

    def master_snapshot(self) -> dict[str, Any]:
        sleeves = list(self.sleeves.values())
        master_initial = sum(s.initial_equity_usd for s in sleeves)
        master_current = sum(s.current_equity_usd for s in sleeves)
        master_realized = sum(s.cumulative_realized_net_pnl_usd for s in sleeves)
        master_open_risk = sum(s.open_position_risk_usd for s in sleeves if s.open_position_id)
        master_risk_capacity = sum(s.next_risk_budget_usd for s in sleeves)
        master_available = sum(s.available_risk_usd for s in sleeves)
        open_count = sum(1 for s in sleeves if s.open_position_id)
        return {
            "master_initial_equity_usd": master_initial,
            "master_current_equity_usd": master_current,
            "master_realized_net_pnl_usd": master_realized,
            "master_unrealized_pnl_usd": 0.0,
            "master_open_risk_usd": master_open_risk,
            "master_risk_capacity_usd": master_risk_capacity,
            "master_available_risk_usd": master_available,
            "master_open_notional_usd": None,
            "open_positions_count": open_count,
        }

    def ops_trader_rows(self) -> list[dict[str, Any]]:
        rows = []
        for tf in TIMEFRAMES:
            if tf not in self.sleeves:
                continue
            s = self.sleeves[tf]
            rows.append(
                {
                    "timeframe": tf,
                    "initial_equity_usd": s.initial_equity_usd,
                    "current_equity_usd": s.current_equity_usd,
                    "risk_pct_per_trade": s.risk_pct_per_trade,
                    "next_risk_budget_usd": s.next_risk_budget_usd,
                    "open_risk_usd": s.open_position_risk_usd if s.open_position_id else 0.0,
                    "available_risk_usd": s.available_risk_usd,
                    "realized_pnl_usd": s.cumulative_realized_net_pnl_usd,
                    "unrealized_pnl_usd": 0.0,
                    "open_position_id": s.open_position_id,
                    "closed_trades_count": s.closed_trades_count,
                }
            )
        return rows
