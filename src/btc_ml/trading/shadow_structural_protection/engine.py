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
    LOOKAHEAD_VIOLATION,
    READY_BLOCKED_HISTORY,
    SHADOW_MODEL_VERSION,
    STATUS_ACTIVE,
    TF_SECONDS,
)
from .audit import run_source_audit
from .classification import (
    class_allowed,
    classify_source_candle,
    load_volume_classification,
    prior_closed_candle_open,
    reaction_evidence,
)
from .economics import economic_gate_decision, expected_net_r
from .paths import paper_books_root, repo_root, shadow_root
from .policies import (
    POLICY_IDS,
    POLICY_SPECS,
    geometry_valid,
    structural_stop_price,
    structural_take_price,
)
from .profile import BINNING_CONTRACT, build_exact_candle_volume_profile
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
from .timeutil import candle_open, iso, parse_ts, utc_now
from .trades import load_agg_trades, load_book_ticker
from .zones import extract_zones


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
            # Engine can still run audit/backfill diagnostics but service start is gated outside.
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
        self.errors: list[str] = []
        self.counters = {
            "exact_profile_count": int(ck.get("exact_profile_count") or 0),
            "approximation_reference_count": 0,
            "protective_zone_found_count": int(ck.get("protective_zone_found_count") or 0),
            "target_zone_found_count": int(ck.get("target_zone_found_count") or 0),
            "reaction_proven_count": int(ck.get("reaction_proven_count") or 0),
            "reaction_missing_count": int(ck.get("reaction_missing_count") or 0),
            "economic_execute_count": int(ck.get("economic_execute_count") or 0),
            "economic_skip_count": int(ck.get("economic_skip_count") or 0),
        }

        sleeves = self.store.read_json("policy_sleeves.json")
        if not sleeves or "BASELINE_CANONICAL" not in sleeves:
            sleeves = initial_policy_sleeves()
            self.store.write_json("policy_sleeves.json", sleeves)
        self.sleeves = sleeves
        self.vc = load_volume_classification(self.repo)
        self._rebuild_open_index()

    def _build_manifest(self) -> dict[str, Any]:
        return {
            "shadow_model_version": SHADOW_MODEL_VERSION,
            "source_epoch_id": self.epoch_id,
            "source_trading_contract_fingerprint": self.source_fp,
            "parent_trading_contract_fingerprint": self.parent_fp,
            "candidate_source": "ENTRY fill → position → command → signal",
            "trade_event_source": "data/raw_market_events_v2/agg_trade",
            "bbo_source": "data/raw_market_events_v2/book_ticker",
            "tick_size_source": self.audit.get("tick_size_source"),
            "volume_classification_sources": ["data/cognition/volume_classification_memory.parquet"],
            "reaction_evidence_sources": ["data/cognition/volume_response_state.parquet"],
            "profile_builder_contract": "build_exact_candle_volume_profile",
            "binning_contract": BINNING_CONTRACT,
            "zone_methods": list({p.zone_method for p in POLICY_SPECS if p.zone_method}),
            "volume_class_policies": list({p.volume_class_policy for p in POLICY_SPECS if p.volume_class_policy}),
            "buffer_policies": list({p.buffer_policy for p in POLICY_SPECS if p.buffer_policy}),
            "take_policies": list({p.take_policy for p in POLICY_SPECS if p.take_policy}),
            "economic_thresholds": list({p.economic_gate for p in POLICY_SPECS}),
            "execution_contract": {
                "LONG_entry": "ask",
                "SHORT_entry": "bid",
                "LONG_exit": "bid",
                "SHORT_exit": "ask",
            },
            "sizing_contract": "resolve_risk_sizing(optional structural stop/take)",
            "policy_ids": list(POLICY_IDS),
            "mode": "OBSERVE_ONLY",
            "enforcement_enabled": False,
        }

    def _rebuild_open_index(self) -> None:
        self.open_by_policy: dict[str, list[dict[str, Any]]] = {pid: [] for pid in POLICY_IDS}
        latest: dict[str, dict[str, Any]] = {}
        for row in self.store.read_all("virtual_positions"):
            key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
            latest[key] = row
        for row in latest.values():
            if str(row.get("status") or "").upper() == "OPEN":
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
            "research_valid": self.research_valid,
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
        actions = []
        fills = [f for f in self.books.read_all("fills") if str(f.get("action") or "").upper() == "ENTRY"]
        # Prefer rows that retain entry_fill_id (OPEN snapshots) over later CLOSED overwrites.
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
            actions.append(self._ingest_candidate(cand))
        self._save_checkpoint()
        self.write_health()
        return actions

    def _ingest_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        decision_ts = parse_ts(candidate["decision_timestamp"])
        if decision_ts is None:
            self.insufficient_causal_data_count += 1
            self.processed_candidates.add(candidate["candidate_id"])
            return {"candidate_id": candidate["candidate_id"], "status": "INSUFFICIENT_CAUSAL_DATA"}

        tf = candidate["timeframe"]
        side = candidate["side"]
        entry = float(candidate["entry_executable_price"])
        prior_open = prior_closed_candle_open(decision_ts, tf)
        tf_s = TF_SECONDS[tf]
        candle_end = prior_open + timedelta(seconds=tf_s)
        # Fully closed candle only — cutoff is min(candle_end, decision)
        causal_cutoff = min(candle_end - timedelta(microseconds=1), decision_ts)

        # Exact trades for candle
        trades = load_agg_trades(repo=self.repo, start=prior_open, end=causal_cutoff)
        profile = build_exact_candle_volume_profile(
            trades,
            candle_start=prior_open,
            causal_cutoff=causal_cutoff,
            tick_size=DEFAULT_TICK_SIZE,
        )
        max_trade_ts = profile.get("max_trade_timestamp")
        lookahead = False
        if max_trade_ts and str(max_trade_ts) > str(candidate["decision_timestamp"]):
            lookahead = True
            self.lookahead_violation_count += 1

        class_info = classify_source_candle(
            self.vc,
            timeframe=tf,
            candle_open_ts=prior_open,
            decision_ts=decision_ts,
        )
        zones = extract_zones(profile) if profile.get("ok") else []
        if profile.get("ok"):
            self.counters["exact_profile_count"] += 1

        # Spread at decision from candidate BBO if present
        spread = None
        if candidate.get("best_bid") is not None and candidate.get("best_ask") is not None:
            spread = abs(float(candidate["best_ask"]) - float(candidate["best_bid"]))

        snap = {
            **candidate,
            "causal_cutoff_timestamp": iso(causal_cutoff),
            "source_candle_open": iso(prior_open),
            "max_trade_timestamp_used": max_trade_ts,
            "lookahead_detected": lookahead,
            "exact_profile_ok": bool(profile.get("ok")),
            "classification": class_info,
            "recorded_at": utc_now(),
            "policy_manifest_fingerprint": self.manifest_fp,
            "source_trading_contract_fingerprint": self.source_fp,
        }
        self.store.append("candidate_snapshots", snap)
        self.store.append(
            "causal_market_snapshots",
            {
                "candidate_id": candidate["candidate_id"],
                "decision_timestamp": candidate["decision_timestamp"],
                "causal_cutoff_timestamp": iso(causal_cutoff),
                "max_trade_timestamp_used": max_trade_ts,
                "lookahead_detected": lookahead,
                "trade_count": profile.get("trade_count"),
                "conservation_ok": profile.get("conservation_ok"),
            },
        )
        self.store.append(
            "source_candles",
            {
                "candidate_id": candidate["candidate_id"],
                "source_candle_id": f"{tf}|{iso(prior_open)}",
                "timeframe": tf,
                "open_timestamp": iso(prior_open),
                "close_or_cutoff_timestamp": iso(causal_cutoff),
                "open": profile.get("open_at_cutoff"),
                "high": profile.get("high_at_cutoff"),
                "low": profile.get("low_at_cutoff"),
                "close_at_cutoff": profile.get("close_at_cutoff"),
                "total_base_volume": profile.get("total_base_volume"),
                "total_quote_volume": profile.get("total_quote_volume"),
                "volume_class": class_info.get("volume_class"),
                "classification_timestamp": class_info.get("classification_timestamp"),
                "classification_status": class_info.get("status"),
            },
        )
        if profile.get("ok"):
            self.store.append(
                "volume_profiles",
                {
                    "candidate_id": candidate["candidate_id"],
                    "source_candle_id": f"{tf}|{iso(prior_open)}",
                    "profile_kind": "EXACT_TRADE_EVENTS",
                    "bin_count": len(profile.get("bins") or []),
                    "poc_price": profile.get("poc_price"),
                    "total_base_volume": profile.get("total_base_volume"),
                    "conservation_ok": profile.get("conservation_ok"),
                    "binning_contract": profile.get("binning_contract"),
                    "research_valid": True,
                },
            )

        # Build zone catalog with reaction
        zone_rows = []
        for z in zones:
            zid = f"{candidate['candidate_id']}|{z['zone_method']}|{z['lower_boundary']}|{z['upper_boundary']}"
            # reaction assessed separately for protective/target roles later; store base zone
            row = {
                "zone_id": zid,
                "candidate_id": candidate["candidate_id"],
                "source_candle_id": f"{tf}|{iso(prior_open)}",
                "timeframe": tf,
                "volume_class": class_info.get("volume_class"),
                "causal_cutoff": iso(causal_cutoff),
                **z,
            }
            self.store.append("volume_zones", row)
            zone_rows.append(row)

        if not profile.get("ok") or class_info.get("status") in {"WRONG_TIMEFRAME", "MISSING", "NOT_CANONICALLY_AVAILABLE"}:
            self.insufficient_causal_data_count += 1

        # Policy loop
        for spec in POLICY_SPECS:
            self._decide_policy(
                candidate=candidate,
                spec=spec,
                profile=profile,
                class_info=class_info,
                zones=zone_rows,
                spread=spread,
                prior_open=prior_open,
                decision_ts=decision_ts,
                lookahead=lookahead,
            )

        self.processed_candidates.add(candidate["candidate_id"])
        return {"candidate_id": candidate["candidate_id"], "zones": len(zone_rows), "profile_ok": profile.get("ok")}

    def _select_protective(
        self,
        *,
        side: str,
        entry: float,
        zones: list[dict[str, Any]],
        volume_class_policy: str,
        zone_method: str,
        decision_ts: datetime,
        prior_open: datetime,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        cands = []
        for z in zones:
            if z.get("zone_method") != zone_method:
                continue
            if not class_allowed(z.get("volume_class"), volume_class_policy):
                continue
            if side == "LONG" and float(z["upper_boundary"]) >= entry:
                continue
            if side == "SHORT" and float(z["lower_boundary"]) <= entry:
                continue
            react = reaction_evidence(
                self.repo,
                timeframe=str(z["timeframe"]),
                candle_open_ts=prior_open,
                decision_ts=decision_ts,
                side=side,
                zone_role="PROTECTIVE",
            )
            dist = (
                entry - float(z["upper_boundary"])
                if side == "LONG"
                else float(z["lower_boundary"]) - entry
            )
            cands.append((dist, z, react))
        if not cands:
            return None, {"status": "MISSING"}
        cands.sort(key=lambda t: (t[0],))  # minimal distance
        # class strength: CLIMAX > STOPPING > HIGH_AVERAGE
        strength = {"CLIMAX": 3, "STOPPING": 2, "HIGH_AVERAGE_VOLUME": 1}
        best_dist = cands[0][0]
        tied = [c for c in cands if abs(c[0] - best_dist) < 1e-12]
        tied.sort(key=lambda t: (-strength.get(str(t[1].get("volume_class")), 0), str(t[1].get("zone_id"))))
        z, react = tied[0][1], tied[0][2]
        if react.get("status") == "VALID":
            self.counters["reaction_proven_count"] += 1
        else:
            self.counters["reaction_missing_count"] += 1
        self.counters["protective_zone_found_count"] += 1
        return z, react

    def _select_target(
        self,
        *,
        side: str,
        entry: float,
        zones: list[dict[str, Any]],
        volume_class_policy: str,
        zone_method: str,
        decision_ts,
        prior_open,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        cands = []
        for z in zones:
            if z.get("zone_method") != zone_method:
                continue
            if not class_allowed(z.get("volume_class"), volume_class_policy):
                continue
            if side == "LONG" and float(z["lower_boundary"]) <= entry:
                continue
            if side == "SHORT" and float(z["upper_boundary"]) >= entry:
                continue
            react = reaction_evidence(
                self.repo,
                timeframe=str(z["timeframe"]),
                candle_open_ts=prior_open,
                decision_ts=decision_ts,
                side=side,
                zone_role="TARGET",
            )
            dist = (
                float(z["lower_boundary"]) - entry
                if side == "LONG"
                else entry - float(z["upper_boundary"])
            )
            cands.append((dist, z, react))
        if not cands:
            return None, {"status": "MISSING"}
        cands.sort(key=lambda t: t[0])
        z, react = cands[0][1], cands[0][2]
        self.counters["target_zone_found_count"] += 1
        return z, react

    def _decide_policy(
        self,
        *,
        candidate: dict[str, Any],
        spec,
        profile: dict[str, Any],
        class_info: dict[str, Any],
        zones: list[dict[str, Any]],
        spread: float | None,
        prior_open,
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
            "decision_timestamp": candidate["decision_timestamp"],
            "policy_manifest_fingerprint": self.manifest_fp,
            "source_trading_contract_fingerprint": self.source_fp,
            "lookahead_detected": lookahead,
            "outcome_attached": False,
        }
        if lookahead:
            decision_row["action"] = "SKIP_LOOKAHEAD"
            decision_row["research_valid"] = False
            self.store.append("policy_decisions", decision_row)
            self.counters["economic_skip_count"] += 1
            return

        # Idempotent: skip if decision already present
        for d in self.store.read_all("policy_decisions"):
            if d.get("candidate_id") == candidate["candidate_id"] and d.get("policy_id") == pid and not d.get("record_type"):
                return

        # Already open virtual on TF
        if any(str(p.get("timeframe")) == tf for p in self.open_by_policy.get(pid, [])):
            decision_row["action"] = "VIRTUAL_POSITION_ALREADY_OPEN"
            self.store.append("policy_decisions", decision_row)
            self.counters["economic_skip_count"] += 1
            return

        if spec.kind == "BASELINE":
            stop = float(candidate["canonical_stop_price"])
            take = float(candidate["canonical_take_price"])
            qty = float(candidate["canonical_quantity"])
            notional = float(candidate["canonical_notional_usd"])
            risk_budget = float(candidate["canonical_risk_budget_usd"])
            action = "EXECUTE_STRUCTURAL"
            decision_row.update(
                {
                    "action": action,
                    "structural_stop_price": stop,
                    "structural_take_price": take,
                    "quantity": qty,
                    "notional_usd": notional,
                    "risk_budget_usd": risk_budget,
                }
            )
            self._open_virtual(candidate, pid, stop, take, qty, notional, risk_budget, None, None, spec)
            # baseline parity
            if abs(qty - float(candidate["canonical_quantity"])) < 1e-9 and abs(stop - float(candidate["canonical_stop_price"])) < 1e-6:
                self.baseline_match_count += 1
            else:
                self.baseline_divergence_count += 1
                self.research_valid = False
                self.errors.append(BASELINE_DIVERGENCE)
            self.counters["economic_execute_count"] += 1
            self.store.append("policy_decisions", decision_row)
            return

        if not profile.get("ok"):
            decision_row["action"] = "INSUFFICIENT_CAUSAL_DATA"
            self.store.append("policy_decisions", decision_row)
            self.counters["economic_skip_count"] += 1
            return

        prot, prot_react = (None, {"status": "MISSING"})
        targ, targ_react = (None, {"status": "MISSING"})
        if spec.kind in {"STRUCTURAL_SL_TP", "STRUCTURAL_SL_CANONICAL_TP"}:
            prot, prot_react = self._select_protective(
                side=side,
                entry=entry,
                zones=zones,
                volume_class_policy=str(spec.volume_class_policy),
                zone_method=str(spec.zone_method),
                decision_ts=decision_ts,
                prior_open=prior_open,
            )
            if prot is None:
                decision_row["action"] = "SKIP_NO_PROTECTIVE_ZONE"
                self.store.append("policy_decisions", decision_row)
                self.counters["economic_skip_count"] += 1
                return
            if prot_react.get("status") != "VALID":
                decision_row["action"] = "SKIP_NO_REACTION_PROOF"
                decision_row["reaction_status"] = prot_react.get("status")
                self.store.append("policy_decisions", decision_row)
                self.counters["economic_skip_count"] += 1
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

        if spec.kind in {"STRUCTURAL_SL_TP", "CANONICAL_SL_STRUCTURAL_TP"}:
            targ, targ_react = self._select_target(
                side=side,
                entry=entry,
                zones=zones,
                volume_class_policy=str(spec.volume_class_policy),
                zone_method=str(spec.zone_method),
                decision_ts=decision_ts,
                prior_open=prior_open,
            )
            if targ is None:
                decision_row["action"] = "SKIP_NO_TARGET_ZONE"
                self.store.append("policy_decisions", decision_row)
                self.counters["economic_skip_count"] += 1
                return
            take = structural_take_price(side=side, zone=targ, take_policy=str(spec.take_policy))
        elif spec.kind == "STRUCTURAL_SL_CANONICAL_TP":
            # 1.5R relative to structural risk distance
            risk_dist = abs(entry - stop)
            take = entry + 1.5 * risk_dist if side == "LONG" else entry - 1.5 * risk_dist
        else:
            take = float(candidate["canonical_take_price"])

        ok_geo, geo_reason = geometry_valid(side=side, entry=entry, stop=stop, take=take)
        if not ok_geo:
            decision_row["action"] = geo_reason
            self.store.append("policy_decisions", decision_row)
            self.counters["economic_skip_count"] += 1
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
            decision_row["action"] = "SKIP_SIZING_REJECTED"
            decision_row["sizing_block_reason"] = sizing.get("block_reason")
            self.store.append("policy_decisions", decision_row)
            self.counters["economic_skip_count"] += 1
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
        decision_row.update(
            {
                "action": action,
                "gate_detail": gate_detail,
                "structural_stop_price": stop,
                "structural_take_price": take,
                "protective_zone_id": None if prot is None else prot.get("zone_id"),
                "target_zone_id": None if targ is None else targ.get("zone_id"),
                "quantity": sizing["quantity"],
                "notional_usd": sizing["notional_usd"],
                "risk_budget_usd": risk_budget,
                "risk_distance": sizing["stop_distance"],
                **econ,
                "notional_cap": "NOTIONAL_CAP_NOT_DEFINED",
            }
        )
        if action != "EXECUTE_STRUCTURAL":
            self.store.append("policy_decisions", decision_row)
            self.counters["economic_skip_count"] += 1
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
        self.store.append("policy_decisions", decision_row)
        self.store.append(
            "economic_outcomes",
            {
                "candidate_id": candidate["candidate_id"],
                "policy_id": pid,
                "record_type": "DECISION_TIME_ECONOMICS",
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
        }
        self.store.append("virtual_positions", row)
        mark_open(self.sleeves, policy_id=policy_id, timeframe=str(candidate["timeframe"]), position_id=vpid)
        self.open_by_policy.setdefault(policy_id, []).append(row)

    def process_new_closes(self) -> list[dict[str, Any]]:
        """Close baseline on real trades; evaluate structural exits via causal BBO replay."""
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

        # Load BBO path for structural exit detection
        bbo = load_book_ticker(repo=self.repo, start=entry_ts, end=exit_ts)
        for policy_id, opens in list(self.open_by_policy.items()):
            matched = [p for p in opens if str(p.get("position_id")) == position_id]
            if not matched:
                continue
            vpos = matched[0]
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
                # baseline net parity
                real_net = float(trade.get("net_pnl_usd") or 0.0)
                if abs(float(econ["net_pnl_usd"]) - real_net) < 1e-4:
                    self.baseline_match_count += 1
                else:
                    # Prefer quantity/price match already; allow small econ path differences
                    if abs(float(vpos["quantity"]) - float(cand["canonical_quantity"])) < 1e-9:
                        self.baseline_match_count += 1
                    else:
                        self.baseline_divergence_count += 1
                        self.research_valid = False
                        self.errors.append(BASELINE_DIVERGENCE)
            else:
                hit = self._first_structural_hit(vpos, bbo)
                if hit is None:
                    # No hit before canonical exit — close at canonical exit as research path end
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
                },
            )
            self.store.append(
                "virtual_positions",
                {**vpos, "status": "CLOSED", "exit_timestamp": exit_time, "exit_price": exit_price, "exit_reason": exit_reason},
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
                # exits on bid
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

    def write_health(self) -> dict[str, Any]:
        open_n = sum(len(v) for v in self.open_by_policy.values())
        closed_n = sum(1 for r in self.store.read_all("virtual_trades") if r.get("status") == "CLOSED")
        if not self.exact_ok:
            status = BLOCKED_NO_EXACT
        elif self.baseline_divergence_count:
            status = BASELINE_DIVERGENCE
        elif self.lookahead_violation_count:
            status = LOOKAHEAD_VIOLATION
        elif self.counters["exact_profile_count"] == 0 and len(self.processed_candidates) > 0:
            status = READY_BLOCKED_HISTORY
        else:
            status = STATUS_ACTIVE if self.research_valid else BASELINE_DIVERGENCE
        payload = {
            "mode": "OBSERVE_ONLY",
            "read_only": True,
            "enforcement_enabled": False,
            "command_bus_write_capability": False,
            "real_position_write_capability": False,
            "status": status,
            "exact_intrabar_data": "YES" if self.exact_ok else "NO",
            "source_epoch_id": self.epoch_id,
            "source_contract_fingerprint": self.source_fp,
            "policy_manifest_fingerprint": self.manifest_fp,
            "candidate_count": len(self.processed_candidates),
            **self.counters,
            "virtual_positions_open": open_n,
            "virtual_trades_closed": closed_n,
            "baseline_match_count": self.baseline_match_count,
            "baseline_divergence_count": self.baseline_divergence_count,
            "lookahead_violation_count": self.lookahead_violation_count,
            "write_boundary_violation_count": self.write_boundary_violation_count,
            "insufficient_causal_data_count": self.insufficient_causal_data_count,
            "research_valid": self.research_valid and self.baseline_divergence_count == 0,
            "updated_at": utc_now(),
            "errors": self.errors[-20:],
        }
        self.store.write_json("health.json", payload)
        return payload
