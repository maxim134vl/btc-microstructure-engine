"""One Paper-owned direct Spot source, bounded by native data/RSS quotas.
No trading decisions, automatic retry, fresh financial books or canary target.
"""
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
import os,sys,json,signal,hashlib,time
BASE=Path('/app/r08-forward');sys.path[:0]=[str(BASE)]
from r08_spot import common,storage,recorder
import canary_runner as cr
from receive_worker import ReceiveWorker
from live_processing import LiveCanary
from btc_ml.runtime.r08_service import atomic,now
from btc_ml.trend.recorder_live_adapter import RecorderLiveAdapter
from btc_ml.trend.trend_research_system import ResearchSystem
from btc_ml.trend.trend_journal import digest
from btc_ml.trend.trend_event import Trade,canonical,utc
from btc_ml.trend.trend_evidence import RawOccurrence


class ContextNotReady(RuntimeError):
    pass

def current_contexts():
    """Observer-only: genuine current-generation reference, not OPEN permission."""
    from btc_ml.external_traders.context_phase_publication import (
        HOME, _paths, _verified_generation, _new_native_target, _time,
        verify_consumer_clock, PinnedContextObservations,
    )
    root=Path('/app');cutoff=now();contexts={};refs={}
    for tf in ('M15','M30','H1','H4'):
        folder=root/HOME/tf;head_path=folder/'head.json'
        if not head_path.exists() or (folder/'pending.json').exists():
            raise ContextNotReady('R08_CONTEXT_NOT_READY:'+tf+':PHASE_PUBLICATION_PENDING')
        pointer=json.loads(head_path.read_text())
        generation=_verified_generation(root,tf,pointer);manifest=generation['manifest']
        if (manifest['market'],manifest['instrument'])!=('BINANCE_SPOT','BTCUSDT'):
            raise ContextNotReady('R08_CONTEXT_NOT_READY:'+tf+':MARKET_INSTRUMENT_BINDING')
        if (manifest['scope']!='NATIVE_RUNTIME' or manifest['source_admission']!='NATIVE_NEW_TARGET'
                or not _new_native_target(manifest['native_publication_witness'],tf,manifest['target_bar_open'],root)):
            raise ContextNotReady('R08_CONTEXT_NOT_READY:'+tf+':NATIVE_PUBLICATION_NOT_PROVEN')
        verify_consumer_clock(manifest,generation['receipt'],generation['activation'],cutoff)
        pins={rel:hashlib.sha256((root/'data'/rel).read_bytes()).hexdigest() for rel in _paths(tf)}
        packet=PinnedContextObservations(root/'data',pins,market=manifest['market'],
            instrument=manifest['instrument'],legacy_m15_owner=generation['legacy_owner']).read(
                tf,manifest['target_bar_open'],cutoff)
        if (packet['final_context_episode_id']!=manifest['canonical_context_episode_id']
                or packet['direction']!=manifest['direction']
                or _time(packet['bar_open'])!=_time(manifest['target_bar_open'])
                or _time(packet['bar_close'])!=_time(manifest['target_bar_close'])
                or {k:v['source_row_sha'] for k,v in packet['sources'].items()}!=
                   {k:v['source_row_sha'] for k,v in manifest['target_source_rows'].items()}):
            raise ContextNotReady('R08_CONTEXT_NOT_READY:'+tf+':CURRENT_CONTEXT_SOURCE_CONFLICT')
        if (folder/'pending.json').exists() or json.loads(head_path.read_text())!=pointer:
            raise ContextNotReady('R08_CONTEXT_NOT_READY:'+tf+':PHASE_PUBLICATION_CHANGED')
        if packet['direction'] not in ('LONG','SHORT'):
            raise ContextNotReady('R08_DIRECTIONAL_CONTEXT_NOT_READY:'+tf)
        contexts[tf]=dict(episode=packet['final_context_episode_id'],direction=packet['direction'],
            available_at=generation['activation']['publication_completed_at'],
            target_open=packet['bar_open'],target_close=packet['bar_close'],state={})
        refs[tf]=pointer
    return contexts,refs


def await_contexts(root,report):
    """Wait for the existing publisher before capture; re-read only changed input."""
    from btc_ml.external_traders.context_phase_publication import HOME
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    handlers={sig:signal.signal(sig,stop) for sig in (signal.SIGTERM,signal.SIGINT)}
    previous=object()
    try:
        while not stopped:
            tokens=[]
            for tf in ('M15','M30','H1','H4'):
                for name in ('head.json','pending.json'):
                    path=Path('/app')/HOME/tf/name
                    try:
                        st=path.stat();tokens.append((st.st_ino,st.st_size,st.st_mtime_ns))
                    except FileNotFoundError:tokens.append(None)
            signature=tuple(tokens)
            if signature!=previous:
                previous=signature
                try:return current_contexts()
                except ContextNotReady as exc:report('WAITING_CONTEXT',str(exc))
            time.sleep(1)
        return None
    finally:
        for sig,handler in handlers.items():signal.signal(sig,handler)


def publish_binding(root,adapter):
    config=adapter.system.j.state['config']
    descriptor={'schema':'existing_trend_sources_v1','sources':{tf:{'journal_root':str(adapter.system.j.path),'config_sha256':digest(config)} for tf in config['timeframes']}}
    path=root/'runtime/trend-descriptor.json';atomic(path,descriptor)
    env={'BTC_ML_TREND_DESCRIPTOR':str(path),'BTC_ML_TREND_DESCRIPTOR_SHA256':hashlib.sha256(path.read_bytes()).hexdigest()}
    atomic(root/'runtime/environment.json',env);return env


def restore_adapter(adapter,source,rows):
    """Native current-capture metadata only; never re-evaluate committed A/B/R."""
    from btc_ml.trend.live_direct_source import CommittedDirectSource
    path=adapter.journal_path
    if not (path/'records/00000001.json').exists():
        # No native INIT existed yet: retain the source cursor. A real gap on
        # the next message is rejected, never silently converted into a prefix.
        adapter.previous=source.last
        return False
    system=ResearchSystem(path,live_source=adapter);adapter.system=system
    config=system.j.state['config'];adapter.prepared=SimpleNamespace(config=config);adapter._prepared_config=config
    adapter.previous=None;adapter.first_T=None;adapter.cycle_delivered=True
    adapter.baseline_summary=json.loads((path/'baseline-summary.json').read_text())
    adapter.integration=None;adapter.max_r08_events=source.max_unique;system.max_raw_events=source.max_unique
    # Restore source order/bar metadata from existing receipts, not all RAW files.
    # Pending packets retain their ORIGINAL ACK/receive clocks.
    pending={x['delivery_id']:x for x in source.q};previous=None
    adapter.system=None
    for entry in source.j.records():
        out=entry['record']['record']
        if out['type']=='DELIVERY' and out['queue']['status']=='ADMITTED':
            core=out['mapping']['core'];trade=Trade(**core,receive_time=out['message_received']['wall_utc'],payload_sha=out['mapping']['core_sha256'])
            adapter._observe_trade(out,trade);adapter.first_T=adapter.first_T or utc(trade.trade_time)
            if out['delivery_id'] in pending:
                raw=RawOccurrence(trade,canonical(core),'REAL_CANDIDATE',adapter.capture_family,str(source.j.root/out['coverage_ref']),previous,None)
                ack_path=source.j.root/'receipts'/('ack-'+entry['content_sha256']+'.json');data=ack_path.read_bytes();ack=json.loads(data)
                packet=raw.packet();packet['available_at']=ack['observed_clock']['wall_utc']
                pending[out['delivery_id']]['r08_delivery']={'delivery_id':out['delivery_id'],'packet':packet,'available_by':packet['available_at'],'ack_sha256':hashlib.sha256(data).hexdigest(),'manifest_seq':entry['seq'],'manifest_sha256':entry['content_sha256'],'message_received':out['message_received'],'clock_domain':out['clock_domain'],'receive_sequence':None}
            previous=trade.native_id
        elif out['type']=='SPOT_KLINE_CLOSED':
            payload=json.loads((source.j.root/out['native_ref']).read_bytes());data=(source.j.root/'receipts'/('ack-'+entry['content_sha256']+'.json')).read_bytes();ack=json.loads(data)
            receipt={'session':source.session,'clock_domain':source.domain,'native_ref':str(source.j.root/out['native_ref']),'manifest_sha256':entry['content_sha256'],'available_at':ack['observed_clock']['wall_utc'],'ack_monotonic_ns':ack['observed_clock']['monotonic_ns'],'received':out['message_received']}
            # Validate original source-session fields, not the newly opened one.
            original_session,original_domain=source.session,source.domain
            try:
                source.session=out['session'];source.domain=out['clock_domain'];receipt['session']=source.session;receipt['clock_domain']=source.domain
                adapter.accept_kline(payload.get('data',payload),stream=out['stream'],receipt=receipt)
            finally:source.session,source.domain=original_session,original_domain
    adapter.system=system;adapter.previous=previous
    for item in list(source.q):
        if item.get('r08_delivery') is None:raise RuntimeError('R08_PENDING_DELIVERY_NOT_RESTORED')
    adapter.drain_live()
    system.resume_live_handoff(common.stamp(),source.domain)
    return True


def main():
    root=Path(os.environ['BTC_ML_R08_RUNTIME_MOUNT']);status=root/'runtime/status.json'
    j=None;r=None;c=None;a=None;error=None
    snapshot_attempted=False;pending_snapshot=None
    def persist_unprocessed_once():
        nonlocal snapshot_attempted,pending_snapshot
        if not snapshot_attempted:
            snapshot_attempted=True
            pending_snapshot=c.worker.persist_unprocessed()
        return pending_snapshot
    def report(phase,reason=None):
        value={'phase':phase,'at':now(),'owner':'paper-manager','producer_pid':os.getpid(),'reason':reason}
        if a is not None:value.update(capture_root=str(r.j.root),capture_family=a.capture_family,source_native=r.last,baseline_fixed=bool(a.system),R08_cursor=a.system.j.state['source_cursor'] if a.system else None,queue_depth=len(r.q),R08_roles={tf:t['role'] for tf,t in a.system.j.state['tf'].items()} if a.system else {})
        atomic(status,value);return value
    try:
        if not root.is_mount():raise RuntimeError('R08_EXTERNAL_BIND_REQUIRED')
        import storage.path_registry as application_paths
        print(json.dumps({'R08_IMPORTS':{'recorder_storage':storage.__file__,'application_path_registry':application_paths.__file__,'executable':sys.executable,'uid':os.getuid(),'gid':os.getgid(),'cwd':os.getcwd(),'PYTHONPATH':os.environ.get('PYTHONPATH'),'sys_path':sys.path}}),flush=True)
        cfg=json.loads((BASE/'canary_config.json').read_text())
        cr.ENDPOINT=cfg['endpoint']
        prepared_contexts=await_contexts(root,report)
        if prepared_contexts is None:
            report('STOPPED','SERVICE_STOP_BEFORE_CONTEXT');return 0
        contexts,refs=prepared_contexts
        active_path=root/'runtime/active-source.json'
        active=json.loads(active_path.read_text()) if active_path.exists() else {'capture_id':__import__('uuid').uuid4().hex,'contexts':contexts,'context_references':refs}
        capture=root/'captures'/active['capture_id'];journal=root/'research'/active['capture_id']
        cfg['source_pins']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in (BASE/'src').glob('*.py')}
        j=storage.Journal(capture,quota=cfg['quota_bytes'],max_transactions=cfg['max_transactions'],rss_budget=cfg['rss_bytes'])
        r=recorder.Recorder(j,origin=cfg['origin'],max_unique=cfg['max_unique'],queue_items=cfg['queue_items'],queue_bytes=cfg['queue_bytes'])
        if r.blocked or j.ack_missing or j.orphans:raise RuntimeError('R08_CURRENT_CAPTURE_INCOMPLETE:'+str(r.blocked or j.ack_missing or j.orphans))
        family=active.get('capture_family') or r.session;active['capture_family']=family;atomic(active_path,active)
        config={'paper_context_root':'/app','paper_capture_id':active['capture_id'],
                'paper_context_references':active['context_references']}
        observer_only=os.environ.get('BTC_ML_R08_OBSERVER_ONLY')=='1'
        if observer_only:
            # Existing REAL_CANDIDATE calculations, without PAPER authority.
            # The existing OPEN path still requires its native source permission.
            config['observer_only']=True
        else:
            permission_path=root/'runtime'/('paper-permission-'+active['capture_id']+'.json')
            if not permission_path.exists():
                atomic(permission_path,{'contract':'PAPER_OBSERVED_SCOPE_SEED_RELATIVE_V1','mode':'PAPER','real_execution_enabled':False,'complete_venue_coverage':False,'capture_family':family,'market':'BINANCE_SPOT','timeframes':['M15','M30','H1','H4'],'effective_at':now(),'evidence_level':'OBSERVED','scope':'OWNER_APPROVED_R08_OBSERVED_S0_THEN_INDEPENDENT_S1','owner_methodology':'Existing approved R08; source instantiated by authorized TASK8 startup, not a new strategy permission','context_root':str(Path('/app').resolve()),'financial_root':str(Path(os.environ['BTC_ML_FINANCIAL_ROOT']).resolve())})
            config['paper_permission']={'path':str(permission_path),'sha256':hashlib.sha256(permission_path.read_bytes()).hexdigest()}
        metrics=cr.Metrics();c=LiveCanary(j,r,cfg,metrics);c.stop_on_target_bar=False
        a=RecorderLiveAdapter(r,metrics.rows,active['contexts'],journal_path=journal,log_path=root/'runtime/source-events.jsonl',declared_at=now(),max_r08_events=cfg['max_unique'],runtime_config=config,capture_family=family);a.queue_handoff=True;c.adapter=a
        restored=restore_adapter(a,r,metrics.rows)
        if restored:publish_binding(root,a)
        bound=bool(a.system)
        def process(message,received):
            nonlocal bound
            result=c.process(message,received)
            if a.system is not None:
                s=a.system.j.state
                if any(k not in s['projection_results'] for k in s['intents']):a.system.drain()
                if not bound:
                    atomic(journal/'baseline-summary.json',a.baseline_summary)
                    publish_binding(root,a);bound=True;report('RUNNING')
            return result
        c.worker=ReceiveWorker(c,process);c.worker.start()
        def stop(*_):c.request_stop('SERVICE_STOP')
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        cr.resources=lambda label:{'label':label,'clock':common.stamp(),'rss_bytes':common.rss_bytes(),'worker':c.worker.snapshot(),'source':report('RUNNING' if bound else 'BOOTSTRAP_PREFIX')}
        report('RUNNING' if bound else 'BOOTSTRAP_PREFIX')
        import websocket
        result=c.run_network(factory=websocket.create_connection,continuous=True)
        c.worker.close();pending=persist_unprocessed_once()
        if c.worker.error:raise RuntimeError(c.worker.error)
        if result!='SERVICE_STOP':raise RuntimeError('SOURCE_STOP:'+result)
        if r.q or pending:raise RuntimeError('SOURCE_STOP_PENDING')
        r.end();report('STOPPED','SERVICE_STOP');return 0
    except BaseException as exc:
        error=type(exc).__name__+':'+str(exc)
        if c is not None:
            c.request_stop('FAILED:'+error)
            if getattr(c,'worker',None):c.worker.close();persist_unprocessed_once()
        report('BLOCKED',error);print(json.dumps({'R08_SOURCE_BLOCKED':error,'worker_traceback':getattr(getattr(c,'worker',None),'failure_traceback',None)}),flush=True);return 1
    finally:
        if j is not None:j.close()
if __name__=='__main__':raise SystemExit(main())
