"""Explicit, durable open-position resume; no change to engine economics.

A fresh domain stages a verified contiguous market range before any engine
callback. The immutable range and committed-state manifest survive a crash;
only the original engine/receipt/checkpoint protocol advances its consumer.
"""
from __future__ import annotations
import hashlib,json,math,os,threading,time
from pathlib import Path
from decimal import Decimal
from datetime import datetime,timezone
from .execution_commit import atomic_bytes,prefix_digest
from .execution_market_processor import normalize_futures_agg_trade
from .execution_market_backfill import normalize_rest_agg_trade,default_fetch_agg_trades,ResumeCaptureTransport

from .admission_diagnostics import AdmissionDiagnostics,ObservedLock,diagnostic_attempt,diagnostic_capture,diagnostic_bbo,diagnostic_entry_ready

MODE='OPEN_POSITION_RESUME_V1'
def utc():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def publish(path,value):
 raw=json.dumps(value,sort_keys=True);atomic_bytes(path,json.dumps({'payload':raw,'sha256':hashlib.sha256(raw.encode()).hexdigest()},sort_keys=True).encode())
def load(path):
 e=json.loads(Path(path).read_text());raw=e['payload']
 if hashlib.sha256(raw.encode()).hexdigest()!=e['sha256']:raise RuntimeError('RESUME_DOCUMENT_CHECKSUM_MISMATCH')
 return json.loads(raw)
def reject(reason):raise RuntimeError('RESUME_'+reason)
def committed_snapshot(root,epoch):
 root=Path(root)
 if (root/'execution_commits_v1/pending.json').exists():reject('PENDING_EXECUTION_COMMIT')
 from ..sleeve_risk_contract import PERCENTAGES
 def rows(path):
  # Never retain complete book text or unused command/metrics rows in RAM.
  with path.open() as f:
   for line in f:
    if not line.strip():continue
    try:r=json.loads(line)
    except Exception:reject('MALFORMED_BOOK:'+path.name)
    if not isinstance(r,dict) or r.get('paper_epoch_id')!=epoch:reject('BOOK_EPOCH_MISMATCH')
    yield r
 members={};paths=sorted((root/'books').glob('*.jsonl'))
 if {p.stem for p in paths}!=set(('signals','commands','orders','fills','trades','positions','equity_snapshots','metrics','blocked')):reject('MISSING_BOOK')
 positions={};position_ids=set()
 for r in rows(root/'books/positions.jsonl'):
  ID=r['position_id'];position_ids.add(ID)
  if r.get('status')=='OPEN':positions[ID]=r
  elif r.get('status')=='CLOSED':positions.pop(ID,None)
  else:reject('POSITION_STATUS')
 opens=list(positions.values());entry_fills={p.get('entry_fill_id'):p['position_id'] for p in opens};found_fills=set();realized={tf:0.0 for tf in PERCENTAGES}
 for path in paths:
  seen=set();table=path.stem;key={'orders':'order_id','fills':'fill_id','trades':'trade_id'}.get(table)
  for r in rows(path):
   if key:
    ID=r.get(key)
    if not ID or ID in seen:reject('DUPLICATE_BOOK_ID:'+table)
    seen.add(ID)
   if table=='fills' and r.get('fill_id') in entry_fills and r.get('position_id')==entry_fills[r['fill_id']]:found_fills.add(r['fill_id'])
   if table=='trades' and r.get('status')=='CLOSED':
    if r.get('timeframe') not in PERCENTAGES or not math.isfinite(float(r['net_pnl_usd'])):reject('TRADE_TF_OR_PNL')
    realized[r['timeframe']]+=float(r['net_pnl_usd'])
  members[str(path.relative_to(root))]={'sha256':sha(path),'bytes':path.stat().st_size}
 sleeves=json.loads((root/'sleeves.json').read_text())
 if sleeves.get('epoch_id')!=epoch:reject('SLEEVE_EPOCH_MISMATCH')
 if set(sleeves['sleeves'])!=set(PERCENTAGES):reject('SLEEVE_TIMEFRAMES')
 for tf,s in sleeves['sleeves'].items():
  if s.get('epoch_id')!=epoch or s.get('timeframe')!=tf or float(s['risk_pct_per_trade'])!=PERCENTAGES[tf]:reject('SLEEVE_IDENTITY_OR_RISK_CONTRACT')
  if not all(math.isfinite(float(s[k])) for k in ('current_equity_usd','initial_equity_usd','cumulative_realized_net_pnl_usd','open_position_risk_usd')):reject('SLEEVE_NONFINITE')
  if not math.isclose(float(s['cumulative_realized_net_pnl_usd']),realized[tf],abs_tol=1e-7) or not math.isclose(float(s['current_equity_usd']),float(s['initial_equity_usd'])+realized[tf],abs_tol=1e-7):reject('SLEEVE_REALIZED_EQUITY_MISMATCH')
  own=[p for p in opens if p['timeframe']==tf]
  if len(own)>1 or s['open_position_id']!=(own[0]['position_id'] if own else None):reject('SLEEVE_POSITION_MISMATCH')
  if float(s['open_position_risk_usd'])!=float(own[0]['risk_amount_usd'] if own else 0):reject('SLEEVE_RISK_MISMATCH')
 for r in opens:
  for key in ('entry_price','quantity','stop_loss_price','take_profit_price','risk_amount_usd'):
   if not math.isfinite(float(r[key])) or float(r[key])<=0:reject('INVALID_POSITION:'+key)
  if r.get('timeframe') not in PERCENTAGES or r['side'] not in ('LONG','SHORT') or not r.get('opened_at') or not r.get('entry_decision_ts'):reject('POSITION_CLOCK_TF_OR_SIDE_MISSING')
 receipts=[];committed_entry_fills=set()
 for p in sorted((root/'execution_commits_v1/receipts').glob('*.json')):
  r=load(p)
  if r.get('epoch')!=epoch or r.get('status')!='COMMITTED':reject('RECEIPT_IDENTITY')
  for table,b in r['books'].items():
   target=root/'books'/(table+'.jsonl');offset=int(b['offset']);data=b['data'].encode()
   if prefix_digest(target,offset)!=b['prefix_sha256']:reject('RECEIPT_BOOK_PREFIX')
   with target.open('rb') as f:f.seek(offset);actual=f.read(len(data))
   if actual!=data:reject('RECEIPT_BOOK_DATA')
  if r.get('terminal') and isinstance(r.get('result'),dict) and r['result'].get('status')=='ENTERED':
   pid=r['result'].get('position_id')
   if pid is not None and pid not in position_ids:reject('ENTRY_RECEIPT_POSITION')
  if r.get('terminal'):
   for line in r['books'].get('fills',{}).get('data','').splitlines():
    fill=json.loads(line)
    if fill.get('action')=='ENTRY':committed_entry_fills.add(fill.get('fill_id'))
  members[str(p.relative_to(root))]={'sha256':sha(p),'bytes':p.stat().st_size}
  receipts.append({'file':str(p.relative_to(root)),'sha256':sha(p),'key':r['key'],'terminal':r.get('terminal'),
                   'publication_order':sum(b['offset']+len(b['data'].encode()) for b in r['books'].values())})
 for p in [root/'sleeves.json',root/'trading_contract.json',root/'context_consumer_checkpoint.json']:
  if p.exists():members[str(p.relative_to(root))]={'sha256':sha(p),'bytes':p.stat().st_size}
 for p in opens:
  if p.get('entry_fill_id') not in committed_entry_fills:reject('OPEN_POSITION_WITHOUT_COMMITTED_ENTRY_RECEIPT')
  if p.get('entry_fill_id') not in found_fills:reject('OPEN_POSITION_WITHOUT_FILL')
 raw=json.dumps(members,sort_keys=True)
 return {'members':members,'snapshot_sha256':hashlib.sha256(raw.encode()).hexdigest(),'open_positions':opens,
         'sleeves':sleeves,'last_committed_execution_receipt':max(receipts,key=lambda r:r['publication_order'],default=None),'receipts':receipts,'pending_commit':False}

def validate_resume_startup(root,domain_root,epoch,expected):
 """Validate before engine constructor (which otherwise repairs/syncs books)."""
 pending=Path(root)/'execution_commits_v1/pending.json'
 manifest=Path(domain_root)/'resume_manifest.json';proof=Path(domain_root)/'fresh_live_boundary.json'
 if pending.exists():
  if not manifest.exists() or not proof.exists() or load(proof).get('status')!='CONTINUITY_ADMITTED':reject('UNVERIFIED_PENDING_EXECUTION_COMMIT')
  intent=load(pending);m=load(manifest);proof_data=load(proof)
  if m.get('contract')!=MODE or m.get('epoch')!=epoch or m.get('execution_root')!=str(Path(root).resolve()) or m.get('new_domain')!=str(Path(domain_root).resolve()) or m.get('expected_position_ids')!=sorted(expected):reject('PENDING_MANIFEST_IDENTITY')
  if proof_data.get('schema_version')!=MODE or proof_data.get('paper_epoch_id')!=epoch or proof_data.get('manifest_sha256')!=sha(manifest):reject('PENDING_ADMISSION_IDENTITY')
  stage=Path(domain_root)/'verified_catchup.jsonl'
  if sha(stage)!=proof_data['verified_range_sha256']:reject('PENDING_RANGE_CHECKSUM')
  src=intent.get('source',{});kw=src.get('kwargs',{});identity=kw.get('source_event_id','')
  if intent.get('epoch')!=epoch or src.get('method')!='update_from_trade' or not identity.startswith('agg_'):reject('PENDING_COMMIT_IDENTITY')
  ID=int(identity[4:]);event=None
  if not m['last_durable_market_checkpoint']['last_processed_agg_trade_id']<ID<=proof_data['boundary_agg_trade_id']:reject('PENDING_OUTSIDE_ADMITTED_RANGE')
  with stage.open() as f:
   for line in f:
    row=json.loads(line)
    if row['aggregate_trade_id']==ID:event=row;break
  prov=kw.get('market_provenance',{})
  if event is None or float(kw.get('price',0))!=float(event['price']) or prov.get('exchange_trade_timestamp')!=event['exchange_trade_timestamp'] or prov.get('aggregate_trade_id')!=ID:reject('PENDING_EVENT_MISMATCH')
  # Actual v12 constructor recovers the original durable intent before restore.
  return
 snap=committed_snapshot(root,epoch)
 if not manifest.exists() and sorted(p['position_id'] for p in snap['open_positions'])!=sorted(expected):reject('EXPECTED_OPEN_POSITION_IDENTITY')

class OpenPositionResume:
 def __init__(self,processor,consumer,domain_root,*,previous_domain_root,expected_position_ids):
  self.diagnostic=AdmissionDiagnostics(domain_root)
  self.processor=processor;self.engine=processor.engine;self.consumer=consumer
  self.root=Path(domain_root);self.previous=Path(previous_domain_root);self.path=self.root/'fresh_live_boundary.json'
  self.manifest_path=self.root/'resume_manifest.json';self.stage=self.root/'verified_catchup.jsonl';self.lock=ObservedLock(threading.RLock(),self.diagnostic,'state')
  self.index_path=self.root/'verified_catchup.offsets';self.convergence_lock=ObservedLock(threading.RLock(),self.diagnostic,'convergence_authority');self.work_stop=threading.Event();self.worker=None
  self.authority_condition=threading.Condition();self.authority_turn='CONVERGENCE';self.admission_requested=False;self.admission_publisher=None;self.capture_mutator=None;self.handoff_snapshot=None
  self.target_id=None;self.current_ws=None;self.current_session=None;self.rest_calls=0;self.rest_retries=0;self.last_capture_error=None;self.capture_failure=None;self.superseded_count=0;self.bbo_callback_count=0
  self.capture_transport=ResumeCaptureTransport()
  # Only in-process authority: never deserialize or reuse an unadmitted hash.
  self.stage_hasher=hashlib.sha256();self.index_hasher=hashlib.sha256();self.stage_identity=None;self.stage_bytes=0
  self.proof=None;self.admitted=False;self.complete=False;self.bbo=None;self.count=0;self.last_id=None;self.last_T=None;self.last_ws=None;self.session=None
  from .execution_market_processor import DeferredPublicPublication
  self.public_defer=DeferredPublicPublication(self)
  self.engine.fresh_live_contract_required=True;processor.fresh_live_boundary=self
  if not expected_position_ids or self.root.resolve()==self.previous.resolve():reject('EXPLICIT_NEW_DOMAIN_AND_POSITION_REQUIRED')
  if processor.economic_dispatch_enabled or processor.entry_admission_enabled:reject('PROCESSOR_NOT_DEFERRED')
  if self.manifest_path.exists():
   self.manifest=load(self.manifest_path)
   if self.manifest['contract']!=MODE or self.manifest['epoch']!=self.engine.epoch.paper_epoch_id or self.manifest['execution_root']!=str(self.engine.epoch_root.resolve()) or self.manifest['new_domain']!=str(self.root.resolve()) or self.manifest['previous_live_domain']!=str(self.previous.resolve()) or self.manifest['expected_position_ids']!=sorted(expected_position_ids):reject('MANIFEST_IDENTITY')
   if self.path.exists():
    self.proof=load(self.path)
    if self.proof.get('schema_version')!=MODE or self.proof.get('paper_epoch_id')!=self.engine.epoch.paper_epoch_id:reject('ADMISSION_IDENTITY')
    if self.proof.get('manifest_sha256')!=sha(self.manifest_path):reject('ADMISSION_MANIFEST_MISMATCH')
    if self.proof['status']=='CATCHUP_COMPLETE':reject('COMPLETED_DOMAIN_REQUIRES_NEW_BOUNDARY')
    if self.proof['status']!='CONTINUITY_ADMITTED':reject('INVALID_ADMISSION_STATUS')
    self._verify_stage();self._verify_committed_evolution();self.admitted=True
   else:
    self._verify_initial_snapshot()
    if self.stage.exists():self.stage.rename(self.stage.with_name('unadmitted-'+str(time.time_ns())+'.jsonl'))
    if self.index_path.exists():self.index_path.rename(self.index_path.with_name('unadmitted-'+str(time.time_ns())+'.offsets'))
  else:
   if self.path.exists() or processor.wal.last_offset or processor.checkpoint.last_processed_agg_trade_id is not None:reject('DOMAIN_NOT_NEW')
   snap=committed_snapshot(self.engine.epoch_root,self.engine.epoch.paper_epoch_id)
   if sorted(p['position_id'] for p in snap['open_positions'])!=sorted(expected_position_ids):reject('EXPECTED_OPEN_POSITION_IDENTITY')
   cp_path=self.previous/'execution_market_checkpoint.json';cp=json.loads(cp_path.read_text())
   if cp.get('paper_epoch_id')!=self.engine.epoch.paper_epoch_id or cp.get('last_processed_agg_trade_id') is None:reject('PREVIOUS_CHECKPOINT_IDENTITY')
   ws_path=self.previous/'execution_market_wal/state.json';ws=json.loads(ws_path.read_text())
   if ws.get('paper_epoch_id')!=self.engine.epoch.paper_epoch_id or int(ws['last_wal_offset'])<int(cp['last_processed_wal_offset']):reject('PREVIOUS_WAL_AUTHORITY')
   from .execution_market_wal_archive import SegmentedWalStorage
   reader=object.__new__(SegmentedWalStorage);reader.root=ws_path.parent;reader.active_path=ws_path.parent/'events.jsonl';reader.archive_root=ws_path.parent/'archive'
   anchor=None
   for row in reader.iter_from_offset(max(0,int(cp['last_processed_wal_offset'])-1),active_start_offset=ws['active_segment_start_offset'],active_last_offset=ws['last_wal_offset']):
    if row.get('event_type')=='AGG_TRADE' and int(row['aggregate_trade_id'])==int(cp['last_processed_agg_trade_id']):anchor=row;break
   if anchor is None:reject('COMMITTED_MARKET_ANCHOR_UNAVAILABLE')
   self.manifest={'contract':MODE,'epoch':self.engine.epoch.paper_epoch_id,'execution_root':str(self.engine.epoch_root.resolve()),'new_domain':str(self.root.resolve()),'previous_live_domain':str(self.previous.resolve()),'expected_position_ids':sorted(expected_position_ids),'created_at':utc(),'committed_snapshot':snap,'last_durable_market_checkpoint':cp,'checkpoint_sha256':sha(cp_path),'previous_WAL_state':ws,'previous_WAL_state_sha256':sha(ws_path),'last_committed_market_event':anchor,'last_WAL_physical_position':{'active_file':str(reader.active_path),'bytes':reader.active_path.stat().st_size,'sha256':sha(reader.active_path)},'last_WAL_logical_position':ws['last_wal_offset']}
   publish(self.manifest_path,self.manifest)
  self.diagnostic.set_manifest_baseline(sha,self.manifest_path)
  self.anchor=int(self.manifest['last_durable_market_checkpoint']['last_processed_agg_trade_id']);self.last_id=self.anchor
  self.last_T=int(self.manifest['last_committed_market_event']['exchange_trade_timestamp']);self.target_id=self.anchor
  if self.admitted:
   self.last_id=self.proof['boundary_agg_trade_id'];self.last_T=self.proof['boundary_exchange_T'];self.count=self.proof['verified_rows']

 def _verify_initial_snapshot(self):
  snapshot=committed_snapshot(self.engine.epoch_root,self.engine.epoch.paper_epoch_id)
  self.diagnostic.snapshot_verified(snapshot,self.manifest['committed_snapshot'])
  if snapshot['snapshot_sha256']!=self.manifest['committed_snapshot']['snapshot_sha256']:reject('COMMITTED_BOOKS_CHANGED_BEFORE_ADMISSION')
 def _verify_stage(self):
  if sha(self.stage)!=self.proof['verified_range_sha256']:reject('VERIFIED_RANGE_CHECKSUM')
  last=self.manifest['last_durable_market_checkpoint']['last_processed_agg_trade_id'];count=0;T=int(self.manifest['last_committed_market_event']['exchange_trade_timestamp'])
  for e in self._rows():
   if int(e['aggregate_trade_id'])!=last+1 or int(e['exchange_trade_timestamp'])<T:reject('VERIFIED_RANGE_NOT_CONTIGUOUS')
   last+=1;T=int(e['exchange_trade_timestamp']);count+=1
  if count!=self.proof['verified_rows'] or last!=self.proof['boundary_agg_trade_id']:reject('VERIFIED_RANGE_BOUNDARY')
 def _verify_committed_evolution(self):
  snap=committed_snapshot(self.engine.epoch_root,self.engine.epoch.paper_epoch_id);original=self.manifest['committed_snapshot'];new=[]
  for receipt in snap['receipts']:
   old=original['members'].get(receipt['file'])
   if old:
    if old['sha256']!=receipt['sha256']:reject('ORIGINAL_RECEIPT_CHANGED')
   else:
    r=load(self.engine.epoch_root/receipt['file']);src=r.get('source',{});kwargs=src.get('kwargs',{});identity=kwargs.get('source_event_id','')
    if src.get('method')!='update_from_trade' or not identity.startswith('agg_'):reject('UNEXPECTED_RESUME_RECEIPT')
    ID=int(identity[4:])
    if not self.manifest['last_durable_market_checkpoint']['last_processed_agg_trade_id']<ID<=self.proof['boundary_agg_trade_id']:reject('RECEIPT_OUTSIDE_VERIFIED_RANGE')
    new.append(r)
  for name,old in original['members'].items():
   p=self.engine.epoch_root/name
   if name.startswith('books/'):
    if prefix_digest(p,old['bytes'])!=old['sha256']:reject('ORIGINAL_BOOK_PREFIX_CHANGED')
    cursor=old['bytes']
    pieces=sorted((b for r in new for t,b in r['books'].items() if name=='books/'+t+'.jsonl'),key=lambda b:b['offset'])
    for b in pieces:
     if b['offset']!=cursor:reject('UNRECEIPTED_BOOK_TAIL')
     cursor+=len(b['data'].encode())
    if p.stat().st_size!=cursor:reject('UNRECEIPTED_BOOK_TAIL')
   elif name in ('sleeves.json','context_consumer_checkpoint.json'):
    docs=[r['documents'][name] for r in new if name in r['documents']]
    if sha(p)!=old['sha256'] and not any(hashlib.sha256(d['data'].encode()).hexdigest()==sha(p) for d in docs):reject('UNRECEIPTED_STATE_CHANGE')
   elif sha(p)!=old['sha256']:reject('ORIGINAL_STATE_CHANGED')
 def _rows(self):
  with self.stage.open() as f:
   for line in f:yield json.loads(line)
 def _match(self,a,b):
  for key in ('a','T','m','f','l'):
   if key in a or key in b:
    if key not in a or key not in b or a[key]!=b[key]:reject('REST_WS_MISMATCH:'+key)
  for key in ('p','q'):
   if Decimal(str(a[key]))!=Decimal(str(b[key])):reject('REST_WS_MISMATCH:'+key)
 def _staged_event(self,ID):
  number=ID-self.anchor-1
  if number<0 or ID>self.last_id:reject('OVERLAP_OUTSIDE_VERIFIED_RANGE')
  with self.index_path.open('rb') as f:
   f.seek(number*8);raw=f.read(8)
  if len(raw)!=8:reject('STAGE_INDEX_INCOMPLETE')
  with self.stage.open('rb') as f:
   f.seek(int.from_bytes(raw,'little'));row=json.loads(f.readline())
  if row['aggregate_trade_id']!=ID:reject('STAGE_INDEX_IDENTITY')
  return {'a':ID,'T':row['exchange_trade_timestamp'],'p':row['price'],'q':row['quantity'],'m':row['buyer_is_market_maker'],
          **({k:row['rest_'+k] for k in ('f','l') if 'rest_'+k in row})}
 def _stage_file_identity(self):
  st=self.stage.stat();idx=self.index_path.stat()
  return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,
          idx.st_dev,idx.st_ino,idx.st_size,idx.st_mtime_ns,idx.st_ctime_ns)
 def _check_stage_integrity(self):
  # SHA proves the authored bytes; metadata protects exclusive file ownership.
  # Real disk SHA/count/IDs are still verified by _verify_stage before economics
  # and on admitted restart, independently of this nonpersistent optimization.
  if self.stage_identity is None:
   if self.count or self.stage.exists() or self.index_path.exists():reject('STAGE_INTEGRITY_NOT_INITIALIZED')
   return
  if self._stage_file_identity()!=self.stage_identity:reject('STAGE_INTEGRITY_CHANGED')
  if self.stage_bytes!=self.stage_identity[2] or self.stage_identity[7]!=self.count*8 or self.last_id!=self.anchor+self.count:reject('STAGE_INTEGRITY_RANGE')
 def _verified_stage_digest(self):
  self._check_stage_integrity()
  if not self.count:reject('EMPTY_VERIFIED_RANGE')
  # The offset index is small; check its authored digest even when timestamp
  # resolution cannot distinguish a same-size mutation in one clock tick.
  if sha(self.index_path)!=self.index_hasher.copy().hexdigest():reject('STAGE_INTEGRITY_INDEX_CHECKSUM')
  return self.stage_hasher.copy().hexdigest()
 def _append_verified(self,rows):
  if len(rows)>512:reject('STAGING_BATCH_LIMIT')
  self._check_stage_integrity()
  last=self.last_id;T=self.last_T;raw=[]
  for e in rows:
   ID=int(e['aggregate_trade_id']);nextT=int(e['exchange_trade_timestamp'])
   if ID!=last+1 or nextT<T or Decimal(e['price'])<=0 or Decimal(e['quantity'])<=0:reject('RANGE_GAP_DUPLICATE_OR_TIME_REGRESSION')
   raw.append((json.dumps(e,sort_keys=True)+'\n').encode());last=ID;T=nextT
  with self.stage.open('ab') as f,self.index_path.open('ab') as index:
   start=f.tell();index_start=index.tell();offset=start;offsets=[]
   for line in raw:offsets.append(offset.to_bytes(8,'little'));offset+=len(line)
   try:
    f.write(b''.join(raw));f.flush();os.fsync(f.fileno())
    index.write(b''.join(offsets));index.flush();os.fsync(index.fileno())
   except BaseException:
    f.seek(start);f.truncate();f.flush();os.fsync(f.fileno())
    index.seek(index_start);index.truncate();index.flush();os.fsync(index.fileno());raise
  # Publish in-memory integrity only after BOTH original durable appends.
  self.stage_hasher.update(b''.join(raw));self.index_hasher.update(b''.join(offsets));self.stage_bytes+=sum(map(len,raw))
  self.last_id=last;self.last_T=T;self.count+=len(rows)
  self.stage_identity=self._stage_file_identity();self._check_stage_integrity()
 def handle_market(self,payload,connection_session_id=None):
  # WS ingress carries evidence/high-watermark, never network I/O or economics.
  if self.complete:
   return self.processor.handle_market_ws_payload(payload,connection_session_id=connection_session_id)
  data=payload.get('data') or payload
  if data.get('e')!='aggTrade':return []
  ID=int(data['a']);sid=connection_session_id or self.processor.market_connection_session_id
  with self.lock:
   if self.admitted:
    self.target_id=max(self.target_id,ID)
    if sid==self.processor.market_connection_session_id and (self.current_session!=sid or self.current_ws is None or ID>=int(self.current_ws['a'])):self.current_ws=dict(data);self.current_session=sid
    return [{'status':'RESUME_POST_BOUNDARY_QUEUED_FOR_CONTIGUOUS_HANDOFF','id':ID}]
   if ID<=self.anchor:return [{'status':'VERIFIED_SUPERSEDED_BY_COMMITTED_CHECKPOINT','id':ID}]
   if ID<=self.last_id:
    self._match(self._staged_event(ID),data);self.superseded_count+=1
    if sid==self.processor.market_connection_session_id:
     if self.current_session!=sid or self.current_ws is None or ID>=int(self.current_ws['a']):self.current_ws=dict(data);self.current_session=sid
     if ID==self.last_id:self.last_ws=dict(data);self.session=sid;self.diagnostic.overlap_stored(self)
    return [{'status':'VERIFIED_SUPERSEDED_BY_REST','id':ID,'current_session':sid==self.processor.market_connection_session_id}]
   self.target_id=max(self.target_id,ID)
   if sid==self.processor.market_connection_session_id:
    if self.current_session!=sid or self.current_ws is None or ID>=int(self.current_ws['a']):
     self.current_ws=dict(data);self.current_session=sid
   return [{'status':'RESUME_RANGE_VERIFICATION_REQUESTED','id':ID,'current_session':sid==self.processor.market_connection_session_id}]
 def _begin_capture(self):
  # Protocol mutex is never held while acquiring capture/state locks or doing I/O.
  with self.authority_condition:
   if self.work_stop.is_set():return False
   if self.worker is not None and self.worker.is_alive() and self.worker.ident!=threading.get_ident():reject('SECOND_CONVERGENCE_WRITER')
   if self.capture_mutator is not None:reject('SECOND_CONVERGENCE_WRITER')
   if self.authority_turn=='ADMISSION':reject('CAPTURE_DURING_ADMISSION_HANDOFF')
   self.capture_mutator=threading.get_ident();return True
 def _end_capture(self):
  with self.authority_condition:
   self.capture_mutator=None;self.authority_condition.notify_all()
 def _offer_admission_turn(self,stop_requested):
  # Completed verified capture is stable until this turn is returned. Callbacks
  # retain their old short state-lock path; original predicates revalidate them.
  with self.lock:
   potential_overlap=self.last_ws is not None
   snapshot=(self.last_id,self.last_T,self.count)
  with self.authority_condition:
   if self.work_stop.is_set() or stop_requested() or self.admitted:return
   if not potential_overlap:return
   self.handoff_snapshot=snapshot;self.authority_turn='ADMISSION';self.authority_condition.notify_all()
   self.authority_condition.wait_for(lambda:self.authority_turn!='ADMISSION' or self.work_stop.is_set())
 def _claim_admission_turn(self):
  with self.authority_condition:
   if self.admission_publisher is not None:return 'BUSY'
   if self.work_stop.is_set():return 'STOPPED'
   if self.worker is not None and self.worker.is_alive() and self.authority_turn!='ADMISSION':
    self.admission_requested=True;return 'PENDING'
   self.admission_publisher=threading.get_ident();return 'OWNED'
 def _return_admission_turn(self):
  with self.authority_condition:
   self.admission_publisher=None;self.admission_requested=False;self.authority_turn='CONVERGENCE';self.authority_condition.notify_all()
 @diagnostic_capture
 def converge_once(self):
  # One capture authority. A REST request holds only this private authority lock;
  # WS/BBO callbacks use the separate short state lock and keep progressing.
  if not self._begin_capture():return False
  try:
   with self.convergence_lock:
    if self.admitted or self.complete:return False
    with self.lock:
     first=self.anchor if not self.stage.exists() else self.last_id+1
     end=min(first+511,self.target_id)
     if first>end:return False
     witness=dict(self.current_ws) if self.current_ws is not None else None
     witness_session=self.current_session
    if first==self.anchor:self._verify_initial_snapshot()
    self.rest_calls+=1
    fetch=self.processor.fetch_agg_trades
    rows=(self.capture_transport if fetch is default_fetch_agg_trades else fetch)(self.processor.symbol,first,end)
    if len(rows)!=end-first+1 or [int(r['a']) for r in rows]!=list(range(first,end+1)):reject('REST_RANGE_GAP_OR_DUPLICATE')
    if first==self.anchor:
     a=self.manifest['last_committed_market_event'];anchor={'a':self.anchor,'T':int(a['exchange_trade_timestamp']),'p':a['price'],'q':a['quantity'],'m':a['buyer_is_market_maker']}
     self._match(anchor,{k:v for k,v in rows[0].items() if k not in ('f','l')});rows=rows[1:]
    overlap=witness is not None and int(witness['a'])==end
    if overlap:self._match(rows[-1],witness)
    normalized=[{**normalize_rest_agg_trade(r,symbol=self.processor.symbol,connection_session_id=witness_session or self.processor.market_connection_session_id,receive_monotonic_ns=time.monotonic_ns(),receive_timestamp=utc()),**{'rest_'+k:r[k] for k in ('f','l') if k in r}} for r in rows]
    if overlap:
     normalized[-1]={**normalize_futures_agg_trade(witness,symbol=self.processor.symbol,connection_session_id=witness_session,receive_monotonic_ns=time.monotonic_ns(),receive_timestamp=utc()),**{'rest_'+k:rows[-1][k] for k in ('f','l') if k in rows[-1]}}
    with self.lock:
     self._append_verified(normalized)
     if overlap:self.last_ws=witness;self.session=witness_session;self.diagnostic.overlap_stored(self)
     elif self.last_ws is not None and int(self.last_ws['a'])!=self.last_id:self.last_ws=None;self.session=None
    self.last_capture_error=None
    return True
  finally:self._end_capture()
 def on_public_websocket_connected(self):
  self.processor.on_public_websocket_connected()
 def on_public_websocket_disconnected(self):
  self.processor.on_public_websocket_disconnected()
 def on_market_websocket_connected(self):
  self.processor.on_market_websocket_connected()
 def on_market_websocket_disconnected(self):
  self.processor.on_market_websocket_disconnected()
 def start_convergence(self,stop_requested):
  def run():
   import requests
   try:
    while not stop_requested() and not self.work_stop.is_set() and not self.admitted:
     try:
      progressed=self.converge_once()
      self._offer_admission_turn(stop_requested)
      self.work_stop.wait(.01 if progressed else .05)
     except (TimeoutError,requests.RequestException) as exc:
      self.rest_retries+=1;self.last_capture_error=str(exc)[:512];self.work_stop.wait(.25)
     except Exception as exc:
      self.capture_failure=str(exc)[:512];self.processor.engine.errors.append('resume_convergence:'+self.capture_failure);return
   finally:self.capture_transport.close()
  with self.authority_condition:
   if self.worker is not None:reject('SECOND_CONVERGENCE_WRITER')
   self.worker=threading.Thread(target=run,name='resume-capture-convergence',daemon=True);self.worker.start()
 def stop_convergence(self):
  with self.authority_condition:
   self.work_stop.set();self.authority_condition.notify_all()
  if self.worker is not None:self.worker.join(timeout=11)
  if self.worker is None or not self.worker.is_alive():self.capture_transport.close()
 @diagnostic_bbo
 def handle_public(self,payload,connection_session_id=None):
  sid=connection_session_id or self.processor.public_connection_session_id
  if self.complete:
   data=payload.get('data') or payload
   if not self.processor._looks_like_book_ticker(data):return []
   return self.public_defer.receive(payload,sid)
  data=payload.get('data') or payload
  if not self.processor._looks_like_book_ticker(data):return []
  if Decimal(str(data['b']))<=0 or Decimal(str(data['a']))<Decimal(str(data['b'])):reject('INVALID_BBO')
  with self.lock:
   self.bbo={'payload':payload,'received_at':utc(),'session':sid};self.bbo_callback_count+=1
   self.diagnostic.bbo_stored(self)
  return [{'status':'RESUME_BBO_STAGED','session':sid}]
 def _publish_public(self,payload,sid):
  with self.lock:self.bbo={'payload':payload,'received_at':utc(),'session':sid};self.diagnostic.bbo_stored(self)
  return self.processor.handle_public_ws_payload(payload)
 @diagnostic_entry_ready
 def entry_ready(self):
  if self.public_defer.fault or self.public_defer.active or self.public_defer.stopped():return False
  if not self.complete or not self.bbo or self.bbo.get('session')!=self.processor.public_connection_session_id:return False
  E=int((self.bbo['payload'].get('data') or self.bbo['payload']).get('E') or 0)
  return 0<=time.time_ns()/1e6-E<=self.engine.cfg.max_bbo_age_ms
 def _admission_evidence(self):
  if not self.last_ws or not self.bbo or not self.processor.state.websocket_connected:
   self.diagnostic.evidence(self,'BLOCK_NO_MARKET_OVERLAP' if not self.last_ws else 'BLOCK_NO_BBO' if not self.bbo else 'BLOCK_TRANSPORT_DISCONNECTED');return None
  if int(self.last_ws['a'])!=self.last_id or self.session!=self.processor.market_connection_session_id:
   self.diagnostic.evidence(self,'BLOCK_RANGE_NOT_CURRENT' if int(self.last_ws['a'])!=self.last_id else 'BLOCK_MARKET_SESSION_MISMATCH');return None
  if self.bbo.get('session')!=self.processor.public_connection_session_id:
   self.diagnostic.evidence(self,'BLOCK_BBO_SESSION_MISMATCH');return None
  E=int((self.bbo['payload'].get('data') or self.bbo['payload']).get('E') or 0);now=time.time_ns()/1e6
  if not (0<=now-E<=self.engine.cfg.max_bbo_age_ms and 0<=now-int(self.last_ws['T'])<=self.engine.cfg.max_agg_trade_age_ms):
   self.diagnostic.evidence(self,'BLOCK_BBO_FUTURE' if now<E else 'BLOCK_BBO_STALE' if now-E>self.engine.cfg.max_bbo_age_ms else 'BLOCK_MARKET_FUTURE' if now<int(self.last_ws['T']) else 'BLOCK_MARKET_STALE',guard_now_ms=now);return None
  self.diagnostic.evidence(self,guard_now_ms=now)
  return {'ws':dict(self.last_ws),'market_session':self.session,'bbo':dict(self.bbo),'public_session':self.bbo['session'],'generation':self.processor.reconnect_generation,'last_id':self.last_id}
 @diagnostic_attempt
 def try_activate(self):
  if self.complete:return self.entry_ready() and self.processor.state.execution_market_ready_for_entry()
  if self.capture_failure:reject('CONVERGENCE_HALTED:'+self.capture_failure)
  turn=self._claim_admission_turn()
  if turn!='OWNED':
   self.diagnostic.put(authority_handoff=turn)
   self.diagnostic.block({'PENDING':'BLOCK_ADMISSION_HANDOFF_PENDING','STOPPED':'BLOCK_RESUME_STOPPED','BUSY':'BLOCK_ADMISSION_LOCK_BUSY'}[turn]);return False
  acquired=False
  try:
   acquired=self.convergence_lock.acquire(blocking=False)
   if not acquired:
    self.diagnostic.put(admission_lock_acquired=False);self.diagnostic.block('BLOCK_ADMISSION_LOCK_BUSY');return False
   self.diagnostic.put(admission_lock_acquired=True,authority_handoff='OWNED')
   if self.admitted:
    self._catchup();return self.entry_ready() and self.processor.state.execution_market_ready_for_entry()
   with self.lock:evidence=self._admission_evidence()
   if evidence is None:return False
   for position in self.manifest['committed_snapshot']['open_positions']:
    opened=datetime.fromisoformat(position['opened_at'].replace('Z','+00:00')).timestamp()*1000
    if int(evidence['ws']['T'])<opened:reject('BOUNDARY_BEFORE_POSITION_OPEN')
   self.diagnostic.put(active_phase='COMMITTED_SNAPSHOT_VERIFY')
   self._verify_initial_snapshot()
   self.diagnostic.put(active_phase='STAGE_DIGEST')
   digest=self._verified_stage_digest()
   with self.lock:
    current=self._admission_evidence()
    self.diagnostic.revalidation(evidence,current,'AFTER_HASH_UNDER_STATE_LOCK')
    if current is None or any(current[k]!=evidence[k] for k in ('ws','market_session','public_session','generation','last_id')):return False
    evidence=current
    proof={'schema_version':MODE,'continuity_mode':MODE,'paper_epoch_id':self.engine.epoch.paper_epoch_id,'status':'CONTINUITY_ADMITTED','manifest_sha256':sha(self.manifest_path),'verified_range_sha256':digest,'verified_rows':self.count,'first_agg_trade_id':self.anchor+1,'boundary_agg_trade_id':self.last_id,'boundary_exchange_T':int(evidence['ws']['T']),'boundary_exchange_E':evidence['ws'].get('E'),'boundary_WS_event':evidence['ws'],'session':evidence['market_session'],'public_session':evidence['public_session'],'fresh_BBO':evidence['bbo'],'no_unresolved_gap':True,'admitted_at':utc(),'convergence_contract':'SINGLE_REST_AUTHORITY_CURRENT_SESSION_V2','rest_calls':self.rest_calls,'verified_superseded_by_rest':self.superseded_count}
    self._phase('before_admission')
    checked=self._admission_evidence()
    self.diagnostic.revalidation(evidence,checked,'BEFORE_DURABLE_PUBLICATION')
    if checked is None or any(checked[k]!=evidence[k] for k in ('ws','market_session','public_session','generation','last_id')):return False
    self._check_stage_integrity()
    proof['fresh_BBO']=checked['bbo']
    self.diagnostic.publish(publish,self.path,proof);self.proof=proof;self.admitted=True;self._phase('after_admission')
   self._catchup();return self.entry_ready() and self.processor.state.execution_market_ready_for_entry()
  finally:
   if acquired:self.convergence_lock.release()
   self._return_admission_turn()
 def _phase(self,name):pass
 def _catchup(self):
  try:return self._catchup_verified()
  except BaseException:
   self.processor.economic_dispatch_enabled=False;self.processor.entry_admission_enabled=False;self.processor._halted=True
   raise
 def _catchup_verified(self):
  if self.processor._halted:reject("PROCESSOR_RESTART_REQUIRED")
  self._verify_stage();self._verify_committed_evolution()
  staged=iter(self._rows());offset=0
  for persisted in self.processor.wal.iter_from_offset(0):
   expected=next(staged,None);offset+=1
   if expected is None or persisted.get('wal_offset')!=offset:reject('WAL_OUTSIDE_ADMITTED_RANGE')
   for key in ('event_type','aggregate_trade_id','exchange_trade_timestamp','price','quantity','buyer_is_market_maker','source_event_id'):
    if persisted.get(key)!=expected.get(key):reject('WAL_ADMITTED_PAYLOAD_MISMATCH:'+key)
  self.processor.economic_dispatch_enabled=True
  self.processor.entry_admission_enabled=False
  self._phase('before_catchup_dispatch')
  # This is the first permitted checkpoint-tail replay; only admitted staged rows.
  for event in self.processor.wal.iter_from_offset(self.processor.checkpoint.last_processed_wal_offset):
   if event.get('event_type')!='AGG_TRADE' or not self.anchor<int(event['aggregate_trade_id'])<=self.proof['boundary_agg_trade_id']:reject('WAL_OUTSIDE_ADMITTED_RANGE')
   if int(event['aggregate_trade_id']) not in self.processor.checkpoint.processed_agg_trade_ids:
    self.processor._dispatch_agg_trade(event,wal_offset=event['wal_offset'],save_checkpoint=False)
  self.processor._sync_engine_outputs();self.processor.checkpoint.save(self.processor.checkpoint_path)
  batch=[]
  def dispatch(rows):
   appends=self.processor.wal.append_batch(rows,max_events=512)
   if len(appends)!=len(rows) or any(not a.ok for a in appends):reject('CATCHUP_WAL_PUBLICATION_FAILED')
   for e,a in zip(rows,appends):
    self.processor._dispatch_agg_trade(e,wal_offset=a.wal_offset,save_checkpoint=False)
   self.processor._sync_engine_outputs();self._phase('before_checkpoint_publish');self.processor.checkpoint.save(self.processor.checkpoint_path);self._phase('after_catchup_checkpoint')
  for e in self._rows():
   current=self.processor.checkpoint.last_processed_agg_trade_id
   if current is not None and int(e['aggregate_trade_id'])<=current:continue
   batch.append(e)
   if len(batch)==512:dispatch(batch);batch=[]
  if batch:dispatch(batch)
  if self.processor.checkpoint.last_processed_agg_trade_id!=self.proof['boundary_agg_trade_id']:reject('CATCHUP_NOT_AT_BOUNDARY')
  fence=self.consumer.quarantine_recovery_backlog()
  self.proof={**self.proof,'status':'CATCHUP_COMPLETE','catchup_completed_at':utc(),'open_cutoff':fence['cutoff']};publish(self.path,self.proof)
  with self.lock:self.complete=True;self.admitted=True
  if self.bbo:self.processor.handle_public_ws_payload(self.bbo['payload'])
  self.processor._resolve_gap(last_confirmed=self.processor.checkpoint.last_processed_agg_trade_id)
  self.processor.entry_admission_enabled=True
  with self.lock:handoff=dict(self.current_ws) if self.current_ws is not None and self.current_session==self.processor.market_connection_session_id else None;handoff_session=self.current_session
  if handoff is not None and int(handoff['a'])>self.processor.checkpoint.last_processed_agg_trade_id:
   self.processor.handle_market_ws_payload(handoff,connection_session_id=handoff_session)
  return [{'status':'RESUME_CATCHUP_COMPLETE','last_agg_trade_id':self.processor.checkpoint.last_processed_agg_trade_id}]
