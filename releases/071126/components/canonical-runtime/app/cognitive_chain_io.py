"""Operational IO for original cognitive scripts; never supplies missing states.

Core schemas/formulas are unchanged. Publication journals use actual availability,
not candle open times. Strict canonical paths exclude archive migration.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import uuid

import pandas as pd
from storage.path_registry import COGNITIVE_CHAIN_FILES, resolve_read, resolve_write, data_root

OUTPUTS = {
 'test_recognition_engine_v1.py':'test_recognition_memory.parquet',
 'defended_liquidity_engine_v1.py':'defended_liquidity_memory.parquet',
 'contextual_memory_loader_v2.py':'contextual_memory_state.parquet',
 'perception_context_integration_v1.py':'perception_context_integration.parquet',
 'temporal_context_memory_v1.py':'temporal_context_memory.parquet',
}
BAR_FILES={'candle_geometry_v2_memory.parquet','volume_localization_v2_memory.parquet','test_recognition_memory.parquet','defended_liquidity_memory.parquet'}
HISTORY_FILES={'test_recognition_memory.parquet','defended_liquidity_memory.parquet'}

def validate_times(frame, name, at):
    if frame.empty or 'timestamp' not in frame:
        raise ValueError('Required timestamped input empty or invalid: '+name)
    times=pd.to_datetime(frame.timestamp,utc=True)
    if times.isna().any() or not times.is_monotonic_increasing:
        raise ValueError('Input timestamps invalid or out of order: '+name)
    if name in BAR_FILES:
        if times.duplicated().any():
            raise ValueError('Duplicate candle input: '+name)
        if (times+pd.Timedelta(minutes=15) > at).any():
            raise ValueError('Incomplete/future candle input: '+name)
    elif (times > at).any():
        raise ValueError('Future cognitive input: '+name)


def install_io(engine):
    if os.environ.get('BTC_ML_COGNITIVE_CHAIN_LIVE','0') != '1':
        return
    read_original=pd.read_parquet
    write_original=pd.DataFrame.to_parquet
    decision_at=pd.Timestamp.now(tz='UTC')
    input_records=[]
    frames={}
    output=OUTPUTS[engine]
    folder=data_root()/'diagnostics/cognitive_chain'
    folder.mkdir(parents=True,exist_ok=True)

    def publications(name):
        for path in sorted((folder/name.removesuffix('.parquet')).glob('*.json')):
            yield json.loads(path.read_text())

    def read(path,*args,**kwargs):
        # Original source reader passes BytesIO; its own publication contract applies.
        if not isinstance(path,(str,os.PathLike)):
            return read_original(path,*args,**kwargs)
        name=Path(path).name
        target=Path(resolve_read(name))
        raw=target.read_bytes()
        sha=hashlib.sha256(raw).hexdigest()
        frame=read_original(io.BytesIO(raw),*args,**kwargs)
        validate_times(frame,name,decision_at)
        available_at=pd.Timestamp(target.stat().st_mtime_ns,tz='UTC')
        if available_at > decision_at:
            raise RuntimeError('Input changed after decision cutoff: '+name)
        if name in COGNITIVE_CHAIN_FILES:
            matches=[p for p in publications(name) if p['sha256']==sha and pd.Timestamp(p['available_at'])<=decision_at]
            if not matches:
                raise RuntimeError('No proven current-generation cognitive publication: '+name)
            available_at=pd.Timestamp(matches[-1]['available_at'])
        frames[name]=frame
        geometry=frames.get('candle_geometry_v2_memory.parquet')
        zones=frames.get('volume_localization_v2_memory.parquet')
        if geometry is not None and zones is not None:
            if not pd.to_datetime(geometry.timestamp,utc=True).reset_index(drop=True).equals(pd.to_datetime(zones.timestamp,utc=True).reset_index(drop=True)):
                raise ValueError('Original positional geometry/zone join is not timestamp-aligned')
        input_records.append(dict(file=name,path=str(target),sha256=sha,read_at=str(pd.Timestamp.now(tz='UTC')),available_at=str(available_at),rows=len(frame),latest_observation=str(pd.to_datetime(frame.timestamp,utc=True).max())))
        return frame

    def write(frame,path,*args,**kwargs):
        name=Path(path).name
        if name != output:
            raise PermissionError('Cognitive script may publish only its original output')
        validate_times(frame,name,pd.Timestamp.now(tz='UTC'))
        target=Path(resolve_write(name))
        old=None
        if target.exists():
            old=read_original(target)
            if name in HISTORY_FILES:
                if len(frame)<len(old):
                    raise ValueError('Existing cognitive history cannot be truncated')
                pd.testing.assert_frame_equal(old.reset_index(drop=True),frame.iloc[:len(old)].reset_index(drop=True))
            elif name=='temporal_context_memory.parquet':
                # Preserve original tail(500) ring and every overlapping past row.
                suffix=frame.iloc[:-1].reset_index(drop=True)
                pd.testing.assert_frame_equal(old.tail(len(suffix)).reset_index(drop=True),suffix)
                if pd.to_datetime(frame.timestamp.iloc[-1],utc=True) <= pd.to_datetime(old.timestamp.iloc[-1],utc=True):
                    raise ValueError('Repeated/backdated temporal event is not a new decision')
            if old.equals(frame) and any(p['sha256']==hashlib.sha256(target.read_bytes()).hexdigest() for p in publications(name)):
                print('COGNITIVE_PUBLICATION_UNCHANGED '+name,flush=True)
                return
        # Journal stores immutable actual publications, including snapshot projections.
        pubfolder=folder/name.removesuffix('.parquet');pubfolder.mkdir(exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='.'+name+'.',dir=target.parent)
        os.close(fd)
        try:
            write_original(frame,tmp,*args,**kwargs)
            with open(tmp,'rb') as handle:
                os.fsync(handle.fileno())
            sha=hashlib.sha256(Path(tmp).read_bytes()).hexdigest()
            os.replace(tmp,target)
        finally:
            Path(tmp).unlink(missing_ok=True)
        event=dict(engine=engine,file=name,path=str(target),sha256=sha,decision_at=str(decision_at),available_at=str(pd.Timestamp.now(tz='UTC')),rows=len(frame),schema=list(frame.columns),latest_observation=str(pd.to_datetime(frame.timestamp,utc=True).max()),inputs=input_records,records=json.loads(frame.to_json(orient='records',date_format='iso',date_unit='us')))
        pub=pubfolder/(uuid.uuid4().hex+'.json')
        temporary=pub.with_suffix('.tmp')
        with temporary.open('x') as handle:
            json.dump(event,handle);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,pub)
        print('COGNITIVE_PUBLISHED '+json.dumps({k:v for k,v in event.items() if k not in {'records'}}),flush=True)

    pd.read_parquet=read
    pd.DataFrame.to_parquet=write
    return decision_at
