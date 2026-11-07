"""Causal protective replay contract; synthetic price fixture, real engine."""
from datetime import datetime,timedelta,timezone
import pytest
from tests.trading.intrabar_paper.test_protective_ignores_pre_entry_tape import _engine,_start
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine

@pytest.mark.parametrize('restart',[False,True])
def test_recovered_print_before_book_open_cannot_close_position(tmp_path,restart):
 e=_engine(tmp_path);_start(e)
 row=e.books.open_positions()[0];opened=datetime.fromisoformat(row['opened_at'].replace('Z','+00:00'))
 if restart:e=IntrabarPaperEngine(cfg=e.cfg,epoch=e.epoch)
 p=e.positions['M15'];before={x.name:x.read_bytes() for x in e.books.root.glob('*.jsonl')}
 result=e.update_from_trade(price=p.stop_loss_price-.5,receive_monotonic_ns=9000000,receive_timestamp=(opened+timedelta(minutes=12)).isoformat(),source_event_id='pre-open-actual-book-clock',market_provenance={'exchange_trade_timestamp':int((opened-timedelta(minutes=4)).timestamp()*1000),'backfill':True,'aggregate_trade_id':3446452763})
 assert result==[] and 'M15' in e.positions
 assert before=={x.name:x.read_bytes() for x in e.books.root.glob('*.jsonl')}
 live=e.update_from_trade(price=p.stop_loss_price-.5,receive_monotonic_ns=10000000,receive_timestamp=(opened+timedelta(seconds=8)).isoformat(),source_event_id='after-open',market_provenance={'exchange_trade_timestamp':int((opened+timedelta(seconds=8)).timestamp()*1000),'backfill':False,'aggregate_trade_id':3446459000})
 assert live[0]['status']=='EXITED' and not e.positions
 assert len(e.books.closed_trades())==1
