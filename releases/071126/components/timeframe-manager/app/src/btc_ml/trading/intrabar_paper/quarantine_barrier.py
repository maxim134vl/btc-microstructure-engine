"""Original quarantine dispositions through existing metadata authority, no execution."""
from __future__ import annotations
import base64,copy,datetime as dt,io,json
from pathlib import Path
from . import execution_commit as ec
from . import cold_forward_guard as c
from . import financial_authority_runtime as runtime

BARRIER='s41_recovery_open_barrier.json'
METHOD='quarantine_barrier_v1'
SCHEMA='quarantine_barrier_transition_v1'
# A bounded receipt input, not an economic or freshness threshold.
MAX_SNAPSHOT_BYTES=ec.MAX_INTENT_BYTES//3

def need(ok,code):c.need(ok,'QUARANTINE_'+code)
def stamp(value):
 need(type(value) is str,'CLOCK_TYPE')
 try:v=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
 except ValueError as e:raise c.ColdBlocked('QUARANTINE_CLOCK_INVALID') from e
 need(v.tzinfo is not None and v.utcoffset()==dt.timedelta(0),'UTC_REQUIRED');return v

def barrier(raw):
 v=json.loads(raw,object_pairs_hook=c.a.unique_object)
 need(type(v) is dict and v.get('schema_version')=='s41_recovery_open_barrier_v1' and v.get('paper_epoch_id')==c.EPOCH,'BARRIER_IDENTITY')
 need(v.get('status') in {'IN_PROGRESS','COMPLETED'},'BARRIER_STATUS_UNKNOWN');stamp(v['cutoff'])
 ids=v.get('open_command_ids');need(type(ids) is list and all(type(i) is str and i for i in ids) and len(ids)==len(set(ids)),'BARRIER_IDS')
 keys={'schema_version','paper_epoch_id','cutoff','status','open_command_ids'}
 if v['status']=='COMPLETED':
  need(v.get('close_commands_preserved') is True,'CLOSE_HISTORY_REQUIRED');keys|={'previous_cutoff','close_commands_preserved'}
  if v.get('previous_cutoff') is not None:need(stamp(v['previous_cutoff'])<=stamp(v['cutoff']),'PREVIOUS_CUTOFF_REGRESSION')
 else:need(ids==[],'IN_PROGRESS_CANNOT_ACK_IDS')
 need(set(v)==keys,'BARRIER_FIELDS_UNKNOWN');return v

def normal(command):
 from .cursor_ack import command_check
 value=ec.command_association({'method':'apply_s41_manager_command','args':[command],'kwargs':{}})['command']
 return command_check(value)

def capture_snapshot(path):
 present=path.exists();data=path.read_bytes() if present else b''
 need(not present or bool(data),'EMPTY_OR_PARTIAL_QUEUE_FILE')
 need(len(data)<=MAX_SNAPSHOT_BYTES,'SNAPSHOT_RESOURCE_BOUND')
 return data,present

def selection(snapshot,cursor,configured_consume_after=None):
 from ..command_bus import pending_from_frame,COMMAND_COLUMNS
 from .cursor_ack import legacy_ids
 LEGACY=legacy_ids()
 import pandas as pd
 need(len(snapshot)<=MAX_SNAPSHOT_BYTES,'SNAPSHOT_RESOURCE_BOUND')
 if snapshot:
  frame=pd.read_parquet(io.BytesIO(snapshot))
  need(set(COMMAND_COLUMNS)<=set(frame),'SNAPSHOT_SCHEMA')
 else:frame=pd.DataFrame(columns=COMMAND_COLUMNS)
 cfg=c.J(Path(runtime.authority().config['observation_config_path']));order=cfg['timeframes']
 from .s41_command_consumer import later_iso
 need(configured_consume_after in (None,cfg['s41_consume_commands_after']),'CONSUMER_BOUNDARY_UNQUALIFIED')
 effective=later_iso(cursor['consume_after'],configured_consume_after)
 processed=set(cursor['processed_command_ids']);need(set(LEGACY)<=processed,'LEGACY_PROCESSED_LOSS')
 ids=frame['command_id'].astype(str).tolist();need(len(ids)==len(set(ids)),'DUPLICATE_QUEUE_IDENTITIES')
 # Keep the original parser. Do not silently complete a sweep it cannot observe.
 commands=[]
 for tf in order:
  own=frame[frame['timeframe'].astype(str).str.upper()==tf].reset_index(drop=True)
  stamps=pd.to_datetime(own['evaluation_timestamp'],utc=True,errors='coerce',format='mixed')
  unsafe=own['intent'].astype(str).str.upper().isin({'OPEN_LONG','OPEN_SHORT'}) & ~own['command_id'].astype(str).isin(processed) & stamps.isna()
  need(not unsafe.any(),'QUEUE_TIMESTAMP_PARSER_BLOCKED')
  for cmd in pending_from_frame(own,processed_command_ids=processed,after_evaluation_timestamp=effective):
   if str(cmd.get('intent') or '').upper() not in {'OPEN_LONG','OPEN_SHORT'}:continue
   cmd=normal(cmd);need(cmd['timeframe']==tf and cmd['command_id'] not in LEGACY,'COMMAND_OWNERSHIP')
   commands.append(cmd);processed.add(cmd['command_id'])
 return commands

def selection_replayed(snapshot,cursor,configured_consume_after,replay_cache):
    # Reuse only an identical input to the existing selector in this replay.
    # Re-read every mutable dependency before each lookup; actual snapshot bytes,
    # not only a digest, are part of the cache identity.
    if replay_cache is None:
        return selection(snapshot,cursor,configured_consume_after)
    from .cursor_ack import legacy_ids
    cfg=c.J(Path(runtime.authority().config['observation_config_path']))
    def identity():
        return (snapshot, cursor['consume_after'], tuple(cursor['processed_command_ids']),
                configured_consume_after, ec.canonical(cfg), tuple(legacy_ids()))
    key=identity()
    if replay_cache.get('key')==key:
        return copy.deepcopy(replay_cache['commands'])
    commands=selection(snapshot,cursor,configured_consume_after)
    cfg_after=c.J(Path(runtime.authority().config['observation_config_path']))
    if ec.canonical(cfg_after)==ec.canonical(cfg) and identity()==key:
        replay_cache.clear();replay_cache.update(key=key,commands=copy.deepcopy(commands))
    else:
        replay_cache.clear()
    return commands

def acknowledged_commands(r):
 if r['source']['method']==METHOD and r['source']['args'][0]['stage']=='DISPOSE':return r['source']['args'][0]['commands']
 if r['source']['method']=='cursor_ack_v1':return [r['source']['args'][0]['command']]
 return []

def verify_transition(r,parent,tip,ar,docs,state,*,selection_cache=None,run_without_lock=None):
 from .cursor_ack import project_cache
 source=r['source'];need(source['method']==METHOD and source['kwargs']=={} and len(source['args'])==1,'SOURCE')
 b=source['args'][0];need(b['schema']==SCHEMA and b['epoch']==c.EPOCH and b['parent']==ec.head_reference(parent),'BODY_PARENT')
 need(b['stage'] in {'PREPARE','DISPOSE','COMPLETE'},'STAGE_UNKNOWN');need(b['execution_permission'] is False and b['market_continuity_proven'] is False,'NO_ADMISSION_GRANT')
 keys={'schema','epoch','stage','parent','execution_permission','market_continuity_proven','evaluated_at'}
 keys|={'previous_cutoff'} if b['stage']=='PREPARE' else {'configured_consume_after','prepared_reference','snapshot','commands','outcomes'} if b['stage']=='DISPOSE' else {'prepared_reference','disposition_reference'}
 need(set(b)==keys,'BODY_FIELDS_UNKNOWN')
 key=c.EPOCH+'|'+METHOD+'|'+ec.digest(ec.canonical(b).encode())
 need(r['key']==r.get('source_key')==key and r['terminal'] is True,'KEY_OR_TERMINAL')
 need(r['books']=={} and r['publication']['scopes']==parent['publication']['scopes'] and r['publication']['files']==parent['publication']['files'],'NO_FINANCIAL_EFFECTS')
 occupancy={tf:x['sleeve']['open_position_id'] for tf,x in parent['publication']['scopes'].items() if x['sleeve']['open_position_id']}
 need(r['occupancy_before']==r['occupancy_after']==occupancy,'OCCUPANCY_CHANGED')
 before=barrier(docs[BARRIER]);doc=r['documents'].get(BARRIER)
 if doc:need(doc['before']==c.H(docs[BARRIER]),'BARRIER_PARENT_BYTES')
 after=barrier(doc['data'].encode()) if doc else before
 need(stamp(after['cutoff'])>=stamp(before['cutoff']),'CUTOFF_REGRESSION')
 result=r['result'];need(result=={'status':b['stage'],'barrier':after,'economic_effects':0,'ack_is_fill':False,'market_continuity_proven':False,'entry_admission_granted':False},'RESULT')
 if b['stage']=='PREPARE':
  need(set(r['documents'])=={BARRIER} and after['status']=='IN_PROGRESS' and after['cutoff']==b['evaluated_at'] and b['previous_cutoff']==before['cutoff'],'PREPARE_SEMANTICS')
  state.setdefault('preparations',{})[r['key']]={'reference':ec.head_reference({'schema':ec.HEAD_SCHEMA,'epoch':c.EPOCH,'publication':r['publication'],'receipt_sha256':ec.digest(ec.encode_authority({**r,'status':'COMMITTED'}))}),'barrier_data':doc['data'],'previous_cutoff':b['previous_cutoff']}
  return []
 need(before['status']=='IN_PROGRESS','ACTIVE_PREPARE_REQUIRED')
 prepared=state.get('preparations',{}).get(b['prepared_reference']['receipt_key']);need(prepared and prepared['reference']==b['prepared_reference'] and prepared['barrier_data'].encode()==docs[BARRIER],'PREPARED_AUTHORITY_MISSING')
 if b['stage']=='COMPLETE':
  need(set(r['documents'])=={BARRIER} and after['status']=='COMPLETED','COMPLETE_SEMANTICS')
  disposed=state.get('dispositions',{}).get(b['disposition_reference']['receipt_key']);need(disposed and disposed['reference']==b['disposition_reference'] and disposed['prepared_reference']==b['prepared_reference'],'COMPLETED_WITHOUT_DISPOSITION_ACK')
  need(after['open_command_ids']==disposed['command_ids'] and after['previous_cutoff']==prepared['previous_cutoff'] and after['cutoff']==b['evaluated_at'],'COMPLETE_DISPOSITION_BINDING')
  need(stamp(b['evaluated_at'])>=stamp(disposed['evaluated_at']),'COMPLETION_BEFORE_ACK')
  return []
 need(set(r['documents'])=={'s41_command_cursor.json'} and after==before,'DISPOSITION_MUST_KEEP_BARRIER_IN_PROGRESS')
 need(not any(x['prepared_reference']==b['prepared_reference'] for x in state.get('dispositions',{}).values()),'DUPLICATE_PREPARE_DISPOSITION')
 try:snapshot=base64.b64decode(b['snapshot']['base64'],validate=True)
 except Exception as e:raise c.ColdBlocked('QUARANTINE_SNAPSHOT_ENCODING') from e
 need(type(b['snapshot']['present']) is bool and (bool(snapshot) if b['snapshot']['present'] else snapshot==b''),'SNAPSHOT_PRESENCE_CONFLICT')
 need(len(snapshot)==b['snapshot']['bytes'] and ec.digest(snapshot)==b['snapshot']['sha256'],'SNAPSHOT_IDENTITY')
 prior=json.loads(docs['s41_command_cursor.json'])
 compute=lambda:selection_replayed(snapshot,prior,b["configured_consume_after"],selection_cache)
 commands=run_without_lock(compute) if run_without_lock else compute()
 need(ec.canonical(commands)==ec.canonical(b['commands']),'INCOMPLETE_OR_FALSE_DISPOSITION')
 ids=[x['command_id'] for x in commands]
 need(b['outcomes']==[{'command_id':x['command_id'],'timeframe':x['timeframe'],'status':'ENTRY_BLOCKED_RECOVERY_BARRIER','economic_effects':0,'ack_is_fill':False} for x in commands],'PROCESSING_RESULT_BINDING')
 next_cursor=copy.deepcopy(prior);known=list(state['acks'])
 for cmd in commands:
  need(cmd['command_id'] not in state['acks'],'DUPLICATE_DISPOSITION')
  next_cursor['processed_command_ids']=project_cache(next_cursor['processed_command_ids'],cmd['command_id'],known);known.append(cmd['command_id'])
 next_cursor['updated_at']=b['evaluated_at'];need(stamp(next_cursor['updated_at'])>=stamp(prior['updated_at']),'CURSOR_CLOCK_REGRESSION')
 cp=r['documents']['s41_command_cursor.json'];need(cp['before']==c.H(docs['s41_command_cursor.json']) and json.loads(cp['data'])==next_cursor,'CURSOR_DISPOSITION_BINDING')
 state.setdefault('dispositions',{})[r['key']]={'reference':ec.head_reference({'schema':ec.HEAD_SCHEMA,'epoch':c.EPOCH,'publication':r['publication'],'receipt_sha256':ec.digest(ec.encode_authority({**r,'status':'COMMITTED'}))}),'prepared_reference':b['prepared_reference'],'command_ids':ids,'evaluated_at':b['evaluated_at']}
 return commands

def publish(owner,stage,body,documents):
 owner._verify_owned();head=ec.verify_committed_head(owner.root,c.EPOCH)
 body.update(schema=SCHEMA,epoch=c.EPOCH,stage=stage,parent=ec.head_reference(head),execution_permission=False,market_continuity_proven=False)
 key=c.EPOCH+'|'+METHOD+'|'+ec.digest(ec.canonical(body).encode());source={'method':METHOD,'args':[body],'kwargs':{}}
 pub={'schema':ec.HEAD_SCHEMA,'epoch':c.EPOCH,'generation':head['publication']['generation']+1,'parent':ec.head_reference(head),'key':key,'association':ec.command_association(source),'files':head['publication']['files'],'scopes':head['publication']['scopes']}
 occupancy={tf:x['sleeve']['open_position_id'] for tf,x in head['publication']['scopes'].items() if x['sleeve']['open_position_id']}
 result={'status':stage,'barrier':barrier(documents[BARRIER]['data'].encode()) if BARRIER in documents else barrier((owner.root/BARRIER).read_bytes()),'economic_effects':0,'ack_is_fill':False,'market_continuity_proven':False,'entry_admission_granted':False}
 intent={'schema':'execution_commit_v3','epoch':c.EPOCH,'key':key,'source_key':key,'status':'INTENT','source':source,'result':result,'terminal':True,'books':{},'documents':documents,'occupancy_before':occupancy,'occupancy_after':occupancy,'publication':pub}
 pub['history']=c.fh.plan(head['publication']['history'],c.fh.receipt_leaf(intent))[0]
 docs,state=parent_documents(owner.root,ec.head_reference(head))
 verify_transition(intent,head,head,owner.root/'execution_commits_v1',docs,state)
 data=ec.encode_authority(intent);need(len(data)<=ec.MAX_INTENT_BYTES,'INTENT_RESOURCE_BOUND');need(not owner.books.commit.pending.exists(),'UNRESOLVED_PENDING')
 ec.atomic_bytes(owner.books.commit.pending,data);owner.books.commit._phase('quarantine_after_intent:'+stage)
 owner.books.commit.materialize(intent);owner._verify_owned();return result,ec.head_reference(ec.verify_committed_head(owner.root,c.EPOCH))

def parent_documents(root,reference):
 """Read-only reconstruct published documents with native membership/witness proof."""
 from .cursor_ack import GuardExtension
 from .publication_witness import record
 ar=root/'execution_commits_v1';g=reference['generation'];need(type(g) is int and g>=1,'PARENT_GENERATION_INVALID')
 top=ec.decode_authority(ar/'publications'/f'{g}.json',c.EPOCH);tip={'schema':ec.HEAD_SCHEMA,'epoch':c.EPOCH,'publication':top['publication'],'receipt_sha256':ec.digest((ar/'publications'/f'{g}.json').read_bytes())};need(ec.head_reference(tip)==reference,'PARENT_REFERENCE')
 docs={n:(runtime.source_financial_root()/n).read_bytes() for n in ('sleeves.json',)+c.CURSORS+(BARRIER,)};ext=GuardExtension();state=ext.begin();prev=None;witness=None
 for n in range(1,g+1):
  p=ar/'publications'/f'{n}.json';r=ec.decode_authority(p,c.EPOCH);h={'schema':ec.HEAD_SCHEMA,'epoch':c.EPOCH,'publication':r['publication'],'receipt_sha256':ec.digest(p.read_bytes())}
  need(r['status']=='COMMITTED' and r['publication']['generation']==n and (ar/'receipts'/(ec.digest(r['key'].encode())+'.json')).read_bytes()==p.read_bytes(),'PARENT_MARKER_RECEIPT')
  ec._verify_receipt(h,ar,c.EPOCH,tip['publication']['history'])
  need((ar/'publication.witness').read_bytes()[(n-1)*176:n*176]==record(h,witness),'PARENT_WITNESS');witness=record(h,witness)
  if n==1:
   need(r['publication']['parent'] is None and r['source']['method']=='legacy_snapshot_admission_v1','PARENT_GENESIS');prev=h;continue
  need(r['publication']['parent']==ec.head_reference(prev),'PARENT_CHAIN');ext.receipt(r,prev,tip,ar,docs,state)
  for name,e in r['documents'].items():
   need(name in docs,'PARENT_DOCUMENT_UNKNOWN');docs[name]=ext.bridge(name,docs[name],e,r,state);need(e['before']==ec.digest(docs[name]),'PARENT_DOCUMENT_BYTES')
   new=e['data'].encode()
   if name in c.CURSORS or name==BARRIER:ext.cursor(name,json.loads(docs[name]),json.loads(new),r,state)
   docs[name]=new
  prev=h
 return docs,state

def read_current(books):
 from .unified_financial_authority import check_locked
 with books.exclusive():
  check_locked(books.root.parent,books.paper_epoch_id);return barrier((books.root.parent/BARRIER).read_bytes())

def quarantine(consumer):
 from .unified_financial_authority import ack_owner
 from .cursor_ack import project_cache,raw
 from .s41_command_consumer import _utc_iso
 books=consumer.engine.books
 with books.exclusive():
  owner=ack_owner(books);owner._verify_owned();consumer._state=consumer._load();old=barrier((owner.root/BARRIER).read_bytes())
  # Verify original parser/captured input before mutating even a technical fence.
  initial,_=capture_snapshot(consumer.bus.paths.memory);selection(initial,json.loads((owner.root/'s41_command_cursor.json').read_bytes()),consumer.consume_after)
  if old['status']=='IN_PROGRESS':
   docs,state=parent_documents(owner.root,ec.head_reference(ec.verify_committed_head(owner.root,c.EPOCH)))
   prepared=next((x for x in state['preparations'].values() if x['barrier_data'].encode()==docs[BARRIER]),None);need(prepared is not None,'PREPARE_RESUME_AUTHORITY');prepared_ref=prepared['reference'];previous_cutoff=prepared['previous_cutoff']
  else:
   at=_utc_iso();need(stamp(at)>=stamp(old['cutoff']),'CLOCK_REGRESSION')
   fence={'schema_version':'s41_recovery_open_barrier_v1','paper_epoch_id':c.EPOCH,'cutoff':at,'status':'IN_PROGRESS','open_command_ids':[]}
   _,prepared_ref=publish(owner,'PREPARE',{'evaluated_at':at,'previous_cutoff':old['cutoff']},{BARRIER:{'before':ec.digest((owner.root/BARRIER).read_bytes()),'data':raw(fence).decode()}});previous_cutoff=old['cutoff']
  books.commit._phase('quarantine_prepared')
  _,state=parent_documents(owner.root,ec.head_reference(ec.verify_committed_head(owner.root,c.EPOCH)))
  disposed=next((x for x in state.get('dispositions',{}).values() if x['prepared_reference']==prepared_ref),None)
  if disposed is None:
   before_cp=(owner.root/'s41_command_cursor.json').read_bytes();cursor=json.loads(before_cp)
   snapshot,present=capture_snapshot(consumer.bus.paths.memory);commands=selection(snapshot,cursor,consumer.consume_after)
   for cmd in commands:consumer._record_open_rejection(cmd['command_id'],cmd['timeframe'],'ENTRY_BLOCKED_RECOVERY_BARRIER')
   at=_utc_iso();need(stamp(at)>=stamp(barrier((owner.root/BARRIER).read_bytes())['cutoff']),'DISPOSITION_CLOCK_REGRESSION')
   after=copy.deepcopy(cursor);known=list(state['acks'])
   for cmd in commands:after['processed_command_ids']=project_cache(after['processed_command_ids'],cmd['command_id'],known);known.append(cmd['command_id'])
   after['updated_at']=at
   body={'configured_consume_after':consumer.consume_after,'evaluated_at':at,'prepared_reference':prepared_ref,'snapshot':{'present':present,'path':str(consumer.bus.paths.memory),'bytes':len(snapshot),'sha256':ec.digest(snapshot),'base64':base64.b64encode(snapshot).decode()},'commands':commands,'outcomes':[{'command_id':x['command_id'],'timeframe':x['timeframe'],'status':'ENTRY_BLOCKED_RECOVERY_BARRIER','economic_effects':0,'ack_is_fill':False} for x in commands]}
   _,disposition_ref=publish(owner,'DISPOSE',body,{'s41_command_cursor.json':{'before':ec.digest(before_cp),'data':raw(after).decode()}})
   ids=[x['command_id'] for x in commands]
  else:disposition_ref=disposed['reference'];ids=disposed['command_ids']
  books.commit._phase('quarantine_disposition_committed')
  # Original completion clock is sampled only after command persistence/ACK.
  at=_utc_iso()
  fence={'schema_version':'s41_recovery_open_barrier_v1','paper_epoch_id':c.EPOCH,'cutoff':at,'status':'COMPLETED','open_command_ids':ids,'previous_cutoff':previous_cutoff,'close_commands_preserved':True}
  result,_=publish(owner,'COMPLETE',{'evaluated_at':at,'prepared_reference':prepared_ref,'disposition_reference':disposition_ref},{BARRIER:{'before':ec.digest((owner.root/BARRIER).read_bytes()),'data':raw(fence).decode()}})
  consumer._quarantine=result['barrier'];consumer._state=consumer._load();return result['barrier']
