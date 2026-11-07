"""Own-context integration of Living Process metadata and native DRA/R2 reducers.

This interface never creates a new numeric strength formula, classifies a phase
from a score, grants REAL entry authority, or writes financial state. The numeric
input is the existing Final/Lifecycle ``process_strength``. Its existing controller
uses remain authoritative; the proposed replacement OPEN policy is not approved.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import math
import json
from typing import Any, Mapping

from .trend_evidence import DUR
from .trend_journal import Blocked, digest
from .trend_scope_sessions import bind, head, view
from .trend_research_system import ResearchSystem

VERSION = "CONTEXT_TREND_INTEGRATION_V1"
ENTRY_EFFECT = "UNAPPROVED_NOT_APPLIED"


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("TREND_UTC_REQUIRED")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class TrendDecisionInput:
    """Separate lineage metadata; never a risk contract or execution permission."""

    timeframe: str
    numeric_process_strength: float | None
    living_process: str | None
    metadata: dict[str, Any]
    qualifier: str = "NOT_QUALIFIED"
    entry_effect: str = ENTRY_EFFECT


class ContextTrendIntegration:
    """Application attachment without implicit journal creation or scope genesis.

    Sources must be the accepted ResearchSystem. Caller-selected, committed C_E/
    C_P state is read at consumption. Explicit ingest/handoff methods invoke the
    original reducers, with their original authority and PENDING checks. Merely
    constructing a manager does not initialize a research or economic ledger.
    """

    def __init__(self, systems: Mapping[str, ResearchSystem] | None = None, *, context_phases=None) -> None:
        if context_phases is not None:
            from .context_phase_qualification import ContextPhaseQualifier
            from btc_ml.external_traders.context_phase_publication import PublishedContextPhaseReader
            if type(context_phases) not in (ContextPhaseQualifier, PublishedContextPhaseReader):
                raise TypeError("NATIVE_CONTEXT_PHASE_QUALIFIER_REQUIRED")
        self.context_phases = context_phases
        self._systems = dict(systems or {})
        for tf, system in self._systems.items():
            if tf not in DUR or not isinstance(system, ResearchSystem):
                raise TypeError("ACCEPTED_OWN_TF_RESEARCH_SYSTEM_REQUIRED")
            if tf not in system.state["config"]["timeframes"]:
                raise ValueError("TREND_SYSTEM_OWN_TF_UNAVAILABLE")

    @classmethod
    def from_context_publication(cls, root, systems=None):
        """Explicit environment root; no genesis, write or implicit OPEN authority."""
        from btc_ml.external_traders.context_phase_publication import PublishedContextPhaseReader
        return cls(systems, context_phases=PublishedContextPhaseReader(root))

    def attach_context_publication(self, root):
        """Read-only attachment at the existing manager launcher's explicit root."""
        from btc_ml.external_traders.context_phase_publication import PublishedContextPhaseReader
        if self.context_phases is not None:
            if (type(self.context_phases) is not PublishedContextPhaseReader
                    or self.context_phases.root != Path(root).resolve()):
                raise ValueError("CONTEXT_PHASE_PUBLICATION_ATTACHMENT_CONFLICT")
            return
        self.context_phases = PublishedContextPhaseReader(root)

    def _system(self, timeframe: str) -> ResearchSystem:
        if timeframe not in DUR:
            raise ValueError("TREND_OWN_TF_REQUIRED")
        if timeframe not in self._systems:
            raise Blocked("COMMITTED_TREND_LINEAGE_UNAVAILABLE")
        return self._systems[timeframe]

    def bind_context(self, timeframe: str, proof: Mapping[str, Any], cutoff: Any) -> dict:
        """H1 scope admission; authentic input cannot acquire fixture authority."""
        system = self._system(timeframe)
        if proof.get("timeframe") != timeframe:
            raise Blocked("TREND_SCOPE_OWN_TF_MISMATCH")
        snapshot = system.state
        predecessor = head(snapshot, timeframe)
        for session in snapshot.get("scope_sessions", {}).values():
            if (session["timeframe"] == timeframe and
                    session["proof"]["canonical_episode_id"] == proof.get("canonical_episode_id")):
                predecessor = session["predecessor"]
                break
        return bind(system, dict(proof), predecessor, _utc(cutoff).isoformat())

    def admit_scope(self, timeframe: str, request: Mapping[str, Any], cutoff: Any) -> dict:
        if request.get("timeframe") != timeframe:
            raise Blocked("TREND_ADMISSION_OWN_TF_MISMATCH")
        return self._system(timeframe).admit_scope(dict(request), _utc(cutoff).isoformat())

    def ingest(self, timeframe: str, packet: Mapping[str, Any], cutoff: Any) -> dict:
        """Original D1-D7/window economic calculation and source deduplication."""
        return self._system(timeframe).ingest(deepcopy(dict(packet)), _utc(cutoff).isoformat())

    def watermark(self, timeframe: str, closed_at: Any, cutoff: Any, coverage_ref: str) -> dict:
        return self._system(timeframe).watermark(
            timeframe, _utc(closed_at).isoformat(), _utc(cutoff).isoformat(), coverage_ref
        )

    def drain(self, timeframe: str) -> list:
        """Original bridge evaluates R2; REAL economic grant remains fail closed."""
        return self._system(timeframe).drain()

    def bookkeeping(self, timeframe: str, request: Mapping[str, Any]) -> dict:
        if request.get("timeframe") not in (None, timeframe):
            raise Blocked("TREND_BOOKKEEPING_OWN_TF_MISMATCH")
        return self._system(timeframe).bookkeeping(deepcopy(dict(request)))

    def evaluate(self, timeframe: str, state: Mapping[str, Any], cutoff: Any) -> TrendDecisionInput:
        """Read the same own Final state consumed by the ordinary decision path.

        A failed Trend binding cannot reinterpret a score or an old R2 phase as
        current authority. This reader grants no OPEN permission. The controller
        keeps its source/decision checks, uses the entry-only authorization gate
        for new OPEN, and preserves existing-position exit rules.
        """
        if timeframe not in DUR:
            raise ValueError("TREND_OWN_TF_REQUIRED")
        end = _utc(cutoff)
        supplied_tf = state.get("timeframe")
        reasons = []
        if supplied_tf != timeframe:
            reasons.append("OWN_TIMEFRAME_MISMATCH")
        try:
            from btc_ml.trading.timeframe_state_adapter import source_lifecycle_binding_reason

            binding_reason = source_lifecycle_binding_reason(state, timeframe=timeframe)
            if binding_reason:
                reasons.append(binding_reason)
            opened = _utc(state["source_bar_open"])
            closed = _utc(state["source_bar_close"])
            if closed > end:
                reasons.append("CONTEXT_NOT_AVAILABLE_AT_CUTOFF")
            for key in ("lifecycle_information_available_at", "information_available_at"):
                if state.get(key) is not None and _utc(state[key]) > end:
                    reasons.append("FUTURE_CONTEXT_INFORMATION")
        except (KeyError, TypeError, ValueError):
            opened = closed = None
            reasons.append("SOURCE_OWNERSHIP_UNAVAILABLE")
        episode = state.get("lifecycle_episode_id")
        if not episode or ":prov:" in str(episode).lower():
            reasons.append("CANONICAL_EPISODE_UNAVAILABLE")
        strength = state.get("process_strength")
        if strength is not None:
            try:
                strength = float(strength)
                if not math.isfinite(strength):
                    strength = None
                    reasons.append("NUMERIC_PROCESS_STRENGTH_UNAVAILABLE")
            except (TypeError, ValueError):
                strength = None
                reasons.append("NUMERIC_PROCESS_STRENGTH_UNAVAILABLE")
        if reasons:
            # An input from a different source row/TF is not this TF's numerical
            # authority either. Existing controller fail-closed checks remain.
            strength = None
        living = state.get("living_process")
        direction = state.get("timeframe_direction")
        metadata = {
            "version": VERSION,
            "timeframe": timeframe,
            "canonical_context_episode_id": episode,
            "canonical_direction": direction,
            "canonical_lifecycle_phase": state.get("lifecycle_phase"),
            "numeric_process_strength": strength,
            "numeric_strength_source": "OWN_FINAL_LIFECYCLE_PROCESS_STRENGTH",
            "living_process": living,
            "source_bar_open": opened.isoformat() if opened else state.get("source_bar_open"),
            "source_bar_close": closed.isoformat() if closed else state.get("source_bar_close"),
            "lifecycle_row_timestamp": state.get("lifecycle_row_timestamp"),
            "evaluation_cutoff": end.isoformat(),
            "trend_phase": None,
            "trend_phase_status": "NOT_PROVEN",
            "trend_phase_origin": None,
            "trend_phase_source": None,
            "trend_strength": None,
            "trend_strength_status": "NOT_AVAILABLE",
            "trend_strength_source": None,
            "native_entry_opportunity": None,
            "native_trend_direction": None,
            "context_information_available_at": str(state["lifecycle_information_available_at"]) if state.get("lifecycle_information_available_at") is not None else None,
            "context_publication_ref": state.get("context_publication_ref"),
            "context_actual_publication_at": str(state["actual_publication_at"]) if state.get("actual_publication_at") is not None else None,
            "economic_owner": None,
            "r2_lineage_ref": None,
            "pending_opportunity_ids": [],
            "source_gate": "NOT_PROVEN",
            "economic_gate": "NOT_PROVEN",
            "r2_admission_gate": "NO_REAL_ADMISSION",
            "qualifier": "NOT_QUALIFIED",
            "entry_effect": ENTRY_EFFECT,
            "real_entry_authority": "NO_ENTRY",
            "missing_open_contract": "ENTRY_VETO_POLICY_PROPOSED_NOT_APPROVED",
        }
        system = self._systems.get(timeframe)
        if system is None:
            reasons.append("COMMITTED_TREND_LINEAGE_UNAVAILABLE")
        elif not reasons:
            # Reading through the accepted journal validates every retained C_E/C_P
            # commit before the result is attached to a trading decision.
            snapshot = system.state
            current = view(system, timeframe)
            own = current["own_context"]
            identity = own.get("canonical_episode_id", own.get("id"))
            same_context = identity == episode and own.get("direction") == direction
            if not same_context:
                reasons.append("SYSTEM_CANONICAL_SCOPE_MISMATCH")
            elif _utc(own["available_at"]) > end:
                reasons.append("SYSTEM_SCOPE_FUTURE")
            elif any(_utc(raw["available_at"]) > end for raw in snapshot["raw"].values()) or any(
                _utc(record["action"][key]) > end
                for record in system.j.records
                for key in ("cutoff", "available_at")
                if record.get("action", {}).get(key)
            ):
                reasons.append("JOURNAL_HEAD_AFTER_CUTOFF")
            else:
                native_tf = snapshot["r2"]["timeframes"][timeframe]
                native_opportunity = snapshot["r2"]["opportunities"].get(
                    native_tf["active_opportunity_id"])
                # Resolve the ACTUAL accepted native event, not config.mode or a
                # caller's phase label. Economic/phase history is read-only.
                phase_source = None
                for record in reversed(system.j.records):
                    if record["boundary"] != "C_P" or record.get("action", {}).get("kind") != "PROJECT":
                        continue
                    attempt = record["action"].get("attempt")
                    intent = snapshot["intents"].get(attempt)
                    if (intent and intent["timeframe"] == timeframe
                            and snapshot["projection_results"].get(attempt, {}).get("status") == "ACCEPTED"):
                        phase_source = deepcopy(intent["r2_payload"])
                        break
                phase_origin = phase_source.get("origin") if phase_source else None
                if phase_source and _utc(phase_source["publication_time"]) > end:
                    reasons.append("TREND_PHASE_SOURCE_AFTER_CUTOFF")
                    phase_source = None
                    phase_origin = None
                metadata.update({
                    "trend_phase": current["current_phase"] if phase_source else None,
                    "trend_phase_status": "NATIVE_COMMITTED" if phase_source and current["current_phase"] else "NOT_PROVEN",
                    "trend_phase_origin": phase_origin,
                    "trend_phase_source": phase_source,
                    "native_entry_opportunity": deepcopy(native_opportunity),
                    "native_trend_direction": native_tf["direction"],
                    "economic_owner": current["current_owner"],
                    "historical_owner": current["historical_owner"],
                    "r2_lineage_ref": current["r2_lineage_ref"],
                    "pending_opportunity_ids": current["obligation_ledger_ref"]["pending_ids"],
                    "scope_ref": current["session_id"],
                    "scope_admission_refs": current["scope_admission_refs"],
                    "economic_ancestry_preserved": True,
                    "committed_state_sha": digest(snapshot),
                    "committed_journal_head": system.j.records[-1]["sha"],
                    "source_gate": snapshot["config"]["mode"],
                    "economic_gate": current["current_economic_authority"],
                    "r2_pending_reset": False,
                })
        # Context phase is a separate axis. It never mutates or relabels R2.
        metadata["native_r2_phase"] = metadata["trend_phase"]
        metadata["context_trend_phase"] = None
        if self.context_phases is not None:
            context = self.context_phases.read(timeframe, state, cutoff)
            metadata["context_trend"] = context
            metadata["context_trend_phase"] = context["context_trend_phase"]
        metadata["binding_reasons"] = sorted(set(reasons))
        return TrendDecisionInput(timeframe, strength, living, metadata)

    def paper_enabled(self, timeframe):
        system = self._systems.get(timeframe)
        return bool(system and system.state['config'].get('paper_permission'))

    def paper_permission(self, timeframe, cutoff):
        from .real_scope_proof import paper_permission
        return paper_permission(self._system(timeframe).state['config'], str(cutoff))

    def paper_command_reason(self, command, *, pending_retry=True):
        """Re-read native context and journal; persisted ALLOW is not authority."""
        from datetime import datetime, timezone
        from btc_ml.runtime.financial_trend_environment import load_own_inputs
        from btc_ml.trading.timeframe_state_adapter import resolve_timeframe_state
        from .entry_kill_switch import EntryOnlyKillSwitch
        from .real_scope_proof import paper_segment
        tf = str(command.get('timeframe', '')).upper()
        cutoff = datetime.now(timezone.utc).isoformat()
        permission = self.paper_permission(tf, cutoff)
        root = self.context_phases.root if self.context_phases is not None else None
        if root is None or Path(permission['context_root']).resolve() != root:
            return 'PAPER_CONTEXT_ROOT_MISMATCH'
        sources, _ = load_own_inputs(root)
        state = resolve_timeframe_state(timeframe=tf, evaluation_timestamp=cutoff, sources=sources, now=cutoff, prefer_forming=False)
        candidate = {'timeframe': tf, 'side': str(command.get('intent', '')).removeprefix('OPEN_'),
            'canonical_episode_id': command.get('lifecycle_episode_id'),
            'source_bar_open': command.get('source_bar_open'), 'source_bar_close': command.get('source_bar_close')}
        metadata = command.get('cross_timeframe_metadata') or {}
        if isinstance(metadata, str): metadata = json.loads(metadata)
        refs = (metadata.get('entry_kill_switch') or {}).get('evidence_refs') or {}
        expected = refs.get('native_entry_opportunity') or {}
        snapshot = self._system(tf).state
        opportunity = snapshot['r2']['opportunities'].get(expected.get('opportunity_id'))
        if not opportunity:
            return 'PAPER_ORIGINAL_OPPORTUNITY_REQUIRED'
        if opportunity.get('state') == 'PENDING' and pending_retry:
            request = {'kind': 'request', 'timeframe': tf, 'opportunity_id': opportunity['opportunity_id'],
                'event_id': 'PAPER_REQUEST:' + str(command['command_id']), 'order_id': 'S41:' + str(command['command_id'])}
            from .trend_evidence import evaluate, r2_restore
            _, receipt = evaluate(r2_restore(snapshot['r2']), request)
            if receipt.status != 'DUPLICATE':
                return 'PAPER_PENDING_FOREIGN_REQUEST'
            # Exact retry of an already accepted request, never another OPEN.
            # M4/context/source checks are still revalidated below.
            veto = EntryOnlyKillSwitch().evaluate_paper(candidate, state, self, cutoff, pending_command=str(command['command_id']))
            return veto.reason if veto.decision != 'ALLOW' else None
        veto = EntryOnlyKillSwitch().evaluate_paper(candidate, state, self, cutoff)
        if veto.decision != 'ALLOW': return veto.reason
        actual = veto.evidence_refs['native_entry_opportunity']
        if actual['opportunity_id'] != opportunity['opportunity_id']:
            return 'PAPER_SUPERSEDED_OPPORTUNITY'
        return None

    def reserve_paper_command(self, command):
        from datetime import datetime, timezone
        reason = self.paper_command_reason(command)
        if reason: raise Blocked(reason)
        tf = command['timeframe']
        metadata = command.get('cross_timeframe_metadata') or {}
        if isinstance(metadata, str): metadata = json.loads(metadata)
        # Reserve exactly the opportunity carried by this accepted command.
        # A concurrent new initiative must not silently replace its identity.
        refs = (metadata.get('entry_kill_switch') or {}).get('evidence_refs') or {}
        oid = (refs.get('native_entry_opportunity') or {}).get('opportunity_id')
        if not oid: raise Blocked('PAPER_ORIGINAL_OPPORTUNITY_REQUIRED')
        request = {'kind': 'request', 'timeframe': tf, 'opportunity_id': oid,
            'event_id': 'PAPER_REQUEST:' + str(command['command_id']),
            'order_id': 'S41:' + str(command['command_id'])}
        result = self.bookkeeping(tf, request)
        if result['status'] not in ('ACCEPTED', 'DUPLICATE'):
            raise Blocked('PAPER_R2_REQUEST_' + result['reason'])
        return result

    def reconcile_paper_execution(self, engine, commands):
        """Financial is authoritative; only R2 bookkeeping is written here.

        S41 routing request IDs and native financial order IDs are separate and
        explicitly linked in the C_P outcome. No fills/PnL/receipts are created.
        """
        from .real_scope_proof import paper_permission
        from btc_ml.trading.intrabar_paper import execution_commit as ec
        with engine.books.exclusive():
            head = ec.verify_committed_head(engine.epoch_root, engine.epoch.paper_epoch_id)
            head_sha256 = ec.digest((engine.epoch_root/'execution_commits_v1/head.json').read_bytes())
            books = {name: engine.books.read_all(name) for name in ('commands', 'fills', 'trades')}
        for command in commands:
            if str(command.get('intent')) not in ('OPEN_LONG', 'OPEN_SHORT'): continue
            tf = command['timeframe']
            if not self.paper_enabled(tf): continue
            permission = self.paper_permission(tf, datetime.now(timezone.utc).isoformat())
            if Path(permission['financial_root']).resolve() != engine.epoch_root.resolve():
                raise Blocked('PAPER_FINANCIAL_ROOT_MISMATCH')
            state = self._system(tf).state
            routing = 'S41:' + str(command['command_id'])
            opportunities = [o for o in state['r2']['opportunities'].values()
                if o['timeframe'] == tf and o.get('consumed_by_order_id') == routing]
            if not opportunities: continue
            if len(opportunities) != 1: raise Blocked('PAPER_REQUEST_NOT_UNIQUE')
            o = opportunities[0]
            entries = [c for c in books['commands'] if c.get('context_event_id') == command['command_id'] and c.get('action') == 'ENTRY' and c.get('timeframe') == tf]
            if not entries: continue
            if len(entries) != 1: raise Blocked('PAPER_FINANCIAL_COMMAND_NOT_UNIQUE')
            fills = [f for f in books['fills'] if f.get('command_id') == entries[0]['command_id'] and f.get('action') == 'ENTRY' and f.get('timeframe') == tf]
            if len(fills) != 1: raise Blocked('PAPER_FINANCIAL_FILL_NOT_UNIQUE')
            fill = fills[0]
            if o['state'] == 'PENDING':
                req = {'kind':'outcome','timeframe':tf,'opportunity_id':o['opportunity_id'],
                    'event_id':'PAPER_FILLED:'+str(command['command_id']),'order_id':routing,
                    'position_id':fill['position_id'],'outcome':'FILLED',
                    'financial_order_id':fill['order_id'],'financial_fill_id':fill['fill_id'],
                    'financial_head_sha256':head_sha256}
                result = self.bookkeeping(tf, req)
                if result['status'] != 'ACCEPTED': raise Blocked('PAPER_FILL_RECONCILIATION')
            updated = self._system(tf).state['r2']['opportunities'][o['opportunity_id']]
            if updated['state'] != 'CONSUMED' or updated['consumed_by_position_id'] != fill['position_id']:
                raise Blocked('PAPER_FINANCIAL_POSITION_BINDING')
            trades = [t for t in books['trades'] if t.get('position_id') == fill['position_id'] and t.get('timeframe') == tf]
            if len(trades) > 1: raise Blocked('PAPER_FINANCIAL_SETTLEMENT_NOT_UNIQUE')
            if trades and updated['settlement'] is None:
                trade = trades[0]; outcome = trade['exit_reason']
                if outcome not in ('SL','TP','CLOSE'): outcome = 'CLOSE'
                result = self.bookkeeping(tf, {'kind':'outcome','timeframe':tf,'opportunity_id':o['opportunity_id'],
                    'event_id':'PAPER_SETTLED:'+trade['trade_id'],'order_id':routing,
                    'position_id':fill['position_id'],'outcome':outcome,
                    'financial_trade_id':trade['trade_id'],'financial_head_sha256':head_sha256})
                if result['status'] != 'ACCEPTED': raise Blocked('PAPER_SETTLEMENT_RECONCILIATION')
