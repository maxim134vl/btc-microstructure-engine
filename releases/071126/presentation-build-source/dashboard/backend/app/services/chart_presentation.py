"""Presentation of native owner outputs; no classifiers, P&L or trading decisions."""
from __future__ import annotations
import copy,json,threading,time
from datetime import timedelta
from pathlib import Path
from app.services.runtime_observation import DATA,VISUAL,read_json,utc,stamp

MINUTES={'M15':15,'M30':30,'H1':60,'H4':240}
_lock=threading.Lock();_cache=None;_at=0;_projections={}

def native_rows(path,tf):
    import pyarrow.parquet as pq
    p=Path(path);before=p.stat()
    if before.st_size>8*1024*1024:raise ValueError('PRESENTATION_INPUT_SIZE_BOUND')
    names=set(pq.ParquetFile(p).schema.names)
    wanted=['timestamp','timeframe','close','market_context','active_market_context','lifecycle_state','context_episode_id','context_status','living_process','process_strength','source_bar_open','source_bar_close','information_available_at','first_published_at','raw_market_context','context_reason','state_reason']
    rows=pq.ParquetFile(p).read(columns=[x for x in wanted if x in names],use_threads=False).to_pylist()
    after=p.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED_DURING_READ')
    rows=[r for r in rows if r.get('timeframe')==tf]
    if not rows:raise ValueError('OWN_TF_ROWS_UNAVAILABLE:'+tf)
    result={}
    for r in rows:
        t=r.get('timestamp');t=t.isoformat() if hasattr(t,'isoformat') else str(t)
        if t in result:raise ValueError('DUPLICATE_OWNER_BAR:'+tf)
        r={k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in r.items()};r['timestamp']=t;result[t]=r
    return result,{'source':str(p),'file_mtime_ns':after.st_mtime_ns,'bytes':after.st_size,'owner':'native Final/Lifecycle publisher','timeframe':tf}

def project_native(block,tf,root=DATA,window_start=None):
    base=Path(root)/'cognition' if tf=='M15' else Path(root)/'cognition/timeframes'/tf
    try:
        final,fmeta=native_rows(base/'final_market_context_memory.parquet',tf)
        life,lmeta=native_rows(base/'market_context_lifecycle_memory.parquet',tf)
        common=sorted(set(final)&set(life),key=lambda x:utc(x) or utc('1970-01-01T00:00:00Z'))
        if not common:raise ValueError('NO_ALIGNED_NATIVE_OWNER_RESULTS')
        rows=[];segs=[]
        for opened in common:
            t=utc(opened)
            if t is None:raise ValueError('MISSING_OWNER_BAR_CLOCK')
            if window_start is not None and t+timedelta(minutes=MINUTES[tf])<utc(window_start):continue
            if t.timestamp()%(MINUTES[tf]*60):raise ValueError('MISALIGNED_OWN_BAR')
            f,l=final[opened],life[opened]
            if l.get('raw_market_context') is not None and f.get('market_context')!=l.get('raw_market_context'):raise ValueError('FINAL_LIFECYCLE_GENERATION_MISMATCH')
            closed=t+timedelta(minutes=MINUTES[tf])
            row={'bar_open':opened,'bar_close':closed.isoformat(),'final_context':f.get('market_context'),'lifecycle_context':l.get('active_market_context'),'lifecycle_state':l.get('lifecycle_state'),'episode_id':l.get('context_episode_id'),'living_process':f.get('living_process'),'process_strength':f.get('process_strength'),'owner_published_at':l.get('first_published_at') or f.get('first_published_at'),'information_available_at':l.get('information_available_at') or f.get('information_available_at'),'source':lmeta['source']}
            if window_start is None or closed>=utc(window_start):
                rows.append(row);segs.append({'timeframe':tf,'start_timestamp':opened,'end_timestamp':closed.isoformat(),'directional_state':row['lifecycle_context'],'final_context':row['final_context'],'lifecycle_state':row['lifecycle_state'],'lifecycle_episode_id':row['episode_id'],'source':row['source'],'source_timestamp':opened,'context_price':l.get('close'),'active':False})
        tip=rows[-1] if rows else None
        if tip is None:raise ValueError('NO_OWNER_RESULTS_IN_VIEW_WINDOW')
        candle_close=utc((block.get('candle_contract') or {}).get('latest_confirmed_close'))
        owner_close=utc(tip['bar_close']);behind=(candle_close-owner_close).total_seconds() if candle_close else None
        status='BEHIND_CANDLES' if behind is not None and behind>0 else 'CANDLES_BEHIND_CONTEXT' if behind is not None and behind<0 else 'CURRENT_AT_CANDLE_CUT' if behind==0 else 'UNKNOWN'
        block['native_context']={'status':status,'context_lag_to_candles_s':behind,'tip':tip,'rows':rows,'sources':[fmeta,lmeta],'observed_at':stamp(),'note':'Literal own-TF owner results. Behind-candles is a display comparison, not a trading admission rule.'}
        # Replace mixed/global legacy context bands only. Trade and context event identities stay distinct.
        segs=[seg for seg in segs if candle_close is None or utc(seg['end_timestamp'])<=candle_close]
        block['context_zones']=segs;block['context_segments']=segs;block['context_history']=segs;block['context_source']='NATIVE_OWN_TF_FINAL_LIFECYCLE'
    except (OSError,ValueError,KeyError,IndexError) as exc:
        block['native_context']={'status':'DATA_UNAVAILABLE','reason':str(exc),'observed_at':stamp(),'timeframe':tf,'source':str(base)}
        block['context_zones']=[];block['context_segments']=[];block['context_history']=[]
    return block

def read_phase(tf,report=None):
    base=DATA/'cognition/context_trend_phase_v1'/tf
    head,meta=read_json(base/'head.json')
    if not head:return {'status':'DATA_UNAVAILABLE','source':str(base),'reason':meta.get('reason')}
    # Never calculate a phase from candles or requalify it. Unknown publisher shapes stay explicit.
    summary=None
    for row in (report or {}).get('outputs',[]):
        phase=row.get('context_phase') or {}
        if row.get('timeframe')==tf and phase.get('generation_id')==head.get('generation_id'):
            summary=phase
    if summary is None:
        analysis,analysis_meta=read_json(base/'generations'/str(head.get('generation_id'))/'phase.json')
        results=(analysis or {}).get('results') or []
        if results and results[-1].get('timeframe')==tf:summary=results[-1]
    receipt,rmeta=read_json(base/'generations'/str(head.get('generation_id'))/'receipt.meta.json')
    return {'status':'OWNER_SUMMARY_OBSERVED' if summary else 'OWNER_HEAD_OBSERVED_SUMMARY_UNAVAILABLE','source':meta,'head':head,'summary':summary,'published_at':(receipt or {}).get('publication_completed_at'),'reason':None if summary else 'A compact summary for the current phase generation is not yet published','note':'Display only; no qualification is performed by OPS'}

def read_chart():
    global _cache,_at
    with _lock:
        if _cache is not None and time.monotonic()-_at<15:return copy.deepcopy(_cache)
        value,meta=read_json(VISUAL/'timeframe_chart_truth.json',16*1024*1024)
        if not isinstance(value,dict):return {'status':'DATA_UNAVAILABLE','source':meta,'timeframes':{},'generated_at':None}
        value['presentation']={'observed_at':stamp(),'source':meta,'scope':'read-only own-TF owner results; no market classifications or financial arithmetic','clock':'UTC'}
        value.pop('global_lifecycle',None)
        phase_report,_=read_json(DATA/'live/primary_context_publication.json')
        for tf in MINUTES:
            block=value.get('timeframes',{}).get(tf)
            if not isinstance(block,dict):value.setdefault('timeframes',{})[tf]={'native_context':{'status':'DATA_UNAVAILABLE','reason':'OWN_TF_BLOCK_MISSING'},'candles':[]};continue
            for kind in ('candles','context_events','open_positions','closed_trades'):
                if isinstance(block.get(kind),list):block[kind]=[x for x in block[kind] if (x.get('timeframe',tf)==tf if kind=='candles' else x.get('timeframe')==tf)]
            base=DATA/'cognition' if tf=='M15' else DATA/'cognition/timeframes'/tf
            versions=[]
            for filename in ['final_market_context_memory.parquet','market_context_lifecycle_memory.parquet']:
                try:
                    st=(base/filename).stat();versions.append((st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns))
                except OSError:versions.append(None)
            key=(tuple(versions),value.get('window_start'),(block.get('candle_contract') or {}).get('latest_confirmed_close'))
            cached=_projections.get(tf)
            if cached and cached[0]==key:block.update(copy.deepcopy(cached[1]))
            else:
                block=project_native(block,tf,window_start=value.get('window_start'))
                _projections[tf]=(key,{k:copy.deepcopy(block.get(k)) for k in ['native_context','context_zones','context_segments','context_history','context_source']})
            block['trend_phase_owner']=read_phase(tf,phase_report)
            if (block.get('anti_saw') or {}).get('error'):block['anti_saw']['is_saw']=None
        _cache=value;_at=time.monotonic();return copy.deepcopy(value)
