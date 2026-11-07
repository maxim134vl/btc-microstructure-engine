"""Isolated research receipts. No market or economic qualification."""
import hashlib, json, time, uuid, os, subprocess
from datetime import datetime, timezone, timedelta
VERSION = 'DRA_PASSIVE_RAW_RECEIPT_RECORDER_V1'
VOLUME_UUID = 'DB659F02-B68F-4223-9AB7-D68B27CEFE71'
MARKET = 'BINANCE_SPOT'
TF = ('M15','M30','H1','H4')
def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def sha(b): return hashlib.sha256(b).hexdigest()
def digest(x): return sha(canonical(x))
def stamp():
    wall=time.time_ns(); mono=time.monotonic_ns()
    dt=datetime.fromtimestamp(wall//1_000_000_000,timezone.utc)+timedelta(microseconds=(wall%1_000_000_000)//1000)
    return {'wall_utc':dt.isoformat().replace('+00:00','Z'),'wall_ns':wall,'monotonic_ns':mono}
def utc(x):
    t=datetime.fromisoformat(x.replace('Z','+00:00'))
    if t.tzinfo is None or t.utcoffset()!=timedelta(0): raise ValueError('UTC_REQUIRED')
    return t
def ms(x): return (datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(milliseconds=x)).isoformat().replace('+00:00','Z')
def seal(x): return {**x,'content_sha256':digest(x)}
def verified(x): return x.get('content_sha256')==digest({k:v for k,v in x.items() if k!='content_sha256'})
def domain():
    try: boot=subprocess.check_output(['/usr/sbin/sysctl','-n','kern.bootsessionuuid'],text=True).strip()
    except (OSError,subprocess.SubprocessError): boot=None
    return {'boot_id':boot,'boot_id_status':'OBSERVED_OS' if boot else 'UNKNOWN','process_id':os.getpid(),'process_domain':str(uuid.uuid4()),'utc_uncertainty':'NOT_MEASURED','kernel_receive':None}
class Blocked(RuntimeError): pass
class Corrupt(Blocked): pass
class Capacity(Blocked): pass

def rss_bytes():
    import resource,sys
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform=='darwin' else value*1024
