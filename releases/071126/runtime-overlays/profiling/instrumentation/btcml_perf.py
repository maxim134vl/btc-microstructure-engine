"""Standard-library profiling; same original call once, no new runtime threads.
Bounded summaries, 20s flush, cProfile windows >=120s on existing threads.
"""
import time,os,sys,json,threading,functools,collections,cProfile,atexit,inspect,runpy
from pathlib import Path
ROOT=Path(os.environ.get('BTCML_PERF_OUTPUT','/profile/output'));ROOT.mkdir(parents=True,exist_ok=True)
MET={};SAMPLES={};TLS=threading.local();last_flush=0;queues=[];pending={};processes=[];active={};PATCHED=set();_jsonloads=json.loads

def add(k,ns):
 m=MET.setdefault(k,{'count':0,'sum_ns':0,'min_ns':ns,'max_ns':0});m['count']+=1;m['sum_ns']+=ns;m['min_ns']=min(m['min_ns'],ns);m['max_ns']=max(m['max_ns'],ns);SAMPLES.setdefault(k,collections.deque(maxlen=1024)).append(ns)
def finish_profile(force=False):
 p=getattr(TLS,'prof',None)
 if p and (force or time.perf_counter_ns()-TLS.prof_start>=120_000_000_000):
  p.disable();TLS.prof=None
  try:p.dump_stats(str(ROOT/('python-%s-%s-%s.prof'%(os.getpid(),threading.current_thread().name,time.time_ns()))))
  except Exception:pass

def flush(force=False):
 global last_flush
 n=time.perf_counter_ns()
 if not force and n-last_flush<20_000_000_000:return
 last_flush=n
 TLS.flushing=True
 try:
  phases={}
  for k,v in list(MET.items()):
   s=sorted(SAMPLES[k]);phases[k]={**v,'mean_ns':v['sum_ns']/max(1,v['count']),'bounded_samples':len(s),**{q:s[int((len(s)-1)*a)] for q,a in [('p50_ns',.5),('p95_ns',.95),('p99_ns',.99)]}}
  state=[]
  for p in processes:
   b=getattr(p,'fresh_live_boundary',None);state.append({'complete':getattr(b,'complete',False),'admitted':getattr(b,'admitted',False),'count':getattr(b,'count',None),'last_id':getattr(b,'last_id',None),'target':getattr(b,'target_id',None),'market':p.state.state.value,'agg_age_ms':p.state._age_ms(p.state.last_agg_trade_monotonic_ns),'bbo_local_age_ms':p.state._age_ms(p.state.last_book_ticker_monotonic_ns)})
  d={'wall_ns':time.time_ns(),'mono_ns':n,'pid':os.getpid(),'thread':threading.current_thread().name,'phases':phases,'queue':[{'size':q.qsize(),'maxsize':q.maxsize} for q in queues],'queue_highwater':HIGH[0],'active':dict(active),'state':state}
  with (ROOT/('business-%s.jsonl'%os.getpid())).open('a') as f:f.write(json.dumps(d)+'\n')
 except Exception:pass
 finally:TLS.flushing=False
 finish_profile()

def timed(fn,phase,tf=None):
 if getattr(fn,'_btcml_perf',False):return fn
 @functools.wraps(fn)
 def call(*a,**kw):
  if getattr(TLS,'flushing',False):return fn(*a,**kw)
  if os.environ.get('BTCML_PERF_ROLE')=='paper-manager' and phase=='COMMITTED_SNAPSHOT_VERIFY_CALL' and not getattr(TLS,'prof',None) and not getattr(TLS,'late_done',False):
   TLS.late_done=True;TLS.prof=cProfile.Profile();TLS.prof_start=time.perf_counter_ns();TLS.prof.enable()
  key=phase
  if phase=='STAGE_DIGEST_OR_FILE_HASH' and a:key='STAGE_DIGEST' if str(a[0]).endswith('verified_catchup.jsonl') else 'RESUME_FILE_HASH:'+Path(a[0]).name
  tfval=kw.get('timeframe') or kw.get('tf') or tf
  if tfval:key+=':'+str(tfval)
  n=time.perf_counter_ns();old=getattr(TLS,'scope',None);TLS.scope=key;ticket=(threading.get_ident(),key);active[str(ticket)]={'phase':key,'start_ns':n,'wall_ns':time.time_ns()}
  try:return fn(*a,**kw)
  finally:
   add(key,time.perf_counter_ns()-n);active.pop(str(ticket),None);TLS.scope=old;flush()
 call._btcml_perf=True
 return call

def wrap(obj,name,key):
 try:
  raw=inspect.getattr_static(obj,name)
  if isinstance(raw,classmethod):setattr(obj,name,classmethod(timed(raw.__func__,key)))
  elif isinstance(raw,staticmethod):setattr(obj,name,staticmethod(timed(raw.__func__,key)))
  elif callable(raw) and not inspect.isgeneratorfunction(raw):setattr(obj,name,timed(raw,key))
 except (AttributeError,TypeError):pass

PAPER={
 'execution_market_processor':{'normalize_futures_agg_trade':'AGGTRADE_NORMALIZE','normalize_futures_book_ticker':'BBO_NORMALIZE','ExecutionMarketProcessor':{'handle_market_ws_payload':'MARKET_DISPATCH_TOTAL','_dispatch_agg_trade':'AGGTRADE_DISPATCH','_process_book_ticker':'BBO_UPDATE','_sync_engine_outputs':'BOOK_WRITE','_recover_gap_then_process':'REST_LIVE_GAP_RECOVERY'}},
 'execution_market_backfill':{'default_fetch_agg_trades':'REST_FETCH','normalize_rest_agg_trade':'REST_PARSE'},
 'open_position_resume':{'sha':'STAGE_DIGEST_OR_FILE_HASH','committed_snapshot':'COMMITTED_SNAPSHOT_VERIFY','load':'MANIFEST_VERIFY','publish':'PROOF_WRITE','OpenPositionResume':{'try_activate':'ADMISSION_TOTAL','_verify_initial_snapshot':'COMMITTED_SNAPSHOT_VERIFY_CALL','_verify_stage':'STAGE_RANGE_VERIFY','_verify_committed_evolution':'COMMITTED_EVOLUTION_VERIFY','_append_verified':'STAGE_APPEND','_admission_evidence':'SESSION_RANGE_REVALIDATE','_catchup_verified':'CATCHUP_DISPATCH','_staged_event':'STAGE_LOOKUP','handle_market':'RESUME_MARKET_CALLBACK','handle_public':'PUBLIC_BBO_CALLBACK','_claim_admission_turn':'CONVERGENCE_MUTEX_WAIT'}},
 'engine':{'IntrabarPaperEngine':{'update_from_trade':'ENGINE_UPDATE_FROM_TRADE','_check_tp_sl_on_market':'TP_SL_CHECK','_enter_position':'OPEN_EXECUTION','_complete_exit':'CLOSE_EXECUTION','_enter_position_locked':'RISK_AND_OPEN','update_bbo_from_market':'BBO_UPDATE','apply_s41_manager_command':'COMMAND_VALIDATION_AND_EXECUTION','write_health':'HEALTH_PUBLICATION'}},
 'execution_market_wal':{'ExecutionMarketWAL':{'append':'WAL_APPEND','append_batch':'WAL_APPEND_BATCH','_save_state':'WAL_STATE_WRITE'}},
 'execution_market_checkpoint':{'ExecutionMarketCheckpoint':{'save':'CHECKPOINT_WRITE'}},
 'books':{'EpochBooks':{'read_all':'BOOK_READ','append':'BOOK_WRITE'}},
 'execution_commit':{'atomic_bytes':'ATOMIC_BYTES','prefix_digest':'BOOK_PREFIX_DIGEST','ExecutionCommit':{'run':'RECEIPT_COMMIT','materialize':'COMMIT_MATERIALIZE'}},
 's41_command_consumer':{'S41CommandConsumer':{'poll':'COMMAND_POLL','_open_block_reason':'COMMAND_VALIDATION','_save':'COMMAND_CURSOR_WRITE'}},
 'admission_diagnostics':{'ObservedLock':{'acquire':'OBSERVED_MUTEX_ACQUIRE'},'AdmissionDiagnostics':{'publish':'PROOF_BUILD_AND_WRITE','revalidation':'RANGE_REVALIDATE','snapshot_verified':'SNAPSHOT_COMPARE'}}}
GRAPH={'refresh_once':'TOTAL_GRAPH_REFRESH','load_parquet':'LOAD_PARQUET','build_normalized_trade_render_layer':'LOAD_BOOKS','write_json':'WRITE_JSON','build_paper_overlays':'BUILD_MARKERS','build_timeframe_chart_truth':'BUILD_TF_STATE','build_context_zones':'BUILD_CONTEXT_ZONES','load_lifecycle':'LOAD_LIFECYCLE'}
CONTROLLER={'run_manager_cycle':'TOTAL_MANAGER_CYCLE','resolve_timeframe_state':'RESOLVE_CLOSED_STATES','_scoped_lifecycle':'LOAD_OWN_LIFECYCLE','load_books':'LOAD_BOOKS','load_sources':'LOAD_SOURCES','apply_anti_saw':'ANTI_SAW','build_commands':'BUILD_COMMANDS','append_commands':'COMMAND_BUS_WRITE'}

def patch_module(m):
 name=getattr(m,'__name__','');file=str(getattr(m,'__file__',''))
 if 'intrabar_paper' in name:
  for k,items in PAPER.items():
   if name.endswith('.'+k):
    for attr,phase in items.items():
     if isinstance(phase,dict):
      obj=getattr(m,attr,None)
      if obj:
       for method,p in phase.items():wrap(obj,method,p)
     else:wrap(m,attr,phase)
  if name.endswith('execution_market_processor'):
   cls=getattr(m,'ExecutionMarketProcessor');raw=inspect.getattr_static(cls,'create')
   if not getattr(raw.__func__,'_perf_create',False):
    original=raw.__func__
    def create(cls,*a,**kw):p=original(cls,*a,**kw);processes.append(p);return p
    create._perf_create=True;setattr(cls,'create',classmethod(create))
 if 'timeframe' in name or 'run_timeframe' in file:
  for attr,phase in CONTROLLER.items():wrap(m,attr,phase)
 if 'visual' in name or 'visual' in file:
  for attr,phase in GRAPH.items():wrap(m,attr,phase)
  for attr in list(vars(m)):
   if attr.startswith('_load') or attr.startswith('build_timeframe'):wrap(m,attr,'GRAPH_'+attr)

HIGH=[0]
def install():
 import builtins,queue,hashlib
 import importlib
 if os.environ.get('BTCML_PERF_ROLE')=='paper-manager':
  for mod in PAPER:
   try:patch_module(importlib.import_module('btc_ml.trading.intrabar_paper.'+mod))
   except ModuleNotFoundError:pass
  import btc_ml.trading.intrabar_paper.execution_market_processor as pm
  import btc_ml.trading.intrabar_paper.execution_market_backfill as bf
  pm.default_fetch_agg_trades=bf.default_fetch_agg_trades
 # cProfile existing main and existing worker threads only; no added thread.
 p=cProfile.Profile();TLS.prof=p;TLS.prof_start=time.perf_counter_ns();p.enable()
 original_run=threading.Thread.run
 def run(self):
  p=cProfile.Profile();TLS.prof=p;TLS.prof_start=time.perf_counter_ns();p.enable()
  try:return original_run(self)
  finally:finish_profile(True);flush(True)
 threading.Thread.run=run
 orig=queue.Queue.__init__;put=queue.Queue.put;get=queue.Queue.get
 def init(q,*a,**kw):orig(q,*a,**kw);queues.append(q) if q.maxsize==1024 else None
 def qput(q,item,*a,**kw):
  n=time.perf_counter_ns();ret=put(q,item,*a,**kw)
  if q.maxsize==1024:
   add('MARKET_QUEUE_PUT',time.perf_counter_ns()-n);pending[id(item)]=time.perf_counter_ns();HIGH[0]=max(HIGH[0],q.qsize())
   if len(pending)>2048:pending.pop(next(iter(pending)))
  return ret
 def qget(q,*a,**kw):
  n=time.perf_counter_ns();r=get(q,*a,**kw)
  if q.maxsize==1024:
   add('MARKET_QUEUE_GET',time.perf_counter_ns()-n);t=pending.pop(id(r),None)
   if t:add('MARKET_QUEUE_WAIT',time.perf_counter_ns()-t)
  return r
 queue.Queue.__init__=init;queue.Queue.put=qput;queue.Queue.get=qget
 origfs=os.fsync
 def fs(fd):
  n=time.perf_counter_ns()
  try:return origfs(fd)
  finally:add('FSYNC:'+str(getattr(TLS,'scope','GLOBAL')),time.perf_counter_ns()-n)
 os.fsync=fs
 import websocket
 websocket.WebSocket.recv_data_frame=timed(websocket.WebSocket.recv_data_frame,'WS_FRAME_RECEIVE')
 json.loads=timed(_jsonloads,'JSON_DECODE');json.dumps=timed(json.dumps,'SERIALIZE_JSON');hashlib.file_digest=timed(hashlib.file_digest,'FILE_DIGEST')
 # Only profile the exact main script, preserving its original main() argv.
 oldrun=runpy.run_path
 def runpath(path,*a,**kw):
  if str(path).endswith('qualified_paper_launcher.py'):return oldrun(path,*a,**kw)
  return oldrun(path,*a,**kw)
 runpy.run_path=runpath
 atexit.register(lambda:(finish_profile(True),flush(True)))
