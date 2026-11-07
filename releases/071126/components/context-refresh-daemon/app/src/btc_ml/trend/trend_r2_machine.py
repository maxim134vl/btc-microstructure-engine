"""Pure reducer of explicitly qualified fixtures. No orders or price formulas."""
from dataclasses import dataclass, field, asdict
from copy import deepcopy
from .trend_r2_contract import VERSION, TFS, Phase, OpportunityState, QualifiedMarketEvidence, digest

@dataclass
class TFState:
    direction: str='NONE'
    context_episode_id: str | None=None
    trend_phase: str | None=None
    observe_seen: bool=True
    last_market_order: tuple | None=None
    last_opportunity_evidence_key: str | None=None
    active_opportunity_id: str | None=None

@dataclass
class State:
    algorithm_version: str=VERSION
    timeframes: dict=field(default_factory=lambda:{tf:TFState() for tf in TFS})
    opportunities: dict=field(default_factory=dict)
    seen_events: dict=field(default_factory=dict)
    used_boundaries: dict=field(default_factory=dict)
    receipts: dict=field(default_factory=dict)
    def to_dict(self): return asdict(self)

@dataclass(frozen=True)
class Evaluation:
    status: str
    reason: str
    opportunity_id: str | None=None
    entry_eligible: bool=False  # Local experimental eligibility only, never a live permission.

def evaluate(state, request):
    """Return new state + result. The caller's committed state is never mutated."""
    s=deepcopy(state)
    def reject(reason): return state,Evaluation('REJECTED',reason)
    if request.get('qualification_error'): return reject('QUALIFIER_FAILED')
    kind=request.get('kind')
    if kind=='market':
        try: e=QualifiedMarketEvidence.from_dict(request['evidence'])
        except (KeyError,TypeError,ValueError): return reject('INVALID_ENVELOPE')
        invalid=e.validate()
        if invalid: return reject(invalid)
        if e.evidence_status!='QUALIFIED' or (e.origin,e.eligibility_status) not in (('FIXTURE_ONLY','ELIGIBLE_FIXTURE_ONLY'),('PAPER_OBSERVED','ELIGIBLE_PAPER_OBSERVED')): return reject('NOT_QUALIFIED')
        key,fp=e.dedup_key,e.fingerprint
        if key in s.seen_events:
            if s.seen_events[key]!=fp: return reject('CONFLICTING_SOURCE_RECORD')
            return state,Evaluation('DUPLICATE','SAME_EVIDENCE')
        t=s.timeframes[e.timeframe]
        if t.last_market_order is not None and e.ordering_key<=t.last_market_order: return reject('LATE_OR_OUT_OF_ORDER')
        typ=e.event_type; old=t.trend_phase; opportunity_id=None
        if typ=='OBSERVE':
            if old not in (None,'BROKEN') or e.direction!='NONE': return reject('INVALID_TRANSITION')
            t.direction='NONE'; t.observe_seen=True
        elif typ=='FORMING':
            if old not in (None,'BROKEN') or not t.observe_seen or e.direction=='NONE': return reject('INVALID_TRANSITION')
            if t.context_episode_id==e.context_episode_id: return reject('NEW_EPISODE_LINEAGE_REQUIRED')
            t.direction=e.direction; t.context_episode_id=e.context_episode_id; t.trend_phase='FORMING'; t.observe_seen=False
        else:
            if t.context_episode_id!=e.context_episode_id or t.direction!=e.direction or e.direction=='NONE': return reject('OWN_CONTEXT_MISMATCH')
            required={'CONFIRM':('FORMING',),'CONTINUE':('CONFIRMED','ACTIVE'),
                'WEAKEN':('CONFIRMED','ACTIVE'),'EXHAUST':('WEAKENING','ACTIVE','CONFIRMED'),
                'REACTIVATE':('WEAKENING','EXHAUSTED'),'CONFIRM_REACTIVATION':('REACTIVATING','WEAKENING'),
                'NEW_INITIATIVE':('ACTIVE',),'BREAK':('FORMING','CONFIRMED','ACTIVE','WEAKENING','EXHAUSTED','REACTIVATING'),
                'CONTEXT_RECOVERY':('ACTIVE','WEAKENING','EXHAUSTED')}
            if old not in required.get(typ,()): return reject('INVALID_TRANSITION')
            if typ in ('CONFIRM','CONFIRM_REACTIVATION','NEW_INITIATIVE'):
                if not e.independent_verified: return reject('INDEPENDENCE_NOT_QUALIFIED')
                boundary=digest([e.timeframe,e.independent_boundary_id])
                if boundary in s.used_boundaries: return reject('BOUNDARY_ALREADY_USED')
                previous=t.last_opportunity_evidence_key
                if typ!='CONFIRM' and (not previous or e.parent_evidence_key!=previous or key==previous): return reject('MISSING_INDEPENDENT_LINEAGE')
                if any(o['timeframe']==e.timeframe and o['state']=='PENDING' for o in s.opportunities.values()): return reject('PENDING_OPPORTUNITY')
                if t.active_opportunity_id:
                    current=s.opportunities[t.active_opportunity_id]
                    if current['state']=='PENDING': return reject('PENDING_OPPORTUNITY')
                    if current['state']=='ARMED': current['state']='EXPIRED'
                t.trend_phase='CONFIRMED' if typ=='CONFIRM' else 'ACTIVE'
                transition=digest([VERSION,e.timeframe,old,t.trend_phase,key])
                opportunity_id=digest([VERSION,e.timeframe,e.context_episode_id,e.direction,key])
                s.opportunities[opportunity_id]={'opportunity_id':opportunity_id,'source_evidence_id':key,
                    'timeframe':e.timeframe,'context_episode_id':e.context_episode_id,'direction':e.direction,
                    'phase_transition_id':transition,'state':'ARMED','consumed_by_position_id':None,
                    'consumed_by_order_id':None,'settlement':None,'settlement_event_id':None,
                    'exchange_event_time':e.exchange_event_time,'qualification_time':e.qualification_time,
                    'publication_time':e.publication_time,'origin':e.origin}
                t.last_opportunity_evidence_key=key; t.active_opportunity_id=opportunity_id
                s.used_boundaries[boundary]=opportunity_id
            else:
                t.trend_phase={'CONTINUE':'ACTIVE','WEAKEN':'WEAKENING','EXHAUST':'EXHAUSTED',
                    'REACTIVATE':'REACTIVATING','BREAK':'BROKEN','CONTEXT_RECOVERY':old}[typ]
                if typ in ('WEAKEN','EXHAUST','BREAK'):
                    for o in s.opportunities.values():
                        if o['timeframe']==e.timeframe and o['state']=='ARMED': o['state']='INVALIDATED'
                        elif o['timeframe']==e.timeframe and o['state']=='PENDING':
                            o.setdefault('validity_loss_evidence',[]).append({'source_evidence_key':key,'fingerprint':fp,'event_type':typ,'qualification_time':e.qualification_time,'publication_time':e.publication_time,'original_request_receipt':o['accepted_request_receipt']})
                if typ=='BREAK': t.direction='NONE'; t.observe_seen=False
        s.seen_events[key]=fp; t.last_market_order=e.ordering_key
        return s,Evaluation('ACCEPTED','QUALIFIED_PAPER_TRANSITION' if e.origin=='PAPER_OBSERVED' else 'QUALIFIED_FIXTURE_TRANSITION',opportunity_id,opportunity_id is not None)

    if kind in ('request','outcome','expire'):
        tf=request.get('timeframe'); oid=request.get('opportunity_id'); rid=request.get('event_id')
        if tf not in TFS or not isinstance(rid,str) or not rid: return reject('MISSING_RECEIPT_IDENTITY')
        o=s.opportunities.get(oid)
        if not o or o['timeframe']!=tf: return reject('OPPORTUNITY_OWNERSHIP_MISMATCH')
        receipt_key=digest([tf,rid]); receipt_fp=digest(request)
        if receipt_key in s.receipts:
            if s.receipts[receipt_key]!=receipt_fp: return reject('CONFLICTING_RECEIPT')
            return state,Evaluation('DUPLICATE','SAME_RECEIPT',oid)
        t=s.timeframes[tf]
        if kind=='request':
            if o['state']!='ARMED' or t.trend_phase not in ('CONFIRMED','ACTIVE') or t.active_opportunity_id!=oid: return reject('NO_ELIGIBLE_OPPORTUNITY')
            order=request.get('order_id')
            if not isinstance(order,str) or not order: return reject('MISSING_ORDER_ID')
            o['state']='PENDING'; o['consumed_by_order_id']=order; o['accepted_request_receipt']={'receipt_key':receipt_key,'receipt_fingerprint':receipt_fp,'event_id':rid,'order_id':order,'request_payload':deepcopy(request)}
        elif kind=='expire':
            if o['state']!='ARMED': return reject('INVALID_OPPORTUNITY_TRANSITION')
            o['state']='EXPIRED'
        else:
            outcome=request.get('outcome'); position=request.get('position_id'); order=request.get('order_id')
            if not isinstance(position,str) or not position or order!=o['consumed_by_order_id']: return reject('MISSING_OR_CONFLICTING_EXECUTION_IDENTITY')
            if outcome=='FILLED':
                if o['state']!='PENDING': return reject('INVALID_OPPORTUNITY_TRANSITION')
                accepted=o.get('accepted_request_receipt',{})
                payload=accepted.get('request_payload')
                if not isinstance(payload,dict) or not isinstance(payload.get('event_id'),str) or not payload['event_id'] or (payload.get('kind'),payload.get('timeframe'),payload.get('opportunity_id'),payload.get('order_id'))!=('request',tf,oid,order): return reject('PENDING_REQUEST_RECEIPT_UNPROVEN')
                if accepted.get('order_id')!=order or accepted.get('event_id')!=payload['event_id'] or accepted.get('receipt_key')!=digest([tf,payload['event_id']]) or accepted.get('receipt_fingerprint')!=digest(payload) or s.receipts.get(accepted['receipt_key'])!=accepted['receipt_fingerprint']: return reject('PENDING_REQUEST_RECEIPT_UNPROVEN')
                o['state']='CONSUMED'; o['consumed_by_position_id']=position
            elif outcome in ('TP','SL','CLOSE'):
                if o['state']!='CONSUMED' or o['consumed_by_position_id']!=position or o['settlement'] is not None: return reject('INVALID_SETTLEMENT')
                o['settlement']=outcome; o['settlement_event_id']=rid
            else: return reject('UNKNOWN_EXECUTION_OUTCOME')
        s.receipts[receipt_key]=receipt_fp
        return s,Evaluation('ACCEPTED','OPPORTUNITY_BOOKKEEPING_ONLY',oid)
    return reject('UNKNOWN_REQUEST')
