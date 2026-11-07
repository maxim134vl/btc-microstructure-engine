"""Bounded function timing for the installed native publisher only."""
import sys
from pathlib import Path

# Cold-preparation boundaries only; no event/row-level instrumentation.
from contextlib import contextmanager as _prep_contextmanager
import time as _prep_clock
import json as _prep_json
import os as _prep_os
_prep_state = {'active': False}


def _prep_emit(kind, operation, **values):
    try:
        print('PUBLISHER_PREP_TIMING ' + _prep_json.dumps({
            'kind': kind, 'operation': operation, 'pid': _prep_os.getpid(),
            'monotonic_ns': _prep_clock.monotonic_ns(),
            'process_cpu_ns': _prep_clock.process_time_ns(), **values}), flush=True)
    except Exception:
        pass  # Instrumentation must not change the calculation's outcome.


def _prep_start():
    _prep_state.update(active=True, started_ns=_prep_clock.monotonic_ns(),
                       cpu_ns=_prep_clock.process_time_ns())
    _prep_emit('BEGIN', 'cold_preparation')


def _prep_finish():
    if _prep_state['active']:
        end, cpu = _prep_clock.monotonic_ns(), _prep_clock.process_time_ns()
        _prep_state['active'] = False
        _prep_emit('END', 'cold_preparation',
                   wall_s=(end-_prep_state['started_ns'])/1e9,
                   cpu_s=(cpu-_prep_state['cpu_ns'])/1e9,
                   next_operation='build_auction_episode_rows')


def _prep_files(paths):
    files = []
    for path in paths:
        try:
            path = Path(path)
            files.append({'path': str(path), 'bytes': path.stat().st_size})
        except OSError:
            files.append({'path': str(path), 'bytes': None})
    return {'input_files': files,
            'input_file_bytes_at_start': sum(f['bytes'] or 0 for f in files),
            'volume_kind': 'FILE_SIZES_NOT_PHYSICAL_IO'}


def _prep_freeze_inputs(fn, root, stage):
    g = fn.__globals__
    paths = []
    for rel, _ in {**g['SOURCES'], **g['TF_NATIVE_SOURCES']}.values():
        p = Path(stage)/rel
        paths.append(p if p.exists() else Path(root)/rel)
    paths += [Path(root)/g['RECORDED_PROOF_ROOT']/name for name in g['RECORDED_PROOF_SHA256']]
    return _prep_files(paths)


@_prep_contextmanager
def _prep_span(operation, **metadata):
    start, cpu = _prep_clock.monotonic_ns(), _prep_clock.process_time_ns()
    values = dict(metadata)
    _prep_emit('BEGIN', operation, **values)
    status = 'RETURN'
    try:
        yield values
    except BaseException:
        status = 'RAISE'
        raise
    finally:
        end, end_cpu = _prep_clock.monotonic_ns(), _prep_clock.process_time_ns()
        _prep_emit('END', operation, wall_s=(end-start)/1e9,
                   cpu_s=(end_cpu-cpu)/1e9, status=status, **values)


def _prep_arguments(fn, name, args, kwargs):
    try:
        if name == '_decoded_parquet':
            return {'raw_bytes': len(args[0]), 'source': str(kwargs.get('key')),
                    'volume_kind': 'RAW_ARGUMENT_BYTES'}
        if name == '_history_frame_sha':
            return {'rows': int(args[0].shape[0]), 'columns': int(args[0].shape[1])}
        g = fn.__globals__
        if name == 'load_sources':
            given = kwargs.get('specifications')
            specs = g['SOURCES'] if given is None else given
            folder = Path(args[0])/g['SIDECAR_ROOT']/'sources'
            paths = [folder/(key+suffix) for key in specs
                     for suffix in ('.parquet', '.meta.json', '.publication.json')]
            return {'sources': list(specs), **_prep_files(paths)}
        if name == '_own_tf_history':
            root, tf, E = Path(args[0]), args[1], g['E']
            base = E.final_path(tf).parent
            rels = [E.final_path(tf), base/'auction_episode_memory.parquet',
                    Path('data/cognition/market_context_lifecycle_memory.parquet')]
            if tf != 'M15': rels.append(base/'market_context_lifecycle_memory.parquet')
            rels.append(Path('data/live/context_decision_log.parquet'))
            if tf == 'M15':
                rels.append(Path('data/cognition/auction_episode_observations.parquet'))
                rels += [Path('data/live/m15_september_shadow_v1')/p for p in (
                    'auction.parquet', 'cognitive_market_state_memory.parquet',
                    'final_market_context_memory.parquet', 'market_context_lifecycle_memory.parquet')]
            else: rels.append(base/'auction_episode_confirmations.parquet')
            return {'timeframe': tf, **_prep_files([root/rel for rel in rels])}
    except Exception:
        return {'input_volume': 'UNAVAILABLE'}
    return {}

if Path(sys.argv[0]).name in {"run_context_refresh_daemon.py","run_causal_context_chain_candidate.py","build_auction_episode_memory.py","append_context_decision_log.py"}:
    import importlib.machinery as _m, functools as _f, time as _t, json as _j, os as _o, atexit as _a
    _start=_t.perf_counter();_cpu=_t.process_time()
    def _emit(v):
        try: print("NATIVE_STAGE_TIMING "+_j.dumps(v,default=str),flush=True)
        except (OSError,ValueError): pass
    _emit({"kind":"process_start","pid":_o.getpid(),"script":sys.argv[0],"utc_ns":_t.time_ns()})
    def _end():_emit({"kind":"process_end","pid":_o.getpid(),"script":sys.argv[0],"utc_ns":_t.time_ns(),"wall_s":_t.perf_counter()-_start,"cpu_s":_t.process_time()-_cpu})
    _a.register(_end)
    _targets={"build_auction_episode_rows","build_cognitive_market_state_rows","build_final_market_context_rows","build_lifecycle_memory","prepare_m15","prepare_higher_contexts","publish_context_phase","publish_completed","calculate_phase_history"}
    _prep_targets = {'load_sources', '_decoded_parquet', '_own_tf_history', '_history_frame_sha'} if Path(sys.argv[0]).name == 'run_causal_context_chain_candidate.py' else set()
    _targets |= _prep_targets
    def _wrapped(fn,module,name):
        @_f.wraps(fn)
        def measured(*args,**kwargs):
            if name in _prep_targets:
                if not _prep_state['active']:
                    return fn(*args,**kwargs)
                with _prep_span(module+'.'+name, **_prep_arguments(fn,name,args,kwargs)) as info:
                    result = fn(*args,**kwargs)
                    if name == '_decoded_parquet':
                        frame = result[0] if isinstance(result,tuple) else result
                        try: info.update(rows=int(frame.shape[0]), columns=int(frame.shape[1]))
                        except Exception: pass
                    return result
            if module == '_primary_context_native_auction' and name == 'build_auction_episode_rows':
                _prep_finish()  # Stop before the first classifier call, never trace its rows.
            start=_t.perf_counter();cpu=_t.process_time();at=_t.time_ns();status="RETURN"
            try:return fn(*args,**kwargs)
            except BaseException:
                status="RAISE";raise
            finally:_emit({"kind":"function","pid":_o.getpid(),"module":module,"function":name,"start_utc_ns":at,"end_utc_ns":_t.time_ns(),"wall_s":_t.perf_counter()-start,"cpu_s":_t.process_time()-cpu,"status":status,"tf":kwargs.get("timeframe",next((x for x in args if isinstance(x,str) and x in ("M15","M30","H1","H4")),None))})
        measured.__btcml_timing__=True
        return measured
    _original=_m.SourceFileLoader.exec_module
    def _exec(loader,module):
        _original(loader,module)
        if not (str(getattr(module,"__file__","")).startswith("/app/") or "/.primary-context-stage-" in str(getattr(module,"__file__",""))):return
        for name in _targets:
            fn=vars(module).get(name)
            if callable(fn) and getattr(fn,"__module__",None)==module.__name__ and not getattr(fn,"__btcml_timing__",False):setattr(module,name,_wrapped(fn,module.__name__,name))
    _m.SourceFileLoader.exec_module=_exec
