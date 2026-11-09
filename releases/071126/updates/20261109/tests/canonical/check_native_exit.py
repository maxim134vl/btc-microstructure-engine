"""Small saved-input regression only. No network or production mounts."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import threading
import time
from unittest.mock import patch

sys.path[:0] = ['/app', '/app/src']
os.environ['BTC_ML_DATA_ROOT'] = '/app/data'
os.environ['BTC_ML_CANONICAL_CANDLE_LANE'] = '1'
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ['PYTHONPATH'] = '/app:/app/src'
os.environ['PYTHONFAULTHANDLER'] = '1'
ROOT = Path('/app')
for child in Path('/fixtures/data').iterdir():
    shutil.copytree(child, ROOT/'data'/child.name, dirs_exist_ok=True)
(ROOT/'data/live').mkdir(exist_ok=True)
(ROOT/'data/runtime').mkdir(exist_ok=True)

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow.fs import LocalFileSystem
import auction_parquet_io as native
import parquet_utils as original
from btc_ml.runtime import canonical_candle_lane as L
from runtime_engine_guard import _run_engine_subprocess_isolated

checks = []
def check(name, condition):
    assert condition, name
    checks.append(name)

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

saved = json.loads(Path('/preserved/state.json').read_text())
def fixture_item(item):
    item = copy.deepcopy(item)
    folder = Path('/preserved') / Path(item['directory']).name
    for key in ['descriptor', 'feed_origin_snapshot', 'native_read_record']:
        item[key] = str(folder/Path(item[key]).name)
    item['directory'] = str(folder)
    item['inputs'] = {k: str(folder/Path(v).name) for k,v in item['inputs'].items()}
    return item
items = [fixture_item(saved[k]) for k in ['current','active']]
items += [fixture_item(v) for v in saved['pending']]

# Compare the actual backend arguments as well as every decoded value/dtype.
read_calls = []
real_read = pq.read_table
def read_spy(source, *args, **kwargs):
    read_calls.append({'source_type':type(source).__name__,
                       'native_path':isinstance(source,(str,Path)),
                       'filesystem':type(kwargs.get('filesystem')).__name__})
    return real_read(source, *args, **kwargs)

names = ['volume_response_state.parquet','auction_convergence_memory.parquet',
         'htf_structure_memory.parquet','htf_ltf_context_memory.parquet',
         'auction_synthesis_memory.parquet']
schemas = {}
with patch.object(pq,'read_table',read_spy):
    for name in names:
        before = original.safe_read_parquet(name)
        old_call = read_calls[-1]
        after = native.safe_read_parquet(name)
        new_call = read_calls[-1]
        pd.testing.assert_frame_equal(before,after,check_exact=True)
        check('attrs:'+name,before.attrs == after.attrs)
        a = pa.Table.from_pandas(before).schema
        b = pa.Table.from_pandas(after).schema
        check('schema/index/metadata:'+name,a.equals(b,check_metadata=True))
        check('Python-backed old reader:'+name,not old_call['native_path'])
        check('native filesystem reader:'+name,new_call['native_path'] and new_call['filesystem']=='LocalFileSystem')
        schemas[name]={'rows':len(before),'dtypes':{str(k):str(v) for k,v in before.dtypes.items()},'index':repr(before.index),'schema':str(a)}

check('original atomic writer retained',native.atomic_parquet_write is original.atomic_parquet_write)
old_source = ast.parse(Path('/baseline/auction_synthesis_engine_v1.py').read_text())
new_source = ast.parse(Path('/app/auction_synthesis_engine_v1.py').read_text())
def calculation(tree):
    return ast.dump(ast.Module(body=[n for n in tree.body if not
        (isinstance(n,ast.ImportFrom) and n.module in {'parquet_utils','state_guard','auction_parquet_io'})],type_ignores=[]))
check('Auction calculation AST unchanged',calculation(old_source)==calculation(new_source))

# Deterministic append: same genuine saved row, including its original time.
state_path = ROOT/'data/reinforcement/auction_synthesis_memory.parquet'
full_state = original.safe_read_parquet('auction_synthesis_memory.parquet')
before_payload = full_state.iloc[:-1]
new_row = full_state.iloc[[-1]].reset_index(drop=True)
append_bytes = []
for mode, append in [('old',original.append_state_row),('native',native.append_state_row)]:
    test_root = ROOT/'data'/('append_'+mode)
    dest = test_root/'reinforcement/auction_synthesis_memory.parquet'
    dest.parent.mkdir(parents=True,exist_ok=True)
    before_payload.to_parquet(dest,index=False)
    with patch.dict(os.environ,{'BTC_ML_DATA_ROOT':str(test_root)}):
        result = append('auction_synthesis_memory.parquet',new_row)
        pd.testing.assert_frame_equal(result,full_state.reset_index(drop=True),check_exact=True)
    append_bytes.append(dest.read_bytes())
check('append bytes and checksum identical',append_bytes[0]==append_bytes[1])
check('append directory/sidecars identical',
      sorted(p.name for p in (ROOT/'data/append_old/reinforcement').iterdir()) ==
      sorted(p.name for p in (ROOT/'data/append_native/reinforcement').iterdir()))
old_hash = sha(state_path)
try:
    with patch.object(native,'atomic_parquet_write',side_effect=OSError('isolated write failure')):
        native.append_state_row('auction_synthesis_memory.parquet',new_row)
except OSError:
    pass
else:
    raise AssertionError('write failure suppressed')
check('write failure leaves previous state unchanged',sha(state_path)==old_hash)

# Saved original generation owner metadata and source pins, never reissued.
for item in items:
    L.CandleLane._verify(None,item)
check('existing owner metadata and input pins valid',True)

# Bound at two, backpressure before accepting; recover active, never re-run current.
queue_root = ROOT/'data/queue_check'
produced = []
def producer(job):
    produced.append(time.monotonic())
    return items[2] if len(produced)==1 else None
lane = L.CandleLane(queue_root,poll_s=.02,produce=producer)
lane.state.update(current=None,active=None,pending=copy.deepcopy(items[:2]))
lane._save();lane.start();time.sleep(.10)
check('full FIFO waits before producer',not produced and lane.fatal is None)
active = lane.next()
end = time.monotonic()+5
while not produced and time.monotonic()<end:time.sleep(.01)
lane.close()
check('FIFO remains bounded and ordered',
      [x['target'] for x in lane.state['pending']]==[items[1]['target'],items[2]['target']] and lane.fatal is None)
restored = L.CandleLane(queue_root,poll_s=.02,produce=lambda job:None)
check('interrupted active restored first',restored.next()==active==items[0])
try:restored.committed(items[2])
except RuntimeError as error:check('wrong commit fail-stop',str(error)=='CANDLE_GENERATION_COMMIT_ORDER')
else:raise AssertionError('wrong commit accepted')
seen=[]
for item in items:
    got=restored.next();seen.append(got['target']);restored.committed(got)
check('saved generations committed in order',seen==[x['target'] for x in items])
check('committed generation not recalculated',restored.next() is None)
def failed_producer(job):raise RuntimeError('CANDLE_GENERATION_INPUT_CHANGED:fixture')
failed = L.CandleLane(ROOT/'data/fail_check',poll_s=.02,produce=failed_producer).start()
failed.thread.join(2)
try:failed.check()
except RuntimeError as error:check('producer pin failure still fail-stop','CANDLE_GENERATION_INPUT_CHANGED' in str(error))
else:raise AssertionError('producer failure ignored')
failed.close()

# Actual Candle calculation from prior genuine E to F, overlapping child launch.
for source,target in [('feed_origin.parquet','data/live/live_market_feed.parquet'),
                      ('feed_origin.meta.json','data/live/live_market_feed.parquet.meta.json')]:
    shutil.copyfile(Path('/fixtures')/source,ROOT/target)
prior=items[0]
for source,target in [(prior['inputs']['candle_structure_memory.parquet'],'data/cognition/candle_structure_memory.parquet'),
                      (prior['inputs']['candle_structure_memory.parquet']+'.meta.json','data/cognition/candle_structure_memory.parquet.meta.json')]:
    shutil.copyfile(source,ROOT/target)
descriptor=copy.deepcopy(items[1]);descriptor['descriptor']=str(ROOT/'data/runtime/active_fixture.json')
Path(descriptor['descriptor']).write_text(json.dumps(descriptor))
real_popen=subprocess.Popen
measured=[]
class MeasuredPopen(real_popen):
    def _try_wait(self,wait_flags):
        try:
            pid,status,usage=os.wait4(self.pid,wait_flags)
        except ChildProcessError:
            return self.pid,0
        if pid==self.pid and usage is not None:
            self.measured_usage=usage
        return pid,status
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        measured.append(self)
subprocess.Popen=MeasuredPopen
live_lane=L.CandleLane(ROOT,poll_s=.05).start()
child_results=[]
try:
    for i in range(16):
        mode='baseline' if i<4 else 'native'
        if i>=12:before_payload.to_parquet(state_path,index=False)
        script='/baseline/auction_synthesis_engine_v1.py' if mode=='baseline' else '/app/auction_synthesis_engine_v1.py'
        started=time.monotonic();offset=len(measured)
        with L.input_scope(descriptor):
            rc=_run_engine_subprocess_isolated(sys.executable,script,str(ROOT),'auction_synthesis_engine_v1.py',30)
        wall=time.monotonic()-started
        process=measured[offset]
        usage=process.measured_usage
        child_results.append({'mode':mode,'branch':'append' if i>=12 else 'unchanged',
            'returncode':rc,'wall_s':wall,'CPU_s':usage.ru_utime+usage.ru_stime,
            'peak_RSS_KiB':usage.ru_maxrss,'pid':process.pid,'output_sha':sha(state_path)})
        check('child exit and native cleanup:'+str(i),rc==0 and not Path('/proc',str(process.pid)).exists())
        if i<12:check('NEUTRAL/NO STATE CHANGE:'+str(i),sha(state_path)==old_hash)
        else:
            result=native.safe_read_parquet('auction_synthesis_memory.parquet')
            pd.testing.assert_frame_equal(result.iloc[:-1].reset_index(drop=True),before_payload.reset_index(drop=True),check_exact=True)
            check('append Auction payload:'+str(i),result.iloc[-1]['auction_state']=='NEUTRAL' and result.iloc[-1]['interpretation']=='NEUTRAL')
        live_lane.check()
    check('actual Candle lane alive',live_lane.thread.is_alive())
    check('actual Candle F published',live_lane.state['pending'] and live_lane.state['pending'][0]['target']==items[1]['target'])
finally:
    live_lane.close()
    subprocess.Popen=real_popen
for item in items:L.CandleLane._verify(None,item)
check('owner receipts/source pins unchanged after children',True)
stats={}
for mode in ['baseline','native']:
    group=[v for v in child_results if v['mode']==mode and v['branch']=='unchanged']
    stats[mode]={'runs':len(group),'mean_wall_s':sum(v['wall_s'] for v in group)/len(group),
        'mean_CPU_s':sum(v['CPU_s'] for v in group)/len(group),
        'peak_RSS_KiB':max(v['peak_RSS_KiB'] for v in group)}
check('candidate peak within baseline plus 16 MiB',stats['native']['peak_RSS_KiB']<=stats['baseline']['peak_RSS_KiB']+16384)
print('CANDIDATE_RESULT '+json.dumps({'PASS':len(checks),'FAIL':0,'checks':checks,'schemas':schemas,
    'read_paths':read_calls,'child_results':child_results,'stats':stats,
    'parent_peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'fixture_only':True}),flush=True)
