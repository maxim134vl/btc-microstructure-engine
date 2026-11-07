"""Read-only, research-only cold/prefix verifier. Never grants execution.

No original Final65 source modification or automatic recovery. Trust anchor SHA
must come from outside the candidate financial root. APFS tests are not Linux QA.
"""
from __future__ import annotations
import contextlib, copy, datetime as dt, fcntl, hashlib, importlib.util, json, os
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from . import legacy_admission as a
from . import financial_authority_runtime as runtime

def native_ec(): return a.reference()[0]
def native_fh(): return a.reference()[1]
def authority_policy(): return runtime.policy()
def authority_epoch(): return runtime.epoch()
def authority_source(): return runtime.source()
def authority_root_rel(): return runtime.root_relative()
CURSORS=('context_consumer_checkpoint.json','s41_command_cursor.json')

def __getattr__(name):
 if name=='P': return authority_policy()
 if name=='EPOCH': return authority_epoch()
 if name=='SOURCE': return authority_source()
 if name=='ROOT_REL': return authority_root_rel()
 if name in {'ec','fh','bm'}: return a.reference()[{'ec':0,'fh':1,'bm':2}[name]]
 raise AttributeError(name)
class ColdBlocked(RuntimeError):pass
def need(ok,code):
 if not ok:raise ColdBlocked(code)
def H(b):return hashlib.sha256(b).hexdigest()
def J(path):return a.read_json(path)
def identity(raw):return {'bytes':len(raw),'sha256':H(raw)}
def _contains_symlink(root):
 # Same complete namespace check. DirEntry type information avoids a separate
 # lstat RPC for every Path on the external filesystem. No validated data cache.
 pending=[str(root)]
 while pending:
  with os.scandir(pending.pop()) as entries:
   for entry in entries:
    if entry.is_symlink():return True
    if entry.is_dir(follow_symlinks=False):pending.append(entry.path)
 return False

def case_guard(case):
 with runtime.validated_path_reads():
  case=Path(case)
  need(case.resolve()==runtime.case_root(),'FINANCIAL_CASE_IDENTITY_CONFLICT')
  for member in authority_policy()['state_members']:runtime.member_path(case,member['path'])
  need(not _contains_symlink(runtime.authority().root),'SYMLINK_FORBIDDEN')
  return case.resolve()
def locked(case):
 @contextlib.contextmanager
 def acquire():
  case_guard(case);p=case/authority_root_rel()/'books/.writer.lock';need(p.is_file(),'LOCK_FILE_MISSING')
  with p.open('rb') as f:
   try:fcntl.flock(f,fcntl.LOCK_SH|fcntl.LOCK_NB)
   except BlockingIOError:raise ColdBlocked('PUBLICATION_IN_PROGRESS')
   try:yield f
   finally:fcntl.flock(f,fcntl.LOCK_UN)
 return acquire()
def verify_committed_head_cooperative(root,epoch,shared_lock):
 """Run the original full verifier in bounded reader sections.

 The caller owns shared_lock. Every yield rechecks pending and exact head bytes;
 any concurrent financial publication fails closed and requires a new pass.
 """
 from . import execution_commit as ec, unified_financial_authority as unified
 from .cursor_ack import GuardExtension
 root=Path(root).resolve();ar=root/'execution_commits_v1';head_path=ar/'head.json'
 need(not (ar/'pending.json').exists(),'PAPER_FINANCIAL_RECOVERY_REQUIRED')
 baseline=head_path.read_bytes()
 def run_without_lock(operation):
  fcntl.flock(shared_lock.fileno(),fcntl.LOCK_UN)
  try: result=operation()
  finally: fcntl.flock(shared_lock.fileno(),fcntl.LOCK_SH)
  need(not (ar/'pending.json').exists(),'PAPER_FINANCIAL_RECOVERY_REQUIRED')
  need(head_path.read_bytes()==baseline,'PAPER_FINANCIAL_HEAD_CHANGED')
  return result
 def prepare():
  c,case,checked,anchor,pin=unified.binding(root,epoch)
  return c.ColdValidator(case,anchor,pin,extension=GuardExtension())
 validator=run_without_lock(prepare)
 validator._verify(None,_yield_writer=lambda:run_without_lock(lambda:None),_run_without_lock=run_without_lock)
 run_without_lock(lambda:None)
 head=run_without_lock(lambda:ec._verify_committed_head_raw(root,epoch))
 need(head_path.read_bytes()==baseline,'PAPER_FINANCIAL_HEAD_CHANGED')
 return head

def legacy_image():
 a.pinned_check(authority_source(),authority_policy())
 return a.semantic_check(authority_source(),authority_policy())
def validate_anchor(case,anchor_path,expected_sha):
 path=Path(anchor_path)
 need(path.resolve()==runtime.anchor_path().resolve() and not path.is_symlink(),'INDEPENDENT_ANCHOR_REQUIRED')
 need(H(path.read_bytes())==expected_sha,'ANCHOR_PIN_CONFLICT')
 v=J(path)
 need(v['schema']=='cold_legacy_trust_anchor_v1' and v['policy_sha256']==runtime.policy_sha() and v['epoch']==authority_epoch(),'ANCHOR_IDENTITY_CONFLICT')
 ar=case/authority_root_rel()/'execution_commits_v1';bound=native_ec().decode_authority(ar/'publications/1.json',authority_epoch())
 need(H((ar/'publications/1.json').read_bytes())==v['boundary_receipt_sha256'],'BOUNDARY_PIN_CONFLICT')
 # Validate exact original metadata plan against original trusted constituents,
 # not against mutable present-day sleeves/books.
 intent={**bound,'status':'INTENT'}
 facts=legacy_image();a.validate_plan(intent,runtime.source_financial_root(),authority_policy(),facts)
 boundary={'schema':native_ec().HEAD_SCHEMA,'epoch':authority_epoch(),'publication':bound['publication'],'receipt_sha256':v['boundary_receipt_sha256']}
 need(native_ec().head_reference(boundary)==v['boundary'],'BOUNDARY_HEAD_CONFLICT')
 need(H((ar/'publication.witness').read_bytes()[:176])==v['first_witness_sha256'],'BOUNDARY_WITNESS_CONFLICT')
 return v,facts,boundary

def seal_admission(case,anchor_path):
 """One metadata research pin outside the financial root, never financial ACK."""
 case=case_guard(case);p=Path(anchor_path)
 need(p.resolve()==runtime.anchor_path().resolve() and not p.exists(),'NEW_ANCHOR_REQUIRED')
 with locked(case):
  a.verify_legacy(case,authority_policy());head=native_ec().verify_committed_head(case/authority_root_rel(),authority_epoch())
  need(head['publication']['generation']==1,'SEAL_REQUIRES_INITIAL_BOUNDARY')
  bound=native_ec().decode_authority(case/authority_root_rel()/'execution_commits_v1/publications/1.json',authority_epoch())
  a.validate_plan({**bound,'status':'INTENT'},case/authority_root_rel(),authority_policy(),legacy_image())
  v={'schema':'cold_legacy_trust_anchor_v1','epoch':authority_epoch(),'policy_sha256':runtime.policy_sha(),'boundary':native_ec().head_reference(head),'boundary_receipt_sha256':head['receipt_sha256'],'first_witness_sha256':H((case/authority_root_rel()/'execution_commits_v1/publication.witness').read_bytes()[:176]),'authority':'RESEARCH_METADATA_ONLY','entry_allowed':False}
  p.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
 return H(p.read_bytes())

def monotonic_cursor(name,before,after):
 need(set(before)==set(after),'CURSOR_SCHEMA_CHANGED:'+name)
 ids='processed_keys' if name.startswith('context_') else 'processed_command_ids'
 need(all(type(x) is str for x in after[ids]) and len(after[ids])==len(set(after[ids])),'CURSOR_ID_INVALID')
 need(set(before[ids])<=set(after[ids]),'CURSOR_HISTORY_LOSS')
 if name.startswith('context_'):
  need(after['paper_epoch_id']==before['paper_epoch_id']==authority_epoch(),'CURSOR_EPOCH_CONFLICT')
  need(after['last_path']==before['last_path'],'CURSOR_SOURCE_ROTATION_UNQUALIFIED')
  for k in ['last_offset','last_event_monotonic_ns','duplicate_events_prevented']:
   need(type(after[k]) is int and after[k]>=before[k],'CURSOR_ROLLBACK:'+k)
 else:
  need(after['schema_version']==before['schema_version'],'CURSOR_SCHEMA_CHANGED')
  need(after['consume_after']==before['consume_after'],'QUARANTINE_BOUNDARY_CHANGE_UNQUALIFIED')
  need(dt.datetime.fromisoformat(after['updated_at'].replace('Z','+00:00'))>=dt.datetime.fromisoformat(before['updated_at'].replace('Z','+00:00')),'CURSOR_TIME_ROLLBACK')

def reject_legacy_source(r,facts,*,_verified_legacy=None):
 need(r.get('source_key',r['key']) not in facts['legacy_receipt_keys'],'LEGACY_RECEIPT_EFFECT_REPLAY')
 if _verified_legacy is None:
  old_ids=set(J(runtime.source_financial_root()/'s41_command_cursor.json')['processed_command_ids'])
  old_context=set(J(runtime.source_financial_root()/'context_consumer_checkpoint.json')['processed_keys'])
 else:old_ids,old_context=_verified_legacy
 need(not any(r.get('source_key',r['key'])==k or r.get('source_key',r['key']).startswith(k+'|attempt|') for k in facts['legacy_receipt_keys']),'LEGACY_ATTEMPT_REPLAY')
 def walk(v):
  if type(v) is dict:
   if any(v.get(k) in old_ids for k in ('command_id','manager_command_id')):raise ColdBlocked('OLD_PROCESSED_COMMAND_REPLAY')
   if v.get('idempotency_key') in old_context:raise ColdBlocked('OLD_PROCESSED_CONTEXT_REPLAY')
   for x in v.values():walk(x)
  elif type(v) is list:
   for x in v:walk(x)
 walk(r['source'])
 for table,e in r['books'].items():
  for row in parse_rows(e['data'].encode()):
   if table in ('commands','orders','fills'):
    need(all(row.get(k) not in old_ids for k in ('command_id','manager_command_id')),'OLD_PROCESSED_COMMAND_REPLAY')

def parse_rows(raw):
 need(not raw or raw.endswith(b'\n'),'INCOMPLETE_JSONL_TAIL')
 return [json.loads(line,object_pairs_hook=a.unique_object) for line in raw.splitlines() if line.strip()]

def reconcile(books,ledger,*,_verified_context=None):
 """Only recorded values are reconciled; prices, commission and PnL not computed."""
 if _verified_context is None:
  seed=J(runtime.source_financial_root()/'sleeves.json');epoch=authority_epoch();policy=authority_policy()
 else:seed,epoch,policy=_verified_context
 need(ledger['epoch_id']==epoch and ledger['schema_version']==seed['schema_version'],'LEDGER_IDENTITY_CONFLICT')
 need(set(ledger['sleeves'])==set(policy['risk_pct']),'SLEEVE_SET_CONFLICT')
 latest={}
 for row in books['positions']:
  tf=row['timeframe'];pid=row['position_id'];need(tf in policy['risk_pct'],'POSITION_TF_CONFLICT')
  old=latest.get(pid)
  if old:
   need(old['timeframe']==tf and old['side']==row['side'],'POSITION_REPARENTED')
   need(old['status']=='OPEN' and row['status']=='CLOSED','CLOSED_POSITION_REOPEN_OR_DUPLICATE')
  else:need(row['status']=='OPEN','POSITION_MISSING_OPEN_ANCESTOR')
  latest[pid]=row
 for name,field in [('fills','fill_id'),('orders','order_id'),('trades','trade_id')]:
  ids=[r[field] for r in books[name]];need(len(ids)==len(set(ids)),'DUPLICATE_FINANCIAL_ID:'+name)
 for t in books['trades']:
  need(t['position_id'] in latest and latest[t['position_id']]['status']=='CLOSED' and latest[t['position_id']]['timeframe']==t['timeframe'],'TRADE_POSITION_CONFLICT')
 need(len({t['position_id'] for t in books['trades']})==len(books['trades']),'DUPLICATE_POSITION_SETTLEMENT')
 for tf,s in ledger['sleeves'].items():
  need(s['timeframe']==tf and s['epoch_id']==epoch,'SLEEVE_OWNER_CONFLICT')
  need(a.money(s['initial_equity_usd'])==a.money(seed['sleeves'][tf]['initial_equity_usd']) and a.money(s['risk_pct_per_trade'])==a.money(policy['risk_pct'][tf]),'INITIAL_EQUITY_OR_RISK_CHANGED')
  own=[t for t in books['trades'] if t['timeframe']==tf];net=sum((a.money(t['net_pnl_usd']) for t in own),a.money(0))
  need(a.near(s['cumulative_realized_net_pnl_usd'],net) and a.near(s['current_equity_usd'],a.money(s['initial_equity_usd'])+net),'UNCONFIRMED_CAPITAL_OR_PNL')
  need(s['closed_trades_count']==len(own),'TRADE_COUNT_CONFLICT')
  opened=[p for p in latest.values() if p['timeframe']==tf and p['status']=='OPEN'];need(len(opened)<=1,'MULTIPLE_OWN_POSITIONS')
  need(s['open_position_id']==(opened[0]['position_id'] if opened else None),'OCCUPANCY_CONFLICT')
  need(a.near(s['open_position_risk_usd'],opened[0]['risk_amount_usd'] if opened else 0),'OCCUPANCY_RISK_CONFLICT')
  need(a.near(s['next_risk_budget_usd'],a.money(s['current_equity_usd'])*a.money(policy['risk_pct'][tf])/100),'RISK_BUDGET_CONFLICT')
 m=ledger['master'];total=sum((a.money(s['current_equity_usd']) for s in ledger['sleeves'].values()),a.money(0));net=sum((a.money(t['net_pnl_usd']) for t in books['trades']),a.money(0))
 need(a.near(m['master_current_equity_usd'],total) and a.near(m['master_realized_net_pnl_usd'],net),'MASTER_CAPITAL_CONFLICT')
 need(m['master_initial_equity_usd']==seed['master']['master_initial_equity_usd'],'MASTER_INITIAL_EQUITY_CHANGED')
 need(m['open_positions_count']==sum(p['status']=='OPEN' for p in latest.values()),'MASTER_OCCUPANCY_CONFLICT')
 need(a.near(m['master_open_risk_usd'],sum((a.money(s['open_position_risk_usd']) for s in ledger['sleeves'].values()),a.money(0))),'MASTER_RISK_CONFLICT')

class ColdValidator:
 def __init__(self,case,anchor_path,anchor_sha,extension=None):
  self.case=case_guard(case);self.anchor_path=Path(anchor_path);self.anchor_sha=anchor_sha;self.extension=extension
 def verify(self,minimum_seen=None):
  """Read-only coherent SH snapshot. Returns evidence, never execution authority."""
  with locked(self.case):
   try:return self._verify(minimum_seen)
   except ColdBlocked:raise
   except Exception as e:raise ColdBlocked('AUTHORITY_OR_SCHEMA_REJECTED:'+str(e)) from e
 def _verify(self,minimum_seen,*,_yield_writer=None,_run_without_lock=None):
  case=self.case;root=case/authority_root_rel();ar=root/'execution_commits_v1'
  # Capture immutable, pinned authority once and revalidate it before return.
  def read_immutable_inputs():
   ec,fh,_=a.reference();policy=authority_policy();epoch=authority_epoch()
   directory=runtime.source_financial_root()
   names=('sleeves.json','s41_command_cursor.json','context_consumer_checkpoint.json')
   blobs={name:(directory/name).read_bytes() for name in names}
   values={name:json.loads(raw,object_pairs_hook=a.unique_object) for name,raw in blobs.items()}
   return ec,fh,policy,epoch,directory,blobs,values
  inputs=_run_without_lock(read_immutable_inputs) if _run_without_lock else read_immutable_inputs()
  verified_ec,verified_fh,verified_policy,verified_epoch,legacy_dir,legacy_bytes,legacy_decoded=inputs
  verified_legacy=(set(legacy_decoded['s41_command_cursor.json']['processed_command_ids']),set(legacy_decoded['context_consumer_checkpoint.json']['processed_keys']))
  verified_reconcile=(legacy_decoded['sleeves.json'],verified_epoch,verified_policy)
  need(not (ar/'pending.json').exists(),'UNRESOLVED_PENDING_NO_AUTO_RECOVERY')
  need(not any(p.name.endswith(('.commit-tmp','.tmp')) for p in ar.rglob('*')),'UNRESOLVED_TEMP_AUTHORITY')
  need({p.name for p in (root/'books').iterdir()}=={'.writer.lock'}|{t+'.jsonl' for t in a.TABLES},'UNKNOWN_FINANCIAL_BOOK')
  from .verified_continuation import certified_prefix,certify
  cached,last_seen=certified_prefix(root,self.anchor_sha)
  if minimum_seen is None:minimum_seen=last_seen
  if cached is None:
   anchor,facts,boundary=(_run_without_lock(lambda:validate_anchor(case,self.anchor_path,self.anchor_sha)) if _run_without_lock else validate_anchor(case,self.anchor_path,self.anchor_sha))
  else:
   anchor,facts,boundary=cached['anchor'],cached['facts'],cached['boundary']
  immutable_books={m['path'] for m in verified_policy['state_members'] if '/books/' in m['path'] and Path(m['path']).name in {t+'.jsonl' for t in a.TABLES}}
  immutable_full={m['path'] for m in verified_policy['state_members'] if '/receipts/' in m['path'] or '/paper_epochs/' in m['path'] or m['path'].endswith(('/trading_contract.json','/books/.writer.lock'))}
  independent_domain_changes=[]
  mutable_docs={m['path'] for m in verified_policy['state_members'] if Path(m['path']).name in ('sleeves.json',)+CURSORS+('s41_recovery_open_barrier.json',)}
  # Existing bounded authority/path scope; every prefix/member check runs.
  # Cold validation is unchanged. Full admission repeats at scope entry/exit.
  with runtime.validated_path_reads() if cached is not None else contextlib.nullcontext():
   for m in verified_policy['state_members']:
    if _yield_writer is not None:_yield_writer()
    path=runtime.member_path(case,m['path']);need(path.is_file(),'LEGACY_MEMBER_MISSING:'+m['path'])
    if m['path'] in immutable_books:
     with path.open('rb') as f:raw=f.read(m['bytes'])
     need(len(raw)==m['bytes'] and H(raw)==m['sha256'],'LEGACY_BOOK_PREFIX_CHANGED:'+m['path'])
    elif m['path'] in immutable_full:
     need(path.stat().st_size==m['bytes'] and H(path.read_bytes())==m['sha256'],'PINNED_LEGACY_AUTHORITY_DRIFT:'+m['path'])
    elif m['path'] not in mutable_docs and (path.stat().st_size!=m['bytes'] or H(path.read_bytes())!=m['sha256']):
     independent_domain_changes.append(m['path'])
  if _yield_writer is not None:_yield_writer()
  head=(_run_without_lock(lambda:verified_ec.verify_committed_head(root,verified_epoch)) if _run_without_lock else verified_ec.verify_committed_head(root,verified_epoch));g=head['publication']['generation']
  if _yield_writer is not None:_yield_writer()
  need({p.name for p in (ar/'publications').iterdir()}=={f'{n}.json' for n in range(1,g+1)},'GENERATION_MARKER_SET_CONFLICT')
  # The existing validated continuation below supplies these values.
  # Preserve the original cold path and every source/prefix/final check.
  if cached is None:
   bookraw={t:(runtime.source_financial_root()/'books'/f'{t}.jsonl').read_bytes() for t in a.TABLES}
   docs={n:(runtime.source_financial_root()/n).read_bytes() for n in ('sleeves.json',)+CURSORS+('s41_recovery_open_barrier.json',)}
  else:
   # Keep the existing fresh RO-source/mount/member admission check here.
   # The full bytes below would otherwise be read only to be discarded.
   runtime.source_financial_root()
  extension_state=self.extension.begin() if self.extension else None
  if self.extension is not None and hasattr(self.extension,'_selection_without_lock'):
   self.extension._selection_without_lock=_run_without_lock
  fill_owners=dict(facts['fill_owner_receipt_bindings']);prev=boundary;keys={boundary['publication']['key']};heads={1:verified_ec.head_reference(boundary)};expected_receipts={Path(m['path']).name for m in verified_policy['state_members'] if '/receipts/' in m['path']}
  expected_receipts.add(H(boundary['publication']['key'].encode())+'.json');previous_witness=None
  start=1
  if cached is not None:
   bookraw=cached['bookraw'];docs=cached['docs'];extension_state=cached['extension_state'];fill_owners=cached['fill_owners'];prev=cached['prev'];keys=cached['keys'];heads=cached['heads'];expected_receipts=cached['expected_receipts'];previous_witness=cached['previous_witness'];start=cached['generation']+1
  for n in range(start,g+1):
   if _yield_writer is not None:_yield_writer()
   mark=ar/'publications'/f'{n}.json';r=verified_ec.decode_authority(mark,verified_epoch);pub=r['publication'];key=r['key']
   need(pub['generation']==n and type(pub['generation']) is int and r['schema']=='execution_commit_v3' and r['status']=='COMMITTED' and pub['epoch']==verified_epoch and r['epoch']==verified_epoch,'V3_SEQUENCE_OR_EPOCH_CONFLICT')
   receipt=ar/'receipts'/(H(key.encode())+'.json');need(mark.read_bytes()==receipt.read_bytes(),'MARKER_RECEIPT_CONFLICT')
   expected_receipts.add(receipt.name)
   h={'schema':verified_ec.HEAD_SCHEMA,'epoch':verified_epoch,'publication':pub,'receipt_sha256':H(receipt.read_bytes())}
   verified_ec._verify_receipt(h,ar,verified_epoch,head['publication']['history'])
   witness=(ar/'publication.witness').read_bytes()[(n-1)*176:n*176]
   need(witness==__import__('btc_ml.trading.intrabar_paper.publication_witness',fromlist=['record']).record(h,previous_witness),'FULL_WITNESS_CHAIN_CONFLICT');previous_witness=witness
   if n==1:
    need(verified_ec.head_reference(h)==anchor['boundary'],'BOUNDARY_HEAD_CONFLICT');continue
   need(key not in keys,'DUPLICATE_V3_KEY');keys.add(key)
   need(pub['parent']==verified_ec.head_reference(prev),'FORWARD_PARENT_CONFLICT')
   reject_legacy_source(r,facts,_verified_legacy=verified_legacy)
   if self.extension:self.extension.receipt(r,prev,head,ar,docs,extension_state)
   need(set(pub['scopes'])==set(verified_policy['risk_pct']),'FORWARD_SCOPE_SET_CONFLICT')
   need(all(type(s['version']) is int and s['version']>=0 for s in pub['scopes'].values()),'SCOPE_VERSION_TYPE_CONFLICT')
   old_scopes=prev['publication']['scopes'];changed_effect_tfs=set();touched=set()
   for table,e in r['books'].items():
    need(table in a.TABLES and type(e['offset']) is int and e['offset']==len(bookraw[table]),'BOOK_EFFECT_OFFSET_CONFLICT')
    need(e['prefix_sha256']==H(bookraw[table]),'BOOK_EFFECT_PREFIX_CONFLICT')
    additions=parse_rows(e['data'].encode())
    need(all(x.get('paper_epoch_id')==verified_epoch for x in additions),'FORWARD_BOOK_EPOCH_CONFLICT')
    if table in ('positions','orders','fills','trades'):
     need(all(x.get('timeframe') in verified_policy['risk_pct'] for x in additions),'EFFECT_TF_REQUIRED')
     changed_effect_tfs.update(x['timeframe'] for x in additions);touched.update(x['timeframe'] for x in additions)
    bookraw[table]+=e['data'].encode()
   args=r['source'].get('args') or []
   if args and isinstance(args[0],dict) and args[0].get('timeframe') in verified_policy['risk_pct']:touched.add(args[0]['timeframe'])
   if r['source'].get('kwargs',{}).get('timeframe') in verified_policy['risk_pct']:touched.add(r['source']['kwargs']['timeframe'])
   for name,e in r['documents'].items():
    need(name in docs,'DOCUMENT_FORWARD_CONTRACT_MISSING:'+name)
    if self.extension:docs[name]=self.extension.bridge(name,docs[name],e,r,extension_state)
    need(e['before']==H(docs[name]),'DOCUMENT_BEFORE_CHAIN_CONFLICT')
    new=e['data'].encode();json.loads(new,object_pairs_hook=a.unique_object)
    if name in CURSORS or name=='s41_recovery_open_barrier.json':
     if self.extension:self.extension.cursor(name,json.loads(docs[name]),json.loads(new),r,extension_state)
     else:monotonic_cursor(name,json.loads(docs[name]),json.loads(new))
    docs[name]=new
   ledger=json.loads(docs['sleeves.json']);reconcile({t:parse_rows(raw) for t,raw in bookraw.items()},ledger,_verified_context=verified_reconcile)
   for tf,s in pub['scopes'].items():
    old=old_scopes[tf];state=ledger['sleeves'][tf];changed=verified_ec.canonical(old['sleeve'])!=verified_ec.canonical(state)
    need(not changed or tf in touched,'UNRELATED_TF_CAPITAL_TRANSFER')
    advance=int(changed or tf in changed_effect_tfs)
    expected={'version':old['version']+advance,'sleeve':state,'last_change':{'generation':n,'receipt_key':key} if advance else old['last_change']}
    need(s==expected,'SCOPE_FORWARD_VERSION_OR_OWNERSHIP_CONFLICT:'+tf)
   expected_files={**{'books/'+t+'.jsonl':identity(raw) for t,raw in bookraw.items()},'sleeves.json':identity(docs['sleeves.json'])}
   need(pub['files']==expected_files,'PUBLICATION_EFFECT_COVERAGE_CONFLICT')
   need(pub['history']==verified_fh.plan(prev['publication']['history'],verified_fh.receipt_leaf(r))[0],'MMR_FORWARD_PLAN_CONFLICT')
   # Exact occupancy assertion and each fill's same-receipt position ancestry.
   positions={}
   for x in parse_rows(bookraw['positions']):positions[x['position_id']]=x
   occupancy={tf:x['position_id'] for tf in verified_policy['risk_pct'] for x in positions.values() if x['timeframe']==tf and x['status']=='OPEN'}
   before_positions={}
   for x in parse_rows((case/authority_root_rel()/'books/positions.jsonl').read_bytes()[:pub['files']['books/positions.jsonl']['bytes']-len(r['books'].get('positions',{}).get('data','').encode())]):before_positions[x['position_id']]=x
   before_occ={tf:x['position_id'] for tf in verified_policy['risk_pct'] for x in before_positions.values() if x['timeframe']==tf and x['status']=='OPEN'}
   need(r['occupancy_after']==occupancy and r['occupancy_before']==before_occ,'RECEIPT_OCCUPANCY_CONFLICT')
   effect_positions=parse_rows(r['books'].get('positions',{}).get('data','').encode())
   for fill in parse_rows(r['books'].get('fills',{}).get('data','').encode()):
    need(fill['action'] in ('ENTRY','EXIT'),'FILL_ACTION_CONFLICT')
    tf=fill['timeframe'];status='OPEN' if fill['action']=='ENTRY' else 'CLOSED'
    # A complete same-receipt fixture round trip can contain both OPEN/CLOSED;
    # without intermediate occupancy the original one-callback contract is not proven.
    owner=r['occupancy_after' if fill['action']=='ENTRY' else 'occupancy_before'].get(tf)
    need(owner is not None and any(x['position_id']==owner and x['timeframe']==tf and x['status']==status for x in effect_positions),'FORWARD_FILL_OWNER_CONFLICT')
    need(fill.get('position_id',owner)==owner,'FORWARD_FILL_EXPLICIT_OWNER_CONFLICT')
    need(fill['fill_id'] not in fill_owners,'DUPLICATE_FINANCIAL_FILL_EFFECT')
    fill_owners[fill['fill_id']]=owner
   all_books={t:parse_rows(raw) for t,raw in bookraw.items()}
   orders={x['order_id']:x for x in all_books['orders']}
   for fill in all_books['fills']:
    order=orders.get(fill['order_id']);need(order is not None and order['timeframe']==fill['timeframe'] and order['action']==fill['action'],'FILL_ORDER_PARENT_CONFLICT')
   for pid,pos in positions.items():
    owned=[x for x in all_books['fills'] if fill_owners.get(x['fill_id'])==pid]
    need(sorted(x['action'] for x in owned)==(['ENTRY','EXIT'] if pos['status']=='CLOSED' else ['ENTRY']),'POSITION_FILL_COVERAGE_CONFLICT')
    if pos.get('entry_fill_id') is not None:need(any(x['fill_id']==pos['entry_fill_id'] and x['action']=='ENTRY' for x in owned),'POSITION_ENTRY_FILL_ANCESTOR_CONFLICT')
   need({x['position_id'] for x in all_books['trades']}=={pid for pid,pos in positions.items() if pos['status']=='CLOSED'},'CLOSED_POSITION_TRADE_COVERAGE_CONFLICT')
   prev=h;heads[n]=verified_ec.head_reference(h)
  if _yield_writer is not None:
   _yield_writer()
   # The writer could have run between chunks; repeat structural guards.
   case_guard(case)
   need(not (ar/'pending.json').exists(),'UNRESOLVED_PENDING_NO_AUTO_RECOVERY')
   need(not any(p.name.endswith(('.commit-tmp','.tmp')) for p in ar.rglob('*')),'UNRESOLVED_TEMP_AUTHORITY')
   need({p.name for p in (root/'books').iterdir()}=={'.writer.lock'}|{t+'.jsonl' for t in a.TABLES},'UNKNOWN_FINANCIAL_BOOK')
  need({p.name for p in (ar/'receipts').iterdir()}==expected_receipts,'UNINDEXED_OR_MISSING_RECEIPT')
  need(verified_ec.head_reference(prev)==verified_ec.head_reference(head),'HEAD_CHAIN_TIP_CONFLICT')
  for t,raw in bookraw.items():need((root/'books'/f'{t}.jsonl').read_bytes()==raw,'UNRECEIPTED_BOOK_TAIL:'+t)
  for n,raw in docs.items():
   actual=(root/n).read_bytes()
   if self.extension:self.extension.final_document(n,raw,actual,extension_state)
   else:need(actual==raw,'UNRECEIPTED_DOCUMENT_OR_CURSOR:'+n)
  if minimum_seen is not None:
   need(type(minimum_seen.get('generation')) is int and minimum_seen['generation'] in heads and minimum_seen==heads[minimum_seen['generation']],'LAST_SEEN_ROLLBACK_OR_FORK')
  certify(root,self.anchor_sha,{'generation':g,'anchor':anchor,'facts':facts,'boundary':boundary,'bookraw':bookraw,'docs':docs,'extension_state':extension_state,'fill_owners':fill_owners,'prev':prev,'keys':keys,'heads':heads,'expected_receipts':expected_receipts,'previous_witness':previous_witness})
  def revalidate_immutable_inputs():
   need(authority_policy()==verified_policy and authority_epoch()==verified_epoch,'AUTHORITY_CHANGED_DURING_VALIDATION')
   a.reference()
   need(all((legacy_dir/name).read_bytes()==raw for name,raw in legacy_bytes.items()),'LEGACY_SOURCE_CHANGED_DURING_VALIDATION')
  if _run_without_lock:_run_without_lock(revalidate_immutable_inputs)
  else:revalidate_immutable_inputs()
  return {'status':'PASS_RESEARCH_COLD_FORWARD_VALIDATION','epoch':verified_epoch,'head':verified_ec.head_reference(head),'legacy_receipts':16,'legacy_immutable_prefix_preserved':True,'generations_checked':g,'verified_ack_index':copy.deepcopy(extension_state['acks']) if extension_state is not None else {},'new_generations_checked':max(0,g-start+1),'validation_mode':'COLD_FULL' if cached is None else 'ANCHORED_CONTINUATION','legacy_positions':5,'legacy_fills':10,'historical_master_equity_usd':verified_policy['master_equity_usd'],'historical_net_pnl_usd':verified_policy['recorded_net_pnl_usd'],'current_master_equity_usd':json.loads(docs['sleeves.json'])['master']['master_current_equity_usd'],'new_financial_operations_authorized':False,'genuine_engine_forward_execution':'NOT_PROVEN','canonical_wiring':'NOT_IMPLEMENTED','independent_nonfinancial_domain_changes':independent_domain_changes,'independent_market_command_readiness':'NOT_PROVEN'}
 def check_replay(self,key=None,command_id=None,context_key=None):
  self.verify();facts=legacy_image()
  if key in facts['legacy_receipt_keys'] or any(key and key.startswith(k+'|attempt|') for k in facts['legacy_receipt_keys']):raise ColdBlocked('OLD_RECEIPT_REPLAY_BLOCKED_NO_ACK_GRANTED')
  if command_id in J(runtime.source_financial_root()/'s41_command_cursor.json')['processed_command_ids']:raise ColdBlocked('OLD_COMMAND_REPLAY_BLOCKED_NO_ACK_GRANTED')
  if context_key in J(runtime.source_financial_root()/'context_consumer_checkpoint.json')['processed_keys']:raise ColdBlocked('OLD_CONTEXT_REPLAY_BLOCKED_NO_ACK_GRANTED')
  raise ColdBlocked('NO_NEW_OPERATION_AUTHORITY')
