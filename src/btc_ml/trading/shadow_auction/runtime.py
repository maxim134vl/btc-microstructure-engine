"""AES0–AES6 Shadow Auction runtime — observer-only, no canonical coupling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import SHADOW_REFUSED, STORAGE_UNAVAILABLE
from .cache import BoundedCache
from .canonical_lifecycle import iter_lifecycle_events
from .checkpoint import CheckpointLinker
from .contract import ShadowAuctionContract, build_contract, load_config, write_manifest
from .engine import ShadowAuctionAES2
from .evaluation import Aes5Evaluator, _group_cases, _load_jsonl, load_trade_map
from .features import merge_aes2_params
from .health import mark_process_started, write_health
from .hierarchy import HierarchyEngine, TfStateView
from .hierarchy_states import merge_aes3_params
from .memory import (
    Aes2MemoryWriter,
    Aes3HierarchyMemoryWriter,
    Aes4CheckpointMemoryWriter,
    Aes5MemoryWriter,
)
from .observation import BarObservation
from .postmortem import DEFAULT_HORIZON_SEC
from .resources import storage_status
from .source_adapter import iter_new_bars
from .storage import ShadowAuctionStore, validate_external_storage
from .watermark import Watermark


@dataclass
class ShadowAuctionRuntime:
    """Observer-only Shadow Auction process (AES0–AES6)."""

    config: dict[str, Any]
    contract: ShadowAuctionContract
    store: ShadowAuctionStore
    watermark: Watermark
    cache: BoundedCache[str, Any]
    repo: Path
    aes2: ShadowAuctionAES2
    memory: Aes2MemoryWriter
    hierarchy: HierarchyEngine
    hierarchy_memory: Aes3HierarchyMemoryWriter
    checkpoint_linker: CheckpointLinker
    checkpoint_memory: Aes4CheckpointMemoryWriter
    aes5: Aes5Evaluator
    aes5_memory: Aes5MemoryWriter
    last_m15_timestamp: str | None = None
    last_canonical_timestamp: str | None = None
    last_tf_event_timestamp: dict | None = None
    aes2_enabled: bool = True
    aes3_enabled: bool = True
    aes4_enabled: bool = True
    aes5_enabled: bool = True
    process_started_at: str | None = None
    writes_1h: int = 0
    rows_written_1h: int = 0
    write_errors_1h: int = 0
    peak_rss_memory_mb: float | None = None

    @classmethod
    def bootstrap(
        cls,
        *,
        repo: Path | None = None,
        config_path: Path | None = None,
        cache_max_items: int = 256,
        enable_aes2: bool = True,
        enable_aes3: bool = True,
        enable_aes4: bool = True,
        enable_aes5: bool = True,
    ) -> "ShadowAuctionRuntime":
        repo_path = Path(repo) if repo else Path(__file__).resolve().parents[4]
        config = load_config(config_path, repo_root=repo_path)
        contract = build_contract(config=config)

        validation = validate_external_storage(
            data_root=config["data_root"],
            volume_root=config["required_volume_root"],
            min_free_bytes=int(config.get("min_free_bytes") or 0),
            repo=repo_path,
        )
        if not validation.ok:
            raise RuntimeError(validation.error or STORAGE_UNAVAILABLE)

        store = ShadowAuctionStore(
            data_root=validation.data_root,
            volume_root=validation.volume_root,
            min_free_bytes=int(config.get("min_free_bytes") or 0),
            repo=repo_path,
        )
        write_manifest(store.data_root / "manifests" / "contract.json", contract)
        watermark = Watermark(store)
        watermark.save()
        aes2_params = merge_aes2_params(config)
        aes2 = ShadowAuctionAES2(
            params=aes2_params,
            logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
        )
        aes3_params = merge_aes3_params(config)
        hierarchy = HierarchyEngine(
            params=aes3_params,
            logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
        )
        memory = Aes2MemoryWriter(store)
        hierarchy_memory = Aes3HierarchyMemoryWriter(store)
        checkpoint_memory = Aes4CheckpointMemoryWriter(store)
        linker = CheckpointLinker.from_shadow_root(
            store.data_root,
            logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
            params=aes3_params,
        )
        ckp_path = store.data_root / "memory" / "canonical_checkpoint_memory.jsonl"
        linker.restore_dedup_from_memory(ckp_path)
        aes5_cfg = config.get("aes5") if isinstance(config.get("aes5"), dict) else {}
        aes5 = Aes5Evaluator(
            logic_version=contract.logic_version,
            logic_fingerprint=contract.logic_fingerprint,
            horizon_sec=int(aes5_cfg.get("horizon_sec") or DEFAULT_HORIZON_SEC),
        )
        aes5.outcomes.index = linker.index
        aes5.postmortems.index = linker.index
        aes5.restore(store.data_root / "memory")
        aes5_memory = Aes5MemoryWriter(store)
        last_ckp_ts = None
        wm_path = store.data_root / "memory" / "aes4_watermark.json"
        if wm_path.exists():
            try:
                import json

                wm = json.loads(wm_path.read_text(encoding="utf-8"))
                last_ckp_ts = wm.get("last_canonical_timestamp")
            except Exception:
                last_ckp_ts = None

        runtime = cls(
            config=config,
            contract=contract,
            store=store,
            watermark=watermark,
            cache=BoundedCache(max_items=cache_max_items),
            repo=repo_path,
            aes2=aes2,
            memory=memory,
            hierarchy=hierarchy,
            hierarchy_memory=hierarchy_memory,
            checkpoint_linker=linker,
            checkpoint_memory=checkpoint_memory,
            aes5=aes5,
            aes5_memory=aes5_memory,
            last_m15_timestamp=watermark.state.last_m15_timestamp,
            last_canonical_timestamp=last_ckp_ts,
            last_tf_event_timestamp={"M15": None, "M30": None, "H1": None, "H4": None},
            aes2_enabled=bool(enable_aes2 and config.get("aes2_enabled", True)),
            aes3_enabled=bool(enable_aes3 and config.get("aes3_enabled", True)),
            aes4_enabled=bool(enable_aes4 and config.get("aes4_enabled", True)),
            aes5_enabled=bool(enable_aes5 and config.get("aes5_enabled", True)),
            process_started_at=mark_process_started(),
        )
        runtime.write_health(status="RUNNING")
        return runtime

    def _storage_gate(self) -> str | None:
        free = self.store.validation.storage_free_bytes
        aes6 = self.config.get("aes6") if isinstance(self.config.get("aes6"), dict) else {}
        status = storage_status(
            free_bytes=free,
            min_free_bytes=int(self.config.get("min_free_bytes") or 0),
            warning_bytes=aes6.get("storage_warning_bytes"),
            critical_bytes=aes6.get("storage_critical_bytes"),
        )
        if status == "STORAGE_CRITICAL":
            return status
        return None

    def write_health(self, *, status: str = "RUNNING", source_lag_ms: float | None = None) -> Path:
        critical = self._storage_gate()
        if critical:
            status = critical
        extra: dict[str, Any] = {
            "process_started_at": self.process_started_at,
            "writes_1h": self.writes_1h,
            "rows_written_1h": self.rows_written_1h,
            "write_errors_1h": self.write_errors_1h,
        }
        # TF health
        tf_ts = self.last_tf_event_timestamp or {}
        for tf in ("M15", "M30", "H1", "H4"):
            key = tf.lower()
            extra[f"{key}_last_event_timestamp"] = tf_ts.get(tf)
            eng = self.aes2.engines.get(tf)
            if eng is not None:
                extra[f"{key}_episode_id"] = eng.state.shadow_episode_id
                extra[f"{key}_family"] = eng.state.auction_family
                extra[f"{key}_cache_rows"] = len(eng.state.recent_closes)
                extra[f"cache_rows_{key}"] = len(eng.state.recent_closes)
                # After restart engines are cold; surface last persisted AES2 snapshot for ops.
                if eng.state.shadow_episode_id is None:
                    hist = self.checkpoint_linker.index.tf_rows.get(tf) or []
                    if hist:
                        last = hist[-1]
                        extra[f"{key}_family"] = last.get("auction_family") or extra[f"{key}_family"]
                        extra[f"{key}_episode_id"] = last.get("shadow_episode_id") or extra[f"{key}_episode_id"]
                        extra[f"{key}_last_event_timestamp"] = last.get("timestamp") or extra[
                            f"{key}_last_event_timestamp"
                        ]
                        extra[f"{key}_episode_phase"] = last.get("episode_phase")
        if self.hierarchy.last_snapshot is None:
            hier_hist = self.checkpoint_linker.index.hierarchy_rows
            if hier_hist:
                last_h = hier_hist[-1]
                extra.setdefault("hierarchy_state", last_h.get("hierarchy_state"))
                extra.setdefault("last_hierarchy_timestamp", last_h.get("timestamp"))
                extra.setdefault("propagation_depth", last_h.get("propagation_depth"))
                extra.setdefault("propagation_direction", last_h.get("propagation_direction"))
        extra["open_episode_count"] = sum(
            1 for e in self.aes2.engines.values() if e.state.shadow_episode_id is not None
        )
        extra["open_case_count"] = len(self.checkpoint_linker.open_cases)
        if self.aes2_enabled:
            eng = self.aes2.health_fields()
            extra.update(eng)
            extra["aes2_events_written"] = max(
                int(self.memory.events_written), int(eng.get("aes2_events_written") or 0)
            )
            extra["aes2_transitions_written"] = max(
                int(self.memory.transitions_written),
                int(eng.get("aes2_transitions_written") or 0),
            )
        if self.aes3_enabled:
            hier = self.hierarchy.health_fields()
            extra.update(hier)
            extra["hierarchy_snapshots_written"] = max(
                int(self.hierarchy_memory.snapshots_written),
                int(hier.get("hierarchy_snapshots_written") or 0),
            )
        if self.aes4_enabled:
            extra.update(self.checkpoint_linker.health_fields())
            extra["aes4_enabled"] = True
            extra["canonical_checkpoints_written"] = int(self.checkpoint_memory.checkpoints_written)
            extra["checkpoint_count"] = int(self.checkpoint_memory.checkpoints_written)
        else:
            extra["aes4_enabled"] = False
        if self.aes5_enabled:
            extra.update(self.aes5.health_fields())
            extra["aes5_enabled"] = True
            extra["verdict_count"] = int(self.aes5.verdicts.verdicts_written)
            extra["outcome_count"] = int(self.aes5.outcomes.closed_cases_evaluated)
            extra["postmortem_count"] = int(
                self.aes5.postmortems.postmortems_complete
                + self.aes5.postmortems.postmortems_waiting
                + self.aes5.postmortems.postmortems_expired
            )
            extra["postmortems_waiting_resolution"] = int(self.aes5.postmortems.postmortems_waiting)
            # Coverage funnel aliases
            extra["complete_coverage_count"] = int(
                self.checkpoint_linker.complete_coverage_checkpoints
            )
            extra["partial_coverage_count"] = int(self.checkpoint_linker.partial_coverage_checkpoints)
            extra["stale_coverage_count"] = int(self.checkpoint_linker.stale_coverage_checkpoints)
            extra["missing_coverage_count"] = int(self.checkpoint_linker.missing_coverage_checkpoints)
        else:
            extra["aes5_enabled"] = False
        return write_health(
            contract=self.contract,
            store=self.store,
            watermark=self.watermark,
            status=status,
            source_lag_ms=source_lag_ms,
            extra=extra or None,
            config=self.config,
        )

    def ingest_source_event(
        self,
        *,
        source_event_id: str,
        source_timestamp: str | None,
        derived: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        accepted, reason = self.watermark.accept(
            source_event_id=source_event_id,
            source_timestamp=source_timestamp,
        )
        self.watermark.save()
        result = {
            "accepted": accepted,
            "reason": reason,
            "source_event_id": source_event_id,
            "source_timestamp": source_timestamp,
        }
        if not accepted and reason == "DUPLICATE":
            return result
        if accepted:
            row = {
                "source_event_id": source_event_id,
                "source_timestamp": source_timestamp,
                "shadow_name": self.contract.shadow_name,
                "logic_version": self.contract.logic_version,
                "logic_fingerprint": self.contract.logic_fingerprint,
                "ordering_violation": reason == "ORDERING_VIOLATION",
                "derived": dict(derived or {}),
            }
            self.store.append_jsonl("memory/source_ingest.jsonl", row)
            self.cache.set(source_event_id, {"source_timestamp": source_timestamp})
        self.write_health(status="RUNNING")
        return result

    def _run_hierarchy_after_aes2(self, *, timestamp: str, timeframe: str) -> dict[str, Any] | None:
        if not self.aes3_enabled:
            return None
        eng = self.aes2.engines.get(timeframe.upper())
        if eng is None:
            return None
        view = TfStateView(
            timeframe=eng.timeframe,
            timestamp=timestamp,
            shadow_episode_id=eng.state.shadow_episode_id,
            auction_family=eng.state.auction_family,
            episode_phase=eng.state.episode_phase,
            pressure_side=eng.state.pressure_side,
            resolution_side=eng.state.resolution_side,
        )
        snap = self.hierarchy.ingest_tf_state(view)
        write = self.hierarchy_memory.write_snapshot(snap)
        if self.aes4_enabled and not snap.duplicate:
            self.checkpoint_linker.index.ingest_hierarchy_row(snap.to_dict())
        return {
            "hierarchy_state": snap.hierarchy_state,
            "propagation_direction": snap.propagation_direction,
            "propagation_depth": snap.propagation_depth,
            "m15_m30_relation": snap.m15_m30.relation_state,
            "m30_h1_relation": snap.m30_h1.relation_state,
            "h1_h4_relation": snap.h1_h4.relation_state,
            "snapshot_id": snap.snapshot_id,
            "duplicate": snap.duplicate,
            "write": write,
        }

    def process_observation(self, obs: BarObservation) -> dict[str, Any]:
        if not self.aes2_enabled:
            return {"ok": False, "reason": "AES2_DISABLED"}
        # Restart-safe: skip already-consumed source events (AES6 idempotency).
        if self.watermark.already_processed(obs.source_event_id):
            self.watermark.state.duplicates_dropped += 1
            self.watermark.save()
            return {"ok": True, "duplicate": True, "reason": "DUPLICATE", "timeframe": obs.timeframe}
        pre = {
            tf: (e.state.auction_family, e.state.episode_phase, e.state.shadow_episode_id, e.state.episode_age)
            for tf, e in self.aes2.engines.items()
        }
        result = self.aes2.process(obs)
        write = self.memory.write_transition(obs=obs, result=result)
        if write.get("written"):
            self.writes_1h += 1
            self.rows_written_1h += 1 if write.get("event_rel") else 0
        if self.aes4_enabled and not result.duplicate:
            self.checkpoint_linker.index.ingest_tf_row(result.episode_snapshot)
        self.ingest_source_event(
            source_event_id=obs.source_event_id,
            source_timestamp=obs.timestamp,
            derived={
                "aes2": True,
                "timeframe": obs.timeframe,
                "episode_phase": result.episode_phase,
                "auction_family": result.auction_family,
            },
        )
        if self.last_tf_event_timestamp is None:
            self.last_tf_event_timestamp = {"M15": None, "M30": None, "H1": None, "H4": None}
        self.last_tf_event_timestamp[obs.timeframe.upper()] = obs.timestamp
        if obs.timeframe.upper() == "M15":
            self.last_m15_timestamp = obs.timestamp
            self.watermark.state.last_m15_timestamp = obs.timestamp
            self.watermark.save()

        hier = self._run_hierarchy_after_aes2(timestamp=obs.timestamp, timeframe=obs.timeframe)
        post = {
            tf: (e.state.auction_family, e.state.episode_phase, e.state.shadow_episode_id, e.state.episode_age)
            for tf, e in self.aes2.engines.items()
        }
        for tf, before in pre.items():
            if tf == obs.timeframe.upper():
                continue
            if post[tf] != before:
                raise RuntimeError(f"AES3/AES2 immutability violation on {tf}")

        self.write_health(status="RUNNING")
        return {
            "ok": True,
            "duplicate": result.duplicate,
            "timeframe": obs.timeframe,
            "previous_state": result.previous_state,
            "new_state": result.new_state,
            "auction_family": result.auction_family,
            "episode_phase": result.episode_phase,
            "shadow_episode_id": result.shadow_episode_id,
            "reason_codes": list(result.reason_codes),
            "write": write,
            "hierarchy": hier,
        }

    def process_canonical_checkpoints(self, *, backfill: bool = False) -> dict[str, Any]:
        if not self.aes4_enabled:
            return {"ok": True, "checkpoints": 0, "aes4_enabled": False}
        since = None if backfill else self.last_canonical_timestamp
        if not backfill and self.last_canonical_timestamp is None:
            events = iter_lifecycle_events(self.repo)
            if events:
                self.last_canonical_timestamp = events[-1].canonical_timestamp
                self.checkpoint_memory.save_watermark(
                    {
                        "last_canonical_timestamp": self.last_canonical_timestamp,
                        "mode": "cold_start_anchor_no_backfill",
                    }
                )
            self.write_health(status="RUNNING")
            return {
                "ok": True,
                "checkpoints": 0,
                "mode": "cold_start_anchor_no_backfill",
                "anchored_at": self.last_canonical_timestamp,
            }

        written = 0
        duplicates = 0
        conflicts = 0
        results: list[dict[str, Any]] = []
        try:
            events = iter_lifecycle_events(self.repo, since_timestamp=since)
        except Exception as exc:
            self.write_health(status="RUNNING")
            return {"ok": False, "error": str(exc), "canonical_unaffected": True, "checkpoints": 0}

        aes2_fp = {
            tf: (e.state.auction_family, e.state.episode_phase, e.state.shadow_episode_id)
            for tf, e in self.aes2.engines.items()
        }
        aes3_fp = (
            self.hierarchy.last_snapshot.snapshot_id if self.hierarchy.last_snapshot else None,
            self.hierarchy.last_hierarchy_timestamp,
        )

        for event in events:
            try:
                res = self.checkpoint_linker.build_checkpoint(event)
            except Exception as exc:
                self.write_health(status="RUNNING")
                return {
                    "ok": False,
                    "error": str(exc),
                    "canonical_unaffected": True,
                    "checkpoints": written,
                }
            if res.payload_conflict:
                conflicts += 1
                results.append({"payload_conflict": True})
                continue
            if res.duplicate:
                duplicates += 1
                continue
            if res.written and res.checkpoint:
                self.checkpoint_memory.write_checkpoint(res.checkpoint)
                written += 1
                self.last_canonical_timestamp = event.canonical_timestamp
                results.append(
                    {
                        "checkpoint_id": res.checkpoint["checkpoint_id"],
                        "checkpoint_type": event.checkpoint_type,
                        "canonical_timestamp": event.canonical_timestamp,
                        "coverage_status": res.checkpoint.get("coverage_status"),
                    }
                )

        aes2_fp_after = {
            tf: (e.state.auction_family, e.state.episode_phase, e.state.shadow_episode_id)
            for tf, e in self.aes2.engines.items()
        }
        if aes2_fp != aes2_fp_after:
            raise RuntimeError("AES4 mutated AES2 state")
        aes3_fp_after = (
            self.hierarchy.last_snapshot.snapshot_id if self.hierarchy.last_snapshot else None,
            self.hierarchy.last_hierarchy_timestamp,
        )
        if aes3_fp != aes3_fp_after:
            raise RuntimeError("AES4 mutated AES3 state")

        if self.last_canonical_timestamp:
            self.checkpoint_memory.save_watermark(
                {
                    "last_canonical_timestamp": self.last_canonical_timestamp,
                    "last_checkpoint_id": self.checkpoint_linker.last_checkpoint_id,
                }
            )
        self.write_health(status="RUNNING")
        return {
            "ok": True,
            "checkpoints": written,
            "duplicates": duplicates,
            "conflicts": conflicts,
            "results": results,
        }

    def poll_once(self, *, backfill: bool = False) -> dict[str, Any]:
        critical = self._storage_gate()
        if critical:
            self.write_health(status=critical)
            return {
                "ok": False,
                "status": critical,
                "canonical_unaffected": True,
                "processed": 0,
                "checkpoints": 0,
                "verdicts": 0,
                "outcomes": 0,
            }
        aes2_out: dict[str, Any] = {"processed": 0}
        if self.aes2_enabled:
            since = None if backfill else self.last_m15_timestamp
            if not backfill and self.last_m15_timestamp is None:
                from .source_adapter import aggregate_htf, load_m15_observations

                recent = load_m15_observations(repo=self.repo, limit=1)
                if recent:
                    obs = recent[-1]
                    out = self.process_observation(obs)
                    window = load_m15_observations(repo=self.repo, limit=32)
                    processed = [out]
                    for tf in ("M30", "H1", "H4"):
                        bars = aggregate_htf(window, tf)
                        if bars:
                            processed.append(self.process_observation(bars[-1]))
                    self.last_m15_timestamp = obs.timestamp
                    aes2_out = {
                        "processed": len(processed),
                        "mode": "cold_start_latest_only",
                        "results": processed,
                    }
                else:
                    aes2_out = {"processed": 0, "mode": "cold_start_empty"}
            else:
                processed = []
                for _tf, bar in iter_new_bars(repo=self.repo, last_m15_timestamp=since):
                    processed.append(self.process_observation(bar))
                aes2_out = {
                    "processed": len(processed),
                    "mode": "incremental" if not backfill else "backfill",
                    "results": processed,
                }

        aes4_out = self.process_canonical_checkpoints(backfill=backfill)
        aes5_out = self.process_aes5()
        self.write_health(status="RUNNING")
        return {
            "ok": True,
            "aes2": aes2_out,
            "aes4": aes4_out,
            "aes5": aes5_out,
            "processed": int(aes2_out.get("processed") or 0),
            "checkpoints": int(aes4_out.get("checkpoints") or 0),
            "verdicts": int(aes5_out.get("verdicts") or 0),
            "outcomes": int(aes5_out.get("outcomes") or 0),
        }

    def process_aes5(self) -> dict[str, Any]:
        if not self.aes5_enabled:
            return {"ok": True, "verdicts": 0, "outcomes": 0, "postmortems": 0, "aes5_enabled": False}
        aes2_fp = {
            tf: (e.state.auction_family, e.state.episode_phase, e.state.shadow_episode_id)
            for tf, e in self.aes2.engines.items()
        }
        aes3_fp = (
            self.hierarchy.last_snapshot.snapshot_id if self.hierarchy.last_snapshot else None,
            self.hierarchy.last_hierarchy_timestamp,
        )
        aes4_last = self.checkpoint_linker.last_checkpoint_id
        try:
            ckps = _load_jsonl(self.store.data_root / "memory" / "canonical_checkpoint_memory.jsonl")
            trade_map = load_trade_map(self.repo)
            verdicts = 0
            outcomes = 0
            postmortems = 0
            duplicates = 0
            conflicts = 0
            for ckp in ckps:
                res = self.aes5.evaluate_checkpoint(ckp)
                if res.get("payload_conflict"):
                    conflicts += 1
                    continue
                if res.get("duplicate"):
                    duplicates += 1
                    continue
                if res.get("written") and res.get("record"):
                    self.aes5_memory.write_verdict(res["record"])
                    verdicts += 1
            cases = _group_cases(ckps)
            waiting = 0
            for cid, bucket in cases.items():
                if bucket.get("entry") and not bucket.get("close"):
                    waiting += 1
                    continue
                if not bucket.get("close"):
                    continue
                close = bucket["close"]
                key = close.get("trade_id") or close.get("position_id")
                trade = dict(trade_map.get(str(key), {})) if key else {}
                if close.get("entry_price") is not None:
                    trade.setdefault("entry_price", close.get("entry_price"))
                if close.get("close_price") is not None:
                    trade.setdefault("exit_price", close.get("close_price"))
                if close.get("close_reason"):
                    trade.setdefault("exit_reason", close.get("close_reason"))
                pack = self.aes5.evaluate_case(
                    case_id=cid,
                    context_ckp=bucket.get("context"),
                    entry_ckp=bucket.get("entry"),
                    close_ckp=close,
                    canonical_trade=trade or None,
                )
                if pack.get("outcome"):
                    ores = self.aes5.outcomes.ingest(pack["outcome"])
                    if ores.get("payload_conflict"):
                        conflicts += 1
                    elif ores.get("duplicate"):
                        duplicates += 1
                    elif ores.get("written"):
                        self.aes5_memory.write_outcome(ores["record"])
                        outcomes += 1
                        self.aes5.last_outcome_id = ores["record"].get("outcome_id")
                if pack.get("postmortem"):
                    pres = self.aes5.postmortems.ingest(pack["postmortem"])
                    if pres.get("payload_conflict"):
                        conflicts += 1
                    elif pres.get("duplicate"):
                        duplicates += 1
                    elif pres.get("written"):
                        self.aes5_memory.write_postmortem(pres["record"])
                        postmortems += 1
                        self.aes5.last_postmortem_id = pres["record"].get("postmortem_id")
            self.aes5.open_cases_waiting_close = waiting
        except Exception as exc:
            self.write_health(status="RUNNING")
            return {
                "ok": False,
                "error": str(exc),
                "canonical_unaffected": True,
                "verdicts": 0,
                "outcomes": 0,
                "postmortems": 0,
            }

        aes2_fp_after = {
            tf: (e.state.auction_family, e.state.episode_phase, e.state.shadow_episode_id)
            for tf, e in self.aes2.engines.items()
        }
        if aes2_fp != aes2_fp_after:
            raise RuntimeError("AES5 mutated AES2 state")
        aes3_fp_after = (
            self.hierarchy.last_snapshot.snapshot_id if self.hierarchy.last_snapshot else None,
            self.hierarchy.last_hierarchy_timestamp,
        )
        if aes3_fp != aes3_fp_after:
            raise RuntimeError("AES5 mutated AES3 state")
        if self.checkpoint_linker.last_checkpoint_id != aes4_last:
            raise RuntimeError("AES5 mutated AES4 linker")

        self.write_health(status="RUNNING")
        return {
            "ok": True,
            "verdicts": verdicts,
            "outcomes": outcomes,
            "postmortems": postmortems,
            "duplicates": duplicates,
            "conflicts": conflicts,
            "open_cases_waiting_close": waiting,
        }


def refuse_without_storage(
    *,
    repo: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    repo_path = Path(repo) if repo else Path(__file__).resolve().parents[4]
    try:
        config = load_config(config_path, repo_root=repo_path)
    except Exception as exc:
        return {
            "status": SHADOW_REFUSED,
            "ok": False,
            "error": str(exc),
            "canonical_unaffected": True,
        }
    validation = validate_external_storage(
        data_root=config["data_root"],
        volume_root=config["required_volume_root"],
        min_free_bytes=int(config.get("min_free_bytes") or 0),
        repo=repo_path,
    )
    return {
        "status": "READY" if validation.ok else SHADOW_REFUSED,
        "ok": validation.ok,
        "validation": validation.to_dict(),
        "canonical_unaffected": True,
    }
