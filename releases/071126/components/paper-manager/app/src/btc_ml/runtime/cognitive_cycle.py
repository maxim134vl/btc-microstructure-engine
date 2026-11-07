"""Approved observation-only cognitive cycle; original reducers, no trading authority."""
from __future__ import annotations
import ast
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
from unittest.mock import patch
import pandas as pd

CONTRACT = 'COLD_START_FROM_OBSERVATIONS_V1'
OUTPUTS = ('perception_context_integration.parquet','contextual_memory_state.parquet','temporal_context_memory.parquet')
PROJECTION_FIELDS = ('timestamp','regime_state','inventory_modifier','acceptance_modifier','reaction_state','volume_state')
LEGACY = ('volume_memory.parquet','inventory_states.parquet','acceptance_states.parquet','regime_history.parquet','volume_reactions.parquet')
BARS = ('candle_geometry_v2_memory.parquet','volume_localization_v2_memory.parquet','test_recognition_memory.parquet','defended_liquidity_memory.parquet')
SOURCE = Path(__file__).resolve().parents[3]

class CognitiveStateUnavailable(RuntimeError):
    pass

def sha(raw): return hashlib.sha256(raw).hexdigest()
def now(): return pd.Timestamp.now(tz='UTC').isoformat()
def encode(obj): return json.dumps(obj,sort_keys=True,default=str).encode()
def home(root): return Path(root)/'diagnostics/cognitive_cycle'
def sync_dir(path):
    fd=os.open(path,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
def atomic(path, raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.tmp')
    with temporary.open('wb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(temporary,path);sync_dir(path.parent)
def load(path): return json.loads(Path(path).read_bytes())

def verified_commit(folder, pointer):
    if not isinstance(pointer.get('id'),str) or len(pointer['id'])!=64 or any(c not in '0123456789abcdef' for c in pointer['id']):
        raise CognitiveStateUnavailable('INVALID_COMMIT_ID')
    base=folder/'commits'/pointer['id'];raw=(base/'manifest.json').read_bytes()
    if sha(raw)!=pointer['manifest_sha256']:raise CognitiveStateUnavailable('COMMIT_MANIFEST_MISMATCH')
    manifest=json.loads(raw)
    reservation=load(folder.parent.parent/'runtime/cognitive_generation_reservation.json')
    if reservation['genesis_sha256']!=sha((folder/'genesis.json').read_bytes()):raise CognitiveStateUnavailable('GENERATION_RESERVATION_MISMATCH')
    if manifest['genesis_sha256']!=sha((folder/'genesis.json').read_bytes()):raise CognitiveStateUnavailable('GENESIS_IDENTITY_MISMATCH')
    if manifest['generation']!=load(folder/'genesis.json')['generation']:raise CognitiveStateUnavailable('GENERATION_MISMATCH')
    if manifest['parent_head_sha256'] is not None:
        if sha((base/'parent.json').read_bytes())!=manifest['parent_head_sha256']:raise CognitiveStateUnavailable('PARENT_POINTER_MISMATCH')
    for name in OUTPUTS:
        if sha((base/name).read_bytes())!=manifest['outputs'][name]:raise CognitiveStateUnavailable('COMMITTED_STATE_CORRUPT')
    inputs_raw=(base/'inputs.json').read_bytes()
    if sha(inputs_raw)!=manifest['input_manifest_sha256']:raise CognitiveStateUnavailable('INPUT_LINEAGE_MISMATCH')
    for name,h in json.loads(inputs_raw)['file_sha256'].items():
        if sha((base/'inputs'/name).read_bytes())!=h:raise CognitiveStateUnavailable('COMMITTED_INPUT_CORRUPT')
    return base,manifest

def committed_state_path(root, name):
    folder=home(root)
    if (folder/'pending.json').exists():raise CognitiveStateUnavailable('UNFINISHED_COGNITIVE_PUBLICATION')
    if not (folder/'head.json').exists():return str(folder/'not-ready'/name)
    try: base,manifest=verified_commit(folder,load(folder/'head.json'))
    except (OSError,ValueError,KeyError) as error:raise CognitiveStateUnavailable('UNREADABLE_COMMITTED_COGNITIVE_STATE') from error
    return str(base/name)

def committed_paths(root):
    folder=home(root)
    if (folder/'pending.json').exists():raise CognitiveStateUnavailable('UNFINISHED_COGNITIVE_PUBLICATION')
    try:
        base,manifest=verified_commit(folder,load(folder/'head.json'))
    except (OSError,KeyError,ValueError) as error:raise CognitiveStateUnavailable('NO_CONFIRMED_COGNITIVE_SET') from error
    return {**{name:str(base/name) for name in OUTPUTS},**{name:str(base/'inputs'/name) for name in LEGACY+BARS}}

def original(name, frames):
    """Execute untouched scripts in the dedicated support process, intercept IO only."""
    from storage import path_registry as paths
    outputs={}
    def read(path,*a,**kw):
        key=Path(path).name
        if key not in frames:raise FileNotFoundError(key)
        return frames[key].copy(deep=True)
    def write(frame,path,*a,**kw):outputs[Path(path).name]=frame.copy(deep=True)
    with patch.object(paths,'resolve_read',lambda x:x),patch.object(paths,'resolve_write',lambda x:x),patch.object(pd,'read_parquet',read),patch.object(pd.DataFrame,'to_parquet',write),contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(str(SOURCE/name),run_name='__main__')
    return outputs

def projections(frames):
    """Reuse exact observation assignments; defer only temporal confidence bonuses."""
    tree=ast.parse((SOURCE/'perception_context_integration_v1.py').read_text())
    aliases={'last_inventory':'inventory_states.parquet','last_acceptance':'acceptance_states.parquet','last_reaction':'volume_reactions.parquet','last_test':'test_recognition_memory.parquet','last_liquidity':'defended_liquidity_memory.parquet','last_geometry':'candle_geometry_v2_memory.parquet','last_localization':'volume_localization_v2_memory.parquet'}
    scope={k:frames[v].iloc[-1] for k,v in aliases.items()};nodes=[];started=False
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='inventory_modifier' for t in node.targets):started=True
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='integration' for t in node.targets):break
        if not started:continue
        if any(isinstance(n,ast.Name) and n.id=='last_temporal' for n in ast.walk(node)):
            if not isinstance(node,ast.If) or any(isinstance(n,(ast.Assign,ast.AugAssign)) and ast.unparse(n.target if isinstance(n,ast.AugAssign) else n.targets[0])!='context_confidence' for n in ast.walk(node)):
                raise RuntimeError('UNAPPROVED_TEMPORAL_MODIFIER_DEPENDENCY')
            continue
        nodes.append(node)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<original perception observation blocks>','exec'),scope)
    modifiers={k:scope[k] for k in ('inventory_modifier','acceptance_modifier','reaction_modifier')}
    # Exact expressions from original Contextual output, not a substitute classifier.
    ct=ast.parse((SOURCE/'contextual_memory_loader_v2.py').read_text())
    assignment=next(n for n in ct.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='context_state' for t in n.targets))
    values=assignment.value.args[0]
    cs={'latest_regime':frames['regime_history.parquet'].iloc[-1],'latest_reaction':frames['volume_reactions.parquet'].iloc[-1],'latest_volume':frames['volume_memory.parquet'].iloc[-1],'latest_integration':modifiers}
    result={}
    for key,value in zip(values.keys,values.values):
        if key.value in PROJECTION_FIELDS:result[key.value]=eval(compile(ast.Expression(value),'<original contextual projection>','eval'),cs)
    if set(result)!=set(PROJECTION_FIELDS):raise RuntimeError('PROJECTION_SCHEMA_CHANGED')
    return pd.DataFrame(result)

def calculate(frames, previous=None):
    if previous is None:
        projection=projections(frames)
        temporal=original('temporal_context_memory_v1.py',{'contextual_memory_state.parquet':projection})['temporal_context_memory.parquet']
        inputs=dict(frames,**{'temporal_context_memory.parquet':temporal})
        perception=original('perception_context_integration_v1.py',inputs)['perception_context_integration.parquet']
        contextual=original('contextual_memory_loader_v2.py',dict(inputs,**{'perception_context_integration.parquet':perception}))['contextual_memory_state.parquet']
        pd.testing.assert_frame_equal(projection[list(PROJECTION_FIELDS)].reset_index(drop=True),contextual[list(PROJECTION_FIELDS)].reset_index(drop=True))
    else:
        memory=previous['temporal_context_memory.parquet']
        perception=original('perception_context_integration_v1.py',dict(frames,**{'temporal_context_memory.parquet':memory}))['perception_context_integration.parquet']
        contextual=original('contextual_memory_loader_v2.py',dict(frames,**{'temporal_context_memory.parquet':memory,'perception_context_integration.parquet':perception}))['contextual_memory_state.parquet']
        temporal=original('temporal_context_memory_v1.py',{'contextual_memory_state.parquet':contextual,'temporal_context_memory.parquet':memory})['temporal_context_memory.parquet']
        pd.testing.assert_frame_equal(memory.tail(min(len(memory),499)).reset_index(drop=True),temporal.iloc[:-1].reset_index(drop=True))
    return dict(zip(OUTPUTS,(perception,contextual,temporal)))

def observe(root, cutoff, observation_cutoff=None):
    """Verified original Futures publications plus retained real, closed bar inputs."""
    from legacy_source_inputs import legacy_source_root,publication_records,select_available
    from storage.path_registry import resolve_read
    at=pd.Timestamp(cutoff);market_at=pd.Timestamp(observation_cutoff or cutoff)
    if at.tzinfo is None or market_at.tzinfo is None or market_at>at:raise ValueError('INVALID_CUTOFF')
    rawroot=legacy_source_root()
    if rawroot is None:raise CognitiveStateUnavailable('ORIGINAL_SOURCE_ROUTING_REQUIRED')
    frames={};proof={}
    for name in LEGACY:
        raw=(rawroot/name).read_bytes();source_sha=sha(raw);records=publication_records(rawroot,name)
        if not any(p.get('sha256')==source_sha for p in records):raise CognitiveStateUnavailable('UNPROVEN_SOURCE_PUBLICATION:'+name)
        selected,available=select_available(pd.read_parquet(io.BytesIO(raw)),records,name,market_at)
        selected=selected.sort_values('timestamp').tail(1).reset_index(drop=True)
        frames[name]=selected
        proof[name]={'selected_rows_sha256':_frame_sha(selected),'source_sha256':source_sha,'original_publication_latest_available_at':str(max(pd.to_datetime(available,utc=True))),'authority':'ORIGINAL_CAPTURED_FUTURES_PUBLICATION'}
    for name in BARS:
        path=Path(resolve_read(name));raw=path.read_bytes();available=pd.Timestamp(path.stat().st_mtime_ns,tz='UTC')
        if available>at:raise CognitiveStateUnavailable('INPUT_CHANGED_AFTER_CUTOFF:'+name)
        df=pd.read_parquet(io.BytesIO(raw));times=pd.to_datetime(df.timestamp,utc=True)
        if times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing:raise ValueError('INVALID_BAR_LINEAGE:'+name)
        closed=df.loc[times+pd.Timedelta(minutes=15)<=market_at]
        if closed.empty:raise CognitiveStateUnavailable('CLOSED_OBSERVATION_UNAVAILABLE:'+name)
        frames[name]=closed.tail(1).reset_index(drop=True)
        proof[name]={'selected_rows_sha256':_frame_sha(frames[name]),'source_sha256':sha(raw),'available_at':str(available),'selected_observation':str(pd.to_datetime(closed.timestamp.iloc[-1],utc=True)),'authority':'ORIGINAL_DERIVED_BAR_INPUT_NOT_ORIGINAL_RECEIVE'}
    times=[pd.to_datetime(frames[n].timestamp.iloc[-1],utc=True) for n in BARS]
    if len(set(times))!=1:raise ValueError('UNALIGNED_PERCEPTION_BAR_INPUTS')
    return frames,{'cutoff':str(at),'observation_cutoff':str(market_at),'inputs':proof}

def _frame_sha(frame):return sha(frame.to_json(orient='split',date_format='iso',date_unit='us').encode())
def _head_hash(folder):return sha((folder/'head.json').read_bytes()) if (folder/'head.json').exists() else None

def run_cycle(root,generation,frames=None,provenance=None,*,initialize=False,hook=lambda phase:None):
    """One exclusive writer. Pending is durable; head selects all three immutable files."""
    if not generation or '/' in generation or '..' in generation:raise CognitiveStateUnavailable('EXPLICIT_COGNITIVE_GENERATION_REQUIRED')
    root=Path(root);folder=home(root);folder.mkdir(parents=True,exist_ok=True)
    with (folder/'writer.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        genesis=folder/'genesis.json';pending=folder/'pending.json'
        reservation=root/'runtime/cognitive_generation_reservation.json'
        if not genesis.exists():
            if reservation.exists():raise CognitiveStateUnavailable('LOST_GENERATION_IS_NOT_COLD_START')
            if not initialize:raise CognitiveStateUnavailable('EXPLICIT_EMPTY_GENERATION_INITIALIZATION_REQUIRED')
            if (folder/'head.json').exists() or pending.exists() or any((root/'cognition'/n).exists() for n in OUTPUTS) or list((folder/'commits').glob('*')) or any(list((root/'diagnostics/cognitive_chain'/n.removesuffix('.parquet')).glob('*.json')) for n in OUTPUTS):
                raise CognitiveStateUnavailable('PRIOR_OR_UNFINISHED_STATE_NOT_EMPTY')
            atomic(genesis,encode({'contract':CONTRACT,'generation':generation,'created_at':now(),'initial_publications':0,'authorization':'EXPLICIT_OWNER_APPROVED_EMPTY_ROOT_INITIALIZATION'}))
            atomic(reservation,encode({'generation':generation,'genesis_sha256':sha(genesis.read_bytes()),'created_at':now()}))
        if load(genesis)['generation']!=generation:raise CognitiveStateUnavailable('GENERATION_MISMATCH')
        if not reservation.exists() or load(reservation).get('genesis_sha256')!=sha(genesis.read_bytes()):raise CognitiveStateUnavailable('INCOMPLETE_GENERATION_AUTHORIZATION')
        parent_hash=_head_hash(folder);previous=None;last=None
        if parent_hash:
            base,last=verified_commit(folder,load(folder/'head.json'))
            previous={n:pd.read_parquet(base/n) for n in OUTPUTS}
        elif list((folder/'commits').glob('*')) and not pending.exists():
            raise CognitiveStateUnavailable('MISSING_HEAD_IS_NOT_COLD_START')
        if pending.exists():
            operation=load(pending);stage=folder/'commits'/operation['id']
            if operation['generation']!=generation:raise CognitiveStateUnavailable('PENDING_GENERATION_MISMATCH')
            allowed_parents={operation['parent_head_sha256']}
            if operation.get('published_head_sha256'):allowed_parents.add(operation['published_head_sha256'])
            if parent_hash not in allowed_parents:
                raise CognitiveStateUnavailable('PENDING_PARENT_CONFLICT')
            if parent_hash==operation.get('published_head_sha256') and parent_hash is not None:
                verified_commit(folder,load(folder/'head.json'));pending.unlink();sync_dir(folder)
                return {'status':'SUCCESS','mode':'RECOVERED_ALREADY_PUBLISHED','id':operation['id']}
            snapshot=load(stage/'inputs.json')
            frames={n:pd.read_parquet(stage/'inputs'/n) for n in LEGACY+BARS}
            for n,h in snapshot['hashes'].items():
                if _frame_sha(frames[n])!=h:raise CognitiveStateUnavailable('PENDING_INPUT_CORRUPT')
            provenance=snapshot['provenance'];identity=snapshot['identity'];mode='RECOVERY'
        else:
            if frames is None or provenance is None:raise CognitiveStateUnavailable('OBSERVATION_EVIDENCE_REQUIRED')
            if set(frames)!=set(LEGACY+BARS) or any(len(f)!=1 for f in frames.values()):raise ValueError('EXACT_REAL_OBSERVATION_REQUIRED')
            hashes={n:_frame_sha(f) for n,f in frames.items()}
            if set(provenance.get('inputs',{}))!=set(frames) or any(provenance['inputs'][n].get('selected_rows_sha256')!=h for n,h in hashes.items()):raise CognitiveStateUnavailable('OBSERVATION_PROVENANCE_MISMATCH')
            identity=sha(encode(hashes))
            if last and last['observation_id']==identity:return {'status':'SUCCESS','mode':'REPLAY_NO_CHANGE','id':load(folder/'head.json')['id']}
            if previous is not None and pd.to_datetime(frames['regime_history.parquet'].timestamp.iloc[-1],utc=True)<=pd.to_datetime(previous['temporal_context_memory.parquet'].timestamp.iloc[-1],utc=True):
                raise CognitiveStateUnavailable('BACKDATED_OR_CONFLICTING_OBSERVATION')
            cid=sha(encode({'observation':identity,'parent':parent_hash,'generation':generation}));stage=folder/'commits'/cid;stage.mkdir(parents=True,exist_ok=True)
            if parent_hash is not None:atomic(stage/'parent.json',(folder/'head.json').read_bytes())
            for name,frame in frames.items():
                path=stage/'inputs'/name;path.parent.mkdir(exist_ok=True);frame.to_parquet(path,index=False)
                with path.open('rb') as f:os.fsync(f.fileno())
            atomic(stage/'inputs.json',encode({'hashes':hashes,'identity':identity,'provenance':provenance,'file_sha256':{name:sha((stage/'inputs'/name).read_bytes()) for name in frames}}))
            operation={'id':cid,'generation':generation,'parent_head_sha256':parent_hash}
            atomic(pending,encode(operation));mode='COLD_START' if previous is None else 'NEXT_CYCLE'
        hook('after_prepare')
        if (stage/'manifest.json').exists():
            pointer={'id':operation['id'],'manifest_sha256':sha((stage/'manifest.json').read_bytes())}
            verified_commit(folder,pointer)
        else:
            outputs=calculate(frames,previous)
            if previous is None and len(outputs['temporal_context_memory.parquet'])!=1:raise RuntimeError('FIRST_TEMPORAL_ROW_COUNT')
            out_hashes={}
            for name,frame in outputs.items():
                path=stage/name;frame.to_parquet(path,index=False)
                with path.open('rb') as f:os.fsync(f.fileno())
                out_hashes[name]=sha(path.read_bytes())
            sources={n:sha((SOURCE/n).read_bytes()) for n in ('contextual_memory_loader_v2.py','perception_context_integration_v1.py','temporal_context_memory_v1.py')}
            manifest={'generation':generation,'contract':CONTRACT,'parent_head_sha256':operation['parent_head_sha256'],'genesis_sha256':sha(genesis.read_bytes()),'input_manifest_sha256':sha((stage/'inputs.json').read_bytes()),'observation_id':identity,'outputs':out_hashes,'provenance':provenance,'algorithms':sources,'prepared_at':now()}
            atomic(stage/'manifest.json',encode(manifest));pointer={'id':operation['id'],'manifest_sha256':sha((stage/'manifest.json').read_bytes())}
        hook('before_publish')
        # READY pointer exposes the complete set only; never replace three mutable files.
        pointer['available_at']=now();pointer['generation']=generation
        rawhead=encode(pointer);operation['published_head_sha256']=sha(rawhead);atomic(pending,encode(operation))
        atomic(folder/'head.json',rawhead);hook('after_publish')
        pending.unlink();sync_dir(folder)
        return {'status':'SUCCESS','mode':mode,'id':operation['id'],'available_at':pointer['available_at']}
