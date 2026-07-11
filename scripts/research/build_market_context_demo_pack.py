#!/usr/bin/env python3
"""Build explainability + acceptance demo pack for the market-context shadow chain.

Read-only over restored shadow artifacts. Does not change model logic / pipeline /
visualizer / execution.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
COGNITION = ROOT / "data" / "cognition"
VISUAL_DATA = ROOT / "sandbox" / "market_state_context_visualizer" / "public" / "data"

AUCTION_PATH = COGNITION / "auction_episode_memory.parquet"
COGNITIVE_PATH = COGNITION / "cognitive_market_state_memory.parquet"
FINAL_PATH = COGNITION / "final_market_context_memory.parquet"
LIFECYCLE_MEMORY_PATH = COGNITION / "market_context_lifecycle_memory.parquet"
LIFECYCLE_EPISODES_PATH = COGNITION / "market_context_lifecycle_episodes.parquet"
SHADOW_STATUS_PATH = COGNITION / "market_context_shadow_chain_status.json"

OUTPUT_JSON = COGNITION / "market_context_demo_pack.json"
OUTPUT_MD = ROOT / "docs" / "MARKET_CONTEXT_DEMO_PACK_OUTPUT.md"

VISUAL_JSONS = [
    VISUAL_DATA / "lifecycle_candles.json",
    VISUAL_DATA / "lifecycle_context_episodes.json",
    VISUAL_DATA / "lifecycle_latest.json",
]

REQUIRED_LATEST_CONTEXT_FIELDS = [
    "timestamp",
    "close",
    "active_market_context",
    "lifecycle_state",
    "active_context_age_bars",
    "challenge_ratio",
    "action_allowed",
    "action_reason",
]

FORBIDDEN_TOKENS = ("FAILED_SHORT_REPRICE", "raw_chosen_context", "calibrated_context")


def _iso(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _clean(value: Any, default: str = "UNKNOWN") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "nat"}:
        return default
    return text


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes"}:
        return True
    if text in {"0", "false", "f", "no"}:
        return False
    return bool(value)


def _to_utc_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce").astype("datetime64[ns, UTC]")


def load_inputs() -> dict[str, Any]:
    missing = [
        path
        for path in [
            AUCTION_PATH,
            COGNITIVE_PATH,
            FINAL_PATH,
            LIFECYCLE_MEMORY_PATH,
            LIFECYCLE_EPISODES_PATH,
            SHADOW_STATUS_PATH,
        ]
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "missing required inputs:\n" + "\n".join(f"  - {p}" for p in missing)
        )

    auction = pd.read_parquet(AUCTION_PATH)
    cognitive = pd.read_parquet(COGNITIVE_PATH)
    final = pd.read_parquet(FINAL_PATH)
    life_mem = pd.read_parquet(LIFECYCLE_MEMORY_PATH)
    life_ep = pd.read_parquet(LIFECYCLE_EPISODES_PATH)
    status = json.loads(SHADOW_STATUS_PATH.read_text(encoding="utf-8"))

    for frame in (auction, cognitive, final, life_mem):
        if "timestamp" in frame.columns:
            frame["timestamp"] = _to_utc_series(frame["timestamp"])
    if "start_time" in life_ep.columns:
        life_ep["start_time"] = _to_utc_series(life_ep["start_time"])
    if "end_time" in life_ep.columns:
        life_ep["end_time"] = _to_utc_series(life_ep["end_time"])

    auction = auction.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    cognitive = cognitive.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    final = final.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    life_mem = life_mem.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    life_ep = life_ep.dropna(subset=["start_time", "end_time"]).sort_values("start_time").reset_index(drop=True)

    return {
        "auction": auction,
        "cognitive": cognitive,
        "final": final,
        "life_mem": life_mem,
        "life_ep": life_ep,
        "status": status,
    }


def lookup_asof(frame: pd.DataFrame, ts: pd.Timestamp) -> pd.Series | None:
    if frame is None or len(frame) == 0 or ts is None or pd.isna(ts):
        return None
    work = frame
    idx = work["timestamp"].searchsorted(ts, side="right") - 1
    if idx < 0:
        return None
    return work.iloc[int(idx)]


def build_explanation(
    *,
    context: str,
    dominant_state: str,
    challenged_bars: int,
    bars_count: int,
    start_cognitive: str,
    start_auction: str,
    end_raw_context: str,
    end_lifecycle: str,
    challenge_context: str | None,
    start_reason: str,
) -> str:
    ctx = _clean(context, "OBSERVE")
    cog = _clean(start_cognitive, "UNKNOWN")
    auction = _clean(start_auction, "UNKNOWN")
    bars = max(1, int(bars_count))
    challenged = int(challenged_bars)
    challenge_ratio = challenged / bars

    if ctx == "OBSERVE":
        base = (
            f"OBSERVE because cognitive state was {cog}, derived from auction episode {auction}. "
            "No confirmed directional context is active."
        )
    elif ctx == "LONG_CONTEXT":
        base = (
            f"LONG_CONTEXT because cognitive state was {cog}, derived from auction episode "
            f"{auction} showing buyer-side pressure. Activated via: {_clean(start_reason)}."
        )
    elif ctx == "SHORT_CONTEXT":
        base = (
            f"SHORT_CONTEXT because cognitive state was {cog}, derived from auction episode "
            f"{auction} showing seller pressure. Activated via: {_clean(start_reason)}."
        )
    else:
        base = f"{ctx} from cognitive state {cog} / auction episode {auction}."

    if _clean(dominant_state).upper() == "CHALLENGED" or challenge_ratio > 0.5:
        challenge = _clean(challenge_context or end_raw_context, "OBSERVE")
        base += (
            f" Episode is challenged because recent raw context is {challenge}, "
            "but no confirmed opposite context replaced it."
        )
    elif _clean(end_lifecycle).upper() == "INVALIDATED":
        base += " Episode ended because source context was invalidated."
    return base


def build_source_point(
    *,
    auction_row: pd.Series | None,
    cognitive_row: pd.Series | None,
    final_row: pd.Series | None,
    life_row: pd.Series | None,
    label: str,
) -> dict[str, Any]:
    return {
        "point": label,
        "timestamp": _iso(life_row["timestamp"]) if life_row is not None else None,
        "auction_episode": _clean(auction_row.get("auction_episode")) if auction_row is not None else "UNKNOWN",
        "episode_status": _clean(auction_row.get("episode_status")) if auction_row is not None else "UNKNOWN",
        "episode_reason": _clean(auction_row.get("episode_reason")) if auction_row is not None else "UNKNOWN",
        "cognitive_market_state": _clean(cognitive_row.get("cognitive_market_state"))
        if cognitive_row is not None
        else "UNKNOWN",
        "state_direction": _clean(cognitive_row.get("state_direction")) if cognitive_row is not None else "UNKNOWN",
        "state_status": _clean(cognitive_row.get("state_status")) if cognitive_row is not None else "UNKNOWN",
        "market_context": _clean(final_row.get("market_context")) if final_row is not None else "UNKNOWN",
        "context_status": _clean(final_row.get("context_status")) if final_row is not None else "UNKNOWN",
        "active_market_context": _clean(life_row.get("active_market_context"))
        if life_row is not None
        else "UNKNOWN",
        "lifecycle_state": _clean(life_row.get("lifecycle_state")) if life_row is not None else "UNKNOWN",
        "freshness": {
            "auction_source_freshness": _clean(auction_row.get("source_freshness"), default="unknown")
            if auction_row is not None
            else "unknown",
            "cognitive_source_freshness": _clean(cognitive_row.get("source_episode_freshness"), default="unknown")
            if cognitive_row is not None
            else "unknown",
            "final_source_freshness": _clean(final_row.get("source_state_freshness"), default="unknown")
            if final_row is not None
            else "unknown",
        },
    }


def build_latest_episodes(inputs: dict[str, Any], limit: int = 20) -> tuple[list[dict], list[dict]]:
    life_ep = inputs["life_ep"]
    auction = inputs["auction"]
    cognitive = inputs["cognitive"]
    final = inputs["final"]
    life_mem = inputs["life_mem"]

    tail = life_ep.tail(limit).copy()
    episodes: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    for _, ep in tail.iterrows():
        start_ts = ep["start_time"]
        end_ts = ep["end_time"]
        start_auction = lookup_asof(auction, start_ts)
        start_cognitive = lookup_asof(cognitive, start_ts)
        start_final = lookup_asof(final, start_ts)
        start_life = lookup_asof(life_mem, start_ts)
        end_auction = lookup_asof(auction, end_ts)
        end_cognitive = lookup_asof(cognitive, end_ts)
        end_final = lookup_asof(final, end_ts)
        end_life = lookup_asof(life_mem, end_ts)

        bars = _safe_int(ep.get("bars_count"), default=1)
        challenged = _safe_int(ep.get("challenged_bars_count"), default=0)
        explanation = build_explanation(
            context=_clean(ep.get("active_market_context"), "OBSERVE"),
            dominant_state=_clean(ep.get("dominant_lifecycle_state")),
            challenged_bars=challenged,
            bars_count=bars,
            start_cognitive=_clean(start_cognitive.get("cognitive_market_state"))
            if start_cognitive is not None
            else "UNKNOWN",
            start_auction=_clean(start_auction.get("auction_episode")) if start_auction is not None else "UNKNOWN",
            end_raw_context=_clean(end_final.get("market_context")) if end_final is not None else "UNKNOWN",
            end_lifecycle=_clean(end_life.get("lifecycle_state")) if end_life is not None else "UNKNOWN",
            challenge_context=_clean(end_life.get("challenge_context"), default="")
            if end_life is not None
            else None,
            start_reason=_clean(ep.get("start_reason")),
        )

        episodes.append(
            {
                "episode_id": _safe_int(ep.get("episode_id")),
                "active_market_context": _clean(ep.get("active_market_context"), "OBSERVE"),
                "start_time": _iso(start_ts),
                "end_time": _iso(end_ts),
                "bars_count": bars,
                "duration_minutes": _safe_float(ep.get("duration_minutes"), default=0.0),
                "challenged_bars_count": challenged,
                "dominant_lifecycle_state": _clean(ep.get("dominant_lifecycle_state")),
                "start_reason": _clean(ep.get("start_reason")),
                "end_reason": _clean(ep.get("end_reason")),
                "explanation": explanation,
            }
        )
        traces.append(
            {
                "episode_id": _safe_int(ep.get("episode_id")),
                "active_market_context": _clean(ep.get("active_market_context"), "OBSERVE"),
                "start": build_source_point(
                    auction_row=start_auction,
                    cognitive_row=start_cognitive,
                    final_row=start_final,
                    life_row=start_life,
                    label="start",
                ),
                "end": build_source_point(
                    auction_row=end_auction,
                    cognitive_row=end_cognitive,
                    final_row=end_final,
                    life_row=end_life,
                    label="end",
                ),
                "summary": {
                    "auction_episode": _clean(start_auction.get("auction_episode"))
                    if start_auction is not None
                    else "UNKNOWN",
                    "cognitive_market_state": _clean(start_cognitive.get("cognitive_market_state"))
                    if start_cognitive is not None
                    else "UNKNOWN",
                    "market_context": _clean(start_final.get("market_context"))
                    if start_final is not None
                    else "UNKNOWN",
                    "lifecycle_state": _clean(start_life.get("lifecycle_state"))
                    if start_life is not None
                    else "UNKNOWN",
                },
            }
        )

    return episodes, traces


def build_latest_context(inputs: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    life_mem = inputs["life_mem"]
    life_ep = inputs["life_ep"]
    latest = life_mem.iloc[-1]
    challenge_ratio = None
    if len(life_ep):
        last_ep = life_ep.iloc[-1]
        bars = max(1, _safe_int(last_ep.get("bars_count"), default=1))
        challenged = _safe_int(last_ep.get("challenged_bars_count"), default=0)
        challenge_ratio = round(challenged / bars, 4)
    status_latest = status.get("latest_context") or {}
    if challenge_ratio is None:
        challenge_ratio = status_latest.get("challenge_ratio")
    result = {
        "timestamp": _iso(latest.get("timestamp")),
        "close": _safe_float(latest.get("close")),
        "active_market_context": _clean(latest.get("active_market_context"), "OBSERVE"),
        "lifecycle_state": _clean(latest.get("lifecycle_state")),
        "active_context_age_bars": _safe_int(latest.get("active_context_age_bars")),
        "challenge_ratio": challenge_ratio,
        "action_allowed": _safe_bool(latest.get("action_allowed"), default=False),
        "action_reason": _clean(latest.get("action_reason"), default="shadow market context only; execution disabled"),
        "raw_market_context": _clean(latest.get("raw_market_context"), "OBSERVE"),
        "challenge_context": _clean(latest.get("challenge_context"), default="") or None,
        "transition_reason": _clean(latest.get("transition_reason")),
        "previous_active_market_context": _clean(latest.get("previous_active_market_context"), default="") or None,
        "invalidation_type": _clean(latest.get("invalidation_type"), default="NONE"),
        "invalidation_reason": _clean(latest.get("invalidation_reason"), default="") or None,
        "invalidated_at": _iso(latest.get("invalidated_at")),
        "invalidated_by_auction_episode": _clean(latest.get("invalidated_by_auction_episode"), default="") or None,
        "invalidated_by_cognitive_state": _clean(latest.get("invalidated_by_cognitive_state"), default="") or None,
        "invalidated_by_market_context": _clean(latest.get("invalidated_by_market_context"), default="") or None,
    }
    if result["active_market_context"] == "OBSERVE" or result["lifecycle_state"] in {
        "NO_ACTIVE_CONTEXT",
        "INVALIDATED",
    }:
        result["active_context_age_bars"] = 0
    return result


def scan_forbidden(payload: Any) -> list[str]:
    blob = json.dumps(payload, ensure_ascii=False, default=str)
    return [token for token in FORBIDDEN_TOKENS if token in blob]


def scan_parquet_forbidden(path: Path) -> list[str]:
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    chunks = [" ".join(map(str, frame.columns))]
    for col in frame.columns:
        dtype = str(frame[col].dtype)
        if dtype.startswith(("int", "float", "bool", "datetime", "timedelta")):
            continue
        chunks.append(" ".join(map(str, frame[col].head(3000).tolist())))
    blob = " ".join(chunks)
    return [token for token in FORBIDDEN_TOKENS if token in blob]


def build_acceptance_checks(inputs: dict[str, Any], status: dict[str, Any], latest: dict[str, Any]) -> dict[str, bool]:
    life_ep = inputs["life_ep"]
    raw_count = int(status.get("raw_episodes_count") or 0)
    life_count = int(len(life_ep))
    if raw_count <= 0:
        raw_count = int(status.get("raw_episodes_count") or 0)

    forbidden_hits: list[str] = []
    for path in [
        AUCTION_PATH,
        COGNITIVE_PATH,
        FINAL_PATH,
        LIFECYCLE_MEMORY_PATH,
        LIFECYCLE_EPISODES_PATH,
    ]:
        forbidden_hits.extend(scan_parquet_forbidden(path))

    visual_hits: list[str] = []
    visual_present = all(path.exists() for path in VISUAL_JSONS)
    for path in VISUAL_JSONS:
        if path.exists():
            visual_hits.extend(scan_forbidden(json.loads(path.read_text(encoding="utf-8"))))

    action_false = True
    for frame in (inputs["final"], inputs["life_mem"], inputs["life_ep"]):
        if "action_allowed" in frame.columns and bool(frame["action_allowed"].astype(bool).any()):
            action_false = False
        if "action_allowed_any" in frame.columns and bool(frame["action_allowed_any"].astype(bool).any()):
            action_false = False
    if latest.get("action_allowed") is True:
        action_false = False

    latest_open = False
    if len(life_ep):
        end_reason = _clean(life_ep.iloc[-1].get("end_reason")).lower()
        latest_open = "latest open" in end_reason

    return {
        "chain_status_is_pass": str(status.get("status", "")).upper() == "PASS",
        "lifecycle_episodes_less_than_raw": bool(raw_count > 0 and life_count < raw_count),
        "no_failed_short_reprice": "FAILED_SHORT_REPRICE" not in forbidden_hits
        and "FAILED_SHORT_REPRICE" not in visual_hits,
        "no_raw_chosen_context_in_visual": "raw_chosen_context" not in visual_hits,
        "no_calibrated_context_in_visual": "calibrated_context" not in visual_hits,
        "action_allowed_false": action_false,
        "latest_context_available": bool(latest.get("active_market_context")) and bool(latest.get("timestamp")),
        "latest_episode_open": latest_open,
        "visual_source_is_lifecycle": visual_present,
    }


def build_chain_health(
    inputs: dict[str, Any],
    status: dict[str, Any],
    checks: dict[str, bool],
) -> dict[str, Any]:
    raw_count = int(status.get("raw_episodes_count") or 0)
    life_count = int(len(inputs["life_ep"]))
    reduction = None
    if raw_count > 0:
        reduction = round(1.0 - (life_count / raw_count), 4)
    forbidden = not (
        checks.get("no_failed_short_reprice", False)
        and checks.get("no_raw_chosen_context_in_visual", False)
        and checks.get("no_calibrated_context_in_visual", False)
    )
    return {
        "shadow_chain_status": status.get("status"),
        "memory_rows": int(len(inputs["life_mem"])),
        "lifecycle_episodes_count": life_count,
        "raw_episodes_count": raw_count,
        "reduction_ratio": reduction,
        "forbidden_labels_found": forbidden,
        "execution_disabled": True,
    }


def pack_status(checks: dict[str, bool]) -> str:
    return "PASS" if all(bool(v) for v in checks.values()) else "FAIL"


def build_demo_pack(inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    data = inputs if inputs is not None else load_inputs()
    status = data["status"]
    latest = build_latest_context(data, status)
    episodes, traces = build_latest_episodes(data, limit=20)
    checks = build_acceptance_checks(data, status, latest)
    health = build_chain_health(data, status, checks)
    overall = pack_status(checks)

    # Human explanation for latest context
    last_ep = episodes[-1] if episodes else None
    latest_explanation = last_ep["explanation"] if last_ep else "No lifecycle episodes available."
    if latest.get("active_market_context") == "OBSERVE":
        prev_ctx = latest.get("previous_active_market_context")
        inv_type = _clean(latest.get("invalidation_type"), default="NONE")
        inv_reason = latest.get("invalidation_reason")
        if prev_ctx and inv_type != "NONE":
            latest_explanation = (
                f"No active directional context. "
                f"Previous active context {prev_ctx} was cancelled via {inv_type}. "
                f"{inv_reason or ''} "
                "This is not a new opposite LONG/SHORT context. "
                f"action_allowed=False because {_clean(latest.get('action_reason'))}."
            ).replace("  ", " ").strip()
        else:
            latest_explanation = (
                "No active directional context (OBSERVE / NO_ACTIVE_CONTEXT). "
                f"action_allowed=False because {_clean(latest.get('action_reason'))}."
            )
    elif latest.get("lifecycle_state") == "INVALIDATED" or _clean(
        latest.get("invalidation_type"), default="NONE"
    ) in {"AUCTION_NEUTRALIZATION", "OPPOSITE_CONTEXT_REPLACEMENT", "THESIS_REJECTION"}:
        prev_ctx = latest.get("previous_active_market_context") or "UNKNOWN"
        inv_reason = latest.get("invalidation_reason") or "auction/cognitive neutralization"
        inv_type = latest.get("invalidation_type") or "NONE"
        latest_explanation = (
            f"Previous active context {prev_ctx} was closed by {inv_type}. "
            f"{inv_reason} "
            "This is not a new opposite LONG/SHORT context — active is OBSERVE until a confirmed "
            "directional context appears. "
            f"action_allowed=False because {_clean(latest.get('action_reason'))}."
        )
    else:
        if latest.get("lifecycle_state") == "CHALLENGED":
            latest_explanation += (
                f" Current active context age is {latest.get('active_context_age_bars')} bars; "
                f"challenge_ratio={latest.get('challenge_ratio')}."
            )
        latest_explanation += (
            f" action_allowed=False because {_clean(latest.get('action_reason'))}."
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": overall,
        "latest_context": latest,
        "latest_context_explanation": latest_explanation,
        "chain_health": health,
        "latest_episodes": episodes,
        "source_trace": traces,
        "acceptance_checks": checks,
        "shadow_only": True,
    }


def render_markdown(pack: dict[str, Any]) -> str:
    latest = pack.get("latest_context") or {}
    health = pack.get("chain_health") or {}
    checks = pack.get("acceptance_checks") or {}
    episodes = pack.get("latest_episodes") or []
    traces = pack.get("source_trace") or []

    lines: list[str] = []
    lines.append("# Market Context Demo Pack")
    lines.append("")
    lines.append("## 1. Current status")
    lines.append("")
    lines.append(f"- latest active context: `{latest.get('active_market_context')}`")
    lines.append(f"- lifecycle state: `{latest.get('lifecycle_state')}`")
    if latest.get("active_market_context") == "OBSERVE":
        lines.append("- active directional context age: `0` (no active directional context)")
        if latest.get("previous_active_market_context"):
            lines.append(
                f"- previous active context: `{latest.get('previous_active_market_context')}` "
                f"({latest.get('invalidation_type')})"
            )
    else:
        lines.append(f"- age: `{latest.get('active_context_age_bars')}` bars")
    lines.append(f"- action allowed: `{latest.get('action_allowed')}`")
    lines.append(f"- chain status: `{health.get('shadow_chain_status')}`")
    lines.append(f"- demo pack status: `{pack.get('status')}`")
    lines.append("")
    lines.append("## 2. What the graph shows")
    lines.append("")
    lines.append("- green fill = active `LONG_CONTEXT`")
    lines.append("- red fill = active `SHORT_CONTEXT`")
    lines.append("- faded / hatched fill = `CHALLENGED` active context")
    lines.append("- no fill = `OBSERVE`")
    lines.append("- this is **not** a trade signal; execution remains disabled")
    lines.append("")
    lines.append("## 3. Latest context explanation")
    lines.append("")
    lines.append(f"- active_market_context: `{latest.get('active_market_context')}`")
    lines.append(f"- lifecycle_state: `{latest.get('lifecycle_state')}`")
    lines.append(f"- challenge_ratio: `{latest.get('challenge_ratio')}`")
    lines.append(f"- action_allowed: `{latest.get('action_allowed')}`")
    if latest.get("lifecycle_state") == "INVALIDATED":
        lines.append(f"- previous_active_market_context: `{latest.get('previous_active_market_context')}`")
        lines.append(f"- invalidation_type: `{latest.get('invalidation_type')}`")
        lines.append(f"- invalidation_reason: `{latest.get('invalidation_reason')}`")
    lines.append("")
    lines.append(pack.get("latest_context_explanation") or "")
    lines.append("")
    lines.append("## 4. Last 20 context episodes")
    lines.append("")
    lines.append("| episode_id | context | start | end | bars | challenged | explanation |")
    lines.append("|---|---|---|---|---|---|---|")
    for ep in episodes:
        expl = str(ep.get("explanation") or "").replace("|", "/")
        lines.append(
            f"| {ep.get('episode_id')} | {ep.get('active_market_context')} | "
            f"{ep.get('start_time')} | {ep.get('end_time')} | {ep.get('bars_count')} | "
            f"{ep.get('challenged_bars_count')} | {expl} |"
        )
    lines.append("")
    lines.append("## 5. Source trace")
    lines.append("")
    lines.append("| episode_id | auction_episode | cognitive_market_state | market_context | lifecycle_state |")
    lines.append("|---|---|---|---|---|")
    for tr in traces:
        summary = tr.get("summary") or {}
        lines.append(
            f"| {tr.get('episode_id')} | {summary.get('auction_episode')} | "
            f"{summary.get('cognitive_market_state')} | {summary.get('market_context')} | "
            f"{summary.get('lifecycle_state')} |"
        )
    lines.append("")
    lines.append("## 6. Acceptance checks")
    lines.append("")
    lines.append("| check | result |")
    lines.append("|---|---|")
    for key, value in checks.items():
        lines.append(f"| `{key}` | `{'PASS' if value else 'FAIL'}` |")
    lines.append("")
    lines.append(f"Overall: **{pack.get('status')}**")
    lines.append("")
    lines.append("## Chain health")
    lines.append("")
    lines.append(f"- memory rows: `{health.get('memory_rows')}`")
    lines.append(f"- raw episodes: `{health.get('raw_episodes_count')}`")
    lines.append(f"- lifecycle episodes: `{health.get('lifecycle_episodes_count')}`")
    lines.append(f"- reduction ratio: `{health.get('reduction_ratio')}`")
    lines.append(f"- forbidden labels found: `{health.get('forbidden_labels_found')}`")
    lines.append(f"- execution disabled: `{health.get('execution_disabled')}`")
    lines.append("")
    return "\n".join(lines)


def write_outputs(pack: dict[str, Any]) -> tuple[Path, Path]:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    tmp_json = OUTPUT_JSON.with_suffix(OUTPUT_JSON.suffix + ".tmp")
    tmp_json.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_json.replace(OUTPUT_JSON)

    md = render_markdown(pack)
    tmp_md = OUTPUT_MD.with_suffix(OUTPUT_MD.suffix + ".tmp")
    tmp_md.write_text(md, encoding="utf-8")
    tmp_md.replace(OUTPUT_MD)
    return OUTPUT_JSON, OUTPUT_MD


def main() -> int:
    try:
        pack = build_demo_pack()
        json_path, md_path = write_outputs(pack)
    except Exception as exc:
        print(f"demo pack status: FAIL")
        print(f"error: {exc}")
        return 1

    latest = pack.get("latest_context") or {}
    print(f"demo pack status: {pack.get('status')}")
    print(f"latest active context: {latest.get('active_market_context')}")
    print(f"latest lifecycle state: {latest.get('lifecycle_state')}")
    print(f"episodes included: {len(pack.get('latest_episodes') or [])}")
    print(f"output json path: {json_path}")
    print(f"output markdown path: {md_path}")
    return 0 if pack.get("status") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
