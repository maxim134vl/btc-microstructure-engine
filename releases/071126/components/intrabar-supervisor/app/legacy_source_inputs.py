"""Original source records selected by proven local publication availability.

Does not change market measurements, original formulas or core parquet schemas.
Missing publication provenance fails closed; archived root files are never read.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import time

import pandas as pd
from storage.path_registry import LEGACY_SOURCE_FILES, legacy_source_root

FIELDS = {
 'multi_exchange_flow.parquet':['timestamp','exchange','buy_volume','sell_volume','delta','trade_count','avg_price','price_change','efficiency'],
 'volume_clusters.parquet':['buy_volume','sell_volume','delta','trade_count','total_volume'],
 'volume_reactions.parquet':['timestamp','reaction','price_change','delta','volume','delta_efficiency','volume_efficiency'],
 'volume_memory.parquet':['timestamp','current_price','nearest_zone','distance','memory_state'],
 'inventory_states.parquet':['timestamp','price','rolling_delta','rolling_move','inventory_state','confidence'],
 'acceptance_states.parquet':['timestamp','price','state','confidence','rotation'],
 'regime_history.parquet':['timestamp','regime','volatility','pressure'],
}

def utc(value):
    return pd.to_datetime(value, utc=True)

def publication_records(root, name):
    result = []
    for path in sorted((root/'ops/publications').glob(name.removesuffix('.parquet')+'-*.jsonl.gz')):
        # A writer may still be appending its last gzip member. Never use an
        # incomplete line; previous complete publication records remain valid.
        with gzip.open(path, 'rt') as stream:
            try:
                for line in stream:
                    item = json.loads(line)
                    if item.get('file') == name:
                        result.append(item)
            except (EOFError, gzip.BadGzipFile):
                pass
    return result

def select_available(df, publications, name, at):
    at = utc(at)
    if list(df.columns) != FIELDS[name]:
        raise ValueError('Incompatible original source schema: '+name)
    eligible = [p for p in publications if utc(p['available_at']) <= at]
    if name == 'volume_clusters.parquet':
        if not eligible:
            raise RuntimeError('No published cluster generation available at decision time')
        pub = max(eligible, key=lambda p: utc(p['available_at']))
        result = pd.DataFrame(pub['new_rows'], columns=FIELDS[name])
        result.index = pd.Index(pub['cluster_index'], name='price_cluster')
        return result, [pub['available_at']]*len(result)
    availability = {}
    for pub in eligible:
        available = utc(pub['available_at'])
        for row in pub['new_rows']:
            key = (utc(row['timestamp']), row.get('exchange'))
            availability[key] = min(availability.get(key, available), available)
    keys = [(utc(t), ex) for t,ex in zip(df.timestamp, df.exchange if 'exchange' in df else [None]*len(df))]
    times = pd.Series([availability.get(k, pd.NaT) for k in keys], index=df.index, dtype='datetime64[ns, UTC]')
    mask = times.notna() & (times <= at) & (utc(df.timestamp) <= at)
    if name == 'multi_exchange_flow.parquet':
        mask &= df.exchange == 'BINANCE'
    result = df.loc[mask].copy()
    selected = times.loc[mask]
    if result.empty:
        raise RuntimeError('No provenance-confirmed original source records available at decision time: '+name)
    return result, selected.tolist()

def read_available_source(name, at, *, consumer, audit=True):
    if name not in LEGACY_SOURCE_FILES or legacy_source_root() is None:
        raise ValueError('Original source routing is not configured')
    root = legacy_source_root()
    for attempt in range(3):
        raw = (root/name).read_bytes()  # one atomic inode, not a file bind mount
        sha = hashlib.sha256(raw).hexdigest()
        publications = publication_records(root, name)
        if any(p.get('sha256') == sha for p in publications):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('Source file has no matching completed publication: '+name)
    df = pd.read_parquet(io.BytesIO(raw), use_threads=False)
    result, available = select_available(df, publications, name, at)
    if audit:
        item = dict(consumer=consumer, source=name, source_path=str(root/name),
                    source_sha256=sha, decision_at=str(utc(at)), rows=len(result),
                    latest_observation=str(utc(result.timestamp.max())) if 'timestamp' in result else None,
                    latest_available_at=str(max(map(utc,available))),
                    schema=list(result.columns), source_market='BINANCE_FUTURES',
                    selected_rows_sha256=hashlib.sha256(result.to_json(orient='records',date_format='iso',date_unit='us').encode()).hexdigest())
        folder = Path(os.environ.get('BTC_ML_DATA_ROOT','/app/data'))/'diagnostics/legacy_source_consumption'
        folder.mkdir(parents=True, exist_ok=True)
        # Each consumer subprocess writes its own append-only journal.
        with (folder/(consumer+'.jsonl')).open('a') as fd:
            fd.write(json.dumps(item)+'\n');fd.flush();os.fsync(fd.fileno())
        print('ORIGINAL_SOURCE_CONSUMED '+json.dumps(item), flush=True)
    return result

def read_consumer_source(name, at, *, consumer, original_loader):
    """Keep unconfigured legacy behavior; configured consumers use one store."""
    if legacy_source_root() is None:
        return original_loader(name)
    return read_available_source(name, at, consumer=consumer)
