"""Observe-only shadow engine: candidates → policies → virtual outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config

from . import (
    BASELINE_DIVERGENCE,
    EXPECTED_ACTIVE_FP,
    EXPECTED_EPOCH,
    EXPECTED_PARENT_FP,
    FIELD_NOT_AVAILABLE,
    LOOKAHEAD_VIOLATION,
    POLICY_IDS,
    SOURCE_EPOCH_MISMATCH,
    STATUS_ACTIVE,
    STATUS_ENRICHMENT_ACTIVE,
    STATUS_ENRICHMENT_AMBIGUOUS,
    STATUS_ENRICHMENT_BASELINE,
    STATUS_ENRICHMENT_LOOKAHEAD,
    STATUS_ENRICHMENT_PARTIAL,
    STATUS_ENRICHMENT_WRITE,
)
from .cluster import build_cluster_snapshot
from .enrichment import (
    CausalFeatureEnricher,
    audit_cognition_sources,
    policy_manifest_fingerprint,
    summarize_enrichment_health,
)
from .features import build_decision_time_features, parse_ts, utc_now
from .marginal import marginal_contribution
from .outcomes import build_quality_outcome, scale_net_pnl
from .paths import paper_books_root, repo_root, shadow_root
from .policies import decide_policy
from .sleeves import (
    apply_policy_sizing,
    apply_realized,
    initial_policy_sleeves,
    mark_open,
    sync_baseline_from_real,
)
from .store import ShadowStore


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class _ReadOnlyPaperBooks:
    """Read-only view of paper books — never mkdir/touch/append."""

    TABLES = ("signals", "commands", "orders", "fills", "positions", "trades")

    def __init__(self, root: Path, *, paper_epoch_id: str) -> None:
        self.root = Path(root)
        self.paper_epoch_id = paper_epoch_id

    def read_all(self, table: str) -> list[dict[str, Any]]:
        if table not in self.TABLES:
            raise ValueError(table)
        return _read_jsonl(self.root / f"{table}.jsonl")


def _latest_positions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid = str(r.get("position_id") or "")
        if pid:
            latest[pid] = r
    return [p for p in latest.values() if str(p.get("status") or "").upper() == "OPEN"]


def _load_context_event(repo: Path, context_event_id: str | None) -> dict[str, Any] | None:
    if not context_event_id:
        return None
    journal = repo / "data" / "cognition" / "intrabar_context_events" / "events.jsonl"
    if not journal.exists():
        return None
    # Scan tail first for speed.
    lines = journal.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines[-20000:]):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("context_event_id") or "") == str(context_event_id):
            return row
    return None


class ShadowEconomicCorrelationEngine:
    def __init__(
        self,
        *,
        repo: Path | None = None,
        shadow_dir: Path | None = None,
        epoch_id: str | None = None,
        strict_epoch: bool = True,
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
            raise RuntimeError(f"{SOURCE_EPOCH_MISMATCH}: {self.epoch_id}")
        if strict_epoch and self.source_fp != EXPECTED_ACTIVE_FP:
            raise RuntimeError(f"{SOURCE_EPOCH_MISMATCH}: fingerprint {self.source_fp}")

        self.books = _ReadOnlyPaperBooks(
            paper_books_root(self.repo, epoch_id=self.epoch_id),
            paper_epoch_id=self.epoch_id,
        )
        ck = self.store.read_json("checkpoint.json")
        self.processed_candidates: set[str] = set(ck.get("processed_candidates") or [])
        self.processed_closes: set[str] = set(ck.get("processed_closes") or [])
        self.processed_enrichments: set[str] = set(ck.get("processed_enrichments") or [])
        self.baseline_match_count = int(ck.get("baseline_match_count") or 0)
        self.baseline_divergence_count = int(ck.get("baseline_divergence_count") or 0)
        self.lookahead_violation_count = int(ck.get("lookahead_violation_count") or 0)
        self.write_boundary_violation_count = int(ck.get("write_boundary_violation_count") or 0)
        self.research_valid = bool(ck.get("research_valid", True))
        self.last_candidate_timestamp = ck.get("last_candidate_timestamp")
        self.last_trade_close_timestamp = ck.get("last_trade_close_timestamp")
        self.last_enrichment_timestamp = ck.get("last_enrichment_timestamp")
        self.errors: list[str] = []

        sleeves = self.store.read_json("policy_sleeves.json")
        if not sleeves or "BASELINE_ALL_ELIGIBLE" not in sleeves:
            sleeves = initial_policy_sleeves()
            self.store.write_json("policy_sleeves.json", sleeves)
        self.sleeves = sleeves

        self.manifest = {
            "mode": "OBSERVE_ONLY",
            "enforcement_enabled": False,
            "quality_scoring_enabled": False,
            "feature_enrichment_enabled": True,
            "policy_ids": list(POLICY_IDS),
            "source_epoch_id": self.epoch_id,
            "source_contract_fingerprint": self.source_fp,
            "parent_trading_contract_fingerprint": self.parent_fp,
            "expected_active_fingerprint": EXPECTED_ACTIVE_FP,
            "expected_parent_fingerprint": EXPECTED_PARENT_FP,
        }
        self.manifest_fp = policy_manifest_fingerprint(self.manifest)
        self.manifest["shadow_policy_manifest_fingerprint"] = self.manifest_fp
        self.store.write_json("policy_manifest.json", self.manifest)
        # Persist source audit snapshot (shadow-only write).
        try:
            audit = audit_cognition_sources(repo=self.repo)
            self.store.write_json("cognition_source_audit.json", {"generated_at": utc_now(), "sources": audit})
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"source_audit:{exc}")
        self.enricher = CausalFeatureEnricher(repo=self.repo)
        self._rebuild_open_index()

    def _rebuild_open_index(self) -> None:
        self.open_by_policy: dict[str, list[dict[str, Any]]] = {pid: [] for pid in POLICY_IDS}
        latest: dict[str, dict[str, Any]] = {}
        for row in self.store.read_all("virtual_positions"):
            key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
            latest[key] = row
        for row in latest.values():
            if str(row.get("status") or "").upper() != "OPEN":
                continue
            pid = str(row.get("policy_id"))
            self.open_by_policy.setdefault(pid, []).append(row)

    def _save_checkpoint(self) -> None:
        self.store.write_json(
            "checkpoint.json",
            {
                "processed_candidates": sorted(self.processed_candidates),
                "processed_closes": sorted(self.processed_closes),
                "processed_enrichments": sorted(self.processed_enrichments),
                "baseline_match_count": self.baseline_match_count,
                "baseline_divergence_count": self.baseline_divergence_count,
                "lookahead_violation_count": self.lookahead_violation_count,
                "write_boundary_violation_count": self.write_boundary_violation_count,
                "research_valid": self.research_valid,
                "last_candidate_timestamp": self.last_candidate_timestamp,
                "last_trade_close_timestamp": self.last_trade_close_timestamp,
                "last_enrichment_timestamp": self.last_enrichment_timestamp,
                "updated_at": utc_now(),
            },
        )
        self.store.write_json("policy_sleeves.json", self.sleeves)

    def _candidate_from_entry_chain(self, fill: dict[str, Any], position: dict[str, Any]) -> dict[str, Any]:
        command_id = str(fill.get("command_id") or "")
        commands = {str(c.get("command_id")): c for c in self.books.read_all("commands")}
        signals = {str(s.get("signal_id")): s for s in self.books.read_all("signals")}
        cmd = commands.get(command_id) or {}
        signal_id = str(cmd.get("signal_id") or position.get("entry_command_id") or "")
        # Prefer signal linked via command; fallback scan by context.
        sig = signals.get(str(cmd.get("signal_id") or "")) or {}
        if not sig:
            for s in self.books.read_all("signals"):
                if str(s.get("context_event_id")) == str(position.get("entry_context_event_id") or fill.get("context_event_id")):
                    if str(s.get("timeframe")) == str(fill.get("timeframe")):
                        sig = s
                        signal_id = str(s.get("signal_id") or "")
                        break
        cand_id = f"{self.epoch_id}|{position.get('position_id')}|{fill.get('fill_id')}"
        entry_px = float(fill.get("paper_fill_price") or fill.get("gross_entry_price") or position.get("entry_price") or 0.0)
        return {
            "paper_epoch_id": self.epoch_id,
            "candidate_id": cand_id,
            "signal_id": signal_id or sig.get("signal_id"),
            "command_id": command_id or position.get("entry_command_id"),
            "order_id": fill.get("order_id"),
            "fill_id": fill.get("fill_id"),
            "position_id": position.get("position_id"),
            "context_event_id": position.get("entry_context_event_id") or sig.get("context_event_id"),
            "lifecycle_episode_id": position.get("lifecycle_episode_id") or sig.get("lifecycle_episode_id"),
            "timeframe": str(fill.get("timeframe") or position.get("timeframe")).upper(),
            "side": str(fill.get("side") or position.get("side")).upper(),
            "candidate_timestamp": fill.get("ts") or position.get("opened_at"),
            "entry_timestamp": fill.get("ts") or position.get("opened_at"),
            "entry_executable_price": entry_px,
            "stop_price": position.get("stop_loss_price"),
            "take_price": position.get("take_profit_price"),
            "risk_budget_usd": float(
                position.get("risk_budget_usd")
                or position.get("risk_amount_usd")
                or sig.get("risk_budget_usd")
                or 0.0
            ),
            "risk_amount_usd": float(position.get("risk_amount_usd") or 0.0),
            "quantity": float(position.get("quantity") or fill.get("quantity") or 0.0),
            "notional_usd": float(
                position.get("notional_usd")
                or (float(position.get("quantity") or 0.0) * entry_px)
            ),
            "equity_at_entry_usd": position.get("equity_at_entry_usd") or sig.get("equity_at_entry_usd"),
            "risk_pct_at_entry": position.get("risk_pct_at_entry") or sig.get("risk_pct_at_entry") or 1.0,
            "stop_distance_usd": position.get("stop_distance_usd") or sig.get("stop_distance_usd"),
        }

    def process_new_entries(self) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        fills = [f for f in self.books.read_all("fills") if str(f.get("action") or "").upper() == "ENTRY"]
        positions = {str(p.get("position_id")): p for p in self.books.read_all("positions")}
        open_now = _latest_positions(self.books.read_all("positions"))

        # Sync baseline sleeves from live health if present.
        health_path = self.repo / "data" / "runtime" / "intrabar_paper_health.json"
        if health_path.exists():
            try:
                health = json.loads(health_path.read_text(encoding="utf-8"))
                if isinstance(health.get("sleeves"), dict):
                    sync_baseline_from_real(self.sleeves, real_sleeves=health["sleeves"])
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"sleeve_sync:{exc}")

        for fill in fills:
            # Match position by entry_fill_id or timeframe+qty+side open/closed.
            pos = None
            for p in positions.values():
                if str(p.get("entry_fill_id") or "") == str(fill.get("fill_id") or ""):
                    pos = p
                    break
            if pos is None:
                # Fallback: OPEN/CLOSED row with same tf/side/qty/entry.
                for p in positions.values():
                    if (
                        str(p.get("timeframe")) == str(fill.get("timeframe"))
                        and str(p.get("side")).upper() == str(fill.get("side")).upper()
                        and abs(float(p.get("quantity") or 0) - float(fill.get("quantity") or 0)) < 1e-12
                        and abs(float(p.get("entry_price") or 0) - float(fill.get("paper_fill_price") or fill.get("gross_entry_price") or 0))
                        < 1e-6
                    ):
                        pos = p
                        break
            if pos is None:
                continue
            cand = self._candidate_from_entry_chain(fill, pos)
            cid = str(cand["candidate_id"])
            if cid in self.processed_candidates:
                continue
            actions.append(self._ingest_candidate(cand, open_positions_before=open_now))
        self._save_checkpoint()
        self.write_health()
        return actions

    def _ingest_candidate(self, candidate: dict[str, Any], *, open_positions_before: list[dict[str, Any]]) -> dict[str, Any]:
        decision_ts = str(candidate.get("candidate_timestamp") or utc_now())
        ctx = _load_context_event(self.repo, candidate.get("context_event_id"))
        features = build_decision_time_features(
            candidate=candidate,
            context_event=ctx,
            open_positions_before=open_positions_before,
        )
        cluster = build_cluster_snapshot(candidate=candidate, open_positions_before=open_positions_before)

        # Lookahead guard on inputs.
        max_input = decision_ts
        for ts in (
            features.get("context_start_timestamp"),
            candidate.get("entry_timestamp"),
            (ctx or {}).get("event_timestamp"),
        ):
            if ts and str(ts) > str(max_input):
                max_input = str(ts)
        lookahead = False
        d_dt = parse_ts(decision_ts)
        m_dt = parse_ts(max_input)
        if d_dt and m_dt and m_dt > d_dt:
            lookahead = True
            self.lookahead_violation_count += 1

        snap = {
            **candidate,
            "decision_time_features": features,
            "recorded_at": utc_now(),
            "economic_quality_mode": "DATA_COLLECTION",
        }
        self.store.append("candidate_snapshots", snap)
        self.store.append(
            "cluster_snapshots",
            {
                "candidate_id": candidate["candidate_id"],
                "decision_timestamp": decision_ts,
                **cluster,
            },
        )

        results = []
        for policy_id in POLICY_IDS:
            policy_open = list(self.open_by_policy.get(policy_id) or [])
            decision = decide_policy(
                policy_id=policy_id,
                candidate=candidate,
                cluster=cluster,
                policy_open_positions=policy_open,
            )
            decision_row = {
                "policy_id": policy_id,
                "candidate_id": candidate["candidate_id"],
                "decision_timestamp": decision_ts,
                "max_input_timestamp": max_input,
                "lookahead_detected": lookahead,
                "action": decision.action,
                "risk_multiplier": decision.risk_multiplier,
                "reason": decision.reason,
                "outcome_attached": False,
                "research_valid": self.research_valid and not lookahead,
                # Outcome intentionally absent at decision time.
                "outcome_fields_present_at_decision": False,
            }
            if lookahead:
                decision_row["research_valid"] = False
                decision_row["lookahead_status"] = LOOKAHEAD_VIOLATION

            virtual_pos = None
            if decision.action in {"EXECUTE_FULL", "EXECUTE_REDUCED"} and decision.risk_multiplier > 0:
                sizing = apply_policy_sizing(
                    cfg=self.cfg,
                    candidate=candidate,
                    sleeves=self.sleeves,
                    policy_id=policy_id,
                    risk_multiplier=decision.risk_multiplier,
                )
                if sizing.get("sizing_ok"):
                    vpid = f"vpos_{policy_id}_{candidate['position_id']}"
                    # Idempotent open
                    if not any(str(p.get("virtual_position_id")) == vpid for p in policy_open):
                        virtual_pos = {
                            "virtual_position_id": vpid,
                            "policy_id": policy_id,
                            "candidate_id": candidate["candidate_id"],
                            "position_id": candidate["position_id"],
                            "timeframe": candidate["timeframe"],
                            "side": candidate["side"],
                            "status": "OPEN",
                            "entry_timestamp": candidate["entry_timestamp"],
                            "entry_executable_price": candidate["entry_executable_price"],
                            "stop_price": candidate["stop_price"],
                            "take_price": candidate["take_price"],
                            "quantity": sizing["quantity"],
                            "notional_usd": sizing["notional_usd"],
                            "risk_budget_usd": sizing["effective_risk_budget_usd"],
                            "risk_amount_usd": sizing["risk_amount_usd"],
                            "risk_multiplier": decision.risk_multiplier,
                            "equity_at_entry_usd": sizing["equity_at_entry_usd"],
                        }
                        self.store.append("virtual_positions", virtual_pos)
                        mark_open(
                            self.sleeves,
                            policy_id=policy_id,
                            timeframe=str(candidate["timeframe"]),
                            position_id=vpid,
                            risk_usd=float(sizing["risk_amount_usd"] or 0.0),
                        )
                        self.open_by_policy.setdefault(policy_id, []).append(virtual_pos)
                        # Baseline parity check
                        if policy_id == "BASELINE_ALL_ELIGIBLE":
                            self._check_baseline_entry(candidate, virtual_pos)
                else:
                    decision_row["action"] = "BLOCK_CORRELATED_EXPOSURE"
                    decision_row["reason"] = sizing.get("block_reason") or "sizing_failed"
            else:
                decision_row["counterfactual_reserved"] = True

            self.store.append("policy_decisions", decision_row)
            results.append(decision_row)

        self.processed_candidates.add(str(candidate["candidate_id"]))
        self.last_candidate_timestamp = decision_ts
        # Enrichment after immutable decision snapshot — failures must not block simulation.
        try:
            self._enrich_candidate(candidate, decision_timestamp=decision_ts, historical=False)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"enrichment:{exc}")
        return {"candidate_id": candidate["candidate_id"], "decisions": len(results), "lookahead": lookahead}

    def _enrich_candidate(
        self,
        candidate: dict[str, Any],
        *,
        decision_timestamp: str,
        historical: bool,
    ) -> dict[str, Any] | None:
        cid = str(candidate.get("candidate_id") or "")
        if not cid or cid in self.processed_enrichments:
            return None
        # Journal-level idempotency (survives checkpoint gaps).
        for existing in self.store.read_all("candidate_feature_enrichments"):
            if str(existing.get("candidate_id") or "") == cid:
                self.processed_enrichments.add(cid)
                return None
        row = self.enricher.enrich_candidate(
            candidate=candidate,
            decision_timestamp=decision_timestamp,
            source_epoch_id=self.epoch_id,
            source_contract_fingerprint=self.source_fp,
            shadow_policy_manifest_fingerprint=self.manifest_fp,
            historical=historical,
        )
        if row.get("lookahead_detected"):
            self.lookahead_violation_count += 1
        self.store.append("candidate_feature_enrichments", row)
        self.processed_enrichments.add(cid)
        self.last_enrichment_timestamp = row.get("enriched_at")
        return row

    def backfill_enrichments(self) -> list[dict[str, Any]]:
        """Causally enrich existing candidates without rewriting decisions/snapshots."""
        actions: list[dict[str, Any]] = []
        for snap in self.store.read_all("candidate_snapshots"):
            cid = str(snap.get("candidate_id") or "")
            if not cid or cid in self.processed_enrichments:
                continue
            decision_ts = str(snap.get("candidate_timestamp") or snap.get("entry_timestamp") or "")
            try:
                row = self._enrich_candidate(snap, decision_timestamp=decision_ts, historical=True)
                if row:
                    actions.append({"candidate_id": cid, "status": "ENRICHED"})
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"backfill_enrichment:{cid}:{exc}")
                actions.append({"candidate_id": cid, "status": "FAILED", "error": str(exc)})
        self._save_checkpoint()
        self.write_health()
        return actions

    def _check_baseline_entry(self, candidate: dict[str, Any], virtual_pos: dict[str, Any]) -> None:
        qty_ok = abs(float(virtual_pos.get("quantity") or 0) - float(candidate.get("quantity") or 0)) < 1e-9
        px_ok = abs(float(virtual_pos.get("entry_executable_price") or 0) - float(candidate.get("entry_executable_price") or 0)) < 1e-9
        stop_ok = abs(float(virtual_pos.get("stop_price") or 0) - float(candidate.get("stop_price") or 0)) < 1e-6
        take_ok = abs(float(virtual_pos.get("take_price") or 0) - float(candidate.get("take_price") or 0)) < 1e-6
        if qty_ok and px_ok and stop_ok and take_ok:
            self.baseline_match_count += 1
        else:
            self.baseline_divergence_count += 1
            self.research_valid = False
            self.errors.append(BASELINE_DIVERGENCE)

    def process_new_closes(self) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        trades = self.books.read_all("trades")
        for trade in trades:
            tid = str(trade.get("trade_id") or "")
            if not tid or tid in self.processed_closes:
                continue
            actions.append(self._close_trade(trade))
            self.processed_closes.add(tid)
            self.last_trade_close_timestamp = trade.get("exit_ts")
        self._save_checkpoint()
        self.write_health()
        return actions

    def _close_trade(self, trade: dict[str, Any]) -> dict[str, Any]:
        position_id = str(trade.get("position_id") or "")
        # Find candidate
        cand = None
        for row in reversed(self.store.read_all("candidate_snapshots")):
            if str(row.get("position_id")) == position_id:
                cand = row
                break
        if cand is None:
            return {"status": "NO_CANDIDATE", "trade_id": trade.get("trade_id")}

        outcome = build_quality_outcome(candidate=cand, trade=trade)
        self.store.append("quality_outcomes", outcome)

        # Attach outcome to decisions without mutating decision fields beyond outcome_* keys.
        # We append outcome linkage rows rather than rewriting history.
        for policy_id in POLICY_IDS:
            opens = [p for p in self.open_by_policy.get(policy_id, []) if str(p.get("position_id")) == position_id]
            decision_action = None
            risk_mult = 0.0
            for d in reversed(self.store.read_all("policy_decisions")):
                if d.get("candidate_id") == cand.get("candidate_id") and d.get("policy_id") == policy_id:
                    decision_action = d.get("action")
                    risk_mult = float(d.get("risk_multiplier") or 0.0)
                    break

            counterfactual_net = float(trade.get("net_pnl_usd") or 0.0)
            if decision_action in {"EXECUTE_FULL", "EXECUTE_REDUCED"} and opens:
                vpos = opens[0]
                vqty = float(vpos.get("quantity") or 0.0)
                cq = float(cand.get("quantity") or 0.0)
                net = scale_net_pnl(canonical_net=counterfactual_net, canonical_qty=cq, virtual_qty=vqty)
                # fees scale similarly for absolute amounts
                fees = scale_net_pnl(
                    canonical_net=float(trade.get("fees_usd") or 0.0),
                    canonical_qty=cq,
                    virtual_qty=vqty,
                )
                slip = scale_net_pnl(
                    canonical_net=float(trade.get("slippage_usd") or 0.0),
                    canonical_qty=cq,
                    virtual_qty=vqty,
                )
                self.store.append(
                    "virtual_trades",
                    {
                        "policy_id": policy_id,
                        "candidate_id": cand.get("candidate_id"),
                        "virtual_position_id": vpos.get("virtual_position_id"),
                        "trade_id": trade.get("trade_id"),
                        "timeframe": cand.get("timeframe"),
                        "side": cand.get("side"),
                        "entry_timestamp": vpos.get("entry_timestamp"),
                        "entry_price": vpos.get("entry_executable_price"),
                        "exit_timestamp": trade.get("exit_ts"),
                        "exit_price": trade.get("exit_price"),
                        "exit_reason": trade.get("exit_reason"),
                        "quantity": vqty,
                        "risk_amount_usd": vpos.get("risk_amount_usd"),
                        "gross_pnl_usd": scale_net_pnl(
                            canonical_net=float(trade.get("gross_pnl_usd") or 0.0),
                            canonical_qty=cq,
                            virtual_qty=vqty,
                        ),
                        "fees_usd": fees,
                        "slippage_usd": slip,
                        "net_pnl_usd": net,
                        "status": "CLOSED",
                    },
                )
                self.store.append(
                    "virtual_positions",
                    {
                        **vpos,
                        "status": "CLOSED",
                        "exit_timestamp": trade.get("exit_ts"),
                        "exit_price": trade.get("exit_price"),
                        "exit_reason": trade.get("exit_reason"),
                        "closed_at": utc_now(),
                    },
                )
                apply_realized(
                    self.sleeves,
                    policy_id=policy_id,
                    timeframe=str(cand.get("timeframe")),
                    net_pnl_usd=net,
                )
                self.open_by_policy[policy_id] = [
                    p for p in self.open_by_policy.get(policy_id, []) if str(p.get("position_id")) != position_id
                ]
                if policy_id == "BASELINE_ALL_ELIGIBLE":
                    if abs(net - counterfactual_net) < 1e-6:
                        self.baseline_match_count += 1
                    else:
                        self.baseline_divergence_count += 1
                        self.research_valid = False
                        self.errors.append(BASELINE_DIVERGENCE)
                # Marginal: with vs without = net vs 0 for this policy path
                marg = marginal_contribution(
                    with_candidate_net_pnl=net,
                    without_candidate_net_pnl=0.0,
                    with_candidate_peak_equity=None,
                    without_candidate_peak_equity=None,
                    with_candidate_trough_equity=None,
                    without_candidate_trough_equity=None,
                    risk_used_usd=float(vpos.get("risk_amount_usd") or 0.0),
                    capital_used_usd=float(vpos.get("notional_usd") or 0.0),
                    blocked=False,
                    counterfactual_net_pnl=None,
                )
                self.store.append(
                    "policy_decisions",
                    {
                        "policy_id": policy_id,
                        "candidate_id": cand.get("candidate_id"),
                        "record_type": "OUTCOME_ATTACHMENT",
                        "attached_at": utc_now(),
                        "decision_immutable": True,
                        "outcome": outcome,
                        "marginal_contribution": marg,
                        "original_action": decision_action,
                        "risk_multiplier": risk_mult,
                    },
                )
            else:
                # Blocked: keep counterfactual
                marg = marginal_contribution(
                    with_candidate_net_pnl=0.0,
                    without_candidate_net_pnl=0.0,
                    with_candidate_peak_equity=None,
                    without_candidate_peak_equity=None,
                    with_candidate_trough_equity=None,
                    without_candidate_trough_equity=None,
                    risk_used_usd=0.0,
                    capital_used_usd=0.0,
                    blocked=True,
                    counterfactual_net_pnl=counterfactual_net,
                )
                self.store.append(
                    "policy_decisions",
                    {
                        "policy_id": policy_id,
                        "candidate_id": cand.get("candidate_id"),
                        "record_type": "OUTCOME_ATTACHMENT",
                        "attached_at": utc_now(),
                        "decision_immutable": True,
                        "counterfactual_outcome": outcome,
                        "marginal_contribution": marg,
                        "original_action": decision_action or "BLOCK_CORRELATED_EXPOSURE",
                    },
                )
        return {"status": "CLOSED", "trade_id": trade.get("trade_id"), "candidate_id": cand.get("candidate_id")}

    def poll_once(self) -> dict[str, Any]:
        entries = self.process_new_entries()
        closes = self.process_new_closes()
        enrichments = self.backfill_enrichments()
        return {"entries": len(entries), "closes": len(closes), "enrichments": len(enrichments)}

    def same_direction_clusters(self) -> dict[str, Any]:
        opens = _latest_positions(self.books.read_all("positions"))
        long_n = sum(1 for p in opens if str(p.get("side")).upper() == "LONG")
        short_n = sum(1 for p in opens if str(p.get("side")).upper() == "SHORT")
        return {
            "BTC_LONG": long_n,
            "BTC_SHORT": short_n,
            "open_positions": [
                {"timeframe": p.get("timeframe"), "side": p.get("side"), "position_id": p.get("position_id")}
                for p in opens
            ],
        }

    def virtual_open_counts(self) -> dict[str, int]:
        return {pid: len(self.open_by_policy.get(pid) or []) for pid in POLICY_IDS}

    def _enrichment_status(self, enrich_summary: dict[str, Any]) -> str:
        if self.write_boundary_violation_count:
            return STATUS_ENRICHMENT_WRITE
        if self.baseline_divergence_count:
            return STATUS_ENRICHMENT_BASELINE
        if self.lookahead_violation_count:
            return STATUS_ENRICHMENT_LOOKAHEAD
        if int(enrich_summary.get("ambiguous_timestamp_count") or 0) > 0 and int(
            enrich_summary.get("valid_feature_count") or 0
        ) == 0:
            return STATUS_ENRICHMENT_AMBIGUOUS
        if int(enrich_summary.get("valid_feature_count") or 0) > 0 and int(
            enrich_summary.get("missing_feature_count") or 0
        ) > 0:
            return STATUS_ENRICHMENT_PARTIAL
        if int(enrich_summary.get("valid_feature_count") or 0) > 0:
            return STATUS_ENRICHMENT_ACTIVE
        if int(enrich_summary.get("enriched_candidate_count") or 0) > 0:
            return STATUS_ENRICHMENT_PARTIAL
        return STATUS_ACTIVE

    def write_health(self) -> dict[str, Any]:
        # lag vs paper health tip
        lag = None
        paper_health_path = self.repo / "data" / "runtime" / "intrabar_paper_health.json"
        if paper_health_path.exists() and self.last_candidate_timestamp:
            try:
                ph = json.loads(paper_health_path.read_text(encoding="utf-8"))
                tip = parse_ts(ph.get("updated_at"))
                last = parse_ts(self.last_candidate_timestamp)
                if tip and last:
                    lag = max(0.0, (tip - last).total_seconds())
            except Exception:
                lag = None
        enrich_rows = self.store.read_all("candidate_feature_enrichments")
        # Deduplicate by candidate_id keeping latest
        latest_enrich: dict[str, dict[str, Any]] = {}
        for row in enrich_rows:
            cid = str(row.get("candidate_id") or "")
            if cid:
                latest_enrich[cid] = row
        enrich_summary = summarize_enrichment_health(list(latest_enrich.values()))
        enrich_summary["future_row_rejected_count"] = max(
            int(enrich_summary.get("future_row_rejected_count") or 0),
            int(getattr(self.enricher, "future_row_rejected_count", 0) or 0),
        )
        enrich_summary["wrong_timeframe_rejected_count"] = max(
            int(enrich_summary.get("wrong_timeframe_rejected_count") or 0),
            int(getattr(self.enricher, "wrong_timeframe_rejected_count", 0) or 0),
        )
        enrich_summary["ambiguous_timestamp_count"] = max(
            int(enrich_summary.get("ambiguous_timestamp_count") or 0),
            int(getattr(self.enricher, "ambiguous_timestamp_count", 0) or 0),
        )
        if self.last_enrichment_timestamp:
            enrich_summary["last_enrichment_timestamp"] = self.last_enrichment_timestamp

        status = self._enrichment_status(enrich_summary)
        if not self.research_valid and self.baseline_divergence_count:
            status = STATUS_ENRICHMENT_BASELINE
        elif self.lookahead_violation_count:
            status = STATUS_ENRICHMENT_LOOKAHEAD

        payload = {
            "mode": "OBSERVE_ONLY",
            "read_only": True,
            "enforcement_enabled": False,
            "quality_scoring_enabled": False,
            "command_bus_write_capability": False,
            "status": status,
            "eqcorr1_status": STATUS_ACTIVE if self.research_valid and self.lookahead_violation_count == 0 else (
                LOOKAHEAD_VIOLATION if self.lookahead_violation_count else BASELINE_DIVERGENCE
            ),
            "source_epoch_id": self.epoch_id,
            "source_contract_fingerprint": self.source_fp,
            "parent_trading_contract_fingerprint": self.parent_fp,
            "last_candidate_timestamp": self.last_candidate_timestamp,
            "last_trade_close_timestamp": self.last_trade_close_timestamp,
            "lag_seconds": lag if lag is not None else FIELD_NOT_AVAILABLE,
            "candidate_count": len(self.processed_candidates),
            "closed_outcome_count": len(self.processed_closes),
            "open_virtual_positions": sum(self.virtual_open_counts().values()),
            "virtual_open_by_policy": self.virtual_open_counts(),
            "same_direction_clusters": self.same_direction_clusters(),
            "baseline_match_count": self.baseline_match_count,
            "baseline_divergence_count": self.baseline_divergence_count,
            "lookahead_violation_count": self.lookahead_violation_count,
            "write_boundary_violation_count": self.write_boundary_violation_count,
            "research_valid": self.research_valid,
            **enrich_summary,
            "cognition_enrichment": "ACTIVE",
            "updated_at": utc_now(),
            "errors": self.errors[-20:],
        }
        self.store.write_json("health.json", payload)
        return payload
