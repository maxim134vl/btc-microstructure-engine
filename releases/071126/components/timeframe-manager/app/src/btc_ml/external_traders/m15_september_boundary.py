"""September M15 version boundary; no classifier or execution rules here.

Shadow history is private state reconstruction. Only rows after the immutable
legacy boundary are exposed through the unchanged October publication wrapper.
The original September builders retain all internal process/lifecycle counters.
"""
from pathlib import Path
import hashlib, importlib.util, io, json, os, sys, tempfile
import pandas as pd

VERSION='M15_SEPTEMBER_SEMANTICS_CAUSAL_V1'
COMMIT='9e5d5934ec5c6fcea60a018afdd51d37b9501822'
STEMS=('cognitive_market_state_memory','final_market_context_memory','market_context_lifecycle_memory')

def atomic(frame,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.parquet',delete=False) as f: tmp=Path(f.name)
    try:
        frame.to_parquet(tmp,index=False)
        with tmp.open('rb') as f: os.fsync(f.fileno())
        os.replace(tmp,path)
    finally: tmp.unlink(missing_ok=True)

def atomic_json(value,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,mode='w',delete=False) as f:
        json.dump(json.loads(json.dumps(value,default=str),parse_constant=lambda _:None),f,indent=2);f.flush();os.fsync(f.fileno());tmp=Path(f.name)
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def load(root,stem):
    p=root/'scripts/research'/('build_'+stem+'.py')
    spec=importlib.util.spec_from_file_location('sept_m15_'+stem,p)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m

def append(old,new):
    if old is None or not len(old): return new.copy()
    tail=new.loc[pd.to_datetime(new.timestamp,utc=True)>pd.to_datetime(old.timestamp,utc=True).max()]
    return pd.concat([old,tail],ignore_index=True,sort=False) if len(tail) else old.copy()

def read(path): return pd.read_parquet(path) if path.exists() else None

def prepare_m15(root,stage,existing,cutoff,input_hashes):
    root,stage=Path(root),Path(stage);cutoff=pd.Timestamp(cutoff)
    home=root/'data/live/m15_september_shadow_v1';manifest_path=home/'boundary.json'
    auction=pd.read_parquet(stage/'data/cognition/auction_episode_memory.parquet')
    auction['timeframe']='M15'
    ts=pd.to_datetime(auction.timestamp,utc=True)
    if ts.duplicated().any() or ts.isna().any() or ts.max()>cutoff: raise RuntimeError('M15_SHADOW_INVALID_AUCTION_CLOCK')
    if (pd.to_datetime(auction.information_available_at,utc=True)>ts+pd.Timedelta(minutes=15)).any(): raise RuntimeError('M15_SHADOW_FUTURE_AUCTION')
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if manifest['version']!=VERSION or manifest['authoritative_commit']!=COMMIT: raise RuntimeError('M15_BOUNDARY_VERSION_CONFLICT')
    else:
        for stem in STEMS:
            published=existing.get(stem+'.parquet')
            if published is not None and 'builder_version' in published and published.builder_version.astype(str).str.contains(VERSION,regex=False).any():
                raise RuntimeError('M15_SEMANTIC_BOUNDARY_MANIFEST_MISSING')
        life=existing['market_context_lifecycle_memory.parquet']
        if life is None or not len(life): raise RuntimeError('M15_LEGACY_BOUNDARY_SOURCE_MISSING')
        tips=[pd.to_datetime(existing[x+'.parquet'].timestamp,utc=True).max() for x in STEMS]
        if len(set(tips))!=1: raise RuntimeError('M15_LEGACY_BOUNDARY_TIPS_NOT_ALIGNED')
        legacy_end=tips[0]
        if legacy_end>cutoff: raise RuntimeError('M15_BOUNDARY_BEYOND_CLOSED_SOURCE')
        oldeps=read(root/'data/cognition/market_context_lifecycle_episodes.parquet')
        if oldeps is not None and 'timeframe' in oldeps: oldeps=oldeps.loc[oldeps.timeframe=='M15']
        maximum=max([0]+pd.to_numeric(life.context_episode_id,errors='coerce').dropna().astype(int).tolist()+([] if oldeps is None else pd.to_numeric(oldeps.episode_id,errors='coerce').dropna().astype(int).tolist()))
        manifest={'version':VERSION,'authoritative_commit':COMMIT,'legacy_version':'LEGACY_M15_V1_SEMANTICS','legacy_end':str(legacy_end),'first_new_bar_open':str(legacy_end+pd.Timedelta(minutes=15)),'episode_id_offset':maximum,'source_sha256_at_boundary':input_hashes,'shadow_is_published_history':False,'reset_anchor':'NONE_PROVEN; earliest available causal M15 Auction source','legacy_prefix_sha256':{x:hashlib.sha256((root/'data/cognition'/(x+'.parquet')).read_bytes()).hexdigest() for x in STEMS}}
        # Durable boundary BEFORE any output, so a partial publication cannot move it.
        atomic_json(manifest,manifest_path)
    legacy_end=pd.Timestamp(manifest['legacy_end'])
    prior_auction=read(home/'auction.parquet')
    auction=append(prior_auction,auction)
    auction=auction.loc[pd.to_datetime(auction.timestamp,utc=True)<=cutoff].copy()
    if len(auction)==0: raise RuntimeError('M15_SHADOW_EMPTY')
    # Preserve admitted sparse cognition evidence across later snapshots. The
    # existing producer availability gate excludes late/backdated components.
    from btc_ml.external_traders.independent_context_publication import admit_component
    cog_path=stage/'data/cognition/runtime_cognition_memory.parquet'
    runtime=pd.read_parquet(cog_path) if cog_path.exists() else pd.DataFrame()
    runtime=admit_component(runtime,'cognition_m15','M15',cutoff+pd.Timedelta(minutes=15))
    prev_runtime=read(home/'runtime_cognition.parquet')
    if prev_runtime is not None: runtime=append(prev_runtime,runtime)
    C,F,L=[load(root,x) for x in STEMS]
    cognitive=C.build_cognitive_market_state_rows(auction)
    final=F.build_final_market_context_rows(cognitive)
    lifecycle=L.build_lifecycle_memory(final,auction_frame=auction,cognition_frame=runtime,evaluation_frame=cognitive)
    lifecycle['timeframe']='M15'
    frames=dict(zip(STEMS,[cognitive,final,lifecycle]))
    for stem,new in frames.items():
        # Compare the actual persisted representation: original lifecycle
        # returns object Timestamp/None, while parquet restores datetime/NaT.
        buffer=io.BytesIO();new.to_parquet(buffer,index=False);buffer.seek(0)
        stored=pd.read_parquet(buffer)
        previous=read(home/(stem+'.parquet'))
        if previous is not None:
            pd.testing.assert_frame_equal(previous.reset_index(drop=True),stored.iloc[:len(previous)].reset_index(drop=True),check_dtype=False,check_exact=True)
        if new.timestamp.duplicated().any() or set(new.timeframe)!={'M15'}: raise RuntimeError('M15_SHADOW_INVALID_OWNERSHIP')
    before=lifecycle.loc[pd.to_datetime(lifecycle.timestamp,utc=True)<=legacy_end]
    if not len(before): raise RuntimeError('M15_SHADOW_PRIOR_MISSING')
    last=before.iloc[-1]
    if pd.Timestamp(last.timestamp)!=legacy_end: raise RuntimeError('M15_SHADOW_PRIOR_TIP_MISMATCH')
    if 'prior_state' not in manifest:
        manifest.update({'replay_first_timestamp':str(before.timestamp.iloc[0]),'replay_last_timestamp':str(last.timestamp),'replay_rows':len(before),'replay_start_available_at':str(pd.Timestamp(before.timestamp.iloc[0])+pd.Timedelta(minutes=15)),'prior_state':last.to_dict(),'prior_final':final.loc[pd.to_datetime(final.timestamp,utc=True)==legacy_end].iloc[-1].to_dict(),'no_future_reads':'Auction availability <= own close; pointwise Cognitive; forward September process/lifecycle; backward asof cognition admitted by its availability; saved immutable shadow inputs'})
        atomic_json(manifest,manifest_path)
    # Durable private causal inputs/state, never a replacement for legacy output.
    atomic(auction,home/'auction.parquet');atomic(runtime,home/'runtime_cognition.parquet')
    for stem,frame in frames.items(): atomic(frame,home/(stem+'.parquet'))
    for stem,frame in frames.items():
        tail=frame.loc[pd.to_datetime(frame.timestamp,utc=True)>legacy_end].copy()
        tail['builder_version']=tail.builder_version.astype(str)+'|'+VERSION
        # Availability is attached only to the new version's closed rows.
        # Existing M15 values (including legacy missing clocks) stay immutable.
        tail['information_available_at']=pd.to_datetime(tail.timestamp,utc=True)+pd.Timedelta(minutes=15)
        if stem==STEMS[-1]: tail['context_episode_id']=pd.to_numeric(tail.context_episode_id)+manifest['episode_id_offset']
        old=existing[stem+'.parquet']
        combined=append(old,tail)
        atomic(combined,stage/'data/cognition'/(stem+'.parquet'))
    # Do not renumber legacy summaries or let a shadow origin masquerade as a
    # published historical episode. New IDs are numeric, scoped by the adapter.
    tail=lifecycle.loc[pd.to_datetime(lifecycle.timestamp,utc=True)>legacy_end].copy()
    summaries=L.build_lifecycle_episodes(tail)
    for i,row in summaries.iterrows():
        hit=lifecycle.loc[(pd.to_datetime(lifecycle.timestamp,utc=True)==pd.Timestamp(row.start_time))]
        summaries.at[i,'episode_id']=int(hit.iloc[0].context_episode_id)+manifest['episode_id_offset']
    summaries['timeframe']='M15'
    oldeps=read(root/'data/cognition/market_context_lifecycle_episodes.parquet')
    if oldeps is not None and 'timeframe' in oldeps: oldeps=oldeps.loc[oldeps.timeframe=='M15'].copy()
    if oldeps is not None:
        oldeps=oldeps.loc[pd.to_datetime(oldeps.start_time,utc=True)<=legacy_end]
        summaries=pd.concat([oldeps,summaries],ignore_index=True,sort=False)
    atomic(summaries,stage/'data/cognition/market_context_lifecycle_episodes.parquet')
    return json.loads(json.dumps(manifest,default=str),parse_constant=lambda _:None)
