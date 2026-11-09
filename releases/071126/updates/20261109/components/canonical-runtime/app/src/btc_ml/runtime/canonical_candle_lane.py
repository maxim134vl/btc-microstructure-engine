"""One Candle owner and bounded, immutable input generations for Canonical.

Only Feed/Candle input views are scoped. Analytical outputs keep their existing
owners/paths. No Stage2 formula, native producer, receipt or market clock is
changed. Pending generations retain files, never native arrays/DataFrames.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import functools
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import copy
import weakref

ENV = 'BTC_ML_CANDLE_INPUT_GENERATION'
MODE = 'BTC_ML_CANONICAL_CANDLE_LANE'
_scope = ContextVar('canonical_candle_inputs', default=None)
_local = threading.local()
allocation_gate = threading.RLock()
candle_waiting = threading.Event()
candle_done = threading.Event()
candle_done.set()


def enabled():
    return os.environ.get(MODE) == '1'


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _sync(folder):
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _sync(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def _load(path):
    return json.loads(Path(path).read_text())


def _event(event, **fields):
    print(json.dumps({'event': event, 'at': datetime.now(timezone.utc).isoformat(), **fields}), flush=True)


def current():
    item = _scope.get()
    if item is not None:
        return item
    name = os.environ.get(ENV)
    if not name:
        return None
    saved = getattr(_local, 'environment_scope', None)
    if saved is None or saved[0] != name:
        saved = (name, _load(name))
        _local.environment_scope = saved
    return saved[1]


def candle_frame():
    """Reuse the genuine read captured by the Candle owner, not a new clock.

    The saved record was emitted by the unchanged native read helper against
    the public file, before another Candle could replace it. Re-decoding the
    identical retained bytes never creates a new availability/publication.
    Only a weak reference to the caller's active frame is cached.
    """
    item = current()
    if item is None or item.get('role') != 'consumer':
        return None
    import pandas as pd
    import stage2_publication_metadata as H
    key = item['descriptor']
    saved = getattr(_local, 'candle', None)
    frame = saved[1]() if saved is not None and saved[0] == key else None
    if frame is None:
        path = item['inputs']['candle_structure_memory.parquet']
        if _hash(path) != item['generation_id']:
            raise RuntimeError('CANDLE_GENERATION_INPUT_CHANGED')
        cached = getattr(_local, 'read_record', None)
        if cached is None or cached[0] != key:
            cached = (key, _load(item['native_read_record']))
            _local.read_record = cached
        record = cached[1]
        if (record.get('artifact_sha256') != item['generation_id']
                or record.get('reader_helper_source_sha256') != _hash(H.__file__)):
            raise RuntimeError('CANDLE_NATIVE_READ_IMPLEMENTATION_CHANGED')
        frame = pd.read_parquet(path)
        if H.meta_frame_identity(frame)['frame_sha256'] != record['frame_sha256']:
            raise RuntimeError('CANDLE_GENERATION_DECODE_CHANGED')
        frame.attrs[H.META_READ_ATTR] = copy.deepcopy(record)
    else:
        frame = frame.copy()
    _local.candle = (key, weakref.ref(frame))
    return frame


def read_override(filename):
    item = current()
    if item is None:
        return None
    return item['inputs'].get(filename)


def write_override(filename):
    item = current()
    if item is None or filename != 'candle_structure_memory.parquet':
        return None
    if item.get('role') != 'producer':
        raise RuntimeError('CANDLE_HAS_SINGLE_INDEPENDENT_OWNER')
    return item['candidate']


def partition_override():
    # The view is the exact original merged history through the queued CLOSED
    # bar. Do not merge a later live partition back into this immutable view.
    return [] if current() is not None else None


def environment(base=None):
    env = dict(os.environ if base is None else base)
    item = current()  # Preserve the same generation in nested existing workers.
    if item is not None and item.get('descriptor'):
        env[ENV] = item['descriptor']
    else:
        env.pop(ENV, None)
    return env


@contextmanager
def input_scope(item):
    token = _scope.set(item)
    try:
        yield item
    finally:
        _scope.reset(token)


def install_allocation_gate(stage2):
    """No Candle heap expansion while native packets/history are expanded.

    One heavy computation remains. These wrappers change scheduling only; the
    original functions and their source/producer SHA remain unchanged.
    """
    for name in ('build_tf_native_results',):
        original = getattr(stage2, name)
        if getattr(original, '_candle_allocation_gate', False):
            continue
        @functools.wraps(original)
        def guarded(*args, _function=original, **kwargs):
            with allocation_gate:
                return _function(*args, **kwargs)
        guarded._candle_allocation_gate = True
        setattr(stage2, name, guarded)
    original_publish = stage2.publish_tf_native_results
    if not getattr(original_publish, '_candle_allocation_gate', False):
        @functools.wraps(original_publish)
        def publish(frames):
            result = {}
            # Same native owner loop/order, one TF per call. Its previous large
            # history/concat locals are released before the next TF is loaded.
            # A waiting light Candle publication gets the intervening turn.
            for tf, frame in frames.items():
                with allocation_gate:
                    result.update(original_publish({tf: frame}))
                if candle_waiting.is_set():
                    candle_done.wait()
            return result
        publish._candle_allocation_gate = True
        stage2.publish_tf_native_results = publish
    original = stage2._tf_original_source_publication
    if not getattr(original, '_candle_generation_binding', False):
        @functools.wraps(original)
        def publication(read, source_bound):
            item = current()
            if item is None or item.get('role') != 'consumer' or not source_bound:
                return original(read, source_bound)
            recorded = _load(item['native_read_record'])
            for key in ('artifact_sha256', 'artifact_absolute_path', 'frame_sha256', 'decoded_at'):
                if read.get(key) != recorded.get(key):
                    raise RuntimeError('MIXED_CANDLE_INPUT_GENERATION:' + key)
            # Only metadata lookup uses the retained alias. Published provenance
            # retains the genuine original native read record, unchanged.
            lookup = dict(read, artifact_absolute_path=item['inputs']['candle_structure_memory.parquet'])
            return original(lookup, source_bound)
        publication._candle_generation_binding = True
        stage2._tf_original_source_publication = publication


class CandleLane:
    def __init__(self, root, *, pending_limit=2, poll_s=5, produce=None):
        self.root = Path(root).resolve()
        self.home = self.root / 'data/runtime/canonical_candle_lane'
        self.home.mkdir(parents=True, exist_ok=True)
        self.state_path = self.home / 'state.json'
        self.pending_path = self.home / 'pending_publication.json'
        self.limit = pending_limit
        self.poll_s = poll_s
        self.lock = threading.RLock()
        self.changed = threading.Event()
        self.stop_event = threading.Event()
        self.thread = None
        self.fatal = None
        self.producer = produce or self._produce_native
        self.state = _load(self.state_path) if self.state_path.exists() else {
            'schema': 'CANONICAL_CANDLE_INPUT_QUEUE_V1', 'current': None,
            'active': None, 'pending': [], 'cursor': None}
        if not self.state_path.exists():
            public = self.root / 'data/cognition/candle_structure_memory.parquet'
            metadata = Path(str(public) + '.meta.json')
            if self.producer == self._produce_native:
                if not public.exists() or not metadata.exists():
                    raise RuntimeError('CANDLE_EXISTING_CUTOVER_REQUIRED_NO_REPLAY')
                body = _load(metadata)
                if body.get('file_sha256') != _hash(public) or not body.get('latest_timestamp'):
                    raise RuntimeError('CANDLE_EXISTING_CUTOVER_UNBOUND')
                self.state['cutover'] = body['latest_timestamp']
        if self.state.get('schema') != 'CANONICAL_CANDLE_INPUT_QUEUE_V1':
            raise RuntimeError('CANDLE_QUEUE_FORMAT')
        if len(self.state['pending']) > self.limit:
            raise RuntimeError('CANDLE_QUEUE_LIMIT')
        self._save()

    def producer_can_start(self):
        # On restart, drain an already full accepted queue before accepting any
        # new generation. Never throw away the interrupted active generation.
        return len(self.state['pending']) < self.limit

    def _save(self):
        _json(self.state_path, self.state)

    def _verify(self, item):
        for filename, expected in item['sha256'].items():
            if _hash(item['inputs'][filename]) != expected:
                raise RuntimeError('CANDLE_GENERATION_INPUT_CHANGED:' + filename)
        meta_path = Path(item['inputs']['candle_structure_memory.parquet'] + '.meta.json')
        if _hash(meta_path) != item['metadata_sha256']:
            raise RuntimeError('CANDLE_GENERATION_METADATA_CHANGED')
        if _load(meta_path).get('file_sha256') != item['generation_id']:
            raise RuntimeError('CANDLE_GENERATION_OWNER_BINDING')
        if _hash(item['native_read_record']) != item['native_read_record_sha256']:
            raise RuntimeError('CANDLE_GENERATION_READ_RECORD_CHANGED')
        if _hash(item['feed_origin_snapshot']) != item['feed_source_sha256']:
            raise RuntimeError('CANDLE_GENERATION_FEED_PIN_CHANGED')

    def _produce_native(self, job):
        import pandas as pd
        from live_feed_paths import read_live_feed_history, _iter_partition_dirs
        from runtime_dataset_metadata import emit_metadata_for_path
        public = self.root / 'data/cognition/candle_structure_memory.parquet'
        if job is not None and (Path(job['directory']) / 'generation.json').exists():
            return _load(Path(job['directory']) / 'generation.json')
        if job is None:
            # The original merger remains the source of all historical values.
            # Restrict only the view to the next actual queued CLOSED bar.
            source = self.root / 'data/live/live_market_feed.parquet'
            meta_path = Path(str(source) + '.meta.json')
            if not meta_path.exists():
                return None
            before = meta_path.read_bytes()
            meta = json.loads(before)
            with self.lock:
                latest = next((v for v in reversed([self.state['current'], self.state['active'], *self.state['pending']]) if v), None)
            if (latest and self.state['cursor'] == latest['target']
                    and meta.get('file_sha256') == latest['feed_source_sha256']
                    and pd.to_datetime(meta['latest_timestamp'], utc=True) <= pd.to_datetime(self.state['cursor'], utc=True)):
                return None  # Same already accepted source; no repeated history decode.
            def signatures():
                paths = [source]
                for folder in _iter_partition_dirs():
                    paths.extend(sorted(p for p in folder.glob('*.parquet') if p.name != 'latest.parquet'))
                return [(str(p), p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
            initial = signatures()
            history = read_live_feed_history()
            if initial != signatures():
                return None  # Retry a concurrent original atomic feed write.
            if history.empty:
                return None
            times = pd.to_datetime(history.timestamp, utc=True)
            source_sha = _hash(source)
            if source_sha != meta.get('file_sha256') or before != meta_path.read_bytes():
                return None  # Existing atomic writer is between data and sidecar.
            if initial != signatures():
                return None
            tip = pd.Timestamp(meta['latest_timestamp'])
            tip = tip.tz_localize('UTC') if tip.tzinfo is None else tip.tz_convert('UTC')
            # The existing feed owner writes only actual k.x=true messages.
            # Do not invent a Binance-clock <= local-clock admission rule.
            if (meta.get('writer_entrypoint') != 'live_binance_feed_v2.py'
                    or meta.get('metadata_origin') != 'LIVE_WRITER'
                    or meta.get('last_write_status') != 'OK'):
                raise RuntimeError('CANDLE_CLOSED_FEED_OWNER_UNCONFIRMED')
            if times.max() > tip:
                return None
            cursor = self.state['cursor'] or self.state.get('cutover')
            if cursor is None and public.exists():
                clocks = pd.read_parquet(public, columns=['timestamp'])
                cursor = pd.to_datetime(clocks.timestamp, utc=True).max().isoformat() if len(clocks) else None
            after = history.loc[times > pd.Timestamp(cursor)] if cursor else history
            if latest and cursor:
                accepted = pd.read_parquet(latest['inputs']['live_market_feed.parquet'])
                if not history.loc[times <= pd.Timestamp(cursor)].reset_index(drop=True).equals(accepted):
                    raise RuntimeError('CANDLE_ACCEPTED_PREFIX_CHANGED')
            if after.empty and self.state['cursor'] is not None:
                return None
            target = pd.to_datetime(after.timestamp, utc=True).min() if len(after) else tip
            if cursor is not None and target > pd.Timestamp(cursor) + pd.Timedelta(minutes=15):
                raise RuntimeError('CANDLE_CONFIRMED_BAR_GAP')
            with self.lock:
                if len(self.state['pending']) >= self.limit:
                    raise RuntimeError('CANDLE_PENDING_QUEUE_FULL')
            selected = history.loc[times <= target].reset_index(drop=True)
            directory = Path(tempfile.mkdtemp(dir=self.home, prefix='input-'))
            origin = directory / 'feed_origin.parquet'
            shutil.copyfile(source, origin)
            if _hash(origin) != source_sha or before != meta_path.read_bytes():
                shutil.rmtree(directory)
                return None
            (directory / 'feed_origin.meta.json').write_bytes(before)
            feed = directory / 'live_market_feed.parquet'
            selected.to_parquet(feed, index=False)
            with feed.open('rb') as stream:
                os.fsync(stream.fileno())
            job = {'directory': str(directory), 'target': target.isoformat(),
                   'feed_source_sha256': source_sha, 'feed_source_metadata_sha256': hashlib.sha256(before).hexdigest(),
                   'feed_source_path': str(source), 'feed_origin_snapshot': str(origin),
                   'feed_view_sha256': _hash(feed),
                   'feed_source_written_at': meta.get('written_at'),
                   'observed_at': datetime.now(timezone.utc).isoformat(),
                   'observed_monotonic': time.monotonic()}
            _json(self.pending_path, job)  # Durable before publication begins.
        directory = Path(job['directory'])
        feed = directory / 'live_market_feed.parquet'
        if _hash(feed) != job['feed_view_sha256']:
            raise RuntimeError('CANDLE_PENDING_INPUT_CHANGED')
        candidate = directory / 'candle_structure_memory.parquet'
        view = {'role': 'producer', 'inputs': {'live_market_feed.parquet': str(feed)}, 'candidate': str(candidate)}
        script = self.root / 'candle_structure_engine_v1.py'
        with input_scope(view):
            # Isolated module globals; no sys.path/cwd/function monkey-patch.
            namespace = {'__name__': '__main__', '__file__': str(script)}
            exec(compile(script.read_bytes(), str(script), 'exec'), namespace)
        pin = _hash(candidate)
        public.parent.mkdir(parents=True, exist_ok=True)
        public_meta = Path(str(public) + '.meta.json')
        matching = (public.exists() and public_meta.exists() and _hash(public) == pin
                    and _load(public_meta).get('file_sha256') == pin
                    and _load(public_meta).get('last_write_status') == 'OK'
                    and _load(public_meta).get('metadata_origin') == 'LIVE_WRITER'
                    and _load(public_meta).get('writer_entrypoint') == 'candle_structure_engine_v1.py')
        if not matching:
            os.replace(candidate, public)
            _sync(public.parent)
            # This exact existing writer emits genuine LIVE_WRITER metadata.
            with input_scope(None):
                written = emit_metadata_for_path('data/cognition/candle_structure_memory.parquet',
                                                  root=self.root, metadata_origin='LIVE_WRITER')
            if not written.get('ok'):
                raise RuntimeError('CANDLE_OWNER_METADATA:' + str(written.get('error')))
        else:
            candidate.unlink(missing_ok=True)
        # Retain the exact public bytes/metadata. These small files are inputs,
        # not a second public owner or new permission/publication protocol.
        os.link(public, candidate)
        candle_meta = Path(str(candidate) + '.meta.json')
        candle_meta.write_bytes(public_meta.read_bytes())
        with candle_meta.open('rb') as stream:
            os.fsync(stream.fileno())
        import stage2_publication_metadata as H
        with input_scope(None):
            captured = H._source_snapshot_read(str(public), native_safe=False)
        record = captured.attrs[H.META_READ_ATTR]
        if record.get('artifact_sha256') != pin:
            raise RuntimeError('CANDLE_NATIVE_READ_PIN_MISMATCH')
        record_path = directory / 'native_read.json'
        _json(record_path, record)
        del captured
        item = {**job, 'role': 'consumer', 'generation_id': pin,
                'inputs': {'live_market_feed.parquet': str(feed), 'candle_structure_memory.parquet': str(candidate)},
                'sha256': {'live_market_feed.parquet': _hash(feed), 'candle_structure_memory.parquet': pin},
                'metadata_sha256': _hash(candle_meta), 'descriptor': str(directory / 'generation.json'),
                'native_read_record': str(record_path), 'native_read_record_sha256': _hash(record_path),
                'published_at': _load(public_meta)['written_at']}
        _json(item['descriptor'], item)
        return item

    def publish_once(self):
        candle_done.clear()
        candle_waiting.set()
        try:
            return self._publish_once()
        finally:
            candle_waiting.clear()
            candle_done.set()

    def _publish_once(self):
        started = time.monotonic()
        cpu_started = time.thread_time()
        with allocation_gate:
            job = _load(self.pending_path) if self.pending_path.exists() else None
            item = self.producer(job)
        if item is None:
            return False
        self._verify(item)
        with self.lock:
            known = [self.state['current'], self.state['active'], *self.state['pending']]
            if not any(v and v['generation_id'] == item['generation_id'] for v in known):
                if len(self.state['pending']) >= self.limit:
                    raise RuntimeError('CANDLE_PENDING_QUEUE_FULL')
                self.state['pending'].append(item)
            self.state['cursor'] = item['target']
            self._save()
            self.pending_path.unlink(missing_ok=True)
            _sync(self.home)
            self.changed.set()
        _event('CANDLE_GENERATION_PUBLISHED', generation=item['generation_id'], target=item['target'],
               observed_at=item['observed_at'], publication_s=time.monotonic()-started,
               CPU_thread_s=time.thread_time()-cpu_started,
               feed_source_written_at=item.get('feed_source_written_at'), published_at=item['published_at'],
               queue=len(self.state['pending']))
        return True

    def _run(self):
        try:
            while not self.stop_event.is_set():
                # Feed already durably retains the next CLOSED bars. Do not
                # accept another generation while the bounded FIFO is full.
                # Keep all publication/order/pin fail-stop checks below intact.
                with self.lock:
                    has_capacity = len(self.state['pending']) < self.limit
                if has_capacity:
                    self.publish_once()
                self.stop_event.wait(self.poll_s)
        except BaseException as error:
            self.fatal = error
            self.changed.set()
            _event('CANDLE_LANE_FAIL_STOP', reason=type(error).__name__+':'+str(error))

    def start(self):
        self.thread = threading.Thread(target=self._run, name='canonical-candle-owner', daemon=False)
        self.thread.start()
        return self

    def check(self):
        if self.fatal is not None:
            raise RuntimeError('CANDLE_LANE_FAIL_STOP:' + str(self.fatal)) from self.fatal

    def next(self):
        self.check()
        with self.lock:
            if self.state['active'] is None:
                if self.state['pending']:
                    self.state['active'] = self.state['pending'].pop(0)
                # With no new pending input, wait; current is already committed.
                self._save()  # Cursor before calculation, never ACK before outputs.
            item = self.state['active']
        if item is not None:
            self._verify(item)
        return item

    def committed(self, item):
        with self.lock:
            if self.state['active'] != item:
                raise RuntimeError('CANDLE_GENERATION_COMMIT_ORDER')
            previous = self.state['current']
            self.state['current'] = item
            self.state['active'] = None
            self._save()
            # Only this lane's completed transient snapshots. Native datasets,
            # receipts, WAL and historical files are never removed.
            keep = {v['directory'] for v in [self.state['current'], self.state['active'], *self.state['pending']] if v}
            if previous and previous['directory'] not in keep:
                directory = Path(previous['directory'])
                if directory.parent == self.home and directory.name.startswith('input-'):
                    shutil.rmtree(directory)
        _event('CANONICAL_GENERATION_COMMITTED', generation=item['generation_id'], target=item['target'])

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()

