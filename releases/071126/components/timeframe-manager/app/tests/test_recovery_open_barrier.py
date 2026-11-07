"""Actual engine/consumer safety barrier; fixture signals, no live storage."""
import json
from pathlib import Path
import pytest
from tests.test_live1b_safety_restoration import _engine,quote,cmd,consumer,Bus
from btc_ml.trading.intrabar_paper.s41_command_consumer import S41CommandConsumer
from btc_ml.trading.intrabar_paper.execution_market_state import ExecutionMarketState
from tests.trading.intrabar_paper.test_execution_market_wal import _processor
pytest_plugins=['tests.trading.intrabar_paper.test_context_execution_contract','tests.trading.intrabar_paper.test_execution_market_wal']

def test_barrier_quarantines_all_old_opens_but_keeps_close(cfg,tmp_path):
 e=_engine(cfg[0]);quote(e);assert e.apply_s41_manager_command(cmd('existing','OPEN_LONG',age=10))['status']=='ENTERED'
 rows=[cmd('old-'+tf,'OPEN_SHORT',tf=tf) for tf in e.cfg.timeframes]+[cmd('close','CLOSE',reason=['PREVIEW_CLOSE_LONG_CONTEXT_EXIT'])]
 c=consumer(e,tmp_path,rows);fence=c.quarantine_recovery_backlog()
 assert set(fence['open_command_ids'])=={'old-'+tf for tf in e.cfg.timeframes}
 assert 'close' not in c._state['processed_command_ids']
 assert c.poll()[0]['status']=='EXITED' and not e.positions
 assert len(e.books.closed_trades())==1 and c.poll()==[]


def test_old_open_delivered_after_fence_still_blocked_and_new_open_can_enter(cfg,tmp_path):
 e=_engine(cfg[0]);quote(e);c=consumer(e,tmp_path,[]);c.quarantine_recovery_backlog()
 old=cmd('late-historical','OPEN_LONG',age=100);c.bus.rows=[old];c.bus.paths.latest.write_text(json.dumps({'evaluation_timestamp':old['evaluation_timestamp'],'commands':{'M15':old}}))
 assert c.poll()[0]['status']=='ENTRY_BLOCKED_RECOVERY_BARRIER';assert not e.positions
 from tests.trading.intrabar_paper.test_context_execution_contract import _fresh
 new=cmd('after-fence','OPEN_LONG');new['evaluation_timestamp']=_fresh(0)
 c.bus.rows=[new];c.bus.paths.latest.write_text(json.dumps({'evaluation_timestamp':new['evaluation_timestamp'],'commands':{'M15':new}}))
 assert c.poll()[0]['status']=='ENTERED' and len(e.books.open_positions())==1


def test_interrupted_fence_resume_deduplicates_diagnostics(cfg,tmp_path,monkeypatch):
 e=_engine(cfg[0]);rows=[cmd('historical','OPEN_LONG')];c=consumer(e,tmp_path,rows)
 original=c._save
 monkeypatch.setattr(c,'_save',lambda:(_ for _ in ()).throw(OSError('cursor publication interrupted')))
 with pytest.raises(OSError):c.quarantine_recovery_backlog()
 assert c._open_block_reason(rows[0])=='ENTRY_BLOCKED_RECOVERY_BARRIER_INCOMPLETE'
 d=consumer(e,tmp_path,rows);d.quarantine_recovery_backlog();assert d.poll()==[]
 records=[json.loads(x) for x in (tmp_path/'s41_command_rejections.jsonl').read_text().splitlines()]
 assert len(records)==1 and records[0]['command_id']=='historical';assert not e.positions


def test_failed_barrier_cannot_clear_recovering_or_ack_healthy(env):
 p=_processor(env);p.state.on_gap_detected(first_missing=101,last_missing=102)
 p.recovery_barrier=lambda:(_ for _ in ()).throw(OSError('quarantine fsync failed'))
 with pytest.raises(OSError):p._resolve_gap(last_confirmed=103)
 assert p.state.unresolved_gap and p.state.state==ExecutionMarketState.UNSAFE and p._halted
 assert not p.execution_market_ready_for_entry()


def test_corrupt_or_foreign_barrier_fails_closed(cfg,tmp_path):
 e=_engine(cfg[0]);c=consumer(e,tmp_path,[]);c.quarantine_path.write_text('not-json')
 with pytest.raises(ValueError):consumer(e,tmp_path,[])
 c.quarantine_path.write_text(json.dumps({'schema_version':'s41_recovery_open_barrier_v1','cutoff':'2026-01-01T00:00:00Z','paper_epoch_id':'OTHER'}))
 with pytest.raises(ValueError):consumer(e,tmp_path,[])
