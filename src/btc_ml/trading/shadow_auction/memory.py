"""AES2/AES3/AES4 Shadow memories — append-only JSONL under external Shadow root."""

from __future__ import annotations

from typing import Any, Mapping

from .engine import TransitionResult
from .hierarchy import HierarchySnapshot
from .observation import BarObservation
from .storage import ShadowAuctionStore


class Aes2MemoryWriter:
    """Persists compact TF event + episode snapshots. Never writes into the repo."""

    EVENT_REL = "memory/tf_event_memory.jsonl"
    EPISODE_REL = "memory/tf_episode_memory.jsonl"

    def __init__(self, store: ShadowAuctionStore) -> None:
        self.store = store
        self.events_written = 0
        self.transitions_written = 0

    def write_transition(
        self,
        *,
        obs: BarObservation,
        result: TransitionResult,
    ) -> dict[str, Any]:
        if result.duplicate:
            return {"written": False, "reason": "DUPLICATE"}

        event_row = {
            "timestamp": obs.timestamp,
            "timeframe": obs.timeframe.upper(),
            "source_event_id": obs.source_event_id,
            "source_timestamp": obs.timestamp,
            "shadow_episode_id": result.shadow_episode_id,
            "previous_state": result.previous_state,
            "new_state": result.new_state,
            "auction_family": result.auction_family,
            "episode_phase": result.episode_phase,
            "pressure_side": result.episode_snapshot.get("pressure_side"),
            "resolution_side": result.episode_snapshot.get("resolution_side"),
            "reason_codes": list(result.reason_codes),
            "evidence": dict(result.features),
            "logic_version": result.episode_snapshot.get("logic_version"),
            "logic_fingerprint": result.episode_snapshot.get("logic_fingerprint"),
            "transition": bool(result.previous_state != result.new_state),
        }
        self.store.append_jsonl(self.EVENT_REL, event_row)
        self.events_written += 1

        episode_row = dict(result.episode_snapshot)
        self.store.append_jsonl(self.EPISODE_REL, episode_row)

        if result.previous_state != result.new_state:
            self.transitions_written += 1

        return {
            "written": True,
            "event_rel": self.EVENT_REL,
            "episode_rel": self.EPISODE_REL,
            "transition": result.previous_state != result.new_state,
        }


class Aes3HierarchyMemoryWriter:
    """Persists immutable hierarchy snapshots. Never rewrites AES2 memories."""

    HIERARCHY_REL = "memory/hierarchy_memory.jsonl"

    def __init__(self, store: ShadowAuctionStore) -> None:
        self.store = store
        self.snapshots_written = 0

    def write_snapshot(self, snap: HierarchySnapshot) -> dict[str, Any]:
        if snap.duplicate:
            return {"written": False, "reason": "DUPLICATE", "snapshot_id": snap.snapshot_id}
        self.store.append_jsonl(self.HIERARCHY_REL, snap.to_dict())
        self.snapshots_written += 1
        return {
            "written": True,
            "event_rel": self.HIERARCHY_REL,
            "snapshot_id": snap.snapshot_id,
        }


class Aes4CheckpointMemoryWriter:
    """Persists immutable canonical checkpoints. Never rewrites AES2/AES3."""

    CHECKPOINT_REL = "memory/canonical_checkpoint_memory.jsonl"
    WATERMARK_REL = "memory/aes4_watermark.json"

    def __init__(self, store: ShadowAuctionStore) -> None:
        self.store = store
        self.checkpoints_written = 0

    def write_checkpoint(self, row: Mapping[str, Any]) -> dict[str, Any]:
        self.store.append_jsonl(self.CHECKPOINT_REL, row)
        self.checkpoints_written += 1
        return {
            "written": True,
            "event_rel": self.CHECKPOINT_REL,
            "checkpoint_id": row.get("checkpoint_id"),
        }

    def save_watermark(self, payload: Mapping[str, Any]) -> None:
        self.store.write_json(self.WATERMARK_REL, dict(payload))


class Aes5MemoryWriter:
    """Persists AES5 verdict / outcome / post-mortem JSONL. External root only."""

    VERDICT_REL = "memory/checkpoint_verdict_memory.jsonl"
    OUTCOME_REL = "memory/shadow_outcome_memory.jsonl"
    POSTMORTEM_REL = "memory/postmortem_memory.jsonl"

    def __init__(self, store: ShadowAuctionStore) -> None:
        self.store = store
        self.verdicts_written = 0
        self.outcomes_written = 0
        self.postmortems_written = 0

    def write_verdict(self, row: Mapping[str, Any]) -> dict[str, Any]:
        self.store.append_jsonl(self.VERDICT_REL, row)
        self.verdicts_written += 1
        return {"written": True, "event_rel": self.VERDICT_REL, "verdict_id": row.get("verdict_id")}

    def write_outcome(self, row: Mapping[str, Any]) -> dict[str, Any]:
        self.store.append_jsonl(self.OUTCOME_REL, row)
        self.outcomes_written += 1
        return {"written": True, "event_rel": self.OUTCOME_REL, "outcome_id": row.get("outcome_id")}

    def write_postmortem(self, row: Mapping[str, Any]) -> dict[str, Any]:
        self.store.append_jsonl(self.POSTMORTEM_REL, row)
        self.postmortems_written += 1
        return {
            "written": True,
            "event_rel": self.POSTMORTEM_REL,
            "postmortem_id": row.get("postmortem_id"),
        }


def event_record_contract() -> Mapping[str, str]:
    return {
        "timestamp": "str",
        "timeframe": "str",
        "source_event_id": "str",
        "source_timestamp": "str",
        "shadow_episode_id": "str|null",
        "previous_state": "str",
        "new_state": "str",
        "auction_family": "str",
        "episode_phase": "str",
        "pressure_side": "str|null",
        "resolution_side": "str|null",
        "reason_codes": "list[str]",
        "evidence": "dict",
        "logic_version": "str",
        "logic_fingerprint": "str",
    }
