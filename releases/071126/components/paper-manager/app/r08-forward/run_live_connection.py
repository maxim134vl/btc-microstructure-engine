"""One ordinary forward cycle with the existing recorder and network loop."""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,time,hashlib,uuid,shutil
O=Path(__file__).resolve().parent
sys.path[:0]=[str(O/'src'),str(O/'candidate/src')]
import common,storage,recorder,canary_runner as cr
from btc_ml.trend.recorder_live_adapter import RecorderLiveAdapter
from live_processing import LiveCanary
from receive_worker import ReceiveWorker

def session_exit_code(reason, pending_queue, worker_error, final_error):
    # Existing success conditions, shared with the isolated launcher check.
    return 0 if reason=='FULL_M15_PROCESSED' and not pending_queue and worker_error is None and final_error is None else 1

def main():
    if not Path('/Volumes/MaksTiger').is_mount():raise RuntimeError('MAKSTIGER_REQUIRED')
    assert not (O/'evidence/LIVE_RESULT.json').exists(),'ONE_LIVE_RUN_ONLY'
    # Administrative start selection, not market-data timestamp correction.
    schedule=json.loads((O/'evidence/LIVE_PLAN.json').read_text())
    planned=datetime.fromisoformat(schedule['planned_launch_UTC'])
    while datetime.now(timezone.utc)<planned:
        remaining=(planned-datetime.now(timezone.utc)).total_seconds()
        time.sleep(min(30,remaining))
    if datetime.now(timezone.utc)>=datetime.fromisoformat(schedule['target_M15_open_UTC']):
        raise RuntimeError('TARGET_OPEN_ALREADY_PASSED_NO_ATTEMPT')
    if not Path('/Volumes/MaksTiger').is_mount():raise RuntimeError('MAKSTIGER_REQUIRED')
    if shutil.disk_usage(O).free<schedule['budgets']['capture_bytes']:raise RuntimeError('INSUFFICIENT_EXTERNAL_DISK')
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--capture-name',choices=['live-one','live-ack-clock-fix'],default='live-one');args=parser.parse_args()
    cfg=json.loads((O/'canary_config.json').read_text());cr.ENDPOINT=cfg['endpoint'];contexts=json.loads((O/'CONTEXT_INPUTS.json').read_text())['timeframes']
    j=storage.Journal(O/'captures'/args.capture_name,quota=cfg['quota_bytes'],max_transactions=cfg['max_transactions'],rss_budget=cfg['rss_bytes'])
    if 'one-authorized-attempt' in j.keys:j.close();raise RuntimeError('ONE_ATTEMPT_ALREADY_RESERVED')
    m=cr.Metrics();r=recorder.Recorder(j,origin=cfg['origin'],max_unique=cfg['max_unique'],queue_items=cfg['queue_items'],queue_bytes=cfg['queue_bytes'])
    # Ordinary status only; do not run the historical qualification resource probes.
    cr.resources=lambda label:dict(label=label,clock=common.stamp(),rss_bytes=common.rss_bytes())
    c=LiveCanary(j,r,cfg,m)
    plan=json.loads((O/'evidence/LIVE_PLAN.json').read_text());c.target_open=int(datetime.fromisoformat(plan['target_M15_open_UTC']).timestamp());c.target_close=int(datetime.fromisoformat(plan['target_M15_close_UTC']).timestamp())
    def done():
        # S0 is recorded by the adapter, independently of the technical target.
        pass
    declared=datetime.now(timezone.utc).isoformat()
    a=RecorderLiveAdapter(r,m.rows,contexts,journal_path=O/'candidate/live_journal',
        log_path=O/'live-events.jsonl',declared_at=declared,on_cycle=None,max_r08_events=cfg['max_unique']);c.adapter=a;a.on_s0=done;a.queue_handoff=True
    j.commit('one-authorized-attempt',dict(type='ONE_AUTHORIZED_CANARY_ATTEMPT',
        configuration_sha256=common.sha((O/'canary_config.json').read_bytes()),clock=common.stamp(),no_second_attempt=True))
    c.worker=ReceiveWorker(c,c.process);c.worker.start()
    cr.resources=lambda label:dict(label=label,clock=common.stamp(),rss_bytes=common.rss_bytes(),worker=c.worker.snapshot())
    t0=time.monotonic()
    import websocket
    reason=c.run_network(factory=websocket.create_connection)
    c.worker.close()
    if c.worker.error:reason='FAILED:'+c.worker.error
    final_error=None;unprocessed=None
    try:
        unprocessed=c.worker.persist_unprocessed()
        if not r.blocked:
            # Deferred trades stay in the original durable queue for recovery.
            r.end()
        j.commit('canary-session-ended',dict(type='CANARY_SESSION_ENDED',reason=reason,clock=common.stamp(),
            actual_attempt_start=c.attempt_start,accepting_stopped=c.accepting_stopped,socket_closed=c.socket_closed,
            first_callback=c.first_message,last_callback=c.last_message,received_application_messages=c.received,
            pending_queue=len(r.q),network_session_count=1 if c.transport else 0,worker=c.worker.snapshot(),unprocessed_receive=unprocessed),emergency=True)
    except BaseException as e:final_error=type(e).__name__+':'+str(e)
    result=dict(reason=reason,wall_seconds=time.monotonic()-t0,received_messages=getattr(c,'input_received_count',c.received),processed_messages=c.received,
        delivered_to_adapter=a.delivered,cycle_delivered=a.cycle_delivered,baseline=a.baseline_summary,
        R08_events=len(a.system.j.state['raw']) if a.system else 0,
        live_handoff=dict(a.system.j.state['live_handoff']) if a.system and a.system.j.state.get('live_handoff') else None,entry_decisions=a.last_decisions,S0=a.s0_result,
        quota_bytes=j.quota,quota_used_bytes=j.used,limits=cfg,
        adapter_first_T=a.first_T.isoformat() if a.first_T else None,
        last_committed_native=next((row.get('native_id') for row in reversed(m.rows) if row.get('publication') and row.get('queue',{}).get('status')=='ADMITTED'),None),
        first_committed_event=next((dict(native_id=row.get('native_id'),T=row.get('T')) for row in m.rows if row.get('publication')),None),
        last_committed_event=next((dict(native_id=row.get('native_id'),T=row.get('T')) for row in reversed(m.rows) if row.get('publication')),None),
        last_R08_snapshot={tf:dict(role=t['role'],blocked=t['blocked'],last_look={k:v for k,v in t['looks'][-1].items() if k!='sources'} if t['looks'] else None,last_look_sources=len(t['looks'][-1].get('sources',[])) if t['looks'] else 0) for tf,t in a.system.j.state['tf'].items()} if a.system else None,
        committed_RAW_deliveries=sum(bool(row.get('publication')) for row in m.rows),
        committed_admitted_deliveries=sum(bool(row.get('publication')) and row.get('queue',{}).get('status')=='ADMITTED' for row in m.rows),
        transport=c.transport,first_callback=c.first_message,last_callback=c.last_message,
        capture_root=str(j.root),native_journal=str(a.journal_path) if a.system else None,
        finalization_error=final_error,REAL_execution=False,permission_created=False,
        rss_peak_bytes=common.rss_bytes(),bar_boundaries=a.boundaries,bar_waiting=a.waiting,
        pending_queue=[dict(delivery_id=x.get('delivery_id'),native_id=x.get('native_id'),state=x.get('_dispatch_state','ADMITTED'),sequence=x.get('_dispatch_sequence')) for x in r.q],
        worker=c.worker.snapshot(),unprocessed_receive=unprocessed,resource_observations=m.resources,
        receive_to_complete_ns=c.worker.latencies,callback_enqueue_ns=c.worker.callback_ns,
        kline_messages=sum(row.get('type')=='kline' for row in m.rows),
        closed_klines=sum(row.get('status')=='KLINE_CLOSE_COMMITTED' for row in m.rows),
        bar_coverage={tf:{str(opened):b for opened,b in states.items()} for tf,states in a.bars.items()})
    j.close();(O/'evidence/LIVE_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return session_exit_code(reason,r.q,c.worker.error,final_error)
if __name__=='__main__':raise SystemExit(main())
