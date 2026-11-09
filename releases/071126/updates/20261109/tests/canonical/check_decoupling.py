"""Bounded mechanical regression on saved genuine rows; no live admission."""
import ast
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import threading
import time
import types

sys.path[:0] = ['/app', '/app/src']
import pandas as pd
from btc_ml.runtime import canonical_candle_lane as L
from runtime_dataset_metadata import emit_metadata_for_path
from storage import path_registry as P
import stage2_publication_metadata as H

ROOT = Path('/tmp/candle-case')
os.environ['BTC_ML_DATA_ROOT'] = str(ROOT / 'data')
P._REPO_ROOT = ROOT


def stage2():
    path = Path('/app/stage2_cognition_runtime_v1.py')
    tree = ast.parse(path.read_bytes())
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and n.module == 'state_manager_v1')]
    module = types.ModuleType('tested_stage2')
    module.__file__ = str(path)
    module.STATE = {}
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rss():
    result = {}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('VmRSS:', 'VmHWM:')):
            key, value = line.split(':')
            result[key] = int(value.split()[0]) * 1024
    return result


def worker(mode, descriptor):
    item = json.loads(Path(descriptor).read_text())
    S = stage2()
    with L.input_scope(item if mode == 'after' else None):
        if mode == 'after':
            L.install_allocation_gate(S)
            frame = L.candle_frame()
        else:
            frame = pd.read_parquet(item['inputs']['candle_structure_memory.parquet'])
            frame.attrs[H.META_READ_ATTR] = json.loads(Path(item['native_read_record']).read_text())
        close = pd.to_datetime(frame.timestamp, utc=True).max() + pd.Timedelta(minutes=15)
        # Give both independent processes the same lazy-import/JIT warmup.
        warm = S.build_tf_components(frame, market_cutoff=close)
        S.build_stage2_synthesis(frame, components=warm)
        del warm
        started, cpu = time.monotonic(), time.process_time()
        components = S.build_tf_components(frame, market_cutoff=close)
        synthesis = S.build_stage2_synthesis(frame, components=components)
        outputs = S.build_tf_native_results(frame, market_cutoff=close, components=components, m15_synthesis=synthesis)
        result = {'mode': mode, 'wall_s': time.monotonic()-started, 'CPU_s': time.process_time()-cpu,
                  **rss(), 'outputs': {}, 'rows': len(frame), 'component_rows': {k: len(v) for k, v in components['datasets'].items()}}
        for tf, output in outputs.items():
            data = output.to_parquet(index=False)
            result['outputs'][tf] = {'sha256': hashlib.sha256(data).hexdigest(),
                'analysis_status': output.iloc[0].analysis_status,
                'source_publication': json.loads(output.iloc[0].provenance_json)['historical_source_publication']}
        result['synthesis_sha256'] = hashlib.sha256(synthesis.to_parquet(index=False)).hexdigest()
        # Linux ru_maxrss can include the fork parent's pre-exec high water.
        # /proc/self/VmHWM measures this address space, not the fixture parent.
        result.update(rss())
        result['peak_RSS_bytes'] = result['VmHWM']
        publication_start, publication_cpu = time.monotonic(), time.process_time()
        published = S.publish_tf_native_results(outputs)
        result['publication_wall_s'] = time.monotonic()-publication_start
        result['publication_CPU_s'] = time.process_time()-publication_cpu
        hashes = {tf: sha(ROOT / 'data/cognition' / S.TF_OUTPUTS[tf]) for tf in outputs}
        again = S.publish_tf_native_results(outputs)
        assert all(v['status'] == 'UNCHANGED' for v in again.values())
        assert hashes == {tf: sha(ROOT/'data/cognition'/S.TF_OUTPUTS[tf]) for tf in outputs}
        result['owner_publication_no_duplicate_effect'] = True
        result['published_owner_sha256'] = hashes
        result.update(rss())
        result['peak_RSS_bytes'] = result['VmHWM']
    print('WORKER_RESULT '+json.dumps(result), flush=True)


def run_worker(mode, item):
    p = subprocess.run([sys.executable, __file__, mode, item['descriptor']], capture_output=True, text=True, check=True)
    return json.loads(next(x[len('WORKER_RESULT '):] for x in p.stdout.splitlines() if x.startswith('WORKER_RESULT ')))


def metadata(relative):
    result = emit_metadata_for_path(relative, root=ROOT, metadata_origin='LIVE_WRITER')
    assert result['ok'], result
    return result


def reference_candle():
    p = subprocess.run([sys.executable, '/app/candle_structure_engine_v1.py'], capture_output=True, text=True, check=True)
    metadata('data/cognition/candle_structure_memory.parquet')
    return sha(ROOT / 'data/cognition/candle_structure_memory.parquet')


def main():
    ROOT.mkdir(parents=True)
    (ROOT / 'config').symlink_to('/app/config', target_is_directory=True)
    (ROOT / 'candle_structure_engine_v1.py').symlink_to('/app/candle_structure_engine_v1.py')
    (ROOT / 'data/live').mkdir(parents=True)
    (ROOT / 'data/cognition').mkdir(parents=True)
    feed = pd.read_parquet('/fixtures/feed.parquet').sort_values('timestamp').reset_index(drop=True)
    # Saved real rows, a bounded common prefix, enough complete own H4 bars.
    feed = feed.iloc[-260:].copy().reset_index(drop=True)
    assert len(feed) == 260
    assert (pd.to_datetime(feed.timestamp).diff().dropna() == pd.Timedelta(minutes=15)).all()
    target = ROOT / 'data/live/live_market_feed.parquet'
    def incoming(n):
        feed.iloc[:n].to_parquet(target, index=False)
        metadata('data/live/live_market_feed.parquet')
    checks = []
    def ok(name, condition):
        assert condition, name
        checks.append(name)
        print('PASS '+name, flush=True)

    incoming(256)
    old_hash = reference_candle()
    lane = L.CandleLane(ROOT, poll_s=0.02)
    lane.publish_once()
    A = lane.next()
    ok('Candle exact bytes from unchanged engine', A['generation_id'] == old_hash)
    old_meta = json.loads(Path(A['inputs']['candle_structure_memory.parquet']+'.meta.json').read_text())
    frozen = copy.deepcopy(A)
    before = run_worker('before', A)
    ok('Reference source metadata accepted', all(v['source_publication']['status'] == 'SHA_BOUND_ORIGINAL_SOURCE_PUBLICATION' for v in before['outputs'].values()))
    incoming(257)
    old_hash_B = reference_candle()
    # Publishing B independently while the heavy consumer still owns A.
    with L.allocation_gate:
        lane.start()
        time.sleep(0.05)
        ok('Candle allocations wait outside native expansion peak', not lane.state['pending'])
    timeout = time.monotonic()+30
    while not lane.state['pending'] and time.monotonic() < timeout:
        lane.check()
        lane.changed.wait(0.05)
    lane.close()
    lane.check()
    B = lane.state['pending'][0]
    ok('Candle B published while Stage2 A remains active', lane.state['active'] == A and B['generation_id'] == old_hash_B)
    with L.input_scope(A):
        frame = L.candle_frame()
        ok('Stage2 A exact original frame and timestamps', frame.attrs[H.META_READ_ATTR]['frame_sha256'] == json.loads(Path(A['native_read_record']).read_text())['frame_sha256'])
        S = stage2()
        original = S._tf_original_source_publication(frame.attrs[H.META_READ_ATTR], True)
        ok('Unadapted moving metadata is incompatible', original.get('reason') == 'SOURCE_METADATA_SHA_MISMATCH')
        ok('Scoped Feed excludes later confirmed B', len(__import__('live_feed_paths').read_live_feed_history()) == 256)
        env = L.environment()
        ok('Existing subprocess receives exact descriptor', env[L.ENV] == A['descriptor'])
        try:
            L.write_override('candle_structure_memory.parquet')
        except RuntimeError:
            checks.append('Only independent Candle owner may write')
        else:
            raise AssertionError('writer not exclusive')
    # Compare real first-publication branches, not only duplicate reads.
    old_owner = ROOT / 'old-owner-publications'
    old_owner.mkdir()
    for tf in ['M15', 'M30', 'H1', 'H4']:
        path = ROOT / 'data/cognition' / ('stage2_'+tf.lower()+'_native_memory.parquet')
        for retained in [path, Path(str(path)+'.publication'), Path(str(path)+'.meta.json')]:
            if retained.exists():
                retained.rename(old_owner/retained.name)
    after = run_worker('after', A)
    ok('All four native owner outputs exact byte SHA', before['outputs'] == after['outputs'])
    ok('Actual four owner publications and duplicate receipt reads', before['owner_publication_no_duplicate_effect'] and after['owner_publication_no_duplicate_effect'] and before['published_owner_sha256'] == after['published_owner_sha256'])
    order = []
    identity = {}
    fake = types.SimpleNamespace(build_tf_native_results=lambda: None,
        _tf_original_source_publication=lambda r,b: None)
    threads = []
    def original_publish(frames):
        tf, frame = next(iter(frames.items()))
        order.append(tf)
        assert identity[tf] is frame
        if tf == 'M15':
            def candle_turn():
                L.candle_done.clear(); L.candle_waiting.set()
                with L.allocation_gate:
                    order.append('CANDLE')
                L.candle_waiting.clear(); L.candle_done.set()
            thread = threading.Thread(target=candle_turn)
            threads.append(thread);thread.start()
            assert L.candle_waiting.wait(2)
        return {tf: 'original-result'}
    fake.publish_tf_native_results = original_publish
    L.install_allocation_gate(fake)
    identity = {tf: object() for tf in ['M15','M30','H1','H4']}
    published = fake.publish_tf_native_results(identity)
    for thread in threads: thread.join()
    ok('Light Candle gets turn between original TF publications without frame copies', order == ['M15','CANDLE','M30','H1','H4'] and list(published) == list(identity))
    ok('M15 synthesis exact byte SHA', before['synthesis_sha256'] == after['synthesis_sha256'])
    ok('Captured genuine source metadata unchanged', json.loads(Path(A['inputs']['candle_structure_memory.parquet']+'.meta.json').read_text()) == old_meta)
    ok('Committed/active input not mutated by independent publication', A == frozen)
    restored = L.CandleLane(ROOT)
    ok('Interrupted active and pending FIFO survive restart', restored.next() == A and restored.state['pending'] == [B])
    restored.committed(A)
    ok('FIFO consumes next exact B generation', restored.next() == B)
    restored.committed(B)
    try:
        restored.committed(B)
    except RuntimeError:
        checks.append('Duplicate commit rejected')
    else:
        raise AssertionError('duplicate commit')
    # Same source generation does not enqueue duplicate work on every poll.
    from unittest.mock import patch
    with patch('live_feed_paths.read_live_feed_history', side_effect=AssertionError('redundant decode')):
        restored.publish_once()
    ok('Repeated unchanged CLOSED source has no duplicate effect', not restored.state['pending'])
    incoming(258); restored.publish_once()
    incoming(259); restored.publish_once()
    snapshot = copy.deepcopy(restored.state)
    public_before = sha(ROOT / 'data/cognition/candle_structure_memory.parquet')
    incoming(260)
    try:
        restored.publish_once()
    except RuntimeError as error:
        ok('Bounded full queue fails before changing Candle owner', str(error) == 'CANDLE_PENDING_QUEUE_FULL' and sha(ROOT/'data/cognition/candle_structure_memory.parquet') == public_before and restored.state == snapshot)
    else:
        raise AssertionError('unbounded queue')
    recovered = L.CandleLane(ROOT)
    ok('Accepted generations retained after full-queue restart', recovered.state == snapshot)
    original_open = feed.loc[0, 'open']
    feed.loc[0, 'open'] = original_open + 1
    incoming(260)
    try:
        recovered.publish_once()
    except RuntimeError as error:
        ok('Previously accepted CLOSED prefix revision fails stop', str(error) == 'CANDLE_ACCEPTED_PREFIX_CHANGED')
    else:
        raise AssertionError('accepted prefix revision ignored')
    feed.loc[0, 'open'] = original_open
    incoming(260)
    # Failed state persistence cannot ACK the generation on disk.
    item = recovered.next()
    disk_before = recovered.state_path.read_bytes()
    original_save = recovered._save
    recovered._save = lambda: (_ for _ in ()).throw(OSError('fixture-fsync-failure'))
    try:
        recovered.committed(item)
    except OSError:
        pass
    else:
        raise AssertionError('write failure ignored')
    ok('Failed persistence preserves recoverable active generation', recovered.state_path.read_bytes() == disk_before and L.CandleLane(ROOT).next() == item)
    # Exact-input and source pins remain fail-closed.
    path = Path(item['inputs']['candle_structure_memory.parquet'])
    original_bytes = path.read_bytes()
    path.write_bytes(original_bytes+b'changed')
    try:
        L.CandleLane(ROOT).next()
    except RuntimeError as error:
        ok('Changed retained input rejected', 'INPUT_CHANGED' in str(error))
    else:
        raise AssertionError('changed snapshot accepted')
    result = {'fixture_only': True, 'checks': checks, 'PASS': len(checks), 'FAIL': 0,
              'before': before, 'after': after, 'feed_rows': len(feed), 'feed_sha256': sha('/fixtures/feed.parquet'),
              'queue_limit': lane.limit, 'no_production_writes': True}
    print('TEST_RESULT '+json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        worker(sys.argv[1], sys.argv[2])
    else:
        main()
