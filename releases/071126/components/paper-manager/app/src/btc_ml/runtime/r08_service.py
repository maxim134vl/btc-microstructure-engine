"""Paper-owned process lifecycle and atomic publication of actual source inputs."""
import atexit,json,os,signal,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone

def now():return datetime.now(timezone.utc).isoformat()
def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    with temp.open('w') as f:json.dump(value,f,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
def state(environ=None):
    env=os.environ if environ is None else environ
    root=env.get('BTC_ML_R08_RUNTIME_MOUNT')
    if not root:return None
    try:return json.loads((Path(root)/'runtime/status.json').read_text())
    except FileNotFoundError:return {'phase':'STARTING','reason':'SOURCE_STARTUP_PENDING'}
def environment(environ=None):
    env=dict(os.environ if environ is None else environ);root=env.get('BTC_ML_R08_RUNTIME_MOUNT')
    if not root:return env
    status=state(env)
    if status['phase']!='RUNNING':
        env.pop('BTC_ML_TREND_DESCRIPTOR',None);env.pop('BTC_ML_TREND_DESCRIPTOR_SHA256',None);return env
    actual=json.loads((Path(root)/'runtime/environment.json').read_text());env.update(actual)
    if environ is None:os.environ.update(actual)
    return env
class OwnedSource:
    def __init__(self):
        self.process=subprocess.Popen([sys.executable,'-u','-m','btc_ml.runtime.r08_live_source'])
        self.closed=False;self.reported_exit=False;self.empty_tls_retries=0;atexit.register(self.close)
    def _empty_tls_source(self, status):
        # Permanent observer lifecycle only. Never retry an admitted input,
        # frozen INIT/baseline, resource failure or canary entrypoint.
        if os.environ.get('BTC_ML_R08_OBSERVER_ONLY') != '1' or self.empty_tls_retries:
            return None
        if not str(status.get('reason','')).startswith('RuntimeError:SOURCE_STOP:FAILED:SSLEOFError:'):
            return None
        if status.get('phase') != 'BLOCKED' or status.get('baseline_fixed') is not False:
            return None
        if status.get('source_native') is not None or status.get('queue_depth') != 0:
            return None
        root=Path(os.environ['BTC_ML_R08_RUNTIME_MOUNT'])
        pointer=root/'runtime/active-source.json'
        try:
            active=json.loads(pointer.read_text());capture_id=active['capture_id']
            if not isinstance(capture_id,str) or len(capture_id)!=32 or any(c not in '0123456789abcdef' for c in capture_id):return None
            capture=root/'captures'/capture_id
            if status.get('capture_root') != str(capture):return None
            if any((capture/'native').iterdir()):return None
            if sorted(p.name for p in (capture/'manifests').iterdir()) != ['00000001.json','00000002.json']:return None
            records=root/'research'/capture_id/'records'
            if records.exists() and any(records.iterdir()):return None
            return pointer,capture_id
        except (OSError,ValueError,KeyError,TypeError):
            return None
    def poll(self):
        code=self.process.poll()
        if code is not None and not self.closed and not self.reported_exit:
            root=Path(os.environ['BTC_ML_R08_RUNTIME_MOUNT'])
            if not root.is_mount():
                self.reported_exit=True
                print(json.dumps({'R08_SOURCE_OWNER_MOUNT_MISSING':str(root),'exit_code':code}),flush=True)
                return code
            try:child=state() or {}
            except (OSError,ValueError):child={'phase':'BLOCKED','reason':'SOURCE_STATUS_UNREADABLE'}
            if not isinstance(child,dict):child={'phase':'BLOCKED','reason':'SOURCE_STATUS_INVALID'}
            empty=self._empty_tls_source(child)
            if empty is not None:
                pointer,capture_id=empty
                preserved=pointer.with_name('active-source-preserved-empty-tls-'+capture_id+'.json')
                if not preserved.exists():
                    self.empty_tls_retries=1
                    self.process.wait()  # Reap the exited owner before another writer.
                    try:
                        pointer.rename(preserved)
                        # Same runtime directory: atomic() also syncs the pointer
                        # rename. Original capture/RAW/receipts are untouched.
                        atomic(root/'runtime/status.json',{'phase':'STARTING','reason':'OBSERVER_EMPTY_TLS_RETRY','attempt':1,'at':now(),'owner':'paper-manager','previous_source':str(preserved),'child_status':child})
                        print(json.dumps({'R08_EMPTY_TLS_RETRY':1,'previous_source':str(preserved),'child_status':child}),flush=True)
                        self.process=subprocess.Popen([sys.executable,'-u','-m','btc_ml.runtime.r08_live_source'])
                        return None
                    except Exception as exc:
                        self.reported_exit=True
                        atomic(root/'runtime/status.json',{'phase':'BLOCKED','reason':'SOURCE_RESTART_FAILED:'+type(exc).__name__+':'+str(exc),'exit_code':code,'at':now(),'owner':'paper-manager','child_status':child})
                        return code
            self.reported_exit=True
            atomic(root/'runtime/status.json',{'phase':'BLOCKED','reason':'SOURCE_PROCESS_EXIT','exit_code':code,'at':now(),'owner':'paper-manager','child_status':child})
        return code
    def close(self):
        if self.closed:return
        self.closed=True
        if self.process.poll() is None:self.process.send_signal(signal.SIGTERM)
        self.process.wait() # No kill/automatic restart; child drains its worker.
def start_owned_source():
    if os.environ.get('BTC_ML_R08_OWNER')!='paper-manager':return None
    root=Path(os.environ['BTC_ML_R08_RUNTIME_MOUNT'])
    if not root.is_mount():raise RuntimeError('R08_EXTERNAL_BIND_REQUIRED')
    atomic(root/'runtime/status.json',{'phase':'STARTING','at':now(),'owner':'paper-manager'})
    return OwnedSource()
