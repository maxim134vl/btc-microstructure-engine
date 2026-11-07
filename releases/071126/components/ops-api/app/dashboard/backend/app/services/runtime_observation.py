"""Bounded, read-only runtime observations. No market calculations or admission decisions."""
from __future__ import annotations
import copy, http.client, json, os, re, socket, struct, threading, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode

MANIFEST = Path(os.environ.get('BTCML_RELEASE_MANIFEST', '/release/manifest.json'))
DATA = Path('/app/data')
VISUAL = Path('/app/apps/context_visualizer/public/data')
MAX_JSON = 2 * 1024 * 1024
REFRESH_S = 20.0

def now(): return datetime.now(timezone.utc)
def stamp(): return now().isoformat()
def utc(value):
    if not value: return None
    try:
        v=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return v.astimezone(timezone.utc) if v.tzinfo else None
    except (TypeError,ValueError): return None

def read_json(path, limit=MAX_JSON):
    p=Path(path)
    try:
        before=p.stat()
        if before.st_size>limit: return None, {'source':str(p),'status':'DATA_UNAVAILABLE','reason':'SIZE_BOUND','observed_at':stamp()}
        raw=p.read_bytes();after=p.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError('CHANGED_DURING_READ')
        v=json.loads(raw)
        at=next((v.get(k) for k in ('updated_at','generated_at','completed_at','available_at','at','timestamp') if isinstance(v,dict) and v.get(k)),None)
        return v,{'source':str(p),'status':'OBSERVED','observed_at':stamp(),'source_timestamp':at,'file_mtime_ns':after.st_mtime_ns}
    except (OSError,ValueError) as exc:
        return None,{'source':str(p),'status':'DATA_UNAVAILABLE','reason':str(exc),'observed_at':stamp()}

def release_manifest():
    v,m=read_json(MANIFEST)
    return v or {'version':None,'status':'DATA_UNAVAILABLE','reason':m.get('reason')}

class UnixHTTP(http.client.HTTPConnection):
    def __init__(self,path): super().__init__('localhost',timeout=2);self.path=path
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect(self.path)

class DockerReadOnly:
    """Internal GET-only client; no Docker write/exec endpoint is exposed by OPS."""
    def get(self,path,limit=MAX_JSON):
        if not (path.split('?',1)[0] in ('/containers/json','/info') or re.fullmatch(r'/containers/[a-zA-Z0-9_-]+/(top|stats|logs)',path.split('?',1)[0])): raise ValueError('READ_ROUTE_NOT_ALLOWED')
        conn=UnixHTTP(os.environ.get('BTCML_DOCKER_SOCKET','/var/run/docker.sock'))
        # This bounded presentation metadata read can exceed 2 s on Docker Desktop.
        # No market receive/ACK/guard timeout is changed.
        if path.startswith('/containers/json?'):conn.timeout=5
        try:
            conn.request('GET','/v'+os.environ.get('BTCML_DOCKER_API_VERSION','1.54')+path,headers={'Host':'api.moby.localhost','Connection':'close'});r=conn.getresponse();raw=r.read(limit+1)
            if r.status!=200: raise OSError('DOCKER_GET_'+str(r.status))
            if len(raw)>limit: raise ValueError('DOCKER_RESPONSE_BOUND')
            return raw
        finally: conn.close()
    def json(self,path): return json.loads(self.get(path))

def decode_logs(raw):
    if raw and raw[0] in (0,1,2) and raw[1:4]==b'\0\0\0':
        out=[];pos=0
        while pos+8<=len(raw):
            size=struct.unpack('>I',raw[pos+4:pos+8])[0];pos+=8
            if pos+size>len(raw):break
            out.append(raw[pos:pos+size]);pos+=size
        raw=b''.join(out)
    return raw.decode('utf-8','replace').splitlines()

def parse_processes(top):
    titles=[x.upper() for x in top.get('Titles',[])];rows=[]
    for values in top.get('Processes',[]):
        row=dict(zip(titles,values));cmd=row.get('COMMAND') or row.get('CMD') or row.get('ARGS') or ''
        rows.append({'pid':int(row['PID']) if str(row.get('PID','')).isdigit() else None,
                     'ppid':row.get('PPID'),'start_time':(now()-timedelta(seconds=int(row['ELAPSED']))).isoformat() if str(row.get('ELAPSED','')).isdigit() else row.get('STARTED') or row.get('LSTART'),
                     'command':cmd,'rss_kib':int(row['RSS']) if str(row.get('RSS','')).isdigit() else None})
    # Main application is distinct from tini/shell wrappers; children remain separately visible.
    applications=[r for r in rows if not any(x in r['command'] for x in ('/usr/bin/tini','/bin/sh /app/','nginx: worker'))]
    main=next((r for r in applications if any(x in r['command'] for x in ('run_api.py','run.py','run_intrabar_paper_manager.py','timeframe_manager_daemon.py','run_intrabar_cognition_service.py','run_context_refresh_daemon.py','nginx: master'))),applications[0] if applications else (rows[0] if rows else {}))
    descendants={str(main.get('pid'))};children=[]
    for _ in range(len(rows)):
        added=[r for r in rows if str(r.get('ppid')) in descendants and str(r.get('pid')) not in descendants]
        if not added:break
        children.extend(added);descendants.update(str(r['pid']) for r in added)
    return main,children

def cpu_cores(stats,previous):
    current=stats.get('cpu_stats',{});prior=previous or stats.get('precpu_stats',{})
    a=current.get('cpu_usage',{}).get('total_usage');b=prior.get('cpu_usage',{}).get('total_usage')
    x=current.get('system_cpu_usage');y=prior.get('system_cpu_usage');n=current.get('online_cpus')
    if None in (a,b,x,y,n) or b<=0 or a<b or x<=y:return None
    return (a-b)/(x-y)*n

def command_period(rows,service):
    row=next((r for r in rows if r.get('process_id')==service),{})
    flag='--interval-s' if service=='context-refresh-daemon' else '--interval-seconds'
    m=re.search(re.escape(flag)+r'(?:=|\s+)([0-9.]+)',row.get('command') or '')
    return float(m[1]) if m else None

class RuntimeObserver:
    def __init__(self,engine=None):
        self.engine=engine or DockerReadOnly();self.lock=threading.Lock();self.cached=None;self.sample_mono=0
        self.previous_cpu={};self.cycles={};self.log_cursor={}
    def logs(self,cid,service):
        query={'stdout':1,'stderr':1,'timestamps':1,'tail':4000 if service=='canonical-runtime' and cid not in self.log_cursor else 1 if cid not in self.log_cursor else 100}
        if cid in self.log_cursor:query['since']=int(utc(self.log_cursor[cid]).timestamp())
        self.cycles.get(service,{}).pop('observation_error',None)
        raw=self.engine.get('/containers/'+cid+'/logs?'+urlencode(query),1024*1024)
        lines=decode_logs(raw);latest=None
        for line in lines:
            at,sep,body=line.partition(' ')
            if not sep or utc(at) is None:continue
            latest=at
            state=self.cycles.setdefault(service,{'engines':{},'source':'docker logs: '+service})
            if service=='canonical-runtime':
                m=re.search(r'PIPELINE CYCLE:\s*(\d+)',body)
                if m:
                    if state.get('cycle_id')!=m[1]:state.update(cycle_id=m[1],started_at=at,finished_at=None,current_engine=None)
                m=re.search(r'RUNNING:\s*(\S+)',body)
                if m:state['current_engine']=m[1]
                engine=state.get('current_engine')
                m=re.search(r'SUCCESS \(([\d.]+)s\)',body)
                if m and engine:
                    state['engines'][engine]={'status':'SUCCESS','duration_s':float(m[1]),'timestamp':at}
                    if engine=='mtf_availability_runtime_engine_v1.py':state.update(finished_at=at,last_stage_success_at=at,overall_cycle_result='NOT_PUBLISHED_BY_OWNER')
                if engine and 'COGNITION_EXTENSION_STAGE:' in body:
                    match=re.search(r"['\"]status['\"]\s*:\s*['\"]([A-Z_]+)['\"]",body)
                    state['engines'][engine]={'status':match[1] if match else 'UNKNOWN','reason':body[:500],'timestamp':at}
                elif ('SKIPPED:' in body or 'FAILED (' in body or 'TIMEOUT (' in body) and engine:
                    state['engines'][engine]={'status':'SKIPPED' if 'SKIPPED' in body else 'FAILED','reason':body[:500],'timestamp':at}
            else:
                try:v=json.loads(body)
                except ValueError:continue
                event=v.get('event')
                if event=='CONTEXT_REFRESH_START' and v.get('message')=='cycle_begin':state.update(cycle_id=v.get('cycle_id'),started_at=v.get('timestamp') or at,finished_at=None)
                if v.get('message')=='cycle_end':
                    state.update(last_result=v.get('result'),last_duration_s=v.get('duration_s'),finished_at=v.get('timestamp') or at,last_market_tip=v.get('final_tip'))
                    if v.get('result') in ['REFRESH_SUCCESS','NO_NEW_SAFE_UPSTREAM']:state['last_success_at']=v.get('timestamp') or at
        if latest:self.log_cursor[cid]=latest
        return self.cycles.get(service,{})
    def snapshot(self):
        with self.lock:
            if self.cached is not None and time.monotonic()-self.sample_mono<REFRESH_S:return copy.deepcopy(self.cached)
            at=stamp();manifest=release_manifest();expected=manifest.get('services',[]);rows=[];errors=[]
            native={};sources={}
            files={'publisher':'live/context_refresh_daemon_status.json','manager':'runtime/timeframe_manager_health.json','manager_result':'runtime/timeframe_manager_latest.json','paper':'runtime/intrabar_paper_health.json','cognition':'runtime/intrabar_cognition_health.json','intrabar':'runtime/intrabar_supervision_state.json','availability':'runtime/multi_timeframe_availability_latest.json','datasets':'runtime/runtime_dataset_status.json','stability':'live/ops_stability.json'}
            for k,rel in files.items():native[k],sources[k]=read_json(DATA/rel)
            try:
                items=self.engine.json('/containers/json?'+urlencode({'all':1,'filters':json.dumps({'label':['com.docker.compose.project=btcml-vps-smoke']})}));items=[c for c in items if c.get('Labels',{}).get('com.docker.compose.project')=='btcml-vps-smoke']
                mapped={c['Labels'].get('com.docker.compose.service'):c for c in items}
                for service in expected:
                    c=mapped.get(service);row={'process_id':service,'display_name':service,'required':True,'observed_at':at,'source':'Docker Engine API GET','pid_scope':'Docker VM','health':None,'cpu_cores':None,'memory_bytes':None,'children':[]}
                    if not c:row.update(process_state='UNKNOWN',health_reason='CONTAINER_NOT_FOUND');rows.append(row);continue
                    cid=c['Id'];running=c.get('State')=='running';desc=c.get('Status','')
                    health='UNHEALTHY' if '(unhealthy)' in desc else 'HEALTHY' if '(healthy)' in desc else 'STARTING' if 'health: starting' in desc else 'NOT_CONFIGURED'
                    row.update(container_id=cid,container_name=(c.get('Names') or [''])[0].lstrip('/'),image_id=c.get('ImageID'),process_state=('DEGRADED' if health=='UNHEALTHY' else 'RUNNING') if running else 'STOPPED',health=health,health_reason=desc)
                    if running:
                        try:
                            main,children=parse_processes(self.engine.json('/containers/'+cid+'/top?'+urlencode({'ps_args':'-eo pid,ppid,etimes,rss,args'})))
                            row.update(pid=main.get('pid'),start_time=main.get('start_time'),command=main.get('command'),children=children)
                        except (OSError,ValueError,KeyError) as e:row['process_observation_error']=str(e)
                        try:
                            s=self.engine.json('/containers/'+cid+'/stats?stream=false&one-shot=true');row['cpu_cores']=cpu_cores(s,self.previous_cpu.get(cid));self.previous_cpu[cid]=s.get('cpu_stats')
                            m=s.get('memory_stats',{});usage=m.get('usage');inactive=m.get('stats',{}).get('inactive_file',m.get('stats',{}).get('total_inactive_file',0))
                            row['memory_bytes']=max(0,usage-inactive) if usage is not None else None;row['cpu_sample_at']=s.get('read')
                        except (OSError,ValueError,KeyError) as e:row['resource_observation_error']=str(e)
                    rows.append(row)
                for service in ['canonical-runtime','context-refresh-daemon']:
                    c=mapped.get(service)
                    if c and c.get('State')=='running':
                        try:self.logs(c['Id'],service)
                        except (OSError,ValueError) as e:
                            errors.append({'source':service,'reason':str(e),'timestamp':at});self.cycles.setdefault(service,{})['observation_error']=str(e)
            except (OSError,ValueError,KeyError) as exc:
                errors.append({'source':'Docker Engine','reason':str(exc),'timestamp':at})
                rows=[{'process_id':s,'display_name':s,'process_state':'UNKNOWN','health':None,'health_reason':str(exc),'pid':None,'required':True,'observed_at':at,'source':'Docker Engine API GET'} for s in expected]
            heartbeats=[]
            for path in sorted((DATA/'live/collector_heartbeats').glob('*.json'))[:32]:
                v,m=read_json(path)
                if isinstance(v,dict):heartbeats.append({**v,'source':str(path),'observed_at':at})
            owner_for={'paper-manager':'paper','timeframe-manager':'manager','cognition-runtime':'cognition','intrabar-supervisor':'intrabar','context-refresh-daemon':'publisher'}
            for row in rows:
                key=owner_for.get(row['process_id']);doc=native.get(key) if key else None
                row['heartbeat_at']=sources.get(key,{}).get('source_timestamp') if key else None
                if doc:
                    row['last_result']=doc.get('last_result') or doc.get('last_evaluation_timestamp') or doc.get('manager_status') or doc.get('status')
                    row['last_successful_result_at']=doc.get('last_cycle_at') or doc.get('updated_at')
            timing=[]
            for service,label,period,kind in [('canonical-runtime','Canonical',None,'COMPLETION_DELAY_5S'),('context-refresh-daemon','Publisher',command_period(rows,'context-refresh-daemon'),'MONOTONIC_GRID'),('cognition-runtime','Cognition',None,'EVENT_DRIVEN'),('timeframe-manager','Timeframe',command_period(rows,'timeframe-manager'),'POST_CYCLE_DELAY'),('context-refresher','Visual Refresher',None,'OWNER_PERIOD_NOT_PUBLISHED')]:
                state=copy.deepcopy(self.cycles.get(service,{}));entry={'service':service,'label':label,'configured_period_s':period,'schedule_kind':kind,'source':state.get('source') or sources.get(owner_for.get(service,''),{}).get('source'),'observed_at':at,'status':'UNKNOWN','reason':'CYCLE_DURATION_NOT_PUBLISHED'}
                if state:entry.update(cycle_id=state.get('cycle_id'),started_at=state.get('started_at'),last_success_at=state.get('last_success_at'),last_cycle_duration_s=state.get('last_duration_s'),last_market_tip=state.get('last_market_tip'))
                start=utc(state.get('started_at'));end=utc(state.get('finished_at'))
                if start:
                    elapsed=((end or now())-start).total_seconds()
                    if elapsed>=0:
                        entry.update(status='RUNNING' if end is None else 'WITHIN_PERIOD',current_duration_s=elapsed if end is None else None,last_cycle_duration_s=elapsed if end else entry.get('last_cycle_duration_s'))
                        if period and kind=='MONOTONIC_GRID':entry.update(overrun_s=max(0,elapsed-period),status='OVERRUN' if elapsed>period else entry['status'])
                if service=='context-refresh-daemon' and native.get('publisher'):
                    d=native['publisher'];entry.setdefault('last_cycle_duration_s',d.get('duration_s'));entry['last_market_tip']=entry.get('last_market_tip') or (d.get('tips_after') or {}).get('final')
                if service=='timeframe-manager' and native.get('manager'):
                    d=native['manager'];entry.update(last_success_at=d.get('last_cycle_at'),last_market_tip=d.get('last_evaluation_timestamp'))
                if service=='cognition-runtime':entry.update(status='RUNNING' if any(r.get('process_id')==service and r.get('process_state')=='RUNNING' for r in rows) else 'UNKNOWN',reason='PER_EVENT; NO PERIODIC CYCLE',last_success_at=sources['cognition'].get('source_timestamp'))
                if state.get('observation_error'):entry.update(status='UNKNOWN',reason='TIMING_SOURCE_UNAVAILABLE: '+state['observation_error'],current_duration_s=None)
                if service=='canonical-runtime' and state.get('finished_at'):entry['reason']='Last stage completed; overall successful cycle is not published by owner'
                timing.append(entry)
            alerts=[]
            for row in rows:
                if row.get('process_state') in ['STOPPED','DEGRADED']:
                    alerts.append({'id':'runtime-'+row['process_id'],'severity':'CRITICAL' if row['process_state']=='STOPPED' else 'WARNING','source':row['process_id'],'message':row['health_reason'],'reason':row['health_reason'],'timestamp':at,'actionable':True})
            for t in timing:
                if t['status']=='OVERRUN':alerts.append({'id':'period-'+t['service'],'severity':'WARNING','source':t['service'],'message':'CYCLE_OVERRUN','reason':'CYCLE_OVERRUN','timestamp':t.get('started_at'),'actionable':True})
            manager=native.get('manager') or {};paper_source=manager.get('paper_source') or {}
            if paper_source.get('status')=='BLOCKED':alerts.append({'id':'r08-source','severity':'WARNING','source':'timeframe_manager_health','message':paper_source.get('reason','R08_SOURCE_BLOCKED'),'reason':paper_source.get('reason'),'timestamp':manager.get('updated_at'),'actionable':True})
            states=[r.get('process_state') for r in rows];unknown=not rows or 'UNKNOWN' in states
            pipeline=self.cycles.get('canonical-runtime',{});bad=[{'engine':k,**v} for k,v in pipeline.get('engines',{}).items() if v.get('status')=='FAILED' or (v.get('status')=='SKIPPED' and 'INPUT_UNCHANGED' not in v.get('reason',''))]
            for issue in bad:
                alerts.append({'id':'canonical-'+issue['engine'],'severity':'CRITICAL' if issue['status']=='FAILED' else 'WARNING','source':'canonical-runtime/'+issue['engine'],'message':issue.get('reason') or issue['status'],'reason':issue.get('reason') or issue['status'],'timestamp':issue.get('timestamp'),'actionable':True,'type':'CURRENT_STAGE_RESULT'})
            system='UNKNOWN' if not states or all(s=='UNKNOWN' for s in states) else 'STOPPED' if 'STOPPED' in states else 'DEGRADED' if alerts or bad or unknown else 'UNKNOWN' if not pipeline.get('started_at') else 'RUNNING'
            paper_row=next((r for r in rows if r['process_id']=='paper-manager'),None)
            if paper_row and paper_row.get('process_state')=='RUNNING' and not paper_row.get('process_observation_error'):
                actual=[c for c in paper_row.get('children',[]) if 'btc_ml.runtime.r08_live_source' in c.get('command','')]
                for c in actual:c.update(role='R08 observer',process_state='RUNNING')
                if not actual:paper_row['children'].append({'role':'R08 observer','pid':None,'process_state':'STOPPED','command':'Not observed in Paper process tree'})
            # RUNNING is a process observation, never a qualification of the market model.
            resources={'scope':'installed BTC-ML containers on Docker VM; not Mac-wide RSS','cpu_cores':sum(r['cpu_cores'] for r in rows if r.get('cpu_cores') is not None) if rows and all(r.get('cpu_cores') is not None for r in rows if r.get('process_state')!='STOPPED') else None,'memory_bytes':sum(r['memory_bytes'] for r in rows if r.get('memory_bytes') is not None) if rows and all(r.get('memory_bytes') is not None for r in rows if r.get('process_state')!='STOPPED') else None,'observed_at':at,'disks':[]}
            for label,p in [('runtime Docker volume',DATA)]:
                try:s=os.statvfs(p);resources['disks'].append({'label':label,'source':str(p),'total_bytes':s.f_blocks*s.f_frsize,'free_bytes':s.f_bavail*s.f_frsize,'used_percent':100*(1-s.f_bfree/s.f_blocks),'observed_at':at})
                except OSError as e:resources['disks'].append({'label':label,'status':'UNKNOWN','reason':str(e),'observed_at':at})
            for sample in manifest.get('host_disk_observations',[]):
                resources['disks'].append({**sample,'label':sample['label']+' (host snapshot, not live)','scope':'host filesystem observation at installation; not refreshed by container'})
            resources['host_disk_status']='INSTALLATION_SNAPSHOT_ONLY: Docker Desktop bind statvfs does not prove the physical host disk'
            try:
                info=self.engine.json('/info');resources['memory_total_bytes']=info.get('MemTotal');resources['cpu_count']=info.get('NCPU')
            except (OSError,ValueError):resources['memory_total_bytes']=None;resources['cpu_count']=None
            result={'observed_at':at,'source':'read-only Docker Engine and native owner status files','services':rows,'timing':timing,'resources':resources,'system_status':system,'reason':'; '.join(dict.fromkeys([a['source']+': '+a['reason'] for a in alerts]+(['INCOMPLETE_PROCESS_OBSERVATION'] if unknown else []))) or 'Processes observed; model health is not classified here','alerts':alerts,'alerts_scope':'confirmed runtime errors only; absent research publications are separate availability metadata','collector_heartbeats':heartbeats,'sources':sources,'native':native,'canonical':pipeline,'pipeline_stage_issues':bad,'errors':errors,'release':manifest}
            self.cached=result;self.sample_mono=time.monotonic();return copy.deepcopy(result)

observer=RuntimeObserver()

def augment_snapshot(payload):
    o=observer.snapshot();payload['runtime_observation']=o;payload['generated_at']=o['observed_at']
    payload['processes']=o['services'];payload['runtime_truth']['processes']=o['services']
    payload['overall_health']=o['system_status'];payload['overall_reason']=o['reason'];payload['runtime_truth']['overall_health']=o['system_status'];payload['runtime_truth']['overall_reason']=o['reason']
    health=payload['health'];health.update(level='RED' if o['system_status']=='STOPPED' else 'YELLOW' if o['system_status']=='DEGRADED' else 'GREY' if o['system_status']=='UNKNOWN' else 'GREEN',display_status=o['system_status'],classification_scope='runtime processes/pipeline only; not trading model')
    resources=o['resources'];total=resources.get('memory_total_bytes');used=resources.get('memory_bytes');cores=resources.get('cpu_cores');n=resources.get('cpu_count')
    health['memory_percent']=100*used/total if total and used is not None else None
    health['cpu_percent']=100*cores/n if n and cores is not None else None
    health['disk_percent']=next((d.get('used_percent') for d in resources['disks'] if d.get('used_percent') is not None),None)
    payload['resource_observation']=resources
    alerts={a['id']:a for a in payload.get('alerts',[])+o['alerts']};payload['alerts']=list(alerts.values());payload['alert_groups']={'all':payload['alerts'],'actionable':[a for a in payload['alerts'] if a.get('actionable',True)],'informational':[]}
    payload['source_availability']={k:v for k,v in payload['transport']['sections'].items() if v.get('status') not in ['AVAILABLE','FRAGMENTED_DELIVERY'] and not v.get('routed_from')}
    p=o['canonical'];payload['pipeline'].update(current_cycle=int(p['cycle_id']) if str(p.get('cycle_id','')).isdigit() else None,active_state='DEGRADED' if o['pipeline_stage_issues'] else 'CYCLING' if p.get('started_at') and not p.get('finished_at') else 'IDLE' if p.get('finished_at') else 'SOURCE_UNAVAILABLE',started_at=p.get('started_at'),last_success_at=p.get('last_success_at'))
    avail=o['native'].get('availability')
    if isinstance(avail,dict):payload['multi_timeframe']=avail.get('rows',[]);payload['runtime_truth']['multi_timeframe']=payload['multi_timeframe']
    payload['runtime_truth']['pipeline_engines']=[{'engine_id':name,'display_name':name,'last_result':v.get('status'),'health':v.get('status'),'source_timestamp':v.get('timestamp')} for name,v in p.get('engines',{}).items()]
    issues=o['pipeline_stage_issues'];latest=list(p.get('engines',{}).items())
    payload['runtime_failure_audit']={'exists':bool(latest),'active':issues,'active_count':len(issues) if latest else None,'recent':issues,'historical_count':None,'source':'bounded native Docker logs; complete historical audit not loaded','generated_at':o['observed_at']}
    skipped=[{'engine':k,**v} for k,v in latest if v.get('status')=='SKIPPED']
    payload['runtime_skipped_engine_audit']={'exists':bool(latest),'recent':skipped,'source':'latest native stage observations','generated_at':o['observed_at']}
    payload['transport']['version'].append(('runtime_observation',o['observed_at'],o['system_status']))
    return payload
