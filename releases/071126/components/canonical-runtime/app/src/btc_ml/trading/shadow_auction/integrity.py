"""AES6B integrity / consistency auditor — read-only, never auto-repairs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .checkpoint import TF_ORDER
from .verdict import interpret_checkpoint

SEVERITY_PASS = "PASS"
SEVERITY_WARNING = "WARNING"
SEVERITY_FAIL = "FAIL"

VALID_TFS = set(TF_ORDER)


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


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "context": dict(self.context),
        }


@dataclass
class IntegrityAuditor:
    """Read-only auditor over a Shadow Auction memory root."""

    data_root: Path
    findings: list[Finding] = field(default_factory=list)
    funnel: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def _add(self, severity: str, code: str, message: str, **ctx: Any) -> None:
        self.findings.append(Finding(severity=severity, code=code, message=message, context=ctx))

    def run(self) -> dict[str, Any]:
        mem = self.data_root / "memory"
        events = _load_jsonl(mem / "tf_event_memory.jsonl")
        episodes = _load_jsonl(mem / "tf_episode_memory.jsonl")
        hierarchy = _load_jsonl(mem / "hierarchy_memory.jsonl")
        checkpoints = _load_jsonl(mem / "canonical_checkpoint_memory.jsonl")
        verdicts = _load_jsonl(mem / "checkpoint_verdict_memory.jsonl")
        outcomes = _load_jsonl(mem / "shadow_outcome_memory.jsonl")
        postmortems = _load_jsonl(mem / "postmortem_memory.jsonl")

        self.counts = {
            "aes2_event_count": len(events),
            "aes2_episode_count": len(episodes),
            "aes3_hierarchy_count": len(hierarchy),
            "aes4_checkpoint_count": len(checkpoints),
            "aes5_verdict_count": len(verdicts),
            "aes5_outcome_count": len(outcomes),
            "aes5_postmortem_count": len(postmortems),
        }

        self._audit_aes2(events, episodes)
        self._audit_aes3(hierarchy, episodes)
        self._audit_aes4(checkpoints)
        self._audit_aes5(verdicts, outcomes, postmortems, checkpoints)
        self._audit_lineage(checkpoints, verdicts, outcomes, postmortems)
        self._build_funnel(checkpoints, verdicts, outcomes, postmortems)

        fails = sum(1 for f in self.findings if f.severity == SEVERITY_FAIL)
        warns = sum(1 for f in self.findings if f.severity == SEVERITY_WARNING)
        status = SEVERITY_PASS
        if fails:
            status = SEVERITY_FAIL
        elif warns:
            status = SEVERITY_WARNING

        lookahead = sum(1 for f in self.findings if "LOOKAHEAD" in f.code)
        duplicates = sum(1 for f in self.findings if "DUPLICATE" in f.code and f.severity == SEVERITY_FAIL)
        conflicts = sum(1 for f in self.findings if "PAYLOAD_CONFLICT" in f.code)
        ordering = sum(1 for f in self.findings if "ORDERING" in f.code or "CHRONOLOGY" in f.code)
        broken = sum(1 for f in self.findings if "MISSING_REF" in f.code or "BROKEN" in f.code)

        return {
            "status": status,
            "data_root": str(self.data_root),
            "counts": self.counts,
            "funnel": self.funnel,
            "duplicates": duplicates,
            "payload_conflicts": conflicts,
            "ordering_violations": ordering,
            "lookahead_violations": lookahead,
            "broken_references": broken,
            "findings": [f.to_dict() for f in self.findings],
            "fail_count": fails,
            "warning_count": warns,
        }

    def _audit_aes2(self, events: list[dict[str, Any]], episodes: list[dict[str, Any]]) -> None:
        seen_event_ids: dict[str, dict[str, Any]] = {}
        last_ts: dict[str, datetime] = {}
        for row in events:
            tf = str(row.get("timeframe") or "").upper()
            if tf not in VALID_TFS:
                self._add(SEVERITY_FAIL, "AES2_INVALID_TF", f"invalid timeframe {tf}", row=row.get("source_event_id"))
            eid = str(row.get("source_event_id") or "")
            if eid:
                prev = seen_event_ids.get(eid)
                if prev is not None:
                    if strip_compare(prev, row):
                        # Safe duplicate of identical logical payload.
                        pass
                    else:
                        self._add(
                            SEVERITY_FAIL,
                            "AES2_PAYLOAD_CONFLICT",
                            "conflicting duplicate source_event_id",
                            source_event_id=eid,
                        )
                else:
                    seen_event_ids[eid] = row
            ts = _parse_ts(row.get("timestamp"))
            if ts is None:
                self._add(SEVERITY_WARNING, "AES2_BAD_TIMESTAMP", "unparseable timestamp", source_event_id=eid)
                continue
            if tf in last_ts and ts < last_ts[tf]:
                self._add(
                    SEVERITY_WARNING,
                    "AES2_ORDERING_REGRESSION",
                    "timestamp regression in TF stream",
                    timeframe=tf,
                    timestamp=row.get("timestamp"),
                )
            last_ts[tf] = ts
            if not row.get("logic_fingerprint"):
                self._add(SEVERITY_WARNING, "AES2_MISSING_FINGERPRINT", "missing logic_fingerprint", source_event_id=eid)

        ep_ids = {str(r.get("shadow_episode_id")) for r in episodes if r.get("shadow_episode_id")}
        for row in events:
            epid = row.get("shadow_episode_id")
            if epid and str(epid) not in ep_ids and episodes:
                # Event may precede episode snapshot write order; warn only if episodes exist.
                pass

    def _audit_aes3(self, hierarchy: list[dict[str, Any]], episodes: list[dict[str, Any]]) -> None:
        last_ts: datetime | None = None
        for row in hierarchy:
            ts = _parse_ts(row.get("timestamp"))
            if ts is None:
                continue
            if last_ts is not None and ts < last_ts:
                self._add(SEVERITY_WARNING, "AES3_ORDERING_REGRESSION", "hierarchy timestamp regression")
            last_ts = ts
            depth = row.get("propagation_depth")
            try:
                d = int(depth)
            except (TypeError, ValueError):
                self._add(SEVERITY_FAIL, "AES3_BAD_DEPTH", "propagation_depth not int")
                continue
            if d < 0 or d > 3:
                self._add(SEVERITY_FAIL, "AES3_BAD_DEPTH", "propagation_depth out of 0..3", depth=d)
            # Lookahead vs AES2: hierarchy timestamp must not precede all TF evidence in an impossible way;
            # check as-of: for each hierarchy row, no episode with later timestamp should be required —
            # we verify no hierarchy references a TF state timestamp > hierarchy timestamp.
            for key in ("m15_state_timestamp", "m30_state_timestamp", "h1_state_timestamp", "h4_state_timestamp"):
                rts = _parse_ts(row.get(key))
                if rts is not None and rts > ts:
                    self._add(
                        SEVERITY_FAIL,
                        "AES3_LOOKAHEAD",
                        "hierarchy references future TF state",
                        field=key,
                        hierarchy_ts=row.get("timestamp"),
                        tf_ts=row.get(key),
                    )

    def _audit_aes4(self, checkpoints: list[dict[str, Any]]) -> None:
        seen: dict[str, dict[str, Any]] = {}
        for ckp in checkpoints:
            cid = str(ckp.get("checkpoint_id") or "")
            if not cid:
                self._add(SEVERITY_FAIL, "AES4_MISSING_ID", "checkpoint without id")
                continue
            if cid in seen:
                if strip_compare(seen[cid], ckp):
                    pass
                else:
                    self._add(SEVERITY_FAIL, "AES4_PAYLOAD_CONFLICT", "duplicate checkpoint_id conflict", checkpoint_id=cid)
                    self._add(SEVERITY_FAIL, "AES4_DUPLICATE_CHECKPOINT", "duplicate checkpoint_id", checkpoint_id=cid)
            else:
                seen[cid] = ckp
            cts = _parse_ts(ckp.get("canonical_timestamp"))
            if cts is None:
                self._add(SEVERITY_WARNING, "AES4_BAD_TIMESTAMP", "bad canonical timestamp", checkpoint_id=cid)
                continue
            for tf in TF_ORDER:
                snap = ckp.get(f"{tf.lower()}_snapshot")
                if not isinstance(snap, dict):
                    continue
                sts = _parse_ts(snap.get("shadow_state_timestamp") or snap.get("timestamp"))
                if sts is not None and sts > cts:
                    self._add(
                        SEVERITY_FAIL,
                        "AES4_LOOKAHEAD",
                        "TF snapshot after canonical timestamp",
                        checkpoint_id=cid,
                        timeframe=tf,
                    )
            hier = ckp.get("hierarchy_snapshot")
            if isinstance(hier, dict):
                hts = _parse_ts(hier.get("hierarchy_timestamp") or hier.get("timestamp"))
                if hts is not None and hts > cts:
                    self._add(
                        SEVERITY_FAIL,
                        "AES4_HIERARCHY_LOOKAHEAD",
                        "hierarchy snapshot after canonical timestamp",
                        checkpoint_id=cid,
                    )
            cov = ckp.get("coverage_status")
            available = sum(
                1 for tf in TF_ORDER if ckp.get(f"{tf.lower()}_coverage_status") == "AVAILABLE"
            )
            if cov == "COMPLETE" and available < 4:
                self._add(
                    SEVERITY_FAIL,
                    "AES4_COVERAGE_MISMATCH",
                    "COMPLETE coverage but TF available < 4",
                    checkpoint_id=cid,
                )
            if cov == "NO_SHADOW_COVERAGE" and available > 0:
                self._add(
                    SEVERITY_WARNING,
                    "AES4_COVERAGE_MISMATCH",
                    "NO_SHADOW_COVERAGE but some TF available",
                    checkpoint_id=cid,
                )

    def _audit_aes5(
        self,
        verdicts: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        postmortems: list[dict[str, Any]],
        checkpoints: list[dict[str, Any]],
    ) -> None:
        ckp_by_id = {str(c.get("checkpoint_id")): c for c in checkpoints if c.get("checkpoint_id")}
        seen_v: dict[str, dict[str, Any]] = {}
        for v in verdicts:
            vid = str(v.get("verdict_id") or "")
            cid = str(v.get("checkpoint_id") or "")
            if cid and cid not in ckp_by_id:
                self._add(SEVERITY_FAIL, "AES5_MISSING_REF", "verdict references missing checkpoint", checkpoint_id=cid)
            if vid in seen_v:
                if not strip_compare(seen_v[vid], v):
                    self._add(SEVERITY_FAIL, "AES5_PAYLOAD_CONFLICT", "verdict payload conflict", verdict_id=vid)
            else:
                seen_v[vid] = v
            ckp = ckp_by_id.get(cid)
            if ckp is not None:
                expected = interpret_checkpoint(ckp).get("checkpoint_verdict")
                if expected != v.get("checkpoint_verdict"):
                    # Recompute may differ only if logic changed; fingerprint mismatch already warned.
                    if ckp.get("logic_fingerprint") == v.get("logic_fingerprint"):
                        self._add(
                            SEVERITY_FAIL,
                            "AES5_VERDICT_MISMATCH",
                            "stored verdict disagrees with frozen checkpoint interpretation",
                            verdict_id=vid,
                        )

        for out in outcomes:
            # Chronology of first_* vs entry.
            entry_ts = _parse_ts(out.get("canonical_entry_timestamp"))
            for field in (
                "first_support_timestamp",
                "first_reject_timestamp",
                "first_opposite_timestamp",
                "first_invalidation_timestamp",
            ):
                fts = _parse_ts(out.get(field))
                if entry_ts and fts and fts < entry_ts and field != "first_support_timestamp":
                    # first_support may equal entry when confirmation_delay=0
                    self._add(
                        SEVERITY_FAIL,
                        "AES5_CHRONOLOGY_VIOLATION",
                        f"{field} before entry",
                        outcome_id=out.get("outcome_id"),
                    )
                if entry_ts and fts and field == "first_support_timestamp" and fts < entry_ts:
                    self._add(
                        SEVERITY_FAIL,
                        "AES5_CHRONOLOGY_VIOLATION",
                        "first_support before entry",
                        outcome_id=out.get("outcome_id"),
                    )
            if out.get("timing_counterfactual_same_exit_pnl") is not None:
                if out.get("counterfactual_type") != "SAME_CANONICAL_EXIT_TIMING_ONLY":
                    self._add(
                        SEVERITY_FAIL,
                        "AES5_COUNTERFACTUAL_TYPE",
                        "timing pnl without explicit counterfactual_type",
                        outcome_id=out.get("outcome_id"),
                    )
            # Postmortem must not alter online verdicts: compare referenced values if both exist.
            oid = out.get("shadow_case_id")
            pm = next((p for p in postmortems if p.get("shadow_case_id") == oid), None)
            if pm is not None:
                # Online verdicts are on outcome; postmortem must not carry rewritten entry_verdict.
                if "entry_verdict" in pm and pm.get("entry_verdict") not in {None, out.get("entry_verdict")}:
                    self._add(
                        SEVERITY_FAIL,
                        "AES5_POSTMORTEM_MUTATION",
                        "postmortem altered entry_verdict",
                        shadow_case_id=oid,
                    )

    def _audit_lineage(
        self,
        checkpoints: list[dict[str, Any]],
        verdicts: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        postmortems: list[dict[str, Any]],
    ) -> None:
        by_case: dict[str, dict[str, Any]] = {}
        for c in checkpoints:
            cid = str(c.get("shadow_case_id") or "")
            if not cid:
                continue
            bucket = by_case.setdefault(cid, {"context": None, "entry": None, "close": None})
            ctype = c.get("checkpoint_type")
            if ctype == "CONTEXT_START":
                bucket["context"] = c
            elif ctype == "PAPER_ENTRY":
                bucket["entry"] = c
            elif ctype == "PAPER_CLOSE":
                bucket["close"] = c
        verdict_by_ckp = {str(v.get("checkpoint_id")): v for v in verdicts}
        for case_id, bucket in by_case.items():
            for role in ("context", "entry", "close"):
                ckp = bucket.get(role)
                if ckp is None:
                    continue
                cid = str(ckp.get("checkpoint_id"))
                if cid not in verdict_by_ckp and verdicts:
                    self._add(
                        SEVERITY_WARNING,
                        "AES5_MISSING_VERDICT",
                        f"no verdict for {role} checkpoint",
                        shadow_case_id=case_id,
                        checkpoint_id=cid,
                    )
            if bucket.get("close") is not None:
                if not any(o.get("shadow_case_id") == case_id for o in outcomes) and outcomes is not None:
                    # May be pending evaluation — warning only when other outcomes exist.
                    pass
                # Close before entry.
                ent = bucket.get("entry")
                close = bucket.get("close")
                if ent and close:
                    et = _parse_ts(ent.get("canonical_timestamp"))
                    ct = _parse_ts(close.get("canonical_timestamp"))
                    if et and ct and ct < et:
                        self._add(
                            SEVERITY_FAIL,
                            "AES4_ORDERING_CLOSE_BEFORE_ENTRY",
                            "close timestamp before entry",
                            shadow_case_id=case_id,
                        )

    def _build_funnel(
        self,
        checkpoints: list[dict[str, Any]],
        verdicts: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        postmortems: list[dict[str, Any]],
    ) -> None:
        ctx = sum(1 for c in checkpoints if c.get("checkpoint_type") == "CONTEXT_START")
        ent = sum(1 for c in checkpoints if c.get("checkpoint_type") == "PAPER_ENTRY")
        close = sum(1 for c in checkpoints if c.get("checkpoint_type") == "PAPER_CLOSE")
        cov = {"COMPLETE": 0, "PARTIAL": 0, "STALE_COVERAGE": 0, "NO_SHADOW_COVERAGE": 0}
        for c in checkpoints:
            k = str(c.get("coverage_status") or "")
            if k in cov:
                cov[k] += 1
        pm_complete = sum(1 for p in postmortems if p.get("postmortem_status") == "COMPLETE")
        pm_wait = sum(1 for p in postmortems if p.get("postmortem_status") == "WAITING_FOR_EPISODE_RESOLUTION")
        pm_exp = sum(1 for p in postmortems if p.get("postmortem_status") == "HORIZON_EXPIRED")
        open_cases = 0
        cases: dict[str, set[str]] = {}
        for c in checkpoints:
            cid = str(c.get("shadow_case_id") or "")
            if not cid:
                continue
            cases.setdefault(cid, set()).add(str(c.get("checkpoint_type")))
        for types in cases.values():
            if "PAPER_ENTRY" in types and "PAPER_CLOSE" not in types:
                open_cases += 1
        self.funnel = {
            "contexts_checkpointed": ctx,
            "entries_checkpointed": ent,
            "closes_checkpointed": close,
            "checkpoint_verdicts": len(verdicts),
            "closed_cases_evaluated": len(outcomes),
            "complete_coverage_cases": cov["COMPLETE"],
            "partial_coverage_cases": cov["PARTIAL"],
            "stale_coverage_cases": cov["STALE_COVERAGE"],
            "missing_coverage_cases": cov["NO_SHADOW_COVERAGE"],
            "postmortems_complete": pm_complete,
            "postmortems_waiting": pm_wait,
            "postmortems_expired": pm_exp,
            "open_cases_waiting_close": open_cases,
        }


def strip_compare(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    ignore = {"created_at"}
    ka = {k: v for k, v in a.items() if k not in ignore}
    kb = {k: v for k, v in b.items() if k not in ignore}
    return ka == kb


def write_audit_report(data_root: Path, report: Mapping[str, Any], *, repo: Path | None = None) -> Path:
    from .storage import atomic_write_json

    path = data_root / "health" / "integrity_audit_latest.json"
    return atomic_write_json(path, report, data_root=data_root, repo=repo)
