"""Strict contract: intentionally exposes the inherited partial engine commit defect."""
import json,time,os
from pathlib import Path
import pytest
from tests.test_live1b_safety_restoration import quote,cmd
from tests.trading.intrabar_paper.test_context_execution_contract import _engine
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.execution_market_processor import ExecutionMarketProcessor,normalize_futures_agg_trade
pytest_plugins=['tests.trading.intrabar_paper.test_context_execution_contract']

def test_crash_after_trade_row_before_position_close_cannot_execute_twice(cfg,monkeypatch):
 e=_engine(cfg[0]);quote(e);assert e.apply_s41_manager_command(cmd('entry','OPEN_LONG',age=10))['status']=='ENTERED'
 p=ExecutionMarketProcessor.create(engine=e,epoch_root=e.epoch_root,paper_epoch_id=e.epoch.paper_epoch_id,max_bbo_age_ms=2000,max_agg_trade_age_ms=5000)
 stop=e.positions['M15'].stop_loss_price
 event=normalize_futures_agg_trade({'a':123456,'p':str(stop),'q':'0.01','T':int(time.time_ns()/1e6),'m':False},symbol='BTCUSDT',connection_session_id='ISOLATED_CRASH_CONTRACT',receive_monotonic_ns=time.monotonic_ns(),receive_timestamp='2026-10-04T12:00:00Z')
 append=e.books.append
 def crash(table,row):
  if table=='positions' and row.get('status')=='CLOSED':raise SystemExit('CRASH_AFTER_TRADE_BEFORE_CLOSED_POSITION')
  return append(table,row)
 monkeypatch.setattr(e.books,'append',crash)
 with pytest.raises(SystemExit):p._persist_and_dispatch_agg_trade(event)
 before={'trades':len(e.books.read_all('trades')),'exit_fills':len([r for r in e.books.read_all('fills') if r['action']=='EXIT']),'checkpoint_exists':p.checkpoint_path.exists()}
 d=IntrabarPaperEngine(cfg=cfg[0],epoch=e.epoch)
 again=ExecutionMarketProcessor.create(engine=d,epoch_root=e.epoch_root,paper_epoch_id=e.epoch.paper_epoch_id,max_bbo_age_ms=2000,max_agg_trade_age_ms=5000)
 after={'trades':len(d.books.read_all('trades')),'exit_fills':len([r for r in d.books.read_all('fills') if r['action']=='EXIT']),'checkpoint':again.checkpoint.to_dict(),'same_position_ids':[r['position_id'] for r in d.books.read_all('trades')]}
 if os.environ.get('EVIDENCE_DIR'):
  Path(os.environ['EVIDENCE_DIR']).joinpath('engine-partial-commit-crash.json').write_text(json.dumps({'before':before,'after':after,'isolated_test_price':stop,'real_market_proof':False},indent=2))
 assert after['trades']==1, 'Partial engine commit replayed the same position exit twice'
 assert after['exit_fills']==1
