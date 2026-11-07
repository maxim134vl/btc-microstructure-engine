"""Storage-only configuration for the LIVE1B execution-market WAL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionMarketWalConfig:
    mode: str
    segment_max_bytes: int
    archive_batch_rows: int
    delete_verified_plaintext: bool
    plaintext_retention_hours: float
    warning_size_bytes: int
    critical_size_bytes: int

    @property
    def segmented_enabled(self) -> bool:
        return self.mode == "segmented"


def load_execution_market_wal_config(path: Path) -> ExecutionMarketWalConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "execution_market_wal_storage_v1":
        raise ValueError("unsupported execution WAL storage config schema")
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in {"legacy", "segmented"}:
        raise ValueError("execution WAL storage mode must be legacy or segmented")
    segment_max_bytes = int(raw.get("segment_max_bytes") or 0)
    archive_batch_rows = int(raw.get("archive_batch_rows") or 0)
    plaintext_retention_hours = float(raw.get("plaintext_retention_hours", 0.0))
    warning_size_bytes = int(raw.get("warning_size_bytes") or 10 * 1024**3)
    critical_size_bytes = int(raw.get("critical_size_bytes") or 20 * 1024**3)
    if segment_max_bytes <= 0 or archive_batch_rows <= 0:
        raise ValueError("execution WAL segment and archive batch sizes must be positive")
    if plaintext_retention_hours < 0:
        raise ValueError("execution WAL plaintext retention must not be negative")
    if warning_size_bytes <= 0 or critical_size_bytes <= warning_size_bytes:
        raise ValueError("execution WAL size thresholds must be positive and ordered")
    return ExecutionMarketWalConfig(
        mode=mode,
        segment_max_bytes=segment_max_bytes,
        archive_batch_rows=archive_batch_rows,
        delete_verified_plaintext=bool(raw.get("delete_verified_plaintext", False)),
        plaintext_retention_hours=plaintext_retention_hours,
        warning_size_bytes=warning_size_bytes,
        critical_size_bytes=critical_size_bytes,
    )
