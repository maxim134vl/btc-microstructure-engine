"""AUCTION_EPISODE_SHADOW — observer-only research layer (AES0–AES6).

Independent of canonical cognition, LIVE1A/LIVE1B, paper trading, and other
Shadows. Heavy state must live only under the configured external SSD root.
AES2: four independent TF auction episode engines.
AES3: cross-TF hierarchy interpretation (does not mutate AES2).
AES4: canonical checkpoint linker (historical as-of; no evaluation).
AES5: checkpoint verdicts, case outcome attribution, post-mortem (no execution).
AES6: deterministic replay, integrity audit, resource health, runtime control.
"""

from __future__ import annotations

WRITE_BOUNDARY_VIOLATION = "SHADOW_AUCTION_WRITE_BOUNDARY_VIOLATION"
STORAGE_UNAVAILABLE = "SHADOW_AUCTION_STORAGE_UNAVAILABLE"
STORAGE_NOT_MOUNTED = "SHADOW_AUCTION_STORAGE_NOT_MOUNTED"
STORAGE_NOT_WRITABLE = "SHADOW_AUCTION_STORAGE_NOT_WRITABLE"
STORAGE_INSUFFICIENT_SPACE = "SHADOW_AUCTION_STORAGE_INSUFFICIENT_SPACE"
SHADOW_DEGRADED = "SHADOW_AUCTION_DEGRADED"
SHADOW_REFUSED = "SHADOW_AUCTION_REFUSED"

SHADOW_NAME = "AUCTION_EPISODE_SHADOW"
LOGIC_VERSION = "AES_V1"
SCHEMA_VERSION = 1

__all__ = [
    "WRITE_BOUNDARY_VIOLATION",
    "STORAGE_UNAVAILABLE",
    "STORAGE_NOT_MOUNTED",
    "STORAGE_NOT_WRITABLE",
    "STORAGE_INSUFFICIENT_SPACE",
    "SHADOW_DEGRADED",
    "SHADOW_REFUSED",
    "SHADOW_NAME",
    "LOGIC_VERSION",
    "SCHEMA_VERSION",
]
