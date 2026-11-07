"""Entry-only interface, NOT an approval of the proposed economic OPEN policy.

The legacy runtime/economic authorization path remains closed by default. Original source, economic and R2 reducers
are unchanged; neither a phase label nor caller-supplied ALLOW grants admission.
This pure guard does not consume opportunities, create identities or settle R2.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any, Mapping

VERSION = 'ENTRY_ONLY_AUTHORIZATION_INTERFACE_V1'
POLICY = 'ENTRY_VETO_POLICY_PROPOSED_NOT_APPROVED'


@dataclass(frozen=True)
class EntryVetoResult:
    decision: str
    status: str
    reason: str
    candidate_identity: dict[str, Any]
    evidence_refs: dict[str, Any]
    policy_pin: str | None
    evaluation_cutoff: str
    version: str = VERSION

    def to_dict(self) -> dict:
        return asdict(self)


class EntryOnlyKillSwitch:
    """Fail closed until a separately approved, applicable policy is implemented.

    The signature retains the reviewed contract's policy/evidence boundaries.
    Arbitrary policy_pin strings, fixture evidence and JSON grants are not policy
    authority. No branches implementing the proposed economic restrictions are
    introduced by this integration. CLOSE/HOLD are outside this interface.
    """
    def __init__(self, *, paper_integration=None):
        self.paper_integration = paper_integration

    def evaluate(self, candidate: Mapping[str, Any], committed_evidence_view: Mapping[str, Any],
                 policy_pin: str | None, evaluation_cutoff: Any) -> EntryVetoResult:
        evidence = {key: committed_evidence_view.get(key) for key in (
            'trend_phase', 'economic_owner', 'historical_owner', 'r2_lineage_ref',
            'pending_opportunity_ids', 'scope_ref', 'scope_admission_refs',
            'committed_state_sha', 'committed_journal_head', 'source_gate',
            'economic_gate', 'r2_admission_gate', 'binding_reasons')}
        # Policy absence is a technical admission blocker, never fabricated BREAK,
        # WEAKENING, economic owner loss, or proof of no pre-existing initiative.
        return EntryVetoResult('NOT_QUALIFIED', 'NOT_AUTHORIZED', 'POLICY_NOT_APPROVED',
            dict(candidate), evidence, policy_pin, str(evaluation_cutoff))

    def command_admission_reason(self, command: Mapping[str, Any]) -> str | None:
        if str(command.get('intent') or '').upper() not in {'OPEN_LONG', 'OPEN_SHORT'}:
            return None
        # A persisted ALLOW field or historical pre-integration OPEN is not an
        # independently approved policy. Revalidation occurs at consumption.
        if self.paper_integration is not None:
            try:
                reason = self.paper_integration.paper_command_reason(command)
                return 'ENTRY_BLOCKED_' + reason if reason else None
            except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
                return 'ENTRY_BLOCKED_PAPER_' + str(exc)
        return 'ENTRY_BLOCKED_TREND_NOT_AUTHORIZED_POLICY_NOT_APPROVED'


    @staticmethod
    def _native_phase_veto_reason(candidate: Mapping[str, Any], view: Mapping[str, Any]) -> str | None:
        """Approved entry-only phase policy over an already bound native view.

        No phase is classified here. Opportunity checks mirror the original R2
        request prerequisites; CONTINUE never creates/rearms an opportunity.
        Tests may exercise this kernel with explicitly authored native fixtures;
        real callers use evaluate_native_context(), which reads the source itself.
        """
        phase = view.get('trend_phase')
        if phase is None:
            return 'TREND_PHASE_NOT_PROVEN'
        if phase not in ('FORMING', 'CONFIRMED', 'ACTIVE', 'WEAKENING', 'EXHAUSTED', 'REACTIVATING', 'BROKEN'):
            return 'TREND_PHASE_UNMAPPED'
        if phase not in ('CONFIRMED', 'ACTIVE'):
            return 'TREND_PHASE_' + phase + '_BLOCKS_ENTRY'
        if view.get('pending_opportunity_ids'):
            return 'TREND_NATIVE_OPPORTUNITY_PENDING'
        opportunity = view.get('native_entry_opportunity') or {}
        if (not opportunity.get('opportunity_id') or opportunity.get('state') != 'ARMED'
                or opportunity.get('consumed_by_order_id') is not None
                or opportunity.get('consumed_by_position_id') is not None):
            return 'TREND_NATIVE_OPPORTUNITY_NOT_ARMED'
        if (opportunity.get('timeframe') != candidate.get('timeframe')
                or opportunity.get('context_episode_id') != view.get('r2_lineage_ref')
                or opportunity.get('direction') != candidate.get('side')):
            return 'TREND_NATIVE_OPPORTUNITY_OWNERSHIP_MISMATCH'
        return None

    @staticmethod
    def _context_phase_veto_reason(context: Mapping[str, Any]) -> str | None:
        """M4 removes only this context veto; R2/consumer/OPEN remain separate."""
        if context.get('qualification') != 'LIVE_QUALIFIED':
            return 'CONTEXT_PHASE_' + str(context.get('qualification', 'NOT_PROVEN'))
        if not context.get('current_evidence'):
            return 'CONTEXT_PHASE_NO_CURRENT_EVIDENCE'
        if context.get('context_trend_phase') not in ('CONFIRMED', 'ACTIVE'):
            return 'CONTEXT_PHASE_BLOCKS_ENTRY'
        return None

    def evaluate_native_context(self, candidate: Mapping[str, Any], state: Mapping[str, Any],
                                integration: Any, evaluation_cutoff: Any) -> EntryVetoResult:
        """Prepared isolated policy: lift ONLY the Trend veto, never grant OPEN.

        Re-read the existing native attachment; persisted ALLOW/phase dictionaries
        are not trusted phase sources. Missing DRA/R2 blocks this gate without
        stopping own-TF context delivery or inventing a replacement classifier.
        """
        from .context_trend_integration import ContextTrendIntegration, _utc
        from .trend_journal import Blocked
        policy = 'OWNER_APPROVED_TREND_ENTRY_ONLY_V1'
        if not isinstance(integration, ContextTrendIntegration):
            return EntryVetoResult('BLOCK', 'TREND_VETO', 'NATIVE_TREND_ATTACHMENT_REQUIRED',
                dict(candidate), {}, policy, str(evaluation_cutoff))
        tf = candidate.get('timeframe')
        try:
            native = integration.evaluate(tf, state, evaluation_cutoff)
        except (ValueError, TypeError, KeyError, OSError, Blocked) as exc:
            return EntryVetoResult('BLOCK', 'TREND_VETO', 'TREND_CONTEXT_UNAVAILABLE',
                dict(candidate), {'binding_error': type(exc).__name__}, policy, str(evaluation_cutoff))
        view = native.metadata
        try:
            identity_ok = (candidate.get('timeframe') == view.get('timeframe')
                and candidate.get('canonical_episode_id') == view.get('canonical_context_episode_id')
                and candidate.get('side') == view.get('canonical_direction')
                and _utc(candidate.get('source_bar_open')) == _utc(view.get('source_bar_open'))
                and _utc(candidate.get('source_bar_close')) == _utc(view.get('source_bar_close')))
        except (ValueError, TypeError):
            identity_ok = False
        context = view.get('context_trend')
        context_reason = self._context_phase_veto_reason(context) if context is not None else None
        if not identity_ok:
            reason = 'TREND_OWN_CONTEXT_IDENTITY_MISMATCH'
        elif view.get('binding_reasons') and view['binding_reasons'] != ['COMMITTED_TREND_LINEAGE_UNAVAILABLE']:
            reason = 'TREND_CONTEXT_NOT_BOUND'
        elif context_reason:
            reason = context_reason
        elif view.get('trend_phase') is None:
            reason = 'TREND_PHASE_NOT_PROVEN'
        elif (view.get('trend_phase_status') != 'NATIVE_COMMITTED'
              or view.get('source_gate') != 'REAL_CANDIDATE'
              or view.get('trend_phase_origin') != 'REAL_CANDIDATE'):
            reason = 'TREND_PHASE_NOT_REAL_PROVEN'
        elif view.get('native_trend_direction') != candidate.get('side'):
            reason = 'TREND_NATIVE_DIRECTION_MISMATCH'
        else:
            reason = self._native_phase_veto_reason(candidate, view)
        evidence = {key: view.get(key) for key in (
            'timeframe', 'canonical_context_episode_id', 'canonical_direction',
            'source_bar_open', 'source_bar_close', 'context_information_available_at',
            'context_publication_ref', 'context_actual_publication_at', 'evaluation_cutoff',
            'trend_phase', 'trend_phase_status', 'trend_phase_origin', 'trend_phase_source',
            'trend_strength', 'trend_strength_status', 'native_entry_opportunity',
            'r2_lineage_ref', 'pending_opportunity_ids', 'scope_ref', 'scope_admission_refs',
            'committed_state_sha', 'committed_journal_head', 'source_gate', 'binding_reasons')}
        evidence['native_r2_phase'] = view.get('native_r2_phase')
        if context is not None:
            evidence['context_trend'] = context
            evidence['context_phase_veto'] = 'BLOCK' if context_reason else 'ALLOW_CONTEXT_VETO_ONLY'
        evidence['open_authority'] = 'UNCHANGED_NOT_GRANTED'
        return EntryVetoResult('BLOCK' if reason else 'ALLOW',
            'TREND_VETO' if reason else 'TREND_VETO_CLEARED_ONLY',
            reason or 'NATIVE_CONFIRMED_UNUSED_OPPORTUNITY', dict(candidate), evidence,
            policy, str(evaluation_cutoff))

    def evaluate_paper(self, candidate, state, integration, evaluation_cutoff, *, pending_command=None):
        """Owner-approved observed-scope PAPER. Default/REAL policy is unchanged."""
        from copy import deepcopy
        from pathlib import Path
        from .real_scope_proof import PAPER_CLASS, paper_segment
        from .trend_journal import Blocked, digest
        from .context_trend_integration import ContextTrendIntegration, _utc
        reason = None; refs = {}; permission = None
        try:
            if type(integration) is not ContextTrendIntegration: raise Blocked('PAPER_NATIVE_ATTACHMENT_REQUIRED')
            tf = candidate['timeframe']; permission = integration.paper_permission(tf, evaluation_cutoff)
            root = integration.context_phases.root if integration.context_phases is not None else None
            if root is None or root != Path(permission['context_root']).resolve(): raise Blocked('PAPER_CONTEXT_ROOT_MISMATCH')
            native = integration.evaluate(tf, state, evaluation_cutoff); view = native.metadata
            if view.get('binding_reasons'): raise Blocked('PAPER_CONTEXT_NOT_BOUND')
            if (candidate['canonical_episode_id'],candidate['side'],_utc(candidate['source_bar_open']),_utc(candidate['source_bar_close'])) != (view['canonical_context_episode_id'],view['canonical_direction'],_utc(view['source_bar_open']),_utc(view['source_bar_close'])): raise Blocked('PAPER_OWN_CONTEXT_IDENTITY')
            context = view.get('context_trend')
            if context is None: raise Blocked('PAPER_CONTEXT_PHASE_REQUIRED')
            if error := self._context_phase_veto_reason(context): raise Blocked(error)
            if view.get('trend_phase_origin') != 'PAPER_OBSERVED' or view.get('trend_phase_status') != 'NATIVE_COMMITTED': raise Blocked('PAPER_NATIVE_R2_NOT_QUALIFIED')
            system = integration._system(tf); snapshot = system.state
            opportunity = view.get('native_entry_opportunity') or {}
            segid = snapshot['admitted_segment_map'].get(opportunity.get('source_evidence_id'))
            segment = paper_segment(snapshot, snapshot['economic'].get(segid))
            if segment['id'] != snapshot['tf'][tf]['owner']: raise Blocked('PAPER_STALE_ECONOMIC_OWNER')
            if pending_command is not None:
                expected = 'S41:' + pending_command
                if opportunity.get('state') != 'PENDING' or opportunity.get('consumed_by_order_id') != expected: raise Blocked('PAPER_PENDING_FOREIGN_REQUEST')
                from .trend_evidence import evaluate,r2_restore
                req={'kind':'request','timeframe':tf,'opportunity_id':opportunity['opportunity_id'],'event_id':'PAPER_REQUEST:'+pending_command,'order_id':expected}
                _,receipt=evaluate(r2_restore(snapshot['r2']),req)
                if receipt.status!='DUPLICATE': raise Blocked('PAPER_PENDING_RECEIPT_UNPROVEN')
                if view['trend_phase'] not in ('CONFIRMED','ACTIVE'): raise Blocked('PAPER_PENDING_VALIDITY_LOST')
                if any(x!=opportunity['opportunity_id'] for x in view['pending_opportunity_ids']): raise Blocked('PAPER_OTHER_PENDING_OPPORTUNITY')
                if (opportunity['timeframe'],opportunity['context_episode_id'],opportunity['direction']) != (tf,view['r2_lineage_ref'],candidate['side']): raise Blocked('PAPER_PENDING_SCOPE_MISMATCH')
            elif error := self._native_phase_veto_reason(candidate, view): raise Blocked(error)
            refs = {k:view.get(k) for k in ('timeframe','native_entry_opportunity','canonical_context_episode_id','canonical_direction','source_bar_open','source_bar_close','context_trend','committed_journal_head','committed_state_sha','r2_lineage_ref')}
            refs.update(paper_contract=permission['contract'],paper_evidence_level=permission['evidence_level'],
                paper_permission_sha256=snapshot['config']['paper_permission']['sha256'],economic_segment_id=segment['id'],
                seed_relative_parent_id=segment['parent_id'],complete_venue_coverage=False,full_real_qualification=False)
        except (Blocked,ValueError,KeyError,TypeError,OSError,AttributeError) as exc:
            reason=str(exc)
        return EntryVetoResult('BLOCK' if reason else 'ALLOW','PAPER_OBSERVED_ONLY',reason or 'PAPER_QUALIFIED_UNUSED_OPPORTUNITY',dict(candidate),refs,permission['contract'] if permission else None,str(evaluation_cutoff))
