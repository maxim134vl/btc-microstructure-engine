"""Versioned causal evidence envelope, not a market classifier."""
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Protocol

VERSION = 'TREND_OPPORTUNITY_ISOLATED_V1_R2'
SCHEMA = 1
TFS = ('M15', 'M30', 'H1', 'H4')

class Direction(str, Enum):
    LONG='LONG'; SHORT='SHORT'; NONE='NONE'
class Phase(str, Enum):
    FORMING='FORMING'; CONFIRMED='CONFIRMED'; ACTIVE='ACTIVE'; WEAKENING='WEAKENING'
    EXHAUSTED='EXHAUSTED'; REACTIVATING='REACTIVATING'; BROKEN='BROKEN'
class OpportunityState(str, Enum):
    NONE='NONE'; ARMED='ARMED'; PENDING='PENDING'; CONSUMED='CONSUMED'
    EXPIRED='EXPIRED'; INVALIDATED='INVALIDATED'

EVENTS = ('FORMING','CONFIRM','CONTINUE','WEAKEN','EXHAUST','REACTIVATE',
          'CONFIRM_REACTIVATION','NEW_INITIATIVE','BREAK','OBSERVE','CONTEXT_RECOVERY')

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
def digest(value):
    return sha256(canonical(value).encode()).hexdigest()
def utc(value):
    if not isinstance(value, str): raise ValueError('MISSING_TIME')
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None or t.utcoffset().total_seconds()!=0: raise ValueError('TIME_NOT_UTC')
    return t.astimezone(timezone.utc)

@dataclass(frozen=True)
class QualifiedMarketEvidence:
    timeframe: str
    context_episode_id: str
    direction: str
    event_type: str
    semantic_classification: str
    source_event_ids: tuple[str, ...]
    source_bar_id: str
    source_bar_open: str
    exchange_event_time: str
    receive_time: str
    evaluation_cutoff: str
    qualification_time: str
    publication_time: str
    immutable_source_ids: tuple[str, ...]
    event_lineage: str
    independent_boundary_id: str
    evidence_status: str = 'NOT_QUALIFIED'
    eligibility_status: str = 'NO_ENTRY'
    origin: str = 'REAL_CANDIDATE'
    independent_verified: bool = False
    parent_evidence_key: str | None = None
    source_close: str | None = None
    source_available_at: str | None = None
    # Optional atoms carry no implicit eligibility or numeric interpretation.
    atoms: tuple[tuple[str, str], ...] = ()
    schema_version: int = SCHEMA
    algorithm_version: str = VERSION

    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        for k in ('source_event_ids','immutable_source_ids','atoms'):
            if k in d and not isinstance(d[k],(tuple,list)): raise ValueError('INVALID_SOURCE_COLLECTION')
        for k in ('source_event_ids','immutable_source_ids'): d[k]=tuple(d[k])
        d['atoms']=tuple(tuple(x) for x in d.get('atoms', ()))
        return cls(**d)
    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA or self.algorithm_version != VERSION: return 'UNKNOWN_VERSION'
        if self.timeframe not in TFS or self.direction not in tuple(x.value for x in Direction): return 'UNKNOWN_OWNERSHIP'
        if self.event_type not in EVENTS: return 'UNKNOWN_EVENT_TYPE'
        for name in ('context_episode_id','semantic_classification','source_bar_id','event_lineage','independent_boundary_id'):
            v=getattr(self,name)
            if not isinstance(v,str) or not v.strip() or v.upper()=='UNKNOWN': return 'MISSING_SOURCE_IDENTITY'
        for seq in (self.source_event_ids,self.immutable_source_ids):
            if not isinstance(seq,tuple) or not seq or any(not isinstance(x,str) or not x.strip() or x.upper()=='UNKNOWN' for x in seq) or len(set(seq))!=len(seq): return 'MISSING_SOURCE_IDENTITY'
        if self.independent_boundary_id not in self.source_event_ids: return 'UNBOUND_EVIDENCE_BOUNDARY'
        if not isinstance(self.atoms,tuple) or any(not isinstance(x,tuple) or len(x)!=2 or any(not isinstance(v,str) for v in x) for x in self.atoms): return 'INVALID_ATOMS'
        if not isinstance(self.independent_verified,bool): return 'INVALID_INDEPENDENCE'
        if self.parent_evidence_key is not None and (not isinstance(self.parent_evidence_key,str) or not self.parent_evidence_key): return 'INVALID_PARENT_IDENTITY'
        if self.origin not in ('FIXTURE_ONLY','REAL_CANDIDATE','PAPER_OBSERVED'): return 'UNKNOWN_ORIGIN'
        if self.evidence_status not in ('QUALIFIED','NOT_QUALIFIED') or self.eligibility_status not in ('ELIGIBLE_FIXTURE_ONLY','ELIGIBLE_PAPER_OBSERVED','NO_ENTRY'): return 'UNKNOWN_EVIDENCE_STATUS'
        try:
            opened,event,received,qualified,published,cutoff=map(utc,(self.source_bar_open,self.exchange_event_time,self.receive_time,self.qualification_time,self.publication_time,self.evaluation_cutoff))
            if not opened<=event<=received<=qualified<=published<=cutoff: return 'NONCAUSAL_AVAILABILITY'
            if self.source_close is not None and (utc(self.source_close)<opened or utc(self.source_close)>cutoff): return 'NONCAUSAL_AVAILABILITY'
            if self.source_available_at is not None and not opened<=utc(self.source_available_at)<=qualified: return 'NONCAUSAL_AVAILABILITY'
        except (TypeError, ValueError, OverflowError): return 'INVALID_TIME'
        return None
    @property
    def dedup_key(self):
        # Episode and evaluation cycles cannot make the same source boundary new.
        return digest([VERSION,self.timeframe,sorted(self.immutable_source_ids),sorted(self.source_event_ids),self.independent_boundary_id])
    @property
    def fingerprint(self):
        d=self.to_dict()
        for k in ('receive_time','evaluation_cutoff'): d.pop(k)
        for k in ('source_bar_open','exchange_event_time','qualification_time','publication_time','source_close','source_available_at'):
            if d[k] is not None: d[k]=utc(d[k]).isoformat()
        for k in ('source_event_ids','immutable_source_ids'): d[k]=sorted(d[k])
        return digest(d)
    @property
    def ordering_key(self):
        return (utc(self.exchange_event_time).isoformat(),utc(self.publication_time).isoformat(),self.dedup_key)

class EvidenceQualifier(Protocol):
    def qualify(self, evidence: QualifiedMarketEvidence) -> QualifiedMarketEvidence: ...

class FailClosedQualifier:
    """Real evidence is never upgraded by this prototype, including May labels."""
    def qualify(self,evidence):
        return replace(evidence,evidence_status='NOT_QUALIFIED',eligibility_status='NO_ENTRY',independent_verified=False)
