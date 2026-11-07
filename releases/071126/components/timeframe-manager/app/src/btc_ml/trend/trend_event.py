"""Pure DRA-EVENT hypothesis over frozen, non-overlapping trade windows.

NOT a trading FSM, recorder, automatic live window selector or REAL qualifier.
The caller supplies causally frozen window boundaries and baseline/context proof.
Only synthetic fixtures can project into the unchanged R2 pure interfaces.
"""
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, getcontext, localcontext
from hashlib import sha256
import json
from collections import OrderedDict
from functools import lru_cache

VERSION = 'DRA_INTRABAR_CAUSAL_COMPARISON_V1_EVENT'
PARAMETER_STATUS = 'RESEARCH_UNCALIBRATED'
DUR = {'M15':900, 'M30':1800, 'H1':3600, 'H4':14400}
EPS = Decimal('0.000001')

def canonical(x): return json.dumps(x,sort_keys=True,separators=(',', ':'),allow_nan=False)
def digest(x): return sha256(canonical(x).encode()).hexdigest()
def utc(x):
    t=datetime.fromisoformat(x.replace('Z','+00:00'))
    if t.tzinfo is None or t.utcoffset().total_seconds()!=0: raise ValueError('UTC_REQUIRED')
    return t.astimezone(timezone.utc)
def dec(x):
    if not isinstance(x,str): raise ValueError('DECIMAL_TEXT_REQUIRED')
    v=Decimal(x)
    if not v.is_finite(): raise ValueError('FINITE_REQUIRED')
    return v

@dataclass(frozen=True)
class Trade:
    market: str
    symbol: str
    stream: str
    native_id: int
    trade_time: str
    exchange_event_time: str
    receive_time: str
    price: str
    quantity: str
    buyer_is_maker: bool
    payload_sha: str
    @property
    def source_key(self): return f'{self.market}:{self.symbol}:{self.stream}:{self.native_id}'
    @property
    def core(self): return {k:v for k,v in asdict(self).items() if k not in ('payload_sha','receive_time')}
    @property
    def signed_quantity(self): return -dec(self.quantity) if self.buyer_is_maker else dec(self.quantity)
    def validate(self):
        if type(self) is Trade and getattr(self,'_validated_frozen_scalars',False): return None
        try:
            if self.market not in ('BINANCE_SPOT','BINANCE_FUTURES') or self.symbol!='BTCUSDT' or self.stream!='AGG_TRADE': return 'SOURCE_DOMAIN'
            if type(self.native_id) is not int or self.native_id<0 or type(self.buyer_is_maker) is not bool: return 'SOURCE_ID_OR_AGGRESSION'
            if dec(self.price)<=0 or dec(self.quantity)<=0: return 'SOURCE_MEASUREMENT'
            if not utc(self.trade_time)<=utc(self.exchange_event_time): return 'RAW_CLOCK_ORDER'
            utc(self.receive_time)  # Local UTC is validated independently of exchange T/E.
            if self.payload_sha!=digest(self.core): return 'RAW_PARENT_HASH'
        except (TypeError,ValueError,AttributeError,InvalidOperation): return 'RAW_SCHEMA'
        if (type(self) is Trade and all(type(getattr(self,k)) is str for k in ('market','symbol','stream','trade_time','exchange_event_time','receive_time','price','quantity','payload_sha')) and type(self.native_id) is int and type(self.buyer_is_maker) is bool):
            object.__setattr__(self,'_validated_frozen_scalars',True)
        return None

def _ordered_raw_uncached(trades):
    if len(trades)<2: return 'POSITIVE_SPAN_REQUIRED'
    for t in trades:
        if (err:=t.validate()): return err
    for a,b in zip(trades,trades[1:]):
        if (a.market,a.symbol,a.stream)!=(b.market,b.symbol,b.stream): return 'FLOW_PRICE_MARKET_MISMATCH'
        if b.native_id != a.native_id+1: return 'RAW_SEQUENCE_GAP_OR_REORDER'
        if utc(b.trade_time)<utc(a.trade_time) or utc(b.exchange_event_time)<utc(a.exchange_event_time): return 'RAW_CLOCK_REORDER'
    if utc(trades[-1].trade_time)<=utc(trades[0].trade_time): return 'POSITIVE_SPAN_REQUIRED'
    return None

# Only successfully validated tuples of frozen Trade scalars are memoized.
# Lists and invalid inputs retain the original validation path. Bounded caches
# hold input objects themselves, so identity cannot be reused after collection.
_ORDERED=OrderedDict()
_RATES=OrderedDict()
def _known_tuple(trades):
    saved=_ORDERED.get(id(trades))
    if saved is not None and saved['trades'] is trades:
        _ORDERED.move_to_end(id(trades));return saved
    return None

def _remember_ordered(trades,previous=None):
    saved={'trades':trades,'frozen_scalars':all(getattr(t,'_validated_frozen_scalars',False) for t in trades)}
    if previous is not None:
        new=trades[-1]
        if 'receive_max' in previous:saved['receive_max']=max(previous['receive_max'],utc(new.receive_time))
        if 'source_keys' in previous:saved['source_keys']=previous['source_keys']+(new.source_key,)
        if 'payload_hashes' in previous:saved['payload_hashes']=previous['payload_hashes']|{new.payload_sha}
    _ORDERED[id(trades)]=saved
    while len(_ORDERED)>4:_ORDERED.popitem(last=False)

def ordered_raw(trades):
    if type(trades) is tuple and _known_tuple(trades) is not None:return None
    if type(trades) is tuple and len(trades)>=3 and all(type(t) is Trade for t in trades):
        for previous in reversed(tuple(_ORDERED.values())):
            old=previous['trades']
            if (previous.get('frozen_scalars') and len(old)+1==len(trades)
                    and all(a is b for a,b in zip(old,trades))):
                new=trades[-1];last=old[-1]
                if err:=new.validate():return err
                if (last.market,last.symbol,last.stream)!=(new.market,new.symbol,new.stream):return 'FLOW_PRICE_MARKET_MISMATCH'
                if new.native_id!=last.native_id+1:return 'RAW_SEQUENCE_GAP_OR_REORDER'
                if utc(new.trade_time)<utc(last.trade_time) or utc(new.exchange_event_time)<utc(last.exchange_event_time):return 'RAW_CLOCK_REORDER'
                if utc(new.trade_time)<=utc(trades[0].trade_time):return 'POSITIVE_SPAN_REQUIRED'
                _remember_ordered(trades,previous);return None
    error=_ordered_raw_uncached(trades)
    if error is None and type(trades) is tuple and all(type(t) is Trade for t in trades):_remember_ordered(trades)
    return error

def _tuple_value(trades,name,build):
    saved=_known_tuple(trades) if type(trades) is tuple else None
    if saved is None:return build()
    if name not in saved:saved[name]=build()
    return saved[name]

def _receive_max(trades):return _tuple_value(trades,'receive_max',lambda:max(utc(t.receive_time) for t in trades))
def _source_keys(trades):return _tuple_value(trades,'source_keys',lambda:tuple(t.source_key for t in trades))
def _payload_hashes(trades):return _tuple_value(trades,'payload_hashes',lambda:frozenset(t.payload_sha for t in trades))

def _baseline_rate(trades):
    c=getcontext();context=(c.prec,c.rounding,c.Emin,c.Emax,c.clamp,tuple(sorted((k.__name__,v) for k,v in c.traps.items())))
    key=id(trades);saved=_RATES.get(key)
    if saved is not None and saved[0] is trades and saved[1]==context:
        _RATES.move_to_end(key)
        for flag in saved[3]:c.flags[flag]=True
        return saved[2]
    seconds=Decimal(str((utc(trades[-1].trade_time)-utc(trades[0].trade_time)).total_seconds()))
    with localcontext(c) as calculation:
        calculation.clear_flags()
        try:rate=sum(dec(t.quantity) for t in trades)/seconds
        finally:
            raised=tuple(flag for flag,value in calculation.flags.items() if value)
            for flag in raised:c.flags[flag]=True
    if _known_tuple(trades) is not None:
        _RATES[key]=(trades,context,rate,raised)
        while len(_RATES)>4:_RATES.popitem(last=False)
    return rate

@lru_cache(maxsize=8192)
def _hex_hash(text):return len(text)==64 and all(c in '0123456789abcdef' for c in text)
def _parent_hash_valid(value):
    return _hex_hash(value) if type(value) is str else len(value)==64 and all(c in '0123456789abcdef' for c in value)

_PARENTS=OrderedDict()
def _parent_evidence_error(trades,baseline,parents):
 key=(id(trades),id(baseline),id(parents));saved=_PARENTS.get(key)
 if saved is not None and saved[0] is trades and saved[1] is baseline and saved[2] is parents:
  _PARENTS.move_to_end(key);return None
 expected=_payload_hashes(trades)|_payload_hashes(baseline)
 if not parents or expected!=set(parents) or len(parents)!=len(expected) or any(not _parent_hash_valid(h) for h in parents):return 'MISSING_PARENT_EVIDENCE'
 if set(_source_keys(trades))&set(_source_keys(baseline)):return 'BASELINE_CONSTITUENT_REUSE'
 if (type(trades) is tuple and type(baseline) is tuple and type(parents) is tuple
     and _known_tuple(trades) is not None and _known_tuple(baseline) is not None
     and all(type(h) is str for h in parents)):
  _PARENTS[key]=(trades,baseline,parents)
  while len(_PARENTS)>4:_PARENTS.popitem(last=False)
 return None

@dataclass(frozen=True)
class Observation:
    tf: str
    context_id: str
    context_direction: str
    origin: str
    bar_open: str
    bar_close: str
    available_at: str
    trades: tuple[Trade,...]
    baseline_trades: tuple[Trade,...]
    baseline_available_at: str
    context_available_at: str
    parent_hashes: tuple[str,...]
    partition_policy_id: str
    partition_declared_at: str
    # These annotations NEVER enter primary memory, identity or measurement.
    ft4_available_at: str | None = None
    ft4_label: str | None = None
    synthetic_context_proof: dict | None = None
    @property
    def source_ids(self): return _source_keys(self.trades)
    @property
    def key(self): return digest([VERSION,self.tf,self.source_ids])
    @property
    def fingerprint(self):
        d=asdict(self)
        for k in ('ft4_available_at','ft4_label'): d.pop(k)
        if d.get('synthetic_context_proof') is None: d.pop('synthetic_context_proof',None)
        for t in d['trades']+d['baseline_trades']: t.pop('receive_time')
        return digest(d)
    @property
    def measurements(self):
        p=[dec(t.price) for t in self.trades];q=sum(dec(t.quantity) for t in self.trades)
        secs=Decimal(str((utc(self.trades[-1].trade_time)-utc(self.trades[0].trade_time)).total_seconds()))
        rate=_baseline_rate(self.baseline_trades)
        return dict(open=p[0],high=max(p),low=min(p),close=p[-1],volume=q,
                    delta=sum(t.signed_quantity for t in self.trades),participation=q/(rate*secs),
                    duration=secs,baseline_rate=rate)
    def validate(self,cutoff):
        try:
            if self.tf not in DUR or self.context_direction not in ('LONG','SHORT') or not self.context_id: return 'OWN_TF_CONTEXT_REQUIRED'
            if self.origin not in ('FIXTURE_ONLY','REAL_CANDIDATE','PAPER_OBSERVED'): return 'ORIGIN_REQUIRED'
            if self.synthetic_context_proof is not None and self.origin!='FIXTURE_ONLY': return 'SYNTHETIC_PROOF_ON_REAL_FORBIDDEN'
            for raw in (self.trades,self.baseline_trades):
                if (err:=ordered_raw(raw)): return err
            first,last=self.trades[0],self.trades[-1]
            if (first.market,first.symbol,first.stream)!=(self.baseline_trades[0].market,self.baseline_trades[0].symbol,self.baseline_trades[0].stream): return 'FLOW_PRICE_MARKET_MISMATCH'
            opened,closed,available,at=map(utc,(self.bar_open,self.bar_close,self.available_at,cutoff))
            if (closed-opened).total_seconds()!=DUR[self.tf] or int(opened.timestamp())%DUR[self.tf]: return 'OWN_TF_BAR_ALIGNMENT'
            if not opened<=utc(first.trade_time)<=utc(last.trade_time)<closed: return 'OWN_BAR_CONSTITUENTS'
            if not _receive_max(self.trades)<=available<=at: return 'FUTURE_OR_UNAVAILABLE_SOURCE'
            # Availability/fixation and callback receive times share the local
            # clock domain. Exchange T/E only establish exchange-side order.
            first_received=utc(first.receive_time)
            if not _receive_max(self.baseline_trades)<=utc(self.baseline_available_at)<=first_received: return 'FUTURE_BASELINE'
            if utc(self.baseline_trades[-1].exchange_event_time)>=utc(first.trade_time): return 'BASELINE_NOT_PREEXISTING'
            if utc(self.context_available_at)>first_received: return 'FUTURE_CONTEXT'
            if not self.partition_policy_id or utc(self.partition_declared_at)>first_received: return 'HINDSIGHT_WINDOW_POLICY'
            if (err:=_parent_evidence_error(self.trades,self.baseline_trades,self.parent_hashes)):return err
            if self.synthetic_context_proof is not None:
                from .trend_fixture_context_authority import verify_observation
                if (err:=verify_observation(self,self.synthetic_context_proof)): return err
            elif self.origin=='FIXTURE_ONLY' and (not self.context_id.startswith('fixture:') or not self.partition_policy_id.startswith('fixture:')): return 'FIXTURE_NAMESPACE_REQUIRED'
        except (ValueError,TypeError,AttributeError,InvalidOperation,OverflowError): return 'OBSERVATION_SCHEMA'
        return None

@dataclass(frozen=True)
class Bootstrap:
    tf: str
    proof_ref: str
    available_at: str
    origin: str = 'FIXTURE_ONLY'
    scope: str = 'PROVEN_NO_PREEXISTING_INITIATIVE'

@dataclass(frozen=True)
class Candidate:
    anchor: Observation
    breakout: Observation | None = None
    retest: Observation | None = None

@dataclass(frozen=True)
class Segment:
    initiative_id: str
    anchor: Observation
    breakout: Observation
    retest: Observation
    acceptance: Observation
    parent_initiative_id: str | None
    source_ids: tuple[str,...]
    boundary_source_id: str

@dataclass(frozen=True)
class JournalRecord:
    observation_key: str
    input_fingerprint: str
    cutoff: str
    available_at: str
    outcome: str
    reason: str
    initiative_id: str | None
    event: str | None
    previous_record_sha: str | None
    sha256: str
    def validate(self,previous):
        data=asdict(self);expected=data.pop('sha256')
        if expected!=digest(data) or self.previous_record_sha!=previous:raise ValueError('JOURNAL_HASH_CHAIN')

@dataclass(frozen=True)
class Memory:
    tf: str
    current: Segment | None = None
    candidate: Candidate | None = None
    last: Observation | None = None
    seen: tuple[tuple[str,str],...] = ()
    journal: tuple[JournalRecord,...] = ()
    bootstrap_consumed: bool = False
    def to_json(self):
        data=asdict(self)
        return canonical({'version':VERSION,'data':data,'sha256':digest(data)})
    @classmethod
    def from_json(cls,s):
        d=json.loads(s)
        if d['version']!=VERSION or d['sha256']!=digest(d['data']): raise ValueError('STATE_VERSION_OR_CHECKSUM')
        d=d['data']
        def obs(v):
            if v is None:return None
            v=dict(v)
            for k in ('trades','baseline_trades'): v[k]=tuple(Trade(**t) for t in v[k])
            v['parent_hashes']=tuple(v['parent_hashes']);return Observation(**v)
        if d['current']:
            s=dict(d['current'])
            for k in ('anchor','breakout','retest','acceptance'):s[k]=obs(s[k])
            s['source_ids']=tuple(s['source_ids']);d['current']=Segment(**s)
        if d['candidate']:
            c=d['candidate'];d['candidate']=Candidate(obs(c['anchor']),obs(c['breakout']),obs(c['retest']))
        d['last']=obs(d['last']);d['seen']=tuple(tuple(v) for v in d['seen']);d['journal']=tuple(JournalRecord(**v) for v in d['journal'])
        previous=None
        for record in d['journal']:
            record.validate(previous);previous=record.sha256
        return cls(**d)

@dataclass(frozen=True)
class Result:
    memory: Memory
    observation: Observation
    cutoff: str
    outcome: str
    reason: str
    event: str | None = None
    economic_match: bool = False
    boundary_source_id: str | None = None
    parent_segment: Segment | None = None
    real_evidence_status: str = 'NOT_QUALIFIED'
    real_eligibility: str = 'NO_ENTRY'
    FT4_used: bool = False


def assess(memory,o,cutoff,bootstrap=None):
    """One frozen trade-window update. Economic labels do not authorise trades."""
    def result(m,outcome,reason,event=None,match=False,boundary=None,commit=False):
        if commit:
            rec={'observation_key':o.key,'input_fingerprint':o.fingerprint,'cutoff':cutoff,
                 'available_at':o.available_at,'outcome':outcome,'reason':reason,
                 'initiative_id':m.current.initiative_id if m.current else None,'event':event,
                 'previous_record_sha':memory.journal[-1].sha256 if memory.journal else None}
            rec['sha256']=digest(rec)
            m=replace(m,journal=memory.journal+(JournalRecord(**rec),))
        return Result(m,o,cutoff,outcome,reason,event,match,boundary,memory.current)
    err=o.validate(cutoff)
    if err:return result(memory,'INSUFFICIENT_EVIDENCE',err)
    o=replace(o,ft4_available_at=None,ft4_label=None)
    if memory.tf!=o.tf:return result(memory,'INSUFFICIENT_EVIDENCE','OWN_TF_MISMATCH')
    seen=dict(memory.seen)
    if o.key in seen:
        if seen[o.key]!=o.fingerprint:return result(memory,'INSUFFICIENT_EVIDENCE','CONFLICTING_SAME_SOURCE')
        return result(memory,'INSUFFICIENT_EVIDENCE','DUPLICATE_NO_EFFECT')
    if memory.last:
        prev=memory.last
        if (prev.trades[0].market,prev.context_id,prev.context_direction,prev.origin,prev.partition_policy_id)!=(o.trades[0].market,o.context_id,o.context_direction,o.origin,o.partition_policy_id):return result(memory,'INSUFFICIENT_EVIDENCE','DOMAIN_CONTEXT_OR_POLICY_MISMATCH')
        if set(prev.source_ids)&set(o.source_ids):return result(memory,'INSUFFICIENT_EVIDENCE','CONSTITUENT_REUSE')
        if o.trades[0].native_id!=prev.trades[-1].native_id+1:return result(memory,'INSUFFICIENT_EVIDENCE','SOURCE_GAP_REORDER_OR_REUSE')
        if utc(o.trades[0].trade_time)<utc(prev.trades[-1].trade_time) or utc(o.available_at)<utc(prev.available_at):return result(memory,'INSUFFICIENT_EVIDENCE','LATE_SOURCE_NO_RECODING')
    m=replace(memory,seen=memory.seen+((o.key,o.fingerprint),),last=o)
    def out(outcome,reason,event=None,match=False,**changes):
        return result(replace(m,**changes),outcome,reason,event,match,o.source_ids[0] if match else None,True)
    x=o.measurements;d=1 if o.context_direction=='LONG' else -1
    participating=x['participation']>Decimal('1'); aligned=d*x['delta']>0;counter=d*x['delta']<0
    body=d*(x['close']-x['open'])
    s,c=memory.current,memory.candidate
    def edge(a):return a.measurements['high'] if d==1 else a.measurements['low']
    def outside(a):return d*(x['close']-edge(a))>0
    def loss(a):return d*(x['close']-(a.measurements['low'] if d==1 else a.measurements['high']))<0
    if s and loss(s.anchor) and participating and counter:
        return out('FAILED_CANDIDATE','PREVIOUS_ORIGIN_BROKEN','BREAK',True,current=None,candidate=None)
    if c and participating and counter and (loss(c.anchor) or (c.breakout and d*(x['close']-edge(c.anchor))<0 and body<0)):
        return out('FAILED_CANDIDATE','BREAKOUT_REJECTED_OR_ORIGIN_LOST','BREAK' if s is None else None,True,candidate=None)
    if c and c.breakout and c.retest:
        if participating and aligned and body>0 and outside(c.anchor):
            ids=tuple(t for a in (c.anchor,c.breakout,c.retest,o) for t in a.source_ids)
            iid=digest([VERSION,o.tf,o.trades[0].market,o.context_direction,c.anchor.key,c.breakout.key,c.retest.key,o.key,s.initiative_id if s else None])
            seg=Segment(iid,c.anchor,c.breakout,c.retest,o,s.initiative_id if s else None,ids,o.source_ids[0])
            return out('NEW_INDEPENDENT_INITIATIVE' if s else 'CONFIRMED_ACCEPTANCE','DISTINCT_TOUCH_THEN_PARTICIPATING_OUTWARD_RESPONSE','NEW_INITIATIVE' if s else 'CONFIRM',True,current=seg,candidate=None)
        return out('PROVISIONAL_RETEST','TOUCH_WITHOUT_POSITIVE_ACCEPTANCE')
    if c and c.breakout:
        touched=any(d*(dec(t.price)-edge(c.anchor))<=0 for t in o.trades)
        if touched and participating:
            return out('PROVISIONAL_RETEST','OBSERVED_RETURN_TO_OR_INSIDE_EDGE_NOT_ACCEPTANCE',candidate=Candidate(c.anchor,c.breakout,o))
        return out('PROVISIONAL_BREAKOUT','INDEPENDENT_RETEST_UNPROVEN')
    if c:
        eff=body/(x['high']-x['low']+EPS)
        if participating and aligned and outside(c.anchor) and eff>Decimal('0.6'):
            return out('PROVISIONAL_BREAKOUT','DISTINCT_PARTICIPATING_BREAKOUT','FORMING' if s is None else None,True,candidate=Candidate(c.anchor,o))
        return out('PROVISIONAL_DEFENDED_ORIGIN','BREAKOUT_UNPROVEN')
    wick=min(x['open'],x['close'])-x['low'] if d==1 else x['high']-max(x['open'],x['close'])
    defended=participating and counter and body>=0 and wick>0
    if defended:
        if s:
            old=s.anchor.measurements
            independent=x['low']>old['high'] if d==1 else x['high']<old['low']
            if not independent:return out('SAME_INITIATIVE_CONTINUATION','OVERLAPPING_ORIGIN_NOT_INDEPENDENT')
        else:
            valid=isinstance(bootstrap,Bootstrap) and bootstrap.tf==o.tf and bootstrap.origin==o.origin=='FIXTURE_ONLY' and bootstrap.scope=='PROVEN_NO_PREEXISTING_INITIATIVE' and bootstrap.proof_ref.startswith('fixture:') and not memory.bootstrap_consumed
            try:valid=valid and utc(bootstrap.available_at)<=utc(o.trades[0].trade_time)
            except (ValueError,AttributeError,TypeError):valid=False
            if not valid:return out('INSUFFICIENT_EVIDENCE','UNKNOWN_PREVIOUS_INITIATIVE_BOUNDARY')
        return out('PROVISIONAL_DEFENDED_ORIGIN','OBSERVED_COUNTERFLOW_REJECTION_FROZEN_PREFIX_ZONE',candidate=Candidate(o),bootstrap_consumed=True)
    if s:
        return out('SAME_INITIATIVE_CONTINUATION','NO_NEW_DEFENDED_ACCEPTANCE_CHAIN','CONTINUE' if participating and aligned and body>0 and outside(s.anchor) else None,participating and aligned and body>0 and outside(s.anchor))
    return out('INSUFFICIENT_EVIDENCE','NO_QUALIFIED_PRIOR_OR_ORIGIN')


def fixture_r2_projection(result,r2_state):
    """Intrabar source_close is None: forming own bar is not a closed OHLC."""
    if result.observation.origin!='FIXTURE_ONLY' or not result.economic_match or not result.event:return None
    from .trend_r2_contract import QualifiedMarketEvidence, VERSION as R2
    o=result.observation;typ=result.event;prior=r2_state.timeframes[o.tf]
    if typ=='NEW_INITIATIVE' and prior.trend_phase in ('WEAKENING','REACTIVATING'):typ='CONFIRM_REACTIVATION'
    if typ=='NEW_INITIATIVE' and prior.trend_phase=='EXHAUSTED':return None
    independent=typ in ('CONFIRM','NEW_INITIATIVE','CONFIRM_REACTIVATION')
    s=result.memory.current
    ids=s.source_ids if independent and s else o.source_ids
    boundary=s.boundary_source_id if independent and s else result.boundary_source_id or ids[0]
    immutable_parents=tuple(sorted({h for w in (s.anchor,s.breakout,s.retest,s.acceptance) for h in w.parent_hashes})) if independent and s else o.parent_hashes
    parent=None
    if typ in ('NEW_INITIATIVE','CONFIRM_REACTIVATION') and result.parent_segment:
        prev=result.parent_segment
        parent_roots=sorted({h for w in (prev.anchor,prev.breakout,prev.retest,prev.acceptance) for h in w.parent_hashes})
        parent=digest([R2,o.tf,parent_roots,sorted(prev.source_ids),prev.boundary_source_id])
    return QualifiedMarketEvidence(timeframe=o.tf,context_episode_id=o.context_id,direction=o.context_direction,
        event_type=typ,semantic_classification=result.outcome,source_event_ids=ids,
        source_bar_id='fixture:own:'+o.tf+':'+o.bar_open,source_bar_open=o.bar_open,
        exchange_event_time=o.trades[-1].exchange_event_time,
        receive_time=max(t.receive_time for t in o.trades),evaluation_cutoff=result.cutoff,
        qualification_time=o.available_at,publication_time=o.available_at,
        immutable_source_ids=immutable_parents,event_lineage='fixture:DRA_EVENT:'+o.key,
        independent_boundary_id=boundary,evidence_status='QUALIFIED',eligibility_status='ELIGIBLE_FIXTURE_ONLY',
        origin='FIXTURE_ONLY',independent_verified=independent,parent_evidence_key=parent,
        source_close=None,source_available_at=o.available_at)
