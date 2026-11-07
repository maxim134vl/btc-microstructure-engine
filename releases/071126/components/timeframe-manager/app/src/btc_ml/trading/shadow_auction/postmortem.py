"""AES5 post-mortem — eventual auction resolution AFTER canonical close.

Never rewrites context/entry verdicts, first-support timestamps, or AES4 checkpoints.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .checkpoint import ShadowHistoryIndex
from .states import (
    FAMILY_BALANCE,
    FAMILY_DIRECTIONAL_DOWN,
    FAMILY_DIRECTIONAL_UP,
    FAMILY_TRANSITION,
    PHASE_FAILED_DOWNSIDE_BREAK,
    PHASE_FAILED_UPSIDE_BREAK,
    PHASE_RESOLUTION_DOWN,
    PHASE_RESOLUTION_UP,
)

STATUS_WAITING = "WAITING_FOR_EPISODE_RESOLUTION"
STATUS_COMPLETE = "COMPLETE"
STATUS_EXPIRED = "HORIZON_EXPIRED"
STATUS_INSUFFICIENT = "INSUFFICIENT_COVERAGE"

RES_UP = "UP"
RES_DOWN = "DOWN"
RES_BALANCE = "BALANCE"
RES_UNRESOLVED = "UNRESOLVED"

LABEL_ACCUMULATION = "ACCUMULATION_LIKE"
LABEL_DISTRIBUTION = "DISTRIBUTION_LIKE"
LABEL_REACCUMULATION = "REACCUMULATION_LIKE"
LABEL_REDISTRIBUTION = "REDISTRIBUTION_LIKE"
LABEL_UNRESOLVED_BALANCE = "UNRESOLVED_BALANCE"

DEFAULT_HORIZON_SEC = 14 * 24 * 3600


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def deterministic_postmortem_id(case_id: str) -> str:
    return "PM_" + hashlib.sha1(f"AES5|{case_id}".encode()).hexdigest()[:20]


def _family_bucket(family: str | None, phase: str | None) -> str | None:
    if phase in {PHASE_RESOLUTION_UP}:
        return RES_UP
    if phase in {PHASE_RESOLUTION_DOWN}:
        return RES_DOWN
    if family == FAMILY_DIRECTIONAL_UP:
        return FAMILY_DIRECTIONAL_UP
    if family == FAMILY_DIRECTIONAL_DOWN:
        return FAMILY_DIRECTIONAL_DOWN
    if family in {FAMILY_BALANCE, FAMILY_TRANSITION}:
        return FAMILY_BALANCE
    return None


def retrospective_label(path: Sequence[str]) -> str | None:
    """Classify DOWN→BALANCE→UP etc. Suffix _LIKE is mandatory."""
    compact: list[str] = []
    for item in path:
        if not compact or compact[-1] != item:
            compact.append(item)
    has_bal = FAMILY_BALANCE in compact
    if not has_bal:
        return None
    # Find directional before first balance and resolution after last balance.
    try:
        bi = compact.index(FAMILY_BALANCE)
    except ValueError:
        return None
    before = compact[:bi]
    after = compact[bi + 1 :]
    pre = None
    for x in reversed(before):
        if x in {FAMILY_DIRECTIONAL_UP, FAMILY_DIRECTIONAL_DOWN}:
            pre = x
            break
    post = None
    for x in after:
        if x in {RES_UP, RES_DOWN, FAMILY_DIRECTIONAL_UP, FAMILY_DIRECTIONAL_DOWN}:
            post = RES_UP if x in {RES_UP, FAMILY_DIRECTIONAL_UP} else RES_DOWN
            break
    if pre is None and not after:
        return LABEL_UNRESOLVED_BALANCE
    if post is None:
        return LABEL_UNRESOLVED_BALANCE
    if pre == FAMILY_DIRECTIONAL_DOWN and post == RES_UP:
        return LABEL_ACCUMULATION
    if pre == FAMILY_DIRECTIONAL_UP and post == RES_DOWN:
        return LABEL_DISTRIBUTION
    if pre == FAMILY_DIRECTIONAL_UP and post == RES_UP:
        return LABEL_REACCUMULATION
    if pre == FAMILY_DIRECTIONAL_DOWN and post == RES_DOWN:
        return LABEL_REDISTRIBUTION
    return LABEL_UNRESOLVED_BALANCE


def build_postmortem(
    *,
    case_id: str,
    trade_id: str | None,
    position_id: str | None,
    context_ckp: Mapping[str, Any] | None,
    entry_ckp: Mapping[str, Any] | None,
    close_ckp: Mapping[str, Any] | None,
    index: ShadowHistoryIndex,
    extra_anchor_rows: Sequence[Mapping[str, Any]] | None = None,
    extra_hierarchy_rows: Sequence[Mapping[str, Any]] | None = None,
    now_ts: str | None = None,
    horizon_sec: int = DEFAULT_HORIZON_SEC,
    logic_version: str = "AES_V1",
    logic_fingerprint: str = "",
) -> dict[str, Any]:
    tf = str((entry_ckp or close_ckp or context_ckp or {}).get("canonical_timeframe") or "M15").upper()
    ctx_ts = None if context_ckp is None else context_ckp.get("canonical_timestamp")
    entry_ts = None if entry_ckp is None else entry_ckp.get("canonical_timestamp")
    close_ts = None if close_ckp is None else close_ckp.get("canonical_timestamp")

    def _snap_ep(ckp: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
        if ckp is None:
            return None, None
        snap = ckp.get(f"{tf.lower()}_snapshot") or {}
        if not isinstance(snap, dict):
            return None, None
        return snap.get("shadow_episode_id"), snap.get("auction_family")

    ep_ctx, fam_ctx = _snap_ep(context_ckp)
    ep_ent, fam_ent = _snap_ep(entry_ckp)
    ep_cls, fam_cls = _snap_ep(close_ckp)

    coverage = (close_ckp or entry_ckp or context_ckp or {}).get("coverage_status")
    stale_or_missing = coverage in {"NO_SHADOW_COVERAGE", "STALE_COVERAGE", "MISSING"}
    extra = [dict(r) for r in extra_anchor_rows or []]
    index_rows = [] if stale_or_missing else list(index.tf_rows.get(tf, []))
    if ep_cls:
        filtered = []
        for row in index_rows:
            epid = row.get("shadow_episode_id")
            if epid in {None, "", ep_cls}:
                filtered.append(row)
        index_rows = filtered
    rows = index_rows + extra
    rows.sort(key=lambda r: str(r.get("timestamp") or ""))

    close_dt = _parse_ts(str(close_ts) if close_ts else None)
    path: list[str] = []
    # Seed path from checkpoint families so DOWN→BALANCE→UP works even if history starts later.
    for fam in (fam_ctx, fam_ent, fam_cls):
        b = _family_bucket(fam, None)
        if b:
            path.append(b)

    failed_up = 0
    failed_down = 0
    balance_first: datetime | None = None
    balance_last: datetime | None = None
    resolution_ts: str | None = None
    resolution: str | None = None
    episode_at_close = ep_cls
    episode_changed = bool(ep_ctx and ep_ent and ep_ctx != ep_ent) or bool(
        ep_ent and ep_cls and ep_ent != ep_cls
    )

    for row in rows:
        ts = str(row.get("timestamp") or "")
        rts = _parse_ts(ts)
        if rts is None:
            continue
        bucket = _family_bucket(row.get("auction_family"), row.get("episode_phase"))
        if bucket:
            path.append(bucket)
        if row.get("episode_phase") == PHASE_FAILED_UPSIDE_BREAK:
            failed_up += 1
        if row.get("episode_phase") == PHASE_FAILED_DOWNSIDE_BREAK:
            failed_down += 1
        if bucket == FAMILY_BALANCE:
            if balance_first is None:
                balance_first = rts
            balance_last = rts
        if close_dt is not None and rts >= close_dt:
            if row.get("episode_phase") in {PHASE_RESOLUTION_UP, PHASE_RESOLUTION_DOWN} and resolution is None:
                resolution = RES_UP if row.get("episode_phase") == PHASE_RESOLUTION_UP else RES_DOWN
                resolution_ts = ts
            if row.get("shadow_episode_id") and episode_at_close and row.get("shadow_episode_id") != episode_at_close:
                episode_changed = True
                if resolution is None:
                    # Episode identity change counts as structural end.
                    resolution_ts = ts
                    if bucket in {RES_UP, FAMILY_DIRECTIONAL_UP}:
                        resolution = RES_UP
                    elif bucket in {RES_DOWN, FAMILY_DIRECTIONAL_DOWN}:
                        resolution = RES_DOWN

    # If extra rows encode explicit resolution after close, prefer last such.
    for row in reversed(rows):
        ts = str(row.get("timestamp") or "")
        rts = _parse_ts(ts)
        if rts is None:
            continue
        if close_dt is not None and rts < close_dt:
            continue
        if row.get("episode_phase") == PHASE_RESOLUTION_UP:
            resolution = RES_UP
            resolution_ts = ts
            break
        if row.get("episode_phase") == PHASE_RESOLUTION_DOWN:
            resolution = RES_DOWN
            resolution_ts = ts
            break

    hier_rows = [] if stale_or_missing else list(index.hierarchy_rows)
    if extra_hierarchy_rows:
        hier_rows = hier_rows + [dict(r) for r in extra_hierarchy_rows]
    hier_rows.sort(key=lambda r: str(r.get("timestamp") or ""))
    max_depth = 0
    eventual_hier = None
    first_higher_conf = None
    first_higher_rej = None
    for h in hier_rows:
        ts = str(h.get("timestamp") or "")
        rts = _parse_ts(ts)
        depth = h.get("propagation_depth") or 0
        try:
            max_depth = max(max_depth, int(depth))
        except (TypeError, ValueError):
            pass
        if close_dt is None or (rts and rts >= close_dt):
            eventual_hier = h.get("hierarchy_state")
        hs = str(h.get("hierarchy_state") or "")
        if "ALIGNED" in hs or "RESOLUTION" in hs:
            if first_higher_conf is None:
                first_higher_conf = ts
        if "CONFLICT" in hs or "LOCAL_" in hs:
            if first_higher_rej is None:
                first_higher_rej = ts

    label = retrospective_label(path)
    reasons: list[str] = []
    if resolution == RES_UP:
        reasons.append("POSTMORTEM_RESOLUTION_UP")
    elif resolution == RES_DOWN:
        reasons.append("POSTMORTEM_RESOLUTION_DOWN")
    if label == LABEL_ACCUMULATION:
        reasons.append("POSTMORTEM_ACCUMULATION_LIKE")
    elif label == LABEL_DISTRIBUTION:
        reasons.append("POSTMORTEM_DISTRIBUTION_LIKE")
    elif label == LABEL_REACCUMULATION:
        reasons.append("POSTMORTEM_REACCUMULATION_LIKE")
    elif label == LABEL_REDISTRIBUTION:
        reasons.append("POSTMORTEM_REDISTRIBUTION_LIKE")
    elif label == LABEL_UNRESOLVED_BALANCE:
        reasons.append("POSTMORTEM_UNRESOLVED")

    now = _parse_ts(now_ts) if now_ts else datetime.now(timezone.utc)
    status = STATUS_WAITING
    if stale_or_missing:
        status = STATUS_INSUFFICIENT
        reasons.append("POSTMORTEM_UNRESOLVED")
        resolution = None
        resolution_ts = None
        label = None
    elif resolution is not None:
        status = STATUS_COMPLETE
    elif close_dt and now and (now - close_dt).total_seconds() > float(horizon_sec):
        status = STATUS_EXPIRED
        reasons.append("POSTMORTEM_UNRESOLVED")
    elif label == LABEL_UNRESOLVED_BALANCE and resolution is None:
        status = STATUS_WAITING

    time_to_res = None
    if resolution_ts and close_ts:
        a, b = _parse_ts(resolution_ts), _parse_ts(str(close_ts))
        if a and b:
            time_to_res = (a - b).total_seconds()

    bal_dur = None
    if balance_first and balance_last:
        bal_dur = max(0.0, (balance_last - balance_first).total_seconds())

    eventual_anchor = resolution or (RES_BALANCE if FAMILY_BALANCE in path and resolution is None else RES_UNRESOLVED)
    if status in {STATUS_WAITING, STATUS_INSUFFICIENT, STATUS_EXPIRED}:
        eventual_anchor = RES_UNRESOLVED

    return {
        "postmortem_id": deterministic_postmortem_id(case_id),
        "shadow_case_id": case_id,
        "trade_id": trade_id,
        "position_id": position_id,
        "postmortem_status": status,
        "context_timestamp": ctx_ts,
        "entry_timestamp": entry_ts,
        "close_timestamp": close_ts,
        "anchor_timeframe": tf,
        "anchor_episode_id_at_context": ep_ctx,
        "anchor_episode_id_at_entry": ep_ent,
        "anchor_episode_id_at_close": ep_cls,
        "episode_changed_during_trade": episode_changed,
        "anchor_family_at_context": fam_ctx,
        "anchor_family_at_entry": fam_ent,
        "anchor_family_at_close": fam_cls,
        "eventual_anchor_resolution": eventual_anchor,
        "eventual_resolution_timestamp": resolution_ts,
        "balance_formed": FAMILY_BALANCE in path,
        "balance_duration_sec": bal_dur,
        "failed_upside_break_count": failed_up,
        "failed_downside_break_count": failed_down,
        "max_propagation_depth": max_depth,
        "first_higher_tf_confirmation_timestamp": first_higher_conf,
        "first_higher_tf_rejection_timestamp": first_higher_rej,
        "eventual_hierarchy_state": eventual_hier,
        "time_to_resolution_sec": time_to_res,
        "retrospective_structure_label": label,
        "reason_codes": sorted(set(reasons)),
        "logic_version": logic_version,
        "logic_fingerprint": logic_fingerprint,
        "created_at": _iso_now(),
    }


@dataclass
class PostmortemEngine:
    logic_version: str = "AES_V1"
    logic_fingerprint: str = ""
    horizon_sec: int = DEFAULT_HORIZON_SEC
    index: ShadowHistoryIndex = field(default_factory=ShadowHistoryIndex)
    _seen: dict[str, str] = field(default_factory=dict)
    _status: dict[str, str] = field(default_factory=dict)
    postmortems_complete: int = 0
    postmortems_waiting: int = 0
    postmortems_expired: int = 0
    duplicate_suppressed: int = 0
    payload_conflicts: int = 0
    last_postmortem_id: str | None = None

    def ingest(self, record: Mapping[str, Any]) -> dict[str, Any]:
        pid = str(record.get("postmortem_id") or "")
        payload_hash = hashlib.sha1(
            json.dumps({k: v for k, v in record.items() if k != "created_at"}, sort_keys=True, default=str).encode()
        ).hexdigest()
        status = str(record.get("postmortem_status") or "")
        prev = self._seen.get(pid)
        if prev == payload_hash:
            self.duplicate_suppressed += 1
            return {"written": False, "duplicate": True, "payload_conflict": False, "record": dict(record)}
        if prev is not None:
            prev_status = self._status.get(pid, "")
            allowed = prev_status == STATUS_WAITING and status in {
                STATUS_COMPLETE,
                STATUS_EXPIRED,
                STATUS_INSUFFICIENT,
                STATUS_WAITING,
            }
            if not allowed:
                self.payload_conflicts += 1
                return {"written": False, "duplicate": False, "payload_conflict": True, "record": dict(record)}
            self._seen[pid] = payload_hash
            self._status[pid] = status
            self._count_status(status)
            self.last_postmortem_id = pid
            return {"written": True, "duplicate": False, "payload_conflict": False, "record": dict(record), "updated": True}
        self._seen[pid] = payload_hash
        self._status[pid] = status
        if len(self._seen) > 10000:
            keys = list(self._seen.keys())[-5000:]
            self._seen = {k: self._seen[k] for k in keys}
            self._status = {k: self._status[k] for k in keys if k in self._status}
        self._count_status(status)
        self.last_postmortem_id = pid
        return {"written": True, "duplicate": False, "payload_conflict": False, "record": dict(record)}

    def _count_status(self, status: str) -> None:
        if status == STATUS_COMPLETE:
            self.postmortems_complete += 1
        elif status == STATUS_EXPIRED:
            self.postmortems_expired += 1
        elif status == STATUS_WAITING:
            self.postmortems_waiting += 1

    def health_fields(self) -> dict[str, Any]:
        return {
            "postmortems_complete": self.postmortems_complete,
            "postmortems_waiting": self.postmortems_waiting,
            "postmortems_expired": self.postmortems_expired,
            "last_postmortem_id": self.last_postmortem_id,
        }

    def restore(self, path) -> int:
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return 0
        n = 0
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pid = row.get("postmortem_id")
                if not pid:
                    continue
                self._seen[str(pid)] = hashlib.sha1(
                    json.dumps({k: v for k, v in row.items() if k != "created_at"}, sort_keys=True, default=str).encode()
                ).hexdigest()
                self._status[str(pid)] = str(row.get("postmortem_status") or "")
                n += 1
        return n
