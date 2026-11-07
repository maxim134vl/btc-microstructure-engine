"""Paper epoch registry for LIVE1B isolation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


@dataclass
class PaperEpoch:
    paper_epoch_id: str
    epoch_status: str
    created_at: str
    activated_at: str | None
    closed_at: str | None
    initial_equity_usd: float
    rule_contract_version: str
    void_reason: str | None = None
    failed_reason: str | None = None
    activated_at_monotonic_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PaperEpoch":
        return cls(
            paper_epoch_id=str(raw["paper_epoch_id"]),
            epoch_status=str(raw["epoch_status"]),
            created_at=str(raw["created_at"]),
            activated_at=raw.get("activated_at"),
            closed_at=raw.get("closed_at"),
            initial_equity_usd=float(raw["initial_equity_usd"]),
            rule_contract_version=str(raw["rule_contract_version"]),
            void_reason=raw.get("void_reason"),
            failed_reason=raw.get("failed_reason"),
            activated_at_monotonic_ns=(
                int(raw["activated_at_monotonic_ns"])
                if raw.get("activated_at_monotonic_ns") is not None
                else None
            ),
        )


def create_epoch(
    *,
    epochs_root: Path,
    initial_equity_usd: float,
    rule_contract_version: str = "INTRABAR_RULES_V1",
    utc_stamp: str | None = None,
) -> PaperEpoch:
    epochs_root.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp or _ts()
    epoch = PaperEpoch(
        paper_epoch_id=f"INTRABAR_RULES_V1_{stamp}",
        epoch_status="CREATED",
        created_at=_utc_now().isoformat().replace("+00:00", "Z"),
        activated_at=None,
        closed_at=None,
        initial_equity_usd=float(initial_equity_usd),
        rule_contract_version=rule_contract_version,
    )
    path = epochs_root / f"{epoch.paper_epoch_id}.json"
    path.write_text(json.dumps(epoch.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return epoch


def activate_epoch(epoch: PaperEpoch, *, epochs_root: Path) -> PaperEpoch:
    epoch.epoch_status = "ACTIVE"
    epoch.activated_at = _utc_now().isoformat().replace("+00:00", "Z")
    # Do NOT stamp process-local monotonic here: context events use the
    # cognition process monotonic clock. Post-activation gating is ISO-based.
    epoch.activated_at_monotonic_ns = None
    _write_epoch(epoch, epochs_root)
    active = epochs_root / "active.json"
    active.write_text(json.dumps(epoch.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return epoch


def mark_epoch_status(
    epoch: PaperEpoch,
    *,
    epochs_root: Path,
    status: str,
    failed_reason: str | None = None,
    void_reason: str | None = None,
) -> PaperEpoch:
    epoch.epoch_status = status
    if status in {"CLOSED", "VOID", "FAILED_ACTIVATION"}:
        epoch.closed_at = _utc_now().isoformat().replace("+00:00", "Z")
    if failed_reason:
        epoch.failed_reason = failed_reason
    if void_reason:
        epoch.void_reason = void_reason
    _write_epoch(epoch, epochs_root)
    return epoch


def load_active_epoch(epochs_root: Path) -> PaperEpoch | None:
    path = epochs_root / "active.json"
    if not path.exists():
        return None
    return PaperEpoch.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _write_epoch(epoch: PaperEpoch, epochs_root: Path) -> None:
    epochs_root.mkdir(parents=True, exist_ok=True)
    path = epochs_root / f"{epoch.paper_epoch_id}.json"
    path.write_text(json.dumps(epoch.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
