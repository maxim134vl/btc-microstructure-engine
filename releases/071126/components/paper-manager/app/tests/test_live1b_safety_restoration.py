"""Isolated contract tests; all prices and positions stay under pytest tmp_path."""
import json,time,multiprocessing,subprocess,sys,importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from tests.trading.intrabar_paper.test_context_execution_contract import _engine,_fresh
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.s41_command_consumer import S41CommandConsumer
from btc_ml.runtime.single_instance import acquire_pid_lock
pytest_plugins=['tests.trading.intrabar_paper.test_context_execution_contract']

def quote(e):
 return e.update_bbo_from_market(best_bid=100,best_ask=100.2,receive_monotonic_ns=time.monotonic_ns(),receive_timestamp=_fresh(0))
def cmd(id,intent,tf='M15',reason=None,age=2):
 return {'command_id':id,'intent':intent,'timeframe':tf,'action_allowed':True,'lifecycle_episode_id':tf+':isolated',
         'evaluation_timestamp':_fresh(age),'command_ttl_seconds':300,'context_origin_price':100.1,'reason_codes':reason or []}
class Bus:
 def __init__(self,p,rows):
  self.rows=rows;self.paths=SimpleNamespace(latest=p/'latest.json')
  self.paths.latest.write_text(json.dumps({'evaluation_timestamp':_fresh(0),'commands':{r['timeframe']:r for r in rows if r['intent'].startswith('OPEN')}}))
 def pending_for_timeframe(self,tf,processed_command_ids,**kw):return [r for r in self.rows if r['timeframe']==tf and r['command_id'] not in processed_command_ids]
def consumer(e,p,rows):return S41CommandConsumer(e,checkpoint_path=p/'s41.json',consume_after=None,bus=Bus(p,rows))

def test_flat_close_is_logged_once_without_fill(cfg,tmp_path):
 e=_engine(cfg[0]);r=cmd('flat','CLOSE');c=consumer(e,tmp_path,[r]);assert c.poll()[0]['status']=='CLOSE_NO_POSITION'
 assert c.poll()==[];d=consumer(e,tmp_path,[r]);assert d.poll()==[]
 rows=[json.loads(x) for x in (tmp_path/'s41_close_results.jsonl').read_text().splitlines()]
 assert len(rows)==1 and rows[0]['result']['status']=='CLOSE_NO_POSITION'
 assert not e.books.read_all('fills') and not e.books.read_all('trades') and not e.positions

def test_pending_close_survives_consumer_and_engine_restart(cfg,tmp_path):
 e=_engine(cfg[0]);quote(e);assert e.apply_s41_manager_command(cmd('open','OPEN_LONG',age=10))['status']=='ENTERED'
 e.bbo._latest_local=None;r=cmd('pending','CLOSE',reason=['PREVIEW_CLOSE_LONG_CONTEXT_EXIT']);c=consumer(e,tmp_path,[r])
 assert c.poll()[0]['status']=='EXIT_PENDING_NO_CAUSAL_BBO'
 assert not (tmp_path/'s41.json').exists()
 restarted=IntrabarPaperEngine(cfg=cfg[0],epoch=e.epoch);quote(restarted);d=consumer(restarted,tmp_path,[r])
 assert d.poll()[0]['status']=='EXITED';assert d.poll()==[]
 assert len(restarted.books.closed_trades())==1 and not restarted.positions
 assert len([x for x in restarted.books.read_all('fills') if x['action']=='EXIT'])==1

def test_slot_busy_preserves_open_until_flat(cfg,tmp_path):
 e=_engine(cfg[0]);quote(e);assert e.apply_s41_manager_command(cmd('long','OPEN_LONG',age=10))['status']=='ENTERED'
 r=cmd('short','OPEN_SHORT');c=consumer(e,tmp_path,[r]);assert c.poll()==[]
 assert not (tmp_path/'s41.json').exists()
 assert e.apply_s41_manager_command(cmd('close','CLOSE',reason=['PREVIEW_CLOSE_LONG_CONTEXT_EXIT']))['status']=='EXITED'
 assert c.poll()[0]['status']=='ENTERED';assert e.positions['M15'].side=='SHORT';assert c.poll()==[]

def test_same_step_close_before_open_and_old_long_stop(cfg,tmp_path):
 e=_engine(cfg[0]);quote(e);assert e.apply_s41_manager_command(cmd('oldlong','OPEN_LONG',age=10))['status']=='ENTERED'
 # Deliberately supply OPEN before CLOSE, consumer restores accepted CLOSE-first order.
 c=consumer(e,tmp_path,[cmd('a-short','OPEN_SHORT'),cmd('z-close','CLOSE',reason=['PREVIEW_CLOSE_LONG_CONTEXT_EXIT'])])
 assert [x['status'] for x in c.poll()]==['EXITED','ENTERED']
 pid=e.positions['M15'].position_id
 assert e.apply_s41_manager_command(cmd('lagged','CLOSE',reason=['PREVIEW_CLOSE_LONG_STOP_LOSS']))['status']=='CLOSE_SIDE_MISMATCH'
 assert e.positions['M15'].position_id==pid and len(e.books.closed_trades())==1
 assert c.poll()==[]

@pytest.mark.parametrize('side',['LONG','SHORT'])
@pytest.mark.parametrize('kind',['STOP_LOSS','TAKE_PROFIT'])
def test_current_protective_close_without_bbo(cfg,side,kind):
 e=_engine(cfg[0]);quote(e);assert e.apply_s41_manager_command(cmd('open','OPEN_'+side,age=10))['status']=='ENTERED'
 p=e.positions['M15'];level=p.stop_loss_price if kind=='STOP_LOSS' else p.take_profit_price;e.bbo._latest_local=None
 result=e.apply_s41_manager_command(cmd('protect','CLOSE',reason=['PREVIEW_CLOSE_'+side+'_'+kind]))
 assert result['status']=='EXITED' and result['fill']['paper_fill_price']==pytest.approx(level)
 assert len(e.books.closed_trades())==1 and not e.positions

def test_accepted_open_checkpoint_loss_cannot_repeat_after_restart(cfg):
 e=_engine(cfg[0]);quote(e);r=cmd('durable-entry','OPEN_LONG',age=10);e.apply_s41_manager_command(r)
 e.apply_s41_manager_command(cmd('tp','CLOSE',reason=['PREVIEW_CLOSE_LONG_TAKE_PROFIT']))
 # Crash before context checkpoint save: book is the accepted original fallback.
 e.consumer.checkpoint_path.unlink(missing_ok=True)
 d=IntrabarPaperEngine(cfg=cfg[0],epoch=e.epoch);quote(d)
 assert d.apply_s41_manager_command(r)['status']=='ENTRY_BLOCKED_DUPLICATE_COMMAND'
 assert len(d.books.closed_trades())==1 and not d.positions

def concurrent_entry(config,epoch,barrier,output,id):
 e=IntrabarPaperEngine(cfg=config,epoch=epoch);quote(e);barrier.wait(timeout=30)
 output.put(e.apply_s41_manager_command(cmd(id,'OPEN_LONG'))['status'])
def test_parallel_processes_cannot_double_m15(cfg):
 e=_engine(cfg[0]);ctx=multiprocessing.get_context('spawn');barrier=ctx.Barrier(2);q=ctx.Queue()
 ps=[ctx.Process(target=concurrent_entry,args=(cfg[0],e.epoch,barrier,q,'parallel-'+str(i))) for i in range(2)]
 for p in ps:p.start()
 try:
  statuses=[q.get(timeout=50) for _ in ps]
  for p in ps:p.join(timeout=30);assert p.exitcode==0
  assert sorted(statuses)==['ENTERED','ENTRY_BLOCKED_ACTIVE_POSITION']
  assert len(e.books.open_positions())==1
  assert len([x for x in e.books.read_all('fills') if x['action']=='ENTRY'])==1
 finally:
  for p in ps:
   if p.is_alive():p.terminate()
   p.join(timeout=5)
  q.close()

def test_second_runtime_owner_rejected_before_any_wal_or_book(cfg,tmp_path,monkeypatch):
 c=cfg[0];e=_engine(c);lock=acquire_pid_lock(c.books_root/e.epoch.paper_epoch_id/'.execution_owner.lock')
 root=Path(__file__).resolve().parents[1];path=root/'live/run_intrabar_paper_manager.py'
 spec=importlib.util.spec_from_file_location('isolated_paper_runner',path);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
 monkeypatch.setattr(runner,'load_intrabar_paper_config',lambda *a,**k:c)
 monkeypatch.setattr(runner,'load_execution_market_wal_config',lambda *a:None)
 monkeypatch.setattr(runner,'load_active_epoch',lambda *a:e.epoch)
 monkeypatch.setattr(runner,'IntrabarPaperEngine',lambda **k:pytest.fail('second writer initialized'))
 monkeypatch.setattr(sys,'argv',['runner']);assert runner.main()==4
 # OS closure releases owner while persistent inode survives; next owner restarts normally.
 lock._handle.close();lock._handle=None
 nextlock=acquire_pid_lock(lock.path);assert nextlock.path.exists();nextlock._handle.close();nextlock._handle=None

def test_pending_context_close_cannot_follow_into_new_short(cfg):
 e=_engine(cfg[0]);quote(e);e.apply_s41_manager_command(cmd('long','OPEN_LONG',age=10));e.bbo._latest_local=None
 e.apply_s41_manager_command(cmd('context-pending','CLOSE',reason=['PREVIEW_CLOSE_LONG_CONTEXT_EXIT']))
 stop=e.positions['M15'].stop_loss_price
 e.update_from_trade(price=stop,receive_monotonic_ns=time.monotonic_ns(),receive_timestamp=_fresh(0))
 assert not e.pending_exits
 quote(e);e.apply_s41_manager_command(cmd('short','OPEN_SHORT'))
 assert e.positions['M15'].side=='SHORT' and len(e.books.closed_trades())==1


def test_same_engine_two_feed_threads_close_once(cfg):
 from concurrent.futures import ThreadPoolExecutor
 e=_engine(cfg[0]);quote(e);e.apply_s41_manager_command(cmd('long','OPEN_LONG',age=10));e.bbo._latest_local=None
 e.apply_s41_manager_command(cmd('pending','CLOSE',reason=['PREVIEW_CLOSE_LONG_CONTEXT_EXIT']))
 with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:quote(e),range(2)))
 assert len(e.books.closed_trades())==1
 assert len([x for x in e.books.read_all('fills') if x['action']=='EXIT'])==1
