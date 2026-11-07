"""Research-only two-boundary manifests. Not production/LINUX durability qualification."""
import os,json,hashlib,fcntl,uuid,weakref
from datetime import datetime,timezone
from pathlib import Path
from copy import deepcopy
from functools import lru_cache
ROOT=Path(__file__).resolve().parents[3]
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):
 if isinstance(x,(_StateDict,_StateList,_FrozenDict,_FrozenList)):
  h=hashlib.sha256()
  chunks=[];size=0
  for chunk in _json_chunks(x):
   chunks.append(chunk);size+=len(chunk)
   if size>=1048576:h.update(b''.join(chunks));chunks=[];size=0
  if chunks:h.update(b''.join(chunks))
  return h.hexdigest()
 return hashlib.sha256(canonical(x).encode()).hexdigest()
def _record_blob(record):
 # Each value is encoded once. SHA is still SHA256 of exact canonical JSON of
 # the entire record excluding sha, never a delta digest under a state label.
 fields=[(key,_key_bytes(key)+b':'+b''.join(_json_chunks(value))) for key,value in sorted(record.items())]
 h=hashlib.sha256();h.update(b'{')
 for n,(key,value) in enumerate(fields):
  if n:h.update(b',')
  h.update(value)
 h.update(b'}');record['sha']=h.hexdigest()
 fields.append(('sha',b'"sha":'+canonical(record['sha']).encode()))
 chunks=[b'{']
 for n,(key,value) in enumerate(sorted(fields)):
  if n:chunks.append(b',')
  chunks.append(value)
 chunks.append(b'}\n');return b''.join(chunks)

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
   candidate=new[group].get(key)
   if candidate is not value and candidate!=value:raise ValueError('IMMUTABLE_'+group.upper()+'_PREFIX')
 for tf,prior in old['tf'].items():
  current=new['tf'][tf]
  for key,value in prior['windows'].items():
   candidate=current['windows'].get(key)
   if candidate is not value and candidate!=value:raise ValueError('IMMUTABLE_WINDOW_PREFIX')
  for group in ('looks','fragments','touches','tombstones'):
   if current[group][:len(prior[group])]!=prior[group]:raise ValueError('IMMUTABLE_'+group.upper()+'_PREFIX')
 if new['owner_generation']<old['owner_generation']:raise ValueError('OWNER_GENERATION_REWIND')
class _FrozenDict(dict):
 def __deepcopy__(self,memo):return self
 def _readonly(self,*a,**k):raise TypeError('IMMUTABLE_RESEARCH_CONFIG')
 __setitem__=__delitem__=clear=pop=popitem=update=__ior__=_readonly
 def setdefault(self,key,*default):
  if key in self:return self[key]
  return self._readonly()
class _FrozenList(list):
 def __deepcopy__(self,memo):return self
 def _readonly(self,*a,**k):raise TypeError('IMMUTABLE_RESEARCH_CONFIG')
 __setitem__=__delitem__=append=extend=insert=pop=remove=clear=sort=reverse=__iadd__=__imul__=_readonly

def _freeze_config(value):
 if isinstance(value,dict):return _FrozenDict({k:_freeze_config(v) for k,v in value.items()})
 if isinstance(value,list):return _FrozenList(_freeze_config(v) for v in value)
 return value

# Committed nodes are immutable. Explicit deepcopy remains a mutable copy for
# existing non-ingest callers; the hot ingest fork copies only writable shells.
class _StateDict(_FrozenDict):
 def __deepcopy__(self,memo):
  value={};memo[id(self)]=value
  value.update((k,deepcopy(v,memo)) for k,v in self.items());return value
class _StateList(_FrozenList):
 def __deepcopy__(self,memo):
  value=[];memo[id(self)]=value;value.extend(deepcopy(v,memo) for v in self);return value

@lru_cache(maxsize=8192,typed=True)
def _literal_bytes(value):return canonical(value).encode()
def _scalar_bytes(value):
 # Signed floating zero must not alias +0 in an equality-keyed cache.
 return _literal_bytes(value) if type(value) in (str,int,bool,type(None)) else canonical(value).encode()
@lru_cache(maxsize=4096,typed=True)
def _cached_key_bytes(key):return canonical({key:None}).encode()[1:-6]
def _key_bytes(key):
 return _cached_key_bytes(key) if type(key) in (str,int,bool,type(None)) else canonical({key:None}).encode()[1:-6]

def _encoded_size(value):
 if isinstance(value,(_StateDict,_StateList)):return value._json_size
 if isinstance(value,(_FrozenDict,_FrozenList)):
  if not hasattr(value,'_canonical_json'):value._canonical_json=canonical(value).encode()
  return len(value._canonical_json)
 return len(_scalar_bytes(value))

@lru_cache(maxsize=8192)
def _string_block(values):
 # Exact canonical string bytes, shared by equal immutable contributor prefixes.
 # Return the immutable values too: cold restore reuses equal strings rather
 # than multiplying the same source IDs merely through JSON decoding.
 return values,b','.join(_scalar_bytes(x) for x in values)

def _json_chunks(value,use_cache=True):
 if isinstance(value,_StateDict):
  cached=getattr(value,'_canonical_json',None)
  if cached is not None:yield cached;return
  if use_cache and value._json_size<=65536 and not value._shared_string_blocks:
   value._canonical_json=b''.join(_json_chunks(value,False));yield value._canonical_json;return
  yield b'{'
  for n,key in enumerate(value._json_keys):
   if n:yield b','
   yield _key_bytes(key);yield b':'
   yield from _json_chunks(value[key])
  yield b'}'
 elif isinstance(value,_StateList):
  blocks=getattr(value,'_string_blocks',None)
  if blocks is not None:
   yield b'['
   for n,block in enumerate(blocks):
    if n:yield b','
    yield block
   yield b']';return
  yield b'['
  for n,item in enumerate(value):
   if n:yield b','
   yield from _json_chunks(item)
  yield b']'
 elif isinstance(value,(_FrozenDict,_FrozenList)):
  _encoded_size(value);yield value._canonical_json
 elif isinstance(value,dict):
  yield b'{' 
  for n,key in enumerate(sorted(value)):
   if n:yield b','
   yield _key_bytes(key);yield b':'
   yield from _json_chunks(value[key])
  yield b'}'
 elif isinstance(value,(list,tuple)):
  yield b'['
  for n,item in enumerate(value):
   if n:yield b','
   yield from _json_chunks(item)
  yield b']'
 else:yield _scalar_bytes(value)

@lru_cache(maxsize=8)
def _sealed_strings(items):
 # Equal source-prefix lists may be shared only after freezing. Mutable TF
 # shells still come from _fork_ingest; values and V3 encoding stay identical.
 value=_StateList(items)
 blocks=tuple(_string_block(items[n:n+64])[1] for n in range(0,len(items),64))
 value._string_blocks=blocks;value._shared_string_blocks=True
 value._json_size=2+sum(map(len,blocks))+max(0,len(blocks)-1)
 return value

class _ForkList(list):
 def __init__(self,previous):
  super().__init__(previous);self._sealed_previous=previous

class _ForkDict(dict):
 def __init__(self,previous):
  super().__init__(previous);self._sealed_previous=previous

def _seal(value,baseline=None):
 if isinstance(value,(_StateDict,_StateList,_FrozenDict,_FrozenList)):return value
 if baseline and isinstance(value,(list,tuple)) and len(value)==len(baseline) and all(a==b for a,b in zip(value,baseline)):return baseline
 if isinstance(value,dict):
  previous=getattr(value,'_sealed_previous',None)
  if isinstance(previous,_StateDict) and all(k in value and value[k] is v for k,v in previous.items()):
   added={k:_seal(v,baseline) for k,v in value.items() if k not in previous}
   if not added:return previous
   sealed=_StateDict(previous);dict.update(sealed,added)
   sealed._json_key_encodings=dict(previous._json_key_encodings)
   sealed._json_key_encodings.update((k,_key_bytes(k)) for k in added)
   sealed._shared_string_blocks=previous._shared_string_blocks or any(getattr(v,'_shared_string_blocks',False) for v in added.values())
   sealed._json_keys=tuple(sorted(sealed))
   sealed._json_size=previous._json_size+sum(len(sealed._json_key_encodings[k])+1+_encoded_size(v) for k,v in added.items())+len(added)-(0 if previous else 1)
   sealed._append_parent_ref=weakref.ref(previous);sealed._added_keys=tuple(added)
   return sealed
  encoded_keys=getattr(previous,'_json_key_encodings',{})
  key_encodings={k:encoded_keys[k] if k in encoded_keys else _key_bytes(k) for k in value}
  value=_StateDict({k:_seal(v,baseline) for k,v in value.items()})
  value._json_key_encodings=key_encodings
  value._shared_string_blocks=any(getattr(v,'_shared_string_blocks',False) for v in value.values())
  value._json_keys=tuple(sorted(value))
  value._json_size=2+max(0,len(value)-1)+sum(len(key_encodings[k])+1+_encoded_size(v) for k,v in value.items())
  return value
 if isinstance(value,(list,tuple)):
  if value and all(type(v) is str for v in value):return _sealed_strings(tuple(value))
  previous=getattr(value,'_sealed_previous',None)
  if isinstance(previous,_StateList) and len(value)>=len(previous) and all(a is b for a,b in zip(previous,value)):
   if len(value)==len(previous):return previous
   suffix=[_seal(v,baseline) for v in value[len(previous):]]
   value=_StateList(previous);list.extend(value,suffix)
   value._shared_string_blocks=previous._shared_string_blocks or any(getattr(v,'_shared_string_blocks',False) for v in suffix)
   value._json_size=previous._json_size+sum(_encoded_size(v) for v in suffix)+len(suffix)-(0 if previous else 1)
   value._append_parent_ref=weakref.ref(previous)
   return value
  value=_StateList(_seal(v,baseline) for v in value)
  value._shared_string_blocks=any(getattr(v,'_shared_string_blocks',False) for v in value)
  if value and all(type(v) is str for v in value):
   blocks=[]
   for offset in range(0,len(value),64):
    items,encoded=_string_block(tuple(value[offset:offset+64]))
    list.__setitem__(value,slice(offset,offset+len(items)),items)
    blocks.append(encoded)
   value._string_blocks=tuple(blocks);value._shared_string_blocks=True
  value._json_size=2+max(0,len(value)-1)+sum(_encoded_size(v) for v in value)
  return value
 return value

def _seal_state(state):
 if isinstance(state,_StateDict):return state
 state=dict(state)
 if not isinstance(state['config'],_FrozenDict):state['config']=_freeze_config(state['config'])
 return _seal(state,state['config'].get('baseline'))

def _fork_ingest(state):
 if not isinstance(state,_StateDict):return deepcopy(state)
 value=dict(state)
 for key in ('raw','economic','signal_queue','intents','projection_results','admitted_segment_map'):value[key]=_ForkDict(state[key])
 for key in ('raw_order','receipts'):value[key]=_ForkList(state[key])
 value['tf']={}
 for tf,old in state['tf'].items():
  current=_ForkDict(old)
  for key in ('prefix','looks','fragments','touches','tombstones','blocked','audit'):current[key]=_ForkList(old[key])
  for key in ('windows','candidate'):current[key]=_ForkDict(old[key])
  value['tf'][tf]=current
 return value

LEGACY_COMPACT_VERSION='DRA_RESEARCH_JOURNAL_V2_DELTA'
COMPACT_VERSION='DRA_RESEARCH_JOURNAL_V3_DELTA'

def _packed_value(value,baseline):
 """Externalize exact baseline copies; explicit paths avoid reserved user keys."""
 refs=[]
 def pack(v,path):
  if baseline and isinstance(v,(list,tuple)) and len(v)==len(baseline) and all(a==b for a,b in zip(v,baseline)):
   refs.append(path);return None
  if isinstance(v,_StateList) and getattr(v,'_string_blocks',None) is not None:return v
  if isinstance(v,dict):return {k:pack(x,path+[k]) for k,x in v.items()}
  if isinstance(v,(list,tuple)):return [pack(x,path+[i]) for i,x in enumerate(v)]
  return v
 return pack(value,[]),refs

def _unpacked_value(value,refs,baseline):
 value=deepcopy(value)
 if refs and not baseline:raise ValueError('BASELINE_REFERENCE_UNAVAILABLE')
 for path in refs:
  if not path:value=baseline;continue
  target=value
  for key in path[:-1]:target=target[key]
  target[path[-1]]=baseline
 return value

def _state_delta(old,new):
 ops=[];baseline=old.get('config',{}).get('baseline')
 def emit(kind,path,value):
  value,refs=_packed_value(value,baseline);ops.append([kind,path,value,refs])
 def visit(a,b,path):
  if a is b:return
  if isinstance(a,dict) and isinstance(b,dict):
   if getattr(b,'_append_parent_ref',lambda:None)() is a:
    for key in b._added_keys:emit('set',path+[key],b[key])
    return
   for key in a:
    if key not in b:ops.append(['delete',path+[key]])
   for key,value in b.items():
    if key in a:visit(a[key],value,path+[key])
    else:emit('set',path+[key],value)
  elif isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
   known=getattr(b,'_append_parent_ref',lambda:None)() is a
   if known or (len(b)>=len(a) and all(x is y or x==y for x,y in zip(a,b))):
    if len(b)>len(a):emit('append',path,list(b[len(a):]))
   elif a!=b:emit('set',path,b)
  elif type(a) is not type(b) or a!=b:emit('set',path,b)
 visit(old,new,[]);return ops

def _apply_delta(previous,ops):
 state=dict(previous);baseline=state.get('config',{}).get('baseline')
 for op in ops:
  kind,path=op[:2]
  if not path:
   if kind!='set':raise ValueError('DELTA_ROOT')
   state=_unpacked_value(op[2],op[3],baseline);continue
  target=state
  for key in path[:-1]:
   child=target[key]
   if isinstance(child,(_StateDict,_FrozenDict)):child=_ForkDict(child);target[key]=child
   elif isinstance(child,(_StateList,_FrozenList)):child=list(child);target[key]=child
   target=child
  key=path[-1]
  if kind=='delete':del target[key]
  elif kind=='set':target[key]=_unpacked_value(op[2],op[3],baseline)
  elif kind=='append':
   if isinstance(target[key],(_StateList,_FrozenList)):target[key]=list(target[key])
   target[key].extend(_unpacked_value(op[2],op[3],baseline))
  else:raise ValueError('DELTA_OPERATION')
 return state

def _record_state(record,previous):
 if record.get('version')=='DRA_RESEARCH_JOURNAL_V1':return record['state']
 if record.get('version') not in (LEGACY_COMPACT_VERSION,COMPACT_VERSION):raise ValueError('JOURNAL_VERSION')
 if ('state' in record)==('state_delta' in record):raise ValueError('STATE_ENCODING')
 if 'state' in record:return record['state']
 if previous is None:raise ValueError('DELTA_WITHOUT_INITIAL_STATE')
 return _apply_delta(previous,record['state_delta'])


def record_state_ref(record):
 """Existing durable record identity; deliberately not a full-state digest."""
 return {'kind':'R08_COMMITTED_RECORD','sequence':record['sequence'],'record_sha':record['sha']}

def state_checkpoint_fields(record):
 fields={'state_sha':record.get('state_sha')}
 if record.get('version')==COMPACT_VERSION:fields['state_ref']=record_state_ref(record)
 return fields

def matches_state_checkpoint(record,checkpoint,state=None):
 if record.get('version')==COMPACT_VERSION:
  ref=record_state_ref(record)
  return (checkpoint.get('state_sha') is None and checkpoint.get('state_ref')==ref
          and (state is None or getattr(state,'_committed_record_ref',None)==ref))
 return (record.get('state_sha') is not None and checkpoint.get('state_sha')==record['state_sha']
         and (state is None or digest(state)==record['state_sha']))

def _check_state_encoding(record,state):
 if record.get('version')==COMPACT_VERSION:
  if 'state_sha' in record:raise ValueError('V3_FORBIDS_FULL_STATE_SHA_FIELD')
 elif record.get('version') in ('DRA_RESEARCH_JOURNAL_V1',LEGACY_COMPACT_VERSION):
  if record.get('state_sha')!=digest(state):raise ValueError('HASH_SEQUENCE')
 else:raise ValueError('JOURNAL_VERSION')

class _CommittedRecord(dict):
 """Keep existing record metadata; load a past snapshot only if requested.

 V1 snapshots and V2 deltas use the same files/commit ordering. Ordinary live
 ingest needs metadata plus current state, not every old snapshot in memory.
 Historical scope/admission reads reconstruct exact state on demand.
 """
 def __init__(self,record,path,restore):
  super().__init__((k,v) for k,v in record.items() if k not in ('state','state_delta'));self.path=path;self.restore=restore
 def __missing__(self,key):
  if key!='state':raise KeyError(key)
  return self.restore(self['sequence'],self['sha'])
 def get(self,key,default=None):
  try:return self[key]
  except KeyError:return default

class Journal:
 def __init__(self,path):
  self.path=Path(path).resolve()
  runtime=os.environ.get('BTC_ML_R08_RUNTIME_MOUNT')
  allowed=Path(runtime).resolve() if runtime else ROOT
  mount=Path(runtime) if runtime else Path('/Volumes/MaksTiger')
  if not self.path.is_relative_to(allowed) or os.stat(mount).st_dev==os.stat('/').st_dev or (runtime and not mount.is_mount()):raise Blocked('EXTERNAL_RESEARCH_ROOT_REQUIRED')
  self.device=os.stat(mount).st_dev
  if runtime:self.device_path=mount
  self.path.mkdir(parents=True,exist_ok=True)
  for n in ('records','pending','stages'):(self.path/n).mkdir(exist_ok=True)
  self.state=None;self.records=[];self.load()
 def load(self):
  records=self.records;state=self.state;prev=records[-1]['sha'] if records else None
  directory_stamp=(self.path/'records').stat().st_mtime_ns
  if records and getattr(self,'_loaded_records_stamp',None)==directory_stamp and not (self.path/'records'/f'{len(records)+1:08d}.json').exists():
   self.interrupted=sorted(p.name for p in (self.path/'pending').glob('*'))
   return state
  paths=sorted((self.path/'records').glob('*.json'))
  if len(paths)<len(records):raise CorruptJournal('HASH_SEQUENCE')
  for n,p in enumerate(paths[len(records):],len(records)+1):
   try:
    r=json.loads(p.read_text());body={k:v for k,v in r.items() if k!='sha'}
    if p.name!=f'{n:08d}.json' or r['sequence']!=n or r['previous']!=prev or r['sha']!=digest(body):raise ValueError('HASH_SEQUENCE')
    candidate=_record_state(r,state)
    if state is not None and candidate['config']==state['config']:candidate['config']=state['config']
    candidate=_seal_state(candidate)
    _check_state_encoding(r,candidate)
    r['state']=candidate
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
    candidate._committed_record_ref=record_state_ref(r)
    state=candidate;prev=r['sha'];records.append(_CommittedRecord(r,p,self._snapshot_at))
   except Exception as e:raise CorruptJournal(f'{p.name}: {e}') from e
  self._loaded_records_stamp=(self.path/'records').stat().st_mtime_ns
  self.state=state;self.records=records;self.interrupted=sorted(p.name for p in (self.path/'pending').glob('*'))
  return state
 def _snapshot_at(self,sequence,expected_sha):
  state=None;prev=None
  for n in range(1,sequence+1):
   r=json.loads((self.path/'records'/f'{n:08d}.json').read_text())
   if r['sequence']!=n or r['previous']!=prev or r['sha']!=digest({k:v for k,v in r.items() if k!='sha'}):raise CorruptJournal('HASH_SEQUENCE')
   candidate=_record_state(r,state)
   if state is not None and candidate['config']==state['config']:candidate['config']=state['config']
   candidate=_seal_state(candidate)
   try:_check_state_encoding(r,candidate)
   except ValueError as exc:raise CorruptJournal(str(exc)) from exc
   candidate._committed_record_ref=record_state_ref(r)
   state=candidate;prev=r['sha']
  if prev!=expected_sha:raise CorruptJournal('HASH_SEQUENCE')
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
  state=dict(state)
  if self.state is None:state['config']=_freeze_config(state['config'])
  elif state['config']==self.state['config']:state['config']=self.state['config']
  state=_seal_state(state)
  r={'version':COMPACT_VERSION,'sequence':len(self.records)+1,'previous':self.records[-1]['sha'] if self.records else None,'boundary':boundary,'action':action,'state':state,'result':result,'journal_prepare_utc':datetime.now(timezone.utc).isoformat(),'evaluation_clock':'AUTHORED_FIXTURE' if state['config']['mode']=='FIXTURE_ONLY' else 'SUPPLIED_CANDIDATE_UNQUALIFIED'}
  if self.state is not None:
   del r['state'];r['state_delta']=_state_delta(self.state,state)
  blob=_record_blob(r)
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
  state._committed_record_ref=record_state_ref(r)
  self.state=state;self.records.append(_CommittedRecord(r,final,self._snapshot_at))
  self._loaded_records_stamp=(self.path/'records').stat().st_mtime_ns
  self.stage('FINAL_ACK',r,fault)
  pending.unlink();self.fsyncdir(pending.parent)
  return result
