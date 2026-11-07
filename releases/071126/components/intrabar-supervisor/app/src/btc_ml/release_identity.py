"""Identity of the paper release this tree builds.

The file under deploy/vps/release/ is copied into the runtime and ops-api
images. /health and the dashboard badge both read this version.
"""

from __future__ import annotations

import json
from pathlib import Path

RELEASE_VERSION = "2026.09.22"
RELEASE_CHANNEL = "release"
RELEASE_APP = "btc-ml-paper"


def _candidate_paths() -> list[Path]:
    repo = Path(__file__).resolve().parents[2]
    return [
        Path("/app/deploy/vps/release/current.json"),
        repo / "deploy" / "vps" / "release" / "current.json",
    ]


def load_release_identity() -> dict:
    for path in _candidate_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("version"):
            return payload
    return {
        "version": RELEASE_VERSION,
        "channel": RELEASE_CHANNEL,
        "app": RELEASE_APP,
    }
