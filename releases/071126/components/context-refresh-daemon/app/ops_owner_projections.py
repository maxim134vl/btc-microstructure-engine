"""Small owner-side projections of results already in memory. No data reads."""
from datetime import timedelta
from ops_publication_contract import make_message, utc, write_message

def publish_context_chain(root, status, *, completed_at, interval_seconds, producer_state="PUBLISHED"):
    if status.get("dry_run"):
        return None
    tips = status.get("tips_after") or {}
    # Candle tip is the old dashboard field's meaning; decision uses its true column.
    safe, final, life, decision = (tips.get(k) for k in ("candle","final","lifecycle","decision"))
    lag = (utc(safe)-utc(life)).total_seconds() if safe and life else None
    complete = all((safe, final, life, decision))
    budget = 2*max(60, int(interval_seconds))+60  # existing context-chain rule
    result = str(status.get("result") or "UNKNOWN")
    healthy = complete and result in {"REFRESH_SUCCESS", "NO_NEW_SAFE_UPSTREAM"} and (lag is None or 0 <= lag <= budget)
    reason = "last_result="+result
    if not complete: reason += "; required_artifacts_missing"
    if status.get("error"): reason += "; "+str(status["error"])
    payload = dict(process_health="RUNNING" if producer_state=="PUBLISHED" else "STOPPED", last_poll=completed_at, last_result=result,
                   safe_upstream_tip=safe, final_context_tip=final, lifecycle_tip=life,
                   decision_tip=decision, lag_seconds=lag,
                   rows_added_last_cycle=status.get("added_rows"),
                   health="HEALTHY" if healthy else "DEGRADED", health_reason=reason)
    message = make_message("context_chain", payload,
        source_ids={"cycle_id":status["cycle_id"], "artifact_sha256":status.get("hashes_after",{}),
                    "tip_snapshot":tips}, observation_at=tips.get("safe_upstream"),
        published_at=completed_at, delivery_until=(utc(completed_at)+timedelta(seconds=budget)).isoformat(),
        producer_state=producer_state)
    return write_message(root, message)

def project_multi_timeframe(latest):
    by_tf = latest.get("timeframes") or {}
    rows=[]
    for tf in ("M15","M30","H1","H4","D1"):
        row=by_tf.get(tf) or {}
        if tf == "D1":
            rows.append(dict(timeframe="D1", support="RESEARCH_ONLY_NOT_LIVE",
                availability_status=row.get("availability_status") or "TIMEFRAME_NOT_LIVE",
                availability_reason=row.get("availability_reason") or "NO_LIVE_STAGE2_WRITER",
                display_status="NOT_LIVE", requirement="EXPECTED",
                detail="No live Stage-2 writer · No D1 timeframe trader", state_asof=None,
                source_state_timestamp=None, source_bar_close=None, age_seconds=None,
                age_bars=None, is_new_event=False,
                writer_state=row.get("writer_state") or "NOT_IMPLEMENTED_LIVE",
                entity_type="UNSUPPORTED_CAPABILITY"))
        else:
            rows.append(dict(timeframe=tf, support="LIVE_SUPPORTED",
                availability_status=row.get("availability_status") or "UNKNOWN",
                availability_reason=row.get("availability_reason"), state_asof=row.get("state_asof"),
                source_state_timestamp=row.get("source_state_timestamp"),
                source_bar_close=row.get("source_bar_close"), age_seconds=row.get("age_seconds"),
                age_bars=row.get("age_bars"), is_new_event=row.get("is_new_event"),
                writer_state=row.get("writer_state"), entity_type="READ_MODEL"))
    return rows

def publish_multi_timeframe(root, latest, metadata, *, completed_at):
    # Availability is not synthesis-health. No new synthesis classification.
    # 1800s is the existing operational MTF health budget, not a trading threshold.
    message=make_message("multi_timeframe", project_multi_timeframe(latest),
        source_ids={"schema_version":latest["schema_version"],
                    "latest_sha256":metadata["latest_hash"],
                    "history_sha256":metadata["hash"],
                    "evaluation_timestamp":latest["latest_evaluation_timestamp"]},
        observation_at=latest["latest_evaluation_timestamp"], published_at=completed_at,
        delivery_until=(utc(completed_at)+timedelta(seconds=1800)).isoformat(),
        producer_state="PUBLISHED" if metadata.get("writer_state")=="RUNNING" else "STOPPED")
    return write_message(root, message)


def project_datasets(snapshot, registry):
    """The existing build_datasets DTO, using owner-calculated statuses only."""
    by_id={row.get('dataset_id'):row for row in snapshot.get('datasets') or []}
    result=[]
    for row in registry.get('datasets') or []:
        st=by_id.get(row.get('dataset_id')) or {}
        result.append(dict(dataset_id=row.get('dataset_id'),
            display_name=row.get('logical_state') or row.get('dataset_id'),
            entity_type='READ_MODEL' if row.get('semantic_type')=='READ_MODEL' else 'DATASET',
            path=row.get('dataset_path'),owner=row.get('canonical_writer'),writer=row.get('writer_entrypoint'),
            writer_state=st.get('writer_state'),rows=st.get('row_count'),schema_version=st.get('schema_hash'),
            latest_market_timestamp=st.get('source_market_timestamp'),generated_at=st.get('evaluated_timestamp'),
            age_seconds=st.get('age_seconds'),freshness_status=st.get('health'),availability_status=None,
            health=st.get('health') or 'UNKNOWN',health_reason=st.get('reason') or 'status_row_missing',
            required=bool(row.get('require_live_writer')),operational_status=row.get('operational_status'),
            status_row_present=bool(st)))
    return result


def publish_datasets(root, snapshot, *, source_sha256, completed_at):
    # No fallback registry read: external snapshots without owner projection stay unqualified.
    if 'ops_datasets' not in snapshot:
        return None
    budget=snapshot.get('ops_delivery_budget_seconds')
    if not isinstance(budget,(int,float)) or budget<=0:
        raise ValueError('OWNER_DELIVERY_BUDGET_NOT_PUBLISHED')
    message=make_message('datasets',snapshot['ops_datasets'],
        source_ids={'runtime_dataset_status_sha256':source_sha256,
                    'registry_version':snapshot.get('registry_version'),
                    'owner_evaluated_at':snapshot['generated_at']},
        observation_at=snapshot.get('market_feed_tip'),published_at=completed_at,
        delivery_until=(utc(completed_at)+timedelta(seconds=budget)).isoformat())
    return write_message(root,message)


# OPS-TRANSPORT-03: native operational observations only; no file/history readers.
import atexit
import copy
import os
import socket
import uuid
from datetime import datetime, timezone
from ops_publication_contract import COLLECTOR_OPERATIONS, digest


def _operation_message(section, payload, *, source_ids, evaluated_at, completed_at,
                       lease_seconds, producer_state='PUBLISHED'):
    """Lease is anchored to owner evaluation, never renewed by reading an old file."""
    raw_evaluation=evaluated_at
    observation=None
    try:
        observation=utc(evaluated_at).isoformat()
        deadline=utc(evaluated_at)+timedelta(seconds=float(lease_seconds))
        if utc(evaluated_at)>utc(completed_at):
            producer_state='SOURCE_CLOCK_INVALID';observation=None
        elif deadline<utc(completed_at) and producer_state=='PUBLISHED':
            producer_state='STALE_SOURCE'
    except (TypeError,ValueError):
        deadline=utc(completed_at);producer_state='AVAILABILITY_NOT_PROVEN'
    # Non-deliverable diagnostics need no invented live lease.
    delivery_until=max(deadline,utc(completed_at)).isoformat()
    return make_message(section,payload,source_ids={**source_ids,'owner_evaluated_at_raw':raw_evaluation},
                        observation_at=observation,published_at=completed_at,delivery_until=delivery_until,
                        producer_state=producer_state)


def project_collector_heartbeat(payload, *, producer_pid, namespace, emitter_script=None):
    name=payload['collector']
    entry=next((row for row in COLLECTOR_OPERATIONS.values() if row[0]==name),None)
    if entry is None:raise ValueError('COLLECTOR_NOT_REGISTERED')
    row={'name':name,'required':entry[1],'classification':'REQUIRED' if entry[1] else 'OPTIONAL',
         'status':payload['status'],'level':'GREY', # no native aggregate health/confidence in heartbeat
         'last_message':payload.get('last_timestamp') or payload['timestamp'],
         'heartbeat_timestamp':payload['timestamp'],'message_count':payload.get('message_count'),
         'last_error':payload.get('last_error'),'event':payload.get('event'),
         'age_seconds':None,'pid':producer_pid,'namespace':namespace,
         'native_heartbeat':copy.deepcopy(payload)}
    errors=[payload['last_error']] if payload.get('last_error') else []
    if name=='watchdog':
        errors.extend(str(row['block_reason']) for row in (payload.get('restart_state') or {}).values()
                      if isinstance(row,dict) and row.get('block_reason'))
    self_observed=emitter_script==entry[2]
    row['pid']=payload.get('pid') or (producer_pid if self_observed else None)
    row['emitter_pid']=producer_pid
    processes=[]
    if self_observed:
        processes=[{'process_id':'collector_watchdog' if name=='watchdog' else 'collector:'+name,
                    'display_name':name,'pid':producer_pid,'process_state':payload['status'],
                    'health':'RUNNING','namespace':namespace,'scope':'SELF_HEARTBEAT'}]
    return {'collectors':{'collectors':[row], 'required':[row] if entry[1] else [],
                          'optional':[] if entry[1] else [row], 'legacy':[]},
            'processes':processes,
            'warnings':errors}


def publish_collector_heartbeat(root, payload, *, producer_pid, namespace, completed_at, lease_seconds, emitter_script=None):
    name=payload['collector'];section='operations.collector.'+name
    if section not in COLLECTOR_OPERATIONS:return None
    frame=project_collector_heartbeat(payload,producer_pid=producer_pid,namespace=namespace,emitter_script=emitter_script)
    msg=_operation_message(section,frame,source_ids={'heartbeat_payload_sha256':digest(payload),
        'producer_pid':producer_pid,'namespace':namespace},evaluated_at=payload['timestamp'],
        completed_at=completed_at,lease_seconds=lease_seconds,
        producer_state='STOPPED' if payload['status']=='STOPPED' else 'PUBLISHED')
    path=write_message(root,msg)
    if name=='watchdog':
        overall=payload.get('overall')
        # Formatting of an already-classified enum. Missing evaluation clock cannot be upgraded.
        control={'collectors':{'level':{'HEALTHY':'GREEN','DEGRADED':'YELLOW','CRITICAL':'RED'}.get(overall,'GREY'),
                              'native_overall':overall,
                              'last_native_audit_at':payload.get('audit_evaluated_at_utc')}}
        write_message(root,_operation_message('operations.ingress_control',control,
            source_ids={'watchdog_heartbeat_payload_sha256':digest(payload),'namespace':namespace},
            evaluated_at=payload.get('audit_evaluated_at_utc'),completed_at=completed_at,lease_seconds=lease_seconds))
    return path


def project_system_control(snapshot, *, namespace):
    # PID scans are local to their observer. They are NOT global Docker availability.
    return {'status_planes':{'runtime_metadata':{
        'generated_at':snapshot.get('generated_at'),'registry_version':snapshot.get('registry_version'),
        'writers':copy.deepcopy(snapshot.get('writers',{})),
        'summary':copy.deepcopy(snapshot.get('summary',{})),
        'flags_frozen':copy.deepcopy(snapshot.get('flags_frozen',{})),
        'engine_parity':copy.deepcopy(snapshot.get('engine_parity',{})),
        'observer_namespace':namespace,'scope':'PRODUCER_PROCESS_NAMESPACE',
        'global_container_health':'NOT_PUBLISHED'}}}


def publish_system_control(root,snapshot, *, source_sha256,completed_at,namespace):
    budget=snapshot.get('ops_delivery_budget_seconds')
    if not isinstance(budget,(int,float)) or budget<=0:return None
    frame=project_system_control(snapshot,namespace=namespace)
    return write_message(root,_operation_message('operations.system',frame,
        source_ids={'runtime_dataset_status_sha256':source_sha256,'observer_namespace':namespace},
        evaluated_at=snapshot.get('generated_at'),completed_at=completed_at,lease_seconds=budget))


class CanonicalOpsPublisher:
    """Current-process native display index; never initializes from historical files."""
    def __init__(self,root,*,lease_seconds,pid,namespace,clock=None):
        self.root=root;self.lease_seconds=lease_seconds;self.pid=pid;self.namespace=namespace
        self.clock=clock or (lambda:datetime.now(timezone.utc).isoformat())
        self.session=uuid.uuid4().hex;self.cycle=None;self.sequence=0;self.closed=False
        self.rows={};self.failures={};self.skips={};self.workers={};self.warnings=[]
        self.result=None;self.phase='CYCLING';self.evaluated_at=None

    def begin(self,cycle):
        self.cycle=cycle;self.rows={};self.failures={};self.skips={};self.workers={};self.warnings=[]
        self.closed=False;self.result=None;self.phase='CYCLING';return self._save()

    def record(self,engine,status,duration,reason=None,source_timestamp=None):
        if self.closed:return None
        now=self.clock()
        self.rows[engine]={'engine':engine,'short_name':engine.removesuffix('.py'),
            'raw_status':status,'status':'HEALTHY' if status=='SUCCESS' else status,
            'last_run':source_timestamp or now,'source_timestamp':source_timestamp,'observed_at':now,
            'duration_s':duration,'reason':reason,'note':reason,
            'classification':None,'affects_health':None,'ignored_by_health':False,'mode':None}
        event={'timestamp':now,'engine':engine,'status':status,'duration_s':duration,'error':reason,
               'cycle':self.cycle,'scope':'CURRENT_NATIVE_CYCLE','source_timestamp':source_timestamp}
        if status in {'FAILED','TIMEOUT'}:self.failures[engine]=event
        if status=='SKIPPED':self.skips[engine]={'timestamp':now,'engine':engine,'status':status,'reason':reason,'scope':'CURRENT_NATIVE_CYCLE'}
        return self._save(now)

    def worker_event(self,event):
        if self.closed or event.get('cycle_id')!=self.cycle:return None
        key=event.get('engine')
        if not key or self.workers.get(key)==event:return None
        self.workers[key]=copy.deepcopy(event);return self._save(self.evaluated_at)

    def warning(self,text):
        if self.closed:return None
        self.warnings.append(text);return self._save()

    def finish(self,result):
        self.result=copy.deepcopy(result);self.phase=str(result['result']);return self._save()

    def stop(self):
        if self.closed:return None
        self.closed=True;self.phase='STOPPED';return self._save()

    def _save(self,now=None):
        completed_at=self.clock();now=now or completed_at;self.evaluated_at=now;self.sequence+=1
        failures=list(self.failures.values());skips=list(self.skips.values())
        rows=list(self.rows.values())
        def audit(events,active_statuses):
            return {'exists':True,'path':'native:current-cycle','scope':'CURRENT_NATIVE_CYCLE',
                    'total_count':None,'recent_count':None,'historical_count':None,'active_count':None,
                    'recent':events,'active':[e for e in events if self.rows.get(e['engine'],{}).get('raw_status') in active_statuses],'latest':events[-1] if events else None,
                    'native_worker_events':list(self.workers.values())}
        payload={'engines':rows,
            'pipeline_engines':[{'engine_id':r['engine'],'display_name':r['short_name'],
                                 'last_result':r['raw_status'],'health':r['raw_status']} for r in rows],
            'pipeline':{'current_cycle':self.cycle,'active_state':self.phase,
                        'last_cycle_result':self.result,'average_cycle_duration_s':None,
                        'last_cycle_duration_s':None,'uptime_seconds':None,'heartbeat_level':'GREY'},
            'runtime_failure_audit':audit(failures,{'FAILED','TIMEOUT'}),'runtime_skipped_engine_audit':audit(skips,{'SKIPPED'}),
            'warnings':copy.deepcopy(self.warnings),
            'processes':[{'process_id':'canonical_runtime','display_name':'Canonical runtime',
                'pid':self.pid,'namespace':self.namespace,'scope':'SELF_NATIVE_RUNTIME',
                'process_state':'STOPPED' if self.closed else 'RUNNING',
                'health':'STOPPED' if self.closed else 'RUNNING','session':self.session}]}
        msg=_operation_message('operations.canonical',payload,
            source_ids={'process_session':self.session,'pid':self.pid,'namespace':self.namespace,
                        'cycle_id':self.cycle,'native_event_sequence':self.sequence},
            evaluated_at=now,completed_at=completed_at,lease_seconds=self.lease_seconds,
            producer_state='STOPPED' if self.closed else 'PUBLISHED')
        return write_message(self.root,msg)


_CANONICAL_OPS=None

def begin_canonical_ops(root,cycle,lease_seconds):
    global _CANONICAL_OPS
    try:
        if _CANONICAL_OPS is None:
            _CANONICAL_OPS=CanonicalOpsPublisher(root,lease_seconds=lease_seconds,pid=os.getpid(),namespace=socket.gethostname())
            atexit.register(stop_canonical_ops)
        _CANONICAL_OPS.begin(cycle)
    except Exception as exc:print(f'OPS_PUBLICATION_WARN canonical begin: {exc}')

def record_canonical_ops(engine,status,duration,reason=None,source_timestamp=None):
    try:
        if _CANONICAL_OPS is not None:_CANONICAL_OPS.record(engine,status,duration,reason,source_timestamp)
    except Exception as exc:print(f'OPS_PUBLICATION_WARN canonical event: {exc}')

def record_worker_ops(event):
    try:
        if _CANONICAL_OPS is not None:_CANONICAL_OPS.worker_event(event)
    except Exception as exc:print(f'OPS_PUBLICATION_WARN canonical worker event: {exc}')

def record_canonical_warning(text):
    try:
        if _CANONICAL_OPS is not None:_CANONICAL_OPS.warning(text)
    except Exception as exc:print(f'OPS_PUBLICATION_WARN canonical warning: {exc}')

def finish_canonical_ops(result):
    try:
        if _CANONICAL_OPS is not None:_CANONICAL_OPS.finish(result)
    except Exception as exc:print(f'OPS_PUBLICATION_WARN canonical finish: {exc}')

def stop_canonical_ops():
    try:
        if _CANONICAL_OPS is not None:_CANONICAL_OPS.stop()
    except Exception as exc:print(f'OPS_PUBLICATION_WARN canonical stop: {exc}')


# OPS-TRANSPORT-04. Owner publication forwarding only, never an accounting engine.
from pathlib import Path
import hashlib
import json

POSITION_FIELDS = ('position_id','timeframe','side','quantity','entry_price','stop_loss_price',
 'take_profit_price','risk_amount_usd','lifecycle_episode_id','context_event_id','entry_fill_id',
 'entry_command_id','entry_decision_ts','opened_at')

def _paper_only(payload):
    if payload.get('paper_only') is not True or payload.get('real_execution_enabled') is not False:
        raise ValueError('OPS_PAPER_ONLY_SOURCE_REQUIRED')


def project_paper_owners(health, positions):
    _paper_only(health)
    rows=[]
    for tf,pos in positions.items():
        if tf not in ('M15','M30','H1','H4') or pos.get('timeframe')!=tf:
            raise ValueError('OPS_POSITION_TF_CONFLICT')
        rows.append({'timeframe':tf,'open_position_id':pos.get('position_id'),
            'direction':pos.get('side'),'status':'OPEN',
            **{k:pos.get(k) for k in ('entry_price','quantity','stop_loss_price','take_profit_price',
               'risk_amount_usd','lifecycle_episode_id','context_event_id','opened_at')},
            'native_position':copy.deepcopy(pos)})
    paper={'mode':health.get('mode'),'paper_only':health['paper_only'],
        'real_execution_enabled':health['real_execution_enabled'],
        'real_execution':health['real_execution_enabled'],'exchange_enabled':health['real_execution_enabled'],
        'manager_status':health.get('manager_status'),'context_consumer_status':health.get('context_consumer_status'),
        'execution_lanes':copy.deepcopy(health.get('execution_lanes')),'updated_at':health.get('updated_at'),
        'paper_epoch_id':health.get('paper_epoch_id'),'last_command':copy.deepcopy(health.get('last_command')),
        'last_fill':copy.deepcopy(health.get('last_fill')),'errors':copy.deepcopy(health.get('errors')),
        'blocked_commands':health.get('blocked_commands'),'duplicate_events_prevented':health.get('duplicate_events_prevented'),
        'cost_parameters':{k:health.get(k) for k in ('entry_fee_bps','exit_fee_bps','entry_slippage_bps','exit_slippage_bps')},
        'closed_positions':None,'closed_positions_status':'OWNER_VIEW_NOT_PUBLISHED'}
    # Native health/sleeve unrealized is a constant placeholder, not a priced MTM output.
    portfolio={'initial_equity_usd':health.get('initial_equity_usd'),
        'closed_equity_usd':health.get('equity_usd'),'realised_net_pnl_usd':health.get('realized_pnl_usd'),
        'unrealised_gross_pnl_usd':None,'unrealized_status':'AUTHORITATIVE_MARKED_VIEW_NOT_PUBLISHED',
        'master_initial_equity_usd':health.get('master_initial_equity_usd'),
        'master_current_equity_usd':health.get('master_current_equity_usd'),
        'master_realized_net_pnl_usd':health.get('master_realized_net_pnl_usd'),
        'capital_model':health.get('capital_model')}
    perf={'status':'PARTIAL','portfolio':copy.deepcopy(portfolio),'timeframes':copy.deepcopy(health.get('sleeves')),
          'descriptive_metrics':None,'risk_adjusted_metrics':None,'trade_journal':None,'equity_pnl_curves':None,
          'source':{'adapter':'native_financial_health_post_commit','paper_epoch_id':health.get('paper_epoch_id')},
          'field_availability':{'fees_paid':'OWNER_TOTAL_NOT_PUBLISHED','slippage_paid':'OWNER_TOTAL_NOT_PUBLISHED',
             'drawdown':'OWNER_METRIC_NOT_PUBLISHED','closed_positions':'OWNER_VIEW_NOT_PUBLISHED'}}
    return ({'paper':paper,'live1b_paper':copy.deepcopy(paper),'timeframe_traders':{'traders':rows}},
            {'financial_performance':perf,'timeframe_traders':{'portfolio':portfolio}})


def _bounded_bytes(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('OPS_SOURCE_SYMLINK')
    with path.open('rb') as f:raw=f.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('OPS_SOURCE_TOO_LARGE')
    return raw


def _native_envelope(raw,epoch):
    # Exactly the existing envelope checksum/epoch semantics; no financial computation.
    envelope=json.loads(raw);payload=envelope['payload'].encode()
    if hashlib.sha256(payload).hexdigest()!=envelope['sha256']:raise ValueError('OPS_AUTHORITY_SHA')
    value=json.loads(payload)
    if value['epoch']!=epoch:raise ValueError('OPS_AUTHORITY_EPOCH')
    return value


def write_paper_health_with_ops(engine,root,*,lease_seconds,stopped=False):
    """Existing native write once, then bounded ready JSON forwarding under its lock.

    No core class/calculation/financial protocol is changed. UI publication errors
    never alter the native return or execution outcome. No historical receipt walk.
    """
    with engine._execution_lock:
        commit=engine.books.commit;before=None
        try:before=_bounded_bytes(commit.root/'head.json')
        except Exception:pass
        path=engine.write_health()  # the original call and original error behavior
        now=datetime.now(timezone.utc).isoformat()
        try:
            if engine.last_health_write_error or commit.poisoned or commit.pending.exists():
                raise ValueError('OPS_NATIVE_PUBLICATION_UNAVAILABLE')
            raw=_bounded_bytes(path);health=json.loads(raw);epoch=engine.epoch.paper_epoch_id
            if health.get('paper_epoch_id')!=epoch or health.get('pid')!=os.getpid():
                raise ValueError('OPS_HEALTH_OWNER_IDENTITY')
            if before is None or before!=_bounded_bytes(commit.root/'head.json'):
                raise ValueError('OPS_FINANCIAL_GENERATION_CHANGED')
            head=_native_envelope(before,epoch);pub=head['publication']
            if type(pub.get('generation')) is not int or pub['generation']<1:
                raise ValueError('OPS_GENERATION_ID')
            receipt_raw=_bounded_bytes(commit.root/'publications'/f"{pub['generation']}.json")
            if hashlib.sha256(receipt_raw).hexdigest()!=head['receipt_sha256']:
                raise ValueError('OPS_RECEIPT_SHA')
            receipt=_native_envelope(receipt_raw,epoch)
            if receipt['status']!='COMMITTED' or receipt['publication']!=pub:
                raise ValueError('OPS_RECEIPT_BINDING')
            positions={tf:{k:getattr(pos,k,None) for k in POSITION_FIELDS} for tf,pos in engine.positions.items()}
            for tf,scope in pub['scopes'].items():
                if (health.get('sleeves') or {}).get(tf)!=scope['sleeve']:
                    raise ValueError('OPS_HEALTH_SCOPE_CONFLICT')
                if scope['sleeve']['open_position_id']!=(positions.get(tf) or {}).get('position_id'):
                    raise ValueError('OPS_POSITION_SCOPE_CONFLICT')
            ex,fin=project_paper_owners(health,positions)
            identity={'epoch':epoch,'health_sha256':hashlib.sha256(raw).hexdigest(),
                      'financial_head_sha256':hashlib.sha256(before).hexdigest(),'financial_generation':pub['generation'],
                      'receipt_sha256':head['receipt_sha256'],'pid':health['pid']}
            for section,body in [('trading.execution',ex),('trading.financial',fin)]:
                write_message(root,_operation_message(section,body,source_ids=identity,
                    evaluated_at=health['updated_at'],completed_at=now,lease_seconds=lease_seconds,
                    producer_state='STOPPED' if stopped else 'PUBLISHED'))
        except Exception as exc:
            # Never keep an earlier positive snapshot after a failed owner check.
            for section,body in [('trading.execution',{'paper':{},'live1b_paper':{},'timeframe_traders':{'traders':[]}}),
                                 ('trading.financial',{'financial_performance':{},'timeframe_traders':{'portfolio':{}}})]:
                try:write_message(root,_operation_message(section,body,source_ids={'reason':str(exc)},
                    evaluated_at=now,completed_at=now,lease_seconds=lease_seconds,producer_state='PUBLICATION_UNAVAILABLE'))
                except Exception:pass
            print(f'OPS_PUBLICATION_WARN paper: {exc}')
        return path


def publish_manager_cycle(root,cycle,*,risk_limits,completed_at,lease_seconds):
    """Select native command/risk outputs; never aggregate, evaluate or account."""
    snapshot=cycle['snapshot']
    if snapshot.get('paper_only') is not True or snapshot.get('execution_enabled') is not False:
        raise ValueError('OPS_MANAGER_PAPER_ONLY_REQUIRED')
    commands=snapshot.get('commands') or {}
    identity={'manager_cycle_id':cycle['manager_cycle_id'],'native_snapshot_sha256':digest(snapshot)}
    manager={'paper_only':snapshot['paper_only'],'execution_enabled':snapshot['execution_enabled'],
        'manager_cycle_id':cycle['manager_cycle_id'],'generated_at':snapshot['generated_at'],
        'evaluation_timestamp':snapshot['evaluation_timestamp'],'commands':copy.deepcopy(commands),
        'manager_writes_paper_ledger':snapshot.get('manager_writes_paper_ledger')}
    native_risk_fields=('approved_risk_usd','risk_approval_contract','risk_usd_semantics',
                        'approved_risk_pct','risk_equity_snapshot_usd','risk_paper_epoch_id','reason_codes')
    risk={'owner':'portfolio_risk','manager_cycle_id':cycle['manager_cycle_id'],
          'limits':copy.deepcopy(risk_limits),'per_timeframe':{tf:{k:row.get(k) for k in native_risk_fields} for tf,row in commands.items()},
          'risk_status':None,'paper_only':snapshot['paper_only'],'execution_enabled':snapshot['execution_enabled']}
    for section,body in [('trading.manager',{'manager':manager,'timeframe_traders':{'manager':copy.deepcopy(manager),'command_bus':copy.deepcopy(snapshot.get('command_bus') or {})}}),
                         ('trading.risk',{'risk':risk})]:
        write_message(root,_operation_message(section,body,source_ids=identity,
            evaluated_at=snapshot['generated_at'],completed_at=completed_at,lease_seconds=lease_seconds))
