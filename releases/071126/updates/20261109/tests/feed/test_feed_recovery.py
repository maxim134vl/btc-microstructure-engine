import copy
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from harness import CASE,R,owner

RAW=CASE/'response.json'
ROWS=json.loads(RAW.read_text())
DATE='Mon, 09 Nov 2026 05:39:03 GMT'
BOUNDS=(1794196800000,1794197700000)
WIRE=[r for r in ROWS if BOUNDS[0]<=r[0]<=BOUNDS[1]]
DECODED=R.decode_closed_rows(WIRE,BOUNDS,int(parsedate_to_datetime(DATE).timestamp()*1000))
BASE=pd.read_parquet(CASE/'baseline/feed.parquet')


def candle(row):
    result=dict(row);result['timestamp']=pd.to_datetime(result.pop('open_ms'),unit='ms');return result
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def opens(frame):return [int(pd.Timestamp(x).value//1_000_000) for x in frame.timestamp]
def stamp(s):return int(pd.Timestamp(s).value//1_000_000)


def test_01_normal_sequential_flow(tmp_path):
    prefix=BASE.loc[BASE.timestamp<=pd.Timestamp('2026-11-09T03:30:00')]
    with owner(tmp_path,prefix) as (o,p,_):
        row=BASE.loc[BASE.timestamp==pd.Timestamp('2026-11-09T03:45:00')].iloc[0].to_dict()
        assert o['safe_append_candle'](row)
        s=o['_recovery'].state
        assert s['contiguous_open_ms']==stamp('2026-11-09T03:45Z')==s['max_received_open_ms']
        assert s['missing_ranges']==[]


def test_02_vm_gap_two_closed_bars(tmp_path):
    with owner(tmp_path,BASE) as (o,p,_):
        s=o['_recovery'].state
        assert s['contiguous_open_ms']==stamp('2026-11-09T03:45Z')
        assert s['missing_ranges']==[list(BOUNDS)]
        assert o['_recovery'].next_request(stamp('2026-11-09T08:00Z'))==BOUNDS


def test_03_newer_ws_bar_while_catchup_inflight(tmp_path):
    # Capture starts before the final, already genuine row; network callback adds
    # that row before the earlier historical response returns.
    initial=BASE.iloc[:-1].copy();later=BASE.iloc[-1].to_dict()
    with owner(tmp_path,initial) as (o,p,_):
        def fetch(*args):
            o['safe_append_candle'](later)
            return DECODED,{'url':'saved official fixture','response_date':DATE}
        o['fetch_closed_rows']=fetch
        o['catch_up_closed_klines']()
        result=pd.read_parquet(p)
        pd.testing.assert_frame_equal(result.loc[result.timestamp.isin(BASE.timestamp)].reset_index(drop=True),BASE.reset_index(drop=True))
        assert len(result)==len(BASE)+2 and not o['_recovery'].state['missing_ranges']


def test_04_fill_behind_maximum(tmp_path):
    with owner(tmp_path,BASE) as (o,p,_):
        maximum=o['_recovery'].state['max_received_open_ms']
        for r in DECODED:o['safe_append_candle'](candle(r))
        assert o['_recovery'].state['max_received_open_ms']==maximum
        assert o['_recovery'].state['contiguous_open_ms']==maximum


def test_05_restart_with_unresolved_gap(tmp_path):
    with owner(tmp_path,BASE) as (o,p,_):
        s=copy.deepcopy(o['_recovery'].state)
        again=R.FeedRecovery(o['_recovery'].path)
        again.reconcile(opens(pd.read_parquet(p)))
        assert again.state==s and again.next_request(stamp('2026-11-09T08:00Z'))==BOUNDS


def test_06_unavailable_history_preserves_gap(tmp_path):
    with owner(tmp_path,BASE) as (o,p,_):
        before=sha(p); state=copy.deepcopy(o['_recovery'].state)
        def offline(*args):raise TimeoutError('source unavailable')
        o['fetch_closed_rows']=offline;o['catch_up_closed_klines']()
        assert sha(p)==before
        assert o['_recovery'].state['missing_ranges']==state['missing_ranges']
        assert o['_recovery'].state['contiguous_open_ms']==state['contiguous_open_ms']
        assert 'source unavailable' in o['_recovery'].state['last_request']['error']


def test_07_duplicate_redelivery_no_write(tmp_path):
    with owner(tmp_path,BASE) as (o,p,calls):
        row=candle(DECODED[0]);assert o['safe_append_candle'](row)
        before=sha(p);meta_calls=len(calls)
        assert not o['safe_append_candle'](row)
        assert sha(p)==before and len(calls)==meta_calls
        row['close']+=1
        with pytest.raises(ValueError,match='FEED_CANDLE_CONTENT_CONFLICT'):o['safe_append_candle'](row)
        assert sha(p)==before


def test_08_existing_records_and_frozen_sha_preserved(tmp_path):
    frozen=CASE/'current_input'
    pins={p:sha(p) for p in frozen.iterdir() if p.is_file()}
    baseline_sha=sha(CASE/'baseline/feed.parquet')
    with owner(tmp_path,BASE) as (o,p,_):
        for r in DECODED:o['safe_append_candle'](candle(r))
        result=pd.read_parquet(p)
        pd.testing.assert_frame_equal(result.loc[result.timestamp.isin(BASE.timestamp)].reset_index(drop=True),BASE.reset_index(drop=True))
    assert sha(CASE/'baseline/feed.parquet')==baseline_sha
    assert all(sha(p)==h for p,h in pins.items())


def test_09_contiguous_does_not_cross_one_remaining_gap(tmp_path):
    with owner(tmp_path,BASE) as (o,p,_):
        o['safe_append_candle'](candle(DECODED[1]))
        assert o['_recovery'].state['contiguous_open_ms']==stamp('2026-11-09T03:45Z')
        assert o['_recovery'].state['missing_ranges']==[[BOUNDS[0],BOUNDS[0]]]
        o['safe_append_candle'](candle(DECODED[0]))
        assert o['_recovery'].state['contiguous_open_ms']==o['_recovery'].state['max_received_open_ms']


def test_10_canonical_first_unprocessed_is_0400(tmp_path):
    with owner(tmp_path,BASE) as (o,p,_):
        for r in DECODED:o['safe_append_candle'](candle(r))
        result=pd.read_parquet(p); t=pd.to_datetime(result.timestamp,utc=True)
        cursor=pd.Timestamp('2026-11-09T03:45Z')
        assert list(t[t>cursor].head(3))==list(pd.date_range('2026-11-09T04:00Z',periods=3,freq='15min'))
        accepted=pd.read_parquet(CASE/'current_input/live_market_feed.parquet')
        pd.testing.assert_frame_equal(result.loc[t<=cursor].reset_index(drop=True),accepted.reset_index(drop=True))


def test_11_open_and_wrong_boundary_not_admitted():
    assert R.decode_closed_rows(WIRE,BOUNDS,BOUNDS[0]+R.STEP_MS-1)==[]
    bad=copy.deepcopy(WIRE);bad[0][6]+=1
    with pytest.raises(ValueError,match='BOUNDARY'):R.decode_closed_rows(bad,BOUNDS,stamp('2026-11-09T08:00Z'))


def test_12_snapshot_committed_before_index_crash(tmp_path):
    with owner(tmp_path,BASE) as (o,p,_):
        old_index=o['_recovery'].path.read_bytes()
        for r in DECODED:o['safe_append_candle'](candle(r))
        o['_recovery'].path.write_bytes(old_index)  # Simulated stale derived sidecar only.
        again=R.FeedRecovery(o['_recovery'].path);again.reconcile(opens(pd.read_parquet(p)))
        assert again.state['missing_ranges']==[]
        assert again.state['contiguous_open_ms']==again.state['max_received_open_ms']


def test_13_retention_cannot_erase_unresolved_hole(tmp_path):
    with owner(tmp_path,BASE) as (o,p,_):
        r=o['_recovery']; r.reconcile(opens(BASE.loc[BASE.timestamp>=pd.Timestamp('2026-11-09T04:30')]))
        assert r.state['missing_ranges']==[list(BOUNDS)]
        assert r.state['contiguous_open_ms']==stamp('2026-11-09T03:45Z')


@pytest.mark.parametrize('error_kind',['HTTP451','TLS'])
def test_14_official_transport_failure_no_fallback(tmp_path,monkeypatch,error_kind):
    import ssl
    from urllib.error import HTTPError
    called=[]
    def unavailable(url,**kw):
        called.append(url)
        assert url.startswith('https://data-api.binance.vision/api/v3/klines?')
        assert kw['context'].verify_mode==ssl.CERT_REQUIRED and kw['context'].check_hostname
        assert kw['timeout']==20
        if error_kind=='HTTP451':raise HTTPError(url,451,'restricted',{},None)
        raise ssl.SSLError('handshake failed')
    monkeypatch.setattr(R,'urlopen',unavailable)
    with owner(tmp_path,BASE) as (o,p,_):
        before=sha(p);o['catch_up_closed_klines']()
        assert len(called)==1 and sha(p)==before
        assert o['_recovery'].state['missing_ranges']==[list(BOUNDS)]


def test_16_real_merger_keeps_chronological_history(tmp_path):
    from harness import functions,AUDIT
    with owner(tmp_path,BASE) as (o,p,_):
        for r in DECODED:o['safe_append_candle'](candle(r))
        expected=pd.read_parquet(p).reset_index(drop=True)
        ns=dict(pd=pd,_iter_partition_dirs=lambda:[p.parent/'partitions'],read_live_feed=lambda:pd.read_parquet(p))
        functions(AUDIT/'live_feed_paths.py',{'read_live_feed_history'},ns)
        actual=ns['read_live_feed_history']()
        pd.testing.assert_frame_equal(actual,expected,check_exact=True)
        assert actual.timestamp.is_unique and actual.timestamp.is_monotonic_increasing
