"""Causal partial-bar state for M15/M30/H1/H4 (LIVE1A)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import pandas as pd

TIMEFRAMES = ("M15", "M30", "H1", "H4")
TF_SECONDS = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}
PANDAS_RULE = {"M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h"}


def _ts(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def bar_open_for(timestamp: Any, timeframe: str) -> pd.Timestamp:
    stamp = _ts(timestamp)
    # Floor to timeframe bucket in UTC.
    period = pd.Timedelta(seconds=TF_SECONDS[timeframe])
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    delta = stamp - epoch
    buckets = delta // period
    return epoch + buckets * period


@dataclass
class PartialBar:
    timeframe: str
    bar_open_timestamp: pd.Timestamp
    open: float
    high_so_far: float
    low_so_far: float
    last: float
    volume_so_far: float = 0.0
    quote_volume_so_far: float = 0.0
    buy_volume_so_far: float = 0.0
    sell_volume_so_far: float = 0.0
    trade_count_so_far: int = 0
    last_trade_id: Optional[int] = None
    last_trade_timestamp: Optional[str] = None
    causal_cutoff_timestamp: Optional[str] = None
    causal_cutoff_monotonic_ns: Optional[int] = None
    is_closed: bool = False

    @property
    def delta(self) -> float:
        return float(self.buy_volume_so_far - self.sell_volume_so_far)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "bar_open_timestamp": self.bar_open_timestamp.isoformat().replace("+00:00", "Z"),
            "open": self.open,
            "high_so_far": self.high_so_far,
            "low_so_far": self.low_so_far,
            "last": self.last,
            "close": self.last,
            "high": self.high_so_far,
            "low": self.low_so_far,
            "volume": self.volume_so_far,
            "volume_so_far": self.volume_so_far,
            "quote_volume_so_far": self.quote_volume_so_far,
            "buy_volume_so_far": self.buy_volume_so_far,
            "sell_volume_so_far": self.sell_volume_so_far,
            "trade_count_so_far": self.trade_count_so_far,
            "delta": self.delta,
            "last_trade_id": self.last_trade_id,
            "last_trade_timestamp": self.last_trade_timestamp,
            "causal_cutoff_timestamp": self.causal_cutoff_timestamp,
            "causal_cutoff_monotonic_ns": self.causal_cutoff_monotonic_ns,
            "is_closed": self.is_closed,
            "evaluation_mode": "PROVISIONAL_INTRABAR",
        }


@dataclass
class PartialBarStateEngine:
    """Independent causal open bars per timeframe."""

    bars: dict[str, PartialBar] = field(default_factory=dict)
    completed: list[dict[str, Any]] = field(default_factory=list)

    def update_agg_trade(self, event: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Apply one causal aggTrade. Returns list of just-closed completed bars."""
        price = float(event["price"])
        qty = float(event["quantity"] or 0.0)
        quote = float(event.get("quote_quantity") or (price * qty))
        trade_ts = event.get("exchange_trade_timestamp") or event.get("local_receive_timestamp")
        recv_ts = event.get("local_receive_timestamp")
        mono = int(event.get("local_receive_monotonic_ns") or 0)
        trade_id = event.get("aggregate_trade_id")
        # Binance m=True => buyer is maker => seller aggressor => sell volume
        is_sell = bool(event.get("buyer_is_market_maker"))
        closed: list[dict[str, Any]] = []
        for tf in TIMEFRAMES:
            open_ts = bar_open_for(trade_ts or recv_ts, tf)
            current = self.bars.get(tf)
            if current is not None and open_ts > current.bar_open_timestamp:
                current.is_closed = True
                closed.append(current.to_dict())
                self.completed.append(current.to_dict())
                current = None
            if current is None or current.bar_open_timestamp != open_ts:
                current = PartialBar(
                    timeframe=tf,
                    bar_open_timestamp=open_ts,
                    open=price,
                    high_so_far=price,
                    low_so_far=price,
                    last=price,
                )
                self.bars[tf] = current
            current.high_so_far = max(current.high_so_far, price)
            current.low_so_far = min(current.low_so_far, price)
            current.last = price
            current.volume_so_far += qty
            current.quote_volume_so_far += quote
            if is_sell:
                current.sell_volume_so_far += qty
            else:
                current.buy_volume_so_far += qty
            current.trade_count_so_far += 1
            current.last_trade_id = int(trade_id) if trade_id is not None else current.last_trade_id
            current.last_trade_timestamp = str(trade_ts) if trade_ts else current.last_trade_timestamp
            current.causal_cutoff_timestamp = str(recv_ts) if recv_ts else current.causal_cutoff_timestamp
            current.causal_cutoff_monotonic_ns = mono
            current.is_closed = False
        return closed

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {tf: bar.to_dict() for tf, bar in self.bars.items()}
