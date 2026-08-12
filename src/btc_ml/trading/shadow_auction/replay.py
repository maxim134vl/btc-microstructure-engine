"""AES6A deterministic replay — isolated from live Shadow memory.

Uses the same AES2–AES5 business logic as live. Writes only under
``{data_root}/replay/<replay_run_id>/``. Never touches live memory JSONL.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical_lifecycle import CanonicalLifecycleEvent, iter_lifecycle_events
from .checkpoint import CheckpointLinker, ShadowHistoryIndex
from .contract import build_contract, load_config
from .engine import ShadowAuctionAES2
from .evaluation import Aes5Evaluator
from .features import merge_aes2_params
from .hierarchy import HierarchyEngine, TfStateView
from .hierarchy_states import merge_aes3_params
from .memory import (
    Aes2MemoryWriter,
    Aes3HierarchyMemoryWriter,
    Aes4CheckpointMemoryWriter,
    Aes5MemoryWriter,
)
from .observation import BarObservation
from .paths import assert_shadow_write_path
from .source_adapter import TF_MINUTES, _floor_bucket, aggregate_htf, load_m15_observations
from .storage import ShadowAuctionStore, atomic_write_json, validate_external_storage

REFUSE_UNBOUNDED = "REFUSE_UNBOUNDED_REPLAY"

TECHNICAL_IGNORE = frozenset({"created_at", "pid", "process_started_at", "updated_at", "rss_memory_mb"})


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


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_now() -> str:
    return _iso(datetime.now(timezone.utc))


def config_fingerprint(config: Mapping[str, Any]) -> str:
    payload = {k: config[k] for k in sorted(config) if k not in {"pid_file"}}
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def make_replay_run_id(
    *,
    evaluation_from: str,
    evaluation_to: str,
    warmup_from: str,
    logic_fingerprint: str,
    config_fp: str,
    started_at: str | None = None,
) -> str:
    core = hashlib.sha1(
        f"{evaluation_from}|{evaluation_to}|{warmup_from}|{logic_fingerprint}|{config_fp}".encode()
    ).hexdigest()[:16]
    stamp = (started_at or _iso_now()).replace(":", "").replace("-", "")[:15]
    return f"RPL_{core}_{stamp}"


def strip_technical(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in TECHNICAL_IGNORE}


def compare_logical_rows(
    live_rows: Sequence[Mapping[str, Any]],
    replay_rows: Sequence[Mapping[str, Any]],
    *,
    key_fields: Sequence[str],
) -> dict[str, Any]:
    live_map = {
        tuple(str(r.get(k)) for k in key_fields): strip_technical(r) for r in live_rows
    }
    replay_map = {
        tuple(str(r.get(k)) for k in key_fields): strip_technical(r) for r in replay_rows
    }
    keys = sorted(set(live_map) | set(replay_map))
    mismatches = 0
    details: list[dict[str, Any]] = []
    compared = 0
    for key in keys:
        a = live_map.get(key)
        b = replay_map.get(key)
        if a is None or b is None:
            mismatches += 1
            details.append({"key": key, "reason": "MISSING_SIDE"})
            continue
        compared += 1
        # Compare shared logical keys only.
        shared = set(a) & set(b)
        for field in sorted(shared):
            if a.get(field) != b.get(field):
                mismatches += 1
                details.append({"key": key, "field": field, "live": a.get(field), "replay": b.get(field)})
                break
    return {
        "compared": compared,
        "mismatches": mismatches,
        "live_count": len(live_rows),
        "replay_count": len(replay_rows),
        "details": details[:50],
    }


@dataclass
class ReplayManifest:
    replay_run_id: str
    requested_from: str
    requested_to: str
    warmup_from: str
    evaluation_from: str
    evaluation_to: str
    source_files: list[str]
    source_watermarks: dict[str, Any]
    shadow_name: str
    aes2_logic_version: str
    aes3_logic_version: str
    aes4_logic_version: str
    aes5_logic_version: str
    logic_fingerprint: str
    config_fingerprint: str
    schema_version: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ReplayRunner:
    """Event-time replay of AES2→AES5 into an isolated replay store."""

    repo: Path
    live_data_root: Path
    replay_root: Path
    manifest: ReplayManifest
    store: ShadowAuctionStore
    aes2: ShadowAuctionAES2
    hierarchy: HierarchyEngine
    linker: CheckpointLinker
    aes5: Aes5Evaluator
    memory: Aes2MemoryWriter
    hierarchy_memory: Aes3HierarchyMemoryWriter
    checkpoint_memory: Aes4CheckpointMemoryWriter
    aes5_memory: Aes5MemoryWriter
    evaluation_records: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "tf_episode": [],
            "hierarchy": [],
            "checkpoint": [],
            "verdict": [],
            "outcome": [],
            "postmortem": [],
        }
    )

    @classmethod
    def create(
        cls,
        *,
        repo: Path,
        config_path: Path | None = None,
        evaluation_from: str | None = None,
        evaluation_to: str | None = None,
        warmup_from: str | None = None,
        observations: Sequence[BarObservation] | None = None,
        lifecycle_events: Sequence[CanonicalLifecycleEvent] | None = None,
    ) -> "ReplayRunner":
        if not evaluation_from or not evaluation_to:
            raise RuntimeError(REFUSE_UNBOUNDED)
        if _parse_ts(evaluation_from) is None or _parse_ts(evaluation_to) is None:
            raise RuntimeError(f"{REFUSE_UNBOUNDED}: invalid evaluation interval")
        if _parse_ts(evaluation_from) > _parse_ts(evaluation_to):  # type: ignore[operator]
            raise RuntimeError(f"{REFUSE_UNBOUNDED}: from > to")

        config = load_config(config_path, repo_root=repo)
        contract = build_contract(config=config)
        live_root = Path(config["data_root"]).expanduser()
        volume = Path(config["required_volume_root"]).expanduser()
        validation = validate_external_storage(
            data_root=live_root,
            volume_root=volume,
            min_free_bytes=int(config.get("min_free_bytes") or 0),
            repo=repo,
        )
        if not validation.ok:
            raise RuntimeError(validation.error or "storage unavailable")

        warmup = warmup_from or evaluation_from
        cfg_fp = config_fingerprint(config)
        created = _iso_now()
        run_id = make_replay_run_id(
            evaluation_from=evaluation_from,
            evaluation_to=evaluation_to,
            warmup_from=warmup,
            logic_fingerprint=contract.logic_fingerprint,
            config_fp=cfg_fp,
            started_at=created,
        )
        replay_root = live_root / "replay" / run_id
        assert_shadow_write_path(replay_root, data_root=live_root, repo=repo)
        store = ShadowAuctionStore(
            data_root=replay_root,
            volume_root=volume,
            min_free_bytes=0,
            repo=repo,
        )
        aes2_params = merge_aes2_params(config)
        aes3_params = merge_aes3_params(config)
        aes2 = ShadowAuctionAES2(
            params=aes2_params,
            logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
        )
        hierarchy = HierarchyEngine(
            params=aes3_params,
            logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
        )
        linker = CheckpointLinker(
            index=ShadowHistoryIndex(),
            logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
            params=aes3_params,
        )
        aes5 = Aes5Evaluator(
            logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
            horizon_sec=int((config.get("aes5") or {}).get("horizon_sec") or 1209600),
        )
        aes5.outcomes.index = linker.index
        aes5.postmortems.index = linker.index
        manifest = ReplayManifest(
            replay_run_id=run_id,
            requested_from=evaluation_from,
            requested_to=evaluation_to,
            warmup_from=warmup,
            evaluation_from=evaluation_from,
            evaluation_to=evaluation_to,
            source_files=[],
            source_watermarks={"warmup_from": warmup, "evaluation_to": evaluation_to},
            shadow_name=contract.shadow_name,
            aes2_logic_version=contract.logic_version,
            aes3_logic_version=contract.logic_version,
            aes4_logic_version=contract.logic_version,
            aes5_logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
            config_fingerprint=cfg_fp,
            schema_version=int(contract.schema_version),
            created_at=created,
        )
        runner = cls(
            repo=repo,
            live_data_root=live_root,
            replay_root=replay_root,
            manifest=manifest,
            store=store,
            aes2=aes2,
            hierarchy=hierarchy,
            linker=linker,
            aes5=aes5,
            memory=Aes2MemoryWriter(store),
            hierarchy_memory=Aes3HierarchyMemoryWriter(store),
            checkpoint_memory=Aes4CheckpointMemoryWriter(store),
            aes5_memory=Aes5MemoryWriter(store),
        )
        runner._bootstrap_sources = observations  # type: ignore[attr-defined]
        runner._bootstrap_events = lifecycle_events  # type: ignore[attr-defined]
        return runner

    def write_manifest(self) -> Path:
        path = self.store.data_root / "manifest.json"
        return atomic_write_json(
            path,
            self.manifest.to_dict(),
            data_root=self.store.data_root,
            repo=self.repo,
        )

    def _in_eval(self, ts: str) -> bool:
        t = _parse_ts(ts)
        a = _parse_ts(self.manifest.evaluation_from)
        b = _parse_ts(self.manifest.evaluation_to)
        if t is None or a is None or b is None:
            return False
        return a <= t <= b

    def _process_obs(self, obs: BarObservation) -> None:
        # Hard no-lookahead: refuse any observation beyond evaluation_to.
        limit = _parse_ts(self.manifest.evaluation_to)
        ots = _parse_ts(obs.timestamp)
        if limit is not None and ots is not None and ots > limit:
            return
        result = self.aes2.process(obs)
        write = self.memory.write_transition(obs=obs, result=result)
        if not result.duplicate:
            self.linker.index.ingest_tf_row(result.episode_snapshot)
        eng = self.aes2.engines[obs.timeframe.upper()]
        view = TfStateView(
            timeframe=eng.timeframe,
            timestamp=obs.timestamp,
            shadow_episode_id=eng.state.shadow_episode_id,
            auction_family=eng.state.auction_family,
            episode_phase=eng.state.episode_phase,
            pressure_side=eng.state.pressure_side,
            resolution_side=eng.state.resolution_side,
        )
        snap = self.hierarchy.ingest_tf_state(view)
        self.hierarchy_memory.write_snapshot(snap)
        if not snap.duplicate:
            self.linker.index.ingest_hierarchy_row(snap.to_dict())
        if self._in_eval(obs.timestamp) and write.get("written"):
            self.evaluation_records["tf_episode"].append(dict(result.episode_snapshot))
            if not snap.duplicate:
                self.evaluation_records["hierarchy"].append(snap.to_dict())

    def _process_event(self, event: CanonicalLifecycleEvent) -> None:
        limit = _parse_ts(self.manifest.evaluation_to)
        ets = _parse_ts(event.canonical_timestamp)
        if limit is not None and ets is not None and ets > limit:
            return
        res = self.linker.build_checkpoint(event)
        if res.written and res.checkpoint:
            self.checkpoint_memory.write_checkpoint(res.checkpoint)
            vres = self.aes5.evaluate_checkpoint(res.checkpoint)
            if vres.get("written") and vres.get("record"):
                self.aes5_memory.write_verdict(vres["record"])
                if self._in_eval(event.canonical_timestamp):
                    self.evaluation_records["checkpoint"].append(dict(res.checkpoint))
                    self.evaluation_records["verdict"].append(dict(vres["record"]))

    def run(self) -> dict[str, Any]:
        self.write_manifest()
        warmup = _parse_ts(self.manifest.warmup_from)
        end = _parse_ts(self.manifest.evaluation_to)
        assert warmup is not None and end is not None

        observations: list[BarObservation] = list(getattr(self, "_bootstrap_sources", None) or [])
        events: list[CanonicalLifecycleEvent] = list(getattr(self, "_bootstrap_events", None) or [])
        if not observations:
            # Load M15 then aggregate HTF; filter to warmup→to.
            raw = load_m15_observations(repo=self.repo)
            m15 = [
                o
                for o in raw
                if (t := _parse_ts(o.timestamp)) is not None and warmup <= t <= end
            ]
            self.manifest.source_files = [
                str(self.repo / "data" / "cognition" / "volume_classification_memory.parquet"),
                str(self.repo / "data" / "cognition" / "candle_structure_memory.parquet"),
            ]
            # Emit chronological stream: for each new M15, also emit completed HTF bars.
            seen_htf: set[str] = set()
            for i, bar in enumerate(m15):
                self._process_obs(bar)
                window = m15[: i + 1]
                for tf in ("M30", "H1", "H4"):
                    bars = aggregate_htf(window, tf)
                    if not bars:
                        continue
                    # Prefer completed buckets only.
                    need = {"M30": 2, "H1": 4, "H4": 16}[tf]
                    # Drop last if incomplete relative to window end.
                    last = bars[-1]
                    key = last.source_event_id
                    # Count M15 in last bucket
                    bucket_ts = _parse_ts(last.source_event_id.split("|")[-1])
                    if bucket_ts is not None:
                        count = sum(
                            1
                            for b in window
                            if (pt := _parse_ts(b.timestamp)) is not None
                            and _floor_bucket(pt, TF_MINUTES[tf]) == bucket_ts
                        )
                        completed = bars if count >= need else bars[:-1]
                    else:
                        completed = bars
                    for hb in completed:
                        if hb.source_event_id in seen_htf:
                            continue
                        seen_htf.add(hb.source_event_id)
                        self._process_obs(hb)
            observations = m15
        else:
            for obs in observations:
                ots = _parse_ts(obs.timestamp)
                if ots is None or ots < warmup or ots > end:
                    continue
                self._process_obs(obs)

        if not events:
            events = [
                e
                for e in iter_lifecycle_events(self.repo)
                if (t := _parse_ts(e.canonical_timestamp)) is not None and warmup <= t <= end
            ]
        # Deterministic secondary order: timestamp, checkpoint_type, event_id
        events = sorted(
            events,
            key=lambda e: (e.canonical_timestamp, e.checkpoint_type, e.canonical_event_id),
        )
        for event in events:
            self._process_event(event)

        # AES5 outcomes / postmortems for closed cases inside evaluation window.
        from .evaluation import _group_cases, _load_jsonl

        ckps = _load_jsonl(self.store.data_root / "memory" / "canonical_checkpoint_memory.jsonl")
        for cid, bucket in _group_cases(ckps).items():
            close = bucket.get("close")
            if close is None:
                continue
            if not self._in_eval(str(close.get("canonical_timestamp") or "")):
                continue
            pack = self.aes5.evaluate_case(
                case_id=cid,
                context_ckp=bucket.get("context"),
                entry_ckp=bucket.get("entry"),
                close_ckp=close,
                now_ts=self.manifest.evaluation_to,
            )
            if pack.get("outcome"):
                ores = self.aes5.outcomes.ingest(pack["outcome"])
                if ores.get("written"):
                    self.aes5_memory.write_outcome(ores["record"])
                    self.evaluation_records["outcome"].append(dict(ores["record"]))
            if pack.get("postmortem"):
                # Bound post-mortem future by evaluation_to (no data after --to).
                pm = dict(pack["postmortem"])
                res_ts = pm.get("eventual_resolution_timestamp")
                if res_ts and _parse_ts(str(res_ts)) and _parse_ts(str(res_ts)) > end:
                    pm["eventual_resolution_timestamp"] = None
                    pm["eventual_anchor_resolution"] = "UNRESOLVED"
                    pm["postmortem_status"] = "WAITING_FOR_EPISODE_RESOLUTION"
                pres = self.aes5.postmortems.ingest(pm)
                if pres.get("written"):
                    self.aes5_memory.write_postmortem(pres["record"])
                    self.evaluation_records["postmortem"].append(dict(pres["record"]))

        # Ensure live memory untouched: record live sizes.
        live_paths = [
            self.live_data_root / "memory" / name
            for name in (
                "tf_event_memory.jsonl",
                "tf_episode_memory.jsonl",
                "hierarchy_memory.jsonl",
                "canonical_checkpoint_memory.jsonl",
                "checkpoint_verdict_memory.jsonl",
                "shadow_outcome_memory.jsonl",
                "postmortem_memory.jsonl",
            )
        ]
        live_sizes = {str(p): (p.stat().st_size if p.exists() else 0) for p in live_paths}
        audit = {
            "replay_run_id": self.manifest.replay_run_id,
            "replay_root": str(self.replay_root),
            "live_memory_sizes": live_sizes,
            "counts": {k: len(v) for k, v in self.evaluation_records.items()},
            "observation_count": len(observations),
            "event_count": len(events),
        }
        atomic_write_json(
            self.store.data_root / "audit.json",
            audit,
            data_root=self.store.data_root,
            repo=self.repo,
        )
        health = {
            "status": "REPLAY_COMPLETE",
            "replay_run_id": self.manifest.replay_run_id,
            "logic_fingerprint": self.manifest.logic_fingerprint,
            "updated_at": _iso_now(),
            **audit["counts"],
        }
        atomic_write_json(
            self.store.data_root / "health.json",
            health,
            data_root=self.store.data_root,
            repo=self.repo,
        )
        self.write_manifest()
        return {
            "ok": True,
            "replay_run_id": self.manifest.replay_run_id,
            "replay_root": str(self.replay_root),
            "manifest": self.manifest.to_dict(),
            "audit": audit,
        }


def assert_live_memory_unchanged(
    before: Mapping[str, int],
    after: Mapping[str, int],
) -> None:
    if dict(before) != dict(after):
        raise RuntimeError("REPLAY_WROTE_LIVE_MEMORY")
