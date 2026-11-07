#!/usr/bin/env python3
"""Build the four existing context stages privately, then publish their new tail.

No trading commands, visual generation, Stage2, or auxiliary cognition is run.
The actual source data and original classifier functions remain the authority.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from sitecustomize import (_prep_start, _prep_span, _prep_emit,
                           _prep_files, _prep_freeze_inputs)

ROOT=Path(__file__).resolve().parents[2]
# Preserve installed package lookup in private builder subprocesses.
os.environ['PYTHONPATH']=os.pathsep.join((str(ROOT),str(ROOT/'src'),os.environ.get('PYTHONPATH','')))
NAMES=['auction_episode_memory','cognitive_market_state_memory','final_market_context_memory','market_context_lifecycle_memory']
INPUTS=['data/live/live_market_feed.parquet','data/cognition/candle_structure_memory.parquet','data/cognition/volume_response_state.parquet','data/reinforcement/auction_convergence_memory.parquet','data/probabilistic/probabilistic_auction_memory.parquet','data/cognition/runtime_cognition_memory.parquet','data/cognition/runtime_cognition_composite.parquet']
IMMUTABLE=['auction_episode_observations.parquet','auction_episode_memory.parquet','cognitive_market_state_memory.parquet','final_market_context_memory.parquet','market_context_lifecycle_memory.parquet']

def _report_json_default(value):
    # Keep the original timestamp, including its offset and precision.
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')

def atomic(frame,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.parquet',delete=False) as f:tmp=Path(f.name)
    try:
        frame.to_parquet(tmp,index=False)
        with tmp.open('rb') as f:os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def frozen_tail(old,new):
    if old is None:return new
    old_ts=pd.to_datetime(old.timestamp,utc=True)
    tail=new.loc[pd.to_datetime(new.timestamp,utc=True)>old_ts.max()]
    if not len(tail):return old
    return pd.concat([old,tail],ignore_index=True,sort=False)

def wait_for_closed_market_inputs(root):
    """Await the existing Candle dependency, inside the native child deadline.

    A forming feed row does not demand a future Candle. Use the existing native
    closed-bar selector. No producer runs here; the canonical owner catches up.
    The decision snapshot is created only AFTER this function returns.
    """
    import time
    from btc_ml.external_traders.independent_context_publication import native_safe_close
    root = Path(root)
    began = time.monotonic()
    while True:
        feed = pd.read_parquet(root/'data/live/live_market_feed.parquet', columns=['timestamp'])
        candle = pd.read_parquet(root/'data/cognition/candle_structure_memory.parquet', columns=['timestamp'])
        required = native_safe_close(feed) - pd.Timedelta(minutes=15)
        current = pd.to_datetime(candle.timestamp, utc=True).max()
        if pd.isna(current):
            raise RuntimeError('REQUIRED_MARKET_INPUT_EMPTY')
        if current >= required:
            return
        print('NATIVE_CONTEXT_INPUT_WAIT '+json.dumps({
            'required_closed_feed_bar':str(required),'candle_tip':str(current),
            'waited_seconds':time.monotonic()-began,
            'decision_snapshot_created':False}),flush=True)
        # Infrastructure polling only. The daemon's unchanged subprocess1200s
        # deadline includes this wait; no extra timeout/publication slot exists.
        time.sleep(5)

def run_native_auction(script, *, native_sources=None):
    """Run the same standalone producer API without a second Python heap.

    This driver is already private to one native child/cycle. The producer keeps
    its own module globals, ROOT, functions, output schemas and exception cause.
    Restore interpreter call context and release the ephemeral module afterward.
    """
    import gc
    import traceback
    import pyarrow as pa
    # Discard only unused allocator reservations from completed snapshots.
    # Referenced DataFrame/Arrow buffers and all source/guard bytes stay live.
    with _prep_span('native_auction_entry_gc'):
        gc.collect()
        pa.default_memory_pool().release_unused()
    name = '_primary_context_native_auction'
    previous = sys.modules.get(name)
    argv = sys.argv
    search_path = sys.path
    cwd = Path.cwd()
    module = None
    try:
        spec = importlib.util.spec_from_file_location(name, script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        sys.argv = [str(script)]
        sys.path = [str(Path(script).parent)] + search_path[1:]
        os.chdir(Path(script).resolve().parents[2])
        with _prep_span('native_auction_module_import'):
            spec.loader.exec_module(module)
        try:
            code = module.main(_native_pass=native_sources)
        except Exception as exc:
            raise RuntimeError('auction_episode_memory: ' + traceback.format_exc()[-2000:]) from exc
        if code:
            raise RuntimeError(f'auction_episode_memory: returncode={code}')
    finally:
        sys.argv = argv
        sys.path = search_path
        os.chdir(cwd)
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        del module
        gc.collect()
        pa.default_memory_pool().release_unused()

def main():
    wait_for_closed_market_inputs(ROOT)
    publication=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    _prep_start()
    base=ROOT/'data/live'
    base.mkdir(parents=True,exist_ok=True)
    from btc_ml.external_traders.context_stage2_evidence import NativeSourcePass
    with tempfile.TemporaryDirectory(prefix='.primary-context-stage-',dir=base) as name, NativeSourcePass(name) as native_sources:
        stage=Path(name)
        with _prep_span('stage_layout'):
            (stage/'scripts/research').mkdir(parents=True)
            (stage/'scripts/live').mkdir(parents=True)
            (stage/'src').symlink_to(ROOT/'src',target_is_directory=True)
            for directory in ['config','logs']:
                if (ROOT/directory).exists():(stage/directory).symlink_to(ROOT/directory,target_is_directory=True)
        input_hashes={}
        with _prep_span('staging_inputs') as _prep_copied:
            for rel in INPUTS:
                src=ROOT/rel
                if not src.exists():continue
                raw=src.read_bytes();dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
                input_hashes[rel]=hashlib.sha256(raw).hexdigest()
                _prep_copied['bytes_copied'] = _prep_copied.get('bytes_copied', 0) + len(raw)
                _prep_copied['files_copied'] = _prep_copied.get('files_copied', 0) + 1
        # Optional metadata snapshot, separate from every classifier input.
        from btc_ml.external_traders.context_stage2_evidence import freeze_sources
        try:
            with _prep_span('freeze_sources', **_prep_freeze_inputs(freeze_sources, ROOT, stage)):
                freeze_sources(ROOT, stage, _native_pass=native_sources)
        except Exception as exc:
            print('STAGE2_EVIDENCE_SNAPSHOT_UNAVAILABLE '+type(exc).__name__+':'+str(exc),flush=True)
        with _prep_span('normalize_market_inputs', **_prep_files([stage/INPUTS[0], stage/INPUTS[1]])):
            feed=pd.read_parquet(stage/INPUTS[0]);candles=pd.read_parquet(stage/INPUTS[1])
            feed_tip=pd.to_datetime(feed.timestamp,utc=True).max();candle_tip=pd.to_datetime(candles.timestamp,utc=True).max()
            if pd.isna(feed_tip) or pd.isna(candle_tip):raise RuntimeError('REQUIRED_MARKET_INPUT_EMPTY')
            cutoff=min(feed_tip,candle_tip)
            now=pd.Timestamp.now(tz='UTC')
            if cutoff+pd.Timedelta(minutes=15)>now:raise RuntimeError('UNCOMPLETED_CANDLE_INPUT')
            for frame,rel in [(feed,INPUTS[0]),(candles,INPUTS[1])]:
                frame=frame.loc[pd.to_datetime(frame.timestamp,utc=True)<=cutoff]
                frame.to_parquet(stage/rel,index=False)
        # An explicit live processing snapshot, pinned BEFORE any classifiers.
        # Historical rebuild/readers never call this creator.
        from btc_ml.external_traders.stage2_predecision_evidence import pin_new_own_tf_decision_snapshot
        with _prep_span('snapshot_and_pins'):
            pin_new_own_tf_decision_snapshot(stage,ROOT,market_data_cutoff=cutoff+pd.Timedelta(minutes=15),
                                             _native_pass=native_sources)
        with _prep_span('load_committed_history', **_prep_files([ROOT/'data/cognition'/f for f in IMMUTABLE])):
            existing={}
            for file in IMMUTABLE:
                actual=ROOT/'data/cognition'/file
                existing[file]=pd.read_parquet(actual) if actual.exists() else None
                if file == "market_context_lifecycle_memory.parquet" and existing[file] is not None:
                    if "timeframe" in existing[file]:
                        existing[file]=existing[file].loc[existing[file].timeframe.astype(str).str.upper()=="M15"].copy()
                    # Legacy untagged lifecycle is M15; preserve its owner in staging.
                    existing[file]["timeframe"] = "M15"
        for stem in NAMES[:1]:
            src=ROOT/'scripts/research'/('build_'+stem+'.py');dst=stage/'scripts/research'/src.name;shutil.copy2(src,dst)
            _prep_emit('BOUNDARY', 'native_auction_call')
            run_native_auction(dst, native_sources=native_sources)
            # Freeze each earlier stage BEFORE its dependent stage reads it.
            for file in ([stem+'.parquet','auction_episode_observations.parquet'] if stem=='auction_episode_memory' else [stem+'.parquet']):
                target=stage/'data/cognition'/file;new=pd.read_parquet(target)
                if len(new)==0:raise RuntimeError(f'NO_COMPLETE_FOUR_CLOSE_WINDOW: {file}')
                if pd.to_datetime(new.timestamp,utc=True).duplicated().any():raise RuntimeError(f'DUPLICATE_TIMESTAMP: {file}')
                if file == "market_context_lifecycle_memory.parquet":
                    # Assign ownership BEFORE concat and the scoped decision logger.
                    new["timeframe"] = "M15"
                combined=frozen_tail(existing[file],new)
                atomic(combined,target)
        # September M15 state is reconstructed privately, never seeded from v1.
        from btc_ml.external_traders.m15_september_boundary import prepare_m15
        # The existing metadata helper consumes only timestamp.max(). Use the
        # genuine Auction output, before this calculation commits its shadow.
        # No synthetic Lifecycle row or later replay clock is manufactured.
        from btc_ml.external_traders.context_phase_publication import prepare_native_publication
        phase_target = pd.read_parquet(stage/'data/cognition/auction_episode_memory.parquet')
        m15_phase_witness = prepare_native_publication(ROOT, stage, 'M15', phase_target)
        boundary_manifest = prepare_m15(ROOT, stage, existing, cutoff, input_hashes)
        # Calculate the fifth stage before releasing lifecycle authority. All
        # calculations use original rules; no controller reads the private tree.
        decision_rel=Path('data/live/context_decision_log.parquet')
        if (ROOT/decision_rel).exists():shutil.copy2(ROOT/decision_rel,stage/decision_rel)
        lookup_rel=Path('data/research/paper_simulator/corrected_lagged_context_edge_lookup_snapshot.parquet')
        if (ROOT/lookup_rel).exists():
            (stage/lookup_rel).parent.mkdir(parents=True,exist_ok=True)
            (stage/lookup_rel).symlink_to(ROOT/lookup_rel)
        side_rel=Path('data/live/context_decision_confirmations.jsonl')
        if (ROOT/side_rel).exists():shutil.copy2(ROOT/side_rel,stage/side_rel)
        logger=stage/'scripts/live/append_context_decision_log.py'
        shutil.copy2(ROOT/'scripts/live/append_context_decision_log.py',logger)
        proc=subprocess.run([sys.executable,str(logger)],cwd=stage,capture_output=True,text=True)
        print(proc.stdout,end='',flush=True)
        if proc.returncode:raise RuntimeError(f'decision_log: {proc.stderr[-2000:]}')
        decision=pd.read_parquet(stage/decision_rel)
        if pd.to_datetime(decision.candle_timestamp,utc=True).max()!=cutoff:raise RuntimeError('DECISION_TIP_MISMATCH')
        tips={}
        for file in IMMUTABLE[1:]:
            frame=pd.read_parquet(stage/'data/cognition'/file);tip=pd.to_datetime(frame.timestamp,utc=True).max();tips[file]=str(tip)
            if tip!=cutoff:raise RuntimeError(f'CHAIN_TIP_MISMATCH: {file}: {tip} != {cutoff}')
            if frame.timestamp.isna().any():raise RuntimeError(f'NULL_TIMESTAMP: {file}')
        ae=pd.read_parquet(stage/'data/cognition/auction_episode_memory.parquet')
        if (pd.to_datetime(ae.information_available_at,utc=True)>pd.to_datetime(ae.timestamp,utc=True)+pd.Timedelta(minutes=15)).any():raise RuntimeError('LATE_CONFIRMATION_BACKDATED')
        # Activate each completed own timeframe, never wait for unrelated work.
        from btc_ml.external_traders.context_stage2_evidence import publish_completed_with_evidence as publish_completed
        from btc_ml.external_traders.independent_context_publication import prepare_higher_contexts, native_safe_close
        actual_decision=ROOT/decision_rel;staged_decision=stage/decision_rel
        if not actual_decision.exists() or actual_decision.read_bytes()!=staged_decision.read_bytes(): atomic(decision,actual_decision)
        if (stage/side_rel).exists():
            tmp=(ROOT/side_rel).with_suffix('.jsonl.tmp');tmp.write_bytes((stage/side_rel).read_bytes());os.replace(tmp,ROOT/side_rel)
        m15_life=pd.read_parquet(stage/'data/cognition/market_context_lifecycle_memory.parquet');m15_life['timeframe']='M15'
        m15_episodes=pd.read_parquet(stage/'data/cognition/market_context_lifecycle_episodes.parquet');m15_episodes['timeframe']='M15'
        records=[publish_completed(ROOT,stage,'M15',m15_life,m15_episodes,[str(Path('data/cognition')/f) for f in IMMUTABLE[:4]],context_phase=True,context_phase_witness=m15_phase_witness)]
        print('TIMEFRAME_PUBLICATION '+json.dumps(records[-1]),flush=True)
        # M15 publication is complete. Its private decoded native packet is not
        # an input to any higher-TF calculation and must not retain its heap.
        import gc
        import pyarrow as pa
        from btc_ml.external_traders import context_stage2_evidence as evidence
        evidence._PRIVATE_M15_DECODE = None
        gc.collect()
        pa.default_memory_pool().release_unused()
        def completed(tf,item):
            record=publish_completed(ROOT,stage,tf,item['lifecycle'],item['episodes'],item['artifacts'],context_phase=True)
            records.append(record)
            print('TIMEFRAME_PUBLICATION '+json.dumps(record),flush=True)
        higher=prepare_higher_contexts(ROOT,stage,feed,native_safe_close(feed,now),on_complete=completed)
        records.append({'file':str(decision_rel),'rows':len(decision),'status':'PUBLISHED_OR_UNCHANGED','decision_id':decision.iloc[-1].decision_id,'available_at':decision.iloc[-1].decision_written_at_utc})
        report={'m15_semantic_boundary':boundary_manifest,'status':'PASS','safe_bar_open':str(cutoff),'safe_bar_close':str(cutoff+pd.Timedelta(minutes=15)),'published_at':publication,'record_origin':'LIVE_PUBLICATION_FROM_REAL_MARKET_HISTORY','historical_decisions_created':False,'historical_first_publication':'NOT_VERIFIABLE; window close is market event time, current publication is recorded here','input_sha256':input_hashes,'outputs':records,'tips':tips,'independent_timeframes':{tf:item['summary'] for tf,item in higher.items()}}
        path=ROOT/'data/live/primary_context_publication.json';tmp=path.with_suffix('.json.tmp');tmp.write_text(json.dumps(report,indent=2,default=_report_json_default));os.replace(tmp,path)
        print('PRIMARY_CONTEXT_PUBLICATION '+json.dumps(report,default=_report_json_default),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
