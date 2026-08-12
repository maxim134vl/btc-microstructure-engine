"""AES4 Canonical Checkpoint Linker — historical as-of Shadow freeze.

Reads AES2/AES3 memory histories and canonical lifecycle journals.
Never mutates AES2 engines, AES3 hierarchy, or canonical/paper processes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .canonical_lifecycle import CanonicalLifecycleEvent
from .hierarchy_states import default_aes3_params, merge_aes3_params


TF_ORDER = ("M15", "M30", "H1", "H4")

CHECKPOINT_CONTEXT_START = "CONTEXT_START"
CHECKPOINT_CONTEXT_END = "CONTEXT_END"
CHECKPOINT_PAPER_ENTRY = "PAPER_ENTRY"
CHECKPOINT_PAPER_CLOSE = "PAPER_CLOSE"

COV_COMPLETE = "COMPLETE"
COV_PARTIAL = "PARTIAL"
COV_NO_SHADOW = "NO_SHADOW_COVERAGE"
COV_STALE = "STALE_COVERAGE"

TF_AVAILABLE = "AVAILABLE"
TF_MISSING = "MISSING"
TF_STALE = "STALE"


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


def _age_sec(canonical_ts: str, state_ts: str | None) -> float | None:
    a = _parse_ts(canonical_ts)
    b = _parse_ts(state_ts)
    if a is None or b is None:
        return None
    return max(0.0, (a - b).total_seconds())


def deterministic_checkpoint_id(event: CanonicalLifecycleEvent) -> str:
    raw = "|".join(
        [
            event.checkpoint_type,
            event.canonical_event_id,
            event.position_id or "",
            event.trade_id or "",
            event.canonical_context_episode_id or "",
        ]
    )
    return "CKP_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def deterministic_shadow_case_id(event: CanonicalLifecycleEvent) -> str:
    # Prefer position/trade so multi-trade contexts stay distinct.
    anchor = event.position_id or event.trade_id or event.canonical_event_id
    raw = f"{event.canonical_context_episode_id or ''}|{anchor}"
    return "CASE_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def compact_tf_snapshot(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    keys = (
        "timeframe",
        "shadow_episode_id",
        "auction_family",
        "episode_phase",
        "pressure_side",
        "resolution_side",
        "directional_efficiency",
        "efficiency_trend",
        "balance_state",
        "balance_low",
        "balance_high",
        "balance_age",
        "up_continuation_support",
        "down_continuation_support",
        "up_exhaustion_support",
        "down_exhaustion_support",
        "balance_support",
        "up_resolution_support",
        "down_resolution_support",
        "timestamp",
        "source_event_id",
        "logic_version",
        "logic_fingerprint",
    )
    out = {k: row.get(k) for k in keys}
    out["shadow_state_timestamp"] = row.get("timestamp")
    return out


def compact_hierarchy_snapshot(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "hierarchy_state": row.get("hierarchy_state"),
        "m15_m30_relation": row.get("m15_m30_relation"),
        "m30_h1_relation": row.get("m30_h1_relation"),
        "h1_h4_relation": row.get("h1_h4_relation"),
        "propagation_direction": row.get("propagation_direction"),
        "propagation_depth": row.get("propagation_depth"),
        "local_vs_structural_state": row.get("local_vs_structural_state"),
        "conflict_state": row.get("conflict_state"),
        "hierarchy_timestamp": row.get("timestamp"),
        "hierarchy_logic_version": row.get("logic_version"),
        "hierarchy_logic_fingerprint": row.get("logic_fingerprint"),
        "snapshot_id": row.get("snapshot_id"),
    }


@dataclass
class ShadowHistoryIndex:
    """Bounded chronological index for as-of lookups. Does not mutate sources."""

    tf_rows: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {tf: [] for tf in TF_ORDER})
    hierarchy_rows: list[dict[str, Any]] = field(default_factory=list)
    max_rows_per_tf: int = 5000
    max_hierarchy_rows: int = 5000

    def ingest_tf_row(self, row: Mapping[str, Any]) -> None:
        tf = str(row.get("timeframe") or "").upper()
        if tf not in self.tf_rows:
            return
        ts = _parse_ts(row.get("timestamp") or row.get("source_timestamp"))
        if ts is None:
            return
        payload = dict(row)
        self.tf_rows[tf].append(payload)
        self.tf_rows[tf].sort(key=lambda r: str(r.get("timestamp") or ""))
        if len(self.tf_rows[tf]) > self.max_rows_per_tf:
            self.tf_rows[tf] = self.tf_rows[tf][-self.max_rows_per_tf :]

    def ingest_hierarchy_row(self, row: Mapping[str, Any]) -> None:
        if _parse_ts(row.get("timestamp")) is None:
            return
        self.hierarchy_rows.append(dict(row))
        self.hierarchy_rows.sort(key=lambda r: str(r.get("timestamp") or ""))
        if len(self.hierarchy_rows) > self.max_hierarchy_rows:
            self.hierarchy_rows = self.hierarchy_rows[-self.max_hierarchy_rows :]

    def load_from_store_files(
        self,
        *,
        episode_path: Path | None,
        hierarchy_path: Path | None,
    ) -> None:
        if episode_path and episode_path.exists():
            with episode_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        self.ingest_tf_row(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        if hierarchy_path and hierarchy_path.exists():
            with hierarchy_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        self.ingest_hierarchy_row(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    def asof_tf(self, timeframe: str, canonical_ts: str) -> dict[str, Any] | None:
        """Latest TF row with timestamp <= canonical_ts. Never future."""
        tf = timeframe.upper()
        cutoff = _parse_ts(canonical_ts)
        if cutoff is None:
            return None
        best: dict[str, Any] | None = None
        for row in self.tf_rows.get(tf, []):
            rts = _parse_ts(row.get("timestamp") or row.get("source_timestamp"))
            if rts is None:
                continue
            if rts <= cutoff:
                best = row
            else:
                break
        return best

    def asof_hierarchy(self, canonical_ts: str) -> dict[str, Any] | None:
        cutoff = _parse_ts(canonical_ts)
        if cutoff is None:
            return None
        best: dict[str, Any] | None = None
        for row in self.hierarchy_rows:
            rts = _parse_ts(row.get("timestamp"))
            if rts is None:
                continue
            if rts <= cutoff:
                best = row
            else:
                break
        return best


@dataclass
class CheckpointResult:
    written: bool
    duplicate: bool
    payload_conflict: bool
    checkpoint: dict[str, Any] | None
    reason_codes: list[str] = field(default_factory=list)


@dataclass
class CheckpointLinker:
    """Builds immutable canonical↔Shadow checkpoints via historical as-of lookup."""

    index: ShadowHistoryIndex
    logic_version: str = "AES_V1"
    logic_fingerprint: str = ""
    shadow_name: str = "AUCTION_EPISODE_SHADOW"
    params: dict[str, Any] = field(default_factory=dict)
    _seen: dict[str, str] = field(default_factory=dict)  # checkpoint_id -> payload hash
    _entry_seen: set[str] = field(default_factory=set)  # position_ids with entry checkpoint
    open_cases: dict[str, str] = field(default_factory=dict)  # case_id -> last checkpoint_id

    # Counters for health
    canonical_events_seen: int = 0
    context_start_checkpoints: int = 0
    context_end_checkpoints: int = 0
    paper_entry_checkpoints: int = 0
    paper_close_checkpoints: int = 0
    complete_coverage_checkpoints: int = 0
    partial_coverage_checkpoints: int = 0
    missing_coverage_checkpoints: int = 0
    stale_coverage_checkpoints: int = 0
    duplicate_checkpoints_suppressed: int = 0
    checkpoint_payload_conflicts: int = 0
    out_of_order_canonical_events: int = 0
    last_canonical_event_id: str | None = None
    last_canonical_event_timestamp: str | None = None
    last_checkpoint_id: str | None = None
    last_checkpoint_timestamp: str | None = None

    def __post_init__(self) -> None:
        if not self.params:
            self.params = merge_aes3_params({"aes3": default_aes3_params()})

    @classmethod
    def from_shadow_root(
        cls,
        data_root: Path,
        *,
        logic_version: str = "AES_V1",
        logic_fingerprint: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> "CheckpointLinker":
        idx = ShadowHistoryIndex()
        idx.load_from_store_files(
            episode_path=data_root / "memory" / "tf_episode_memory.jsonl",
            hierarchy_path=data_root / "memory" / "hierarchy_memory.jsonl",
        )
        return cls(
            index=idx,
            logic_version=logic_version,
            logic_fingerprint=logic_fingerprint,
            params=merge_aes3_params({"aes3": dict(params or {})}),
        )

    def _stale(self, tf: str, age: float | None) -> bool:
        if age is None:
            return False
        cadence = float(self.params.get("stale_cadence_sec", {}).get(tf, 3600))
        mult = float(self.params.get("stale_multiplier") or 2.0)
        return age > cadence * mult

    def build_checkpoint(self, event: CanonicalLifecycleEvent) -> CheckpointResult:
        self.canonical_events_seen += 1
        self.last_canonical_event_id = event.canonical_event_id
        self.last_canonical_event_timestamp = event.canonical_timestamp

        ckp_id = deterministic_checkpoint_id(event)
        case_id = deterministic_shadow_case_id(event)
        reasons: list[str] = []

        if event.checkpoint_type == CHECKPOINT_CONTEXT_START:
            reasons.append("CHECKPOINT_CONTEXT_START")
        elif event.checkpoint_type == CHECKPOINT_CONTEXT_END:
            reasons.append("CHECKPOINT_CONTEXT_END")
        elif event.checkpoint_type == CHECKPOINT_PAPER_ENTRY:
            reasons.append("CHECKPOINT_PAPER_ENTRY")
        elif event.checkpoint_type == CHECKPOINT_PAPER_CLOSE:
            reasons.append("CHECKPOINT_PAPER_CLOSE")

        if event.linkage_method == "EXACT_ID":
            reasons.append("EXACT_CANONICAL_LINK")
        else:
            reasons.append("DERIVED_CANONICAL_LINK")
            if event.linkage_reason:
                reasons.append(event.linkage_reason)

        if event.checkpoint_type == CHECKPOINT_PAPER_CLOSE and event.position_id:
            if event.position_id not in self._entry_seen:
                reasons.append("MISSING_PRIOR_ENTRY_CHECKPOINT")
                self.out_of_order_canonical_events += 1
                reasons.append("CANONICAL_EVENT_OUT_OF_ORDER")

        tf_snaps: dict[str, dict[str, Any] | None] = {}
        tf_cov: dict[str, str] = {}
        ages: dict[str, float | None] = {}
        snap_ids: dict[str, str | None] = {}

        for tf in TF_ORDER:
            row = self.index.asof_tf(tf, event.canonical_timestamp)
            # Hard no-lookahead assert
            if row is not None:
                rts = _parse_ts(row.get("timestamp"))
                cts = _parse_ts(event.canonical_timestamp)
                if rts is not None and cts is not None and rts > cts:
                    raise RuntimeError("AES4 lookahead violation in TF as-of")
            snap = compact_tf_snapshot(row)
            age = _age_sec(event.canonical_timestamp, None if row is None else str(row.get("timestamp")))
            ages[tf.lower()] = age
            if row is None:
                tf_cov[tf.lower()] = TF_MISSING
                reasons.append("SHADOW_STATE_MISSING")
                snap_ids[tf.lower()] = None
            elif self._stale(tf, age):
                tf_cov[tf.lower()] = TF_STALE
                reasons.append("SHADOW_STATE_STALE")
                snap_ids[tf.lower()] = (
                    f"{tf}|{row.get('timestamp')}|{row.get('shadow_episode_id')}|{row.get('episode_phase')}"
                )
            else:
                tf_cov[tf.lower()] = TF_AVAILABLE
                snap_ids[tf.lower()] = (
                    f"{tf}|{row.get('timestamp')}|{row.get('shadow_episode_id')}|{row.get('episode_phase')}"
                )
            tf_snaps[tf.lower()] = snap

        hier_row = self.index.asof_hierarchy(event.canonical_timestamp)
        if hier_row is not None:
            rts = _parse_ts(hier_row.get("timestamp"))
            cts = _parse_ts(event.canonical_timestamp)
            if rts is not None and cts is not None and rts > cts:
                raise RuntimeError("AES4 lookahead violation in hierarchy as-of")
        hier_snap = compact_hierarchy_snapshot(hier_row)
        hier_age = _age_sec(
            event.canonical_timestamp,
            None if hier_row is None else str(hier_row.get("timestamp")),
        )
        if hier_row is None:
            hier_cov = TF_MISSING
            reasons.append("HIERARCHY_STATE_MISSING")
            hier_id = None
        elif self._stale("H1", hier_age):  # hierarchy staleness uses H1 cadence as baseline
            hier_cov = TF_STALE
            reasons.append("HIERARCHY_STATE_STALE")
            hier_id = hier_row.get("snapshot_id")
        else:
            hier_cov = TF_AVAILABLE
            hier_id = hier_row.get("snapshot_id")

        available = sum(1 for v in tf_cov.values() if v == TF_AVAILABLE)
        stale_n = sum(1 for v in tf_cov.values() if v == TF_STALE)
        missing_n = sum(1 for v in tf_cov.values() if v == TF_MISSING)

        if available == 4 and hier_cov == TF_AVAILABLE and stale_n == 0:
            coverage = COV_COMPLETE
            reasons.append("SHADOW_ASOF_COMPLETE")
            self.complete_coverage_checkpoints += 1
        elif available == 0 and missing_n == 4:
            coverage = COV_NO_SHADOW
            reasons.append("SHADOW_ASOF_PARTIAL")
            self.missing_coverage_checkpoints += 1
        elif stale_n > 0 and available + stale_n == 4:
            coverage = COV_STALE
            reasons.append("SHADOW_ASOF_PARTIAL")
            self.stale_coverage_checkpoints += 1
        else:
            coverage = COV_PARTIAL
            reasons.append("SHADOW_ASOF_PARTIAL")
            self.partial_coverage_checkpoints += 1

        payload = {
            "checkpoint_id": ckp_id,
            "checkpoint_type": event.checkpoint_type,
            "shadow_case_id": case_id,
            "canonical_event_id": event.canonical_event_id,
            "canonical_context_episode_id": event.canonical_context_episode_id,
            "trade_id": event.trade_id,
            "position_id": event.position_id,
            "canonical_timeframe": event.canonical_timeframe,
            "canonical_side": event.canonical_side,
            "canonical_timestamp": event.canonical_timestamp,
            "entry_price": event.entry_price,
            "close_price": event.close_price,
            "close_reason": event.close_reason,
            "linkage_method": event.linkage_method,
            "coverage_status": coverage,
            "m15_snapshot": tf_snaps["m15"],
            "m30_snapshot": tf_snaps["m30"],
            "h1_snapshot": tf_snaps["h1"],
            "h4_snapshot": tf_snaps["h4"],
            "hierarchy_snapshot": hier_snap,
            "m15_snapshot_id": snap_ids["m15"],
            "m30_snapshot_id": snap_ids["m30"],
            "h1_snapshot_id": snap_ids["h1"],
            "h4_snapshot_id": snap_ids["h4"],
            "hierarchy_snapshot_id": hier_id,
            "m15_coverage_status": tf_cov["m15"],
            "m30_coverage_status": tf_cov["m30"],
            "h1_coverage_status": tf_cov["h1"],
            "h4_coverage_status": tf_cov["h4"],
            "hierarchy_coverage_status": hier_cov,
            "m15_age_sec": ages["m15"],
            "m30_age_sec": ages["m30"],
            "h1_age_sec": ages["h1"],
            "h4_age_sec": ages["h4"],
            "hierarchy_age_sec": hier_age,
            "reason_codes": sorted(set(reasons)),
            "shadow_name": self.shadow_name,
            "logic_version": self.logic_version,
            "logic_fingerprint": self.logic_fingerprint,
            "source_event_type": event.source_event_type,
            "source_path": event.source_path,
            "created_at": _iso_now(),
        }

        payload_hash = hashlib.sha1(
            json.dumps(
                {k: v for k, v in payload.items() if k != "created_at"},
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        if ckp_id in self._seen:
            if self._seen[ckp_id] == payload_hash:
                self.duplicate_checkpoints_suppressed += 1
                return CheckpointResult(
                    written=False,
                    duplicate=True,
                    payload_conflict=False,
                    checkpoint=payload,
                    reason_codes=sorted(set(reasons + ["DUPLICATE_CHECKPOINT_SUPPRESSED"])),
                )
            self.checkpoint_payload_conflicts += 1
            return CheckpointResult(
                written=False,
                duplicate=False,
                payload_conflict=True,
                checkpoint=payload,
                reason_codes=sorted(set(reasons + ["CHECKPOINT_PAYLOAD_CONFLICT"])),
            )

        self._seen[ckp_id] = payload_hash
        if len(self._seen) > 10000:
            # Bound RAM: keep newest half of keys (dict order is insertion order).
            keys = list(self._seen.keys())[-5000:]
            self._seen = {k: self._seen[k] for k in keys}

        if event.checkpoint_type == CHECKPOINT_PAPER_ENTRY and event.position_id:
            self._entry_seen.add(event.position_id)
        if event.checkpoint_type == CHECKPOINT_CONTEXT_START:
            self.context_start_checkpoints += 1
        elif event.checkpoint_type == CHECKPOINT_CONTEXT_END:
            self.context_end_checkpoints += 1
        elif event.checkpoint_type == CHECKPOINT_PAPER_ENTRY:
            self.paper_entry_checkpoints += 1
        elif event.checkpoint_type == CHECKPOINT_PAPER_CLOSE:
            self.paper_close_checkpoints += 1

        self.open_cases[case_id] = ckp_id
        self.last_checkpoint_id = ckp_id
        self.last_checkpoint_timestamp = event.canonical_timestamp

        return CheckpointResult(
            written=True,
            duplicate=False,
            payload_conflict=False,
            checkpoint=payload,
            reason_codes=payload["reason_codes"],
        )

    def health_fields(self) -> dict[str, Any]:
        return {
            "aes4_enabled": True,
            "canonical_events_seen": self.canonical_events_seen,
            "context_start_checkpoints": self.context_start_checkpoints,
            "context_end_checkpoints": self.context_end_checkpoints,
            "paper_entry_checkpoints": self.paper_entry_checkpoints,
            "paper_close_checkpoints": self.paper_close_checkpoints,
            "complete_coverage_checkpoints": self.complete_coverage_checkpoints,
            "partial_coverage_checkpoints": self.partial_coverage_checkpoints,
            "missing_coverage_checkpoints": self.missing_coverage_checkpoints,
            "stale_coverage_checkpoints": self.stale_coverage_checkpoints,
            "duplicate_checkpoints_suppressed": self.duplicate_checkpoints_suppressed,
            "checkpoint_payload_conflicts": self.checkpoint_payload_conflicts,
            "out_of_order_canonical_events": self.out_of_order_canonical_events,
            "open_shadow_cases": len(self.open_cases),
            "last_canonical_event_id": self.last_canonical_event_id,
            "last_canonical_event_timestamp": self.last_canonical_event_timestamp,
            "last_checkpoint_id": self.last_checkpoint_id,
            "last_checkpoint_timestamp": self.last_checkpoint_timestamp,
        }

    def restore_dedup_from_memory(self, path: Path) -> int:
        """Rebuild dedup keys from existing checkpoint memory (restart)."""
        if not path.exists():
            return 0
        n = 0
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ckp_id = row.get("checkpoint_id")
                if not ckp_id:
                    continue
                payload_hash = hashlib.sha1(
                    json.dumps(
                        {k: v for k, v in row.items() if k != "created_at"},
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                self._seen[str(ckp_id)] = payload_hash
                if row.get("checkpoint_type") == CHECKPOINT_PAPER_ENTRY and row.get("position_id"):
                    self._entry_seen.add(str(row["position_id"]))
                if row.get("shadow_case_id"):
                    self.open_cases[str(row["shadow_case_id"])] = str(ckp_id)
                n += 1
        return n
