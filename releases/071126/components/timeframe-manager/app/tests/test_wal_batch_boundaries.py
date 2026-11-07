import json,os,shutil,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from btc_ml.trading.intrabar_paper.execution_market_wal import ExecutionMarketWAL
from btc_ml.trading.intrabar_paper.execution_market_processor import ExecutionMarketProcessor
from btc_ml.trading.intrabar_paper.execution_market_backfill import normalize_rest_agg_trade
from btc_ml.trading.intrabar_paper.execution_market_checkpoint import ExecutionMarketCheckpoint
DATA=Path(__file__).resolve().parents[2]/'evidence'
REAL=json.loads((DATA/'archive-cursor-real-events.json').read_text())
class Engine:
 def __init__(self,root):self.epoch_root=root;self.positions={};self.ids=[];self.wal=None;self.fail_at=None
 def update_from_trade(self,**kw):
  prov=kw['market_provenance'];id=prov['aggregate_trade_id']
  if id==self.fail_at:raise RuntimeError('ENGINE_FAULT_BEFORE_EFFECTS')
  if self.wal:
   assert any(row['aggregate_trade_id']==id for row in self.wal.iter_from_offset(prov['execution_market_wal_offset']-1))
  self.ids.append(id);return {'status':'NO_POSITIONS_NO_TRADE'}
 def update_bbo_from_market(self,**kw):pass

def event(row):return normalize_rest_agg_trade(row,symbol='BTCUSDT',connection_session_id='BOUNDARY_REAL_EVENTS',receive_monotonic_ns=time.monotonic_ns(),receive_timestamp='2026-10-04T12:00:00Z')
def proc(root,engine=None,fetch=None):
 e=engine or Engine(root)
 p=ExecutionMarketProcessor.create(engine=e,epoch_root=root,paper_epoch_id='ISOLATED',max_bbo_age_ms=2000,max_agg_trade_age_ms=5000,fetch_agg_trades=fetch);e.wal=p.wal;return p,e

def test_group_fsync_before_any_engine(tmp_path,monkeypatch):
 p,e=proc(tmp_path);p._process_agg_trade_live(event(REAL[0]));before=p.wal.fsync_count
 p.fetch_agg_trades=lambda symbol,start,end:[r for r in REAL if start<=r['a']<=end]
 old=e.update_from_trade
 def assert_synced(**kw):
  assert p.wal.fsync_count>before
  return old(**kw)
 monkeypatch.setattr(e,'update_from_trade',assert_synced)
 p._process_agg_trade_live(event(REAL[40]));assert e.ids==[r['a'] for r in REAL[:41]]
 assert p.wal.fsync_count-before==2
 assert p.checkpoint.last_processed_agg_trade_id==REAL[40]['a']

@pytest.mark.parametrize('last_complete',[0,1,7])
def test_torn_group_quarantined_and_prefix_replayed_once(tmp_path,last_complete):
 wal=ExecutionMarketWAL(tmp_path/'execution_market_wal',paper_epoch_id='ISOLATED')
 wal.append_batch([event(r) for r in REAL[:8]])
 raw=wal.events_path.read_bytes().splitlines(keepends=True)
 wal.events_path.write_bytes(b''.join(raw[:last_complete])+raw[last_complete][:37])
 p,e=proc(tmp_path);assert e.ids==[r['a'] for r in REAL[:last_complete]]
 assert list((tmp_path/'execution_market_wal').glob('torn-tail-*.bin'))
 p._process_agg_trade_live(event(REAL[last_complete]));assert e.ids==[r['a'] for r in REAL[:last_complete+1]]
 _,restart=proc(tmp_path);assert restart.ids==[]
 assert [r['aggregate_trade_id'] for r in p.wal.iter_from_offset(0)]==e.ids


def test_durable_group_without_checkpoint_replays_all_once(tmp_path):
 wal=ExecutionMarketWAL(tmp_path/'execution_market_wal',paper_epoch_id='ISOLATED');wal.append_batch([event(r) for r in REAL[:20]])
 p,e=proc(tmp_path);assert e.ids==[r['a'] for r in REAL[:20]]
 _,restart=proc(tmp_path);assert restart.ids==[]
 assert p.checkpoint.last_processed_wal_offset==20


def test_group_engine_failure_cannot_ack_failed_id(tmp_path):
 p,e=proc(tmp_path);p._process_agg_trade_live(event(REAL[0]));before=p.checkpoint_path.read_bytes();e.fail_at=REAL[4]['a']
 p.fetch_agg_trades=lambda s,start,end:[r for r in REAL if start<=r['a']<=end]
 with pytest.raises(RuntimeError):p._process_agg_trade_live(event(REAL[8]))
 assert p.checkpoint_path.read_bytes()==before
 assert p._process_agg_trade_live(event(REAL[9]))[0]['status']=='PROCESSOR_RESTART_REQUIRED'
 d,r=proc(tmp_path);assert r.ids==[x['a'] for x in REAL[1:8]]
 assert d.checkpoint.last_processed_agg_trade_id==REAL[7]['a']


def test_io_failure_before_group_dispatch_is_poisoned(tmp_path,monkeypatch):
 wal=ExecutionMarketWAL(tmp_path/'execution_market_wal',paper_epoch_id='ISOLATED')
 with patch('os.fsync',side_effect=OSError('ENOSPC simulated')):
  assert not wal.append_batch([event(r) for r in REAL[:4]])[0].ok
 assert not wal.append_batch([event(REAL[4])])[0].ok
 p,e=proc(tmp_path);assert e.ids==[r['a'] for r in REAL[:4]]
 assert p.checkpoint.last_processed_agg_trade_id==REAL[3]['a']


def test_disk_reserve_refuses_without_bytes(tmp_path,monkeypatch):
 wal=ExecutionMarketWAL(tmp_path,paper_epoch_id='ISOLATED');before=wal.events_path.read_bytes()
 monkeypatch.setattr(shutil,'disk_usage',lambda p:SimpleNamespace(free=1))
 result=wal.append_batch([event(REAL[0])]);assert result[0].error=='WAL_DISK_RESERVE_EXHAUSTED'
 assert wal.events_path.read_bytes()==before


def test_bounded_request_and_logs(tmp_path):
 calls=[]
 def fetch(s,start,end):
  calls.append((start,end));return [r for r in REAL if start<=r['a']<=end]
 p,e=proc(tmp_path,fetch=fetch);p.recovery_batch_size=7;p.recovery_action_limit=20
 p._process_agg_trade_live(event(REAL[0]));a=p._process_agg_trade_live(event(REAL[-1]))
 assert max(end-start+1 for start,end in calls)==7
 assert len(p.dispatch_log)<=20 and len(p.wal_append_log)<=20 and len(a)<=20
 assert e.ids==[r['a'] for r in REAL]
 assert p.checkpoint.last_processed_agg_trade_id==REAL[-1]['a']


def test_batch_limit(tmp_path):
 wal=ExecutionMarketWAL(tmp_path,paper_epoch_id='ISOLATED')
 with pytest.raises(ValueError,match='LIMIT'):wal.append_batch([event(r) for r in REAL[:3]],max_events=2)
 assert wal.last_offset==0

@pytest.mark.parametrize('boundary',['temp_fsync','replace','parent_fsync'])
def test_checkpoint_atomic_publication_fault(tmp_path,monkeypatch,boundary):
 path=tmp_path/'ck.json';ck=ExecutionMarketCheckpoint('ISOLATED');ck.note_processed(aggregate_trade_id=REAL[0]['a'],wal_offset=1);ck.save(path)
 ck.note_processed(aggregate_trade_id=REAL[1]['a'],wal_offset=2)
 real=os.fsync;count=0
 def fail(fd):
  nonlocal count
  count+=1
  if (boundary=='temp_fsync' and count==1) or (boundary=='parent_fsync' and count==2):raise OSError('checkpoint crash boundary')
  return real(fd)
 monkeypatch.setattr(os,'fsync',fail)
 if boundary=='replace':monkeypatch.setattr(Path,'replace',lambda *a:(_ for _ in ()).throw(OSError('replace boundary')))
 with pytest.raises(OSError):ck.save(path)
 read=json.loads(path.read_text());assert read['last_processed_wal_offset'] in {1,2}
 assert read['last_processed_agg_trade_id']==REAL[read['last_processed_wal_offset']-1]['a']
