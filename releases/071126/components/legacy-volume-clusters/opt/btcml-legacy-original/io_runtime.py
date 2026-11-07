"""Operational I/O only. Original algorithm files are verified and executed unchanged."""
import builtins, datetime, fcntl, gzip, hashlib, io, json, os, pathlib, runpy, sys, time, uuid
import numpy as np
import pandas as pd
import requests

FIELDS = {
 'multi_exchange_flow.parquet':['timestamp','exchange','buy_volume','sell_volume','delta','trade_count','avg_price','price_change','efficiency'],
 'volume_clusters.parquet':['buy_volume','sell_volume','delta','trade_count','total_volume'],
 'volume_reactions.parquet':['timestamp','reaction','price_change','delta','volume','delta_efficiency','volume_efficiency'],
 'volume_memory.parquet':['timestamp','current_price','nearest_zone','distance','memory_state'],
 'inventory_states.parquet':['timestamp','price','rolling_delta','rolling_move','inventory_state','confidence'],
 'acceptance_states.parquet':['timestamp','price','state','confidence','rotation'],
 'regime_history.parquet':['timestamp','regime','volatility','pressure']}
READ = pd.read_parquet
WRITE = pd.DataFrame.to_parquet
REPLACE = os.replace
SEND = requests.Session.send
PRINT = builtins.print
ROOT = pathlib.Path.cwd()
AUDIT = ROOT / 'ops'
INPUTS = {}
HTTP = {}
SERVICE = ''
OUTPUT = ''
PENDING = {}
# Optional in-process shared snapshot reader; standalone native I/O is unchanged.
READ_SNAPSHOT = None

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def atomic_bytes(path, raw):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with open(tmp, 'wb') as fd:
            fd.write(raw); fd.flush(); os.fsync(fd.fileno())
        REPLACE(tmp, path); fsync_dir(path.parent)
    finally:
        if tmp.exists(): tmp.unlink()

def log(kind, data):
    folder = AUDIT / kind; folder.mkdir(parents=True, exist_ok=True)
    record = {'logged_at':utc(), 'service':SERVICE, **data}
    path = folder / (SERVICE + '-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d') + '.jsonl.gz')
    # One gzip member per record: completed members remain readable across process restarts.
    raw = gzip.compress((json.dumps(record, default=str, allow_nan=False) + '\n').encode())
    with open(path, 'ab') as fd:
        fd.write(raw); fd.flush(); os.fsync(fd.fileno())
    return record

def status(**changes):
    path = AUDIT / 'status' / (SERVICE + '.json')
    try: state = json.loads(path.read_text())
    except FileNotFoundError: state = {}
    state.update(changes); state.update(service=SERVICE, updated_at=utc(), pid=os.getpid())
    atomic_bytes(path, json.dumps(state, default=str, allow_nan=False).encode())

def validate(df, name):
    if list(df.columns) != FIELDS[name] or df.empty:
        raise ValueError('Empty or incompatible original schema: ' + name)
    if df.isna().any().any(): raise ValueError('Missing values: ' + name)
    numeric = df.select_dtypes(include='number')
    if not np.isfinite(numeric.to_numpy()).all(): raise ValueError('Non-finite values: ' + name)
    if name == 'volume_clusters.parquet':
        if df.index.name != 'price_cluster' or df.index.has_duplicates:
            raise ValueError('Invalid cluster index')
    else:
        if not df.timestamp.is_monotonic_increasing: raise ValueError('Unordered timestamps')
        keys = ['timestamp','exchange'] if name == 'multi_exchange_flow.parquet' else ['timestamp']
        if df.duplicated(keys).any(): raise ValueError('Duplicate timestamps')

def read(path, *args, **kwargs):
    name = pathlib.Path(path).name if isinstance(path, (str, os.PathLike)) else ''
    if name not in FIELDS: return READ(path, *args, **kwargs)
    # Reading one inode guarantees audit and algorithm see exactly the same bytes.
    if name == 'multi_exchange_flow.parquet' and READ_SNAPSHOT is not None and not args and not kwargs:
        raw_sha, df = READ_SNAPSHOT(path, READ)
    else:
        raw = pathlib.Path(path).read_bytes()
        raw_sha = None
        df = READ(io.BytesIO(raw), *args, **kwargs)
    if name != OUTPUT:
        if name == 'multi_exchange_flow.parquet':
            market = df[df.exchange == 'BINANCE']
            latest = pd.Timestamp(market.timestamp.max()).tz_localize('UTC').timestamp()
            if len(market) < 21 or not 0 <= time.time() - latest <= 120:
                raise RuntimeError('Upstream BINANCE data is stale or still warming up')
        captured = df[df.exchange == 'BINANCE'].sort_values('timestamp').tail(500) if name == 'multi_exchange_flow.parquet' else df
        buf = io.BytesIO(); WRITE(captured, buf)
        audit_raw = buf.getvalue(); audit_hash = digest(audit_raw)
        capture_path = AUDIT / 'inputs' / (audit_hash + '.parquet')
        if not capture_path.exists(): atomic_bytes(capture_path, audit_raw)
        INPUTS[name] = {'read_at':utc(), 'sha256':raw_sha if raw_sha is not None else digest(raw), 'capture_sha256':audit_hash,
                       'rows':len(df), 'captured_rows':len(captured),
                       'last_observation':str(captured.timestamp.max()) if 'timestamp' in captured else None}
    return df

def preserve_history(df, name):
    path = ROOT / name
    durable_marker = AUDIT / 'published' / (name + '.json')
    if not path.exists():
        if durable_marker.exists(): raise RuntimeError('Refusing to recreate missing published history: ' + name)
        return 0
    previous = READ(path)
    validate(previous, name)
    if name == 'volume_clusters.parquet': return 0
    if name == 'multi_exchange_flow.parquet':
        # The original collector deliberately retains only its latest 100000 rows.
        cutoff = previous.timestamp.max()
        overlap = previous[previous.timestamp >= df.timestamp.min()].reset_index(drop=True)
        retained = df[df.timestamp <= cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(overlap, retained, check_dtype=False)
        return int((df.timestamp <= cutoff).sum())
    if len(df) < len(previous): raise RuntimeError('Refusing history truncation: ' + name)
    pd.testing.assert_frame_equal(previous.reset_index(drop=True), df.iloc[:len(previous)].reset_index(drop=True), check_dtype=False)
    return len(previous)

def publication(df, name, added_from):
    row = df.iloc[-1].to_dict() if 'timestamp' in df else None
    return {'file':name, 'available_at':utc(), 'rows':len(df), 'last_row':row,
            'inputs':dict(INPUTS), 'sources':dict(HTTP),
            'new_rows':json.loads(df.iloc[added_from:].to_json(orient='records',date_format='iso',date_unit='us')),
            'cluster_index':df.index.tolist() if name == 'volume_clusters.parquet' else None}

def committed(path, details):
    name = details['file']
    details['available_at'] = utc()
    details['sha256'] = digest(pathlib.Path(path).read_bytes())
    log('publications', details)
    atomic_bytes(AUDIT / 'published' / (name + '.json'), json.dumps(details, default=str, allow_nan=False).encode())
    status(last_success_at=details['available_at'], last_output=name, last_rows=details['rows'],
           last_error=None, inputs=details['inputs'], sources=details['sources'])
    INPUTS.clear()

def write(df, path, *args, **kwargs):
    name = pathlib.Path(path).name if isinstance(path, (str, os.PathLike)) else ''
    logical = name[:-4] if name.endswith('.parquet.tmp') else name
    if logical not in FIELDS: return WRITE(df, path, *args, **kwargs)
    try:
        validate(df, logical)
        added_from = preserve_history(df, logical)
        target = pathlib.Path(path)
        tmp = target.with_name('.' + target.name + '.' + uuid.uuid4().hex)
        try:
            WRITE(df, tmp, *args, **kwargs)
            roundtrip = READ(tmp)
            validate(roundtrip, logical)
            if kwargs.get('index') is False:
                pd.testing.assert_frame_equal(df.reset_index(drop=True), roundtrip.reset_index(drop=True), check_dtype=False)
            else:
                pd.testing.assert_frame_equal(df, roundtrip, check_dtype=False)
            with open(tmp, 'rb') as fd: os.fsync(fd.fileno())
            REPLACE(tmp, target); fsync_dir(target.parent)
        finally:
            if tmp.exists(): tmp.unlink()
        details = publication(df, logical, added_from)
        if name.endswith('.parquet.tmp'): PENDING[str(path)] = details
        else: committed(target, details)
    except Exception as ex:
        log('errors', {'kind':'publication_failed','file':logical,'type':type(ex).__name__,'reason':str(ex)})
        status(last_error=str(ex), last_error_at=utc())
        raise

def replace(src, dst, *args, **kwargs):
    result = REPLACE(src, dst, *args, **kwargs)
    if str(src) in PENDING:
        fsync_dir(pathlib.Path(dst).parent)
        committed(dst, PENDING.pop(str(src)))
    return result

def send(session, request, **kwargs):
    source = 'BINANCE' if 'fapi.binance.com' in request.url else 'BYBIT' if 'api.bybit.com' in request.url else 'HYPERLIQUID'
    started = utc()
    try:
        response = SEND(session, request, **kwargs)
        payload = response.json()
        records = payload.get('result', {}).get('list', []) if source == 'BYBIT' else payload
        good = response.status_code == 200 and isinstance(records, list) and len(records) > 0
        if source == 'BYBIT': good = good and payload.get('retCode') == 0
        times = [int(t['time']) for t in records] if isinstance(records, list) else []
        info = log('http', {'source':source,'started_at':started,'response_at':utc(),
                           'http_status':response.status_code,'ok':good,'payload':payload,
                           'event_min_ms':min(times) if times else None,'event_max_ms':max(times) if times else None})
        HTTP[source] = {k:v for k,v in info.items() if k != 'payload'}
        atomic_bytes(AUDIT / 'sources' / (source + '.json'), json.dumps(HTTP[source],default=str).encode())
        if not good:
            log('errors', {'kind':'source_error', **HTTP[source]})
        return response
    except Exception as ex:
        HTTP[source] = {'source':source,'ok':False,'started_at':started,'response_at':utc(),
                        'type':type(ex).__name__,'reason':str(ex)}
        log('errors', {'kind':'source_exception', **HTTP[source]})
        atomic_bytes(AUDIT / 'sources' / (source + '.json'), json.dumps(HTTP[source]).encode())
        raise

def observed_print(*args, **kwargs):
    PRINT(*args, **kwargs)
    text = ' '.join(str(a) for a in args)
    if 'ERROR' in text or 'NO SNAPSHOTS' in text:
        log('errors', {'kind':'original_error_message','message':text})
        status(last_error=text,last_error_at=utc())

def main():
    global SERVICE, OUTPUT
    original, OUTPUT = sys.argv[1:3]
    SERVICE = OUTPUT.removesuffix('.parquet')
    AUDIT.mkdir(exist_ok=True)
    lock = open(AUDIT / (SERVICE + '.lock'), 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest = json.loads(pathlib.Path('/opt/btcml-legacy-original/source_manifest.json').read_text())
    entry = next(e for e in manifest if pathlib.Path(e['git_path']).name.replace('_v2_backup','') == pathlib.Path(original).name)
    if digest(pathlib.Path(original).read_bytes()) != entry['sha256']: raise RuntimeError('Original source hash mismatch')
    status(started_at=utc(), original=original, original_sha256=entry.get('original_sha256', entry['sha256']), executed_sha256=entry['sha256'])
    pd.read_parquet = read
    pd.DataFrame.to_parquet = write
    os.replace = replace
    requests.Session.send = send
    builtins.print = observed_print
    runpy.run_path(original, run_name='__main__')

if __name__ == '__main__': main()
