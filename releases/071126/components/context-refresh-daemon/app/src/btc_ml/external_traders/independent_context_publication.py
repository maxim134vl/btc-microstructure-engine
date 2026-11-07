"""Publication/admission for the original September independent-TF builders.

No classifier formulas or living-process priorities are introduced here.
Four-candle confirmations are evidence, never a rewrite of a primary row.
"""
from pathlib import Path
from datetime import datetime, timezone
import json, os, tempfile
import pandas as pd
from btc_ml.external_traders import rebuild_context as R
from btc_ml.external_traders.tf_market_pack import resample_m15_feed_to_tf

STEMS=('auction_episode_memory','cognitive_market_state_memory','final_market_context_memory','market_context_lifecycle_memory')

def native_safe_close(feed,now=None):
    now=pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    opened=pd.to_datetime(feed.timestamp,utc=True)
    completed=opened.loc[opened+pd.Timedelta(minutes=15)<=now]
    if not len(completed): raise RuntimeError('NO_COMPLETED_M15_MARKET_BAR')
    return completed.max()+pd.Timedelta(minutes=15)

def higher_contexts_need_refresh(root,feed):
    safe=native_safe_close(feed)
    authority_path=Path(root)/'data/cognition/market_context_lifecycle_memory.parquet'
    authority=pd.read_parquet(authority_path) if authority_path.exists() else pd.DataFrame()
    for tf in R.HIGHER_TIMEFRAMES:
        expected=closed_native_bars(feed,tf,safe).timestamp.iloc[-1]
        if not len(authority) or 'timeframe' not in authority: return True
        scope=authority.loc[authority.timeframe.astype(str)==tf]
        if len(scope.loc[pd.to_datetime(scope.timestamp,utc=True)==expected])!=1: return True
        path=Path(root)/'data/cognition/timeframes'/tf/'market_context_lifecycle_memory.parquet'
        if not path.exists(): return True
        current=pd.read_parquet(path,columns=['timestamp'])
        if not len(current) or pd.to_datetime(current.timestamp,utc=True).max()<expected: return True
    return False

def atomic(frame,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.parquet',delete=False) as f: tmp=Path(f.name)
    try:
        frame.to_parquet(tmp,index=False)
        with tmp.open('rb') as f: os.fsync(f.fileno())
        os.replace(tmp,path)
    finally: tmp.unlink(missing_ok=True)

def closed_native_bars(feed,tf,safe_close):
    minutes=R.TF_BAR_MINUTES[tf];work=feed.copy()
    work['timestamp']=pd.to_datetime(work.timestamp,utc=True).astype('datetime64[ns, UTC]')
    if work.timestamp.duplicated().any(): raise RuntimeError('DUPLICATE_M15_SOURCE')
    if not (work.timestamp==work.timestamp.dt.floor('15min')).all(): raise RuntimeError('MISALIGNED_M15_SOURCE')
    work=work.loc[work.timestamp+pd.Timedelta(minutes=15)<=pd.Timestamp(safe_close)]
    bars=resample_m15_feed_to_tf(work,tf)
    bars['timestamp']=pd.to_datetime(bars.timestamp,utc=True).astype('datetime64[ns, UTC]')
    counts=work.groupby(work.timestamp.dt.floor(f'{minutes}min')).size()
    full=counts[counts==minutes//15].index
    bars=bars.loc[bars.timestamp.isin(full)&(bars.timestamp+pd.Timedelta(minutes=minutes)<=safe_close)].reset_index(drop=True)
    if not len(bars): raise RuntimeError(f'NO_COMPLETE_NATIVE_BAR:{tf}')
    return bars

def immutable_append(old,new):
    if old is None or not len(old): return new
    tail=new.loc[pd.to_datetime(new.timestamp,utc=True)>pd.to_datetime(old.timestamp,utc=True).max()]
    return pd.concat([old,tail],ignore_index=True,sort=False) if len(tail) else old.copy()

def admit_component(frame,kind,tf,safe_close):
    """Use the actual producers' clocks, without adding confirmation latency."""
    if not len(frame): return frame
    f=frame.copy();f['timestamp']=pd.to_datetime(f.timestamp,utc=True).astype('datetime64[ns, UTC]')
    # Volume response and convergence timestamp their wall-clock evaluation.
    # Runtime cognition labels a source M15 bar, with a separate propagation clock.
    event_bar=kind in ('cognition_m15','cognition_composite_m15')
    available=f.timestamp+pd.Timedelta(minutes=15) if event_bar else f.timestamp
    for key in ('information_available_at','available_at','evaluated_at','cognition_observed_at','lineage_propagation_timestamp'):
        if key in f:
            at=pd.to_datetime(f[key],utc=True,errors='coerce')
            available=available.where(at.isna() | (available>=at),at)
    native_close=f.timestamp.dt.floor(f'{R.TF_BAR_MINUTES[tf]}min')+pd.Timedelta(minutes=R.TF_BAR_MINUTES[tf])
    # A late component may not repaint the native bar it refers to.
    return f.loc[(available<=safe_close)&(available<=native_close)].copy()

def _unchanged_completed_higher_context(root, tf, bars):
    """Reuse only a fully verified immutable own-TF publication, never re-date it.

    A later M15 close need not re-run H1/H4 classifiers for the same closed bar.
    Every retained artifact is authenticated by the existing phase generation;
    all current own-TF source rows and the full native market input must match.
    Any mismatch/missing/pending evidence falls back to the original native path.
    """
    from io import BytesIO
    from btc_ml.external_traders import context_phase_publication as P
    from btc_ml.external_traders import stage2_predecision_evidence as D
    from btc_ml.external_traders import context_stage2_evidence as E
    root = Path(root)
    try:
        if tf not in R.HIGHER_TIMEFRAMES or bars.empty:
            return None
        folder = root/P.HOME/tf
        if (folder/'pending.json').exists():
            return None
        pointer = json.loads((folder/'head.json').read_bytes())
        verified = P._verified_generation(root, tf, pointer)
        m = verified['manifest']
        target = pd.to_datetime(bars.timestamp, utc=True).max()
        if pd.Timestamp(m['target_bar_open']) != target:
            return None
        # Preserve retry of an interrupted Stage2 sidecar delivery. Missing/late
        # observations remain diagnostic; no new admission is inferred here.
        E.read_context_evidence(root, tf, target)
        slot = folder/'bars'/target.strftime('%Y%m%dT%H%M%SZ.json')
        if json.loads(slot.read_bytes()) != pointer:
            return None
        if any(p.stem > target.strftime('%Y%m%dT%H%M%SZ') for p in (folder/'bars').glob('*.json')):
            return None
        gen = folder/'generations'/pointer['generation_id']
        frames, current_pins = {}, {}
        for rel in P._paths(tf):
            raw = (root/'data'/rel).read_bytes()
            current_pins[rel] = E._sha(raw)
            current = pd.read_parquet(BytesIO(raw))
            retained = pd.read_parquet(gen/'sources'/rel)
            scoped = []
            for frame in (current, retained):
                if 'timeframe' not in frame:
                    return None
                if rel != 'cognition/market_context_lifecycle_memory.parquet' and set(frame.timeframe.astype(str)) != {tf}:
                    return None
                scoped.append(frame.loc[frame.timeframe.astype(str) == tf].reset_index(drop=True))
            if D._history_frame_sha(scoped[0]) != D._history_frame_sha(scoped[1]):
                return None
            frames[rel] = scoped[0]
        market = frames[P._paths(tf)[-1]]
        if not set(bars.columns) <= set(market.columns):
            return None
        if D._history_frame_sha(bars.reset_index(drop=True)) != D._history_frame_sha(market[list(bars.columns)].reset_index(drop=True)):
            return None
        base = Path('data/cognition/timeframes')/tf
        life = frames[P._paths(tf)[3]]
        final = frames[P._paths(tf)[2]]
        if (life.timestamp.duplicated().any() or final.timestamp.duplicated().any()
                or pd.to_datetime(life.timestamp,utc=True).max() != target
                or pd.to_datetime(final.timestamp,utc=True).max() != target):
            return None
        episodes = pd.read_parquet(root/base/'market_context_lifecycle_episodes.parquet')
        confirmations = pd.read_parquet(root/base/'auction_episode_confirmations.parquet')
        if 'timeframe' not in episodes or set(episodes.timeframe.astype(str)) != {tf}:
            return None
        tip = life.iloc[-1]
        return {'lifecycle':life, 'episodes':episodes, 'artifacts':[],
            'summary':{'status':'UNCHANGED_VERIFIED_IMMUTABLE_OWN_TF',
                'rows':len(life),'confirmations':len(confirmations),
                'source_bar_open':str(target),
                'source_bar_close':str(target+pd.Timedelta(minutes=R.TF_BAR_MINUTES[tf])),
                'active_market_context':tip.active_market_context,
                'living_process':tip.living_process,'process_strength':float(tip.process_strength),
                'retained_phase_generation':pointer,'current_source_sha256':current_pins,
                'new_publication':False,'new_receipt':False}}
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        return None


def prepare_higher_contexts(root,stage,feed,safe_close,on_complete=None):
    R.ROOT=Path(root)
    feed=feed.copy();feed['timestamp']=pd.to_datetime(feed.timestamp,utc=True).astype('datetime64[ns, UTC]')
    optional={}
    for arg,rel in [('volume_response_m15','data/cognition/volume_response_state.parquet'),('convergence_m15','data/reinforcement/auction_convergence_memory.parquet'),('probabilistic_m15','data/probabilistic/probabilistic_auction_memory.parquet'),('cognition_m15','data/cognition/runtime_cognition_memory.parquet'),('cognition_composite_m15','data/cognition/runtime_cognition_composite.parquet')]:
        path=Path(stage)/rel;f=pd.read_parquet(path) if path.exists() else pd.DataFrame()
        if len(f):
            f['timestamp']=pd.to_datetime(f.timestamp,utc=True).astype('datetime64[ns, UTC]')
        optional[arg]=f
    results={};published=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    for tf in R.HIGHER_TIMEFRAMES:
        minutes=R.TF_BAR_MINUTES[tf];duration=pd.Timedelta(minutes=minutes)
        bars=closed_native_bars(feed,tf,safe_close)
        unchanged = _unchanged_completed_higher_context(root, tf, bars)
        if unchanged is not None:
            results[tf] = unchanged
            print('TIMEFRAME_REUSED '+json.dumps({'timeframe':tf,**unchanged['summary']}),flush=True)
            continue
        relbase=Path('data/cognition/timeframes')/tf
        artifacts=[];frames_seen={};auction_frames={};modules={}
        loader=R._load_script
        def capture(name,path):
            mod=loader(name,path);modules[name]=mod
            if hasattr(mod,'build_auction_episode_rows'):
                fn=mod.build_auction_episode_rows
                def build(frames=None,**kwargs):
                    auction_frames.update(frames or {})
                    return fn(frames=frames,**kwargs)
                mod.build_auction_episode_rows=build
            return mod
        def sink(stem,frame):
            if frame.timestamp.isna().any() or frame.timestamp.duplicated().any(): raise RuntimeError(f'INVALID_PRIMARY_KEYS:{tf}:{stem}')
            if set(frame.timeframe.astype(str))!={tf}: raise RuntimeError(f'OWNER_LOST:{tf}:{stem}')
            out=frame.copy()
            out['source_bar_open']=pd.to_datetime(out.timestamp,utc=True)
            out['source_bar_close']=out.source_bar_open+duration
            out['information_available_at']=out.source_bar_close
            out['first_published_at']=published
            out['publication_kind']='CAUSAL_HISTORY_INITIALIZATION_OR_NEW_CLOSED_BAR'
            path=Path(root)/relbase/(stem+'.parquet')
            old=pd.read_parquet(path) if path.exists() else None
            out=immutable_append(old,out)
            if (pd.to_datetime(out.information_available_at,utc=True)>safe_close).any(): raise RuntimeError(f'FUTURE_PRIMARY:{tf}:{stem}')
            atomic(out,Path(stage)/relbase/(stem+'.parquet'))
            artifacts.append(str(relbase/(stem+'.parquet')));frames_seen[stem]=out
            return out
        R._load_script=capture
        try:
            admitted={kind:admit_component(f,kind,tf,safe_close) for kind,f in optional.items()}
            from btc_ml.external_traders.stage2_predecision_evidence import lifecycle_conclusions_reader, prepare_consumption_records
            prior_path=Path(root)/'data/cognition/market_context_lifecycle_memory.parquet'
            prior=pd.read_parquet(prior_path) if prior_path.exists() else pd.DataFrame()
            own=prior.loc[prior.timeframe.astype(str)==tf] if len(prior) and 'timeframe' in prior else pd.DataFrame()
            previous_tip=None if not len(own) else pd.to_datetime(own.timestamp,utc=True).max()
            from btc_ml.external_traders.stage2_predecision_evidence import auction_climax_reader
            auction_records=[]
            stage2_records=[]
            life,episodes=R.build_independent_tf_lifecycle(bars,timeframe=tf,stage_sink=sink,
                stage2_reader_factory=lambda final: lifecycle_conclusions_reader(stage,final,previous_tip=previous_tip),
                stage2_consumptions=stage2_records,auction_stage2_reader=auction_climax_reader(stage,tf),
                auction_stage2_consumptions=auction_records,**admitted)
            prepare_consumption_records(stage,stage2_records)
        finally: R._load_script=loader
        # The original full-horizon classifier is run separately, never into Final.
        ae=modules['etll_build_auction_episode_memory']
        complete=ae.build_auction_episode_rows(frames=auction_frames,confirmation=True,
            stage2_reader=auction_climax_reader(stage,tf))
        closes=pd.to_datetime(complete.timestamp,utc=True)
        ready=(closes.shift(-4)==closes+4*duration)
        conf=complete.loc[ready].copy()
        conf['source_event_timestamp']=pd.to_datetime(conf.timestamp,utc=True)
        conf['observation_available_at']=conf.source_event_timestamp+duration
        conf['confirmation_window_end']=conf.source_event_timestamp+4*duration
        conf['information_available_at']=conf.source_event_timestamp+5*duration
        conf['confirmation_horizon_bars']=4
        conf['confirmation_id']=tf+':FT4:'+conf.source_event_timestamp.dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        conf['first_published_at']=published
        conf['applied_to_living_process']=False
        conf['live_application_contract']='NOT_FOUND_IN_ORIGINAL_IMPLEMENTATION'
        rel=relbase/'auction_episode_confirmations.parquet';oldpath=Path(root)/rel
        old=pd.read_parquet(oldpath) if oldpath.exists() else None
        conf=immutable_append(old,conf)
        if len(conf) and (pd.to_datetime(conf.information_available_at,utc=True)>safe_close).any(): raise RuntimeError(f'FUTURE_CONFIRMATION:{tf}')
        atomic(conf,Path(stage)/rel);artifacts.append(str(rel))
        rel=relbase/'market_context_lifecycle_episodes.parquet'
        atomic(episodes,Path(stage)/rel);artifacts.append(str(rel))
        # Source candles are audit evidence, not fabricated volume/context rows.
        bars['timeframe']=tf;bars['source_bar_close']=bars.timestamp+duration
        rel=relbase/'native_closed_candles.parquet';atomic(bars,Path(stage)/rel);artifacts.append(str(rel))
        tip=life.iloc[-1]
        results[tf]={'lifecycle':life,'episodes':episodes,'artifacts':artifacts,'summary':{'rows':len(life),'native_stage2_auction_consumption':[{k:v for k,v in r.items() if k not in ('raw_native_fields','native_events')} for r in auction_records],'confirmations':len(conf),'source_bar_open':str(tip.timestamp),'source_bar_close':str(pd.Timestamp(tip.timestamp)+duration),'active_market_context':tip.active_market_context,'living_process':tip.living_process,'process_strength':float(tip.process_strength),'four_bar_confirmation_applied':False,'late_confirmation_application_contract':'NOT_FOUND_IN_ORIGINAL_IMPLEMENTATION','primary_follow_through_wait_bars':0}}
        if on_complete is not None: on_complete(tf,results[tf])
    return results
