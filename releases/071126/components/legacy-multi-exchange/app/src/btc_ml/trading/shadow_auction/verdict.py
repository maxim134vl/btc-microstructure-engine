"""AES5 checkpoint interpretation — ONLINE-compatible, frozen-snapshot only.

Does not mutate AES4 checkpoints. Verdicts are research labels, not trade commands.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from datetime import datetime, timezone

from .checkpoint import COV_NO_SHADOW, COV_STALE, TF_MISSING, TF_STALE
from .hierarchy_states import (
    HIER_CONFLICTED,
    HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_DOWN,
    HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_UP,
    HIER_LOCAL_DOWN_WITHIN_PARENT_UP,
    HIER_LOCAL_ROTATION_WITHIN_PARENT_BALANCE,
    HIER_LOCAL_UP_WITHIN_PARENT_DOWN,
    HIER_MULTI_TF_BALANCE,
    HIER_MULTI_TF_EXHAUSTION,
    HIER_MULTI_TF_RESOLUTION_DOWN,
    HIER_MULTI_TF_RESOLUTION_UP,
    HIER_STRUCTURAL_DOWN_ALIGNED,
    HIER_STRUCTURAL_UP_ALIGNED,
    HIER_TRANSITION_PROPAGATING_TO_HIGHER_TF,
)
from .states import (
    FAMILY_BALANCE,
    FAMILY_DIRECTIONAL_DOWN,
    FAMILY_DIRECTIONAL_UP,
    FAMILY_TRANSITION,
    FAMILY_UNRESOLVED,
    PHASE_ACCEPTANCE_ABOVE,
    PHASE_ACCEPTANCE_BELOW,
    PHASE_DOWN_CONTINUATION_ACCEPTED,
    PHASE_DOWN_CONTINUATION_DETERIORATING,
    PHASE_DOWN_PRESSURE_ACTIVE,
    PHASE_DOWN_PRESSURE_EXPANDING,
    PHASE_DOWN_STOPPING_CANDIDATE,
    PHASE_EXTREME_DOWN_PARTICIPATION,
    PHASE_EXTREME_UP_PARTICIPATION,
    PHASE_POST_DOWN_STRESS_REACTION,
    PHASE_POST_UP_STRESS_REACTION,
    PHASE_RESOLUTION_DOWN,
    PHASE_RESOLUTION_UP,
    PHASE_TRANSITION,
    PHASE_UP_CONTINUATION_ACCEPTED,
    PHASE_UP_CONTINUATION_DETERIORATING,
    PHASE_UP_PRESSURE_ACTIVE,
    PHASE_UP_PRESSURE_EXPANDING,
    PHASE_UP_STOPPING_CANDIDATE,
)

VERDICT_SUPPORT = "SUPPORT"
VERDICT_WAIT = "WAIT"
VERDICT_REJECT = "REJECT"
VERDICT_OPPOSITE = "OPPOSITE"
VERDICT_UNRESOLVED = "UNRESOLVED"

CONFIRMED_UP = frozenset(
    {
        PHASE_RESOLUTION_UP,
        PHASE_ACCEPTANCE_ABOVE,
        PHASE_UP_CONTINUATION_ACCEPTED,
        PHASE_UP_PRESSURE_EXPANDING,
        PHASE_EXTREME_UP_PARTICIPATION,
        PHASE_UP_PRESSURE_ACTIVE,
    }
)
CONFIRMED_DOWN = frozenset(
    {
        PHASE_RESOLUTION_DOWN,
        PHASE_ACCEPTANCE_BELOW,
        PHASE_DOWN_CONTINUATION_ACCEPTED,
        PHASE_DOWN_PRESSURE_EXPANDING,
        PHASE_EXTREME_DOWN_PARTICIPATION,
        PHASE_DOWN_PRESSURE_ACTIVE,
    }
)
RESOLUTION_UP = frozenset({PHASE_RESOLUTION_UP, PHASE_ACCEPTANCE_ABOVE})
RESOLUTION_DOWN = frozenset({PHASE_RESOLUTION_DOWN, PHASE_ACCEPTANCE_BELOW})
WAIT_PHASES = frozenset(
    {
        PHASE_TRANSITION,
        PHASE_UP_CONTINUATION_DETERIORATING,
        PHASE_DOWN_CONTINUATION_DETERIORATING,
        PHASE_UP_STOPPING_CANDIDATE,
        PHASE_DOWN_STOPPING_CANDIDATE,
        PHASE_POST_UP_STRESS_REACTION,
        PHASE_POST_DOWN_STRESS_REACTION,
    }
)
HIER_WAIT = frozenset(
    {
        HIER_CONFLICTED,
        HIER_TRANSITION_PROPAGATING_TO_HIGHER_TF,
        HIER_LOCAL_ROTATION_WITHIN_PARENT_BALANCE,
        HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_UP,
        HIER_LOCAL_BALANCE_WITHIN_STRUCTURAL_DOWN,
        HIER_LOCAL_UP_WITHIN_PARENT_DOWN,
        HIER_LOCAL_DOWN_WITHIN_PARENT_UP,
        HIER_MULTI_TF_BALANCE,
        HIER_MULTI_TF_EXHAUSTION,
    }
)
HIER_STRUCTURAL_UP = frozenset(
    {HIER_STRUCTURAL_UP_ALIGNED, HIER_MULTI_TF_RESOLUTION_UP}
)
HIER_STRUCTURAL_DOWN = frozenset(
    {HIER_STRUCTURAL_DOWN_ALIGNED, HIER_MULTI_TF_RESOLUTION_DOWN}
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def deterministic_verdict_id(checkpoint_id: str) -> str:
    return "VRD_" + hashlib.sha1(f"AES5|{checkpoint_id}".encode("utf-8")).hexdigest()[:20]


def _anchor_snapshot(checkpoint: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
    tf = str(checkpoint.get("canonical_timeframe") or "M15").upper()
    key = f"{tf.lower()}_snapshot"
    snap = checkpoint.get(key)
    if isinstance(snap, dict):
        return tf, snap
    return tf, None


def interpret_state(
    *,
    canonical_side: str | None,
    family: str | None,
    phase: str | None,
    hierarchy_state: str | None,
    coverage_status: str | None,
    anchor_coverage: str | None,
) -> tuple[str, list[str]]:
    """Deterministic SUPPORT/WAIT/REJECT/OPPOSITE/UNRESOLVED from frozen parts."""
    reasons: list[str] = []
    side = (canonical_side or "").upper()
    fam = family or FAMILY_UNRESOLVED
    ph = phase or "UNRESOLVED"
    hier = hierarchy_state or ""

    if coverage_status in {COV_NO_SHADOW, "MISSING"} or anchor_coverage == TF_MISSING:
        reasons.append("SHADOW_STATE_MISSING")
        return VERDICT_UNRESOLVED, reasons
    if coverage_status == COV_STALE or anchor_coverage == TF_STALE:
        reasons.append("SHADOW_STATE_STALE")
        return VERDICT_UNRESOLVED, reasons
    if side not in {"LONG", "SHORT"}:
        return VERDICT_UNRESOLVED, ["UNRESOLVED_CANONICAL_SIDE"]

    want_up = side == "LONG"
    confirmed_same = ph in (CONFIRMED_UP if want_up else CONFIRMED_DOWN)
    confirmed_opp = ph in (CONFIRMED_DOWN if want_up else CONFIRMED_UP)
    resolved_same = ph in (RESOLUTION_UP if want_up else RESOLUTION_DOWN)
    resolved_opp = ph in (RESOLUTION_DOWN if want_up else RESOLUTION_UP)
    structural_same = hier in (HIER_STRUCTURAL_UP if want_up else HIER_STRUCTURAL_DOWN)
    structural_opp = hier in (HIER_STRUCTURAL_DOWN if want_up else HIER_STRUCTURAL_UP)

    # WAIT: unfinished structure / conflict / local vs parent (before SUPPORT/REJECT).
    if fam in {FAMILY_BALANCE, FAMILY_TRANSITION} or ph == PHASE_TRANSITION or ph in WAIT_PHASES:
        if fam == FAMILY_BALANCE:
            reasons.append("ANCHOR_BALANCE")
        else:
            reasons.append("ANCHOR_TRANSITION")
        return VERDICT_WAIT, reasons
    if hier in HIER_WAIT:
        if hier in {HIER_LOCAL_UP_WITHIN_PARENT_DOWN, HIER_LOCAL_DOWN_WITHIN_PARENT_UP}:
            reasons.append("LOCAL_RESOLUTION_AGAINST_PARENT")
        elif hier == HIER_CONFLICTED:
            reasons.append("STRUCTURAL_PARENT_CONFLICT")
        else:
            reasons.append("ANCHOR_TRANSITION")
        return VERDICT_WAIT, reasons

    # OPPOSITE: confirmed opposite resolution + structural hierarchy (not local-only).
    if resolved_opp and structural_opp:
        reasons += ["ANCHOR_OPPOSES_CANONICAL", "STRUCTURAL_PARENT_CONFLICT"]
        return VERDICT_OPPOSITE, reasons

    # REJECT: opposite directional continuation / resolution without structural confirmation.
    if confirmed_opp:
        reasons.append("ANCHOR_OPPOSES_CANONICAL")
        if structural_opp:
            reasons.append("STRUCTURAL_PARENT_CONFLICT")
        return VERDICT_REJECT, reasons

    # SUPPORT: same-side continuation/resolution without proven structural opposite.
    if confirmed_same and not structural_opp:
        reasons.append("ANCHOR_SUPPORTS_CANONICAL")
        if structural_same:
            reasons.append("STRUCTURAL_PARENT_SUPPORT")
        return VERDICT_SUPPORT, reasons

    if fam == FAMILY_UNRESOLVED:
        return VERDICT_UNRESOLVED, ["UNRESOLVED_ANCHOR"]
    reasons.append("ANCHOR_TRANSITION")
    return VERDICT_WAIT, reasons


def interpret_checkpoint(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a frozen AES4 checkpoint. Never writes back into the checkpoint."""
    tf, snap = _anchor_snapshot(checkpoint)
    family = None if snap is None else snap.get("auction_family")
    phase = None if snap is None else snap.get("episode_phase")
    hier = (checkpoint.get("hierarchy_snapshot") or {}) if isinstance(
        checkpoint.get("hierarchy_snapshot"), dict
    ) else {}
    hier_state = hier.get("hierarchy_state") if hier else None
    lvs = hier.get("local_vs_structural_state") if hier else None
    anchor_cov = checkpoint.get(f"{tf.lower()}_coverage_status")
    if snap is None and not anchor_cov:
        anchor_cov = TF_MISSING
    verdict, reasons = interpret_state(
        canonical_side=checkpoint.get("canonical_side"),
        family=family,
        phase=phase,
        hierarchy_state=hier_state,
        coverage_status=checkpoint.get("coverage_status"),
        anchor_coverage=anchor_cov,
    )
    ckp_id = str(checkpoint.get("checkpoint_id") or "")
    return {
        "verdict_id": deterministic_verdict_id(ckp_id),
        "checkpoint_id": ckp_id,
        "shadow_case_id": checkpoint.get("shadow_case_id"),
        "checkpoint_type": checkpoint.get("checkpoint_type"),
        "canonical_side": checkpoint.get("canonical_side"),
        "canonical_timeframe": tf,
        "canonical_timestamp": checkpoint.get("canonical_timestamp"),
        "checkpoint_verdict": verdict,
        "anchor_tf": tf,
        "anchor_family": family,
        "anchor_phase": phase,
        "hierarchy_state": hier_state,
        "local_vs_structural_state": lvs,
        "reason_codes": list(reasons),
        "coverage_status": checkpoint.get("coverage_status"),
        "logic_version": checkpoint.get("logic_version"),
        "logic_fingerprint": checkpoint.get("logic_fingerprint"),
        "created_at": _iso_now(),
    }


@dataclass
class VerdictEngine:
    """Incremental checkpoint-verdict writer with deterministic dedup."""

    logic_version: str = "AES_V1"
    logic_fingerprint: str = ""
    _seen: dict[str, str] = field(default_factory=dict)
    verdicts_written: int = 0
    support_verdicts: int = 0
    wait_verdicts: int = 0
    reject_verdicts: int = 0
    opposite_verdicts: int = 0
    unresolved_verdicts: int = 0
    duplicate_suppressed: int = 0
    payload_conflicts: int = 0
    lookahead_violations: int = 0
    last_verdict_id: str | None = None

    def interpret(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        row = interpret_checkpoint(checkpoint)
        row["logic_version"] = self.logic_version or row.get("logic_version")
        row["logic_fingerprint"] = self.logic_fingerprint or row.get("logic_fingerprint")
        snap_ts = row.get("canonical_timestamp")
        frozen_ts = None
        snap = checkpoint.get(f"{str(row.get('anchor_tf') or 'M15').lower()}_snapshot")
        if isinstance(snap, dict):
            frozen_ts = snap.get("shadow_state_timestamp") or snap.get("timestamp")
        if snap_ts and frozen_ts:
            try:
                a = datetime.fromisoformat(str(snap_ts).replace("Z", "+00:00"))
                b = datetime.fromisoformat(str(frozen_ts).replace("Z", "+00:00"))
                if b > a:
                    self.lookahead_violations += 1
                    row["checkpoint_verdict"] = VERDICT_UNRESOLVED
                    row.setdefault("reason_codes", []).append("AES5_LOOKAHEAD_BLOCKED")
            except ValueError:
                pass
        return row

    def ingest(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        row = self.interpret(checkpoint)
        vid = row["verdict_id"]
        payload_hash = hashlib.sha1(
            json.dumps({k: v for k, v in row.items() if k != "created_at"}, sort_keys=True, default=str).encode()
        ).hexdigest()
        if vid in self._seen:
            if self._seen[vid] == payload_hash:
                self.duplicate_suppressed += 1
                return {"written": False, "duplicate": True, "payload_conflict": False, "record": row}
            self.payload_conflicts += 1
            return {"written": False, "duplicate": False, "payload_conflict": True, "record": row}
        self._seen[vid] = payload_hash
        if len(self._seen) > 10000:
            keys = list(self._seen.keys())[-5000:]
            self._seen = {k: self._seen[k] for k in keys}
        self.verdicts_written += 1
        v = row["checkpoint_verdict"]
        if v == VERDICT_SUPPORT:
            self.support_verdicts += 1
        elif v == VERDICT_WAIT:
            self.wait_verdicts += 1
        elif v == VERDICT_REJECT:
            self.reject_verdicts += 1
        elif v == VERDICT_OPPOSITE:
            self.opposite_verdicts += 1
        else:
            self.unresolved_verdicts += 1
        self.last_verdict_id = vid
        return {"written": True, "duplicate": False, "payload_conflict": False, "record": row}

    def health_fields(self) -> dict[str, Any]:
        return {
            "checkpoint_verdicts_written": self.verdicts_written,
            "support_verdicts": self.support_verdicts,
            "wait_verdicts": self.wait_verdicts,
            "reject_verdicts": self.reject_verdicts,
            "opposite_verdicts": self.opposite_verdicts,
            "unresolved_verdicts": self.unresolved_verdicts,
            "aes5_duplicate_suppressed": self.duplicate_suppressed,
            "aes5_payload_conflicts": self.payload_conflicts,
            "aes5_lookahead_violations": self.lookahead_violations,
            "last_verdict_id": self.last_verdict_id,
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
                vid = row.get("verdict_id")
                if not vid:
                    continue
                self._seen[str(vid)] = hashlib.sha1(
                    json.dumps({k: v for k, v in row.items() if k != "created_at"}, sort_keys=True, default=str).encode()
                ).hexdigest()
                n += 1
        return n
