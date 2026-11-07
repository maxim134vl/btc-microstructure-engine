"""Original engine economy across staged commit failures; fixture prices only."""
from dataclasses import replace
import json
import pytest
from tests.trading.intrabar_paper.test_context_execution_contract import _engine,_start,_end,_flip,_fresh
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.sleeves import SleeveLedger
pytest_plugins=['tests.trading.intrabar_paper.test_context_execution_contract']

def setup(c):
 e=_engine(c)
 SleeveLedger.initialize(epoch_id=e.epoch.paper_epoch_id,epoch_root=e.epoch_root,initial_equity_usd=100000,risk_pct_by_timeframe={'M15':.005,'M30':.005,'H1':.01,'H4':.01})
 return IntrabarPaperEngine(cfg=c,epoch=e.epoch,activation_monotonic_ns=1000000)

def operation(e,kind,price=None):
 if kind=='OPEN':return e.process_context_event(_start(eid='target',episode='episode',mono=4000000))
 if kind=='CLOSE':return e.process_context_event(_end(eid='target',episode='episode',mono=4000000,occurrence_ts=_fresh(10)))
 if kind=='FLIP':return e.process_context_event(_flip(eid='target',episode='episode',mono=4000000,occurrence_ts=_fresh(10)))
 if price is None:
  p=e.positions['M15'];price=p.stop_loss_price if kind=='SL' else p.take_profit_price
 return e.update_from_trade(price=price,receive_monotonic_ns=5000000,source_event_id='agg_target',receive_timestamp=_fresh(0))

def seed(e,kind):
 if kind!='OPEN':assert e.process_context_event(_start(eid='seed',episode='episode',mono=2000000))[0]['status']=='ENTERED'

def signature(e):
 numeric=('entry_price','exit_price','quantity','gross_pnl_usd','net_pnl_usd','entry_fee_usd','exit_fee_usd','fees_usd','slippage_usd','risk_amount_usd','r_multiple_net')
 return {'counts':{t:e.books.count(t) for t in ('orders','fills','trades','positions')},'equity':e.equity,'realized_pnl':e.realized_pnl,'positions':{tf:p.side for tf,p in e.positions.items()},'trades':[{k:r[k] for k in numeric if k in r} for r in e.books.read_all('trades')],'sleeves':{tf:{k:v for k,v in s.to_dict().items() if k not in ('last_realized_update_at','open_position_id','epoch_id')} for tf,s in e.sleeves.sleeves.items()}}

@pytest.mark.parametrize('kind',['OPEN','CLOSE','FLIP','SL','TP'])
@pytest.mark.parametrize('phase',['before_intent','after_intent','book:fills','book:positions','document:context_consumer_checkpoint.json','before_receipt','after_receipt'])
def test_original_economy_restart_every_stage(cfg,tmp_path,kind,phase):
 c=cfg[0];baseline_cfg=replace(c,books_root=tmp_path/'reference/books',epochs_root=tmp_path/'reference/epochs')
 baseline=setup(baseline_cfg);seed(baseline,kind);operation(baseline,kind);expected=signature(baseline)
 e=setup(c);seed(e,kind)
 price=(e.positions["M15"].stop_loss_price if kind=="SL" else e.positions["M15"].take_profit_price) if kind in {"SL","TP"} else None
 prefix={p.name:p.read_bytes() for p in e.books.root.glob('*.jsonl')}
 def crash(at):
  if at==phase:raise SystemExit('isolated:'+at)
 e.books.commit._phase=crash
 with pytest.raises(SystemExit):operation(e,kind,price)
 d=IntrabarPaperEngine(cfg=c,epoch=e.epoch,activation_monotonic_ns=1000000)
 operation(d,kind,price)
 assert signature(d)==expected
 frozen={p.name:p.read_bytes() for p in d.books.root.glob('*.jsonl')}
 for name,old in prefix.items():assert frozen[name].startswith(old)
 d=IntrabarPaperEngine(cfg=c,epoch=e.epoch,activation_monotonic_ns=1000000);operation(d,kind,price)
 assert signature(d)==expected
 assert frozen=={p.name:p.read_bytes() for p in d.books.root.glob('*.jsonl')}
 for table in ('orders','fills','trades'):
  rows=d.books.read_all(table);ids=[r.get(table[:-1]+'_id') for r in rows]
  assert len(ids)==len(set(ids))


def test_journal_and_health_cannot_publish_over_unresolved_commit(cfg,monkeypatch):
 import threading
 from concurrent.futures import ThreadPoolExecutor
 e=setup(cfg[0]);entered=threading.Event();release=threading.Event();poll_started=threading.Event();health_started=threading.Event()
 def phase(at):
  if at=="after_intent":entered.set();assert release.wait(5)
 e.books.commit._phase=phase
 monkeypatch.setattr(e,"_drain_journal_observe_only",lambda:poll_started.set() or [])
 from dataclasses import replace
 e.cfg=replace(e.cfg,entry_source="s41_command_bus")
 with ThreadPoolExecutor(3) as pool:
  opening=pool.submit(e.process_context_event,_start(eid="concurrent",episode="episode",mono=2000000));assert entered.wait(5)
  poll=pool.submit(e.poll_context_journal)
  def read_health():health_started.set();return e.health()
  health=pool.submit(read_health);assert health_started.wait(5)
  assert not poll_started.wait(.05) and not health.done()
  release.set();assert opening.result(5)[0]["status"]=="ENTERED";assert poll.result(5)==[];assert health.result(5)["active_positions_by_timeframe"]
 assert len(e.books.open_positions())==1 and len(e.books.read_all("fills"))==1
