#!/usr/bin/env python3
"""Cognition readiness: health JSON with recent market timestamps."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("BTC_ML_REPO_ROOT", "/app"))
PATH = REPO / "data" / "runtime" / "intrabar_cognition_health.json"
MAX_AGE_S = float(os.environ.get("VPS_COGNITION_MAX_AGE_S", os.environ.get("CTO_COGNITION_MAX_AGE_S", "120")))


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def main() -> int:
    if not PATH.is_file():
        print("STARTING: missing cognition health")
        return 1
    raw = json.loads(PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    last = _parse(raw.get("last_agg") or raw.get("last_book") or raw.get("updated_at"))
    if last is None:
        print("STARTING: no market timestamps yet")
        return 1
    age = (now - last).total_seconds()
    if age > MAX_AGE_S:
        print(f"UNHEALTHY: last market event age={age:.1f}s")
        return 1
    print(f"HEALTHY: age={age:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
