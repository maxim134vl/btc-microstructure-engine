"""Immutable AES contract / version fingerprint for AUCTION_EPISODE_SHADOW."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import LOGIC_VERSION, SCHEMA_VERSION, SHADOW_NAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ShadowAuctionContract:
    shadow_name: str = SHADOW_NAME
    logic_version: str = LOGIC_VERSION
    schema_version: int = SCHEMA_VERSION
    observer_only: bool = True
    enforcement_enabled: bool = False
    created_at: str = ""
    logic_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_logic_fingerprint(
    *,
    shadow_name: str = SHADOW_NAME,
    logic_version: str = LOGIC_VERSION,
    schema_version: int = SCHEMA_VERSION,
    observer_only: bool = True,
    enforcement_enabled: bool = False,
) -> str:
    """Stable fingerprint of the frozen AES_V1 contract surface.

    AES_V1 must not change after live data accumulates without bumping
    logic_version / fingerprint.
    """
    payload = {
        "shadow_name": shadow_name,
        "logic_version": logic_version,
        "schema_version": int(schema_version),
        "observer_only": bool(observer_only),
        "enforcement_enabled": bool(enforcement_enabled),
        "aes_surface": [
            "storage_isolation",
            "mount_validation",
            "no_internal_fallback",
            "watermark_idempotency",
            "independent_health",
            "bounded_cache",
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_contract(
    *,
    created_at: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> ShadowAuctionContract:
    cfg = dict(config or {})
    shadow_name = str(cfg.get("shadow_name") or SHADOW_NAME)
    logic_version = str(cfg.get("logic_version") or LOGIC_VERSION)
    schema_version = int(cfg.get("schema_version") or SCHEMA_VERSION)
    observer_only = bool(cfg.get("observer_only", True))
    enforcement_enabled = bool(cfg.get("enforcement_enabled", False))
    if not observer_only:
        raise ValueError("AUCTION_EPISODE_SHADOW must remain observer_only=true in AES_V1")
    if enforcement_enabled:
        raise ValueError("AUCTION_EPISODE_SHADOW must keep enforcement_enabled=false in AES_V1")
    fp = compute_logic_fingerprint(
        shadow_name=shadow_name,
        logic_version=logic_version,
        schema_version=schema_version,
        observer_only=observer_only,
        enforcement_enabled=enforcement_enabled,
    )
    return ShadowAuctionContract(
        shadow_name=shadow_name,
        logic_version=logic_version,
        schema_version=schema_version,
        observer_only=observer_only,
        enforcement_enabled=enforcement_enabled,
        created_at=created_at or _utc_now(),
        logic_fingerprint=fp,
    )


def load_config(path: Path | None = None, *, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or Path(__file__).resolve().parents[4]
    cfg_path = Path(path) if path else root / "config" / "shadow_auction.json"
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid shadow_auction config: {cfg_path}")
    required = (
        "shadow_name",
        "logic_version",
        "schema_version",
        "observer_only",
        "enforcement_enabled",
        "data_root",
        "required_volume_root",
    )
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(f"shadow_auction.json missing keys: {missing}")
    if bool(raw.get("enforcement_enabled")):
        raise ValueError("enforcement_enabled must be false for AES_V1")
    if not bool(raw.get("observer_only", True)):
        raise ValueError("observer_only must be true for AES_V1")
    return raw


def write_manifest(path: Path, contract: ShadowAuctionContract) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(
        path.suffix + f".{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}.tmp"
    )
    payload = {
        **contract.to_dict(),
        "manifest_kind": "shadow_auction_contract_v1",
    }
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
