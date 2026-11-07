"""Bounded, observational admission records; never an execution authority.

None means NOT_EVALUATED/NOT_OBSERVABLE. No payload bodies or exception text.
Existing lock objects are delegated unchanged; telemetry errors are suppressed.
"""
from collections import deque
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import dis, hashlib, json, os, threading, time

REVALIDATION_KEYS = ('ws','market_session','public_session','generation','last_id')

class AdmissionDiagnostics:
    MAX_RECORD_BYTES = 32768
    RECORDS_PER_SEGMENT = 128
    def __init__(self, root):
        self.root = Path(root)/'admission_diagnostics_v1'
        self.sequence = 0; self.failures = 0; self.local = threading.local()
        self.locks = deque(maxlen=24); self.bbo_observation = None; self.overlap_observation = None
        self.capture_anchor_verified = None; self.capture_range_verified = None
        self.execution_owner = None; self.segment_records = 0; self.latest = None; self.manifest_baseline_sha=None
    def put(self, **values):
        record = getattr(self.local, 'record', None)
        if record is not None: record.update(values)
    def block(self, reason):
        self.put(reason=reason)
    def evidence(self, resume, reason=None, **values):
        self.put(**self.snapshot(resume,now=values.get('guard_now_ms')), **values)
        if reason: self.block(reason)
    def snapshot(self, f, now=None):
        p=f.processor; s=p.state; now=time.time_ns()/1e6 if now is None else now
        ws=f.last_ws; bbo=f.bbo; data=(bbo['payload'].get('data') or bbo['payload']) if bbo else {}
        E=data.get('E'); T=data.get('T'); age=now-int(E or 0) if bbo else None
        worker=f.worker; owner=self.execution_owner; handle=getattr(owner,'_handle',None)
        observed=self.bbo_observation
        return dict(convergence_worker_alive=bool(worker and worker.is_alive()),
            capture_authority_owned=getattr(f.convergence_lock,'owner',None)==threading.get_ident(), capture_authority_owner_thread=getattr(f.convergence_lock,'owner',None),
            capture_error=bool(f.capture_failure or f.last_capture_error),
            capture_error_digest=hashlib.sha256(str(f.capture_failure or f.last_capture_error).encode()).hexdigest() if f.capture_failure or f.last_capture_error else None,
            rest_range_verified=self.capture_range_verified, anchor_verified=self.capture_anchor_verified,
            contiguous_range=self.capture_range_verified, verified_count=f.count,
            high_watermark_id=f.last_id, high_watermark_T=f.last_T,
            high_watermark_age_ms=now-f.last_T if f.last_T is not None else None,
            current_market_session_id=p.market_connection_session_id, overlap_market_session_id=f.session,
            overlap_event_id=ws.get('a') if ws else None, overlap_event_T=ws.get('T') if ws else None,
            overlap_event_age_ms=now-int(ws['T']) if ws else None,
            overlap_matches_verified_row=bool(ws and int(ws['a'])==f.last_id),
            overlap_exists=bool(ws),bbo_exists=bool(bbo),
            market_session_matches=bool(ws and f.session==p.market_connection_session_id),
            public_session_matches=bool(bbo and bbo.get('session')==p.public_connection_session_id),
            market_fresh=bool(ws and 0<=now-int(ws['T'])<=f.engine.cfg.max_agg_trade_age_ms),
            overlap_generation_current=(self.overlap_observation['generation']==p.reconnect_generation) if ws and self.overlap_observation and self.overlap_observation['object_id']==id(ws) else None,
            reconnect_generation=p.reconnect_generation,
            current_public_session_id=p.public_connection_session_id, bbo_session_id=bbo.get('session') if bbo else None,
            bbo_event_E=E,bbo_event_T=T,bbo_local_receive=bbo.get('received_at') if bbo else None,
            bbo_age_ms=age, bbo_fresh=(0<=age<=f.engine.cfg.max_bbo_age_ms) if age is not None else False,
            bbo_generation_current=(observed['generation']==p.reconnect_generation) if observed and bbo and observed['object_id']==id(bbo) else None,
            bbo_object_id=id(bbo) if bbo else None, bbo_callback_count=f.bbo_callback_count,
            bbo_callback_last=observed, market_connected=s.market_ws_connected, public_connected=s.public_ws_connected,
            websocket_connected=s.websocket_connected, unresolved_gap=s.unresolved_gap,
            pending_commit=(f.engine.epoch_root/'execution_commits_v1/pending.json').exists(),
            execution_lock_valid=bool(handle and not handle.closed) if owner else None,
            execution_lock_observation='RETAINED_ACQUIRED_HANDLE' if owner else 'NOT_OBSERVABLE_IN_DIRECT_CLASS_FIXTURE',
            locks=list(self.locks), admitted=f.admitted, complete=f.complete,
            thresholds=dict(max_bbo_age_ms=f.engine.cfg.max_bbo_age_ms,max_agg_trade_age_ms=f.engine.cfg.max_agg_trade_age_ms))
    def revalidation(self, before, after, phase):
        changed=[] if after is None else [k for k in REVALIDATION_KEYS if after[k]!=before[k]]
        self.put(revalidation_phase=phase, revalidation_changed_keys=changed,
            session_revalidated_after_lock=after is not None and not changed,
            market_session_unchanged=after is not None and after['market_session']==before['market_session'],
            public_session_unchanged=after is not None and after['public_session']==before['public_session'],
            high_watermark_unchanged_or_advanced=after is not None and after['last_id']>=before['last_id'],
            revalidation_before={k:before[k] for k in ('market_session','public_session','generation','last_id')},
            revalidation_after={k:after[k] for k in ('market_session','public_session','generation','last_id')} if after else None)
        if after is not None and changed:
            key=changed[0]
            self.block({'ws':'BLOCK_OVERLAP_CHANGED','market_session':'BLOCK_MARKET_SESSION_CHANGED',
                'public_session':'BLOCK_PUBLIC_SESSION_CHANGED','generation':'BLOCK_GENERATION_CHANGED',
                'last_id':'BLOCK_HIGH_WATERMARK_CHANGED'}[key])
    def set_manifest_baseline(self, reader, path):
        self.manifest_baseline_sha=reader(path)
    def overlap_stored(self, f):
        self.overlap_observation=dict(object_id=id(f.last_ws),generation=f.processor.reconnect_generation,
            published_ns=time.monotonic_ns(),session=f.session)
    def bbo_stored(self, f):
        self.bbo_observation=dict(stored=True,object_id=id(f.bbo),generation=f.processor.reconnect_generation,
            published_ns=time.monotonic_ns(),thread=threading.get_ident())
    def snapshot_verified(self, snapshot, expected):
        self.put(committed_snapshot_sha_match=snapshot['snapshot_sha256']==expected['snapshot_sha256'],
            books_sha_match={k:v for k,v in snapshot['members'].items() if k.startswith('books/')}=={k:v for k,v in expected['members'].items() if k.startswith('books/')},
            position_set_match=snapshot['open_positions']==expected['open_positions'], receipts_match=snapshot['receipts']==expected['receipts'], epoch_match=True,
            pending_commit=snapshot['pending_commit'])
    def publish(self, publisher, path, proof):
        self.put(proof_write_attempted=True,proof_manifest_sha256=proof.get('manifest_sha256'),manifest_sha_match=(proof.get('manifest_sha256')==self.manifest_baseline_sha) if self.manifest_baseline_sha is not None else None)
        try:
            publisher(path, proof)
        except BaseException as exc:
            tb=exc.__traceback__; phase=None; created=None
            while tb:
                frame=tb.tb_frame; name=frame.f_code.co_name
                if name=='atomic_bytes':
                    created='f' in frame.f_locals
                    attrs=[i.argval for i in dis.get_instructions(frame.f_code) if i.offset<=tb.tb_lasti and i.opname in ('LOAD_ATTR','LOAD_METHOD','LOAD_GLOBAL')]
                    called=next((a for a in reversed(attrs) if a in ('fsync','flush','write','replace','mkdir','open')),None)
                    phase={'fsync':'FILE_FSYNC','flush':'FILE_FLUSH','write':'FILE_WRITE','replace':'RENAME','mkdir':'MKDIR','open':'TEMP_OPEN'}.get(called)
                if name=='sync_dir':
                    phase='DIRECTORY_FSYNC' if 'fd' in frame.f_locals else 'DIRECTORY_OPEN'
                tb=tb.tb_next
            self.put(proof_failure_phase=phase or 'PUBLISHER_UNKNOWN',proof_temp_created=created,
                proof_fsync_success=True if phase in ('RENAME','DIRECTORY_FSYNC','DIRECTORY_OPEN') else (False if phase=='FILE_FSYNC' else None),
                proof_rename_success=True if phase in ('DIRECTORY_FSYNC','DIRECTORY_OPEN') else (False if phase=='RENAME' else None),
                proof_dir_fsync_success=False if phase=='DIRECTORY_FSYNC' else None,
                proof_exception_type=type(exc).__name__,proof_errno=getattr(exc,'errno',None))
            self.block('BLOCK_PROOF_DURABILITY_FAILED'); raise
        self.put(proof_temp_created=True,proof_fsync_success=True,proof_rename_success=True,proof_dir_fsync_success=True)
        # Read-back is an observation, never a new admission condition.
        try:
            envelope=json.loads(Path(path).read_bytes()); raw=envelope['payload']
            self.put(proof_readback_sha_match=hashlib.sha256(raw.encode()).hexdigest()==envelope['sha256'] and json.loads(raw)==proof)
        except Exception as exc: self.put(proof_readback_sha_match=None,proof_readback_exception_type=type(exc).__name__)
    def emit(self, record):
        self.latest=record
        try:
            raw=json.dumps(record,sort_keys=True,separators=(',',':')).encode()+b'\n'
            if len(raw)>self.MAX_RECORD_BYTES:
                # Payloads cannot grow the record. Retain all guard fields; trim only lock detail.
                record={**record,'locks':[],'record_lock_detail_truncated':True}
                raw=json.dumps(record,sort_keys=True,separators=(',',':')).encode()+b'\n'
            if len(raw)>self.MAX_RECORD_BYTES: raise ValueError('TELEMETRY_RECORD_BOUND')
            self.root.mkdir(parents=True,exist_ok=True)
            path=self.root/'attempts.jsonl'
            if self.segment_records>=self.RECORDS_PER_SEGMENT or (path.exists() and path.stat().st_size+len(raw)>self.RECORDS_PER_SEGMENT*self.MAX_RECORD_BYTES):
                os.replace(path,self.root/'attempts.previous.jsonl'); self.segment_records=0
            with path.open('ab') as stream: stream.write(raw)
            self.segment_records+=1; self.latest=record
        except Exception: self.failures+=1

class ObservedLock:
    """Delegate exact RLock calls; scalar owner and fixed deque are observational."""
    def __init__(self, lock, diagnostic, name):
        self.lock=lock;self.diagnostic=diagnostic;self.name=name;self.owner=None;self.depth=0
    def acquire(self,*args,**kwargs):
        start=time.monotonic_ns(); result=self.lock.acquire(*args,**kwargs)
        acquired=time.monotonic_ns()
        self.diagnostic.locks.append(dict(lock=self.name,operation='acquire',thread=threading.get_ident(),
            owner_before=self.owner,wait_start_ns=start,acquired_ns=acquired if result else None,wait_ns=acquired-start,acquired=bool(result)))
        if result: self.owner=threading.get_ident();self.depth+=1
        return result
    def release(self):
        self.depth-=1
        if not self.depth:self.owner=None
        self.lock.release()
        self.diagnostic.locks.append(dict(lock=self.name,operation='release',thread=threading.get_ident(),released_ns=time.monotonic_ns()))
    def __enter__(self):return self.acquire()
    def __exit__(self,*args):self.release()

def diagnostic_attempt(method):
    @wraps(method)
    def observed(self,*args,**kwargs):
        d=self.diagnostic;d.sequence+=1
        record=dict(timestamp_UTC=datetime.now(timezone.utc).isoformat(),attempt_sequence=d.sequence,
            admission_lock_acquired=None,session_revalidated_after_lock=None,market_session_unchanged=None,
            public_session_unchanged=None,high_watermark_unchanged_or_advanced=None,
            proof_write_attempted=False,proof_temp_created=None,proof_fsync_success=None,
            proof_rename_success=None,proof_dir_fsync_success=None,proof_readback_sha_match=None,
            manifest_valid=True,manifest_sha_match=None,committed_snapshot_sha_match=None,epoch_match=None,books_sha_match=None,position_set_match=None,receipts_match=None,
            reason=None,return_value=None)
        d.local.record=record
        try:
            d.evidence(self)
            result=method(self,*args,**kwargs); record['return_value']=result
            if not result and not record['reason']:record['reason']='BLOCK_EXECUTION_MARKET_NOT_READY'
            return result
        except BaseException as exc:
            record['exception_type']=type(exc).__name__; record['exception_errno']=getattr(exc,'errno',None)
            if not record['reason']:
                # Original RESUME enum is safe; other exception messages are never logged.
                text=str(exc); code=text.removeprefix('RESUME_').split(':',1)[0] if text.startswith('RESUME_') else type(exc).__name__
                record['reason']='BLOCK_EXCEPTION_'+code
            raise
        finally:
            record['outcome']='ADMISSION_ALLOWED' if self.admitted else 'ADMISSION_BLOCKED'
            if self.admitted and record['reason']:record['readiness_reason']=record['reason'];record['reason']=None
            if not self.admitted and not record['reason']:record['reason']='BLOCK_NOT_ADMITTED'
            record['finished_UTC']=datetime.now(timezone.utc).isoformat();record['admitted']=self.admitted;record['complete']=self.complete
            record['locks']=list(d.locks);record['telemetry_failures']=d.failures
            d.emit(record);d.local.record=None
    return observed

def diagnostic_capture(method):
    @wraps(method)
    def observed(self,*args,**kwargs):
        result=method(self,*args,**kwargs)
        if result:self.diagnostic.capture_anchor_verified=True;self.diagnostic.capture_range_verified=True
        return result
    return observed

def diagnostic_bbo(method):
    @wraps(method)
    def observed(self,*args,**kwargs):
        start=time.monotonic_ns();before=self.bbo
        try:return method(self,*args,**kwargs)
        finally:
            observation=self.diagnostic.bbo_observation
            if observation and self.bbo is not before and observation['object_id']==id(self.bbo):
                self.diagnostic.bbo_observation={**observation,'callback_start_ns':start,'callback_end_ns':time.monotonic_ns()}
    return observed


def observational(method):
    @wraps(method)
    def safe(self,*args,**kwargs):
        try:return method(self,*args,**kwargs)
        except Exception:self.failures+=1;return None
    return safe
for _name in ('put','block','evidence','revalidation','snapshot_verified','bbo_stored','overlap_stored','set_manifest_baseline'):
    setattr(AdmissionDiagnostics,_name,observational(getattr(AdmissionDiagnostics,_name)))


def diagnostic_entry_ready(method):
    @wraps(method)
    def observed(self,*args,**kwargs):
        result=method(self,*args,**kwargs)
        self.diagnostic.put(entry_ready_result=result)
        if not result:
            if not self.complete:reason='BLOCK_CATCHUP_INCOMPLETE'
            elif not self.bbo:reason='BLOCK_NO_BBO'
            elif self.bbo.get('session')!=self.processor.public_connection_session_id:reason='BLOCK_BBO_SESSION_MISMATCH'
            else:
                E=int((self.bbo['payload'].get('data') or self.bbo['payload']).get('E') or 0)
                reason='BLOCK_BBO_FUTURE' if time.time_ns()/1e6<E else 'BLOCK_BBO_STALE'
            self.diagnostic.block(reason)
        return result
    return observed
