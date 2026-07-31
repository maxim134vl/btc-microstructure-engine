"""Shadow raw intrabar market event journal (aggTrade + bookTicker).

Independent data plane — no cognition / trading consumers.
TRD1A.1: bounded queue + archival Parquet/ZSTD writer.
"""

from .schemas import SCHEMA_VERSION, StreamType
from .normalize import normalize_agg_trade, normalize_book_ticker
from .writer import AtomicJournalWriter
from .archival_writer import ArchivalParquetWriter, ChunkPolicy
from .queue import BoundedEventQueue
from .reader import RawEventJournalReader
from .health import HealthSnapshot, HealthStatus

__all__ = [
    "SCHEMA_VERSION",
    "StreamType",
    "normalize_agg_trade",
    "normalize_book_ticker",
    "AtomicJournalWriter",
    "ArchivalParquetWriter",
    "ChunkPolicy",
    "BoundedEventQueue",
    "RawEventJournalReader",
    "HealthSnapshot",
    "HealthStatus",
]
