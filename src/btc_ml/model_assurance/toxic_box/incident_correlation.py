"""Cross-branch Toxic Box incident correlation (MODEL-5).

OBSERVATIONAL / NON-BLOCKING — does not alter LIVE system health or Toxic Box writers.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_ml.model_assurance.registry import read_active_runtime
from btc_ml.model_assurance.toxic_box.common import (
    atomic_write_json,
    canonical_json,
    load_json,
    parse_ts,
    read_jsonl,
    sha256_text,
    utc_now_iso,
)


SEVERITY_RANK = {"WATCH": 1, "WARNING": 2, "CRITICAL": 3}

# Map external-source required_for layers → dependent toxic branches.
LAYER_BRANCHES: dict[str, set[str]] = {
    "LIVE1A_CONTEXT": {"CONTEXT"},
    "CONTEXT_EVENT_PRICE": {"CONTEXT"},
    "TP_SL_MONITORING": {"CONTEXT", "TRADE"},
    "LIVE1B_EXECUTION": {"TRADE"},
    "COMPLETED_BAR_STRUCTURAL_BACKGROUND": {"CONTEXT"},
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "toxic_box"
    incidents = base / "incidents"
    return {
        "external_events": base / "external_data" / "events" / "external_data_events.jsonl",
        "context_events": base / "contexts" / "events" / "context_toxic_events.jsonl",
        "trade_events": base / "trades" / "events" / "trade_toxic_events.jsonl",
        "external_config": root / "config" / "model_assurance_external_sources.json",
        "incidents_events": incidents / "events" / "incidents.jsonl",
        "incident_links": incidents / "links" / "incident_links.jsonl",
        "current_incidents": incidents / "snapshots" / "current_incidents.json",
        "latest_summary": incidents / "snapshots" / "latest_summary.json",
        "checkpoint": incidents / "runtime" / "checkpoint.json",
        "health": incidents / "runtime" / "health.json",
    }


def load_external_source_registry(config_path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return {str(s["source_id"]): s for s in (raw.get("sources") or []) if s.get("source_id")}


def incident_id_for(*, registry_record_id: str, paper_epoch_id: str, root_toxic_event_id: str) -> str:
    return "INC5_" + sha256_text(
        canonical_json(
            {
                "registry_record_id": registry_record_id,
                "paper_epoch_id": paper_epoch_id,
                "root_toxic_event_id": root_toxic_event_id,
            }
        )
    )[:32]


def _event_ts(event: dict[str, Any]) -> datetime | None:
    return parse_ts(
        event.get("subject_event_at")
        or event.get("event_time")
        or event.get("detected_at")
        or event.get("resolved_at")
    )


def _iso(stamp: datetime | None) -> str | None:
    if stamp is None:
        return None
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _max_severity(events: list[dict[str, Any]]) -> str:
    best = "WATCH"
    best_r = 0
    for e in events:
        sev = str(e.get("severity") or "WATCH").upper()
        r = SEVERITY_RANK.get(sev, 0)
        if r > best_r:
            best_r = r
            best = sev
    return best


def _branches_for_source(source: dict[str, Any] | None) -> set[str]:
    if not source:
        return set()
    out: set[str] = set()
    for layer in source.get("required_for") or []:
        out |= LAYER_BRANCHES.get(str(layer), set())
    return out


def _same_active(event: dict[str, Any], active: dict[str, Any]) -> bool:
    if str(event.get("registry_record_id") or "") != str(active.get("registry_record_id") or ""):
        return False
    if str(event.get("paper_epoch_id") or "") != str(active.get("paper_epoch_id") or ""):
        return False
    if event.get("model_version") and active.get("model_version"):
        if str(event.get("model_version")) != str(active.get("model_version")):
            return False
    return True


def load_new_toxic_events(
    *,
    paths_map: dict[str, Path],
    active: dict[str, Any],
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load toxic events for the active model/epoch.

    Checkpoint is recorded for observability; correlation rebuilds idempotently
    from full active-epoch files (append-only writers remain untouched).
    """
    _ = checkpoint  # retained for API / future incremental reads
    external = [
        e
        for e in read_jsonl(paths_map["external_events"])
        if str(e.get("branch") or "") == "EXTERNAL_DATA" and _same_active(e, active)
    ]
    context = [
        e
        for e in read_jsonl(paths_map["context_events"])
        if str(e.get("branch") or "") == "CONTEXT" and _same_active(e, active)
    ]
    trade = [
        e
        for e in read_jsonl(paths_map["trade_events"])
        if str(e.get("branch") or "") == "TRADE" and _same_active(e, active)
    ]
    return {"EXTERNAL_DATA": external, "CONTEXT": context, "TRADE": trade}


def _exact_keys(event: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("context_event_id", "lifecycle_episode_id", "prediction_id", "outcome_id"):
        val = event.get(field)
        if val:
            keys.add(f"{field}:{val}")
    return keys


def _context_trade_exact(ctx: dict[str, Any], trd: dict[str, Any]) -> bool:
    if str(ctx.get("registry_record_id") or "") != str(trd.get("registry_record_id") or ""):
        return False
    if str(ctx.get("paper_epoch_id") or "") != str(trd.get("paper_epoch_id") or ""):
        return False
    if str(ctx.get("timeframe") or "").upper() != str(trd.get("timeframe") or "").upper():
        return False
    if not str(ctx.get("timeframe") or "").strip():
        return False
    return bool(_exact_keys(ctx) & _exact_keys(trd))


def _build_data_intervals(external_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse OPEN→RESOLVED pairs into intervals keyed by source|subtype."""
    open_map: dict[str, dict[str, Any]] = {}
    intervals: list[dict[str, Any]] = []
    ordered = sorted(external_events, key=lambda e: str(e.get("detected_at") or e.get("event_time") or ""))
    for row in ordered:
        key = f"{row.get('source_id')}|{row.get('subtype')}"
        status = str(row.get("status") or "").upper()
        if status == "OPEN":
            open_map[key] = row
        elif status == "RESOLVED":
            opened = open_map.pop(key, None)
            start = parse_ts((opened or row).get("detected_at") or (opened or row).get("event_time"))
            end = parse_ts(row.get("resolved_at") or row.get("event_time") or row.get("detected_at"))
            intervals.append(
                {
                    "key": key,
                    "open_event": opened or row,
                    "resolve_event": row,
                    "source_id": row.get("source_id"),
                    "subtype": row.get("subtype"),
                    "start": start,
                    "end": end,
                    "is_open": False,
                    "root_toxic_event_id": (opened or row).get("toxic_event_id"),
                    "events": [e for e in (opened, row) if e],
                }
            )
    for key, opened in open_map.items():
        start = parse_ts(opened.get("detected_at") or opened.get("event_time"))
        intervals.append(
            {
                "key": key,
                "open_event": opened,
                "resolve_event": None,
                "source_id": opened.get("source_id"),
                "subtype": opened.get("subtype"),
                "start": start,
                "end": None,
                "is_open": True,
                "root_toxic_event_id": opened.get("toxic_event_id"),
                "events": [opened],
            }
        )
    return intervals


def _in_interval(ts: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if ts is None or start is None:
        return False
    if ts < start:
        return False
    if end is not None and ts > end:
        return False
    return True


def _trade_economic_harm(event: dict[str, Any]) -> float:
    """Confirmed realized harm only; never invent theoretical loss."""
    candidates: list[Any] = []
    if event.get("economic_harm_usd") is not None:
        candidates.append(event.get("economic_harm_usd"))
    if event.get("net_pnl_usd") is not None:
        candidates.append(event.get("net_pnl_usd"))
    obs = event.get("observed_value")
    if isinstance(obs, dict):
        for k in ("economic_harm_usd", "net_pnl_usd", "net"):
            if obs.get(k) is not None:
                candidates.append(obs.get(k))
    evid = event.get("evidence")
    if isinstance(evid, dict) and evid.get("economic_harm_usd") is not None:
        candidates.append(evid.get("economic_harm_usd"))
    for raw in candidates:
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val < 0:
            return abs(val)
        # explicit positive harm magnitude
        if event.get("economic_harm_usd") is not None and val > 0 and raw is event.get("economic_harm_usd"):
            return val
        if isinstance(evid, dict) and raw is evid.get("economic_harm_usd") and val > 0:
            return val
    return 0.0


def correlate_events(
    *,
    events_by_branch: dict[str, list[dict[str, Any]]],
    sources: dict[str, dict[str, Any]],
    active: dict[str, Any],
) -> dict[str, Any]:
    """Correlate toxic events into incidents + links."""
    external = [e for e in list(events_by_branch.get("EXTERNAL_DATA") or []) if _same_active(e, active)]
    contexts = [e for e in list(events_by_branch.get("CONTEXT") or []) if _same_active(e, active)]
    trades = [e for e in list(events_by_branch.get("TRADE") or []) if _same_active(e, active)]

    intervals = _build_data_intervals(external)
    links: list[dict[str, Any]] = []

    # Context ↔ Trade EXACT
    trade_assigned: set[str] = set()
    ctx_trade_groups: list[dict[str, Any]] = []
    # Prefer earlier context events as group anchors
    contexts_sorted = sorted(contexts, key=lambda e: str(e.get("detected_at") or e.get("subject_event_at") or ""))
    trades_sorted = sorted(trades, key=lambda e: str(e.get("detected_at") or e.get("subject_event_at") or ""))

    used_ctx: set[str] = set()
    for ctx in contexts_sorted:
        ctx_id = str(ctx.get("toxic_event_id") or "")
        if not ctx_id or ctx_id in used_ctx:
            continue
        group_ctx = [ctx]
        group_trd: list[dict[str, Any]] = []
        used_ctx.add(ctx_id)
        # Merge other contexts sharing exact keys + timeframe/epoch
        for other in contexts_sorted:
            oid = str(other.get("toxic_event_id") or "")
            if not oid or oid in used_ctx:
                continue
            if _context_trade_exact(ctx, other) or (
                str(ctx.get("registry_record_id")) == str(other.get("registry_record_id"))
                and str(ctx.get("paper_epoch_id")) == str(other.get("paper_epoch_id"))
                and str(ctx.get("timeframe") or "").upper() == str(other.get("timeframe") or "").upper()
                and bool(_exact_keys(ctx) & _exact_keys(other))
            ):
                group_ctx.append(other)
                used_ctx.add(oid)
        for trd in trades_sorted:
            tid = str(trd.get("toxic_event_id") or "")
            trade_key = str(trd.get("trade_id") or tid)
            if not tid or trade_key in trade_assigned:
                continue
            if any(_context_trade_exact(c, trd) for c in group_ctx):
                group_trd.append(trd)
                trade_assigned.add(trade_key)
                for c in group_ctx:
                    links.append(
                        {
                            "link_id": sha256_text(
                                canonical_json(
                                    {
                                        "a": c.get("toxic_event_id"),
                                        "b": tid,
                                        "method": "EXACT",
                                    }
                                )
                            )[:24],
                            "from_toxic_event_id": c.get("toxic_event_id"),
                            "to_toxic_event_id": tid,
                            "linkage_method": "EXACT",
                            "root_cause_confidence": "CONFIRMED",
                            "registry_record_id": active.get("registry_record_id"),
                            "paper_epoch_id": active.get("paper_epoch_id"),
                        }
                    )
        if group_trd or len(group_ctx) >= 1:
            ctx_trade_groups.append({"contexts": group_ctx, "trades": group_trd, "data": []})

    # Standalone trades (no exact context)
    for trd in trades_sorted:
        tid = str(trd.get("toxic_event_id") or "")
        trade_key = str(trd.get("trade_id") or tid)
        if trade_key in trade_assigned:
            continue
        ctx_trade_groups.append({"contexts": [], "trades": [trd], "data": []})
        trade_assigned.add(trade_key)

    # External data DEPENDENCY_WINDOW → attach to matching groups or standalone
    used_data_roots: set[str] = set()
    for interval in intervals:
        source = sources.get(str(interval.get("source_id") or ""))
        allowed_branches = _branches_for_source(source)
        if not allowed_branches:
            # No dependency mapping → never declare data as root cause
            continue
        open_event = interval["open_event"]
        data_tid = str(interval.get("root_toxic_event_id") or open_event.get("toxic_event_id") or "")
        matched_any = False
        for group in ctx_trade_groups:
            members = list(group["contexts"]) + list(group["trades"])
            hit_members: list[dict[str, Any]] = []
            for m in members:
                branch = str(m.get("branch") or "")
                if branch not in allowed_branches:
                    continue
                if not _same_active(m, active):
                    continue
                if not _same_active(open_event, active):
                    continue
                if not _in_interval(_event_ts(m), interval.get("start"), interval.get("end")):
                    continue
                hit_members.append(m)
            if hit_members:
                matched_any = True
                if open_event not in group["data"]:
                    group["data"].append(open_event)
                    if interval.get("resolve_event") is not None:
                        group["data"].append(interval["resolve_event"])
                for m in hit_members:
                    links.append(
                        {
                            "link_id": sha256_text(
                                canonical_json(
                                    {
                                        "a": data_tid,
                                        "b": m.get("toxic_event_id"),
                                        "method": "DEPENDENCY_WINDOW",
                                    }
                                )
                            )[:24],
                            "from_toxic_event_id": data_tid,
                            "to_toxic_event_id": m.get("toxic_event_id"),
                            "linkage_method": "DEPENDENCY_WINDOW",
                            "root_cause_confidence": "PROVISIONAL",
                            "source_id": interval.get("source_id"),
                            "registry_record_id": active.get("registry_record_id"),
                            "paper_epoch_id": active.get("paper_epoch_id"),
                        }
                    )
        if matched_any:
            used_data_roots.add(data_tid)
        # else: leave as uncorrelated external — do not invent data-only incidents

    incidents: list[dict[str, Any]] = []
    for group in ctx_trade_groups:
        # Incidents require at least one CONTEXT or TRADE observation
        if not group["contexts"] and not group["trades"]:
            continue
        incidents.append(
            build_incident(
                contexts=group["contexts"],
                trades=group["trades"],
                data_events=group["data"],
                links=links,
                active=active,
            )
        )

    # Drop empty / duplicate by incident_id (prefer richer)
    by_id: dict[str, dict[str, Any]] = {}
    for inc in incidents:
        if not inc.get("toxic_event_ids"):
            continue
        iid = str(inc["incident_id"])
        prev = by_id.get(iid)
        if prev is None or int(inc.get("branch_observation_count") or 0) >= int(
            prev.get("branch_observation_count") or 0
        ):
            by_id[iid] = inc

    # Merge incidents that share trade_ids improperly — trade exclusivity already enforced
    final = list(by_id.values())

    # Events with no incident membership shouldn't happen; compute uncorrelated as single-branch
    return {"incidents": final, "links": _unique_links(links)}


def _unique_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for link in links:
        lid = str(link.get("link_id") or "")
        if not lid or lid in seen:
            continue
        seen.add(lid)
        out.append(link)
    return out


def build_incident(
    *,
    contexts: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    data_events: list[dict[str, Any]],
    links: list[dict[str, Any]],
    active: dict[str, Any],
) -> dict[str, Any]:
    members = list(contexts) + list(trades) + list(data_events)
    if not members:
        return {}

    branches_present = sorted({str(m.get("branch")) for m in members if m.get("branch")})
    has_data = bool(data_events)
    has_ctx = bool(contexts)
    has_trd = bool(trades)

    # Root cause only with proven linkage rules
    data_linked = False
    member_ids = {str(m.get("toxic_event_id")) for m in members}
    for link in links:
        if link.get("linkage_method") == "DEPENDENCY_WINDOW":
            if str(link.get("from_toxic_event_id")) in member_ids and str(link.get("to_toxic_event_id")) in member_ids:
                data_linked = True
                break

    if has_data and data_linked:
        root_branch = "EXTERNAL_DATA"
        # Prefer still-OPEN data event as root
        open_data = [d for d in data_events if str(d.get("status") or "").upper() == "OPEN"]
        root_event = open_data[0] if open_data else data_events[0]
        root_confidence = "PROVISIONAL"
    elif has_ctx and has_trd:
        root_branch = "CONTEXT"
        root_event = contexts[0]
        root_confidence = "CONFIRMED"
    elif has_ctx:
        root_branch = "CONTEXT"
        root_event = contexts[0]
        root_confidence = "CONFIRMED" if has_trd else "NOT_ESTABLISHED"
        # single context: confidence NOT_ESTABLISHED for cross-root, but still CONFIRMED for exact self
        root_confidence = "NOT_ESTABLISHED"
    elif has_trd:
        root_branch = "TRADE"
        root_event = trades[0]
        root_confidence = "NOT_ESTABLISHED"
    else:
        root_branch = "EXTERNAL_DATA"
        root_event = data_events[0]
        root_confidence = "NOT_ESTABLISHED"

    # Refine confidence for exact context↔trade
    if has_ctx and has_trd and root_branch == "CONTEXT":
        root_confidence = "CONFIRMED"
    if has_data and data_linked and root_branch == "EXTERNAL_DATA":
        root_confidence = "PROVISIONAL"

    root_toxic_event_id = str(root_event.get("toxic_event_id") or "")
    iid = incident_id_for(
        registry_record_id=str(active.get("registry_record_id") or ""),
        paper_epoch_id=str(active.get("paper_epoch_id") or ""),
        root_toxic_event_id=root_toxic_event_id,
    )

    # Status — OPEN loses to RESOLVED when the same source|subtype closed
    open_keys = {
        f"{d.get('source_id')}|{d.get('subtype')}"
        for d in data_events
        if str(d.get("status") or "").upper() == "OPEN"
    }
    resolved_keys = {
        f"{d.get('source_id')}|{d.get('subtype')}"
        for d in data_events
        if str(d.get("status") or "").upper() == "RESOLVED"
    }
    still_open_keys = open_keys - resolved_keys
    resolved_data = [d for d in data_events if str(d.get("status") or "").upper() == "RESOLVED"]
    if still_open_keys and data_linked:
        incident_status = "OPEN"
        resolved_at = None
    elif data_linked and resolved_keys and not still_open_keys:
        incident_status = "RESOLVED"
        resolved_at = resolved_data[-1].get("resolved_at") or resolved_data[-1].get("event_time")
    else:
        incident_status = "OBSERVED"
        resolved_at = None

    # Economic harm: unique trade_id
    harm_by_trade: dict[str, float] = {}
    for trd in trades:
        trade_id = str(trd.get("trade_id") or trd.get("toxic_event_id") or "")
        if not trade_id:
            continue
        harm = _trade_economic_harm(trd)
        if harm > 0:
            # one trade once — keep max confirmed harm for that trade
            harm_by_trade[trade_id] = max(harm_by_trade.get(trade_id, 0.0), harm)
    economic_harm = float(sum(harm_by_trade.values()))

    stamps = [_event_ts(m) for m in members]
    stamps_ok = [s for s in stamps if s is not None]
    started = min(stamps_ok) if stamps_ok else None
    last_obs = max(stamps_ok) if stamps_ok else None

    linkage_methods = sorted(
        {
            str(link.get("linkage_method"))
            for link in links
            if str(link.get("from_toxic_event_id")) in member_ids
            and str(link.get("to_toxic_event_id")) in member_ids
        }
    )
    if not linkage_methods:
        linkage_methods = ["UNLINKED"]

    now = utc_now_iso()
    return {
        "incident_id": iid,
        "incident_status": incident_status,
        "incident_severity": _max_severity(members),
        "registry_record_id": active.get("registry_record_id"),
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "runtime_fingerprint": active.get("runtime_fingerprint"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "root_cause_branch": root_branch,
        "root_cause_subtype": root_event.get("subtype"),
        "root_cause_confidence": root_confidence,
        "root_toxic_event_id": root_toxic_event_id,
        "started_at": _iso(started),
        "last_observation_at": _iso(last_obs),
        "resolved_at": resolved_at,
        "branch_observation_count": len(members),
        "branches_present": branches_present,
        "toxic_event_ids": [m.get("toxic_event_id") for m in members],
        "context_event_ids": sorted(
            {str(m.get("context_event_id")) for m in members if m.get("context_event_id")}
        ),
        "lifecycle_episode_ids": sorted(
            {str(m.get("lifecycle_episode_id")) for m in members if m.get("lifecycle_episode_id")}
        ),
        "trade_ids": sorted({str(m.get("trade_id")) for m in trades if m.get("trade_id")}),
        "source_ids": sorted({str(m.get("source_id")) for m in data_events if m.get("source_id")}),
        "linkage_methods": linkage_methods,
        "economic_harm_usd": economic_harm,
        "created_at": now,
        "updated_at": now,
    }


def update_incident_snapshot(
    *,
    incidents_path: Path,
    links_path: Path,
    current_path: Path,
    incidents: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> None:
    from btc_ml.model_assurance.toxic_box.common import append_jsonl

    existing_inc = {str(r.get("incident_id")) for r in read_jsonl(incidents_path) if r.get("incident_id")}
    existing_links = {str(r.get("link_id")) for r in read_jsonl(links_path) if r.get("link_id")}

    for inc in incidents:
        iid = str(inc.get("incident_id") or "")
        if not iid:
            continue
        if iid not in existing_inc:
            append_jsonl(incidents_path, inc)
            existing_inc.add(iid)
            continue
        prior_rows = [r for r in read_jsonl(incidents_path) if r.get("incident_id") == iid]
        last = prior_rows[-1] if prior_rows else None
        if last and (
            last.get("incident_status") != inc.get("incident_status")
            or last.get("resolved_at") != inc.get("resolved_at")
            or last.get("incident_severity") != inc.get("incident_severity")
            or last.get("branch_observation_count") != inc.get("branch_observation_count")
        ):
            row = dict(inc)
            row["revision_of"] = last.get("updated_at")
            row["updated_at"] = utc_now_iso()
            append_jsonl(incidents_path, row)

    for link in links:
        lid = str(link.get("link_id") or "")
        if not lid or lid in existing_links:
            continue
        append_jsonl(links_path, link)
        existing_links.add(lid)

    atomic_write_json(
        current_path,
        {
            "incidents": incidents,
            "updated_at": utc_now_iso(),
            "count": len(incidents),
        },
    )


def build_incident_summary(
    *,
    active: dict[str, Any],
    incidents: list[dict[str, Any]],
    events_by_branch: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    cross = [i for i in incidents if len(i.get("branches_present") or []) >= 2]
    single = [i for i in incidents if len(i.get("branches_present") or []) == 1]

    open_i = [i for i in incidents if i.get("incident_status") == "OPEN"]
    observed_i = [i for i in incidents if i.get("incident_status") == "OBSERVED"]
    resolved_i = [i for i in incidents if i.get("incident_status") == "RESOLVED"]

    critical = [i for i in incidents if i.get("incident_severity") == "CRITICAL"]
    warning = [i for i in incidents if i.get("incident_severity") == "WARNING"]
    watch = [i for i in incidents if i.get("incident_severity") == "WATCH"]

    counts_by_root: dict[str, int] = {}
    counts_by_combo: dict[str, int] = {}
    counts_by_link: dict[str, int] = {}
    for i in incidents:
        rb = str(i.get("root_cause_branch") or "")
        counts_by_root[rb] = counts_by_root.get(rb, 0) + 1
        combo = "+".join(i.get("branches_present") or [])
        counts_by_combo[combo] = counts_by_combo.get(combo, 0) + 1
        for m in i.get("linkage_methods") or []:
            counts_by_link[str(m)] = counts_by_link.get(str(m), 0) + 1

    # Uncorrelated = events that only appear in single-branch incidents of their own branch
    single_event_ids = {
        tid
        for i in single
        for tid in (i.get("toxic_event_ids") or [])
    }
    cross_event_ids = {
        tid
        for i in cross
        for tid in (i.get("toxic_event_ids") or [])
    }

    all_incident_event_ids = single_event_ids | cross_event_ids

    def _uncorrelated(branch: str) -> int:
        n = 0
        for e in events_by_branch.get(branch) or []:
            # RESOLVED companion rows for external data still count as events;
            # correlation uses OPEN root — count events not attached to any incident.
            tid = e.get("toxic_event_id")
            if tid and tid not in all_incident_event_ids:
                # Also treat resolved_from companion as correlated if open root is in an incident
                evid = e.get("evidence") if isinstance(e.get("evidence"), dict) else {}
                resolved_from = evid.get("resolved_from")
                if resolved_from and resolved_from in all_incident_event_ids:
                    continue
                n += 1
        return n

    branch_obs = sum(int(i.get("branch_observation_count") or 0) for i in incidents)
    econ = float(sum(float(i.get("economic_harm_usd") or 0.0) for i in incidents))

    # Eligible correlation subjects are context/trade toxic events.
    # Standalone external-data issues remain observational uncorrelated counts.
    eligible = len(events_by_branch.get("CONTEXT") or []) + len(events_by_branch.get("TRADE") or [])

    if eligible == 0 and not incidents:
        status = "NO_ELIGIBLE_INCIDENTS_YET"
    elif critical:
        status = "CURRENT_CRITICAL"
    elif warning:
        status = "CURRENT_WARNING"
    elif watch or observed_i:
        status = "CURRENT_WATCH"
    else:
        status = "CURRENT_CLEAR"

    last_at = None
    for i in incidents:
        cand = i.get("last_observation_at") or i.get("updated_at")
        if cand and (last_at is None or str(cand) > str(last_at)):
            last_at = cand

    return {
        "status": status,
        "runtime_impact": "NON_BLOCKING",
        "monitoring_mode": "LIVE_CURRENT",
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "registry_record_id": active.get("registry_record_id"),
        "distinct_incidents": len(incidents),
        "branch_observations": branch_obs,
        "cross_branch_incidents": len(cross),
        "single_branch_incidents": len(single),
        "open_incidents": len(open_i),
        "observed_incidents": len(observed_i),
        "resolved_incidents": len(resolved_i),
        "critical_incidents": len(critical),
        "warning_incidents": len(warning),
        "watch_incidents": len(watch),
        "counts_by_root_cause": counts_by_root,
        "counts_by_branch_combination": counts_by_combo,
        "counts_by_linkage_method": counts_by_link,
        "uncorrelated_external_events": _uncorrelated("EXTERNAL_DATA"),
        "uncorrelated_context_events": _uncorrelated("CONTEXT"),
        "uncorrelated_trade_events": _uncorrelated("TRADE"),
        "economic_harm_usd": econ,
        "last_incident_at": last_at,
        "updated_at": utc_now_iso(),
    }


def run_once(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    p = paths(root)
    active = read_active_runtime(repo_root=root)
    if not active:
        summary = {
            "status": "NO_ELIGIBLE_INCIDENTS_YET",
            "runtime_impact": "NON_BLOCKING",
            "monitoring_mode": "LIVE_CURRENT",
            "distinct_incidents": 0,
            "branch_observations": 0,
            "updated_at": utc_now_iso(),
        }
        atomic_write_json(p["latest_summary"], summary)
        atomic_write_json(
            p["health"],
            {
                "status": summary["status"],
                "alive": True,
                "runtime_impact": "NON_BLOCKING",
                "updated_at": utc_now_iso(),
            },
        )
        return summary

    checkpoint = load_json(p["checkpoint"]) or {}
    events_by_branch = load_new_toxic_events(paths_map=p, active=active, checkpoint=checkpoint)
    sources = load_external_source_registry(p["external_config"])
    correlated = correlate_events(events_by_branch=events_by_branch, sources=sources, active=active)
    incidents = correlated["incidents"]
    links = correlated["links"]

    update_incident_snapshot(
        incidents_path=p["incidents_events"],
        links_path=p["incident_links"],
        current_path=p["current_incidents"],
        incidents=incidents,
        links=links,
    )
    summary = build_incident_summary(active=active, incidents=incidents, events_by_branch=events_by_branch)
    atomic_write_json(p["latest_summary"], summary)
    atomic_write_json(
        p["checkpoint"],
        {
            "paper_epoch_id": active.get("paper_epoch_id"),
            "external_event_count": len(events_by_branch.get("EXTERNAL_DATA") or []),
            "context_event_count": len(events_by_branch.get("CONTEXT") or []),
            "trade_event_count": len(events_by_branch.get("TRADE") or []),
            "incident_count": len(incidents),
            "updated_at": utc_now_iso(),
        },
    )
    atomic_write_json(
        p["health"],
        {
            "status": summary["status"],
            "alive": True,
            "runtime_impact": "NON_BLOCKING",
            "monitoring_mode": "LIVE_CURRENT",
            "pid": os.getpid(),
            "paper_epoch_id": active.get("paper_epoch_id"),
            "distinct_incidents": summary["distinct_incidents"],
            "paper_only": active.get("paper_only", True),
            "real_execution": active.get("real_execution", False),
            "updated_at": utc_now_iso(),
        },
    )
    return summary
