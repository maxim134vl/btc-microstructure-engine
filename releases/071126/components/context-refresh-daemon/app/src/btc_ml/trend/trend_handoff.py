"""Approved H1: receipts in accepted C_E, never market/trading grants."""
from copy import deepcopy
from dataclasses import dataclass,asdict
from .trend_journal import digest,Blocked
from .trend_scope_sessions import head,root_id,REASON
VERSION='SCOPE_CONTINUITY_ADMISSION_V1_H1_H2'
PURPOSES=('CONTINUITY_COMPARE','UNFINISHED_CHAIN_CONTINUATION','HISTORICAL_ORIGIN_MONITOR','POST_FAILURE_OBSERVATIONAL_SCAN')
@dataclass(frozen=True)
class ScopeContinuityAdmissionV1:
 scope_ref:str
 predecessor_scope_ref:str
 timeframe:str
 canonical_context_proof_ref:dict
 checkpoint:dict
 root_config_sha:str
 baseline_sha:str
 baseline_available_at:str
 policy_available_at:str
 economic_reference_id:str|None
 economic_confirmation_ref:str|None
 owner_generation:int
 r2_lineage_ref:str|None
 opportunity_anchor_ref:str|None
 capture_domain_ref:tuple
 source_membership:tuple
 coverage_assertion_sha:str
 unfinished_prefix_ref:str
 evidence_authority_ref:str
 authority_class:str
 purpose:str
 effective_available_at:str
 first_source_packet:dict
 entry:str='NO_ENTRY'
 version:str=VERSION
 def to_dict(self):
  import json
  return json.loads(json.dumps(asdict(self)))
def checkpoint(system):
 r=system.j.records
 return {'sequence':len(r),'record_sha':r[-1]['sha'],'state_sha':r[-1]['state_sha'],'C_E':next((x['sha'] for x in reversed(r) if x['boundary']=='C_E'),None),'C_P':next((x['sha'] for x in reversed(r) if x['boundary']=='C_P'),None)}
def prefix_hash(t):return digest({k:t[k] for k in ('role','prefix','candidate','windows','looks','fragments','touches','tombstones','generation','blocked')})
def build_request(system,tf,purpose,first_packet,cutoff):
 """Authored fixture request builder; verification still independent and mandatory."""
 s=system.state;sid=head(s,tf);scope=s.get('scope_sessions',{}).get(sid)
 if not scope:raise Blocked('CURRENT_LINKED_SCOPE_REQUIRED')
 t=s['tf'][tf];ref=s['economic'].get(t['owner'] or t['research_ref']);r=s['r2']['timeframes'][tf];c=s['config']
 return ScopeContinuityAdmissionV1(sid,scope['predecessor'],tf,deepcopy(scope['proof']),checkpoint(system),digest(c),digest(c['baseline']),c['baseline_available_at'],c['policy_available_at'],ref['id'] if ref else None,ref['confirmation_ref'] if ref else None,t['generation'],r['context_episode_id'],r['active_opportunity_id'],(c['market'],'BTCUSDT','AGG_TRADE',c['capture_family'],c['coverage_ref']),tuple((k,s['raw'][k]['trade']['payload_sha']) for k in s['raw_order']),digest(c['coverage_assertion']),prefix_hash(t),c['authority_sha'] or '',ref['authority_class'] if ref else 'POST_FAILURE_OBSERVATIONAL_ONLY',purpose,cutoff,deepcopy(first_packet)).to_dict()
def check(s,r,records):
 from .trend_evidence import E,RawOccurrence
 required=set(ScopeContinuityAdmissionV1.__dataclass_fields__)
 if set(r)!=required or r['version']!=VERSION or r['entry']!='NO_ENTRY':raise Blocked('ADMISSION_SCHEMA_OR_AUTHORITY')
 tf=r['timeframe'];c=s['config'];scope=s.get('scope_sessions',{}).get(r['scope_ref'])
 if tf not in s['tf'] or not scope or scope['timeframe']!=tf or head(s,tf)!=r['scope_ref']:raise Blocked('ADMISSION_OWN_SCOPE')
 if r['predecessor_scope_ref']!=scope['predecessor'] or r['canonical_context_proof_ref']!=scope['proof']:raise Blocked('ADMISSION_PREDECESSOR_CONTEXT')
 cp=r['checkpoint'];i=cp.get('sequence',0)-1
 if i<0 or i>=len(records) or records[i]['state_sha']!=digest(s) or records[i]['sha']!=cp.get('record_sha') or cp.get('state_sha')!=digest(s):raise Blocked('ADMISSION_CHECKPOINT')
 for b in ('C_E','C_P'):
  if cp.get(b)!=next((x['sha'] for x in reversed(records[:i+1]) if x['boundary']==b),None):raise Blocked('ADMISSION_COMMIT_HEAD')
 if c['mode']!='FIXTURE_ONLY' or scope['proof']['origin']!='FIXTURE_ONLY':raise Blocked('REAL_ADMISSION_UNQUALIFIED')
 if (r['root_config_sha'],r['baseline_sha'],r['baseline_available_at'],r['policy_available_at'])!=(digest(c),digest(c['baseline']),c['baseline_available_at'],c['policy_available_at']):raise Blocked('ADMISSION_PINS')
 if r['purpose'] not in PURPOSES:raise Blocked('ADMISSION_PURPOSE')
 t=s['tf'][tf]
 assigned=set(t['prefix'])
 for row in t['looks']+t['fragments']:assigned.update(row.get('sources',row.get('source_ids',[])))
 for row in t['windows'].values():assigned.update(row['source_ids'])
 if set(s['raw_order'])-assigned:raise Blocked('ADMISSION_UNASSESSED_SCOPE_SOURCE')
 ref=s['economic'].get(t['owner'] or t['research_ref']);key=ref['id'] if ref else None
 if (r['economic_reference_id'],r['economic_confirmation_ref'],r['owner_generation'],r['unfinished_prefix_ref'])!=(key,ref['confirmation_ref'] if ref else None,t['generation'],prefix_hash(t)):raise Blocked('ADMISSION_ECONOMIC_PREFIX_ANCESTRY')
 node=key;seen=set()
 while node:
  if node in seen or node not in s['economic']:raise Blocked('ADMISSION_MISSING_ANCESTOR')
  seen.add(node)
  if s['economic'][node]['tf']!=tf:raise Blocked('ADMISSION_CROSS_TF_ANCESTOR')
  node=s['economic'][node]['parent_id']
 rt=s['r2']['timeframes'][tf]
 if (r['r2_lineage_ref'],r['opportunity_anchor_ref'])!=(rt['context_episode_id'],rt['active_opportunity_id']):raise Blocked('ADMISSION_R2_OBLIGATION_PIN')
 if r['source_membership']!=[[k,s['raw'][k]['trade']['payload_sha']] for k in s['raw_order']] or r['coverage_assertion_sha']!=digest(c['coverage_assertion']):raise Blocked('ADMISSION_COMPLETE_MEMBERSHIP')
 if r['capture_domain_ref']!=[c['market'],'BTCUSDT','AGG_TRADE',c['capture_family'],c['coverage_ref']]:raise Blocked('ADMISSION_SOURCE_DOMAIN')
 proof=c['coverage_assertion']
 if c['sequence']!='CONTIGUOUS_PLUS_ONE' or proof.get('kind')!='SYNTHETIC_COMPLETE_BY_CONSTRUCTION' or proof.get('capture_family')!=c['capture_family'] or t['blocked']:raise Blocked('ADMISSION_COVERAGE_INCOMPLETE')
 prior=c['predecessor'];last=None
 for k in s['raw_order']:
  raw=s['raw'][k];q=raw['trade']
  if q['native_id']!=prior+1 or raw['predecessor']!=prior or not raw['fixture_authorized'] or proof['memberships'].get(k)!=q['payload_sha']:raise Blocked('ADMISSION_COVERAGE_INCOMPLETE')
  if last and (E.utc(q['trade_time'])<E.utc(last['trade_time']) or E.utc(raw['available_at'])<E.utc(last['available_at'])):raise Blocked('ADMISSION_SOURCE_CHRONOLOGY')
  prior=q['native_id'];last={**q,'available_at':raw['available_at']}
 raw=RawOccurrence.from_dict(r['first_source_packet']);raw.validate(raw.available_at)
 if (raw.trade.market,raw.trade.symbol,raw.trade.stream)!=(c['market'],'BTCUSDT','AGG_TRADE'):raise Blocked('ADMISSION_FIRST_SOURCE_DOMAIN')
 if raw.predecessor!=s['source_cursor'] or raw.trade.native_id!=s['source_cursor']+1 or raw.trade.source_key in s['raw']:raise Blocked('ADMISSION_FIRST_UNASSIGNED_SOURCE')
 if (raw.capture_origin,raw.capture_family,raw.coverage_ref)!=(c['mode'],c['capture_family'],c['coverage_ref']) or proof['memberships'].get(raw.trade.source_key)!=raw.trade.payload_sha:raise Blocked('ADMISSION_FIRST_SOURCE_AUTHORITY')
 now=E.utc(r['effective_available_at']);first=E.utc(raw.trade.trade_time)
 if not E.utc(scope['proof']['available_at'])<=now<first or not E.utc(c['baseline_available_at'])<first or not E.utc(c['policy_available_at'])<first or (last and E.utc(last['available_at'])>now):raise Blocked('ADMISSION_LATE_OR_NONCAUSAL')
 if r['evidence_authority_ref']!=c['authority_sha'] or not r['evidence_authority_ref']:raise Blocked('ADMISSION_FIXTURE_AUTHORITY')
 purpose=r['purpose'];direction=scope['proof']['direction']
 if purpose in ('CONTINUITY_COMPARE','UNFINISHED_CHAIN_CONTINUATION'):
  if not ref or direction!=ref['direction'] or direction not in ('LONG','SHORT') or r['authority_class']!=ref['authority_class']:raise Blocked('ADMISSION_DIRECTION_OR_REFERENCE')
  if purpose=='CONTINUITY_COMPARE' and (t['candidate'] or t['prefix']):raise Blocked('ADMISSION_UNFINISHED_PERMISSION_REQUIRED')
  if purpose=='UNFINISHED_CHAIN_CONTINUATION' and not (t['candidate'] or t['prefix']):raise Blocked('ADMISSION_NO_UNFINISHED_CHAIN')
 elif purpose=='HISTORICAL_ORIGIN_MONITOR':
  if not ref or r['authority_class']!=ref['authority_class']:raise Blocked('ADMISSION_ORIGIN_MISSING')
  if t['candidate'] or t['prefix']:raise Blocked('ADMISSION_MONITOR_PREFIX_UNRESOLVED')
 else:
  if ref or not t['tombstones'] or r['authority_class']!='POST_FAILURE_OBSERVATIONAL_ONLY':raise Blocked('ADMISSION_POST_FAILURE_AUTHORITY')
  if direction not in ('LONG','SHORT'):raise Blocked('ADMISSION_DIRECTION_OR_REFERENCE')
 return True
def admit(system,request,cutoff,*,fault=None):
 from .trend_evidence import E,RawOccurrence
 with system.j.lock():
  s=deepcopy(system.j.state);r=deepcopy(request);identity=digest(r)
  if identity in s.get('scope_admissions',{}):return {'status':'DUPLICATE_NO_EFFECT','scope_admission_ref':identity,'entry':'NO_ENTRY'}
  if r.get('effective_available_at')!=cutoff:raise Blocked('ADMISSION_CUTOFF_MISMATCH')
  check(s,r,system.j.records)
  raw=RawOccurrence.from_dict(r['first_source_packet'])
  if not system.authority or not system.authority.permits(s['config'],raw):raise Blocked('ADMISSION_UNAPPROVED_AUTHORITY')
  for old in s.get('scope_admissions',{}).values():
   if (old['scope_ref'],old['purpose'],old['first_source_packet']['trade']['native_id'])==(r['scope_ref'],r['purpose'],raw.trade.native_id):raise Blocked('ADMISSION_CONTENT_CONFLICT')
  s.setdefault('scope_admissions',{})[identity]=r
  system.j.stage('ADMISSION_PREPARED',r,fault)
  return system.j.append('C_E',{'kind':'SCOPE_CONTINUITY_ADMISSION','id':identity},s,{'status':'ADMITTED_RESEARCH_PERMISSION','scope_admission_ref':identity,'entry':'NO_ENTRY'},fault)
def verify_admissions(state,records):
 for identity,r in state.get('scope_admissions',{}).items():
  if identity!=digest(r):raise Blocked('ADMISSION_CONTENT_HASH')
  i=r['checkpoint']['sequence']-1
  if i<0 or i>=len(records):raise Blocked('ADMISSION_MISSING_CHECKPOINT')
  check(records[i]['state'],r,records[:i+1])
def validate_admissions(old,new,boundary):
 prior=(old or {}).get('scope_admissions',{});current=new.get('scope_admissions',{})
 for k,v in prior.items():
  if current.get(k)!=v:raise ValueError('IMMUTABLE_ADMISSION_PREFIX')
 added=set(current)-set(prior)
 if added:
  if boundary!='C_E' or len(added)!=1:raise ValueError('ADMISSION_COMMIT_BOUNDARY')
  for k in old:
   if k!='scope_admissions' and new[k]!=old[k]:raise ValueError('ADMISSION_MUTATED_ACCEPTED_STATE')
def permissions(s,tf,ids=None):
 from .trend_evidence import E
 sid=head(s,tf);found={}
 for identity,r in s.get('scope_admissions',{}).items():
  if r['scope_ref']!=sid:continue
  first=r['first_source_packet']['trade']['native_id']
  if ids:
   fresh=[s['raw'][k]['trade'] for k in ids if s['raw'][k]['trade']['native_id']>=first]
   if not fresh:continue
   if any(E.utc(q['trade_time'])<=E.utc(r['effective_available_at']) for q in fresh):continue
  found[r['purpose']]=(identity,r)
 return found
def can_process(s,tf,ids=None):
 if head(s,tf)==root_id(s,tf):return True
 p=permissions(s,tf,ids)
 return bool(p)
def context(s,tf,ids):
 c=s['config']['contexts'][tf]
 if head(s,tf)==root_id(s,tf):return c
 p=permissions(s,tf,ids);scope=s['scope_sessions'][head(s,tf)]['proof']
 if not p:raise Blocked(REASON)
 t=s['tf'][tf]
 old_candidate=any(v['context_id']!=scope['canonical_episode_id'] for v in t['candidate'].values())
 if old_candidate and 'UNFINISHED_CHAIN_CONTINUATION' not in p:raise Blocked('UNFINISHED_SCOPE_CONTINUITY_REQUIRED')
 if 'CONTINUITY_COMPARE' in p or 'UNFINISHED_CHAIN_CONTINUATION' in p or 'POST_FAILURE_OBSERVATIONAL_SCAN' in p:
  return {'id':scope['canonical_episode_id'],'direction':scope['direction'],'available_at':scope['available_at']}
 if 'HISTORICAL_ORIGIN_MONITOR' in p:
  r=p['HISTORICAL_ORIGIN_MONITOR'][1];ref=s['economic'].get(r['economic_reference_id'])
  if not ref or t['owner']!=ref['id']:raise Blocked('HISTORICAL_ORIGIN_REFERENCE_CHANGED')
  original=s['config']['contexts'][tf]
  if ref['context']==original['id']:available=original['available_at']
  else:
   proofs=[row['proof'] for row in s['scope_sessions'].values() if row['timeframe']==tf and row['proof']['canonical_episode_id']==ref['context']]
   if len(proofs)!=1:raise Blocked('HISTORICAL_CONTEXT_PROOF_MISSING')
   available=proofs[0]['available_at']
  return {'id':ref['context'],'direction':ref['direction'],'available_at':available}
 raise Blocked(REASON)
def bridge_bind(s,tf,o,request):
 if head(s,tf)==root_id(s,tf):return request
 from dataclasses import replace
 from .trend_evidence import QualifiedMarketEvidence
 ids=list(request['r2_payload']['source_event_ids']);p=permissions(s,tf,ids)
 purpose='HISTORICAL_ORIGIN_MONITOR' if request['event_type']=='BREAK' else 'UNFINISHED_CHAIN_CONTINUATION' if 'UNFINISHED_CHAIN_CONTINUATION' in p else 'CONTINUITY_COMPARE'
 if purpose not in p:raise Blocked('BRIDGE_SCOPE_PERMISSION')
 sid,grant=p[purpose];scope=s['scope_sessions'][head(s,tf)]['proof'];lineage=s['r2']['timeframes'][tf]['context_episode_id']
 if not lineage or lineage!=grant['r2_lineage_ref']:raise Blocked('BRIDGE_R2_LINEAGE')
 e=QualifiedMarketEvidence.from_dict(request['r2_payload'])
 if purpose!='HISTORICAL_ORIGIN_MONITOR' and (o.context_id!=scope['canonical_episode_id'] or o.context_direction!=scope['direction']):raise Blocked('BRIDGE_CURRENT_CANONICAL_SCOPE')
 request.update(canonical_scope_ref=head(s,tf),scope_admission_ref=sid,r2_lineage_ref=lineage,canonical_context_ref=scope['canonical_episode_id'],canonical_direction=scope['direction'],origin_monitor_ref=sid if purpose=='HISTORICAL_ORIGIN_MONITOR' else None)
 request['r2_payload']=replace(e,context_episode_id=lineage).to_dict()
 return request
def validate_bridge(s,req):
 tf=req['timeframe']
 if req.get('r2_payload',{}).get('origin')=='PAPER_OBSERVED':
  from .real_scope_proof import paper_permission,paper_segment
  paper_permission(s['config'],req['r2_payload']['evaluation_cutoff'])
  if req.get('economic_segment_id'):paper_segment(s,s['economic'].get(req['economic_segment_id']))
 if req.get('r2_payload',{}).get('origin')=='REAL_CANDIDATE':
  from .real_scope_proof import verify_real_scope_proof,trust_from_config
  verify_real_scope_proof(s['config'].get('real_scope_proof'),trust=trust_from_config(s['config']),timeframe=tf,cutoff=req['r2_payload']['evaluation_cutoff'])
 if head(s,tf)==root_id(s,tf):
  if req.get('scope_admission_ref'):raise Blocked('BRIDGE_FOREIGN_SCOPE')
  return
 r=s.get('scope_admissions',{}).get(req.get('scope_admission_ref'));scope=s['scope_sessions'][head(s,tf)]['proof']
 if not r or r['scope_ref']!=head(s,tf) or req.get('canonical_scope_ref')!=head(s,tf) or req.get('canonical_context_ref')!=scope['canonical_episode_id'] or req.get('canonical_direction')!=scope['direction']:raise Blocked('BRIDGE_CURRENT_CANONICAL_SCOPE')
 if req.get('r2_lineage_ref')!=s['r2']['timeframes'][tf]['context_episode_id'] or req['r2_payload']['context_episode_id']!=req['r2_lineage_ref'] or r['r2_lineage_ref']!=req['r2_lineage_ref']:raise Blocked('BRIDGE_R2_LINEAGE')
 seg=s['economic'].get(req['economic_segment_id'])
 if seg and (seg['context']!=scope['canonical_episode_id'] or seg['direction']!=scope['direction']):raise Blocked('BRIDGE_ECONOMIC_CANONICAL_SCOPE')
 if r['purpose']=='HISTORICAL_ORIGIN_MONITOR':
  if req['event_type']!='BREAK' or req.get('origin_monitor_ref')!=req['scope_admission_ref']:raise Blocked('BRIDGE_MONITOR_PURPOSE')
 elif r['purpose'] not in ('CONTINUITY_COMPARE','UNFINISHED_CHAIN_CONTINUATION'):raise Blocked('BRIDGE_PURPOSE')
 if req['r2_payload']['origin'] not in ('FIXTURE_ONLY','PAPER_OBSERVED'):raise Blocked('BRIDGE_REAL_AUTHORITY')

def validate_r2_commit(old,new,boundary,action):
 """No invented pending resolution or rewritten receipt accepted as a C_P state."""
 if not old or old['r2']==new['r2']:return
 if boundary!='C_P':raise ValueError('C_E_MUTATED_R2')
 from .trend_evidence import r2_restore,json_state,evaluate
 kind=action.get('kind')
 if kind=='PROJECT':
  req=old['intents'].get(action.get('attempt'))
  if not req:raise ValueError('C_P_MISSING_PROJECTION_INTENT')
  if req.get('scope_admission_ref'):validate_bridge(old,req)
  request={'kind':'market','evidence':req['r2_payload']}
 elif kind=='R2_BOOKKEEPING':
  request=action['request']
  if not can_bookkeep(old,request):raise ValueError('C_P_CURRENT_SCOPE_OPPORTUNITY_REQUIRED')
 else:raise ValueError('C_P_UNSUPPORTED_R2_STATE_CHANGE')
 expected,result=evaluate(r2_restore(deepcopy(old['r2'])),request)
 if result.status!='ACCEPTED' or json_state(expected)!=new['r2']:raise ValueError('C_P_R2_REDUCER_STATE_MISMATCH')

def queued_permission(s,q):
 """No retrospectively admitted old source or canonical wrapper for queued intent."""
 from .trend_evidence import obs_restore
 tf=q['timeframe']
 if head(s,tf)==root_id(s,tf):return True
 o=obs_restore(q['observation']);p=permissions(s,tf,list(o.source_ids))
 if q['event_type']=='BREAK':
  grant=p.get('HISTORICAL_ORIGIN_MONITOR')
  if not grant:return False
  ref=s['economic'].get(grant[1]['economic_reference_id'])
  return bool(ref and (o.context_id,o.context_direction)==(ref['context'],ref['direction']))
 scope=s['scope_sessions'][head(s,tf)]['proof']
 return bool(('CONTINUITY_COMPARE' in p or 'UNFINISHED_CHAIN_CONTINUATION' in p) and (o.context_id,o.context_direction)==(scope['canonical_episode_id'],scope['direction']))
def can_bookkeep(s,request):
 """H1 is not authority to request/expire a predecessor-scope opportunity."""
 tf=request.get('timeframe')
 if tf not in s['tf'] or request.get('kind')=='outcome' or head(s,tf)==root_id(s,tf):return True
 # Exact prior receipt retains original dedup/conflict handling, never a new request.
 if digest([tf,request.get('event_id')]) in s['r2']['receipts']:return True
 if request.get('kind') not in ('request','expire'):return False
 o=s['r2']['opportunities'].get(request.get('opportunity_id'))
 if not o or o['timeframe']!=tf:return False
 segid=s['admitted_segment_map'].get(o['source_evidence_id']);seg=s['economic'].get(segid);scope=s['scope_sessions'][head(s,tf)]['proof']
 if not seg or seg['tf']!=tf or seg['authority_class'] not in ('QUALIFIED_FIXTURE_ONLY','QUALIFIED_PAPER_OBSERVED') or (seg['context'],seg['direction'])!=(scope['canonical_episode_id'],scope['direction']):return False
 for aid,intent in s['intents'].items():
  result=s['projection_results'].get(aid,{})
  if intent['economic_segment_id']!=segid or result.get('status')!='ACCEPTED' or result.get('opportunity_id')!=o['opportunity_id']:continue
  try:validate_bridge(s,intent)
  except Blocked:continue
  return True
 return False
