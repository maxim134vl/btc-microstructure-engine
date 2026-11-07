"""Read-only delivery of owner messages. No parquet, analytical imports or fallback."""
from __future__ import annotations
import copy
import asyncio
import threading
import json
from datetime import datetime, timezone
from pathlib import Path
from ops_publication_contract import OWNERS, OPERATIONAL_ROUTES, utc, verify_message
from app.transport_config import PUBLICATION_ROOT

MAX_MESSAGE_BYTES = 8*1024*1024
MAX_CACHE_BYTES = 16*1024*1024
# UI shapes only. Unknown numeric values remain null; no fabricated zero metrics.
EMPTY = {
 "ribbon":[], "engines":[], "parquet":{"summary_level":"GREY","files":[],"all":[],"required":[],"optional":[],"archived":[],
    "stale_files":[],"delayed_files":[],"missing_files":[],"live_count":None,"stale_count":None,"delayed_count":None,
    "missing_count":None,"optional_stale_count":None,"archived_count":None},
 "collectors":{"level":"GREY","native_overall":None,"last_native_audit_at":None,"collectors":[],"required":[],"optional":[],"legacy":[]},
 "pipeline":{"active_state":"SOURCE_UNAVAILABLE","current_cycle":None},
 "health":{"level":"GREY","display_status":"SOURCE_UNAVAILABLE","memory_percent":None,"cpu_percent":None,"disk_percent":None,"reasons":[],"critical_reasons":[],"degraded_reasons":[]},
 "research_pipeline":{"pipeline":{"engines":[],"step_count":None,"expected_step_count":None,"in_sync":None},"decision_layer":{"level":"GREY","status_label":"SOURCE_UNAVAILABLE"},
    "model_governance":{"level":"GREY","governance_status":"SOURCE_UNAVAILABLE"},
    "economic_validation":{"level":"GREY","status":"SOURCE_UNAVAILABLE","win_pct":None,"neutral_pct":None,"loss_pct":None},
    "shadow_inference":{"level":"GREY","validation_status":"SOURCE_UNAVAILABLE"},
    "toxic_box":{"level":"GREY","status":"SOURCE_UNAVAILABLE"},
    "drift_monitoring":{"level":"GREY","status":"SOURCE_UNAVAILABLE"},
    "model_summary":{"level":"GREY","status":"SOURCE_UNAVAILABLE"},
    "model_assurance":None,"ribbon_extensions":[]},
 "alerts":[], "alert_groups":{"actionable":[],"informational":[],"all":[]},
 "warnings":[], "context_chain":{"process_health":"UNKNOWN","health":"SOURCE_UNAVAILABLE"},
 "multi_timeframe":[], "processes":[], "pipeline_engines":[], "datasets":[],
 "known_limitations":[], "legacy_components":[], "overall_health":"UNKNOWN",
 "overall_reason":"Owner publications unavailable; transport cannot classify system health",
 "timeframe_traders":{"activated":None,"traders":[],"portfolio":{},"manager":{},"command_bus":{}}, "paper":{"health":"SOURCE_UNAVAILABLE"},
 "live1b_paper":None, "financial_performance":None, "manager":None,"risk":None,
 "runtime_stability":None, "status_planes":{},"health_dimensions":{},
 "feed_confidence":{"overall":"GREY",**{s:{"level":"GREY","label":s,"reason":"Owner publication unavailable"} for s in ("ws","write","consume")}},"stability":{"recent_events":[]},"manifest":{},"classification":{},
 "runtime_failure_audit":{"recent":[],"active":[],"exists":None},
 "runtime_skipped_engine_audit":{"recent":[],"exists":None},
 "mtf_cognition_health":{},
 "shadow_structural_protection":{},"shadow_economic_correlation":{},
 "shadow_stp_be33":{},"shadow_auction":{},"cross_layer_outcome_reconciliation":{},
}
ROUTE_ONLY = {s for s in OWNERS if s.startswith("validation_") or s.startswith("visual_cognition_") or s=="debug_snapshot"}

class PublishedTransport:
    def __init__(self, root=PUBLICATION_ROOT, clock=None):
        self.root=Path(root); self.clock=clock or (lambda:datetime.now(timezone.utc))
        self._cache={}; self._invalid={}; self.decode_count=0

    @staticmethod
    def _signature(st):
        return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)

    def read(self, section, *, request_key=""):
        meta={"owner":OWNERS[section],"status":"SOURCE_UNAVAILABLE","generation_id":None}
        key=None; integrity_verified=False
        try:
            path=self.root/(section+".json")
            before=path.stat(); key=self._signature(before)
            invalid=self._invalid.get(section)
            if invalid is not None and invalid[0]==key:
                return None,copy.deepcopy(invalid[1])
            if before.st_size > MAX_MESSAGE_BYTES: raise ValueError("MESSAGE_TOO_LARGE")
            entry=self._cache.get(section)
            if entry is None or entry[0]!=key:
                # No following a symlink out of the publication directory.
                if path.is_symlink() or path.resolve().parent != self.root.resolve():
                    raise ValueError("PUBLICATION_PATH")
                raw=path.read_bytes()
                if len(raw)>MAX_MESSAGE_BYTES or self._signature(path.stat())!=key:
                    raise ValueError("PUBLICATION_CHANGED_DURING_READ")
                self.decode_count+=1
                message=json.loads(raw, parse_constant=lambda _:(_ for _ in ()).throw(ValueError("NON_FINITE_JSON")))
                verify_message(message,section)
                if section in OPERATIONAL_ROUTES:
                    if not isinstance(message['payload'],dict):raise ValueError('OPERATIONAL_BUNDLE_TYPE')
                    route=OPERATIONAL_ROUTES[section]
                    for target in route['replace']+route['extend']:
                        value=message['payload']
                        for token in target.split('.'):
                            if not isinstance(value,dict) or token not in value:raise ValueError('OPERATIONAL_FIELD_MISSING:'+target)
                            value=value[token]
                        if target in route['extend'] and not isinstance(value,list):raise ValueError('OPERATIONAL_LIST_REQUIRED:'+target)
                        if target in route['replace']:
                            expected=EMPTY
                            for token in target.split('.'):
                                expected=expected.get(token) if isinstance(expected,dict) else None
                            if expected is not None and type(value) is not type(expected):raise ValueError('OPERATIONAL_FIELD_TYPE:'+target)
                # Reject shape drift before it can replace the existing JSON section.
                if '.' in section:
                    parent,field=section.split('.',1); expected=EMPTY.get(parent,{}).get(field)
                else: expected=EMPTY.get(section)
                if expected is not None and type(message['payload']) is not type(expected):
                    raise ValueError("PAYLOAD_TYPE")
                if self._signature(path.stat())!=key: raise ValueError("PUBLICATION_CHANGED_DURING_READ")
                self._cache.pop(section,None)
                while self._cache and sum(v[2] for v in self._cache.values())+len(raw)>MAX_CACHE_BYTES:
                    self._cache.pop(next(iter(self._cache)))
                if len(raw)<=MAX_CACHE_BYTES:
                    self._cache[section]=(key,message,len(raw))
            else: message=entry[1]
            integrity_verified=True
            self._invalid.pop(section,None)
            meta.update({k:message[k] for k in ("generation_id","observation_at","published_at","delivery_until","source_ids")})
            now=self.clock()
            if utc(message["published_at"]) > now: raise ValueError("PUBLICATION_FROM_FUTURE")
            # Explicit owner STOPPED/error diagnostics take precedence over expired delivery.
            if message["producer_state"]!='PUBLISHED':
                meta['status']='SOURCE_'+message["producer_state"];return None,meta
            # Owner-issued delivery lease, not an API-derived market freshness score.
            if utc(message["delivery_until"]) < now:
                meta['status']='DELIVERY_EXPIRED';return None,meta
            if message.get('request_key','') != request_key: raise ValueError("REQUEST_VIEW_NOT_PUBLISHED")
            meta['status']='AVAILABLE'
            return copy.deepcopy(message['payload']),meta
        except FileNotFoundError:
            self._cache.pop(section,None)
            self._invalid.pop(section,None)
            meta['status']='SOURCE_MISSING'
        except (OSError,ValueError,TypeError,KeyError,RecursionError) as exc:
            self._cache.pop(section,None)
            meta['status']='SOURCE_INVALID';meta['error']=str(exc)
            if key is not None and not integrity_verified: self._invalid[section]=(key,copy.deepcopy(meta))
        return None,meta

    def snapshot(self):
        payload=copy.deepcopy(EMPTY); states={}
        grouped={'collectors','engines','pipeline_engines','pipeline','runtime_failure_audit',
                 'runtime_skipped_engine_audit','processes','warnings','status_planes',
                 'paper','live1b_paper','financial_performance','manager','risk','timeframe_traders'}
        for section in OWNERS:
            if section in ROUTE_ONLY or section in OPERATIONAL_ROUTES or section in grouped: continue
            value,meta=self.read(section);states[section]=meta
            if meta['status']=='AVAILABLE':
                if '.' in section:
                    parent,field=section.split('.',1);payload[parent][field]=value
                else: payload[section]=value
        # Each bundle carries one owner generation; partial writes cannot mix its fields.
        for section,route in OPERATIONAL_ROUTES.items():
            value,meta=self.read(section);states[section]=meta
            for target in route['replace']:
                states[target]={**meta,'routed_from':section}
                if meta['status']=='AVAILABLE':
                    tokens=target.split('.');routed=value;dest=payload
                    for token in tokens:routed=routed[token]
                    for token in tokens[:-1]:dest=dest[token]
                    dest[tokens[-1]]=routed
            if meta['status']!='AVAILABLE':continue
            for target in route['extend']:
                tokens=target.split('.');items=value
                for token in tokens:items=items[token]
                dest=payload
                for token in tokens[:-1]:dest=dest[token]
                dest[tokens[-1]].extend(items)
        # Technical generation binding only: do not mix positions/capital from different commits.
        ex=states.get('trading.execution',{});fin=states.get('trading.financial',{})
        if ex.get('status')=='AVAILABLE' and fin.get('status')=='AVAILABLE':
            fields=('epoch','financial_generation','financial_head_sha256','receipt_sha256')
            if any(ex.get('source_ids',{}).get(k)!=fin.get('source_ids',{}).get(k) for k in fields):
                for section in ('trading.execution','trading.financial'):
                    states[section]['status']='SOURCE_GENERATION_MISMATCH'
                    for target in OPERATIONAL_ROUTES[section]['replace']:
                        states[target]['status']='SOURCE_GENERATION_MISMATCH'
                        tokens=target.split('.');dest=payload;empty=EMPTY
                        for token in tokens[:-1]:dest=dest[token];empty=empty[token]
                        dest[tokens[-1]]=copy.deepcopy(empty[tokens[-1]])
        # Composite delivery metadata, not an aggregate claim about system health.
        for target in ('collectors','processes','warnings'):
            frames={s:states[s] for s,r in OPERATIONAL_ROUTES.items()
                    if any(t==target or t.startswith(target+'.') for t in r['extend'])}
            states[target]={'owner':'MULTI_OWNER_DELIVERY','generation_id':None,
                            'status':'FRAGMENTED_DELIVERY','sources':frames}
        # Routing aliases only, no metrics/calculation/classification.
        truth={key:payload[key] for key in ('context_chain','multi_timeframe','processes','pipeline_engines','datasets','paper','timeframe_traders','known_limitations','legacy_components','overall_health','overall_reason')}
        truth['trading_operations']={'performance':payload.pop('financial_performance'),'manager':payload.pop('manager'),'risk':payload.pop('risk')}
        payload.update(runtime_truth=truth, generated_at=None,
            schema_version='ops_snapshot_v3_live_research_historical',snapshot_mode='published_transport')
        payload['transport']={'schema_version':'ops_transport_v1','sections':states,
            'version':[(s,m['generation_id'],m['status']) for s,m in states.items()]}
        from app.services.runtime_observation import augment_snapshot
        return augment_snapshot(payload)

transport=PublishedTransport()
_snapshot_lock=threading.RLock()
def _locked_snapshot():
    with _snapshot_lock:
        return transport.snapshot()
async def build_published_snapshot():
    return await asyncio.to_thread(_locked_snapshot)
