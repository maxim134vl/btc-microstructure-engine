"""Typed raw/window evidence; original EVENT remains imported read-only."""
import sys,json,importlib.util
from dataclasses import dataclass,asdict
from decimal import Decimal
from pathlib import Path
from .trend_journal import digest,Blocked,canonical
from . import trend_event as E
from .trend_r2_contract import QualifiedMarketEvidence,VERSION as R2_VERSION
from .trend_r2_machine import State,TFState,evaluate
DUR=E.DUR
@dataclass(frozen=True)
class RawOccurrence:
 trade: E.Trade
 original_payload: str
 capture_origin: str
 capture_family: str
 coverage_ref: str
 predecessor: int | None  # Unknown before the first retained REAL observation.
 available_at: str
 def packet(self):return {'trade':asdict(self.trade),'original_payload':self.original_payload,'capture_origin':self.capture_origin,'capture_family':self.capture_family,'coverage_ref':self.coverage_ref,'predecessor':self.predecessor,'available_at':self.available_at}
 @classmethod
 def from_dict(cls,p):return cls(E.Trade(**p['trade']),**{k:v for k,v in p.items() if k!='trade'})
 def validate(self,cutoff):
  if (err:=self.trade.validate()):raise Blocked(err)
  if self.capture_origin not in ('FIXTURE_ONLY','REAL_CANDIDATE'):raise Blocked('CAPTURE_ORIGIN')
  if json.loads(self.original_payload)!=self.trade.core:raise Blocked('ORIGINAL_PAYLOAD_MISMATCH')
  if not E.utc(self.trade.receive_time)<=E.utc(self.available_at)<=E.utc(cutoff):raise Blocked('RAW_AVAILABILITY')
  if not self.capture_family or not self.coverage_ref:raise Blocked('RAW_PARENT_REQUIRED')
@dataclass(frozen=True)
class FixtureAuthority:
 declaration_sha:str
 declaration:dict
 @classmethod
 def read(cls,path,expected_sha):
  d=json.loads(Path(path).read_text())
  if digest(d)!=expected_sha or d.get('type')!='AUTHOR_DECLARED_SYNTHETIC_FIXTURE' or not d.get('capture_family','').startswith('fixture:'):raise Blocked('FIXTURE_AUTHORITY_DECLARATION')
  return cls(expected_sha,d)
 def permits(self,config,raw):
  d=self.declaration
  if digest(d)!=self.declaration_sha:raise Blocked('FIXTURE_AUTHORITY_MUTATED')
  return (config['mode']=='FIXTURE_ONLY' and raw.capture_origin=='FIXTURE_ONLY' and raw.capture_family==d['capture_family']==config['capture_family'] and raw.trade.payload_sha in d['allowed_payload_hashes'] and raw.coverage_ref==d['coverage_ref'] and config['authority_sha']==self.declaration_sha)
@dataclass(frozen=True)
class ObservedSeed:
 seed_id:str;scope:dict;generation:int;origin_geometry:dict;windows:tuple;source_interval:tuple;cutoff:str;baseline_ref:str;authority_class:str='OBSERVED_SEED';prior_market_owner:str='UNKNOWN';first_market_initiative:str='NOT_ASSERTED';trading_projection:str='NOT_REQUESTED';entry:str='NO_ENTRY'
@dataclass(frozen=True)
class BridgeRequestV1:
 economic_segment_id:str
 economic_parent_id:str|None
 economic_parent_confirmation_ref:str|None
 opportunity_parent_id:str|None
 opportunity_parent_evidence_key:str|None
 opportunity_anchor_segment_id:str|None
 economic_path_ref:tuple
 skipped_projection_receipts:tuple
 source_evidence_ref:str
 expected_r2_state_hash:str
 bridge_attempt_id:str
 event_type:str
 timeframe:str
 r2_payload:str
 def __post_init__(self):
  object.__setattr__(self,'economic_path_ref',tuple(self.economic_path_ref));object.__setattr__(self,'skipped_projection_receipts',tuple(self.skipped_projection_receipts))
  if isinstance(self.r2_payload,dict):object.__setattr__(self,'r2_payload',canonical(self.r2_payload))
 def to_dict(self):
  d=asdict(self);d['r2_payload']=json.loads(self.r2_payload);return json.loads(json.dumps(d))
def obs_dict(o):
 d=asdict(o)
 if d.get('synthetic_context_proof') is None:d.pop('synthetic_context_proof',None)
 return d
def obs_restore(v):
 v=dict(v)
 for k in ('trades','baseline_trades'):v[k]=tuple(E.Trade(**t) for t in v[k])
 v['parent_hashes']=tuple(v['parent_hashes']);return E.Observation(**v)
def r2_restore(d):
 s=State();s.algorithm_version=d['algorithm_version'];s.opportunities=d['opportunities'];s.seen_events=d['seen_events'];s.used_boundaries=d['used_boundaries'];s.receipts=d['receipts']
 for tf,v in d['timeframes'].items():
  v=dict(v)
  if v['last_market_order'] is not None:v['last_market_order']=tuple(v['last_market_order'])
  s.timeframes[tf]=TFState(**v)
 return s
def json_state(s):return json.loads(json.dumps(s.to_dict()))
