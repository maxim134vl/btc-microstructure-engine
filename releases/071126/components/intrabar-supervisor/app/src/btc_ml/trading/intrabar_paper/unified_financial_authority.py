"""Research-only integration seam, original callers/locks/protocol are retained."""
from pathlib import Path
import json,types
from . import financial_authority_runtime as runtime
from . import execution_commit as ec

def roots(root,epoch):
 from . import cold_forward_guard as c
 root=Path(root).resolve();runtime.activate(root);case=c.case_guard(runtime.case_root())
 c.need(epoch==c.EPOCH and root==case/c.ROOT_REL,'UNQUALIFIED_FINANCIAL_ROOT')
 return c,case,root

def binding(root,epoch):
 c,case,root=roots(root,epoch);path=runtime.binding_path()
 c.need(path.is_file(),'COLD_TRUST_BINDING_MISSING');v=c.J(path)
 c.need(v['epoch']==epoch and v['mode']==runtime.binding_mode(),'COLD_TRUST_BINDING_CONFLICT')
 if runtime.working_profile():
  c.need(v.get('working_provenance')==runtime.admission_provenance(),'WORKING_BINDING_PROVENANCE_CONFLICT')
  c.need(c.J(Path(v['anchor'])).get('working_provenance')==runtime.admission_provenance(),'WORKING_ANCHOR_PROVENANCE_CONFLICT')
 return c,case,root,Path(v['anchor']),v['anchor_sha256']

def immutable_preflight(root,epoch):
 c,case,root=roots(root,epoch);c.legacy_image()
 for m in c.P['state_members']:
  p=runtime.member_path(case,m['path']);c.need(p.is_file(),'LEGACY_MEMBER_MISSING:'+m['path'])
  immutable=('/receipts/' in m['path'] or '/paper_epochs/' in m['path'] or m['path'].endswith(('/trading_contract.json',)))
  if '/books/' in m['path'] or immutable:
   with p.open('rb') as f:raw=f.read(m['bytes'])
   c.need(len(raw)==m['bytes'] and c.H(raw)==m['sha256'],'LEGACY_IMMUTABLE_DRIFT:'+m['path'])
   if immutable:c.need(p.stat().st_size==m['bytes'],'LEGACY_FULL_MEMBER_CHANGED')
 return c,case,root

def preconstructor(root,epoch):
 c,case,root=immutable_preflight(root,epoch)
 # Before original constructor can create any new financial files or recover.
 if not runtime.binding_path().exists():
  if runtime.working_profile():
   from .working_admission import verify_initial
   verify_initial(root,runtime.authority().config)
  c.need(runtime.authority().config['bootstrap_authorized'],'LEGACY_BOOTSTRAP_NOT_AUTHORIZED')
  c.a.verify_legacy(case,c.P)
  ar=root/'execution_commits_v1'
  if (ar/'pending.json').exists():
   c.need((case/'control/admission_plan.json').is_file(),'UNKNOWN_INITIAL_PENDING')
   c.need((ar/'pending.json').read_bytes()==(case/'control/admission_plan.json').read_bytes(),'FOREIGN_INITIAL_PENDING')
 else:
  c,_,_,anchor,pin=binding(root,epoch);c.validate_anchor(case,anchor,pin)
  p=root/'execution_commits_v1/pending.json'
  if p.exists():validate_pending(root,epoch)


def validate_pending(root,epoch):
 c,case,root,anchor,pin=binding(root,epoch);immutable_preflight(root,epoch)
 ar=root/'execution_commits_v1';intent=ec.decode_authority(ar/'pending.json',epoch)
 c.need(intent.get('schema')=='execution_commit_v3' and intent.get('status')=='INTENT','PENDING_SCHEMA_UNQUALIFIED')
 source=intent['source'];method=source.get('method')
 allowed={'cursor_ack_v1','apply_s41_manager_command','process_context_event','update_from_trade','update_bbo_from_market','quarantine_barrier_v1'}
 c.need(method in allowed,'UNKNOWN_PENDING_SOURCE')
 c.reject_legacy_source(intent,c.legacy_image())
 pub=intent['publication'];ref=pub.get('parent');c.need(ref is not None and pub['generation']==ref['generation']+1,'PENDING_PARENT_INVALID')
 parent_receipt=ec.decode_authority(ar/'publications'/f"{ref['generation']}.json",epoch)
 parent={'schema':ec.HEAD_SCHEMA,'epoch':epoch,'publication':parent_receipt['publication'],'receipt_sha256':ec.digest((ar/'publications'/f"{ref['generation']}.json").read_bytes())}
 c.need(ec.head_reference(parent)==ref,'PENDING_PARENT_BINDING_CONFLICT')
 from .financial_history import verify_storage,verify_member,receipt_leaf,plan
 verify_storage(ar/'history.mmr',parent['publication']['history'],allow_tail=True)
 verify_member(ar/'history.mmr',parent['publication']['history'],ref['generation'],receipt_leaf(parent_receipt))
 from .publication_witness import recovery_plan
 successor={"schema":ec.HEAD_SCHEMA,"epoch":epoch,"publication":pub,"receipt_sha256":ec.digest(ec.encode_authority({**intent,'status':'COMMITTED'}))}
 recovery_plan(ar/'publication.witness',parent,successor)
 c.need(pub['history']==plan(parent['publication']['history'],receipt_leaf(intent))[0],'PENDING_HISTORY_PLAN_CONFLICT')
 c.need(set(intent['books'])<=set(ec.BOUND_TABLES) and set(intent['documents'])<={'sleeves.json','context_consumer_checkpoint.json','s41_command_cursor.json','s41_recovery_open_barrier.json'},'PENDING_EFFECT_SCHEMA_UNKNOWN')
 c.need('s41_recovery_open_barrier.json' not in intent['documents'] or method=='quarantine_barrier_v1','QUARANTINE_PENDING_OWNER_REQUIRED')
 expected=dict(parent['publication']['files'])
 for t,e in intent['books'].items():
  rel='books/'+t+'.jsonl';old=expected[rel];c.need(type(e['offset']) is int and e['offset']==old['bytes'] and e['prefix_sha256']==old['sha256'],'PENDING_BOOK_PARENT_CONFLICT')
  path=root/rel;initial=path.read_bytes()[:e['offset']];suffix=path.read_bytes()[e['offset']:];new=e['data'].encode()
  c.need(c.H(initial)==e['prefix_sha256'] and new.startswith(suffix),'PENDING_BOOK_TAIL_CONFLICT');expected[rel]=c.identity(initial+new)
 for n,e in intent['documents'].items():
  actual=(root/n).read_bytes();new=e['data'].encode();c.need(c.H(actual) in {e['before'],c.H(new)},'PENDING_DOCUMENT_UNEXPECTED_STATE')
  if n in ec.BOUND_DOCUMENTS:expected[n]=c.identity(new)
 c.need(pub['files']==expected,'PENDING_CONSTITUENT_PLAN_CONFLICT')
 if method=='cursor_ack_v1':
  from .cursor_ack import verify_ack_body
  verify_ack_body(intent,parent,parent,ar)
 if method=='quarantine_barrier_v1':
  from .quarantine_barrier import parent_documents,verify_transition
  docs,state=parent_documents(root,ref);verify_transition(intent,parent,parent,ar,docs,state)
  c.need(pub['files']==ec.constituent_identities(root),'QUARANTINE_PENDING_FINANCIAL_DRIFT')
 return intent

def seal_locked(books,plan):
 c,case,root=roots(books.root.parent,books.paper_epoch_id)
 c.need(books.owns_exclusive(),'SEAL_REQUIRES_NATIVE_EX')
 head=ec._verify_committed_head_raw(root,books.paper_epoch_id)
 c.need(head['epoch']==books.paper_epoch_id and head['publication']['generation']==1 and head['publication']['parent'] is None,'SEAL_REQUIRES_EXACT_INITIAL_BOUNDARY')
 c.need(head['publication']==plan['publication'],'BOOTSTRAP_READBACK_CONFLICT')
 c.a.validate_plan(plan,root,c.P,c.a.verify_legacy(case,c.P))
 anchor=runtime.anchor_path()
 v={'schema':'cold_legacy_trust_anchor_v1','epoch':c.EPOCH,'policy_sha256':runtime.policy_sha(),'boundary':ec.head_reference(head),'boundary_receipt_sha256':head['receipt_sha256'],'first_witness_sha256':c.H((root/'execution_commits_v1/publication.witness').read_bytes()[:176]),'authority':'RESEARCH_METADATA_ONLY','entry_allowed':False}
 if runtime.working_profile():
  v['authority']=runtime.binding_mode();v['working_provenance']=runtime.admission_provenance()
 expected_seal=(json.dumps(v,sort_keys=True,indent=2)+'\n').encode()
 if anchor.exists():c.need(anchor.is_file() and anchor.read_bytes()==expected_seal,'EXISTING_SEAL_IDENTITY_CONFLICT_NO_REPIN')
 else:ec.atomic_bytes(anchor,expected_seal)
 c.need(anchor.read_bytes()==expected_seal,'SEAL_READBACK_CONFLICT')
 # Existing native validators bind exact committed receipt, MMR and first witness.
 c.validate_anchor(case,anchor,c.H(expected_seal))
 path=runtime.binding_path()
 c.need(path!=anchor,'SEAL_BINDING_PATH_ALIAS')
 expected_binding=(json.dumps(dict({'mode':runtime.binding_mode(),'epoch':c.EPOCH,'anchor':str(anchor),'anchor_sha256':c.H(expected_seal)},**({'working_provenance':runtime.admission_provenance()} if runtime.working_profile() else {})),sort_keys=True)+'\n').encode()
 if path.exists():c.need(path.is_file() and path.read_bytes()==expected_binding,'EXISTING_BINDING_IDENTITY_CONFLICT')
 else:ec.atomic_bytes(path,expected_binding)
 c.need(path.read_bytes()==expected_binding,'BINDING_READBACK_CONFLICT')

def initialize_or_validate(books):
 root=books.root.parent;epoch=books.paper_epoch_id;c,case,root=roots(root,epoch)
 from .verified_continuation import discard
 discard(root)
 c.need(books.owns_exclusive(),'COLD_INIT_REQUIRES_EX')
 if not runtime.binding_path().exists():
  if runtime.working_profile():
   from .working_admission import verify_initial
   verify_initial(root,runtime.authority().config)
  c.need(runtime.authority().config['bootstrap_authorized'],'LEGACY_BOOTSTRAP_NOT_AUTHORIZED')
  _,_,_,plan=c.a.prepare(case)
  if books.commit.pending.exists():c.need(books.commit.pending.read_bytes()==ec.encode_authority(plan),'UNKNOWN_BOOTSTRAP_PENDING')
  elif not (books.commit.root/'head.json').exists():ec.atomic_bytes(books.commit.pending,ec.encode_authority(plan))
  if books.commit.pending.exists():books.commit.materialize(plan)
  seal_locked(books,plan)
 elif books.commit.pending.exists():
  validate_pending(root,epoch)
  if ec.decode_authority(books.commit.pending,epoch)['source']['method']=='cursor_ack_v1':ack_owner(books).recover_ack()
  else:books.commit.recover()
 check_locked(root,epoch)

def check_locked(root,epoch):
 c,case,root,anchor,pin=binding(root,epoch)
 from .cursor_ack import GuardExtension
 return c.ColdValidator(case,anchor,pin,extension=GuardExtension())._verify(None)

def ack_owner(books):
 c,case,root,anchor,pin=binding(books.root.parent,books.paper_epoch_id)
 from .cursor_ack import AckOwner
 return AckOwner(books,anchor,pin)

def completion_reference(books,command):
 key=books.paper_epoch_id+'|apply_s41_manager_command|'+command['command_id'];p=books.commit.receipt_path(key)
 if not p.exists():return None,None
 saved=books.commit.load(p)
 if saved.get('schema')!='execution_commit_v3' or not saved.get('terminal') or saved.get('status')!='COMMITTED':return None,None
 ec_head=ec.verify_committed_head(books.root.parent,books.paper_epoch_id)
 prior={'schema':ec.HEAD_SCHEMA,'epoch':books.paper_epoch_id,'publication':saved['publication'],'receipt_sha256':ec.digest(p.read_bytes())}
 ec.authenticated_prior(ec_head,ec.head_reference(prior),books.root.parent,books.paper_epoch_id)
 if not ec.same_association(saved['source'],{'method':'apply_s41_manager_command','args':[command],'kwargs':{}}):raise RuntimeError('COMMAND_COMPLETION_ASSOCIATION_CONFLICT')
 return ec.head_reference(prior),saved['result']

def confirm_consumer(consumer,command,result,completion_source=None):
 books=consumer.engine.books
 with books.exclusive():
  check_locked(books.root.parent,books.paper_epoch_id);owner=ack_owner(books)
  ref,saved=completion_reference(books,command)
  outcome=saved if ref is not None else result
  confirmed=owner.publish(command,outcome,economic_reference=ref,completion_source=completion_source)
  if confirmed['state'] not in {'ACK_COMMITTED','ALREADY_PROCESSED','ALREADY_PROCESSED_LEGACY'}:raise RuntimeError('ACK_RESULT_NOT_TERMINAL')
  consumer._state=consumer._load()
  return confirmed

def already_processed(consumer,command):
 books=consumer.engine.books
 with books.exclusive():
  check_locked(books.root.parent,books.paper_epoch_id);owner=ack_owner(books)
  state=owner.lookup(command)
  if state['state'].startswith('ALREADY_PROCESSED'):return True
  ref,result=completion_reference(books,command)
  if ref is not None:
   confirm_consumer(consumer,command,result);return True
  return False

def save_observation_checkpoint(path,data):
 # This is the real ContextEventConsumer.save path; use original native lock
 # without initializing another engine or inventing an observation journal.
 import fcntl
 from .cursor_ack import observe_only
 new=json.loads(data);epoch=new['paper_epoch_id']
 c,case,root=roots(path.parent,epoch)
 with (root/'books/.writer.lock').open('rb') as lock:
  fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
  try:
   check_locked(root,epoch);old=json.loads(path.read_bytes());observe_only(old,new);ec.atomic_bytes(path,data)
  finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
