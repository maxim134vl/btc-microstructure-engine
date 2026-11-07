"""Transport FIFO/shutdown tests; economy is covered by the actual-engine suite."""
import importlib.util,queue,threading,time
from pathlib import Path
import pytest
from tests.trading.intrabar_paper.test_execution_market_wal import _processor,_book,_agg
from btc_ml.trading.intrabar_paper.execution_market_processor import ReplayInterrupted
pytest_plugins=['tests.trading.intrabar_paper.test_execution_market_wal']
spec=importlib.util.spec_from_file_location('bounded_runner',Path(__file__).resolve().parents[1]/'scripts/live/run_intrabar_paper_manager.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

def test_transport_full_queue_preserves_order_and_backpressures():
 q=queue.Queue(maxsize=runner.MARKET_PAYLOAD_QUEUE_MAXSIZE)
 for i in range(q.maxsize):q.put(i)
 entered=threading.Event();done=threading.Event();result=[]
 def put():entered.set();result.append(runner._enqueue_market_payload(q,q.maxsize,stop_requested=lambda:False));done.set()
 thread=threading.Thread(target=put);thread.start();assert entered.wait(1)
 assert not done.wait(.1);assert q.qsize()==q.maxsize
 items=[q.get(timeout=1) for _ in range(q.maxsize)];assert done.wait(2);items.append(q.get(timeout=1));thread.join(2)
 assert result==[True];assert items==list(range(q.maxsize+1))

def test_transport_stop_releases_blocked_sender_without_reordering_queue():
 q=queue.Queue(maxsize=1);q.put('first');stop=threading.Event();result=[]
 thread=threading.Thread(target=lambda:result.append(runner._enqueue_market_payload(q,'second',stop_requested=stop.is_set)))
 thread.start();time.sleep(.05);stop.set();thread.join(2)
 assert not thread.is_alive() and result==[False];assert q.get_nowait()=='first';assert q.empty()

def test_replay_stop_does_not_advance_checkpoint_or_remove_wal(env):
 p=_processor(env);_book(p);_agg(p,100,100)
 _book(p);before=p.checkpoint_path.read_bytes();offset=p.wal.last_offset
 with pytest.raises(ReplayInterrupted):p.replay_from_checkpoint(stop_requested=lambda:True)
 assert p._halted;assert p.checkpoint_path.read_bytes()==before;assert p.wal.last_offset==offset
 p.replay_from_checkpoint();assert p.checkpoint_path.read_bytes()==before

def test_replay_large_tail_diagnostics_bounded_every_event_delivered(env):
 p=_processor(env);p.recovery_action_limit=11
 _book(p);_agg(p,100,100)
 # Original engine with no positions; repeated fixture BBO is mechanics only.
 for i in range(200):_book(p,mono=10000000+i)
 observed=[];original=p._dispatch_book_ticker
 def dispatch(event,**kw):observed.append(kw['wal_offset']);return original(event,**kw)
 p._dispatch_book_ticker=dispatch
 result=p.replay_from_checkpoint()
 assert len(result)==11 and len(p.dispatch_log)<=11 and len(p.wal_append_log)<=11
 assert len(observed)==200 and observed==sorted(set(observed))


def test_original_no_effect_market_updates_do_not_touch_receipt_store(env,monkeypatch):
 p=_processor(env);engine=p.engine
 def no_disk(*args,**kwargs):raise AssertionError('no-effect tick consulted receipt store')
 monkeypatch.setattr(engine.books.commit,'run',no_disk)
 quote=engine.update_bbo_from_market(best_bid=100,best_ask=100.2,receive_monotonic_ns=123,source_event_id='bounded-bbo')
 tick=engine.update_from_trade(price=100,receive_monotonic_ns=124,source_event_id='bounded-agg')
 assert quote==tick==[] and not engine.books.open_positions()
 assert engine.bbo._latest_local.best_bid==100

def test_poisoned_commit_cannot_use_no_effect_fast_path(env):
 p=_processor(env);e=p.engine;e.books.commit.poisoned=True
 with pytest.raises(RuntimeError,match='RESTART_REQUIRED'):
  e.update_bbo_from_market(best_bid=100,best_ask=100.2,receive_monotonic_ns=123,source_event_id='poisoned-quote')


def test_checkpoint_bounded_heap_matches_original_exact_set_and_roundtrip(tmp_path):
 import random
 from btc_ml.trading.intrabar_paper.execution_market_checkpoint import ExecutionMarketCheckpoint,RECENT_PROCESSED_AGG_TRADE_IDS_LIMIT
 ck=ExecutionMarketCheckpoint('EXACT'); original=set();rng=random.Random(41)
 values=list(range(4300))+[rng.randrange(0,10000) for _ in range(700)]
 for offset,value in enumerate(values,1):
  original.add(value)
  original=set(sorted(original)[-RECENT_PROCESSED_AGG_TRADE_IDS_LIMIT:])
  ck.note_processed(aggregate_trade_id=value,wal_offset=offset)
  assert ck.processed_agg_trade_ids==original
  assert len(ck._recent_heap)<=RECENT_PROCESSED_AGG_TRADE_IDS_LIMIT
  if offset%511==0:
   path=tmp_path/'checkpoint.json';ck.save(path);ck=ExecutionMarketCheckpoint.load(path,paper_epoch_id='EXACT')
 assert ck.to_dict()=={'paper_epoch_id':'EXACT','last_processed_wal_offset':len(values),'last_processed_agg_trade_id':values[-1],'processed_agg_trade_ids':sorted(original)}


def test_large_near_tail_uses_forward_stream_not_reverse_cache(tmp_path,monkeypatch):
 import json
 import btc_ml.trading.intrabar_paper.execution_market_wal_archive as arch
 path=tmp_path/'source.jsonl'
 with path.open('w') as f:
  for i in range(1,20002):f.write(json.dumps({'wal_offset':i,'source_event_id':str(i)})+'\n')
 before=path.stat().st_size
 monkeypatch.setattr(arch,'_iter_lines_reverse',lambda *_:(_ for _ in ()).throw(AssertionError('unbounded near-tail cache')))
 expected=2
 for row in arch.iter_jsonl_after(path,1,first_offset=1,last_offset=20001):
  assert row['wal_offset']==expected;expected+=1
 assert expected==20002 and path.stat().st_size==before


def test_large_records_reverse_byte_cap_preserves_all_original_rows(tmp_path,monkeypatch):
 import json,hashlib
 import btc_ml.trading.intrabar_paper.execution_market_wal_archive as arch
 path=tmp_path/'wide.jsonl'
 with path.open('w') as f:
  for i in range(1,1602):f.write(json.dumps({'wal_offset':i,'payload':'x'*6000})+'\n')
 before=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
 original=arch.iter_jsonl;calls=[]
 def streaming(p):calls.append(p);yield from original(p)
 monkeypatch.setattr(arch,'iter_jsonl',streaming)
 count=0
 for row in arch.iter_jsonl_after(path,1,first_offset=1,last_offset=1601):
  count+=1;assert row['wal_offset']==count+1 and len(row['payload'])==6000
 assert count==1600 and calls==[path]
 assert hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==before
 storage=arch.SegmentedWalStorage(tmp_path/'archive',archive_batch_rows=65536)
 assert storage.archive_batch_rows==8192
