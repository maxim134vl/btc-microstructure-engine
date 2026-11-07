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

ROOT=Path(__file__).resolve().parents[2]
NAMES=['auction_episode_memory','cognitive_market_state_memory','final_market_context_memory','market_context_lifecycle_memory']
INPUTS=['data/live/live_market_feed.parquet','data/cognition/candle_structure_memory.parquet','data/cognition/volume_response_state.parquet','data/reinforcement/auction_convergence_memory.parquet','data/probabilistic/probabilistic_auction_memory.parquet','data/cognition/runtime_cognition_memory.parquet','data/cognition/runtime_cognition_composite.parquet']
IMMUTABLE=['auction_episode_observations.parquet','auction_episode_memory.parquet','cognitive_market_state_memory.parquet','final_market_context_memory.parquet','market_context_lifecycle_memory.parquet']

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

def main():
    publication=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    base=ROOT/'data/live'
    base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.primary-context-stage-',dir=base) as name:
        stage=Path(name)
        (stage/'scripts/research').mkdir(parents=True)
        (stage/'scripts/live').mkdir(parents=True)
        (stage/'src').symlink_to(ROOT/'src',target_is_directory=True)
        for directory in ['config','logs']:
            if (ROOT/directory).exists():(stage/directory).symlink_to(ROOT/directory,target_is_directory=True)
        input_hashes={}
        for rel in INPUTS:
            src=ROOT/rel
            if not src.exists():continue
            raw=src.read_bytes();dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
            input_hashes[rel]=hashlib.sha256(raw).hexdigest()
        feed=pd.read_parquet(stage/INPUTS[0]);candles=pd.read_parquet(stage/INPUTS[1])
        feed_tip=pd.to_datetime(feed.timestamp,utc=True).max();candle_tip=pd.to_datetime(candles.timestamp,utc=True).max()
        if pd.isna(feed_tip) or pd.isna(candle_tip):raise RuntimeError('REQUIRED_MARKET_INPUT_EMPTY')
        cutoff=min(feed_tip,candle_tip)
        now=pd.Timestamp.now(tz='UTC')
        if cutoff+pd.Timedelta(minutes=15)>now:raise RuntimeError('UNCOMPLETED_CANDLE_INPUT')
        for frame,rel in [(feed,INPUTS[0]),(candles,INPUTS[1])]:
            frame=frame.loc[pd.to_datetime(frame.timestamp,utc=True)<=cutoff]
            frame.to_parquet(stage/rel,index=False)
        existing={}
        for file in IMMUTABLE:
            actual=ROOT/'data/cognition'/file
            existing[file]=pd.read_parquet(actual) if actual.exists() else None
        for stem in NAMES:
            src=ROOT/'scripts/research'/('build_'+stem+'.py');dst=stage/'scripts/research'/src.name;shutil.copy2(src,dst)
            proc=subprocess.run([sys.executable,str(dst)],cwd=stage,capture_output=True,text=True)
            print(proc.stdout,end='',flush=True)
            if proc.returncode:raise RuntimeError(f'{stem}: {proc.stderr[-2000:]}')
            # Freeze each earlier stage BEFORE its dependent stage reads it.
            for file in ([stem+'.parquet','auction_episode_observations.parquet'] if stem=='auction_episode_memory' else [stem+'.parquet']):
                target=stage/'data/cognition'/file;new=pd.read_parquet(target)
                if len(new)==0:raise RuntimeError(f'NO_COMPLETE_FOUR_CLOSE_WINDOW: {file}')
                if pd.to_datetime(new.timestamp,utc=True).duplicated().any():raise RuntimeError(f'DUPLICATE_TIMESTAMP: {file}')
                combined=frozen_tail(existing[file],new)
                atomic(combined,target)
        # Rebuild episode SUMMARY from the frozen lifecycle states; no state is revised.
        modpath=stage/'scripts/research/build_market_context_lifecycle_memory.py'
        spec=importlib.util.spec_from_file_location('candidate_lifecycle',modpath);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
        life=pd.read_parquet(stage/'data/cognition/market_context_lifecycle_memory.parquet')
        episodes=mod.build_lifecycle_episodes(life)
        atomic(episodes,stage/'data/cognition/market_context_lifecycle_episodes.parquet')
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
        # Complete private validation precedes any live output. Lifecycle is the
        # trading adapter's authority; publish it last, after all other inputs.
        # Decision identifiers are in place before the lifecycle activation gate.
        actual_decision=ROOT/decision_rel;staged_decision=stage/decision_rel
        if not actual_decision.exists() or actual_decision.read_bytes()!=staged_decision.read_bytes():
            atomic(decision,actual_decision)
        if (stage/side_rel).exists():
            tmp=(ROOT/side_rel).with_suffix('.jsonl.tmp');tmp.write_bytes((stage/side_rel).read_bytes());os.replace(tmp,ROOT/side_rel)
        order=[IMMUTABLE[0],IMMUTABLE[1],IMMUTABLE[2],IMMUTABLE[3],'market_context_lifecycle_episodes.parquet',IMMUTABLE[4]]
        records=[]
        for file in order:
            frame=pd.read_parquet(stage/'data/cognition'/file);target=ROOT/'data/cognition'/file
            before=target.read_bytes() if target.exists() else None
            if file in existing and existing[file] is not None and len(frame)==len(existing[file]):
                records.append({'file':file,'status':'UNCHANGED','rows':len(frame)});continue
            atomic(frame,target)
            records.append({'file':file,'rows':len(frame),'status':'PUBLISHED','published_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        records.append({'file':str(decision_rel),'rows':len(decision),'status':'PUBLISHED_OR_UNCHANGED','decision_id':decision.iloc[-1].decision_id,'available_at':decision.iloc[-1].decision_written_at_utc})
        report={'status':'PASS','safe_bar_open':str(cutoff),'safe_bar_close':str(cutoff+pd.Timedelta(minutes=15)),'published_at':publication,'record_origin':'LIVE_PUBLICATION_FROM_REAL_MARKET_HISTORY','historical_decisions_created':False,'historical_first_publication':'NOT_VERIFIABLE; window close is market event time, current publication is recorded here','input_sha256':input_hashes,'outputs':records,'tips':tips}
        path=ROOT/'data/live/primary_context_publication.json';tmp=path.with_suffix('.json.tmp');tmp.write_text(json.dumps(report,indent=2));os.replace(tmp,path)
        print('PRIMARY_CONTEXT_PUBLICATION '+json.dumps(report),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
