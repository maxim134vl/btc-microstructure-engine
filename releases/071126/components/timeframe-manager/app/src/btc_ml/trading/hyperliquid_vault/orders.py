"""Pure Hyperliquid order payload builders and fill parsers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .sizing import bps_to_rate


def round_px_to_tick(price: float, *, tick: float = 1.0) -> float:
    step = float(tick)
    if step <= 0:
        return float(price)
    return round(float(price) / step) * step


def aggressive_limit_px(*, side: str, mid: float, ioc_slippage_bps: float, tick: float = 1.0) -> float:
    mid_f = float(mid)
    slip = bps_to_rate(ioc_slippage_bps)
    side_u = str(side).upper()
    if side_u == "LONG":
        raw = mid_f * (1.0 + slip)
    elif side_u == "SHORT":
        raw = mid_f * (1.0 - slip)
    else:
        raise ValueError(f"unsupported side={side!r}")
    return round_px_to_tick(raw, tick=tick)


def ioc_limit_order(*, is_buy: bool, size: float, limit_px: float, reduce_only: bool = False) -> dict[str, Any]:
    return {
        "is_buy": bool(is_buy),
        "sz": float(size),
        "limit_px": float(limit_px),
        "order_type": {"limit": {"tif": "Ioc"}},
        "reduce_only": bool(reduce_only),
    }


def trigger_tpsl_order(
    *,
    is_buy: bool,
    size: float,
    trigger_px: float,
    tpsl: str,
    reduce_only: bool = True,
) -> dict[str, Any]:
    kind = str(tpsl).lower()
    if kind not in {"tp", "sl"}:
        raise ValueError(f"tpsl must be tp|sl, got {tpsl!r}")
    return {
        "is_buy": bool(is_buy),
        "sz": float(size),
        "limit_px": float(trigger_px),
        "order_type": {
            "trigger": {
                # SDK float_to_wire() formats triggerPx with :.8f; a string raises
                # "Unknown format code 'f' for object of type 'str'" and leaves
                # the fill unprotected (no resting SL/TP).
                "triggerPx": float(trigger_px),
                "isMarket": True,
                "tpsl": kind,
            }
        },
        "reduce_only": bool(reduce_only),
    }


def _px_str(price: float) -> str:
    text = f"{float(price):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def protective_side(entry_side: str) -> str:
    return "SHORT" if str(entry_side).upper() == "LONG" else "LONG"


@dataclass(frozen=True)
class ParsedOrderResult:
    ok: bool
    filled: bool
    avg_px: float | None
    total_sz: float | None
    oid: int | None
    error: str | None
    raw: dict[str, Any]


def parse_order_result(payload: Any) -> ParsedOrderResult:
    if not isinstance(payload, dict):
        return ParsedOrderResult(False, False, None, None, None, "non_dict_response", {"raw": payload})
    if str(payload.get("status") or "") != "ok":
        return ParsedOrderResult(False, False, None, None, None, str(payload.get("status") or "not_ok"), payload)
    statuses = (((payload.get("response") or {}).get("data") or {}).get("statuses")) or []
    if not statuses:
        return ParsedOrderResult(False, False, None, None, None, "empty_statuses", payload)
    first = statuses[0] if isinstance(statuses[0], dict) else {}
    if "error" in first:
        return ParsedOrderResult(False, False, None, None, None, str(first.get("error")), payload)
    filled = first.get("filled") if isinstance(first.get("filled"), dict) else None
    resting = first.get("resting") if isinstance(first.get("resting"), dict) else None
    if filled:
        return ParsedOrderResult(
            True,
            True,
            float(filled.get("avgPx") or 0.0),
            float(filled.get("totalSz") or 0.0),
            int(filled["oid"]) if filled.get("oid") is not None else None,
            None,
            payload,
        )
    if resting:
        return ParsedOrderResult(
            True,
            False,
            None,
            None,
            int(resting["oid"]) if resting.get("oid") is not None else None,
            None,
            payload,
        )
    return ParsedOrderResult(False, False, None, None, None, "unrecognized_status", payload)
