"""
Per-alert cooldown overrides. Default is `Config.cooldown_for(severity)`.

The map below lets us override per alertname when the default is wrong. Add
sparingly — most alerts should use the severity default.
"""

from __future__ import annotations

# alertname -> cooldown seconds
COOLDOWN_OVERRIDES: dict[str, int] = {
    # Critical disk: re-fire every minute until acted upon
    "DiskCritical": 60,
    # Container restart loop: don't spam — once every 15 min
    "ContainerRestartLoop": 900,
}


def cooldown_seconds(alertname: str, severity: str, default: int) -> int:
    if alertname in COOLDOWN_OVERRIDES:
        return COOLDOWN_OVERRIDES[alertname]
    return default
