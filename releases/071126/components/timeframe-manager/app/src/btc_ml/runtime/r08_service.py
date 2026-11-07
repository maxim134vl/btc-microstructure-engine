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
        self.closed=False;self.reported_exit=False;atexit.register(self.close)
    def poll(self):
        code=self.process.poll()
        if code is not None and not self.closed and not self.reported_exit:
            self.reported_exit=True
            atomic(Path(os.environ['BTC_ML_R08_RUNTIME_MOUNT'])/'runtime/status.json',{'phase':'BLOCKED','reason':'SOURCE_PROCESS_EXIT','exit_code':code,'at':now(),'owner':'paper-manager'})
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
