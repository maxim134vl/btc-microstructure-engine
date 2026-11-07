"""Opt-in read-only own-context observation, never contextual inheritance."""
from pathlib import Path
import os,json,io
from .common import *
def decode_snapshot(raw,fmt):
    if fmt=='json':return json.loads(raw)
    if fmt=='parquet':
        import pyarrow.parquet as pq
        pf=pq.ParquetFile(io.BytesIO(raw))
        if pf.metadata.num_rows>4096 or pf.metadata.serialized_size>1024*1024:raise ValueError('SNAPSHOT_ROWS_CAP')
        if pf.metadata.num_columns>64 or sum(pf.metadata.row_group(i).total_byte_size for i in range(pf.metadata.num_row_groups))>8*1024*1024:raise ValueError('SNAPSHOT_UNCOMPRESSED_CAP')
        t=pf.read()
        if t.nbytes>8*1024*1024:raise ValueError('SNAPSHOT_DECODE_CAP')
        meta=pf.schema_arrow.metadata or {}
        def val(k):
            v=meta.get(k.encode());return v.decode('utf-8') if v else None
        return {'rows':t.to_pylist(),'generation':val('generation'),'producer_identity':val('producer_identity'),'content_sha256':val('content_sha256')}
    raise ValueError('SNAPSHOT_FORMAT')
class ContextObserver:
    def __init__(self,recorder,approved_sources,*,enabled=False,decoder=decode_snapshot):
        self.r=recorder;self.sources=dict(approved_sources);self.enabled=enabled;self.decoder=decoder
    def observe(self,tf,*,cutoff=None,expected_source_open=None,read_hook=None):
        with self.r.lock:return self._observe(tf,cutoff=cutoff,expected_source_open=expected_source_open,read_hook=read_hook)
    def _observe(self,tf,*,cutoff=None,expected_source_open=None,read_hook=None):
        if not self.enabled:raise Blocked('CONTEXT_OBSERVER_DISABLED')
        if tf not in TF or tf not in self.sources:raise Blocked('OWN_SOURCE_NOT_APPROVED')
        cfg=self.sources[tf];path=Path(cfg['path']);observed=self.r.clock()
        rec={'type':'CONTEXT_OBSERVED','origin':self.r.origin,'timeframe':tf,'source_path':str(path),'authority_namespace':cfg['authority_namespace'],'producer_identity':cfg['producer_identity'],'first_observed':None,'read_started_clock':observed,'observed_clock':None,'qualification':'UNQUALIFIED','read_consistency':'UNPROVEN','original_publication_time':None,'publication_time_is_first_observed':False,'issues':[],'row_sha256':None}
        try:
            if path.is_symlink() or not path.is_absolute():raise ValueError('SOURCE_PATH_UNSAFE')
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            try:
                before=os.fstat(fd)
                if before.st_size>4*1024*1024:raise ValueError('SNAPSHOT_BYTES_CAP')
                with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(4*1024*1024+1)
                if read_hook:read_hook(path)
                after=os.fstat(fd); current=path.stat()
                token=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
                if token(before)!=token(after) or token(after)!=token(current):raise ValueError('SNAPSHOT_CHANGED_DURING_READ')
            finally:os.close(fd)
            observed=self.r.clock()
            rec['observed_clock']=observed
            rec['first_observed']=observed
            rec['read_finished_clock']=observed
            rec['snapshot_sha256']=sha(raw);rec['read_consistency']='STABLE_FILE_OBSERVATION'
            snap=self.decoder(raw,cfg.get('format','json'));rows=snap.get('rows',[])
            if not isinstance(rows,list) or len(rows)>4096:raise ValueError('SNAPSHOT_ROWS_CAP')
            own=[x for x in rows if x.get('timeframe')==tf]
            if not own:raise ValueError('OWN_TIMEFRAME_UNAVAILABLE')
            if any(not x.get('source_bar_open') for x in own):raise ValueError('OWN_SOURCE_OPEN_MISSING')
            if len({x['source_bar_open'] for x in own})!=len(own):raise ValueError('DUPLICATE_OWN_SOURCE_ROWS')
            row=max(own,key=lambda x:utc(x['source_bar_open']))
            rec.update(row=row,row_sha256=digest(row),generation=snap.get('generation'),source_row_version=row.get('version'),original_publication_time=row.get('first_published_at'),source_information_available_at=row.get('information_available_at'))
            observed=self.r.clock();rec['observed_clock']=observed
            rec['first_observed']=self.r.context_seen.get((tf,rec['row_sha256']),observed)
            if snap.get('content_sha256')!=digest({k:v for k,v in snap.items() if k!='content_sha256'}):rec['issues'].append('SNAPSHOT_GENERATION_HASH_UNPROVEN')
            if not snap.get('generation') or snap.get('producer_identity')!=cfg['producer_identity']:rec['issues'].append('PRODUCER_GENERATION_UNPROVEN')
            if not row.get('version') or not row.get('episode') or row.get('authority_namespace')!=cfg['authority_namespace']:rec['issues'].append('OWN_CONTEXT_LINEAGE_UNPROVEN')
            if expected_source_open and row['source_bar_open']!=expected_source_open:rec['issues'].append('STALE_OR_MISMATCHED_OWN_SOURCE')
            if row.get('first_published_at') and utc(row['first_published_at'])>utc(observed['wall_utc']):rec['issues'].append('PUBLICATION_TIME_IN_FUTURE')
            if cutoff and utc(rec['first_observed']['wall_utc'])>utc(cutoff):rec['issues'].append('OBSERVED_AFTER_EVENT_CUTOFF')
            rec['qualification']='COHERENT_OBSERVATION_ONLY' if not rec['issues'] else 'UNQUALIFIED'
        except (OSError,ValueError,TypeError,KeyError,ImportError) as e:rec['issues'].append(str(e))
        self.r._commit('context:'+str(__import__('uuid').uuid4()),rec)
        if rec['row_sha256'] and rec['qualification']=='COHERENT_OBSERVATION_ONLY':self.r.context_seen.setdefault((tf,rec['row_sha256']),rec['first_observed'])
        return rec
