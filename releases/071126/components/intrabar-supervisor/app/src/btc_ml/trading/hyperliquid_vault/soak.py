"""Go/no-go soak checklist for promoting a testnet vault toward mainnet."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import HlVaultSoakConfig


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def evaluate_soak_gates(
    *,
    soak: HlVaultSoakConfig,
    started_at: str | None,
    now: datetime | None = None,
    paired_fills: int,
    liquidations: int,
    fill_rate: float,
    median_abs_basis_bps: float | None,
    kill_switch_tested: bool,
    public_testnet_enabled: bool,
) -> dict[str, Any]:
    now_dt = now or datetime.now(timezone.utc)
    start = _parse_ts(started_at)
    elapsed_days = (now_dt - start).total_seconds() / 86400.0 if start else 0.0
    checks = [
        {
            "id": "min_soak_days",
            "ok": elapsed_days >= float(soak.min_days),
            "actual": round(elapsed_days, 3),
            "threshold": soak.min_days,
        },
        {
            "id": "min_paired_fills",
            "ok": int(paired_fills) >= int(soak.min_paired_fills),
            "actual": int(paired_fills),
            "threshold": soak.min_paired_fills,
        },
        {
            "id": "zero_liquidations",
            "ok": int(liquidations) <= int(soak.max_liquidations),
            "actual": int(liquidations),
            "threshold": soak.max_liquidations,
        },
        {
            "id": "min_fill_rate",
            "ok": float(fill_rate) >= float(soak.min_fill_rate),
            "actual": float(fill_rate),
            "threshold": soak.min_fill_rate,
        },
        {
            "id": "median_abs_basis_bps",
            "ok": median_abs_basis_bps is not None and float(median_abs_basis_bps) <= float(soak.max_median_abs_basis_bps),
            "actual": median_abs_basis_bps,
            "threshold": soak.max_median_abs_basis_bps,
        },
        {
            "id": "kill_switch_tested",
            "ok": (not soak.require_kill_switch_tested) or bool(kill_switch_tested),
            "actual": bool(kill_switch_tested),
            "threshold": True,
        },
        {
            "id": "public_testnet_vault",
            "ok": bool(public_testnet_enabled),
            "actual": bool(public_testnet_enabled),
            "threshold": True,
        },
    ]
    passed = all(bool(c["ok"]) for c in checks)
    return {
        "passed": passed,
        "verdict": "GO" if passed else "NO_GO",
        "elapsed_days": elapsed_days,
        "checks": checks,
        "notes": [
            "Paper PnL will not equal vault PnL: different book, funding, and taker fees.",
            "Do not announce a mainnet vault until every gate is GO.",
        ],
    }
