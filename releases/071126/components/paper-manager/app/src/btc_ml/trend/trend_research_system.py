"""Integrated bounded research descriptor/ledger/bridge. Never production authority."""
from copy import deepcopy
import hashlib
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal,getcontext,localcontext
from datetime import datetime,timezone,timedelta
import json
from .trend_journal import Journal,digest,Blocked,_fork_ingest,_FrozenDict
from .real_scope_proof import PAPER_CLASS,PAPER_SEED,paper_permission,verify_paper_source,verify_paper_context_baseline,paper_segment
from .trend_scope_sessions import suspended, REASON as SCOPE_REASON, verify as verify_scopes
from .trend_handoff import can_process,queued_permission,can_bookkeep,context,permissions,bridge_bind,validate_bridge,admit,VERSION as HANDOFF_VERSION
from .trend_evidence import E,DUR,RawOccurrence,FixtureAuthority,ObservedSeed,BridgeRequestV1,obs_dict,obs_restore,r2_restore,json_state,State,evaluate,QualifiedMarketEvidence
VERSION='DRA_INTEGRATED_ISOLATED_RESEARCH_V1'
def implementation_hashes():
 here=Path(__file__).resolve().parent
 names=['trend_journal.py', 'real_scope_proof.py', 'trend_evidence.py', 'trend_research_system.py', 'trend_scope_sessions.py', 'trend_handoff.py', 'trend_event.py', 'trend_r2_contract.py', 'trend_r2_machine.py', 'trend_r2_ledger.py', 'trend_fixture_context_authority.py', 'trend_october_consumer.py']
 return {str(here/name):hashlib.sha256((here/name).read_bytes()).hexdigest() for name in names}
def stamp(t):return t.astimezone(timezone.utc).isoformat()
def init_state(c):
 return {'config':c,'raw':{},'raw_order':[],'source_cursor':c['predecessor'],'owner_generation':0,'economic':{},'tf':{tf:{'initial_fixture_failed':False,'role':'SEEK_A','prefix':[],'windows':{},'looks':[],'fragments':[],'touches':[],'candidate':{},'owner':None,'research_ref':None,'tombstones':[],'generation':0,'seal':None,'blocked':[],'audit':[]} for tf in c['timeframes']},'r2':json_state(State()),'signal_queue':{},'intents':{},'projection_results':{},'admitted_segment_map':{},'receipts':[]}
class ResearchSystem:
 max_raw_events=4096 # default for existing bounded/offline callers
 def __init__(self,path,config=None,authority=None,live_source=None):
  self.live_source=live_source
  current=implementation_hashes()
  if config is not None:config=deepcopy(config);config.setdefault('implementation_sha',current)
  self.j=Journal(path);self.authority=authority
  with self.j.lock():
   if self.j.state is None:
    if config is None:raise Blocked('NO_RESEARCH_CONFIG')
    if config['mode'] not in ('FIXTURE_ONLY','REAL_CANDIDATE'):raise Blocked('MODE')
    self.j.append('C_E',{'kind':'INIT'},init_state(config),{'status':'INITIALIZED_NO_MARKET_AUTHORITY'})
   elif config is not None and self.j.state['config']!=config:raise Blocked('PINNED_CONFIG_CONFLICT')
   if self.j.state['config'].get('implementation_sha')!=current:raise Blocked('IMPLEMENTATION_VERSION_MISMATCH')
   verify_scopes(self)
 @property
 def state(self):return deepcopy(self.j.load())
 def admit_scope(self,request,cutoff,*,fault=None):return admit(self,request,cutoff,fault=fault)
 def _window_trade(self,s,key):
  node=s['raw'][key]['trade']
  if not hasattr(self,'_trade_inputs'):self._trade_inputs={}
  saved=self._trade_inputs.get(key)
  if saved is not None and (saved[0] is node or saved[0]==node):trade=saved[1]
  else:trade=E.Trade(**node)
  from .trend_journal import _FrozenDict
  self._trade_inputs[key]=(node if isinstance(node,_FrozenDict) else dict(node),trade)
  return trade
 def _window(self,s,tf,ids,cutoff):
  c=s['config']
  if getattr(self,'_baseline_input',None) is not c['baseline']:
   self._baseline_input=c['baseline'];self._baseline_trades=tuple(E.Trade(**x) for x in c['baseline']);self._baseline_sha=digest(c['baseline'])
  sequence=s['source_cursor']
  if getattr(self,'_window_sequence',None)!=sequence:self._window_sequence=sequence;self._window_inputs={}
  key=tuple(ids)
  if key not in self._window_inputs:
   raw=tuple(self._window_trade(s,k) for k in ids)
   self._window_inputs[key]=(raw,tuple(sorted({x.payload_sha for x in raw+self._baseline_trades})))
  raw,parents=self._window_inputs[key];base=self._baseline_trades;d=DUR[tf];first=E.utc(raw[0].trade_time);opened=datetime.fromtimestamp(int(first.timestamp())//d*d,timezone.utc)
  own=context(s,tf,ids)
  o=E.Observation(tf,own['id'],own['direction'],'PAPER_OBSERVED' if c.get('paper_permission') else c['mode'],stamp(opened),stamp(opened+timedelta(seconds=d)),cutoff,tuple(raw),base,c['baseline_available_at'],own['available_at'],parents,'fixture:ANCHORED_FIRST_ELIGIBLE_PREFIX_V1' if c['mode']=='FIXTURE_ONLY' else 'ANCHORED_FIRST_ELIGIBLE_PREFIX_V1',c['policy_available_at'])
  from .trend_fixture_context_authority import proof_for_window
  from dataclasses import replace
  proof=proof_for_window(s,tf,own,ids)
  if proof is not None:o=replace(o,synthetic_context_proof=proof)
  err=o.validate(cutoff)
  if err:raise Blocked(err)
  return o
 def _reference(self,s,t):
  key=t['owner'] or t['research_ref']
  if not key:return None
  r=s['economic'].get(key)
  if not r:raise Blocked('OWNER_HISTORY_MISSING')
  return r
 def _calendar_quantity(self,s,opened,at,raw,pending):
  c=getcontext();signature=(c.prec,c.rounding,c.Emin,c.Emax,c.clamp,tuple(sorted((k.__name__,v) for k,v in c.traps.items())))
  previous=getattr(self,'_calendar_cache',None)
  known=(previous is not None and previous['state'] is self.j.state and previous['context']==signature
         and previous['bounded'] and at>=previous['last_T'] and opened in previous['quantities'])
  with localcontext(c) as calculation:
   calculation.clear_flags()
   flags=previous['quantities'][opened][1] if known else ()
   try:
    if known:quantity=previous['quantities'][opened][0]+E.dec(raw.trade.quantity)
    else:quantity=sum(E.dec(z['trade']['quantity']) for z in s['raw'].values() if opened<=E.utc(z['trade']['trade_time'])<=at)
   finally:
    flags=tuple(set(flags)|{flag for flag,value in calculation.flags.items() if value})
    for flag in flags:c.flags[flag]=True
  pending[opened]=(quantity,flags);pending['context']=signature
  return quantity

 def _condition_anchor(self,node):
  # Only sealed native committed nodes are reused; mutable/offline input keeps
  # the original restore path. Cache is process-local and bounded, not state.
  if not isinstance(node,_FrozenDict):return obs_restore(node)
  cache=getattr(self,'_condition_anchor_inputs',None)
  if cache is None:cache={};self._condition_anchor_inputs=cache
  saved=cache.get(id(node))
  if saved is not None and saved[0] is node:return saved[1]
  restored=obs_restore(node)
  if len(cache)>=8:cache.pop(next(iter(cache)))
  cache[id(node)]=(node,restored)
  return restored
 def _conditions(self,o,ref,cand,measurements=None):
  x=o.measurements if measurements is None else measurements;d=1 if o.context_direction=='LONG' else -1;p=x['participation']>Decimal('1');align=d*x['delta']>0;counter=d*x['delta']<0;body=d*(x['close']-x['open'])
  def anchor(k):return self._condition_anchor(k)
  def edge(a):z=a.measurements;return z['high'] if d==1 else z['low']
  def loss(a):z=a.measurements;return d*(x['close']-(z['low'] if d==1 else z['high']))<0
  def outside(a):return d*(x['close']-edge(a))>0
  if ref and p and counter and loss(anchor(ref['windows'][0])):return 'OWNER_LOSS'
  if cand and p and counter and (loss(anchor(cand['A'])) or (cand.get('B') and d*(x['close']-edge(anchor(cand['A'])))<0 and body<0)):return 'CANDIDATE_FAILURE'
  if cand.get('R'):
   if p and align and body>0 and outside(anchor(cand['A'])):return 'ACCEPT'
  elif cand.get('B'):
   if p and any(d*(E.dec(q.price)-edge(anchor(cand['A'])))<=0 for q in o.trades):return 'R'
  elif cand.get('A'):
   if p and align and outside(anchor(cand['A'])) and body/(x['high']-x['low']+E.EPS)>Decimal('0.6'):return 'B'
  else:
   wick=min(x['open'],x['close'])-x['low'] if d==1 else x['high']-max(x['open'],x['close'])
   if p and counter and body>=0 and wick>0:
    if ref:
     a=anchor(ref['windows'][0]).measurements
     if not (x['low']>a['high'] if d==1 else x['high']<a['low']):return 'OVERLAP_CONTINUE'
    return 'A'
   if ref and p and align and body>0 and outside(anchor(ref['windows'][0])):return 'CONTINUE'
  return None
 def _intent(self,s,tf,event,o,segid=None):
  t=r2_restore(s['r2']).timeframes[tf];seg=s['economic'].get(segid) if segid else None
  paper=bool(s['config'].get('paper_permission'))
  if paper:
   paper_permission(s['config'],o.available_at)
   if seg:paper_segment(s,seg)
  if seg and seg['authority_class'] not in ('QUALIFIED_FIXTURE_ONLY',PAPER_CLASS):return None
  if s['config']['mode']!='FIXTURE_ONLY' and not s['config'].get('paper_permission'):
   if s['config']['mode']=='REAL_CANDIDATE':
    from .real_scope_proof import require_real_scope_proof
    require_real_scope_proof(self,s['config'].get('real_scope_proof'),o.available_at)
   return None
  parent=seg['parent_id'] if seg else None;path=[];skips=[];anchor=s['admitted_segment_map'].get(t.last_opportunity_evidence_key)
  node=segid
  while node:
   if node in path:raise Blocked('ECONOMIC_ANCESTRY_CYCLE')
   r=s['economic'].get(node)
   if not r:raise Blocked('OWNER_HISTORY_MISSING')
   if r['authority_class'] not in ('QUALIFIED_FIXTURE_ONLY',PAPER_CLASS,PAPER_SEED):raise Blocked('BRIDGE_ECONOMIC_AUTHORITY')
   path.append(node)
   if node==anchor:break
   for aid,result in s['projection_results'].items():
    i=s['intents'].get(aid)
    if i and i.get('economic_segment_id')==node and result.get('status')=='REJECTED':skips.append(aid)
   node=r['parent_id']
  if event=='NEW_INITIATIVE' and (not anchor or path[-1]!=anchor):raise Blocked('BRIDGE_ECONOMIC_ANCESTRY')
  path=tuple(reversed(path));ids=tuple(seg['source_ids']) if seg else o.source_ids
  windows=[obs_restore(w) for w in seg['windows']] if seg else [o]
  parents=tuple(sorted({h for w in windows for h in w.parent_hashes}));boundary=seg['boundary_source_id'] if seg else ids[0]
  attempt=digest([VERSION,'bridge',tf,segid or o.key,event])
  e=QualifiedMarketEvidence(tf,o.context_id,o.context_direction,event,('PAPER_DRA_' if paper else 'FIXTURE_DRA_')+event,ids,('paper:own:' if paper else 'fixture:own:')+tf+':'+o.bar_open,o.bar_open,o.trades[-1].exchange_event_time,max(q.receive_time for q in o.trades),o.available_at,o.available_at,o.available_at,parents,('paper:dual-lineage:' if paper else 'fixture:dual-lineage:')+attempt,boundary,'QUALIFIED','ELIGIBLE_PAPER_OBSERVED' if paper else 'ELIGIBLE_FIXTURE_ONLY','PAPER_OBSERVED' if paper else 'FIXTURE_ONLY',event in ('CONFIRM','NEW_INITIATIVE'),t.last_opportunity_evidence_key if event=='NEW_INITIATIVE' else None,None,o.available_at,(('bridge_version','ECONOMIC_R2_LINEAGE_BRIDGE_RESEARCH_V1'),('economic_parent_id',parent or 'NONE'),('path_ref',digest(path)),('economic_id',segid or 'NONE')))
  request=BridgeRequestV1(segid or '',parent,s['economic'][parent]['confirmation_ref'] if parent else None,t.active_opportunity_id,t.last_opportunity_evidence_key,anchor,path,tuple(skips),o.key,digest(s['r2']),attempt,event,tf,e.to_dict()).to_dict()
  request=bridge_bind(s,tf,o,request)
  if attempt in s['intents']:
   if s['intents'][attempt]!=request:raise Blocked('BRIDGE_ATTEMPT_CONFLICT')
  else:s['intents'][attempt]=request
  return attempt
 def _enqueue(self,s,tf,event,o,segid=None):
  if s['config']['mode']!='FIXTURE_ONLY' and not s['config'].get('paper_permission'):
   if s['config']['mode']=='REAL_CANDIDATE':
    from .real_scope_proof import require_real_scope_proof
    require_real_scope_proof(self,s['config'].get('real_scope_proof'),o.available_at)
   return None
  attempt=digest([VERSION,'bridge',tf,segid or o.key,event])
  record={'attempt_id':attempt,'timeframe':tf,'event_type':event,'economic_segment_id':segid,'observation':obs_dict(o),'source_cutoff':o.available_at,'status':'QUEUED_NOT_PREPARED'}
  old=s['signal_queue'].get(attempt)
  if old is not None and old!=record:raise Blocked('QUEUED_INTENT_CONFLICT')
  s['signal_queue'][attempt]=record;return attempt
 def prepare(self,attempt):
  with self.j.lock():
   s=deepcopy(self.j.state)
   if attempt in s['intents']:return deepcopy(s['intents'][attempt])
   q=s['signal_queue'].get(attempt)
   if q is None:raise Blocked('MISSING_QUEUED_INTENT')
   if not can_process(s,q['timeframe']):raise Blocked(SCOPE_REASON)
   if not queued_permission(s,q):raise Blocked('QUEUED_SOURCE_SCOPE_PERMISSION_REQUIRED')
   actual=self._intent(s,q['timeframe'],q['event_type'],obs_restore(q['observation']),q['economic_segment_id'])
   if actual!=attempt:raise Blocked('INTENT_IDENTITY')
   self.j.append('C_E',{'kind':'PREPARE_BRIDGE','attempt':attempt},s,{'status':'PREPARED','expected_r2_state_hash':s['intents'][attempt]['expected_r2_state_hash']})
   return deepcopy(s['intents'][attempt])
 def _freeze(self,s,tf,o,outcome,fault):
  t=s['tf'][tf];ref=self._reference(s,t);cand=t['candidate'];wd=obs_dict(o);t['windows'][o.key]={'type':'MEASURED_EVENT_WINDOW','observation':wd,'outcome':outcome,'baseline_ref':digest(s['config']['baseline']),'source_ids':list(o.source_ids)};t['prefix']=[];self.j.stage('WINDOW_FREEZE',{'window':wd,'outcome':outcome},fault)
  if outcome=='A':cand['A']=wd;t['role']='SEEK_B'
  elif outcome=='B':cand['B']=wd;t['role']='SEEK_R'
  elif outcome=='R':cand['R']=wd;t['role']='SEEK_RESPONSE'
  elif outcome in ('OWNER_LOSS','CANDIDATE_FAILURE'):
   if outcome=='CANDIDATE_FAILURE' and ref is None and not t['tombstones']:
    inputs=list(o.source_ids)+list(obs_restore(cand['A']).source_ids)
    if cand.get('B'):inputs+=list(obs_restore(cand['B']).source_ids)
    if all(s['raw'][k]['fixture_authorized'] for k in inputs):
     t['initial_fixture_failed']=True
     self._enqueue(s,tf,'BREAK',o)
   if outcome=='OWNER_LOSS':
    tomb={'type':'OWNER_TOMBSTONE' if t['owner'] else 'RESEARCH_REFERENCE_TOMBSTONE','previous_id':ref['id'],'origin':ref['origin'],'failure_ref':o.key,'failure_sources':list(o.source_ids),'cutoff':o.available_at,'terminal_native_id':o.trades[-1].native_id,'generation':t['generation']+1};tomb['id']=digest(tomb);t['tombstones'].append(tomb);t['owner']=None;t['research_ref']=None;t['generation']+=1;s['owner_generation']+=1
    if ref['authority_class'] in ('QUALIFIED_FIXTURE_ONLY',PAPER_CLASS):self._enqueue(s,tf,'BREAK',o)
   t['candidate']={};t['role']='SEEK_A'
  elif outcome=='ACCEPT':
   windows=[cand['A'],cand['B'],cand['R'],wd];source_ids=[q['market']+':'+q['symbol']+':'+q['stream']+':'+str(q['native_id']) for w in windows for q in w['trades']]
   if len(set(source_ids))!=len(source_ids):raise Blocked('ROLE_SOURCE_REUSE')
   paper=bool(s['config'].get('paper_permission'))
   paper_ok=paper and all(s['raw'][k].get('paper_authorized') for k in source_ids) and not t['blocked'] and not t['tombstones'] and (not ref or ref['authority_class'] in (PAPER_SEED,PAPER_CLASS))
   fixture=not paper and all(s['raw'][k]['fixture_authorized'] for k in source_ids) and not t['tombstones'] and not t.get('initial_fixture_failed',False) and (not ref or ref['authority_class']=='QUALIFIED_FIXTURE_ONLY')
   cls=(PAPER_CLASS if ref else PAPER_SEED) if paper_ok else 'QUALIFIED_FIXTURE_ONLY' if fixture else ('OBSERVED_SEED' if ref is None else 'RESEARCH_COMPARISON')
   post=bool(t['tombstones']);kind='FIXTURE_SEGMENT' if fixture else ('POST_FAILURE_CHAIN_OBSERVED' if post and ref is None else 'OBSERVED_SEED' if ref is None else 'SEED_RELATIVE_INDEPENDENT_CHAIN_OBSERVED')
   parent=ref['id'] if ref else None;ident=digest([VERSION,tf,kind,[obs_restore(w).key for w in windows],parent,t['generation']]);a=obs_restore(windows[0]).measurements
   r={'type':'CONFIRMED_INITIATIVE_EVIDENCE','kind':kind,'authority_class':cls,'id':ident,'parent_id':parent,'confirmation_ref':o.key,'origin':{'low':str(a['low']),'high':str(a['high'])},'windows':windows,'source_ids':source_ids,'boundary_source_id':o.source_ids[0],'tf':tf,'context':o.context_id,'direction':o.context_direction,'cutoff':o.available_at,'generation':t['generation']+1,'prefix_registry_refs':[digest(x) for x in t['looks']],'source_interval':list(s['raw_order']),'terminal_parent_ref':t['tombstones'][-1]['id'] if post else None,'REAL_QUALIFIER':'NOT_QUALIFIED / NO_ENTRY','qualification_grant':'OWNER_APPROVED_PAPER_OBSERVED_SEED_RELATIVE_V1' if paper_ok else 'FIXTURE_DECLARATION' if fixture else 'DESIGN_REQUIRED'}
   if cls in ('OBSERVED_SEED',PAPER_SEED):r['seed']=asdict(ObservedSeed(ident,{'tf':tf,'context':o.context_id,'market':o.trades[0].market},t['generation']+1,r['origin'],tuple(obs_restore(w).key for w in windows),tuple(s['raw_order']),o.available_at,digest(s['config']['baseline']),prior_market_owner='RELEASED_KNOWN' if post else 'UNKNOWN'))
   s['economic'][ident]=r;t['generation']+=1;s['owner_generation']+=1
   if fixture or cls==PAPER_CLASS:
    t['owner']=ident
    self._enqueue(s,tf,'NEW_INITIATIVE' if ref and ref['authority_class']!=PAPER_SEED else 'CONFIRM',o,ident)
   else:t['research_ref']=ident
   t['candidate']={};t['role']='SEEK_A';self.j.stage('OWNER_COMMIT',r,fault)
  if outcome=='B' and not s['config'].get('paper_permission') and not ref and all(s['raw'][k]['fixture_authorized'] for k in list(o.source_ids)+list(obs_restore(cand['A']).source_ids)) and not t['tombstones'] and not t.get('initial_fixture_failed',False):self._enqueue(s,tf,'FORMING',o)
  if outcome=='B' and s['config'].get('paper_permission') and ref and ref['authority_class']==PAPER_SEED and not t['blocked'] and not t['tombstones']:
   self._enqueue(s,tf,'FORMING',o)
  if outcome=='CONTINUE' and ref and ref['authority_class'] in ('QUALIFIED_FIXTURE_ONLY',PAPER_CLASS):self._enqueue(s,tf,'CONTINUE',o)
 def ingest_canary(self,capture_id,cutoff,*,delivery_ids=None):
  """Existing recorder -> original C_E raw ingestion; never an authority grant."""
  from .real_scope_proof import read_retained_canary,trust_from_config
  config=self.state['config']
  if config['mode']!='REAL_CANDIDATE':raise Blocked('REAL_CANARY_MODE_REQUIRED')
  if config.get('paper_permission'):paper_permission(config,cutoff)
  if config.get('market')!='BINANCE_SPOT':raise Blocked('SOURCE_DOMAIN')
  capture=read_retained_canary(trust_from_config(config),capture_id=capture_id,cutoff=cutoff)
  deliveries=capture['deliveries']
  if delivery_ids is not None:
   requested=list(delivery_ids)
   if not requested:raise Blocked('REAL_CANARY_EMPTY_REQUEST')
   if len(requested)!=len(set(requested)):raise Blocked('REAL_CANARY_DUPLICATE_REQUEST')
   known={d['delivery_id']:d for d in deliveries}
   if any(k not in known for k in requested):raise Blocked('REAL_CANARY_UNKNOWN_DELIVERY')
   selected=[d for d in deliveries if d['delivery_id'] in requested]
   # A partial selection is raw observation only, never complete coverage.
  else:selected=deliveries
  if any(d['packet']['capture_family']!=config['capture_family'] or d['packet']['coverage_ref']!=config['coverage_ref'] for d in selected):
   # Native coverage receipts are per-delivery, so the configured scope names
   # the capture root. Each exact per-delivery reference is preserved in raw.
   if config['coverage_ref']!=capture['root'] or any(d['packet']['capture_family']!=config['capture_family'] for d in selected):raise Blocked('CAPTURE_PROVENANCE_CONFLICT')
  binding={k:capture[k] for k in ('capture_id','root','pins_sha256','manifest_count','manifest_tip_sha256','entry','coverage','economic_authority')}
  binding['deliveries']=[{**{k:v for k,v in d.items() if k!='packet'},'source_key':RawOccurrence.from_dict(d['packet']).trade.source_key,'core_sha256':d['packet']['trade']['payload_sha'],'coverage_ref':d['packet']['coverage_ref']} for d in selected]
  link=digest(binding)
  with self.j.lock():
   if not any(r['action'].get('kind')=='RETAINED_CANARY_SOURCE' and r['action'].get('source_link')==link for r in self.j.records):
    self.j.append('C_E',{'kind':'RETAINED_CANARY_SOURCE','source_link':link,'evidence':binding},deepcopy(self.j.state),{'status':'VERIFIED_RETAINED_SOURCE_ONLY','entry':'NO_ENTRY'})
  results=[]
  for delivery in selected:
   results.append(self.ingest(delivery['packet'],cutoff))
  return {'status':'CAPTURED_SOURCE_ONLY','entry':'NO_ENTRY','source_link':link,'ingestion':results,'qualification':'REAL_SOURCE_COVERAGE_UNQUALIFIED','economic_authority':'NOT_ESTABLISHED','r2_results':self.drain()}
 def begin_live_handoff(self,ready_clock,clock_domain):
  """Record actual readiness AFTER native INIT, without rewriting its inputs.

  The frozen baseline predecessor remains its original cursor. Subsequent
  pre-activation RAW advance source_cursor, not the initiative TF prefix.
  """
  with self.j.lock():
   s=_fork_ingest(self.j.state);c=s['config']
   if c.get('source_transport')!='RECORDER_LIVE' or self.live_source is None:raise Blocked('LIVE_HANDOFF_SOURCE_REQUIRED')
   if s.get('live_handoff') is not None:raise Blocked('LIVE_HANDOFF_ALREADY_FIXED')
   if s['raw_order'] or len(self.j.records)!=1 or self.j.records[0]['action']['kind']!='INIT':raise Blocked('LIVE_HANDOFF_REQUIRES_COMMITTED_INIT')
   ready=E.utc(ready_clock['wall_utc'])
   if type(ready_clock['monotonic_ns']) is not int or ready_clock['monotonic_ns']<0:raise Blocked('LIVE_HANDOFF_RECEIVE_CLOCK')
   if any(E.utc(at)>ready for at in [c['baseline_available_at'],c['policy_available_at']]+[v['available_at'] for v in c['contexts'].values()]):raise Blocked('LIVE_HANDOFF_INPUT_NOT_READY')
   s['live_handoff']={'ready_clock':dict(ready_clock),'clock_domain':clock_domain,
      'init_sha':self.j.records[0]['sha'],'baseline_predecessor':c['predecessor'],
      'preactivation_count':0,'first_pre_activation':None,'last_pre_activation':None,'first_eligible':None}
   return self.j.append('C_E',{'kind':'LIVE_INIT_HANDOFF_READY'},s,{'status':'READY_FOR_POST_INIT_RECEIVE'})
 def resume_live_handoff(self,ready_clock,clock_domain):
  # Record actual readiness for this restarted receive domain only while the
  # initial handoff has no first eligible. Original INIT/baseline are immutable.
  with self.j.lock():
   s=_fork_ingest(self.j.state);h=s.get('live_handoff')
   if h is None or h['first_eligible'] is not None:return
   h=dict(h);h['resume_domains']=list(h.get('resume_domains',[]))+[{'clock_domain':clock_domain,'ready_clock':ready_clock}];s['live_handoff']=h
   return self.j.append('C_E',{'kind':'LIVE_HANDOFF_RESUME'},s,{'status':'RESUMED_RECEIVE_DOMAIN'})
 def _account_live_handoff(self,s,raw,gap):
  handoff=s.get('live_handoff')
  if handoff is None:return False  # Unchanged archive/offline and older journals.
  delivery=self.live_source.current if self.live_source is not None else None
  if not delivery or delivery['packet']!=raw.packet():raise Blocked('LIVE_HANDOFF_DELIVERY_REQUIRED')
  if handoff['first_eligible'] is not None:
   if gap:raise Blocked('SOURCE_CONTINUITY_UNKNOWN')
   return False
  received=delivery['message_received'];ready=handoff['ready_clock']
  if delivery['clock_domain']!=handoff['clock_domain']:
   matches=[d for d in handoff.get('resume_domains',[]) if d['clock_domain']==delivery['clock_domain']]
   if not matches:raise Blocked('LIVE_HANDOFF_RECEIVE_CLOCK')
   ready=matches[-1]['ready_clock']
  if received['wall_utc']!=raw.trade.receive_time:raise Blocked('LIVE_HANDOFF_RECEIVE_CLOCK')
  if gap:raise Blocked('SOURCE_CONTINUITY_UNKNOWN')
  # Both ORIGINAL local observations must be on the ready side. stamp()
  # samples wall and monotonic separately; neither is corrected or replaced.
  early=(received['monotonic_ns']<=ready['monotonic_ns']
         or E.utc(received['wall_utc'])<E.utc(ready['wall_utc']))
  if handoff['first_eligible'] is not None:
   if early:raise Blocked('PRE_ACTIVATION_AFTER_INITIATIVE')
   return False
  h=dict(handoff);s['live_handoff']=h
  evidence={'native_id':raw.trade.native_id,'receive_clock':dict(received),
            'receive_sequence':delivery.get('receive_sequence'),'source_predecessor':raw.predecessor}
  if early:
   h['preactivation_count']+=1
   if h['first_pre_activation'] is None:h['first_pre_activation']=evidence
   h['last_pre_activation']=evidence
   # Keep original receive metadata next to this retained RAW, not in baseline.
   s['raw'][raw.trade.source_key]={**s['raw'][raw.trade.source_key],'preactivation_receive':evidence}
   return True
  h['first_eligible']=evidence
  return False
 def ingest(self,p,cutoff,*,expected_generation=None,fault=None,ft4=None):
  raw=RawOccurrence.from_dict(p);raw.validate(cutoff)
  with self.j.lock():
   s=_fork_ingest(self.j.state);c=s['config'];k=raw.trade.source_key
   if expected_generation is not None and expected_generation!=s['owner_generation']:raise Blocked('OWNER_GENERATION_CAS')
   if raw.capture_family!=c['capture_family'] or raw.capture_origin!=c['mode']:raise Blocked('CAPTURE_PROVENANCE_CONFLICT')
   if (raw.trade.market,raw.trade.symbol,raw.trade.stream)!=(c['market'],'BTCUSDT','AGG_TRADE'):raise Blocked('SOURCE_DOMAIN')
   if k in s['raw']:
    if s['raw'][k]['trade']['payload_sha']!=raw.trade.payload_sha:
     if c.get('paper_permission'):
      for t in s['tf'].values():t['blocked'].append('PAPER_CONFLICTING_SOURCE')
     self.j.append('C_E',{'kind':'SOURCE_CONFLICT','conflicting_packet':p,'key':k},s,{'status':'REJECTED','reason':'CONFLICTING_NATIVE_IDENTITY'})
     raise Blocked('CONFLICTING_NATIVE_IDENTITY')
    s['receipts'].append({'duplicate':k,'receive':raw.trade.receive_time,'available_at':raw.available_at,'original_payload':raw.original_payload,'original_source_sha256':hashlib.sha256(raw.original_payload.encode()).hexdigest()});return self.j.append('C_E',{'kind':'DUPLICATE','key':k},s,{'status':'DUPLICATE_NO_EFFECT'},fault)
   if len(s['raw'])>=self.max_raw_events:raise Blocked('BOUNDED_FIXTURE_RESOURCE_CAP')
   coverage_bound=raw.coverage_ref==c['coverage_ref']
   if not coverage_bound and c['mode']=='REAL_CANDIDATE':
    coverage_bound=any(r['action'].get('kind')=='RETAINED_CANARY_SOURCE'
     and r['action']['evidence']['root']==c['coverage_ref']
     and any(d['source_key']==k and d['core_sha256']==raw.trade.payload_sha and d['coverage_ref']==raw.coverage_ref
             and d['available_by']==raw.available_at for d in r['action']['evidence']['deliveries']) for r in self.j.records)
   if self.live_source is not None and c.get('source_transport')=='RECORDER_LIVE':
    coverage_bound=self.live_source.owns_current(raw,c)
   auth=bool(self.authority and self.authority.permits(c,raw));paper_auth=False;paper_error=None
   if c.get('paper_permission'):
    try:
     verify_paper_source(c,raw,cutoff,records=self.j.records,fixture_authorized=auth,live_source=self.live_source)
     paper_auth=True
    except Blocked as exc:paper_error=str(exc)
   gap=raw.predecessor is None or s['source_cursor'] is None or raw.predecessor!=s['source_cursor'] or (c['sequence']=='CONTIGUOUS_PLUS_ONE' and raw.trade.native_id!=s['source_cursor']+1) or not coverage_bound
   if s['raw_order']:
    prev=s['raw'][s['raw_order'][-1]]['trade']
    gap=gap or E.utc(raw.trade.trade_time)<E.utc(prev['trade_time']) or E.utc(raw.trade.exchange_event_time)<E.utc(prev['exchange_event_time'])
   s['raw'][k]={**p,'type':'RAW_OCCURRENCE','fixture_authorized':auth,'paper_authorized':paper_auth,'payload_identity':digest(json.loads(raw.original_payload)),'original_source_sha256':hashlib.sha256(raw.original_payload.encode()).hexdigest()};s['raw_order'].append(k);s['source_cursor']=raw.trade.native_id
   if self.live_source is not None and c.get('source_transport')=='RECORDER_LIVE':
    d=self.live_source.current
    s['raw'][k]['source_delivery_ref']={n:d[n] for n in ('delivery_id','ack_sha256','manifest_seq','manifest_sha256')}
   self.j.stage('RAW_SOURCE_PERSISTED',s['raw'][k],fault)
   if self._account_live_handoff(s,raw,gap):
    return self.j.append('C_E',{'kind':'LIVE_PREACTIVATION_ACCOUNTED','key':k,'cutoff':cutoff},s,{'status':'PREACTIVATION_ACCOUNTED','key':k},fault)
   calendar_quantities={};window_measurements={};calendar_pending={}
   for tf,t in s['tf'].items():
    if not can_process(s,tf,[k]):continue  # Raw-only without purpose-specific checked H1.
    if gap:t['blocked'].append('SOURCE_CONTINUITY_UNKNOWN')
    proof=c.get('coverage_assertion',{})
    if c.get('paper_permission'):
     if paper_error:t['blocked'].append(paper_error)
     try:verify_paper_context_baseline(c,tf,cutoff,live_source=self.live_source)
     except Blocked as exc:
      t['blocked'].append(str(exc));continue
     if not c.get('baseline') or not c.get('contexts',{}).get(tf):
      t['blocked'].append('PAPER_CONTEXT_OR_BASELINE_UNAVAILABLE');continue
    elif c['mode']=='REAL_CANDIDATE':
     if self.live_source is None:t['blocked'].append('REAL_SOURCE_COVERAGE_UNQUALIFIED')
     if not c.get('baseline') or not c.get('contexts',{}).get(tf):
      t['blocked'].append('REAL_CONTEXT_OR_BASELINE_UNAVAILABLE');continue
    elif proof.get('kind')!='SYNTHETIC_COMPLETE_BY_CONSTRUCTION' or proof.get('capture_family')!=raw.capture_family or proof.get('memberships',{}).get(k)!=raw.trade.payload_sha:t['blocked'].append('SOURCE_COVERAGE_ASSERTION_UNBOUND')
    if c['sequence']!='CONTIGUOUS_PLUS_ONE':t['blocked'].append('LEGACY_SEQUENCE_INCOMPATIBLE')
    if t['seal'] and E.utc(raw.trade.trade_time)<E.utc(t['seal']):t['blocked'].append('LATE_AFTER_VERIFIED_WATERMARK')
    if t['prefix']:
     old=E.utc(s['raw'][t['prefix'][0]]['trade']['trade_time']);new=E.utc(raw.trade.trade_time)
     if int(old.timestamp())//DUR[tf]!=int(new.timestamp())//DUR[tf]:self._fragment(s,tf,cutoff,'BAR_SEAM_UNVERIFIED' if not t['seal'] else 'BAR_SEAM');t['prefix']=[]
    t['prefix'].append(k)
    cand=t['candidate']
    if cand.get('B') and not cand.get('R'):
     a=obs_restore(cand['A']).measurements;d=1 if context(s,tf,t['prefix'])['direction']=='LONG' else -1;edge=a['high'] if d==1 else a['low']
     if d*(E.dec(raw.trade.price)-edge)<=0 and not any(z['candidate_ref']==obs_restore(cand['A']).key for z in t['touches']):t['touches'].append({'candidate_ref':obs_restore(cand['A']).key,'source':k,'receive':raw.trade.receive_time,'cutoff':cutoff,'type':'TOUCH_RECEIPT_NOT_ACCEPTANCE'})
    if len(t['prefix'])<2 or s['raw'][t['prefix'][0]]['trade']['trade_time']==raw.trade.trade_time:
     t['looks'].append({'role':t['role'],'sources':list(t['prefix']),'cutoff':cutoff,'result':'UNMEASURED_ZERO_SPAN','P':None});continue
    try:o=self._window(s,tf,t['prefix'],cutoff)
    except Blocked as e:t['blocked'].append(str(e));t['looks'].append({'role':t['role'],'sources':list(t['prefix']),'cutoff':cutoff,'result':str(e)});continue
    measurement_key=(id(o.trades),id(o.baseline_trades))
    if measurement_key not in window_measurements:window_measurements[measurement_key]=o.measurements
    x=window_measurements[measurement_key];ref=self._reference(s,t);cand=t['candidate'];cond=self._conditions(o,ref,cand,measurements=x)
    if suspended(s,tf):
     granted=permissions(s,tf,t['prefix'])
     if cond=='OWNER_LOSS' and ('HISTORICAL_ORIGIN_MONITOR' not in granted or granted['HISTORICAL_ORIGIN_MONITOR'][1]['economic_reference_id']!=ref['id']):
      t['blocked'].append('ORIGIN_MONITOR_PERMISSION_REQUIRED')
     if not any(p in granted for p in ('CONTINUITY_COMPARE','UNFINISHED_CHAIN_CONTINUATION','POST_FAILURE_OBSERVATIONAL_SCAN')) and cond!='OWNER_LOSS':cond=None
    t['looks'].append({'role':t['role'],'sources':list(t['prefix']),'cutoff':cutoff,'P':str(x['participation']),'result':cond or 'INCOMPLETE_PREFIX','baseline_ref':self._baseline_sha})
    at=E.utc(raw.trade.trade_time);opened=datetime.fromtimestamp(int(at.timestamp())//DUR[tf]*DUR[tf],timezone.utc);span=Decimal(str((at-opened).total_seconds()));qty=calendar_quantities.get(opened)
    if qty is None:
     qty=self._calendar_quantity(s,opened,at,raw,calendar_pending);calendar_quantities[opened]=qty
    t['audit'].append({'open':stamp(opened),'cutoff':cutoff,'quantity':str(qty),'P_calendar':str(qty/(x['baseline_rate']*span)) if span>0 else None,'diagnostic_only':True})
    if t['blocked']:
     t['windows'][o.key]={'type':'MEASURED_EVENT_WINDOW','observation':obs_dict(o),'outcome':'BLOCKED_DEPENDENT_QUALIFICATION','source_ids':list(o.source_ids)};t['prefix']=[]
    elif cond:
     self._freeze(s,tf,o,cond,fault)
     if suspended(s,tf):self.j.stage('CROSS_SCOPE_ECONOMIC_ADVANCED',s['tf'][tf],fault)
   self.j.stage('PROJECTION_INTENT',s['signal_queue'],fault)
   previous_state=self.j.state
   result=self.j.append('C_E',{'kind':'INGEST','key':k,'cutoff':cutoff},s,{'status':'CAPTURED','key':k,'REAL_QUALIFIER':'NOT_QUALIFIED / NO_ENTRY'},fault)
   if calendar_quantities:
    at=E.utc(raw.trade.trade_time);old=getattr(self,'_calendar_cache',None)
    bounded=(old is not None and old['state'] is previous_state and old['bounded'] and at>=old['last_T'])
    if not bounded:bounded=all(E.utc(z['trade']['trade_time'])<=at for z in s['raw'].values())
    self._calendar_cache={'state':self.j.state,'last_T':at,'bounded':bounded,'context':calendar_pending.pop('context'),'quantities':calendar_pending}
   return result
 def _fragment(self,s,tf,cutoff,reason):
  t=s['tf'][tf]
  if not t['prefix']:return
  ids=list(t['prefix']);zero=len(ids)<2 or s['raw'][ids[0]]['trade']['trade_time']==s['raw'][ids[-1]]['trade']['trade_time']
  kind='UNMEASURED_FRAGMENT' if zero else 'MEASURED_NON_SUCCESS_FRAGMENT'
  participation=None;measurement_reason=None
  if not zero:
   try:participation=str(self._window(s,tf,ids,cutoff).measurements['participation'])
   except Blocked as exc:
    # Retain raw membership without fabricating a measurement or authorizing economics.
    kind='MEASUREMENT_BLOCKED_FRAGMENT';measurement_reason=str(exc)
    t['blocked'].append(measurement_reason)
  fragment={'type':kind,'source_ids':ids,'role':t['role'],'cutoff':cutoff,'participation':participation,'reason':reason,'bar_open':int(E.utc(s['raw'][ids[0]]['trade']['trade_time']).timestamp())//DUR[tf]*DUR[tf]}
  if measurement_reason is not None:fragment['measurement_reason']=measurement_reason
  fragment['id']=digest(fragment);t['fragments'].append(fragment)
  if zero:t['blocked'].append('UNMEASURED_REQUIRED_ECONOMIC_EVIDENCE')
  if reason=='BAR_SEAM_UNVERIFIED':t['blocked'].append('COVERAGE_WATERMARK_UNVERIFIED')
 def observed_partial_close(self,tf,close,cutoff):
  # A real close can end the observed prefix without claiming full capture
  # coverage. Keep its native fragment and every contributor; do NOT set seal.
  with self.j.lock():
   s=_fork_ingest(self.j.state);t=s['tf'][tf]
   if not can_process(s,tf):raise Blocked(SCOPE_REASON)
   if E.utc(close)>E.utc(cutoff) or int(E.utc(close).timestamp())%DUR[tf]:raise Blocked('INVALID_WATERMARK')
   if t['prefix'] and E.utc(s['raw'][t['prefix'][-1]]['trade']['trade_time'])>=E.utc(close):raise Blocked('WATERMARK_MEMBERSHIP')
   self._fragment(s,tf,cutoff,'OBSERVED_INITIAL_PARTIAL_CAPTURE_CLOSE');t['prefix']=[]
   return self.j.append('C_E',{'kind':'OBSERVED_PARTIAL_CLOSE','tf':tf,'close':close},s,{'status':'OBSERVED_ONLY_NOT_VERIFIED_COVERAGE'})
 def watermark(self,tf,close,cutoff,coverage_ref):
  with self.j.lock():
   s=_fork_ingest(self.j.state);t=s['tf'][tf]
   if not can_process(s,tf):raise Blocked(SCOPE_REASON)
   if coverage_ref!=s['config']['coverage_ref'] or E.utc(close)>E.utc(cutoff) or int(E.utc(close).timestamp())%DUR[tf]:raise Blocked('INVALID_WATERMARK')
   if t['seal'] and E.utc(close)<E.utc(t['seal']):raise Blocked('WATERMARK_REORDER')
   if t['prefix'] and E.utc(s['raw'][t['prefix'][-1]]['trade']['trade_time'])>=E.utc(close):raise Blocked('WATERMARK_MEMBERSHIP')
   self._fragment(s,tf,cutoff,'VERIFIED_CLOSE');t['prefix']=[];t['seal']=close
   return self.j.append('C_E',{'kind':'WATERMARK','tf':tf,'close':close},s,{'status':'SEALED'})
 def validate_bridge_request(self,request):
  req=request.to_dict() if isinstance(request,BridgeRequestV1) else deepcopy(request)
  s=self.state
  if not can_process(s,req['timeframe']):raise Blocked(SCOPE_REASON)
  validate_bridge(s,req)
  seg=s['economic'].get(req['economic_segment_id'])
  if not seg or seg['authority_class'] not in ('QUALIFIED_FIXTURE_ONLY',PAPER_CLASS):raise Blocked('BRIDGE_ECONOMIC_AUTHORITY')
  if seg['authority_class']==PAPER_CLASS:paper_segment(s,seg)
  parent=s['economic'].get(seg['parent_id']) if seg['parent_id'] else None
  if req['economic_parent_id']!=seg['parent_id'] or req['economic_parent_confirmation_ref']!=(parent['confirmation_ref'] if parent else None):raise Blocked('BRIDGE_PARENT_CONFIRMATION')
  e=QualifiedMarketEvidence.from_dict(req['r2_payload'])
  if list(e.source_event_ids)!=seg['source_ids'] or e.independent_boundary_id!=seg['boundary_source_id']:raise Blocked('BRIDGE_SOURCE_INTEGRITY')
  if req!=s['intents'].get(req['bridge_attempt_id']):raise Blocked('BRIDGE_ATTEMPT_CONTENT_CONFLICT')
  return True
 def project(self,attempt,*,fault=None):
  with self.j.lock():
   s=deepcopy(self.j.state)
   if attempt in s['projection_results']:return deepcopy(s['projection_results'][attempt])
   req=s['intents'].get(attempt)
   if not req:raise Blocked('MISSING_PROJECTION_INTENT')
   if not can_process(s,req['timeframe']):result={'status':'REJECTED','reason':SCOPE_REASON,'opportunity_id':None,'entry_eligible':False}
   elif req['expected_r2_state_hash']!=digest(s['r2']):result={'status':'REJECTED','reason':'CONFLICT_R2_PRE_STATE','opportunity_id':None,'entry_eligible':False}
   else:
    try:
     validate_bridge(s,req)
     seg=s['economic'].get(req['economic_segment_id'])
     if seg:
      if seg['parent_id']!=req['economic_parent_id'] or seg['confirmation_ref']!=req['source_evidence_ref']:raise Blocked('BRIDGE_ECONOMIC_PARENT')
      parent=s['economic'].get(seg['parent_id']) if seg['parent_id'] else None
      if req['economic_parent_confirmation_ref']!=(parent['confirmation_ref'] if parent else None):raise Blocked('BRIDGE_PARENT_CONFIRMATION')
      if seg['tf']!=req['timeframe'] or (s['config']['mode']!='FIXTURE_ONLY' and not s['config'].get('paper_permission')):raise Blocked('BRIDGE_SCOPE_OR_REAL_AUTHORITY')
      if s['tf'][req['timeframe']]['owner']!=seg['id']:raise Blocked('STALE_ECONOMIC_PROJECTION')
      e=QualifiedMarketEvidence.from_dict(req['r2_payload']);windows=[obs_restore(w) for w in seg['windows']]
      if list(e.source_event_ids)!=seg['source_ids'] or e.independent_boundary_id!=seg['boundary_source_id'] or set(e.immutable_source_ids)!={h for w in windows for h in w.parent_hashes}:raise Blocked('BRIDGE_SOURCE_INTEGRITY')
      if e.timeframe!=seg['tf'] or (not req.get('scope_admission_ref') and e.context_episode_id!=seg['context']) or e.direction!=seg['direction'] or e.parent_evidence_key!=(req['opportunity_parent_evidence_key'] if req['event_type']=='NEW_INITIATIVE' else None):raise Blocked('BRIDGE_PAYLOAD_SCOPE_PARENT')
      if seg['authority_class']==PAPER_CLASS:paper_segment(s,seg)
      elif any(not s['raw'][k]['fixture_authorized'] for k in seg['source_ids']):raise Blocked('BRIDGE_FIXTURE_AUTHORITY')
      current=r2_restore(s['r2']).timeframes[req['timeframe']]
      if req['opportunity_parent_id']!=current.active_opportunity_id:raise Blocked('BRIDGE_OPPORTUNITY_PARENT')
      path=req['economic_path_ref']
      for i,key in enumerate(path):
       r=s['economic'].get(key)
       if not r or r['authority_class'] not in ('QUALIFIED_FIXTURE_ONLY',PAPER_CLASS,PAPER_SEED):raise Blocked('BRIDGE_ECONOMIC_ANCESTRY')
       if i and r['parent_id']!=path[i-1]:raise Blocked('BRIDGE_ECONOMIC_PATH')
      if req['event_type']=='NEW_INITIATIVE':
       tf=r2_restore(s['r2']).timeframes[req['timeframe']]
       if tf.last_opportunity_evidence_key!=req['opportunity_parent_evidence_key'] or s['admitted_segment_map'].get(tf.last_opportunity_evidence_key)!=path[0]:raise Blocked('BRIDGE_OPPORTUNITY_ANCESTRY')
       for ancestor in path[1:-1]:
        receipts=[s['projection_results'][a] for a in req['skipped_projection_receipts'] if a in s['projection_results'] and s['intents'][a]['economic_segment_id']==ancestor]
        if not receipts or not any(r['status']=='REJECTED' for r in receipts):raise Blocked('BRIDGE_SKIPPED_RECEIPT_MISSING')
     new,r=evaluate(r2_restore(s['r2']),{'kind':'market','evidence':req['r2_payload']});result=asdict(r);s['r2']=json_state(new)
     if result['opportunity_id']:s['admitted_segment_map'][QualifiedMarketEvidence.from_dict(req['r2_payload']).dedup_key]=req['economic_segment_id']
    except Blocked as exc:
     result={'status':'REJECTED','reason':str(exc),'opportunity_id':None,'entry_eligible':False,'decision_origin':'BRIDGE_VALIDATION','r2_evaluated':False}
   self.j.stage('R2_EVALUATED_BEFORE_C_P',{'attempt':attempt,'result':result},fault);s['projection_results'][attempt]=result
   return self.j.append('C_P',{'kind':'PROJECT','attempt':attempt},s,result,fault)
 def drain(self):
  results=[]
  state=self.state
  queue=sorted(state['signal_queue'],key=lambda k:(state['signal_queue'][k]['observation']['trades'][-1]['exchange_event_time'],state['signal_queue'][k]['source_cutoff'],state['signal_queue'][k]['timeframe'],k))
  for key in queue:
   if key not in self.state['projection_results']:
    if not can_process(self.state,state['signal_queue'][key]['timeframe']):
     results.append({'status':'NOT_QUALIFIED','reason':SCOPE_REASON,'attempt':key});continue
    if key not in self.state['intents'] and not queued_permission(self.state,state['signal_queue'][key]):
     results.append({'status':'NOT_QUALIFIED','reason':'QUEUED_SOURCE_SCOPE_PERMISSION_REQUIRED','attempt':key});continue
    self.prepare(key);results.append(self.project(key))
  return results
 def bookkeeping(self,req,*,fault=None):
  with self.j.lock():
   s=deepcopy(self.j.state)
   if req.get('timeframe') in s['tf'] and not can_process(s,req['timeframe']) and req.get('kind')!='outcome':
    result={'status':'REJECTED','reason':SCOPE_REASON,'opportunity_id':None,'entry_eligible':False}
   elif not can_bookkeep(s,req):
    result={'status':'REJECTED','reason':'CURRENT_SCOPE_OPPORTUNITY_REQUIRED','opportunity_id':None,'entry_eligible':False}
   else:
    new,r=evaluate(r2_restore(s['r2']),req);s['r2']=json_state(new);result=asdict(r)
   return self.j.append('C_P',{'kind':'R2_BOOKKEEPING','request':req},s,result,fault)
