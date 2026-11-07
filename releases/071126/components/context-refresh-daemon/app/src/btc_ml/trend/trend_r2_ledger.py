"""Single-writer, append-only hash-chained research ledger on external SSD.

Each record is fsynced then linked atomically without overwriting another record.
Only numbered *.json files are committed. Interrupted .pending files are ignored,
preserved and exposed by recovery; corrupt committed files fail closed.
"""
from pathlib import Path
import fcntl
import json
import os
import uuid
import hashlib
def reducer_sha(): return hashlib.sha256(Path(__file__).with_name("trend_r2_machine.py").read_bytes()).hexdigest()
from dataclasses import asdict
from .trend_r2_contract import SCHEMA, VERSION, FailClosedQualifier, QualifiedMarketEvidence, canonical, digest
from .trend_r2_machine import State, evaluate, Evaluation

class CorruptLedger(RuntimeError): pass
class WriterBusy(RuntimeError): pass

class Ledger:
    def __init__(self, directory, qualifier=None):
        self.directory=Path(directory).resolve()
        external=Path(__file__).resolve().parents[3]
        if not self.directory.is_relative_to(external): raise ValueError('RESEARCH_EXTERNAL_PATH_REQUIRED')
        self.directory.mkdir(parents=True,exist_ok=True)
        self.qualifier=qualifier or FailClosedQualifier()
        self.state=State(); self.records=[]; self.interrupted=[]
        with self._lock(): self._load()
    class _Locked:
        def __init__(self,path): self.path=path
        def __enter__(self):
            self.f=open(self.path,'a+b')
            try: fcntl.flock(self.f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                self.f.close(); raise WriterBusy('RESEARCH_WRITER_BUSY')
            return self
        def __exit__(self,*args): fcntl.flock(self.f.fileno(),fcntl.LOCK_UN); self.f.close()
    def _lock(self): return self._Locked(self.directory/'.research-writer.lock')
    def _load(self):
        state=State(); records=[]; prev='GENESIS'
        files=sorted(self.directory.glob('*.json'))
        for seq,path in enumerate(files,1):
            try:
                if path.name!=f'{seq:08d}.json': raise ValueError('SEQUENCE_GAP')
                record=json.loads(path.read_text()); body={k:v for k,v in record.items() if k!='record_sha256'}
                if record.get('reducer_implementation_sha')!=reducer_sha(): raise ValueError('IMPLEMENTATION_VERSION_MISMATCH')
                if record['record_sha256']!=digest(body) or record['previous_sha256']!=prev or record['sequence']!=seq or record['schema_version']!=SCHEMA or record['algorithm_version']!=VERSION: raise ValueError('CHAIN_OR_VERSION')
                state,result=evaluate(state,record['request'])
                if asdict(result)!=record['result'] or digest(state.to_dict())!=record['state_sha256']: raise ValueError('REPLAY_MISMATCH')
                records.append(record); prev=record['record_sha256']
            except (ValueError,KeyError,TypeError) as exc: raise CorruptLedger(f'{path.name}: {exc}') from exc
        self.state=state; self.records=records
        self.interrupted=sorted(p.name for p in self.directory.glob('*.pending'))
    def submit(self,request,*,fault=None):
        with self._lock():
            self._load()
            if request.get('kind')=='market':
                try:
                    e=QualifiedMarketEvidence.from_dict(request['evidence'])
                    invalid=e.validate()
                    # Validate raw availability even if a plugin modifies its envelope.
                    if not invalid:
                        qualified=self.qualifier.qualify(e)
                        if qualified is None: raise ValueError('QUALIFIER_RETURNED_NONE')
                        immutable=lambda x:{k:v for k,v in x.to_dict().items() if k not in ('evidence_status','eligibility_status','independent_verified')}
                        if immutable(e)!=immutable(qualified): raise ValueError('QUALIFIER_CHANGED_SOURCE')
                        request={'kind':'market','evidence':qualified.to_dict()}
                except Exception as exc:
                    # Preserve the rejected source envelope and typed cause, never admit.
                    request=dict(request, qualification_error=type(exc).__name__)
            new,result=evaluate(self.state,request)
            if result.status=='DUPLICATE': return result
            record={'reducer_implementation_sha':reducer_sha(),'schema_version':SCHEMA,'algorithm_version':VERSION,'sequence':len(self.records)+1,
                'previous_sha256':self.records[-1]['record_sha256'] if self.records else 'GENESIS',
                'request':request,'result':asdict(result),'state_sha256':digest(new.to_dict())}
            record['record_sha256']=digest(record)
            final=self.directory/f"{record['sequence']:08d}.json"
            temporary=self.directory/f'{uuid.uuid4().hex}.pending'
            payload=(canonical(record)+'\n').encode()
            with open(temporary,'xb') as f:
                if fault=='partial_write':
                    f.write(payload[:len(payload)//2]); f.flush(); os.fsync(f.fileno()); raise InterruptedError('PARTIAL_WRITE_FIXTURE')
                f.write(payload); f.flush(); os.fsync(f.fileno())
            if fault=='before_commit': raise InterruptedError('BEFORE_COMMIT_FIXTURE')
            os.link(temporary,final)  # Atomic no-clobber commit of complete immutable bytes.
            fd=os.open(self.directory,os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
            if fault=='after_commit': raise InterruptedError('AFTER_COMMIT_BEFORE_ACK_FIXTURE')
            temporary.unlink()
            self._load()
            return result
