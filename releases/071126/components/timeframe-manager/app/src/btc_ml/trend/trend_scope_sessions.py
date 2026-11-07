"""Linked immutable scope descriptors. No economic/R2 handoff grant.

All authority-bearing state remains in the accepted shared C_E/C_P journal.
New scopes collect original raw identities only; their economic admission is blocked.
"""
from copy import deepcopy
from datetime import datetime
import hashlib,json
VERSION='IMMUTABLE_LINKED_SCOPE_DESCRIPTORS_V1'
REASON='SCOPE_ECONOMIC_R2_HANDOFF_NOT_APPROVED'
def digest(x):
 return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def root_id(s,tf):
 c=s['config']
 from .trend_journal import _FrozenDict
 if isinstance(c,_FrozenDict):
  roots=getattr(c,'_cached_scope_roots',None)
  if roots is None:roots={};c._cached_scope_roots=roots
  if tf not in roots:roots[tf]=digest([VERSION,'INITIAL_RESEARCH_SCOPE',c,tf])
  return roots[tf]
 return digest([VERSION,'INITIAL_RESEARCH_SCOPE',c,tf])
def head(s,tf):
 heads=s.get('scope_heads',{})
 return heads[tf] if tf in heads else root_id(s,tf)
def suspended(s,tf):return head(s,tf)!=root_id(s,tf)
def stamp(x):
 t=datetime.fromisoformat(x.replace('Z','+00:00'))
 if t.tzinfo is None:raise ValueError('NAIVE_CONTEXT_CLOCK')
 return t

def validate_scopes(old,new,boundary):
 sessions=new.get('scope_sessions',{});heads=new.get('scope_heads',{})
 prior=(old or {}).get('scope_sessions',{})
 for key,value in prior.items():
  if sessions.get(key)!=value:raise ValueError('IMMUTABLE_SCOPE_SESSION_PREFIX')
 for tf in (old or {}).get('scope_heads',{}):
  if tf not in heads:raise ValueError('MISSING_SCOPE_HEAD')
 for key,r in sessions.items():
  if key!=digest({k:v for k,v in r.items() if k!='id'}):raise ValueError('SCOPE_IDENTITY')
  if r['timeframe'] not in new['config']['timeframes'] or r['root_config_sha']!=digest(new['config']):raise ValueError('SCOPE_ROOT_OR_TF')
  if r['predecessor']!=root_id(new,r['timeframe']):
   p=sessions.get(r['predecessor'])
   if not p or p['timeframe']!=r['timeframe']:raise ValueError('MISSING_OR_CROSS_TF_PREDECESSOR')
  if r['disposition']!=REASON or r['economic_authority']!='NOT_ESTABLISHED_FOR_SCOPE' or r['entry']!='NO_ENTRY':raise ValueError('SCOPE_AUTHORITY_ESCALATION')
 for tf,key in heads.items():
  if key not in sessions or sessions[key]['timeframe']!=tf:raise ValueError('SCOPE_HEAD_IDENTITY')
 if old:
  if boundary=='C_P' and any(new.get(k,{})!=old.get(k,{}) for k in ('scope_sessions','scope_heads')):raise ValueError('C_P_MUTATED_SCOPE')
  added=set(sessions)-set(prior)
  if added or heads!=old.get('scope_heads',{}):
   if boundary!='C_E' or len(added)!=1:raise ValueError('SCOPE_BINDING_BOUNDARY')
   r=sessions[next(iter(added))];tf=r['timeframe']
   if r['predecessor']!=head(old,tf) or heads.get(tf)!=r['id']:raise ValueError('SCOPE_PREDECESSOR_CAS')
   if any(heads.get(x)!=old.get('scope_heads',{}).get(x) for x in heads if x!=tf):raise ValueError('CROSS_TF_HEAD_CHANGE')
   for k in old:
    if k not in ('scope_sessions','scope_heads') and new[k]!=old[k]:raise ValueError('ROLLOVER_MUTATED_ACCEPTED_STATE')
  elif sessions!=prior:raise ValueError('SCOPE_MUTATION')

def bind(system,proof,expected_predecessor,cutoff,fault=None):
 """Research-only own-scope binding, one atomic accepted C_E commit.

FIXTURE_ONLY explicitly authored completed-context receipts are the only tested
input authority. REAL canonical publication verification is not implemented.
This does NOT generate an R2 event or initialize another ResearchSystem.
 """
 from .trend_journal import Blocked,state_checkpoint_fields,matches_state_checkpoint
 from .trend_evidence import DUR
 with system.j.lock():
  old=system.j.state;s=deepcopy(old);tf=proof.get('timeframe')
  if tf not in s['config']['timeframes']:raise Blocked('OWN_TIMEFRAME_REQUIRED')
  if s['config']['mode']=='REAL_CANDIDATE' and proof.get('origin')=='REAL_CANDIDATE':
   from .real_scope_proof import require_real_scope_proof
   require_real_scope_proof(system,proof,cutoff)
   # Source inspection is not economic/continuity authority. The partial REAL
   # verifier fails closed while original source-authority receipts are absent.
  if s['config']['mode']!='FIXTURE_ONLY' or proof.get('origin')!='FIXTURE_ONLY':raise Blocked('REAL_CANONICAL_SCOPE_PROOF_UNQUALIFIED')
  required={'origin','timeframe','canonical_episode_id','direction','source_bar_open','source_bar_close','available_at','publication_id','immutable_parent_sha','own_context_id'}
  if set(proof)!=required or not all(isinstance(v,str) and v for v in proof.values()):raise Blocked('EXACT_OWN_CONTEXT_PROOF_REQUIRED')
  if proof['own_context_id']!=proof['canonical_episode_id']:raise Blocked('EXPLICIT_CONTEXT_NAMESPACE_MAPPING_REQUIRED')
  if proof['direction'] not in ('LONG','SHORT','NONE'):raise Blocked('CONTEXT_DIRECTION')
  try:
   opened,close,available,end=map(stamp,[proof['source_bar_open'],proof['source_bar_close'],proof['available_at'],cutoff])
   if (close-opened).total_seconds()!=DUR[tf] or opened.timestamp()%DUR[tf] or not close<=available<=end:raise ValueError('NONCAUSAL_COMPLETED_CONTEXT')
   if len(proof['immutable_parent_sha'])!=64 or any(x not in '0123456789abcdef' for x in proof['immutable_parent_sha']):raise ValueError('CONTEXT_PARENT_SHA')
  except (ValueError,TypeError) as e:raise Blocked(str(e)) from e
  initial=s['config']['contexts'][tf]['id']
  if proof['canonical_episode_id']==initial:raise Blocked('INITIAL_EPISODE_REBIND_NOT_PERMITTED')
  for r in s.get('scope_sessions',{}).values():
   if r['timeframe']==tf and r['proof']['canonical_episode_id']==proof['canonical_episode_id']:
    if r['proof']!=proof or r['predecessor']!=expected_predecessor:raise Blocked('CONFLICTING_EPISODE_BINDING')
    if head(s,tf)!=r['id']:raise Blocked('SUPERSEDED_EPISODE_REUSE')
    return {'status':'DUPLICATE_NO_EFFECT','session_id':r['id'],'entry':'NO_ENTRY','reason':REASON}
  if head(s,tf)!=expected_predecessor:raise Blocked('MISSING_OR_CONFLICTING_PREDECESSOR')
  if tf in s.get('scope_heads',{}) and stamp(proof['available_at'])<=stamp(s['scope_sessions'][head(s,tf)]['proof']['available_at']):raise Blocked('CONTEXT_AVAILABILITY_REORDER')
  ce=next((r['sha'] for r in reversed(system.j.records) if r['boundary']=='C_E'),None)
  cp=next((r['sha'] for r in reversed(system.j.records) if r['boundary']=='C_P'),None)
  record={'version':VERSION,'timeframe':tf,'proof':deepcopy(proof),'predecessor':expected_predecessor,'root_config_sha':digest(s['config']),
   'pinned_baseline_sha':digest(s['config']['baseline']),'pinned_policy_available_at':s['config']['policy_available_at'],
   'checkpoint':{'sequence':len(system.j.records),'record_sha':system.j.records[-1]['sha'],**state_checkpoint_fields(system.j.records[-1]),'C_E':ce,'C_P':cp,'source_cursor':s['source_cursor'],'owner_generation':s['owner_generation'],'r2_sha':digest(s['r2'])},
   'disposition':REASON,'economic_authority':'NOT_ESTABLISHED_FOR_SCOPE','entry':'NO_ENTRY'}
  record['id']=digest(record);s.setdefault('scope_sessions',{})[record['id']]=record;s.setdefault('scope_heads',{})[tf]=record['id']
  system.j.stage('SESSION_BINDING_PREPARED',record,fault)
  return system.j.append('C_E',{'kind':'BIND_CONTEXT_SCOPE','session_id':record['id'],'cutoff':cutoff},s,
   {'status':'BOUND_UNQUALIFIED','session_id':record['id'],'entry':'NO_ENTRY','reason':REASON},fault)

def verify_chain(state,records):
 """Validate exact predecessor snapshots even when all outer hashes are valid."""
 from .trend_journal import Blocked,state_checkpoint_fields,matches_state_checkpoint
 for r in state.get('scope_sessions',{}).values():
  cp=r['checkpoint'];i=cp['sequence']-1
  if i<0 or i>=len(records):raise Blocked('MISSING_SCOPE_CHECKPOINT')
  original=records[i]
  if original['sha']!=cp['record_sha'] or not matches_state_checkpoint(original,cp):raise Blocked('SCOPE_CHECKPOINT_CONFLICT')
  pre=original['state']
  if cp['r2_sha']!=digest(pre['r2']) or cp['source_cursor']!=pre['source_cursor'] or cp['owner_generation']!=pre['owner_generation'] or r['predecessor']!=head(pre,r['timeframe']):raise Blocked('SCOPE_PREDECESSOR_STATE_CONFLICT')
  for b in ('C_E','C_P'):
   expected=next((x['sha'] for x in reversed(records[:i+1]) if x['boundary']==b),None)
   if cp[b]!=expected:raise Blocked('SCOPE_COMMIT_BOUNDARY_CONFLICT')

def verify(system):
 system.j.load();s=system.j.state;verify_chain(s,system.j.records)
 return {'sessions':len(s.get('scope_sessions',{})),'pending':sum(o['state']=='PENDING' for o in s['r2']['opportunities'].values()),'raw':len(s['raw']),'entry':'NO_ENTRY'}

def view(system,tf):
 """No old owner/phase is offered as current authority of the new context."""
 from .trend_journal import Blocked,state_checkpoint_fields,matches_state_checkpoint
 with system.j.lock():
  s=system.j.state
  if tf not in s['config']['timeframes']:raise Blocked('OWN_TIMEFRAME_REQUIRED')
  sid=head(s,tf);changed=suspended(s,tf);session=s.get('scope_sessions',{}).get(sid)
  # A retained source-only journal may honestly have no canonical context.
  # Expose missing evidence to the existing read-only consumer; never invent it.
  context=deepcopy(session['proof']) if changed else deepcopy(s['config'].get('contexts',{}).get(tf,{}))
  from .trend_handoff import permissions
  admissions=permissions(s,tf) if changed else {}
  owner=s['economic'].get(s['tf'][tf]['owner'])
  qualified_current=bool(changed and admissions and owner and owner['context']==context['canonical_episode_id'] and owner['authority_class']=='QUALIFIED_FIXTURE_ONLY')
  return {'scope_admission_refs':[v[0] for v in admissions.values()],
   'r2_lineage_ref':s['r2']['timeframes'][tf]['context_episode_id'],
   'r2_continuity_phase':s['r2']['timeframes'][tf]['trend_phase'] if admissions else None,
   'session_id':sid,'timeframe':tf,'own_context':context,'entry':'NO_ENTRY',
   'status':'NOT_QUALIFIED' if changed or not context else 'ORIGINAL_RESEARCH_SCOPE',
   'reason':REASON if changed else 'OWN_CONTEXT_UNAVAILABLE' if not context else 'NO_REAL_TRADING_AUTHORITY',
   'current_economic_authority':'QUALIFIED_FIXTURE_ONLY' if qualified_current else 'NOT_ESTABLISHED_FOR_SCOPE' if changed else 'ORIGINAL_RESEARCH_STATE_ONLY',
   'current_owner':owner['id'] if qualified_current else None if changed else s['tf'][tf]['owner'],
   'current_phase':None if changed else s['r2']['timeframes'][tf]['trend_phase'],
   'predecessor':session['predecessor'] if changed else None,
   'historical_owner':s['tf'][tf]['owner'],
   'historical_research_reference':s['tf'][tf]['research_ref'],
   'obligation_ledger_ref':{'root_config_sha':digest(s['config']),'r2_sha':digest(s['r2']),
    'pending_ids':[k for k,o in s['r2']['opportunities'].items() if o['timeframe']==tf and o['state']=='PENDING']},
   'raw_cursor':s['source_cursor'],'raw_capture_continues':True}
