"""Offline-qualified passive message recorder. NO economic predicates or R2."""
from collections import deque
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json, uuid, threading, base64
from .common import *
from .storage import Journal
FIELDS=('a','f','l','p','q','m','T','E')
MAPPING_VERSION='SPOT_AGGTRADE_TO_DRA_CORE_V1'
MAPPING_SHA=sha(Path(__file__).read_bytes())
def parse_message(raw):
    def pairs(xs):
        d={}
        for k,v in xs:
            if k in d:raise ValueError('DUPLICATE_JSON_KEY')
            d[k]=v
        return d
    def reject_const(v):raise ValueError('NONFINITE_JSON')
    obj=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=reject_const)
    if not isinstance(obj,dict):raise ValueError('OBJECT_REQUIRED')
    payload=obj.get('data',obj)
    if not isinstance(payload,dict):raise ValueError('DATA_OBJECT_REQUIRED')
    if 'stream' in obj and obj['stream']!='btcusdt@aggTrade':raise ValueError('STREAM_DOMAIN')
    return obj,payload

def mapping(payload,received):
    result={'mapping_version':MAPPING_VERSION,'mapping_sha256':MAPPING_SHA,'fields':{k:{'present':k in payload,'value':payload.get(k)} for k in FIELDS},'parsed_object_sha256':digest(payload),'normalization_ingest':received,'core':None,'core_sha256':None,'status':'REJECTED','reason':None}
    try:
        if payload.get('e')!='aggTrade' or payload.get('s')!='BTCUSDT':raise ValueError('SOURCE_DOMAIN')
        if any(k not in payload or payload[k] is None for k in FIELDS):raise ValueError('MISSING_OR_NULL_NATIVE_FIELD')
        for k in ('a','f','l','T','E'):
            if type(payload[k]) is not int or not 0<=payload[k]<=2**63-1:raise ValueError('NATIVE_INTEGER_REQUIRED')
        if payload['f']>payload['l'] or not 0<payload['T']<=payload['E']:raise ValueError('NATIVE_RANGE_OR_CLOCK')
        if type(payload['m']) is not bool:raise ValueError('LITERAL_MAKER_BOOL_REQUIRED')
        for k in ('p','q'):
            if not isinstance(payload[k],str) or len(payload[k])>128:raise ValueError('DECIMAL_LEXEME_REQUIRED')
            d=Decimal(payload[k])
            if not d.is_finite() or d<=0:raise ValueError('POSITIVE_FINITE_DECIMAL_REQUIRED')
        core={'market':MARKET,'symbol':'BTCUSDT','stream':'AGG_TRADE','native_id':payload['a'],'trade_time':ms(payload['T']),'exchange_event_time':ms(payload['E']),'price':payload['p'],'quantity':payload['q'],'buyer_is_maker':payload['m']}
        utc(received['wall_utc'])  # Preserve independent validation of local UTC.
        # T <= E is checked above in Binance's clock domain. The local receive
        # clock is independent; retain it verbatim without asserting E <= receive.
        result.update(core=core,core_sha256=digest(core),status='ACCEPTED',signed_base_quantity=str(-Decimal(payload['q']) if payload['m'] else Decimal(payload['q'])),aggression_semantics='PROJECT_MAPPING_ONLY / VENUE_UNQUALIFIED')
    except (ValueError,InvalidOperation,OverflowError):result['reason']=str(__import__('sys').exc_info()[1])
    return result
class Recorder:
    def __init__(self,journal,*,clock=stamp,queue_items=1024,queue_bytes=8*1024*1024,max_unique=4096,origin='OFFLINE_SYNTHETIC'):
        if not 1<=queue_items<=1024 or not 1<=queue_bytes<=8*1024*1024 or not 1<=max_unique<=32768:raise ValueError('TECHNICAL_CAP')
        if origin not in ('OFFLINE_SYNTHETIC','LIVE_CAPTURE_RESEARCH_RECORDER'):raise ValueError('CAPTURE_ORIGIN')
        self.j=journal;self.clock=clock;self.items=queue_items;self.bytes=queue_bytes;self.max_unique=max_unique;self.origin=origin
        self.q=deque();self.qbytes=0;self.seen={};self.delivery=0;self.last=None;self.previous_T=None;self.lock=threading.RLock();self.dispatch_condition=threading.Condition(threading.RLock());self._dispatch_current=None;self.blocked=None;self.context_seen={};self.domain=domain()
        self.domain['clock_origin']='LOCAL_OS_SAMPLE' if clock is stamp else 'OFFLINE_INJECTED_CLOCK'
        self._restore();self.session=str(uuid.uuid4());self.generation=self.sessions
        if 'capture-scope' not in self.j.keys:
            self._commit('capture-scope',{'type':'CAPTURE_SCOPE','origin':origin,'capture_id':journal.root.name,'volume_uuid':VOLUME_UUID,'producer_sha256':{p.name:sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')},'queue_items':queue_items,'queue_bytes':queue_bytes,'max_unique':max_unique,'storage_quota':journal.quota,'max_transactions':journal.max_transactions,'coverage':'COVERAGE_SEMANTICS_UNQUALIFIED','original_history':'UNKNOWN','network_activation':'DISABLED_BY_RESEARCH_ENTRYPOINT'}, {'scope/capture.json':canonical({'version':VERSION,'origin':origin,'source':'BINANCE_SPOT/BTCUSDT/AGG_TRADE','clock_domain':self.domain})})
        self._commit('session:'+self.session,{'type':'SESSION_STARTED','session':self.session,'reconnect_generation':self.generation,'clock_domain':self.domain,'origin':origin,'coverage':'COVERAGE_SEMANTICS_UNQUALIFIED','source_scope':{'venue':'BINANCE','market':'SPOT','symbol':'BTCUSDT','stream':'AGG_TRADE'},'prior_history':'UNKNOWN','source_boundary':'OBSERVATION_START_ONLY','resume':'INCOMPLETE_RESTART_BOUNDARY' if self.sessions else 'INITIAL_BOUNDARY','previous_pending':list(self.q),'ack_missing':self.j.ack_missing})
    def _restore(self):
        pending={};self.sessions=0;self.duplicate_count=0;self.conflict_count=0;self.drop_count=0
        for entry in self.j.records():
            r=entry['record']['record'];typ=r['type']
            if typ=='CAPTURE_SCOPE':
                if r.get('producer_sha256')!={p.name:sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')}:raise Corrupt('PRODUCER_VERSION_RESTART_CONFLICT')
                if (r['origin'],r['queue_items'],r['queue_bytes'],r['max_unique'],r['storage_quota'],r['max_transactions'])!=(self.origin,self.items,self.bytes,self.max_unique,self.j.quota,self.j.max_transactions):raise Corrupt('CAPTURE_SCOPE_RESTART_CONFLICT')
            elif typ=='SESSION_STARTED':self.sessions+=1
            elif typ=='DELIVERY':
                self.delivery=max(self.delivery,r['delivery_sequence'])
                reason=r['queue'].get('reason')
                if reason=='DUPLICATE_NATIVE_NO_NEW_MEMBER':self.duplicate_count+=1
                elif reason=='CONFLICTING_NATIVE_IDENTITY':self.conflict_count+=1
                elif reason=='QUEUE_CAPACITY_REJECTED':self.drop_count+=1
                if r['queue']['status']=='ADMITTED':
                    p=r['mapping'];a=p['core']['native_id'];self.seen[a]={'parsed_sha':p['parsed_object_sha256'],'core_sha':p['core_sha256'],'f':p['fields']['f']['value'],'l':p['fields']['l']['value']};self.last=a;self.previous_T=p['core']['trade_time']
                    pending[r['delivery_id']]={'delivery_id':r['delivery_id'],'native_id':a,'estimated_bytes':r['message_bytes'],'normalized_ref':r['normalized_ref']}
            elif typ=='QUEUE_DEQUEUED':pending.pop(r['delivery_id'],None)
            elif typ=='CAPTURE_BLOCKED':self.blocked=r['reason']
            elif typ=='CONTEXT_OBSERVED' and r.get('row_sha256') and r.get('qualification')=='COHERENT_OBSERVATION_ONLY':
                self.context_seen.setdefault((r['timeframe'],r['row_sha256']),r['first_observed'])
        if len(self.seen)>self.max_unique or len(pending)>self.items:raise Corrupt('RESTORE_CAP')
        self.q=deque(pending.values());self.qbytes=sum(x['estimated_bytes'] for x in self.q)
        if self.qbytes>self.bytes:raise Corrupt('RESTORE_QUEUE_BYTES_CAP')
    def offer_received(self,message,received,sequence,queued_clock,*,service=None):
        # The original bounded deque now holds pre-ACK input and admitted work.
        if not isinstance(message,(str,bytes)):raise ValueError('APPLICATION_TEXT_OR_BYTES_REQUIRED')
        size=len(message.encode('utf-8',errors='surrogatepass')) if isinstance(message,str) else len(message)
        if size>65536 and service is None:raise Capacity('MESSAGE_SIZE_CAP')
        item={'_dispatch_state':'RECEIVE_PENDING','_dispatch_message':message,
              '_dispatch_received':dict(received),'_dispatch_sequence':sequence,
              '_dispatch_queued_clock':dict(queued_clock),'estimated_bytes':size}
        if service is not None:item['_dispatch_service']=service
        with self.dispatch_condition:
            if len(self.q)>=self.items or self.qbytes+size>self.bytes:
                return None,item
            self.q.append(item);self.qbytes+=size;self.dispatch_condition.notify()
        return item,None
    def finish_received(self,item):
        # Only non-agg input / durably rejected or duplicate delivery is removed
        # here. Admitted aggTrade leaves through the existing durable dequeue.
        with self.dispatch_condition:
            if 'delivery_id' not in item:
                for n,pending in enumerate(self.q):
                    if pending is item:
                        del self.q[n];self.qbytes-=item['estimated_bytes'];break
            self.dispatch_condition.notify_all()
    def durable_depth(self):
        with self.dispatch_condition:
            return sum('delivery_id' in item for item in self.q)
    def durable_bytes(self):
        with self.dispatch_condition:
            return sum(item['estimated_bytes'] for item in self.q if 'delivery_id' in item)
    def _commit(self,key,record,blobs=None,fault=None):
        try:return self.j.commit(key,record,blobs,fault=fault)
        except (OSError,Blocked) as e:
            self.blocked=str(e)
            try:self.j.commit('block:'+str(uuid.uuid4()),{'type':'CAPTURE_BLOCKED','reason':str(e),'state':'INCOMPLETE','clock':self.clock(),'missing_durable_receipt_possible':True},emergency=True)
            except (OSError,Blocked):pass
            raise
    def receive(self,message,*,fault=None):
        received=self.clock() # FIRST callback instruction, before representation conversion/JSON.
        return self._receive(message,received,fault=fault)
    def application_callback(self,ws,message):
        received=self.clock() # FIRST instruction in transport callback; not kernel arrival.
        result=self._receive(message,received)
        if result['queue']['status']=='ADMITTED':self.dequeue()
        return result
    def transport_observation(self,record):
        return self._commit('transport:'+str(uuid.uuid4()),{'type':'TRANSPORT_SESSION_OBSERVATION','origin':self.origin,'session':self.session,'clock':self.clock(),**record,'real_source_qualification':'NOT_PROVEN'})
    def _receive(self,message,received,*,fault=None):
        with self.lock:
            reserved=self._dispatch_current
            if self.blocked:raise Blocked('CAPTURE_ALREADY_BLOCKED:'+self.blocked)
            if isinstance(message,str):raw=message.encode('utf-8',errors='surrogatepass');representation='TEXT_UTF8_SURROGATEPASS'
            elif isinstance(message,bytes):raw=message;representation='BYTES'
            else:raise ValueError('APPLICATION_TEXT_OR_BYTES_REQUIRED')
            self.delivery+=1;did=self.session+':'+str(self.delivery);tag=str(uuid.uuid4())
            native_ref='native/'+tag+'.bin';norm_ref='normalized/'+tag+'.json'
            r={'type':'DELIVERY','origin':self.origin,'delivery_id':did,'delivery_sequence':self.delivery,'session':self.session,'reconnect_generation':self.generation,'clock_domain':self.domain,'message_received':received,'message_representation':representation,'message_bytes':len(raw),'native_ref':native_ref,'native_message_sha256':sha(raw),'kernel_receive':None,'parse':{'status':'REJECTED'},'mapping':None,'normalized_ref':None,'queue':{'status':'REJECTED','reason':'PARSE_REJECTED'},'coverage':{'state':'COVERAGE_SEMANTICS_UNQUALIFIED','complete_venue_coverage':False}}
            try:
                if len(raw)>65536:raise ValueError('MESSAGE_SIZE_CAP')
                envelope,payload=parse_message(raw);r['parse']={'status':'ACCEPTED','clock':self.clock(),'envelope_sha256':digest(envelope)}
                normalization_start=self.clock()
                r['mapping']=mapping(payload,received)
                r['mapping']['normalization_start']=normalization_start
                r['mapping']['normalization_ingest']=self.clock()
                r['queue']['reason']='NORMALIZATION_REJECTED'
                if r['mapping']['status']=='ACCEPTED':
                    a=payload['a'];old=self.seen.get(a)
                    if old:
                        reason='DUPLICATE_NATIVE_NO_NEW_MEMBER' if old['parsed_sha']==r['mapping']['parsed_object_sha256'] else 'CONFLICTING_NATIVE_IDENTITY'
                        r['queue']['reason']=reason;r['coverage']['identity_outcome']=reason
                        if reason.startswith('CONFLICT'):r['coverage']['state']='SOURCE_IDENTITY_CONFLICT'
                    elif len(self.seen)>=self.max_unique:r['queue']['reason']='UNIQUE_EVENT_CAP_INCOMPLETE'
                    elif reserved is None and (len(self.q)>=self.items or self.qbytes+len(raw)>self.bytes):r['queue']['reason']='QUEUE_CAPACITY_REJECTED'
                    else:
                        item={'delivery_id':did,'native_id':a,'estimated_bytes':len(raw),'normalized_ref':norm_ref}
                        with self.dispatch_condition:
                            if reserved is None:self.q.append(item);self.qbytes+=len(raw)
                            else:
                                if not any(v is reserved for v in self.q):raise Corrupt('DISPATCH_RESERVATION_MISSING')
                                reserved.update(item)
                            r['queue']={'status':'ADMITTED','clock':self.clock(),'depth_after':self.durable_depth(),'bytes_after':self.durable_bytes()}
                        if self.last is not None and a!=self.last+1:r['coverage']['observed_id_discontinuity']={'previous':self.last,'observed':a,'venue_gap_proven':False}
                        if self.previous_T and utc(r['mapping']['core']['trade_time'])<utc(self.previous_T):r['coverage']['exchange_time_rewind']=True
                        self.seen[a]={'parsed_sha':r['mapping']['parsed_object_sha256'],'core_sha':r['mapping']['core_sha256'],'f':payload['f'],'l':payload['l']};self.last=a;self.previous_T=r['mapping']['core']['trade_time']
            except (ValueError,UnicodeError) as e:r['parse']={'status':'REJECTED','reason':str(e),'clock':self.clock()}
            if r['queue']['status']=='REJECTED':r['queue']['clock']=self.clock()
            blobs={native_ref:raw}
            if r['mapping'] is not None:r['normalized_ref']=norm_ref;blobs[norm_ref]=canonical(r['mapping'])
            reason=r['queue'].get('reason')
            if reason=='DUPLICATE_NATIVE_NO_NEW_MEMBER':self.duplicate_count+=1
            elif reason=='CONFLICTING_NATIVE_IDENTITY':self.conflict_count+=1
            elif reason=='QUEUE_CAPACITY_REJECTED':self.drop_count+=1
            r['coverage']['native_fields']={k:r['mapping']['fields'][k] for k in ('a','f','l')} if r['mapping'] else None
            r['coverage']['delivery_id']=did
            r['coverage_ref']='coverage/'+tag+'.json'
            blobs[r['coverage_ref']]=canonical(seal({'type':'SOURCE_COVERAGE_OBSERVATION','native_message_sha256':r['native_message_sha256'],**r['coverage']}))
            for kind,body in [('MESSAGE_RECEIVED',{'clock':received,'native_message_sha256':r['native_message_sha256'],'representation':representation}),('PARSE_OUTCOME',r['parse']),('NORMALIZATION_OUTCOME',{'status':r['mapping']['status'],'reason':r['mapping'].get('reason'),'core_sha256':r['mapping']['core_sha256'],'clock':r['mapping']['normalization_ingest']} if r['mapping'] else {'status':'NOT_ATTEMPTED'}),('QUEUE_APPEND_OUTCOME',r['queue'])]:
                r.setdefault('technical_receipts',{})[kind]=seal({'type':kind,'delivery_id':did,'origin':self.origin,'native_message_sha256':r['native_message_sha256'],**body})
            r['technical_receipts_encoding']='INLINE_SEALED_V1'
            r['native_persistence']='NATIVE_EVENT_PERSISTED_WHEN_REFERENCED_MANIFEST_COMMITS';r['normalization_result']=r['mapping']['status'] if r['mapping'] else 'NOT_ATTEMPTED'
            result=self._commit('delivery:'+did,r,blobs,fault)
            if reserved is not None and r['queue']['status']=='ADMITTED':
                with self.dispatch_condition:
                    reserved['_dispatch_state']='ADMITTED'
                    reserved.pop('_dispatch_message',None)
            if r['queue'].get('reason')=='UNIQUE_EVENT_CAP_INCOMPLETE':self.blocked='UNIQUE_EVENT_CAP_INCOMPLETE';self._commit('unique-cap:'+did,{'type':'CAPTURE_BLOCKED','reason':self.blocked,'state':'INCOMPLETE'})
            return {**r,'publication':result}
    def dequeue(self,*,fault=None):
        with self.lock:
            if self.blocked:raise Blocked('CAPTURE_ALREADY_BLOCKED:'+self.blocked)
            if not self.q:return None
            with self.dispatch_condition:
                item=self.q[0]
                if 'delivery_id' not in item:return None
                item=self.q.popleft();self.qbytes-=item['estimated_bytes'];clock=self.clock()
                public={k:v for k,v in item.items() if not k.startswith('_dispatch_')}
                depth=self.durable_depth()
            self._commit('dequeue:'+item['delivery_id'],{'type':'QUEUE_DEQUEUED',**public,'clock':clock,'depth_after':depth},fault=fault)
            if getattr(self,'on_dequeued',None):self.on_dequeued(item)
            return item
    def reconnect(self,reason):
        with self.lock:
            old=self.session;self.session=str(uuid.uuid4());self.generation+=1
            return self._commit('reconnect:'+self.session,{'type':'SESSION_STARTED','session':self.session,'previous_session':old,'reconnect_generation':self.generation,'reason':reason,'clock':self.clock(),'clock_domain':self.domain,'origin':self.origin,'coverage':'COVERAGE_SEMANTICS_UNQUALIFIED','reconnect_overlap':'UNKNOWN_UNTIL_OBSERVED'})
    def end(self):
        return self._commit('capture-end:'+self.session,{'type':'CAPTURE_END','coverage_registry':{'ordered_admitted_native_members':[{'aggregate_id':a,**v} for a,v in self.seen.items()],'duplicate_deliveries':self.duplicate_count,'conflicting_deliveries':self.conflict_count,'queue_drops':self.drop_count,'session_boundaries':self.generation+1},'clock':self.clock(),'last_observed_native_id':self.last,'pending_queue':len(self.q),'ending_watermark':'OBSERVED_ONLY_NOT_VERIFIED','venue_coverage':'COVERAGE_SEMANTICS_UNQUALIFIED','state':'INCOMPLETE','real_source_qualification':'NOT_PROVEN','real_initiative_qualifier':'NOT_QUALIFIED / NO_ENTRY'})
