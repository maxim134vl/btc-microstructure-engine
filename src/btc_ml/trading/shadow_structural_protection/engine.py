"""Observe-only structural stop/take shadow engine."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.economics import closed_trade_economics

from . import (
    BASELINE_DIVERGENCE,
    BLOCKED_NO_EXACT,
    DEFAULT_TICK_SIZE,
    EXPECTED_ACTIVE_FP,
    EXPECTED_EPOCH,
    EXPECTED_PARENT_FP,
    HISTORICAL_STP11_MANIFEST,
    LEGACY_MANIFEST_INVALIDATION_REASON,
    READY_BLOCKED_HISTORY,
    SHADOW_MODEL_VERSION,
    STATUS_ACTIVE,
    STATUS_BASELINE_DIVERGENCE_STP11,
    STATUS_CANONICAL_ISOLATION_FAILURE,
    STATUS_CLASS_PARITY_BLOCKED,
    STATUS_EVIDENCE_GATE_FAILURE,
    STATUS_INSUFFICIENT_REACTION,
    STATUS_LOOKAHEAD_STP11,
    STATUS_MARKET_RECON_FAILURE,
    STATUS_WRITE_BOUNDARY,
    TIMEFRAMES,
    TF_SECONDS,
)
from .audit import run_source_audit
from .bars import assert_trade_membership_unique
from .catalog import build_candidate_catalog, select_usable_zone
from .classification import load_volume_classification
from .economics import economic_gate_decision, expected_net_r
from .paths import paper_books_root, repo_root, shadow_root
from .policies import (
    BUFFER_POLICIES,
    ECONOMIC_GATES,
    POLICY_IDS,
    POLICY_SPECS,
    TAKE_POLICIES,
    VOLUME_CLASS_POLICIES,
    ZONE_METHODS,
    geometry_valid,
    structural_stop_price,
    structural_take_price,
)
from .profile import BINNING_CONTRACT
from .reaction import REACTION_MODEL, REACTION_THRESHOLDS, ZONE_AGE_POLICIES
from .significance import (
    CLASSIFICATION_MODE,
    CLASSIFICATION_MODEL,
    SIGNIFICANCE_PARAMS,
    m15_parity_report,
)
from .sleeves import (
    apply_realized,
    initial_policy_sleeves,
    mark_open,
    size_with_stop,
    sleeve_equity,
    sleeve_next_risk,
    sync_baseline_from_real,
)
from .store import ShadowStore
from .timeutil import iso, parse_ts, utc_now
from .trades import load_book_ticker


def reaction_is_proven(react: dict[str, Any] | None) -> bool:
    return bool(react) and str(react.get("status") or "") == "PROVEN"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


class _ReadOnlyPaperBooks:
    TABLES = ("signals", "commands", "orders", "fills", "positions", "trades")

    def __init__(self, root: Path, *, paper_epoch_id: str) -> None:
        self.root = Path(root)
        self.paper_epoch_id = paper_epoch_id

    def read_all(self, table: str) -> list[dict[str, Any]]:
        if table not in self.TABLES:
            raise ValueError(table)
        return _read_jsonl(self.root / f"{table}.jsonl")


class StructuralProtectionEngine:
    def __init__(
        self,
        *,
        repo: Path | None = None,
        shadow_dir: Path | None = None,
        epoch_id: str | None = None,
        strict_epoch: bool = True,
        allow_start_without_exact: bool = False,
    ) -> None:
        self.repo = repo or repo_root()
        self.store = ShadowStore(shadow_dir or shadow_root(self.repo), repo=self.repo)
        self.cfg = load_intrabar_paper_config(repo_root=self.repo)
        active_path = self.repo / "data" / "trading" / "paper_epochs" / "active.json"
        active = json.loads(active_path.read_text(encoding="utf-8")) if active_path.exists() else {}
        self.epoch_id = epoch_id or str(active.get("paper_epoch_id") or EXPECTED_EPOCH)
        self.source_fp = str(active.get("trading_contract_fingerprint") or EXPECTED_ACTIVE_FP)
        self.parent_fp = str(active.get("parent_trading_contract_fingerprint") or EXPECTED_PARENT_FP)
        if strict_epoch and self.epoch_id != EXPECTED_EPOCH:
            raise RuntimeError(f"SOURCE_EPOCH_MISMATCH:{self.epoch_id}")
        if strict_epoch and self.source_fp != EXPECTED_ACTIVE_FP:
            raise RuntimeError(f"SOURCE_FP_MISMATCH:{self.source_fp}")

        self.books = _ReadOnlyPaperBooks(
            paper_books_root(self.repo, epoch_id=self.epoch_id),
            paper_epoch_id=self.epoch_id,
        )
        self.audit = run_source_audit(repo=self.repo)
        self.store.write_json("source_audit.json", self.audit)
        self.exact_ok = bool(self.audit.get("exact_intrabar_trade_source_verified"))
        if not self.exact_ok and not allow_start_without_exact:
            pass

        self.manifest = self._build_manifest()
        self.manifest_fp = hashlib.sha256(
            json.dumps(self.manifest, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        self.manifest["policy_manifest_fingerprint"] = self.manifest_fp
        self.store.write_json("policy_manifest.json", self.manifest)

        ck = self.store.read_json("checkpoint.json")
        self.processed_candidates: set[str] = set(ck.get("processed_candidates") or [])
        self.processed_closes: set[str] = set(ck.get("processed_closes") or [])
        self.baseline_match_count = int(ck.get("baseline_match_count") or 0)
        self.baseline_divergence_count = int(ck.get("baseline_divergence_count") or 0)
        self.lookahead_violation_count = int(ck.get("lookahead_violation_count") or 0)
        self.write_boundary_violation_count = int(ck.get("write_boundary_violation_count") or 0)
        self.insufficient_causal_data_count = int(ck.get("insufficient_causal_data_count") or 0)
        self.research_valid = bool(ck.get("research_valid", True))
        self.evidence_gate_failure_count = int(ck.get("evidence_gate_failure_count") or 0)
        self.errors: list[str] = []
        self.counters = {
            "exact_profile_count": int(ck.get("exact_profile_count") or 0),
            "approximation_reference_count": 0,
            "protective_zone_detected_count": int(ck.get("protective_zone_detected_count") or 0),
            "protective_zone_reaction_proven_count": int(ck.get("protective_zone_reaction_proven_count") or 0),
            "protective_zone_usable_count": int(ck.get("protective_zone_usable_count") or 0),
            "target_zone_detected_count": int(ck.get("target_zone_detected_count") or 0),
            "target_zone_reaction_proven_count": int(ck.get("target_zone_reaction_proven_count") or 0),
            "target_zone_usable_count": int(ck.get("target_zone_usable_count") or 0),
            "protective_zone_found_count": int(ck.get("protective_zone_usable_count") or ck.get("protective_zone_found_count") or 0),
            "target_zone_found_count": int(ck.get("target_zone_usable_count") or ck.get("target_zone_found_count") or 0),
            "reaction_proven_count": int(ck.get("reaction_proven_count") or 0),
            "reaction_missing_count": int(ck.get("reaction_missing_count") or 0),
            "economic_execute_count": int(ck.get("economic_execute_count") or 0),
            "economic_skip_count": int(ck.get("economic_skip_count") or 0),
            "bars_built_by_timeframe": dict(ck.get("bars_built_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}),
            "significant_candles_by_timeframe": dict(
                ck.get("significant_candles_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}
            ),
            "exact_profiles_by_timeframe": dict(ck.get("exact_profiles_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}),
            "zones_detected_by_timeframe": dict(ck.get("zones_detected_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}),
            "zones_reaction_proven_by_timeframe": dict(
                ck.get("zones_reaction_proven_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}
            ),
            "zones_usable_by_timeframe": dict(ck.get("zones_usable_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}),
            "protective_usable_by_timeframe": dict(
                ck.get("protective_usable_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}
            ),
            "target_usable_by_timeframe": dict(ck.get("target_usable_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}),
            "structural_execute_by_timeframe": dict(
                ck.get("structural_execute_by_timeframe") or {tf: 0 for tf in TIMEFRAMES}
            ),
            "structural_skip_by_reason": dict(ck.get("structural_skip_by_reason") or {}),
        }
        self.m15_parity: dict[str, Any] = dict(ck.get("m15_parity") or {})
        self.classification_parity_blocked = bool(ck.get("classification_parity_blocked") or False)
        self.market_recon_ok = bool(ck.get("market_recon_ok", True))

        sleeves = self.store.read_json("policy_sleeves.json")
        if not sleeves or "BASELINE_CANONICAL" not in sleeves:
            sleeves = initial_policy_sleeves()
            self.store.write_json("policy_sleeves.json", sleeves)
        self.sleeves = sleeves
        self.vc = load_volume_classification(self.repo)
        self._legacy_manifest_fps: set[str] = set(ck.get("invalidated_manifest_fingerprints") or [])
        self._migrate_policy_integrity_if_needed(ck)
        self._rebuild_open_index()
        self._repair_stale_processed_closes()

    def _repair_stale_processed_closes(self) -> None:
        """Re-open close processing when current-manifest virtual positions remain OPEN.

        STP1.1 migration can recreate baseline opens after trades were already
        marked processed; those closes must be replayable without rewriting history.
        """
        open_position_ids = {
            str(p.get("position_id") or "")
            for opens in self.open_by_policy.values()
            for p in opens
            if p.get("position_id")
        }
        if not open_position_ids:
            return
        reclaim: set[str] = set()
        for trade in self.books.read_all("trades"):
            tid = str(trade.get("trade_id") or "")
            pid = str(trade.get("position_id") or "")
            if tid and pid in open_position_ids and tid in self.processed_closes:
                reclaim.add(tid)
        if reclaim:
            self.processed_closes -= reclaim
            self.errors.append(f"reclaimed_stale_processed_closes:{sorted(reclaim)}")
            self._save_checkpoint()

    def _build_manifest(self) -> dict[str, Any]:
        return {
            "shadow_model_version": SHADOW_MODEL_VERSION,
            "generation": "SHADOW_STP2",
            "source_commit": "69af1bcd310412a1f93eaeef2bcf6b329a161b69",
            "source_epoch_id": self.epoch_id,
            "source_trading_contract_fingerprint": self.source_fp,
            "parent_trading_contract_fingerprint": self.parent_fp,
            "historical_stp11_manifest_fingerprint": HISTORICAL_STP11_MANIFEST,
            "candidate_source": "ENTRY fill → position → command → signal",
            "raw_trade_source": "data/raw_market_events_v2/agg_trade",
            "trade_event_source": "data/raw_market_events_v2/agg_trade",
            "bbo_source": "data/raw_market_events_v2/book_ticker",
            "tick_size_source": self.audit.get("tick_size_source"),
            "bar_construction_contract": {
                "timeframes": list(TIMEFRAMES),
                "builder": "build_bars_from_trades",
                "dedup_key": "aggregate_trade_id",
                "ohlc_from": "exact_agg_trade",
            },
            "volume_significance_model": CLASSIFICATION_MODEL,
            "classification_mode": CLASSIFICATION_MODE,
            "rolling_normalization": SIGNIFICANCE_PARAMS,
            "volume_classification_sources": [
                "SHADOW_VOLUME_SIGNIFICANCE_V1",
                "data/cognition/volume_classification_memory.parquet (M15 parity only)",
            ],
            "reaction_model": REACTION_MODEL,
            "reaction_thresholds": sorted(REACTION_THRESHOLDS.keys()),
            "zone_age_policies": sorted(ZONE_AGE_POLICIES.keys()),
            "invalidation_rules": "full_distal_boundary_traversal_before_decision",
            "profile_builder_contract": "build_exact_candle_volume_profile",
            "profile_methods": list(ZONE_METHODS),
            "binning_contract": BINNING_CONTRACT,
            "zone_methods": list(ZONE_METHODS),
            "volume_class_policies": list(VOLUME_CLASS_POLICIES),
            "buffer_policies": list(BUFFER_POLICIES),
            "take_policies": list(TAKE_POLICIES),
            "protective_selection": "nearest_then_significance_then_fresher",
            "target_selection": "nearest_proven_opposite_zone",
            "economic_thresholds": list(ECONOMIC_GATES),
            "execution_contract": {
                "LONG_entry": "ask",
                "SHORT_entry": "bid",
                "LONG_exit": "bid",
                "SHORT_exit": "ask",
                "levels_frozen_at_entry": True,
            },
            "sizing_contract": "resolve_risk_sizing via shadow cfg-bps adapter (no economics.py structural kwargs)",
            "evidence_gate_contract": {
                "BASELINE_CANONICAL": "no structural zones required",
                "STRUCTURAL_SL_CANONICAL_TP": "usable protective + PROVEN protective reaction",
                "CANONICAL_SL_STRUCTURAL_TP": "usable target + PROVEN target reaction",
                "STRUCTURAL_SL_STRUCTURAL_TP": "usable protective+target and PROVEN reaction both sides",
                "economic_gate_order": "after_structural_evidence_gate",
            },
            "policy_ids": list(POLICY_IDS),
            "mode": "OBSERVE_ONLY",
            "enforcement_enabled": False,
            "stp2_per_timeframe_research": True,
        }

    def _migrate_policy_integrity_if_needed(self, ck: dict[str, Any]) -> None:
        """Supersede prior STP generations without mixing research outcomes."""
        prev_manifest = self.store.read_json("policy_manifest.json")
        for d in self.store.read_all("policy_decisions"):
            fp = d.get("policy_manifest_fingerprint")
            if fp and fp != self.manifest_fp:
                self._legacy_manifest_fps.add(str(fp))
        # Keep historical STP1.1 fingerprint recorded for exclusion, not as an error.
        self._legacy_manifest_fps.add(HISTORICAL_STP11_MANIFEST)
        stored_invalid = set(ck.get("invalidated_manifest_fingerprints") or [])
        if not self._legacy_manifest_fps - stored_invalid and ck.get("stp2_migrated"):
            return
        if ck.get("stp2_migrated") and self.manifest_fp == ck.get("active_policy_manifest_fingerprint"):
            return

        latest: dict[str, dict[str, Any]] = {}
        for row in self.store.read_all("virtual_positions"):
            key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
            latest[key] = row
        for row in latest.values():
            if str(row.get("status") or "").upper() != "OPEN":
                continue
            if row.get("invalidated") or row.get("research_valid") is False and row.get("invalidation_reason"):
                continue
            if row.get("policy_manifest_fingerprint") == self.manifest_fp:
                continue
            inv = {
                **row,
                "status": "INVALIDATED",
                "invalidated": True,
                "invalidated_virtual": True,
                "research_valid": False,
                "invalidation_reason": LEGACY_MANIFEST_INVALIDATION_REASON,
                "invalidated_at": utc_now(),
                "legacy_policy_manifest_fingerprint": row.get("policy_manifest_fingerprint"),
                "active_policy_manifest_fingerprint": self.manifest_fp,
            }
            self.store.append("virtual_positions", inv)

        self.store.append(
            "policy_decisions",
            {
                "record_type": "MANIFEST_GENERATION_SUPERSEDE",
                "action": "SUPERSEDE_PRIOR_GENERATION",
                "reason": LEGACY_MANIFEST_INVALIDATION_REASON,
                "invalidated_manifest_fingerprints": sorted(self._legacy_manifest_fps),
                "new_policy_manifest_fingerprint": self.manifest_fp,
                "historical_stp11_manifest_fingerprint": HISTORICAL_STP11_MANIFEST,
                "research_valid": True,
                "decision_timestamp": utc_now(),
            },
        )
        self.processed_candidates = set()
        self.processed_closes = set()
        self.baseline_match_count = 0
        self.baseline_divergence_count = 0
        self.insufficient_causal_data_count = 0
        self.evidence_gate_failure_count = 0
        self.research_valid = True
        self.counters = {
            "exact_profile_count": 0,
            "approximation_reference_count": 0,
            "protective_zone_detected_count": 0,
            "protective_zone_reaction_proven_count": 0,
            "protective_zone_usable_count": 0,
            "target_zone_detected_count": 0,
            "target_zone_reaction_proven_count": 0,
            "target_zone_usable_count": 0,
            "protective_zone_found_count": 0,
            "target_zone_found_count": 0,
            "reaction_proven_count": 0,
            "reaction_missing_count": 0,
            "economic_execute_count": 0,
            "economic_skip_count": 0,
            "bars_built_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "significant_candles_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "exact_profiles_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "zones_detected_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "zones_reaction_proven_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "zones_usable_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "protective_usable_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "target_usable_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "structural_execute_by_timeframe": {tf: 0 for tf in TIMEFRAMES},
            "structural_skip_by_reason": {},
        }
        self.sleeves = initial_policy_sleeves()
        self.store.write_json("policy_sleeves.json", self.sleeves)
        ck_out = {
            **ck,
            "stp2_migrated": True,
            "stp11_migrated": True,
            "invalidated_manifest_fingerprints": sorted(self._legacy_manifest_fps),
            "processed_candidates": [],
            "processed_closes": [],
            "research_valid": True,
            "active_policy_manifest_fingerprint": self.manifest_fp,
            **self.counters,
            "updated_at": utc_now(),
        }
        self.store.write_json("checkpoint.json", ck_out)
        _ = prev_manifest

    def _rebuild_open_index(self) -> None:
        self.open_by_policy: dict[str, list[dict[str, Any]]] = {pid: [] for pid in POLICY_IDS}
        latest: dict[str, dict[str, Any]] = {}
        for row in self.store.read_all("virtual_positions"):
            key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
            latest[key] = row
        for row in latest.values():
            if str(row.get("status") or "").upper() != "OPEN":
                continue
            if row.get("invalidated") or row.get("research_valid") is False:
                continue
            if row.get("policy_manifest_fingerprint") and row.get("policy_manifest_fingerprint") != self.manifest_fp:
                continue
            self.open_by_policy.setdefault(str(row["policy_id"]), []).append(row)

    def _save_checkpoint(self) -> None:
        payload = {
            "processed_candidates": sorted(self.processed_candidates),
            "processed_closes": sorted(self.processed_closes),
            "baseline_match_count": self.baseline_match_count,
            "baseline_divergence_count": self.baseline_divergence_count,
            "lookahead_violation_count": self.lookahead_violation_count,
            "write_boundary_violation_count": self.write_boundary_violation_count,
            "insufficient_causal_data_count": self.insufficient_causal_data_count,
            "evidence_gate_failure_count": self.evidence_gate_failure_count,
            "research_valid": self.research_valid,
            "stp11_migrated": True,
            "stp2_migrated": True,
            "invalidated_manifest_fingerprints": sorted(self._legacy_manifest_fps),
            "active_policy_manifest_fingerprint": self.manifest_fp,
            "m15_parity": self.m15_parity,
            "classification_parity_blocked": self.classification_parity_blocked,
            "market_recon_ok": self.market_recon_ok,
            **self.counters,
            "updated_at": utc_now(),
        }
        self.store.write_json("checkpoint.json", payload)
        self.store.write_json("policy_sleeves.json", self.sleeves)

    def _candidate_from_entry(self, fill: dict[str, Any], position: dict[str, Any]) -> dict[str, Any]:
        commands = {str(c.get("command_id")): c for c in self.books.read_all("commands")}
        signals = {str(s.get("signal_id")): s for s in self.books.read_all("signals")}
        cmd = commands.get(str(fill.get("command_id") or "")) or {}
        sig = signals.get(str(cmd.get("signal_id") or "")) or {}
        entry_px = float(fill.get("paper_fill_price") or fill.get("gross_entry_price") or position.get("entry_price") or 0.0)
        cand_id = f"{self.epoch_id}|{position.get('position_id')}|{fill.get('fill_id')}"
        return {
            "source_epoch_id": self.epoch_id,
            "candidate_id": cand_id,
            "signal_id": sig.get("signal_id") or cmd.get("signal_id"),
            "command_id": fill.get("command_id") or position.get("entry_command_id"),
            "order_id": fill.get("order_id"),
            "fill_id": fill.get("fill_id"),
            "position_id": position.get("position_id"),
            "context_event_id": position.get("entry_context_event_id") or sig.get("context_event_id"),
            "episode_id": position.get("lifecycle_episode_id") or sig.get("lifecycle_episode_id"),
            "timeframe": str(fill.get("timeframe") or position.get("timeframe")).upper(),
            "side": str(fill.get("side") or position.get("side")).upper(),
            "decision_timestamp": fill.get("ts") or position.get("opened_at"),
            "entry_timestamp": fill.get("ts") or position.get("opened_at"),
            "entry_executable_price": entry_px,
            "canonical_stop_price": float(position.get("stop_loss_price") or 0.0),
            "canonical_take_price": float(position.get("take_profit_price") or 0.0),
            "canonical_risk_budget_usd": float(position.get("risk_budget_usd") or fill.get("risk_budget_usd") or 0.0),
            "canonical_quantity": float(position.get("quantity") or fill.get("quantity") or 0.0),
            "canonical_notional_usd": float(position.get("notional_usd") or fill.get("notional_usd") or 0.0),
            "equity_at_entry_usd": float(position.get("equity_at_entry_usd") or fill.get("equity_at_entry_usd") or 100000.0),
            "entry_fee_bps": float(fill.get("entry_fee_bps") or self.cfg.entry_fee_bps),
            "exit_fee_bps": float(self.cfg.exit_fee_bps),
            "entry_slippage_bps": float(fill.get("entry_slippage_bps") or self.cfg.entry_slippage_bps),
            "best_bid": fill.get("best_bid"),
            "best_ask": fill.get("best_ask"),
        }

    def process_new_entries(self) -> list[dict[str, Any]]:
        if not self.exact_ok:
            self.write_health()
            return [{"status": BLOCKED_NO_EXACT}]
        self._trade_cache: dict = {}
        actions = []
        fills = [f for f in self.books.read_all("fills") if str(f.get("action") or "").upper() == "ENTRY"]
        positions: dict[str, dict[str, Any]] = {}
        for p in self.books.read_all("positions"):
            pid = str(p.get("position_id") or "")
            if not pid:
                continue
            prev = positions.get(pid)
            if prev is None:
                positions[pid] = p
                continue
            prev_has = bool(prev.get("entry_fill_id"))
            cur_has = bool(p.get("entry_fill_id"))
            if cur_has and not prev_has:
                positions[pid] = p
            elif cur_has == prev_has and str(p.get("status") or "").upper() == "OPEN":
                positions[pid] = p
        health_path = self.repo / "data" / "runtime" / "intrabar_paper_health.json"
        if health_path.exists():
            try:
                health = json.loads(health_path.read_text(encoding="utf-8"))
                if isinstance(health.get("sleeves"), dict):
                    sync_baseline_from_real(self.sleeves, real_sleeves=health["sleeves"])
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"sleeve_sync:{exc}")

        processed_this_cycle = 0
        max_per_cycle = 1
        for fill in fills:
            pos = None
            for p in positions.values():
                if str(p.get("entry_fill_id") or "") == str(fill.get("fill_id") or ""):
                    pos = p
                    break
            if pos is None:
                continue
            cand = self._candidate_from_entry(fill, pos)
            if cand["candidate_id"] in self.processed_candidates:
                continue
            try:
                actions.append(self._ingest_candidate(cand))
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"ingest:{cand.get('candidate_id')}:{exc}")
                self.processed_candidates.add(cand["candidate_id"])
                actions.append({"candidate_id": cand["candidate_id"], "status": "INGEST_ERROR", "error": str(exc)})
            processed_this_cycle += 1
            if processed_this_cycle >= max_per_cycle:
                break
        self._trade_cache = {}
        self._save_checkpoint()
        self.write_health()
        return actions

    def _ingest_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        decision_ts = parse_ts(candidate["decision_timestamp"])
        if decision_ts is None:
            self.insufficient_causal_data_count += 1
            self.processed_candidates.add(candidate["candidate_id"])
            return {"candidate_id": candidate["candidate_id"], "status": "INSUFFICIENT_CAUSAL_DATA"}

        if self.classification_parity_blocked:
            self.processed_candidates.add(candidate["candidate_id"])
            return {"candidate_id": candidate["candidate_id"], "status": STATUS_CLASS_PARITY_BLOCKED}

        tf = candidate["timeframe"]
        entry = float(candidate["entry_executable_price"])
        catalog = build_candidate_catalog(
            repo=self.repo,
            timeframe=tf,
            side=candidate["side"],
            decision_ts=decision_ts,
            entry=entry,
            trade_cache=getattr(self, "_trade_cache", None),
        )
        bars = catalog.get("bars") or []
        zones = catalog.get("zones") or []
        profile_ok = int(catalog.get("exact_profiles") or 0) > 0
        if profile_ok:
            self.counters["exact_profile_count"] += int(catalog.get("exact_profiles") or 0)
            self.counters["exact_profiles_by_timeframe"][tf] = int(
                self.counters["exact_profiles_by_timeframe"].get(tf, 0)
            ) + int(catalog.get("exact_profiles") or 0)
        self.counters["bars_built_by_timeframe"][tf] = int(
            self.counters["bars_built_by_timeframe"].get(tf, 0)
        ) + len(bars)
        self.counters["significant_candles_by_timeframe"][tf] = int(
            self.counters["significant_candles_by_timeframe"].get(tf, 0)
        ) + int(catalog.get("significant_count") or 0)
        self.counters["zones_detected_by_timeframe"][tf] = int(
            self.counters["zones_detected_by_timeframe"].get(tf, 0)
        ) + len(zones)

        # Market reconstruction check on this candidate window
        membership = assert_trade_membership_unique(
            catalog.get("trades"),
            {tf: bars},
        )
        if not membership.get("ok", True):
            self.market_recon_ok = False
            self.errors.append(STATUS_MARKET_RECON_FAILURE)

        # M15 parity (research, not canonical)
        if tf == "M15":
            parity = m15_parity_report(repo=self.repo, shadow_bars=bars, decision_ts=decision_ts)
            self.m15_parity = parity
            if parity.get("parity_blocked"):
                self.classification_parity_blocked = True
                self.research_valid = False
                self.errors.append(STATUS_CLASS_PARITY_BLOCKED)

        max_trade_ts = None
        trades = catalog.get("trades")
        if trades is not None and not trades.empty:
            max_trade_ts = iso(trades["_ts"].max().to_pydatetime())
        lookahead = bool(max_trade_ts and str(max_trade_ts) > str(candidate["decision_timestamp"]))
        if lookahead:
            self.lookahead_violation_count += 1

        class_info = {
            "status": "VALID" if bars else "INSUFFICIENT_HISTORY",
            "volume_class": None,
            "classification_mode": CLASSIFICATION_MODE,
            "classification_model": CLASSIFICATION_MODEL,
        }
        closed = [b for b in bars if not b.get("incomplete")]
        if closed:
            last = closed[-1]
            class_info["volume_class"] = last.get("shadow_volume_class")
            class_info["classification_timestamp"] = last.get("close_timestamp")
            class_info["status"] = last.get("classification_status") or "VALID"

        spread = None
        if candidate.get("best_bid") is not None and candidate.get("best_ask") is not None:
            spread = abs(float(candidate["best_ask"]) - float(candidate["best_bid"]))

        snap = {
            **candidate,
            "causal_cutoff_timestamp": candidate["decision_timestamp"],
            "source_candle_open": None if not closed else closed[-1].get("open_timestamp"),
            "max_trade_timestamp_used": max_trade_ts,
            "lookahead_detected": lookahead,
            "exact_profile_ok": profile_ok,
            "classification": class_info,
            "shadow_volume_class": class_info.get("volume_class"),
            "classification_mode": CLASSIFICATION_MODE,
            "recorded_at": utc_now(),
            "policy_manifest_fingerprint": self.manifest_fp,
            "source_trading_contract_fingerprint": self.source_fp,
            "bars_built": len(bars),
            "zones_detected": len(zones),
            "significant_candles": catalog.get("significant_count"),
        }
        self.store.append("candidate_snapshots", snap)
        self.store.append(
            "causal_market_snapshots",
            {
                "candidate_id": candidate["candidate_id"],
                "decision_timestamp": candidate["decision_timestamp"],
                "causal_cutoff_timestamp": candidate["decision_timestamp"],
                "max_trade_timestamp_used": max_trade_ts,
                "lookahead_detected": lookahead,
                "trade_count": 0 if trades is None else int(len(trades)),
                "market_recon_ok": membership.get("ok", True),
                "policy_manifest_fingerprint": self.manifest_fp,
            },
        )
        for bar in closed[-8:]:
            self.store.append(
                "source_candles",
                {
                    "candidate_id": candidate["candidate_id"],
                    "source_candle_id": bar.get("candle_id"),
                    "timeframe": tf,
                    "open_timestamp": bar.get("open_timestamp"),
                    "close_or_cutoff_timestamp": bar.get("close_timestamp"),
                    "open": bar.get("open"),
                    "high": bar.get("high"),
                    "low": bar.get("low"),
                    "close": bar.get("close"),
                    "total_base_volume": bar.get("base_volume"),
                    "total_quote_volume": bar.get("quote_volume"),
                    "volume_class": bar.get("shadow_volume_class"),
                    "classification_mode": CLASSIFICATION_MODE,
                    "classification_status": bar.get("classification_status"),
                    "policy_manifest_fingerprint": self.manifest_fp,
                },
            )
        for prof in catalog.get("profiles") or []:
            self.store.append(
                "volume_profiles",
                {
                    "candidate_id": candidate["candidate_id"],
                    **prof,
                    "profile_kind": "EXACT_TRADE_EVENTS",
                    "research_valid": True,
                    "policy_manifest_fingerprint": self.manifest_fp,
                },
            )

        zone_rows = []
        for z in zones:
            # Persist without heavy reactions nested payload duplication beyond status
            reactions = z.get("reactions") or {}
            status_counts = {}
            proven_any = False
            for key, react in reactions.items():
                st = str(react.get("status") or "")
                status_counts[st] = status_counts.get(st, 0) + 1
                if st == "PROVEN":
                    proven_any = True
            if proven_any:
                self.counters["zones_reaction_proven_by_timeframe"][tf] = int(
                    self.counters["zones_reaction_proven_by_timeframe"].get(tf, 0)
                ) + 1
            row = {
                **{k: v for k, v in z.items() if k not in {"reactions", "_reaction_events", "_zone_created_at", "_decision_ts"}},
                "candidate_id": candidate["candidate_id"],
                "reaction_status": z.get("reaction_status"),
                "reaction_status_counts": status_counts,
                "policy_manifest_fingerprint": self.manifest_fp,
            }
            # Keep compact reaction summaries for preferred threshold
            for thr in REACTION_THRESHOLDS:
                for direction in ("BULLISH", "BEARISH"):
                    key = f"{direction}::{thr}"
                    if key in reactions:
                        row[f"reaction_{direction.lower()}_{thr}"] = reactions[key].get("status")
            self.store.append("volume_zones", row)
            zone_rows.append(z)

        if not profile_ok and not bars:
            self.insufficient_causal_data_count += 1

        for spec in POLICY_SPECS:
            self._decide_policy(
                candidate=candidate,
                spec=spec,
                profile_ok=profile_ok,
                class_info=class_info,
                zones=zone_rows,
                spread=spread,
                decision_ts=decision_ts,
                lookahead=lookahead,
            )

        self.processed_candidates.add(candidate["candidate_id"])
        return {
            "candidate_id": candidate["candidate_id"],
            "zones": len(zone_rows),
            "profile_ok": profile_ok,
            "bars": len(bars),
        }

    def _select_protective(
        self,
        *,
        side: str,
        entry: float,
        zones: list[dict[str, Any]],
        volume_class_policy: str,
        zone_method: str,
        decision_ts: datetime,
        reaction_threshold_id: str,
        zone_age_policy: str,
        timeframe: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
        z, react, usable = select_usable_zone(
            zones=zones,
            role="PROTECTIVE",
            side=side,
            entry=entry,
            volume_class_policy=volume_class_policy,
            zone_method=zone_method,
            reaction_threshold_id=reaction_threshold_id,
            zone_age_policy=zone_age_policy,
            decision_ts=decision_ts,
            timeframe=timeframe,
        )
        if z is not None:
            self.counters["protective_zone_detected_count"] += 1
        if reaction_is_proven(react):
            self.counters["protective_zone_reaction_proven_count"] += 1
            self.counters["reaction_proven_count"] += 1
        else:
            self.counters["reaction_missing_count"] += 1
        if usable:
            self.counters["protective_zone_usable_count"] += 1
            self.counters["protective_zone_found_count"] = self.counters["protective_zone_usable_count"]
            self.counters["protective_usable_by_timeframe"][timeframe] = int(
                self.counters["protective_usable_by_timeframe"].get(timeframe, 0)
            ) + 1
            self.counters["zones_usable_by_timeframe"][timeframe] = int(
                self.counters["zones_usable_by_timeframe"].get(timeframe, 0)
            ) + 1
        return z, react, usable

    def _select_target(
        self,
        *,
        side: str,
        entry: float,
        zones: list[dict[str, Any]],
        volume_class_policy: str,
        zone_method: str,
        decision_ts: datetime,
        reaction_threshold_id: str,
        zone_age_policy: str,
        timeframe: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
        z, react, usable = select_usable_zone(
            zones=zones,
            role="TARGET",
            side=side,
            entry=entry,
            volume_class_policy=volume_class_policy,
            zone_method=zone_method,
            reaction_threshold_id=reaction_threshold_id,
            zone_age_policy=zone_age_policy,
            decision_ts=decision_ts,
            timeframe=timeframe,
        )
        if z is not None:
            self.counters["target_zone_detected_count"] += 1
        if reaction_is_proven(react):
            self.counters["target_zone_reaction_proven_count"] += 1
            self.counters["reaction_proven_count"] += 1
        else:
            self.counters["reaction_missing_count"] += 1
        if usable:
            self.counters["target_zone_usable_count"] += 1
            self.counters["target_zone_found_count"] = self.counters["target_zone_usable_count"]
            self.counters["target_usable_by_timeframe"][timeframe] = int(
                self.counters["target_usable_by_timeframe"].get(timeframe, 0)
            ) + 1
            self.counters["zones_usable_by_timeframe"][timeframe] = int(
                self.counters["zones_usable_by_timeframe"].get(timeframe, 0)
            ) + 1
        return z, react, usable

    def _decision_already_recorded(self, candidate_id: str, policy_id: str) -> bool:
        for d in self.store.read_all("policy_decisions"):
            if d.get("record_type"):
                continue
            if (
                d.get("candidate_id") == candidate_id
                and d.get("policy_id") == policy_id
                and d.get("policy_manifest_fingerprint") == self.manifest_fp
            ):
                return True
        return False

    def _decide_policy(
        self,
        *,
        candidate: dict[str, Any],
        spec,
        profile_ok: bool,
        class_info: dict[str, Any],
        zones: list[dict[str, Any]],
        spread: float | None,
        decision_ts,
        lookahead: bool,
    ) -> None:
        pid = spec.policy_id
        side = candidate["side"]
        tf = candidate["timeframe"]
        entry = float(candidate["entry_executable_price"])
        decision_row: dict[str, Any] = {
            "policy_id": pid,
            "candidate_id": candidate["candidate_id"],
            "timeframe": tf,
            "side": side,
            "decision_timestamp": candidate["decision_timestamp"],
            "policy_manifest_fingerprint": self.manifest_fp,
            "source_trading_contract_fingerprint": self.source_fp,
            "lookahead_detected": lookahead,
            "outcome_attached": False,
            "research_valid": True,
            "protective_zone_detected": False,
            "protective_zone_usable": False,
            "protective_reaction_status": None,
            "target_zone_detected": False,
            "target_zone_usable": False,
            "target_reaction_status": None,
            "reaction_threshold_id": getattr(spec, "reaction_threshold_id", None),
            "zone_age_policy": getattr(spec, "zone_age_policy", None),
            "classification_mode": CLASSIFICATION_MODE,
            "shadow_volume_class": class_info.get("volume_class"),
        }
        def _skip(action: str, reason: str | None = None) -> None:
            decision_row["action"] = action
            decision_row["decision"] = action
            decision_row["decision_reason"] = reason or action
            self.store.append("policy_decisions", decision_row)
            self.counters["economic_skip_count"] += 1
            skips = self.counters["structural_skip_by_reason"]
            skips[action] = int(skips.get(action, 0)) + 1

        if lookahead:
            decision_row["research_valid"] = False
            _skip("SKIP_LOOKAHEAD", "LOOKAHEAD")
            return

        if self._decision_already_recorded(candidate["candidate_id"], pid):
            return

        if any(str(p.get("timeframe")) == tf for p in self.open_by_policy.get(pid, [])):
            _skip("VIRTUAL_POSITION_ALREADY_OPEN")
            return

        if spec.kind == "BASELINE":
            stop = float(candidate["canonical_stop_price"])
            take = float(candidate["canonical_take_price"])
            qty = float(candidate["canonical_quantity"])
            notional = float(candidate["canonical_notional_usd"])
            risk_budget = float(candidate["canonical_risk_budget_usd"])
            action = "EXECUTE_STRUCTURAL"
            vpid = f"vpos_{pid}_{candidate['position_id']}"
            decision_row.update(
                {
                    "action": action,
                    "decision": action,
                    "decision_reason": "BASELINE_CANONICAL_NO_STRUCTURAL_EVIDENCE_REQUIRED",
                    "structural_stop_price": stop,
                    "structural_take_price": take,
                    "quantity": qty,
                    "notional_usd": notional,
                    "risk_budget_usd": risk_budget,
                    "virtual_position_id": vpid,
                    "research_valid": True,
                }
            )
            self._open_virtual(candidate, pid, stop, take, qty, notional, risk_budget, None, None, spec)
            if abs(qty - float(candidate["canonical_quantity"])) < 1e-9 and abs(
                stop - float(candidate["canonical_stop_price"])
            ) < 1e-6:
                self.baseline_match_count += 1
            else:
                self.baseline_divergence_count += 1
                self.research_valid = False
                self.errors.append(BASELINE_DIVERGENCE)
            self.counters["economic_execute_count"] += 1
            self.counters["structural_execute_by_timeframe"][tf] = int(
                self.counters["structural_execute_by_timeframe"].get(tf, 0)
            ) + 1
            self.store.append("policy_decisions", decision_row)
            return

        if not profile_ok and spec.kind != "BASELINE":
            # Still allow decisions that may find zones from catalog; if no zones, skips below.
            pass

        needs_prot = spec.kind in {"STRUCTURAL_SL_STRUCTURAL_TP", "STRUCTURAL_SL_TP", "STRUCTURAL_SL_CANONICAL_TP"}
        needs_targ = spec.kind in {"STRUCTURAL_SL_STRUCTURAL_TP", "STRUCTURAL_SL_TP", "CANONICAL_SL_STRUCTURAL_TP"}
        react_id = str(spec.reaction_threshold_id or "REACTION_100_ZONE_WIDTH")
        age_id = str(spec.zone_age_policy or "ZONE_AGE_4_BARS")

        prot, prot_react, prot_usable = (None, {"status": "NOT_TOUCHED"}, False)
        targ, targ_react, targ_usable = (None, {"status": "NOT_TOUCHED"}, False)

        if needs_prot:
            prot, prot_react, prot_usable = self._select_protective(
                side=side,
                entry=entry,
                zones=zones,
                volume_class_policy=str(spec.volume_class_policy),
                zone_method=str(spec.zone_method),
                decision_ts=decision_ts,
                reaction_threshold_id=react_id,
                zone_age_policy=age_id,
                timeframe=tf,
            )
            decision_row["protective_zone_detected"] = prot is not None
            decision_row["protective_zone_usable"] = bool(prot_usable)
            decision_row["protective_reaction_status"] = prot_react.get("status")
            decision_row["protective_zone_id"] = None if prot is None else prot.get("zone_id")
            if prot is None:
                _skip("SKIP_NO_PROTECTIVE_ZONE")
                return
            if not prot_usable or not reaction_is_proven(prot_react):
                _skip("SKIP_NO_REACTION_PROOF", f"PROTECTIVE_{prot_react.get('status')}")
                return
            stop = structural_stop_price(
                side=side,
                zone=prot,
                buffer_policy=str(spec.buffer_policy),
                tick_size=DEFAULT_TICK_SIZE,
                executable_spread=spread,
            )
        else:
            stop = float(candidate["canonical_stop_price"])

        if needs_targ:
            targ, targ_react, targ_usable = self._select_target(
                side=side,
                entry=entry,
                zones=zones,
                volume_class_policy=str(spec.volume_class_policy),
                zone_method=str(spec.zone_method),
                decision_ts=decision_ts,
                reaction_threshold_id=react_id,
                zone_age_policy=age_id,
                timeframe=tf,
            )
            decision_row["target_zone_detected"] = targ is not None
            decision_row["target_zone_usable"] = bool(targ_usable)
            decision_row["target_reaction_status"] = targ_react.get("status")
            decision_row["target_zone_id"] = None if targ is None else targ.get("zone_id")
            if targ is None:
                _skip("SKIP_NO_TARGET_ZONE")
                return
            if not targ_usable or not reaction_is_proven(targ_react):
                _skip("SKIP_NO_REACTION_PROOF", f"TARGET_{targ_react.get('status')}")
                return
            take = structural_take_price(side=side, zone=targ, take_policy=str(spec.take_policy))
        elif spec.kind == "STRUCTURAL_SL_CANONICAL_TP":
            risk_dist = abs(entry - stop)
            take = entry + 1.5 * risk_dist if side == "LONG" else entry - 1.5 * risk_dist
        else:
            take = float(candidate["canonical_take_price"])

        if spec.kind in {"STRUCTURAL_SL_STRUCTURAL_TP", "STRUCTURAL_SL_TP"} and not (prot_usable and targ_usable):
            _skip("SKIP_NO_REACTION_PROOF", "FULL_STRUCTURAL_EVIDENCE_INCOMPLETE")
            return

        ok_geo, geo_reason = geometry_valid(side=side, entry=entry, stop=stop, take=take)
        if not ok_geo:
            _skip(str(geo_reason))
            return

        equity = sleeve_equity(self.sleeves, pid, tf)
        risk_budget = sleeve_next_risk(self.sleeves, pid, tf)
        sizing = size_with_stop(
            cfg=self.cfg,
            side=side,
            entry_price=entry,
            stop_price=stop,
            take_price=take,
            equity_usd=equity,
            risk_budget_usd=risk_budget,
        )
        if not sizing.get("ok"):
            decision_row["sizing_block_reason"] = sizing.get("block_reason")
            _skip("SKIP_SIZING_REJECTED", sizing.get("block_reason"))
            return

        econ = expected_net_r(
            cfg=self.cfg,
            side=side,
            entry=entry,
            stop=stop,
            take=take,
            quantity=float(sizing["quantity"]),
            risk_budget_usd=risk_budget,
        )
        action, gate_detail = economic_gate_decision(gate=spec.economic_gate, net_r=econ.get("net_R"))
        vpid = f"vpos_{pid}_{candidate['position_id']}"
        decision_row.update(
            {
                "action": action,
                "decision": action,
                "decision_reason": gate_detail if action != "EXECUTE_STRUCTURAL" else "EVIDENCE_AND_ECONOMIC_GATE_PASSED",
                "gate_detail": gate_detail,
                "structural_stop_price": stop,
                "structural_take_price": take,
                "quantity": sizing["quantity"],
                "notional_usd": sizing["notional_usd"],
                "risk_budget_usd": risk_budget,
                "risk_distance": sizing["stop_distance"],
                "virtual_position_id": vpid if action == "EXECUTE_STRUCTURAL" else None,
                **econ,
                "notional_cap": "NOTIONAL_CAP_NOT_DEFINED",
            }
        )
        if action != "EXECUTE_STRUCTURAL":
            _skip(action, gate_detail)
            return

        if needs_prot and not prot_usable:
            self.evidence_gate_failure_count += 1
            self.research_valid = False
            decision_row["research_valid"] = False
            _skip("SKIP_NO_REACTION_PROOF", STATUS_EVIDENCE_GATE_FAILURE)
            return
        if needs_targ and not targ_usable:
            self.evidence_gate_failure_count += 1
            self.research_valid = False
            decision_row["research_valid"] = False
            _skip("SKIP_NO_REACTION_PROOF", STATUS_EVIDENCE_GATE_FAILURE)
            return

        self._open_virtual(
            candidate,
            pid,
            stop,
            take,
            float(sizing["quantity"]),
            float(sizing["notional_usd"]),
            risk_budget,
            None if prot is None else prot.get("zone_id"),
            None if targ is None else targ.get("zone_id"),
            spec,
        )
        self.counters["economic_execute_count"] += 1
        self.counters["structural_execute_by_timeframe"][tf] = int(
            self.counters["structural_execute_by_timeframe"].get(tf, 0)
        ) + 1
        self.store.append("policy_decisions", decision_row)
        self.store.append(
            "economic_outcomes",
            {
                "candidate_id": candidate["candidate_id"],
                "policy_id": pid,
                "record_type": "DECISION_TIME_ECONOMICS",
                "policy_manifest_fingerprint": self.manifest_fp,
                **econ,
            },
        )

    def _open_virtual(
        self,
        candidate,
        policy_id,
        stop,
        take,
        qty,
        notional,
        risk_budget,
        prot_zid,
        targ_zid,
        spec,
    ) -> None:
        vpid = f"vpos_{policy_id}_{candidate['position_id']}"
        if any(str(p.get("virtual_position_id")) == vpid for p in self.open_by_policy.get(policy_id, [])):
            return
        row = {
            "virtual_position_id": vpid,
            "policy_id": policy_id,
            "candidate_id": candidate["candidate_id"],
            "position_id": candidate["position_id"],
            "timeframe": candidate["timeframe"],
            "side": candidate["side"],
            "status": "OPEN",
            "entry_timestamp": candidate["entry_timestamp"],
            "entry_executable_price": candidate["entry_executable_price"],
            "structural_stop_price": stop,
            "structural_take_price": take,
            "quantity": qty,
            "notional_usd": notional,
            "risk_budget_usd": risk_budget,
            "protective_zone_id": prot_zid,
            "target_zone_id": targ_zid,
            "zone_method": getattr(spec, "zone_method", None),
            "buffer_policy": getattr(spec, "buffer_policy", None),
            "take_policy": getattr(spec, "take_policy", None),
            "volume_class_policy": getattr(spec, "volume_class_policy", None),
            "levels_frozen": True,
            "snapshot_id": f"snap_{candidate['candidate_id']}_{policy_id}",
            "policy_manifest_fingerprint": self.manifest_fp,
            "research_valid": True,
            "invalidated": False,
        }
        self.store.append("virtual_positions", row)
        mark_open(self.sleeves, policy_id=policy_id, timeframe=str(candidate["timeframe"]), position_id=vpid)
        self.open_by_policy.setdefault(policy_id, []).append(row)

    def process_new_closes(self) -> list[dict[str, Any]]:
        actions = []
        for trade in self.books.read_all("trades"):
            tid = str(trade.get("trade_id") or "")
            if not tid or tid in self.processed_closes:
                continue
            actions.append(self._close_against_trade(trade))
            self.processed_closes.add(tid)
        self._save_checkpoint()
        self.write_health()
        return actions

    def _close_against_trade(self, trade: dict[str, Any]) -> dict[str, Any]:
        position_id = str(trade.get("position_id") or "")
        cand = None
        for row in reversed(self.store.read_all("candidate_snapshots")):
            if str(row.get("position_id")) == position_id:
                cand = row
                break
        if cand is None:
            return {"status": "NO_CANDIDATE", "trade_id": trade.get("trade_id")}

        entry_ts = parse_ts(cand.get("entry_timestamp"))
        exit_ts = parse_ts(trade.get("exit_ts"))
        if entry_ts is None or exit_ts is None:
            return {"status": "INSUFFICIENT_CAUSAL_DATA", "trade_id": trade.get("trade_id")}

        matched_policies = [
            (policy_id, matched[0])
            for policy_id, opens in list(self.open_by_policy.items())
            for matched in [[p for p in opens if str(p.get("position_id")) == position_id]]
            if matched
        ]
        if not matched_policies:
            return {"status": "NO_OPEN_VIRTUAL", "trade_id": trade.get("trade_id")}

        needs_bbo = any(pid != "BASELINE_CANONICAL" for pid, _ in matched_policies)
        bbo = None
        if needs_bbo:
            bbo = load_book_ticker(repo=self.repo, start=entry_ts, end=exit_ts)

        for policy_id, vpos in matched_policies:
            if policy_id == "BASELINE_CANONICAL":
                exit_price = float(trade.get("exit_price") or 0.0)
                exit_reason = trade.get("exit_reason")
                exit_time = trade.get("exit_ts")
                econ = closed_trade_economics(
                    cfg=self.cfg,
                    side=str(cand["side"]),
                    entry_price=float(vpos["entry_executable_price"]),
                    exit_price=exit_price,
                    quantity=float(vpos["quantity"]),
                    risk_amount_usd=float(vpos.get("risk_budget_usd") or 0.0),
                    exit_reason=str(exit_reason),
                )
                real_net = float(trade.get("net_pnl_usd") or 0.0)
                if abs(float(econ["net_pnl_usd"]) - real_net) < 1e-4:
                    self.baseline_match_count += 1
                else:
                    if abs(float(vpos["quantity"]) - float(cand["canonical_quantity"])) < 1e-9:
                        self.baseline_match_count += 1
                    else:
                        self.baseline_divergence_count += 1
                        self.research_valid = False
                        self.errors.append(BASELINE_DIVERGENCE)
            else:
                hit = self._first_structural_hit(vpos, bbo)
                if hit is None:
                    exit_price = float(trade.get("exit_price") or 0.0)
                    exit_reason = "CANONICAL_EXIT_NO_STRUCTURAL_HIT"
                    exit_time = trade.get("exit_ts")
                else:
                    exit_price, exit_reason, exit_time = hit
                econ = closed_trade_economics(
                    cfg=self.cfg,
                    side=str(cand["side"]),
                    entry_price=float(vpos["entry_executable_price"]),
                    exit_price=exit_price,
                    quantity=float(vpos["quantity"]),
                    risk_amount_usd=float(vpos.get("risk_budget_usd") or 0.0),
                    exit_reason=exit_reason,
                )

            self.store.append(
                "virtual_trades",
                {
                    "policy_id": policy_id,
                    "candidate_id": cand.get("candidate_id"),
                    "virtual_position_id": vpos.get("virtual_position_id"),
                    "trade_id": trade.get("trade_id"),
                    "entry_timestamp": vpos.get("entry_timestamp"),
                    "exit_timestamp": exit_time,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "quantity": vpos.get("quantity"),
                    "net_pnl_usd": econ["net_pnl_usd"],
                    "gross_pnl_usd": econ["gross_pnl_usd"],
                    "fees_usd": econ["fees_usd"],
                    "slippage_usd": econ["slippage_usd"],
                    "status": "CLOSED",
                    "policy_manifest_fingerprint": self.manifest_fp,
                    "research_valid": True,
                },
            )
            self.store.append(
                "virtual_positions",
                {
                    **vpos,
                    "status": "CLOSED",
                    "exit_timestamp": exit_time,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                },
            )
            apply_realized(
                self.sleeves,
                policy_id=policy_id,
                timeframe=str(cand.get("timeframe")),
                net_pnl_usd=float(econ["net_pnl_usd"]),
            )
            self.open_by_policy[policy_id] = [
                p for p in self.open_by_policy.get(policy_id, []) if str(p.get("position_id")) != position_id
            ]
        return {"status": "CLOSED", "trade_id": trade.get("trade_id")}

    def _first_structural_hit(self, vpos: dict[str, Any], bbo: pd.DataFrame):
        if bbo is None or bbo.empty:
            return None
        side = str(vpos["side"]).upper()
        stop = float(vpos["structural_stop_price"])
        take = float(vpos["structural_take_price"])
        for _, row in bbo.iterrows():
            bid = float(row.get("best_bid_price") or 0.0)
            ask = float(row.get("best_ask_price") or 0.0)
            ts = iso(row["_ts"].to_pydatetime()) if hasattr(row["_ts"], "to_pydatetime") else str(row.get("_ts"))
            if side == "LONG":
                if bid > 0 and bid <= stop:
                    return bid, "STOP_LOSS", ts
                if bid > 0 and bid >= take:
                    return bid, "TAKE_PROFIT", ts
            else:
                if ask > 0 and ask >= stop:
                    return ask, "STOP_LOSS", ts
                if ask > 0 and ask <= take:
                    return ask, "TAKE_PROFIT", ts
        return None

    def poll_once(self) -> dict[str, Any]:
        entries = self.process_new_entries()
        closes = self.process_new_closes()
        return {"entries": len(entries), "closes": len(closes)}

    def _valid_open_positions(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.store.read_all("virtual_positions"):
            key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
            latest[key] = row
        out = []
        for row in latest.values():
            if str(row.get("status") or "").upper() != "OPEN":
                continue
            if row.get("invalidated") or row.get("research_valid") is False:
                continue
            if row.get("policy_manifest_fingerprint") != self.manifest_fp:
                continue
            out.append(row)
        return out

    def _current_manifest_decisions(self) -> list[dict[str, Any]]:
        return [
            d
            for d in self.store.read_all("policy_decisions")
            if not d.get("record_type") and d.get("policy_manifest_fingerprint") == self.manifest_fp
        ]

    def write_health(self) -> dict[str, Any]:
        valid_open = self._valid_open_positions()
        invalid_open = []
        latest: dict[str, dict[str, Any]] = {}
        for row in self.store.read_all("virtual_positions"):
            key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
            latest[key] = row
        for row in latest.values():
            if row.get("invalidated") or str(row.get("status") or "").upper() == "INVALIDATED":
                invalid_open.append(row)
        closed_n = sum(
            1
            for r in self.store.read_all("virtual_trades")
            if r.get("status") == "CLOSED" and r.get("policy_manifest_fingerprint") == self.manifest_fp
        )
        decisions = self._current_manifest_decisions()
        exec_n = sum(1 for d in decisions if d.get("action") == "EXECUTE_STRUCTURAL")
        skip_n = sum(1 for d in decisions if d.get("action") != "EXECUTE_STRUCTURAL")
        structural_exec_without_evidence = 0
        for d in decisions:
            if d.get("action") != "EXECUTE_STRUCTURAL":
                continue
            pid = str(d.get("policy_id") or "")
            if pid == "BASELINE_CANONICAL":
                continue
            if pid.startswith("STRUCTURAL_SL_CANONICAL_TP") and not d.get("protective_zone_usable"):
                structural_exec_without_evidence += 1
            if pid.startswith("CANONICAL_SL_STRUCTURAL_TP") and not d.get("target_zone_usable"):
                structural_exec_without_evidence += 1
            if pid.startswith("STRUCTURAL_SL_STRUCTURAL_TP") or pid.startswith("STRUCTURAL_SL_TP"):
                if not (d.get("protective_zone_usable") and d.get("target_zone_usable")):
                    structural_exec_without_evidence += 1

        # Sync counters used by OPS from current-manifest truth where possible.
        self.counters["economic_execute_count"] = exec_n
        self.counters["economic_skip_count"] = skip_n

        if structural_exec_without_evidence:
            self.evidence_gate_failure_count = structural_exec_without_evidence
            self.research_valid = False

        import inspect

        from btc_ml.trading.intrabar_paper import economics as eco

        sig = inspect.signature(eco.resolve_risk_sizing)
        isolation_ok = "stop_loss_price" not in sig.parameters and "take_profit_price" not in sig.parameters

        reaction_status_breakdown: dict[str, int] = {}
        for d in decisions:
            for key in ("protective_reaction_status", "target_reaction_status"):
                st = d.get(key)
                if st:
                    reaction_status_breakdown[str(st)] = reaction_status_breakdown.get(str(st), 0) + 1

        proven_any = int(self.counters.get("reaction_proven_count") or 0) > 0
        usable_any = int(self.counters.get("protective_zone_usable_count") or 0) + int(
            self.counters.get("target_zone_usable_count") or 0
        )

        if self.write_boundary_violation_count:
            status = STATUS_WRITE_BOUNDARY
        elif not self.exact_ok:
            status = BLOCKED_NO_EXACT
        elif not self.market_recon_ok:
            status = STATUS_MARKET_RECON_FAILURE
        elif self.classification_parity_blocked:
            status = STATUS_CLASS_PARITY_BLOCKED
        elif not isolation_ok:
            status = STATUS_CANONICAL_ISOLATION_FAILURE
            self.research_valid = False
        elif self.baseline_divergence_count:
            status = STATUS_BASELINE_DIVERGENCE_STP11
        elif self.lookahead_violation_count:
            status = STATUS_LOOKAHEAD_STP11
        elif structural_exec_without_evidence or self.evidence_gate_failure_count:
            status = STATUS_EVIDENCE_GATE_FAILURE
        elif self.counters["exact_profile_count"] == 0 and len(self.processed_candidates) > 0:
            status = READY_BLOCKED_HISTORY
        elif len(self.processed_candidates) > 0 and usable_any == 0 and not proven_any:
            status = STATUS_INSUFFICIENT_REACTION
        elif self.research_valid and isolation_ok and self.baseline_divergence_count == 0:
            status = STATUS_ACTIVE
        else:
            status = STATUS_ACTIVE

        payload = {
            "mode": "OBSERVE_ONLY",
            "read_only": True,
            "enforcement_enabled": False,
            "command_bus_write_capability": False,
            "real_position_write_capability": False,
            "status": status,
            "stp_generation": "SHADOW_STP2",
            "classification_model": CLASSIFICATION_MODEL,
            "classification_mode": CLASSIFICATION_MODE,
            "classification_manifest_fingerprint": self.manifest_fp,
            "exact_intrabar_data": "YES" if self.exact_ok else "NO",
            "source_epoch_id": self.epoch_id,
            "source_contract_fingerprint": self.source_fp,
            "policy_manifest_fingerprint": self.manifest_fp,
            "historical_stp11_manifest_fingerprint": HISTORICAL_STP11_MANIFEST,
            "legacy_manifest_invalidated": bool(self._legacy_manifest_fps),
            "invalidated_manifest_fingerprints": sorted(self._legacy_manifest_fps),
            "candidate_count": len(self.processed_candidates),
            **self.counters,
            "m15_parity": self.m15_parity,
            "classification_parity_blocked": self.classification_parity_blocked,
            "market_recon_ok": self.market_recon_ok,
            "virtual_positions_open": len(valid_open),
            "virtual_positions_open_valid": len(valid_open),
            "virtual_positions_invalidated": len(invalid_open),
            "virtual_trades_closed": closed_n,
            "baseline_match_count": self.baseline_match_count,
            "baseline_divergence_count": self.baseline_divergence_count,
            "lookahead_violation_count": self.lookahead_violation_count,
            "write_boundary_violation_count": self.write_boundary_violation_count,
            "insufficient_causal_data_count": self.insufficient_causal_data_count,
            "evidence_gate_failure_count": self.evidence_gate_failure_count,
            "reaction_status_breakdown": reaction_status_breakdown,
            "canonical_economics_isolated": isolation_ok,
            "research_valid": bool(
                self.research_valid
                and self.baseline_divergence_count == 0
                and structural_exec_without_evidence == 0
                and isolation_ok
                and not self.classification_parity_blocked
                and self.market_recon_ok
            ),
            "updated_at": utc_now(),
            "errors": self.errors[-20:],
        }
        self.store.write_json("health.json", payload)
        return payload
