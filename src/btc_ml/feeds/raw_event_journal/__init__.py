"""Shadow raw intrabar market event journal (aggTrade + bookTicker).

Independent data plane — no cognition / trading consumers.
"""

from .schemas import SCHEMA_VERSION, StreamType
from .normalize import normalize_agg_trade, normalize_book_ticker
from .writer import AtomicJournalWriter
from .reader import RawEventJournalReader
from .health import HealthSnapshot, HealthStatus

__all__ = [
    "SCHEMA_VERSION",
    "StreamType",
    "normalize_agg_trade",
    "normalize_book_ticker",
    "AtomicJournalWriter",
    "RawEventJournalReader",
    "HealthSnapshot",
    "HealthStatus",
]
