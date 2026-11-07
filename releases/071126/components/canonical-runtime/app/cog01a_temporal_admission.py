"""COG-01A: explicit, fail-closed historical data admission.

This module is an authorization boundary, not a market-data repair utility.
Never replace publication availability with a candle's event timestamp or file mtime.
A pass requires the exact files identified in an evidence manifest, matching SHA256,
a publication/availability timestamp and (for candles) their confirmed close time.
Computational runs are not granted historical authority.
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = {
    'volume_memory.parquet': 'FUTURES',
    'regime_history.parquet': 'FUTURES',
    'volume_reactions.parquet': 'FUTURES',
    'acceptance_states.parquet': 'FUTURES',
    'inventory_states.parquet': 'FUTURES',
    'live_market_feed.parquet': 'SPOT_CLOSED_BAR',
    'htf_structure_memory.parquet': 'HTF',
    'htf_ltf_context_memory.parquet': 'HTF',
    'auction_synthesis_memory.parquet': 'AUCTION',
}
ALLOWED_AUTHORITIES = {
    'FUTURES': {'ORIGINAL_CAPTURED_FUTURES_PUBLICATION'},
    'SPOT_CLOSED_BAR': {'ORIGINAL_CAPTURED_SPOT_PUBLICATION'},
    'HTF': {'ORIGINAL_CAPTURED_HTF_PUBLICATION'},
    'AUCTION': {'ORIGINAL_CAPTURED_AUCTION_PUBLICATION'},
}
MAX_FILE_BYTES = 120_000_000

class HistoricalAdmissionDenied(RuntimeError):
    pass

def parse_utc(value, label):
    if not isinstance(value, str) or not value.strip():
        raise HistoricalAdmissionDenied('UNPROVEN_TIMESTAMP:'+label)
    try:
        v=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as e:
        raise HistoricalAdmissionDenied('INVALID_TIMESTAMP:'+label) from e
    if v.tzinfo is None or v.utcoffset() is None:
        raise HistoricalAdmissionDenied('NAIVE_TIMESTAMP:'+label)
    return v.astimezone(timezone.utc)

def sha256_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while True:
            block=f.read(1<<20)
            if not block:break
            h.update(block)
    return h.hexdigest()

def evaluate_sources(evidence, *, cutoff):
    at=parse_utc(cutoff,'evaluation_at')
    if not isinstance(evidence,dict) or set(evidence)!=set(REQUIRED):
        raise HistoricalAdmissionDenied('MISSING_OR_EXTRA_SOURCE_RECEIPTS')
    results={}
    for name,kind in REQUIRED.items():
        record=evidence[name]
        if not isinstance(record,dict):
            raise HistoricalAdmissionDenied('INVALID_RECEIPT:'+name)
        authority=record.get('authority')
        if authority not in ALLOWED_AUTHORITIES[kind]:
            raise HistoricalAdmissionDenied('UNPROVEN_AUTHORITY:'+name)
        event=parse_utc(record.get('event_at'),name+':event_at')
        available=parse_utc(record.get('available_at'),name+':available_at')
        if event>at or available>at:
            raise HistoricalAdmissionDenied('FUTURE_EVENT_OR_PUBLICATION:'+name)
        if available<event:
            raise HistoricalAdmissionDenied('PUBLICATION_BEFORE_EVENT:'+name)
        if kind in ('SPOT_CLOSED_BAR','HTF'):
            closed=parse_utc(record.get('closed_at'),name+':closed_at')
            if closed>available or closed>at or closed<event:
                raise HistoricalAdmissionDenied('UNCONFIRMED_CLOSED_BAR:'+name)
        if kind=='AUCTION':
            processed=parse_utc(record.get('processed_at'),name+':processed_at')
            if processed>available or processed>at or processed<event:
                raise HistoricalAdmissionDenied('LATE_AUCTION_PROCESSING:'+name)
        raw_path=record.get('path')
        expected=record.get('sha256')
        if not isinstance(raw_path,str) or not Path(raw_path).is_absolute():
            raise HistoricalAdmissionDenied('SOURCE_PATH_NOT_ABSOLUTE:'+name)
        path=Path(raw_path)
        if path.is_symlink() or not path.is_file():
            raise HistoricalAdmissionDenied('SOURCE_MISSING_OR_LINKED:'+name)
        if path.stat().st_size>MAX_FILE_BYTES or not isinstance(expected,str) or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
            raise HistoricalAdmissionDenied('UNVERIFIABLE_SOURCE_SHA:'+name)
        if sha256_file(path)!=expected:
            raise HistoricalAdmissionDenied('SOURCE_SHA_MISMATCH:'+name)
        # The receipt must tie a real file to an as-of decision; no .mtime fallback.
        results[name]={'authority':authority,'event_at':event.isoformat(),
                       'available_at':available.isoformat(),'sha256':expected}
    return {'historical_authority':'ELIGIBLE_FOR_ASOF_DATA_USE',
            'evaluation_at':at.isoformat(),'sources':results}

def enforce_stage2_admission_from_environment():
    mode=os.environ.get('BTC_ML_COG01A_MODE','COMPUTATIONAL_TEST')
    if mode=='COMPUTATIONAL_TEST':
        print('COG01A_HISTORICAL_AUTHORITY=DENIED mode=COMPUTATIONAL_TEST',flush=True)
        return {'historical_authority':'DENIED'}
    if mode!='HISTORICAL_ASOF':
        raise HistoricalAdmissionDenied('INVALID_COG01A_MODE')
    path=os.environ.get('BTC_ML_COG01A_MANIFEST')
    if not path or not Path(path).is_absolute():
        raise HistoricalAdmissionDenied('HISTORICAL_PROVENANCE_MANIFEST_REQUIRED')
    cutoff=os.environ.get('BTC_ML_COG01A_EVALUATION_AT')
    if not cutoff:
        raise HistoricalAdmissionDenied('HISTORICAL_EVALUATION_AT_REQUIRED')
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>1024*1024:
        raise HistoricalAdmissionDenied('INVALID_HISTORICAL_MANIFEST')
    doc=json.loads(p.read_text())
    if not isinstance(doc,dict) or doc.get('mode')!='HISTORICAL_ASOF' or doc.get('evaluation_at')!=cutoff:
        raise HistoricalAdmissionDenied('MANIFEST_MODE_OR_CUTOFF_MISMATCH')
    result=evaluate_sources(doc.get('sources'),cutoff=cutoff)
    print('COG01A_ASOF_DATA_ELIGIBLE evaluation_at='+result['evaluation_at'],flush=True)
    return result
