"""Load only owner functions into an isolated root; no startup/WS/process loop.

The two existing Parquet writer bodies run unchanged against fixture paths.
The metadata publisher is an observed boundary stub; it issues no LIVE_WRITER
metadata/permission in fixtures or in the unpublished data candidate.
"""
import ast
from contextlib import contextmanager
from datetime import datetime
import importlib.util
import os
from pathlib import Path
import sys
import threading
import types
from unittest.mock import patch

import pandas as pd

CASE=Path('/fixtures/feed')
SOURCE=Path('/app')
AUDIT=SOURCE
spec=importlib.util.spec_from_file_location('feed_gap_recovery',SOURCE/'feed_gap_recovery.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
sys.modules['feed_gap_recovery']=R


def functions(path,names,ns):
    tree=ast.parse(Path(path).read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(nodes)==len(names)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),ns)


@contextmanager
def owner(root,initial):
    root=Path(root); data=root/'data/live';data.mkdir(parents=True,exist_ok=True)
    file=data/'live_market_feed.parquet';initial.to_parquet(file,index=False)
    registry=types.ModuleType('storage.path_registry')
    registry.CANONICAL_LIVE_FEED_PATH='data/live/live_market_feed.parquet'
    registry.resolve_write=lambda name:str(file)
    metadata=types.ModuleType('runtime_dataset_metadata'); calls=[]
    metadata.emit_metadata_for_path=lambda *a,**kw:calls.append((a,kw)) or {'ok':True}
    recovery=R.FeedRecovery(data/'feed_recovery_state.json')
    writer_ns=dict(pd=pd,os=os,datetime=datetime,MAX_ROWS_PER_FILE=50000)
    functions(AUDIT/'parquet_writer_v2.py',{'get_daily_file','append_parquet'},writer_ns)
    paths_ns=dict(os=os,pd=pd,LEGACY_PARTITION_DIR=str(data/'partitions'),
        _CANONICAL_LEGACY_MIRROR=str(data/'latest.parquet'),LEGACY_LIVE_FEED_PATH=str(data/'latest.parquet'),
        CANONICAL_LIVE_FEED_PATH=registry.CANONICAL_LIVE_FEED_PATH,resolve_write=registry.resolve_write)
    functions(AUDIT/'live_feed_paths.py',{'write_live_feed_snapshot'},paths_ns)
    ns=dict(pd=pd,os=os,sys=sys,Path=Path,datetime=datetime,
        _write_lock=threading.Lock(),_catch_up_lock=threading.Lock(),
        _recovery=recovery,_message_count=0,symbol='btcusdt',interval='15m',MAX_ROWS=50000,
        DATASET_PATH=str(data/'partitions'),WRITE_AUDIT_PATH=str(root/'audit.jsonl'),
        last_closed_timestamp=initial.iloc[-1]['timestamp'] if len(initial) else None,
        read_live_feed=lambda:pd.read_parquet(file),
        append_parquet=writer_ns['append_parquet'],write_live_feed_snapshot=paths_ns['write_live_feed_snapshot'],
        _safe_heartbeat=lambda **kw:None,_log=lambda text:None,
        fetch_closed_rows=R.fetch_closed_rows,__file__=str(root/'live_binance_feed_v2.py'))
    functions(SOURCE/'live_binance_feed_v2.py',{'_feed_opens','_audit_write','safe_append_candle','catch_up_closed_klines'},ns)
    recovery.reconcile(ns['_feed_opens'](initial))
    with patch.dict(sys.modules,{'storage.path_registry':registry,'runtime_dataset_metadata':metadata}):
        yield ns,file,calls
