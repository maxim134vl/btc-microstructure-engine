"""
Redis state operations. All keys carry TTLs — the engine never leaks state.

Schema:
  alert:active:<fp>      JSON, TTL=cooldown+60s
  alert:cooldown:<fp>    "1",  TTL=cooldown
  alert:history:<YYYYMMDD>  ZSET   member=fp, score=ts; trimmed to last 1000
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis_async


def fingerprint(alert: dict[str, Any]) -> str:
    """Stable fingerprint from alertname + sorted labels. Accepts both
    Alertmanager-style {labels:{alertname,...}} and evaluator-style
    {alertname, labels:{...}}.
    """
    labels = alert.get("labels", {}) or {}
    alertname = alert.get("alertname") or labels.get("alertname")
    canonical = json.dumps(
        {"alertname": alertname, "labels": dict(sorted(labels.items()))},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


class AlertState:
    """Thin wrapper over redis-py async client. Errors are surfaced to caller."""

    def __init__(self, client: redis_async.Redis) -> None:
        self.r = client

    async def is_in_cooldown(self, fp: str) -> bool:
        return await self.r.exists(f"alert:cooldown:{fp}") > 0

    async def mark_active(self, fp: str, payload: dict[str, Any], cooldown_s: int) -> None:
        ttl = max(cooldown_s + 60, 120)
        # set both keys in a pipeline (atomic enough for our purposes)
        pipe = self.r.pipeline()
        pipe.set(f"alert:active:{fp}", json.dumps(payload, separators=(",", ":")), ex=ttl)
        pipe.set(f"alert:cooldown:{fp}", "1", ex=cooldown_s)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        pipe.zadd(f"alert:history:{day}", {fp: datetime.now(timezone.utc).timestamp()})
        pipe.expire(f"alert:history:{day}", 7 * 86400)
        # cap history to last 1000 per day
        pipe.zremrangebyrank(f"alert:history:{day}", 0, -1001)
        await pipe.execute()

    async def mark_resolved(self, fp: str) -> None:
        # drop the active flag immediately on resolve; cooldown lingers
        # so a flapping alert doesn't immediately re-fire
        await self.r.delete(f"alert:active:{fp}")

    async def list_active(self) -> list[dict[str, Any]]:
        keys: list[bytes] = []
        async for k in self.r.scan_iter(match="alert:active:*", count=200):
            keys.append(k)
        if not keys:
            return []
        values = await self.r.mget(keys)
        out: list[dict[str, Any]] = []
        for v in values:
            if v is None:
                continue
            try:
                out.append(json.loads(v))
            except json.JSONDecodeError:
                continue
        return out

    async def count_cooldowns(self) -> int:
        count = 0
        async for _ in self.r.scan_iter(match="alert:cooldown:*", count=200):
            count += 1
        return count

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        await self.r.publish(channel, json.dumps(payload, separators=(",", ":")))

    async def ping(self) -> bool:
        try:
            return await self.r.ping()
        except Exception:
            return False

    async def close(self) -> None:
        try:
            await self.r.close()
        except Exception:
            pass
