"""Research-only two-boundary manifests. Not production/LINUX durability qualification."""
import os,json,hashlib,fcntl,uuid
from datetime import datetime,timezone
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[3]
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
class Blocked(RuntimeError):pass
class CorruptJournal(Blocked):pass
class WriterBusy(Blocked):pass
def validate_transition(old,new,boundary,action=None):
 from .trend_scope_sessions import validate_scopes
 validate_scopes(old,new,boundary)
 from .trend_handoff import validate_admissions
 validate_admissions(old,new,boundary)
 from .trend_handoff import validate_r2_commit
 validate_r2_commit(old,new,boundary,action or {})
 if not old:return
 if new['config']!=old['config']:raise ValueError('PINNED_CONFIG_MUTATION')
 if boundary=='C_E' and new['r2']!=old['r2']:raise ValueError('C_E_MUTATED_R2')
 if boundary=='C_P' and any(new[k]!=old[k] for k in ('config','raw','raw_order','tf','economic','owner_generation','source_cursor','intents','signal_queue')):raise ValueError('C_P_MUTATED_ECONOMICS_OR_INTENTS')
 for group in ('raw','economic','signal_queue','intents','projection_results','admitted_segment_map'):
  for key,value in old[group].items():
   if new[group].get(key)!=value:raise ValueError('IMMUTABLE_'+group.upper()+'_PREFIX')
 for tf,prior in old['tf'].items():
  current=new['tf'][tf]
  for key,value in prior['windows'].items():
   if current['windows'].get(key)!=value:raise ValueError('IMMUTABLE_WINDOW_PREFIX')
  for group in ('looks','fragments','touches','tombstones'):
   if current[group][:len(prior[group])]!=prior[group]:raise ValueError('IMMUTABLE_'+group.upper()+'_PREFIX')
 if new['owner_generation']<old['owner_generation']:raise ValueError('OWNER_GENERATION_REWIND')
class Journal:
 def __init__(self,path):
  self.path=Path(path).resolve()
  if not self.path.is_relative_to(ROOT) or os.stat('/Volumes/MaksTiger').st_dev==os.stat('/').st_dev:raise Blocked('EXTERNAL_RESEARCH_ROOT_REQUIRED')
  self.device=os.stat('/Volumes/MaksTiger').st_dev
  self.path.mkdir(parents=True,exist_ok=True)
  for n in ('records','pending','stages'):(self.path/n).mkdir(exist_ok=True)
  self.state=None;self.records=[];self.load()
 def load(self):
  prev=None;state=None;records=[]
  for n,p in enumerate(sorted((self.path/'records').glob('*.json')),1):
   try:
    r=json.loads(p.read_text());body={k:v for k,v in r.items() if k!='sha'}
    if p.name!=f'{n:08d}.json' or r['sequence']!=n or r['previous']!=prev or r['sha']!=digest(body) or r['state_sha']!=digest(r['state']):raise ValueError('HASH_SEQUENCE')
    if r.get('version')!='DRA_RESEARCH_JOURNAL_V1':raise ValueError('JOURNAL_VERSION')
    if r['boundary'] not in ('C_E','C_P'):raise ValueError('BOUNDARY')
    validate_transition(state,r['state'],r['boundary'],r['action'])
    if state:
     if r['boundary']=='C_E' and r['state']['r2']!=state['r2']:raise ValueError('C_E_MUTATED_R2')
     if r['boundary']=='C_P' and any(r['state'][k]!=state[k] for k in ('config','raw','raw_order','tf','economic','owner_generation','source_cursor')):raise ValueError('C_P_MUTATED_ECONOMICS')
    if state:
     for key,v in state['economic'].items():
      if r['state']['economic'].get(key)!=v:raise ValueError('IMMUTABLE_ECONOMIC_PREFIX')
     for key,v in state['raw'].items():
      if r['state']['raw'].get(key)!=v:raise ValueError('IMMUTABLE_RAW_PREFIX')
    candidate=r['state']
    from .trend_scope_sessions import verify_chain
    verify_chain(candidate,records)
    from .trend_handoff import verify_admissions
    verify_admissions(candidate,records)
    if len(candidate['raw_order'])!=len(set(candidate['raw_order'])):raise ValueError('DUPLICATE_RAW_ACCOUNTING')
    for key,segment in candidate['economic'].items():
     if segment['parent_id'] and segment['parent_id'] not in candidate['economic']:raise ValueError('MISSING_OWNER_ANCESTOR')
     if any(k not in candidate['raw'] for k in segment['source_ids']):raise ValueError('MISSING_RAW_ANCESTOR')
    for tf,t in candidate['tf'].items():
     if any(k and k not in candidate['economic'] for k in (t['owner'],t['research_ref'])):raise ValueError('MISSING_OWNER_ANCESTOR')
    state=r['state'];prev=r['sha'];records.append(r)
   except Exception as e:raise CorruptJournal(f'{p.name}: {e}') from e
  self.state=state;self.records=records;self.interrupted=sorted(p.name for p in (self.path/'pending').glob('*'))
  return state
 class Lock:
  def __init__(self,j):self.j=j
  def __enter__(self):
   if os.stat(getattr(self.j,'device_path','/Volumes/MaksTiger')).st_dev!=self.j.device:raise Blocked('MOUNT_CHANGED')
   self.f=open(self.j.path/'.writer.lock','a+b')
   try:fcntl.flock(self.f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:self.f.close();raise WriterBusy('WRITER_BUSY')
   self.j.load();return self.j
  def __exit__(self,*a):fcntl.flock(self.f.fileno(),fcntl.LOCK_UN);self.f.close()
 def lock(self):return self.Lock(self)
 def stage(self,name,payload,fault):
  if fault!=name:return
  p=self.path/'stages'/f'{uuid.uuid4().hex}.{name}.json'
  with open(p,'xb') as f:f.write(canonical(payload).encode());f.flush();os.fsync(f.fileno())
  self.fsyncdir(p.parent);os._exit(91)
 @staticmethod
 def fsyncdir(path):
  fd=os.open(path,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
 def append(self,boundary,action,state,result,fault=None):
  r={'version':'DRA_RESEARCH_JOURNAL_V1','sequence':len(self.records)+1,'previous':self.records[-1]['sha'] if self.records else None,'boundary':boundary,'action':action,'state':state,'state_sha':digest(state),'result':result,'journal_prepare_utc':datetime.now(timezone.utc).isoformat(),'evaluation_clock':'AUTHORED_FIXTURE' if state['config']['mode']=='FIXTURE_ONLY' else 'SUPPLIED_CANDIDATE_UNQUALIFIED'}
  r['sha']=digest(r);blob=(canonical(r)+'\n').encode()
  try:
   validate_transition(self.state,state,boundary,action)
   from .trend_scope_sessions import verify_chain
   verify_chain(state,self.records)
   from .trend_handoff import verify_admissions
   verify_admissions(state,self.records)
  except (ValueError,Blocked) as exc:
   rejected=self.path/'stages'/f'{uuid.uuid4().hex}.conflicting-state.json'
   with open(rejected,'xb') as f:f.write(blob);f.flush();os.fsync(f.fileno())
   self.fsyncdir(rejected.parent);raise CorruptJournal(str(exc)) from exc
  if len(blob)>8*1024*1024:raise Blocked('RESEARCH_RECORD_RESOURCE_CAP')
  pending=self.path/'pending'/f'{uuid.uuid4().hex}.pending';final=self.path/'records'/f"{r['sequence']:08d}.json"
  with open(pending,'xb') as f:
   if fault=='PARTIAL_WRITE':f.write(blob[:len(blob)//2]);f.flush();os.fsync(f.fileno());os._exit(91)
   f.write(blob);f.flush();os.fsync(f.fileno())
  self.fsyncdir(pending.parent);self.stage(boundary+'_BEFORE_PUBLISH',r,fault)
  os.link(pending,final);self.fsyncdir(final.parent)
  self.stage(boundary+'_AFTER_PUBLISH',r,fault)
  self.state=deepcopy(state);self.records.append(r)
  self.stage('FINAL_ACK',r,fault)
  pending.unlink();self.fsyncdir(pending.parent)
  return result
