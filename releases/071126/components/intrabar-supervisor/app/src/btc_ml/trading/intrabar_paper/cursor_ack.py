"""Bounded isolated Cursor/ACK owner. No trade callback, engine or activation.
Reuse exact Final65 receipts/MMR/witness/EX; no separate financial journal.
"""
from __future__ import annotations
import copy,datetime as dt,hashlib,json,sys,threading
from pathlib import Path
sys.dont_write_bytecode=True
from . import financial_authority_runtime as runtime
from . import cold_forward_guard as c
class AckBlocked(c.ColdBlocked):pass
def need(v,why):
 if not v:raise AckBlocked(why)
def raw(v):return (json.dumps(v,sort_keys=True,indent=2)+'\n').encode()
def now():return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
def legacy_ids(): return runtime.legacy_ids()
ACK_METHOD='cursor_ack_v1';MAX_CACHE=5000

def observe_only(before,after):
 mode=Path(runtime.authority().config['observation_config_path'])
 need(c.H(mode.read_bytes())==runtime.authority().config['observation_config_sha256'],'OBSERVATION_MODE_CONFIG_DRIFT')
 need(c.J(mode)['entry_source']=='s41_command_bus','OBSERVATION_MODE_NOT_QUALIFIED')
 c.monotonic_cursor('context_consumer_checkpoint.json',before,after)
 additions=set(after['processed_keys'])-set(before['processed_keys'])
 need(all(k.startswith(c.EPOCH+'|') and k.endswith('|CONSUME_OBSERVE') and k.split('|')[-2] in c.P['risk_pct'] for k in additions),'OBSERVATION_CANNOT_ADVANCE_FINANCIAL_KEY')
 return after

def project_cache(before,new_id,verified_ack_ids):
 """Only a cache, authority stays in retained original v3 ACK receipts."""
 # One authenticated immutable source read per projection, no cross-call cache.
 legacy=legacy_ids();legacy_set=set(legacy)
 need(legacy_set<=set(before),'LEGACY_ID_LOSS')
 need(len(before)==len(set(before)),'DUPLICATE_CACHE_ID')
 old=[i for i in before if i not in legacy_set]
 need(set(old)<=set(verified_ack_ids),'UNWITNESSED_CACHE_ID')
 if new_id not in legacy_set and new_id not in old:old.append(new_id)
 # Original IDs are never evicted. All evicted forward IDs must retain proof.
 return list(legacy)+old[-(MAX_CACHE-len(legacy)):]

def ack_key(command):return c.EPOCH+'|cursor_ack_v1|'+command['command_id']
def command_check(command):
 need(type(command) is dict and type(command.get('command_id')) is str and bool(command['command_id'].strip()),'COMMAND_ID_REQUIRED')
 need(command.get('timeframe') in c.P['risk_pct'],'OWN_TF_REQUIRED')
 need(command.get('intent') in {'OPEN_LONG','OPEN_SHORT','CLOSE','HOLD','NO_ACTION'},'INTENT_UNQUALIFIED')
 need(type(command.get('action_allowed')) is bool,'COMMAND_ALLOWED_TYPE_INVALID')
 # Use original tuple/list/scalar normalization, not a new command semantics.
 c.ec.command_association({'method':'apply_s41_manager_command','args':[command],'kwargs':{}})
 return copy.deepcopy(command)

def verify_ack_body(receipt,parent,tip,ar):
 body=receipt['source']['args'][0];command=command_check(body['command']);cmd=command['command_id'];tf=command['timeframe']
 need(cmd not in legacy_ids(),'OLD_PROCESSED_ID_CANNOT_GET_NEW_ACK')
 need(receipt['source']['method']==ACK_METHOD and receipt['source']['kwargs']=={} and len(receipt['source']['args'])==1,'ACK_SOURCE_SCHEMA_CONFLICT')
 need(body['schema']=='cursor_ack_authority_v1' and body['epoch']==c.EPOCH and body['command_sha256']==c.H(c.ec.canonical(command).encode()),'ACK_COMMAND_BINDING_CONFLICT')
 need(body['parent']==c.ec.head_reference(parent),'ACK_CURRENT_PARENT_CONFLICT')
 need(receipt['key']==ack_key(command) and receipt.get('source_key')==receipt['key'] and receipt['terminal'] is True,'ACK_STABLE_KEY_CONFLICT')
 need(receipt['books']=={} and set(receipt['documents'])=={'s41_command_cursor.json'},'ACK_MUST_NOT_CREATE_ECONOMIC_EFFECTS')
 need(receipt['publication']['scopes']==parent['publication']['scopes'] and receipt['publication']['files']==parent['publication']['files'],'ACK_MUST_NOT_CHANGE_FINANCIAL_SCOPE')
 result=receipt['result'];need(result['command_id']==cmd and result['timeframe']==tf and result['ack_is_fill'] is False,'ACK_RESULT_IDENTITY_CONFLICT')
 outcome=body['outcome'];status=outcome.get('status');kind=body['outcome_kind']
 need(outcome.get('command_id',cmd)==cmd and outcome.get('timeframe',tf)==tf,'OUTCOME_COMMAND_OR_TF_CONFLICT')
 need(status not in transient_statuses() and not str(status).startswith('EXIT_PENDING'),'TRANSIENT_RESULT_CANNOT_BE_ACKED')
 if kind=='FINAL_NO_EFFECT':
  need(body['economic_reference'] is None,'NO_EFFECT_CANNOT_CLAIM_FILL_REFERENCE')
  if status=='CLOSE_NO_POSITION':
   need(command['intent']=='CLOSE' and command['action_allowed'] is True and parent['publication']['scopes'][tf]['sleeve']['open_position_id'] is None,'NO_POSITION_NOT_PROVEN')
  elif status in {'CLOSE_SIDE_MISMATCH','CLOSE_STALE_FOR_NEWER_POSITION'}:verify_original_close_refusal(command,outcome,parent,ar)
  elif status=='IGNORED':need(command['intent'] in {'HOLD','NO_ACTION'} or command['action_allowed'] is False,'IGNORED_NOT_PROVEN')
  elif status=='ENTRY_BLOCKED_EXPIRED_COMMAND':
   need(command['intent'] in {'OPEN_LONG','OPEN_SHORT'},'EXPIRED_INTENT_CONFLICT')
   stamp=dt.datetime.fromisoformat(command['evaluation_timestamp'].replace('Z','+00:00'));evaluation=dt.datetime.fromisoformat(body['evaluated_at'].replace('Z','+00:00'))
   need(stamp.tzinfo is not None and evaluation.tzinfo is not None and 0<float(command['command_ttl_seconds'])<(evaluation-stamp).total_seconds(),'EXPIRY_NOT_PROVEN')
  elif body.get('completion_source')=='S41_ORIGINAL_PREFLIGHT_REJECTION':
   need(command['intent'] in {'OPEN_LONG','OPEN_SHORT'} and str(status).startswith('ENTRY_BLOCKED_'),'PREFLIGHT_REJECTION_CONFLICT')
  else:raise AckBlocked('NO_EFFECT_STATUS_REQUIRES_QUALIFIED_PROCESSING_CONTRACT')
  need(result['status']=='ACK_FINAL_NO_EFFECT','ACK_KIND_CONFLICT')
 elif kind in {'ECONOMIC_COMMITTED','RECORDED_FINAL_NO_EFFECT'}:
  ref=body['economic_reference'];need(ref is not None and ref['generation']<=parent['publication']['generation'],'EFFECT_REFERENCE_NOT_PRIOR')
  prior,effect=c.ec.authenticated_prior(tip,ref,ar.parent,c.EPOCH)
  need(effect.get('terminal') is True and effect['source']['method']=='apply_s41_manager_command','TERMINAL_COMMAND_RECEIPT_REQUIRED')
  need(c.ec.same_association(effect['source'],{'method':'apply_s41_manager_command','args':[command],'kwargs':{}}),'EFFECT_COMMAND_IDENTITY_CONFLICT')
  need(effect['result']==outcome,'EFFECT_RESULT_MISMATCH')
  if kind=='RECORDED_FINAL_NO_EFFECT':
   need(not any(effect['books'].get(t,{}).get('data') for t in ('orders','fills','trades','positions')) and bool(status),'NO_EFFECT_RECEIPT_CONFLICT')
   need(result['status']=='ACK_FINAL_NO_EFFECT','ACK_KIND_CONFLICT');return command
  need(status in {'ENTERED','EXITED'},'ECONOMIC_RESULT_REQUIRED')
  need(bool(effect['books'].get('fills',{}).get('data')),'ECONOMIC_ACK_WITHOUT_FILL_RECEIPT')
  fills=c.parse_rows(effect['books']['fills']['data'].encode());wanted='ENTRY' if status=='ENTERED' else 'EXIT'
  need((status=='ENTERED' and command['intent'] in {'OPEN_LONG','OPEN_SHORT'} or status=='EXITED' and command['intent']=='CLOSE') and any(x['timeframe']==tf and x['action']==wanted for x in fills),'EFFECT_ACK_ACTION_OR_TF_CONFLICT')
  if isinstance(outcome.get('fill'),dict):need(outcome['fill']['fill_id'] in {x['fill_id'] for x in fills},'RESULT_FILL_RECEIPT_CONFLICT')
  need(result['status']=='ACK_COMMITTED_RESULT','ACK_KIND_CONFLICT')
 else:raise AckBlocked('ACK_OUTCOME_KIND_UNQUALIFIED')
 return command

class GuardExtension:
 def begin(self):return {'acks':{},'preparations':{},'dispositions':{}}
 def receipt(self,r,prev,tip,ar,docs,state):
  from .quarantine_barrier import BARRIER,METHOD,verify_transition
  if BARRIER in r['documents']:need(r['source']['method']==METHOD,'BARRIER_REQUIRES_QUARANTINE_OWNER')
  if r['source']['method']==METHOD:
   commands=verify_transition(r,prev,tip,ar,docs,state)
   for command in commands:
    i=command['command_id'];need(i not in state['acks'],'DUPLICATE_QUARANTINE_ACK');state['acks'][i]={'command':command,'key':r['key'],'generation':r['publication']['generation']}
  if r['source']['method']==ACK_METHOD:
   command=verify_ack_body(r,prev,tip,ar);i=command['command_id'];need(i not in state['acks'],'DUPLICATE_ACK_EFFECT')
   state['acks'][i]={'command':command,'key':r['key'],'generation':r['publication']['generation']}
 def cursor(self,name,before,after,r,state):
  from .quarantine_barrier import BARRIER,METHOD,barrier
  if name==BARRIER:
   need(r['source']['method']==METHOD,'BARRIER_OWNER_REQUIRED');barrier(raw(before));barrier(raw(after));return
  if name=='s41_command_cursor.json' and r['source']['method']==METHOD:
   need(r['source']['args'][0]['stage']=='DISPOSE','QUARANTINE_CURSOR_ONLY_AT_DISPOSITION');return
  if name=='context_consumer_checkpoint.json':
   c.monotonic_cursor(name,before,after)
   additions=set(after['processed_keys'])-set(before['processed_keys'])
   for key in additions:
    parts=key.split('|');need(len(parts)==4 and parts[0]==c.EPOCH and parts[2] in c.P['risk_pct'],'FINANCIAL_CONTEXT_KEY_SCHEMA_CONFLICT')
    if parts[3]=='CONSUME_OBSERVE':continue
    method=r['source']['method'];args=r['source'].get('args') or []
    if method in {'update_from_trade','update_bbo_from_market'}:
     fills=c.parse_rows(r['books'].get('fills',{}).get('data','').encode())
     need(parts[3].startswith('EXIT') and r.get('terminal') is True and any(x['timeframe']==parts[2] and x['action']=='EXIT' for x in fills),'MARKET_EXIT_COMPLETION_MISSING')
     continue
    need(method in {'apply_s41_manager_command','process_context_event'} and bool(args),'FINANCIAL_CONTEXT_COMPLETION_SOURCE_MISSING')
    origin=args[0];identity=origin.get('command_id') if method=='apply_s41_manager_command' else origin.get('context_event_id',origin.get('event_id'))
    need(identity==parts[1] and origin.get('timeframe')==parts[2] and r.get('terminal') is True,'FINANCIAL_CONTEXT_COMPLETION_IDENTITY_CONFLICT')
    result=r['result'];status=result.get('status') if isinstance(result,dict) else None
    fills=c.parse_rows(r['books'].get('fills',{}).get('data','').encode())
    if status in {'ENTERED','EXITED'}:
     action='ENTRY' if status=='ENTERED' else 'EXIT'
     need(parts[3].startswith(action) and any(x['timeframe']==parts[2] and x['action']==action for x in fills),'FINANCIAL_CONTEXT_FILL_COMPLETION_MISSING')
    else:
     need(status not in transient_statuses() and not str(status).startswith('EXIT_PENDING') and bool(status) and not any(r['books'].get(t,{}).get('data') for t in ('orders','fills','trades','positions')),'FINANCIAL_CONTEXT_TERMINAL_RESULT_UNQUALIFIED')
   return
  need(r['source']['method']==ACK_METHOD,'FINANCIAL_CURSOR_REQUIRES_ACK_AUTHORITY')
  command=r['source']['args'][0]['command'];expected=project_cache(before['processed_command_ids'],command['command_id'],state['acks'])
  need(set(before)==set(after) and after['schema_version']==before['schema_version'] and after['consume_after']==before['consume_after'],'CURSOR_SCHEMA_OR_BOUNDARY_CHANGE')
  need(after['processed_command_ids']==expected,'CURSOR_ACK_COVERAGE_OR_PROJECTION_CONFLICT')
  need(dt.datetime.fromisoformat(after['updated_at'].replace('Z','+00:00'))>=dt.datetime.fromisoformat(before['updated_at'].replace('Z','+00:00')),'CURSOR_TIME_REGRESSION')
 def bridge(self,name,expected,entry,r,state):
  if name!='context_consumer_checkpoint.json' or entry['before']==c.H(expected):return expected
  need('observation_before_data' in entry,'OBSERVATION_FINANCIAL_BRIDGE_MISSING')
  bridge=entry['observation_before_data'].encode();need(c.H(bridge)==entry['before'],'OBSERVATION_BRIDGE_HASH_CONFLICT')
  observe_only(json.loads(expected),json.loads(bridge));return bridge
 def final_document(self,name,expected,actual,state):
  if actual==expected:return
  if name=='context_consumer_checkpoint.json':observe_only(json.loads(expected),json.loads(actual));return
  raise AckBlocked('UNRECEIPTED_FINANCIAL_CURSOR_OR_DOCUMENT:'+name)

class AckOwner:
 def __init__(self,books,anchor,pin):
  self.books=books;self.root=books.root.parent;runtime.activate(self.root);self.case=c.case_guard(runtime.case_root());self.anchor=Path(anchor);self.pin=pin;self.ext=GuardExtension()
  self.guard=c.ColdValidator(self.case,anchor,pin,extension=self.ext)
 def _verify_owned(self):
  need(self.books.owns_exclusive(),'OWNER_EX_REQUIRED');return self.guard._verify(None)
 def lookup(self,command):
  with c.locked(self.case) if not self.books.owns_exclusive() else __import__('contextlib').nullcontext():
   return self._lookup_locked(command)
 def _lookup_locked(self,command):
  command_check(command)
  proof=self.guard._verify(None)
  if command['command_id'] in legacy_ids():return {'state':'ALREADY_PROCESSED_LEGACY','ack_is_fill':False,'new_receipt':False}
  p=self.books.commit.receipt_path(ack_key(command))
  if not p.exists():
   from .quarantine_barrier import METHOD
   previous=proof['verified_ack_index'].get(command['command_id'])
   if previous is None:return {'state':'RECEIVED_NOT_ACKED','ack_is_fill':False}
   need(c.ec.same_association({'method':'apply_s41_manager_command','args':[previous['command']],'kwargs':{}},{'method':'apply_s41_manager_command','args':[command],'kwargs':{}}),'QUARANTINE_DUPLICATE_PAYLOAD_CONFLICT')
   receipt_path=self.books.commit.receipt_path(previous['key']);r=self.books.commit.load(receipt_path)
   need(r['source']['method']==METHOD,'ACK_INDEX_RECEIPT_KIND_CONFLICT')
   head=c.ec.verify_committed_head(self.root,c.EPOCH)
   prior={'schema':c.ec.HEAD_SCHEMA,'epoch':c.EPOCH,'publication':r['publication'],'receipt_sha256':c.H(receipt_path.read_bytes())}
   c.ec.authenticated_prior(head,c.ec.head_reference(prior),self.root,c.EPOCH)
   return {'state':'ALREADY_PROCESSED_QUARANTINED','ack_is_fill':False,'receipt_key':r['key']}
  receipt=self.books.commit.load(p)
  need(receipt['source']['args'][0]['command']==command,'DUPLICATE_COMMAND_PAYLOAD_OR_TF_CONFLICT')
  self.guard._verify(None) if self.books.owns_exclusive() else self.guard.verify();return {'state':'ALREADY_PROCESSED','ack_is_fill':False,'receipt_key':receipt['key']}
 def publish(self,command,outcome=None,economic_reference=None,expected_cursor_sha=None,phase=None,completion_source=None):
  command=command_check(command);hook=phase or (lambda n:None)
  with self.books.exclusive():
   proof=self._verify_owned();p=self.books.commit.receipt_path(ack_key(command))
   if command['command_id'] in legacy_ids():return {'state':'ALREADY_PROCESSED_LEGACY','ack_is_fill':False,'new_receipt':False}
   if p.exists():
    saved=self.books.commit.load(p);need(saved['source']['args'][0]['command']==command,'DUPLICATE_COMMAND_PAYLOAD_OR_TF_CONFLICT')
    return {'state':'ALREADY_PROCESSED','receipt_key':saved['key'],'ack_is_fill':False}
   cursor_path=self.root/'s41_command_cursor.json';old_raw=cursor_path.read_bytes();before=json.loads(old_raw)
   if expected_cursor_sha is not None:need(c.H(old_raw)==expected_cursor_sha,'STALE_CURSOR_PROPOSAL_REJECTED')
   head=c.ec.verify_committed_head(self.root,c.EPOCH)
   if economic_reference is None:
    if outcome is None:raise AckBlocked('ORIGINAL_RESULT_REQUIRED')
    if command['intent'] in {'OPEN_LONG','OPEN_SHORT'} and outcome.get('status')=='ENTRY_BLOCKED_EXPIRED_COMMAND':need(command.get('intent') in {'OPEN_LONG','OPEN_SHORT'},'EXPIRED_INTENT_REQUIRED')
    kind='FINAL_NO_EFFECT'
   else:kind='ECONOMIC_COMMITTED' if (outcome or {}).get('status') in {'ENTERED','EXITED'} else 'RECORDED_FINAL_NO_EFFECT'
   status=(outcome or {}).get('status')
   if status in transient_statuses() or str(status).startswith('EXIT_PENDING'):
    return {'state':'RETRYABLE','original_result':outcome,'cursor_advanced':False,'ack_is_fill':False}
   # Build the projection only from retained authenticated ACKs, never cache alone.
   # The index is supplied only by this call's verified native EX prefix/suffix
   # proof. It is not reconstructed from cursor cache or an unpinned memo.
   ack_ids=proof['verified_ack_index']
   after=copy.deepcopy(before);after['processed_command_ids']=project_cache(before['processed_command_ids'],command['command_id'],ack_ids);after['updated_at']=now()
   body={'schema':'cursor_ack_authority_v1','epoch':c.EPOCH,'command':command,'command_sha256':c.H(c.ec.canonical(command).encode()),'parent':c.ec.head_reference(head),'outcome':outcome,'outcome_kind':kind,'economic_reference':economic_reference,'evaluated_at':now(),'execution_permission':False,'completion_source':completion_source}
   source={'method':ACK_METHOD,'args':[body],'kwargs':{}};key=ack_key(command);g=head['publication']['generation']+1
   result={'status':'ACK_FINAL_NO_EFFECT' if kind!='ECONOMIC_COMMITTED' else 'ACK_COMMITTED_RESULT','command_id':command['command_id'],'timeframe':command['timeframe'],'ack_is_fill':False}
   pub={'schema':c.ec.HEAD_SCHEMA,'epoch':c.EPOCH,'generation':g,'parent':c.ec.head_reference(head),'key':key,'association':c.ec.command_association(source),'files':head['publication']['files'],'scopes':head['publication']['scopes']}
   occupancy={tf:s['sleeve']['open_position_id'] for tf,s in head['publication']['scopes'].items() if s['sleeve']['open_position_id']}
   intent={'schema':'execution_commit_v3','epoch':c.EPOCH,'key':key,'source_key':key,'status':'INTENT','source':source,'result':result,'terminal':True,'books':{},'documents':{'s41_command_cursor.json':{'before':c.H(old_raw),'data':raw(after).decode()}},'occupancy_before':occupancy,'occupancy_after':occupancy,'publication':pub}
   pub['history']=c.fh.plan(head['publication']['history'],c.fh.receipt_leaf(intent))[0]
   # Current tip is sufficient for existing prior membership. New metadata
   # receipt cannot introduce financial authority or economic effects.
   verify_ack_body(intent,head,head,self.root/'execution_commits_v1')
   need(not self.books.commit.pending.exists(),'PENDING_WRITER_BLOCKED')
   c.ec.atomic_bytes(self.books.commit.pending,c.ec.encode_authority(intent));hook('after_ack_intent')
   old_phase=self.books.commit._phase;self.books.commit._phase=hook
   try:self.books.commit.materialize(intent)
   finally:self.books.commit._phase=old_phase
   self._verify_owned();return {'state':'ACK_COMMITTED','receipt_key':key,'ack_is_fill':False,'cursor_advanced':True}
 def recover_ack(self):
  with self.books.exclusive():
   if not self.books.commit.pending.exists():self._verify_owned();return {'state':'NO_PENDING'}
   p=self.books.commit.load(self.books.commit.pending)
   need(p.get('schema')=='execution_commit_v3' and p['source']['method']==ACK_METHOD,'FOREIGN_PENDING_NO_RECOVERY')
   # Immutable legacy prefixes/epoch/contracts/receipt pins before original recovery.
   c.validate_anchor(self.case,self.anchor,self.pin)
   for m in c.P['state_members']:
    if '/books/' in m['path'] or '/receipts/' in m['path'] or '/paper_epochs/' in m['path'] or m['path'].endswith('/trading_contract.json'):
     with (runtime.member_path(self.case,m['path'])).open('rb') as f:initial=f.read(m['bytes'])
     need(c.H(initial)==m['sha256'],'LEGACY_CORRUPTION_BEFORE_RECOVERY')
   pub=p['publication'];ref=pub['parent'];need(type(ref['generation']) is int and pub['generation']==ref['generation']+1,'PENDING_PARENT_INVALID')
   parent_receipt=self.books.commit.load(self.root/'execution_commits_v1/publications'/f"{ref['generation']}.json")
   parent={'schema':c.ec.HEAD_SCHEMA,'epoch':c.EPOCH,'publication':parent_receipt['publication'],'receipt_sha256':c.H((self.root/'execution_commits_v1/publications'/f"{ref['generation']}.json").read_bytes())}
   need(c.ec.head_reference(parent)==ref,'PENDING_PARENT_IDENTITY_CONFLICT')
   verify_ack_body(p,parent,parent,self.root/'execution_commits_v1')
   need(pub['files']==c.ec.constituent_identities(self.root),'PENDING_FINANCIAL_CONSTITUENTS_CONFLICT')
   need(pub['history']==c.fh.plan(parent['publication']['history'],c.fh.receipt_leaf(p))[0],'PENDING_HISTORY_PLAN_CONFLICT')
   doc=p['documents']['s41_command_cursor.json'];present=(self.root/'s41_command_cursor.json').read_bytes()
   need(c.H(present) in {doc['before'],c.H(doc['data'].encode())},'PENDING_CURSOR_UNEXPECTED_STATE')
   # Read-only reconstruct parent cursor from existing receipt chain; no invented
   # snapshot or reset, and validate the exact intended successor before recovery.
   prior=c.J(runtime.source_financial_root()/'s41_command_cursor.json');ack_state={'acks':{}}
   for n in range(2,ref['generation']+1):
    r=c.ec.decode_authority(self.root/'execution_commits_v1/publications'/f'{n}.json',c.EPOCH)
    from .quarantine_barrier import acknowledged_commands
    for cmd in acknowledged_commands(r):ack_state['acks'][cmd['command_id']]={}
    if 's41_command_cursor.json' in r['documents']:prior=json.loads(r['documents']['s41_command_cursor.json']['data'])
   need(c.H(raw(prior))==doc['before'] or c.H((runtime.source_financial_root()/'s41_command_cursor.json').read_bytes())==doc['before'],'PENDING_CURSOR_PARENT_CONFLICT')
   command=p['source']['args'][0]['command'];ack_state['acks'][command['command_id']]={}
   self.ext.cursor('s41_command_cursor.json',prior,json.loads(doc['data']),p,ack_state)
   self.books.commit.recover();self._verify_owned();return {'state':'ACK_RECOVERED','ack_is_fill':False}

def stage_financial_checkpoint(commit,path,data):
 """Small future save hook; preserves real prior observation bytes, under EX."""
 need(commit.books.owns_exclusive(),'FINANCIAL_CHECKPOINT_REQUIRES_EX')
 before=Path(path).read_bytes();commit.stage_document(Path(path),data)
 commit.documents['context_consumer_checkpoint.json']['observation_before_data']=before.decode()


def transient_statuses():
 from .s41_command_consumer import _TRANSIENT_OPEN_BLOCKS
 return _TRANSIENT_OPEN_BLOCKS


def verify_original_close_refusal(command,outcome,parent,ar):
 from .engine import IntrabarPaperEngine,_as_utc_datetime
 tf=command['timeframe'];need(command['intent']=='CLOSE' and command['action_allowed'] is True,'CLOSE_REFUSAL_INTENT_CONFLICT')
 own=parent['publication']['scopes'][tf]['sleeve']['open_position_id'];need(own is not None,'CLOSE_REFUSAL_NO_POSITION')
 length=parent['publication']['files']['books/positions.jsonl']['bytes']
 states={x['position_id']:x for x in c.parse_rows((ar.parent/'books/positions.jsonl').read_bytes()[:length])}
 pos=states.get(own);need(pos and pos['status']=='OPEN' and pos['timeframe']==tf,'CLOSE_REFUSAL_PARENT_POSITION_CONFLICT')
 target=IntrabarPaperEngine._s41_close_target_side(command);side=pos['side']
 if outcome['status']=='CLOSE_SIDE_MISMATCH':
  need(target and target!=side and outcome['position_side']==side and outcome['command_side']==target,'ORIGINAL_SIDE_MISMATCH_NOT_PROVEN')
 else:
  need(not target or target==side,'ORIGINAL_CLOSE_PRIORITY_CONFLICT')
  entered=_as_utc_datetime(pos.get('entry_decision_ts'));stamp=_as_utc_datetime(command.get('evaluation_timestamp')) or _as_utc_datetime(command.get('created_at'))
  need(entered and stamp and stamp<entered and outcome['entry_decision_ts']==pos['entry_decision_ts'] and outcome['command_ts']==(command.get('evaluation_timestamp') or command.get('created_at')),'ORIGINAL_STALE_CLOSE_NOT_PROVEN')
