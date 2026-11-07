import json,time
from pathlib import Path
from types import SimpleNamespace
import pytest,requests
from btc_ml.trading.intrabar_paper.execution_market_backfill import default_fetch_agg_trades
from btc_ml.trading.intrabar_paper.execution_market_state import ExecutionMarketStateMachine
from btc_ml.trading.intrabar_paper.s41_command_consumer import S41CommandConsumer
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'evidence'


def test_rest_error_keeps_exchange_code(monkeypatch):
 j=json.loads((DATA/'official-probes.json').read_text())[0]
 class Response:
  status_code=400;text=j['body']
  def raise_for_status(self):raise requests.HTTPError('400 Client Error',response=self)
 monkeypatch.setattr(requests,'get',lambda *a,**k:Response())
 with pytest.raises(Exception) as ex:default_fetch_agg_trades('BTCUSDT',3428401511,3428401512)
 assert '-4166' in str(ex.value) and '3428401511' in str(ex.value)


def test_error_survives_next_actual_gap():
 m=ExecutionMarketStateMachine(2000,5000);m.on_gap_detected(first_missing=3428401511,last_missing=3474293652)
 error=json.loads((DATA/'official-probes.json').read_text())[0]['body'];m.on_backfill_failed(error)
 m.on_gap_detected(first_missing=3428401511,last_missing=3474293653)
 assert m.last_backfill_error==error
 assert m.unresolved_gap and not m.execution_market_ready_for_entry()

class Bus:
 def __init__(self,rows,root,latest):
  self.rows=rows;self.paths=SimpleNamespace(latest=root/'latest.json');self.paths.latest.write_text(json.dumps(latest,allow_nan=True))
 def pending_for_timeframe(self,tf,processed_command_ids,after_evaluation_timestamp):return [x for x in self.rows if x['timeframe']==tf and x['command_id'] not in processed_command_ids]
class BBO:
 def resolve_live_local_entry_bbo(self,**kw):return (object(),None,0,'local')
class Engine:
 def __init__(self,gap=False):
  self.cfg=SimpleNamespace(timeframes=['M15','M30','H1','H4'],max_bbo_age_ms=2000);self.bbo=BBO();self.calls=[]
  self.execution_market=SimpleNamespace(state=SimpleNamespace(unresolved_gap=gap))
 def execution_market_ready_for_entry(self):return not self.execution_market.state.unresolved_gap
 def apply_s41_manager_command(self,row):self.calls.append(row['command_id']);return {'status':'PROBE_ONLY_NO_TRADE'}

def setup_consumer(tmp_path,gap=False,select=None):
 j=json.loads((DATA/'commands-audit.before.json').read_text());rows=[r for r in j['pending'] if r['intent'].startswith('OPEN')]
 if select:rows=select(rows)
 engine=Engine(gap);bus=Bus(rows,tmp_path,j['latest']);c=S41CommandConsumer(engine,checkpoint_path=tmp_path/'cursor.json',consume_after=None,bus=bus)
 return c,engine,rows

def test_actual_expired_and_superseded_commands_do_not_reach_engine(tmp_path):
 c,e,rows=setup_consumer(tmp_path,select=lambda rs:[r for r in rs if r['command_id'] not in {x['command_id'] for x in json.loads((DATA/'commands-audit.before.json').read_text())['latest']['commands'].values()}])
 assert rows;c.poll();assert not e.calls


def test_actual_recovery_backlog_quarantined_durably(tmp_path):
 c,e,rows=setup_consumer(tmp_path,gap=True);assert rows
 acts=c.poll();assert not e.calls
 assert {x['command_id'] for x in acts}=={x['command_id'] for x in rows}
 e.execution_market.state.unresolved_gap=False
 d=S41CommandConsumer(e,checkpoint_path=tmp_path/'cursor.json',consume_after=None,bus=c.bus)
 assert d.poll()==[] and not e.calls


def test_close_leg_is_not_discarded_with_recovery(tmp_path):
 # Original command schema test only: no fake market price, positions or fills.
 row={'command_id':'CLOSE_CONTRACT_TEST','timeframe':'M30','intent':'CLOSE','action_allowed':True}
 e=Engine(True);b=Bus([row],tmp_path,{'commands':{}});c=S41CommandConsumer(e,checkpoint_path=tmp_path/'cursor.json',consume_after=None,bus=b)
 c.poll();assert e.calls==[row['command_id']]

def test_current_real_command_passes_original_ttl_and_identity(tmp_path,monkeypatch):
 import datetime
 j=json.loads((DATA/'commands-audit.before.json').read_text())
 clock=datetime.datetime.fromisoformat(j['asof'])
 class Fixed(datetime.datetime):
  @classmethod
  def now(cls,tz=None):return clock
 monkeypatch.setattr(datetime,'datetime',Fixed)
 current_ids={x['command_id'] for x in j['latest']['commands'].values()}
 c,e,rows=setup_consumer(tmp_path,select=lambda rs:[r for r in rs if r['command_id'] in current_ids]);assert len(rows)==3
 c.poll();assert set(e.calls)=={x['command_id'] for x in rows}
 assert c.poll()==[]

def test_atomic_snapshot_publication_race_retries_not_consumes(tmp_path,monkeypatch):
 import datetime
 j=json.loads((DATA/'commands-audit.before.json').read_text());clock=datetime.datetime.fromisoformat(j['asof'])
 class Fixed(datetime.datetime):
  @classmethod
  def now(cls,tz=None):return clock
 monkeypatch.setattr(datetime,'datetime',Fixed)
 ids={x['command_id'] for x in j['latest']['commands'].values()}
 c,e,rows=setup_consumer(tmp_path,select=lambda rs:[r for r in rs if r['command_id'] in ids]);latest=dict(j['latest']);latest['evaluation_timestamp']='2026-10-04T11:15:00Z';c.bus.paths.latest.write_text(json.dumps(latest));assert c.poll()==[];assert not e.calls
 c.bus.paths.latest.write_text(json.dumps(j['latest']));c.poll();assert len(e.calls)==3

def test_real_archive_catchup_not_mistaken_for_current_market(tmp_path):
 from btc_ml.trading.intrabar_paper.execution_market_processor import ExecutionMarketProcessor
 from btc_ml.trading.intrabar_paper.execution_market_checkpoint import ExecutionMarketCheckpoint
 from btc_ml.trading.intrabar_paper.execution_market_backfill import normalize_rest_agg_trade
 from datetime import datetime,timezone
 rows=json.loads((DATA/'archive-cursor-real-events.json').read_text());row=next(x for x in rows if x['a']==3428401511)
 class ProbeEngine:
  epoch_root=tmp_path
  def update_from_trade(self,**kw):return {'status':'NO_POSITIONS'}
 m=ExecutionMarketStateMachine(2000,5000);m.on_websocket_connected();m.note_book_ticker(receive_monotonic_ns=time.monotonic_ns())
 p=ExecutionMarketProcessor(engine=ProbeEngine(),wal=None,checkpoint=ExecutionMarketCheckpoint('ISOLATED'),state=m)
 evt=normalize_rest_agg_trade(row,symbol='BTCUSDT',connection_session_id='ISOLATED',receive_monotonic_ns=time.monotonic_ns(),receive_timestamp=datetime.now(timezone.utc).isoformat())
 p._dispatch_agg_trade(evt,wal_offset=1)
 assert m.last_confirmed_agg_trade_id==3428401511
 assert not p.execution_market_ready_for_entry()

def test_verified_original_archive_chunk_holds_execution(tmp_path):
 import sys
 sys.path.insert(0,str(ROOT))
 from recovery_chunk import recover_verified_chunk
 from btc_ml.trading.intrabar_paper.execution_market_processor import ExecutionMarketProcessor
 from btc_ml.trading.intrabar_paper.execution_market_checkpoint import ExecutionMarketCheckpoint
 class Engine:
  epoch_root=tmp_path;positions={}
  def update_from_trade(self,**kw):return {'status':'NO_POSITIONS_NO_TRADES'}
 e=Engine();ck=json.loads((DATA/'checkpoint.before.json').read_text());ExecutionMarketCheckpoint.from_dict(ck).save(tmp_path/'execution_market_checkpoint.json')
 p=ExecutionMarketProcessor.create(engine=e,epoch_root=tmp_path,paper_epoch_id=ck['paper_epoch_id'],max_bbo_age_ms=2000,max_agg_trade_age_ms=5000)
 p.state.last_confirmed_agg_trade_id=ck['last_processed_agg_trade_id'];rows=[x for x in json.loads((DATA/'archive-cursor-real-events.json').read_text()) if x['a']>ck['last_processed_agg_trade_id']][:100]
 p.state.on_gap_detected(first_missing=rows[0]['a'],last_missing=rows[-1]['a'])
 accepted=recover_verified_chunk(p,rows,isolated_root=tmp_path);assert accepted==[r['a'] for r in rows];assert p.state.unresolved_gap and not p.execution_market_ready_for_entry()
 assert p.checkpoint.last_processed_agg_trade_id==rows[-1]['a'];before=p.checkpoint_path.read_bytes()
 with pytest.raises(ValueError):recover_verified_chunk(p,rows,isolated_root=tmp_path)
 assert before==p.checkpoint_path.read_bytes()
 remaining=[x for x in json.loads((DATA/'archive-cursor-real-events.json').read_text()) if x['a']>rows[-1]['a']][:20]
 accepted=recover_verified_chunk(p,remaining,isolated_root=tmp_path);assert accepted==[r['a'] for r in remaining]
 with pytest.raises(ValueError):recover_verified_chunk(p,remaining,isolated_root=tmp_path/'wrong')
