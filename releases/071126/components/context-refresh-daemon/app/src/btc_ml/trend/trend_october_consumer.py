"""Post-completion isolated reader. Does not publish, classify, or dispatch commands.

The trusted input is an immutable frozen bundle, not a boolean `completed` claim.
A snapshot fingerprint is NOT an original canonical commit receipt. REAL records
with absent original receipts remain unqualified, without fixture relabelling.
"""
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone, timedelta
from copy import deepcopy
from io import BytesIO
import hashlib,json
import pandas as pd

VERSION='OCTOBER_CONTEXT_DEPENDENT_DIAGNOSTIC_V1'
DUR={'M15':900,'M30':1800,'H1':3600,'H4':14400}
SHARED='data/cognition/market_context_lifecycle_memory.parquet'
def sha(b): return hashlib.sha256(b).hexdigest()
def digest(x): return sha(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def utc(x):
 t=datetime.fromisoformat(str(x).replace('Z','+00:00'))
 if t.tzinfo is None: raise BindingError('NAIVE_CLOCK')
 return t.astimezone(timezone.utc)
def scalar(x):
 if x is None or pd.isna(x): return None
 if isinstance(x,pd.Timestamp):return x.isoformat()
 if hasattr(x,'item'):x=x.item()
 if isinstance(x,float) and pd.isna(x):return None
 return x
class BindingError(ValueError): pass
@dataclass(frozen=True)
class BoundContext:
 timeframe:str
 canonical_context_episode_id:str
 canonical_direction:str
 source_bar_open:str
 source_bar_close:str
 information_available_at:str
 actual_publication_at:object
 context_publication_ref:dict
 source_identity:dict
 lifecycle_row:dict
 final_row:dict
 authority:str
 generation_ref:dict

class CompletedContextReader:
 """Allowlisted archival or synthetic artifacts; never accepts a live path.

 The shared lifecycle atomic file is read first and verified again last. Exact
 own dependency rows must agree with its committed row. Dependencies ahead of
 lifecycle are not promoted. Missing completion proof is retained as unqualified.
 """
 def __init__(self,root,manifest,origin,episode_mapper):
  self.root=Path(root).resolve();self.manifest=deepcopy(manifest);self.origin=origin
  if origin not in ('ARCHIVED_CAPTURE','SYNTHETIC_FIXTURE'):raise BindingError('ORIGIN')
  ssd=Path('/Volumes/MaksTiger')
  if not self.root.is_relative_to(ssd) or ssd.stat().st_dev==Path('/').stat().st_dev:raise BindingError('EXTERNAL_SSD_REQUIRED')
  if origin=='SYNTHETIC_FIXTURE' and not self.root.is_relative_to(Path(__file__).resolve().parents[3]/'test_artifacts'):raise BindingError('FIXTURE_STORAGE_AUTHORITY_REQUIRED')
  self.episode_mapper=episode_mapper
 def _read(self,rel):
  p=(self.root/rel).resolve()
  if not p.is_relative_to(self.root) or rel not in self.manifest:raise BindingError('UNPINNED_OR_OUTSIDE_BUNDLE:'+rel)
  if not p.is_file():raise BindingError('SOURCE_UNAVAILABLE:'+rel)
  if p.stat().st_size>16*1024*1024:raise BindingError('BOUNDED_READ_CAP')
  b=p.read_bytes();wanted=self.manifest[rel];wanted=wanted['sha256'] if isinstance(wanted,dict) else wanted
  if sha(b)!=wanted:raise BindingError('SNAPSHOT_HASH_CONFLICT:'+rel)
  return b
 def _frame(self,rel):
  f=pd.read_parquet(BytesIO(self._read(rel)))
  if len(f)>100000:raise BindingError('BOUNDED_ROW_CAP')
  if 'timestamp' not in f:raise BindingError('SOURCE_ROW_ID_MISSING')
  f=f.copy();f['timestamp']=pd.to_datetime(f.timestamp,utc=True)
  return f
 def _row(self,f,tf,opened):
  if 'timeframe' not in f or f.timeframe.isna().any():raise BindingError('EXPLICIT_OWN_TIMEFRAME_REQUIRED')
  if f.duplicated(['timeframe','timestamp']).any():raise BindingError('DUPLICATE_SOURCE_ROW')
  r=f.loc[(f.timeframe==tf)&(f.timestamp==pd.Timestamp(opened))]
  if len(r)!=1:raise BindingError('EXACT_OWN_ROW_UNAVAILABLE')
  return {k:scalar(v) for k,v in r.iloc[0].to_dict().items()}
 def consume(self,tf,source_bar_open,cutoff,fixture_receipt=None):
  if tf not in DUR:raise BindingError('OWN_TIMEFRAME_REQUIRED')
  opened,end=utc(source_bar_open),utc(cutoff);close=opened+timedelta(seconds=DUR[tf])
  if opened.timestamp()%DUR[tf] or close>end:raise BindingError('FORMING_OR_FUTURE_BAR')
  original=self._read(SHARED);shared=self._row(self._frame(SHARED),tf,opened)
  suffix='' if tf=='M15' else 'timeframes/'+tf+'/'
  final_rel='data/cognition/'+suffix+'final_market_context_memory.parquet'
  life_rel=SHARED if tf=='M15' else 'data/cognition/'+suffix+'market_context_lifecycle_memory.parquet'
  own=self._row(self._frame(life_rel),tf,opened);final=self._row(self._frame(final_rel),tf,opened)
  if any(shared.get(k)!=v for k,v in own.items()) or set(shared)-set(own)-{'lifecycle_source'}:raise BindingError('LIFECYCLE_COMPLETION_CONFLICT')
  if not self._read(SHARED)==original:raise BindingError('PUBLICATION_CHANGED_DURING_READ')
  if str(own.get('context_episode_id','')).lower() in ('','none','nan'):raise BindingError('EPISODE_UNAVAILABLE')
  ep=self.episode_mapper(tf,own['context_episode_id'])
  if not ep or ':prov:' in ep.lower() or any('PROVISIONAL' in str(r.get('record_origin','')).upper() for r in [own,final]):raise BindingError('PROVISIONAL_NOT_AUTHORITATIVE')
  context=final.get('market_context')
  if context not in ('LONG_CONTEXT','SHORT_CONTEXT','OBSERVE'):raise BindingError('FINAL_DIRECTION_UNAVAILABLE')
  if own.get('raw_market_context')!=context:raise BindingError('FINAL_LIFECYCLE_ROW_CONFLICT')
  for k in ('living_process','process_strength'):
   if own.get(k)!=final.get(k):raise BindingError('FINAL_LIFECYCLE_VALUE_CONFLICT:'+k)
  annotations=[]
  for row in (own,final):
   for k in ('source_bar_open','source_bar_close'):
    if row.get(k) is not None and utc(row[k])!=(opened if k=='source_bar_open' else close):raise BindingError('OWN_BAR_METADATA_CONFLICT')
   if row.get('information_available_at') is not None:
    at=utc(row['information_available_at'])
    if not close<=at<=end:raise BindingError('FUTURE_INFORMATION')
    annotations.append(at)
  info=max(annotations or [close]).isoformat()
  pub={'original_first_publication':None,'authority':'UNQUALIFIED_ORIGINAL_PUBLICATION','observation_snapshot_sha':sha(original)}
  authority='ARCHIVED_CAPTURE_UNQUALIFIED';actual=None
  if fixture_receipt is not None:
   if self.origin!='SYNTHETIC_FIXTURE' or fixture_receipt.get('origin')!='FIXTURE_ONLY':raise BindingError('FIXTURE_AUTHORITY_ON_REAL_INPUT')
   required={'origin','timeframe','source_bar_open','source_bar_close','canonical_episode_id','available_at','publication_id','final_sha','lifecycle_sha'}
   if set(fixture_receipt)!=required:raise BindingError('EXACT_FIXTURE_RECEIPT_REQUIRED')
   if fixture_receipt['timeframe']!=tf or fixture_receipt['canonical_episode_id']!=ep or utc(fixture_receipt['source_bar_open'])!=opened or utc(fixture_receipt['source_bar_close'])!=close:raise BindingError('PUBLICATION_OWNERSHIP_CONFLICT')
   if fixture_receipt['final_sha']!=sha(self._read(final_rel)) or fixture_receipt['lifecycle_sha']!=sha(original):raise BindingError('PUBLICATION_HASH_CONFLICT')
   actual=fixture_receipt['available_at']
   if not utc(info)<=utc(actual)<=end:raise BindingError('FUTURE_PUBLICATION')
   pub={'original_first_publication':actual,'authority':'AUTHOR_DECLARED_SYNTHETIC_CLOCK','fixture_receipt':deepcopy(fixture_receipt),'observation_snapshot_sha':sha(original)}
   authority='FIXTURE_ONLY'
  elif 'data/live/primary_context_publication.json' in self.manifest:
   report=json.loads(self._read('data/live/primary_context_publication.json'))
   receipt=next((r for r in report.get('outputs',[]) if r.get('timeframe')==tf and r.get('source_bar_open') and utc(r['source_bar_open'])==opened),None)
   if receipt and receipt.get('published_at'):
    if utc(receipt['published_at'])>end:raise BindingError('FUTURE_COMPLETION_RECEIPT')
    pub['retained_completion_observation']=receipt
    pub['receipt_limit']='No original row hash/commit generation; NOT first-publication proof'
  gen={'kind':'FROZEN_SNAPSHOT_ASSOCIATION_NOT_ORIGINAL_COMMIT','shared_lifecycle_sha':sha(original),'own_lifecycle_sha':sha(self._read(life_rel)),'own_final_sha':sha(self._read(final_rel))}
  gen['snapshot_association_id']=digest(gen)
  source={'timeframe':tf,'source_bar_open':opened.isoformat(),'source_bar_close':close.isoformat(),'lifecycle_timestamp':own['timestamp'],'native_event_ids':None,'original_receive':None,'original_ingest':None,'original_queue':None,'coverage':'NOT_PROVEN'}
  return BoundContext(tf,ep,{'LONG_CONTEXT':'LONG','SHORT_CONTEXT':'SHORT','OBSERVE':'NONE'}[context],opened.isoformat(),close.isoformat(),info,actual,pub,source,deepcopy(own),deepcopy(final),authority,gen)

class ContextDependentConsumer:
 """No dispatcher, clocks, classifier, journal, or background process is added.

 H1 owns the only scope commit API. Synthetic proof conversion is explicit;
 authentic inputs cannot be promoted through that fixture-only API.
 """
 def bind_fixture_scope(self,system,bound,cutoff):
  if bound.authority!='FIXTURE_ONLY' or system.state['config']['mode']!='FIXTURE_ONLY':raise BindingError('REAL_H1_SCOPE_PROOF_UNQUALIFIED')
  from .trend_scope_sessions import bind,head
  proof={'origin':'FIXTURE_ONLY','timeframe':bound.timeframe,'canonical_episode_id':bound.canonical_context_episode_id,'own_context_id':bound.canonical_context_episode_id,'direction':bound.canonical_direction,'source_bar_open':bound.source_bar_open,'source_bar_close':bound.source_bar_close,'available_at':bound.actual_publication_at,'publication_id':bound.context_publication_ref['fixture_receipt']['publication_id'],'immutable_parent_sha':bound.generation_ref['shared_lifecycle_sha']}
  return bind(system,proof,head(system.state,bound.timeframe),cutoff)
 def project(self,bound,cutoff,system=None,evaluated_at=None):
  end=utc(cutoff);now=utc(evaluated_at) if evaluated_at else datetime.now(timezone.utc)
  if now<end:raise BindingError('RESULT_CLOCK_BEFORE_EVALUATION_CUTOFF')
  phase=owner=opportunity=admission=lineage=None;ce=cp=None;heads=None;versions={};details=[]
  if system is not None:
   from .trend_scope_sessions import view,head,root_id
   from .trend_journal import digest as jd
   s=system.state;tf=bound.timeframe
   if tf not in s['config']['timeframes']:raise BindingError('SYSTEM_OWN_TF_UNAVAILABLE')
   current=head(s,tf);session=s.get('scope_sessions',{}).get(current)
   context=s['config']['contexts'][tf] if session is None else {'id':session['proof']['canonical_episode_id'],'direction':session['proof']['direction'],'available_at':session['proof']['available_at']}
   if context['id']!=bound.canonical_context_episode_id or context['direction']!=bound.canonical_direction:raise BindingError('SYSTEM_CANONICAL_SCOPE_MISMATCH')
   if utc(context['available_at'])>end:raise BindingError('SYSTEM_SCOPE_FUTURE')
   if any(utc(r['available_at'])>end for r in s.get('raw',{}).values()):raise BindingError('JOURNAL_HEAD_AFTER_CUTOFF')
   if (bound.authority=='FIXTURE_ONLY')!=(s['config']['mode']=='FIXTURE_ONLY'):raise BindingError('SOURCE_AUTHORITY_CLASS_MISMATCH')
   # Refuse projection at an earlier cutoff than the committed observed history.
   for record in system.j.records:
    event=record.get('action',{})
    for key in ('cutoff','available_at'):
     if event.get(key) and utc(event[key])>end:raise BindingError('JOURNAL_HEAD_AFTER_CUTOFF')
   v=view(system,tf);phase=v['current_phase'];owner=v['current_owner'];rt=s['r2']['timeframes'][tf];lineage=rt['context_episode_id']
   opportunity=rt['active_opportunity_id']
   admission=v['scope_admission_refs'][-1] if v['scope_admission_refs'] else None
   ce=next((r['sha'] for r in reversed(system.j.records) if r['boundary']=='C_E'),None);cp=next((r['sha'] for r in reversed(system.j.records) if r['boundary']=='C_P'),None)
   heads={'C_E':ce,'C_P':cp,'sequence':len(system.j.records),'state_sha':jd(s),'scope_ref':current,'historical_r2_phase':rt['trend_phase'],'pending_ids':v['obligation_ledger_ref']['pending_ids']}
   versions={'implementation_sha':s['config']['implementation_sha'],'baseline_sha':jd(s['config']['baseline']),'config_sha':jd(s['config']),'policy_available_at':s['config']['policy_available_at']}
  if bound.authority!='FIXTURE_ONLY':details+=['ORIGINAL_PUBLICATION_UNQUALIFIED','NATIVE_SOURCE_RECEIPTS_MISSING','SOURCE_COVERAGE_NOT_PROVEN','REAL_ECONOMIC_GRANT_NOT_PROVEN','REAL_R2_ADMISSION_NOT_PROVEN']
  if system is None:details.append('H1_SCOPE_AND_COMMITTED_LINEAGE_UNAVAILABLE')
  now=utc(evaluated_at) if evaluated_at else datetime.now(timezone.utc)
  return {'timeframe':bound.timeframe,'canonical_context_episode_id':bound.canonical_context_episode_id,'canonical_direction':bound.canonical_direction,'context_publication_ref':deepcopy(bound.context_publication_ref),'context_available_at':bound.actual_publication_at,'context_information_available_at':bound.information_available_at,'r2_lineage_ref':lineage,'trend_phase':phase,'economic_segment_ref':owner,'opportunity_ref':opportunity,'scope_admission_ref':admission,'source_economic_authority':{'source':bound.authority,'economic':'REAL_NOT_PROVEN' if bound.authority!='FIXTURE_ONLY' else 'SYNTHETIC_MECHANICS_ONLY','r2':'NO_REAL_ADMISSION','entry':'NO_ENTRY','missing_evidence':details},'diagnostic_decision':'NOT_QUALIFIED','reason':'UNSPECIFIED_POLICY','evaluation_cutoff':end.isoformat(),'evaluated_at':now.isoformat(),'result_available_at':now.isoformat(),'version_lineage':{'module':VERSION,'module_sha':sha(Path(__file__).read_bytes()),'canonical_snapshot':deepcopy(bound.generation_ref),'original_source_identity':deepcopy(bound.source_identity),'committed_heads':heads,**versions},'canonical_lifecycle_status':bound.lifecycle_row.get('lifecycle_state'),'trading_eligibility':'NO_ENTRY','publication_status':'RETURNED_IN_MEMORY_NOT_DURABLY_PUBLISHED'}
