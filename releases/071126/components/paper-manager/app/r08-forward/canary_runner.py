"""One explicitly authorised bounded canary, no runtime or trading imports."""
import os,sys,json,time,ssl,socket,signal,stat,resource,subprocess,hashlib,functools,array,uuid,threading,base64
from pathlib import Path
ROOT=Path(__file__).resolve().parent
from r08_spot import common,recorder,storage
from r08_spot.recorder import Recorder
from r08_spot.storage import Journal
from r08_spot.ws_connection import bounded_socket_class
from r08_spot.transport import ENDPOINT
def peer_close_details(data):
 raw=data.encode('utf-8') if isinstance(data,str) else bytes(data)
 result={'payload_base64':base64.b64encode(raw).decode('ascii'),'code':None,'reason':'','decode_error':None}
 if len(raw)==1:result['decode_error']='CLOSE_PAYLOAD_TOO_SHORT'
 elif len(raw)>=2:
  result['code']=int.from_bytes(raw[:2],'big')
  try:result['reason']=raw[2:].decode('utf-8')
  except UnicodeDecodeError as exc:result['reason']=None;result['decode_error']=str(exc)
 return result

class Deadline(RuntimeError):pass
class Stop(RuntimeError):pass
def pins():
 saved=json.loads((ROOT/'evidence/QUALIFIED_PINS.json').read_text())
 for name,expected in saved['sha256'].items():
  if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected:raise Stop('SOURCE_PIN_MISMATCH:'+name)
 if not json.loads((ROOT/'evidence/PREFLIGHT.json').read_text())['passed']:raise Stop('PREFLIGHT_NOT_PASSED')
 return saved

def resources(label):
 out={'label':label,'clock':common.stamp(),'process_rss_highwater':common.rss_bytes(),'load_average':os.getloadavg(),'canonical_health':'NOT_VERIFIED_NO_DOCKER_ACTIONS'}
 for key,cmd in [('vm_stat',['/usr/bin/vm_stat']),('swap',['/usr/sbin/sysctl','vm.swapusage']),('memory_pressure',['/usr/bin/memory_pressure','-Q']),('cpu',['/usr/bin/top','-l','1','-n','0'])]:
  p=subprocess.run(cmd,text=True,capture_output=True,timeout=8);out[key]={'exit':p.returncode,'stdout':p.stdout[:4000],'stderr':p.stderr[:300]}
 p=subprocess.run(['/bin/ps','-axo','pid,pcpu,rss,comm'],text=True,capture_output=True,timeout=5)
 out['existing_processes']=[l for l in p.stdout.splitlines() if any(x in l.lower() for x in ['docker','python','btc'])][:60]
 return out
class Metrics:
 def __init__(self):
  self.samples={};self.rows=[];self.resources=[];self.queue_max=0;self.queue_bytes_max=0
  self.queue_calls=[];self.admission_attempts=[];self.instrumentation_errors=[];self._installed=False
 def add(self,name,ns):
  a=self.samples.setdefault(name,array.array('d'))
  if len(a)>=65536:raise Stop('MEASUREMENT_MEMORY_CAP')
  a.append(ns/1e6)
 def safe_add(self,name,ns):
  try:self.add(name,ns)
  except Exception as e:
   if len(self.instrumentation_errors)<1024:self.instrumentation_errors.append({'phase':name,'error':type(e).__name__+':'+str(e)})
 def wrap(self,name,fn):
  @functools.wraps(fn)
  def wrapped(*a,**k):
   t=time.monotonic_ns()
   try:return fn(*a,**k)
   finally:self.safe_add(name,time.monotonic_ns()-t)
  return wrapped
 def instrument(self):
  if self._installed:return
  self._installed=True
  recorder.parse_message=self.wrap('json_parse',recorder.parse_message)
  recorder.mapping=self.wrap('normalization',recorder.mapping)
  for name in ['commit','_publish']:
   original=getattr(Journal,name)
   if name=='_publish':
    def publication(j,rel,raw,_original=original):
     phase='native_publication' if rel.startswith('native/') else 'manifest_publication' if rel.startswith('manifests/') else 'ack_publication' if rel.startswith('receipts/ack-') else 'receipt_publication'
     return self.wrap(phase,_original)(j,rel,raw)
    setattr(Journal,name,publication)
   else:setattr(Journal,name,self.wrap('journal_commit',original))
  from collections import deque
  metrics=self
  class TimedQueue(deque):
   _dra_metrics=metrics
   def append(self,v):
    start=time.monotonic_ns();outcome='RETURNED';error=None
    try:return super().append(v)
    except BaseException as e:
     outcome='RAISED';error=type(e).__name__;raise
    finally:
     end=time.monotonic_ns()
     metrics.safe_add('queue_append',end-start)
     if len(metrics.queue_calls)<65536:
      metrics.queue_calls.append({'start_monotonic_ns':start,'end_monotonic_ns':end,'duration_ns':end-start,'outcome':outcome,'error':error,'queue_object_id':id(self)})
  recorder.deque=TimedQueue
 def verify_queue(self,r):
  if getattr(r.q,'_dra_metrics',None) is not self:raise Stop('QUEUE_INSTRUMENTATION_NOT_BOUND')
  return {'queue_object_id':id(r.q),'bound_before_delivery':r.delivery==0,'pending_restored':len(r.q)}
 def receive_attempt(self,fn,message,received):
  # Inclusive actual _receive call; rejection occurs before append in Recorder.
  start=time.monotonic_ns();before=len(self.queue_calls);out=None;error=None
  try:
   out=fn(message,received);return out
  except BaseException as e:
   error=type(e).__name__;raise
  finally:
   end=time.monotonic_ns();self.safe_add('receive_admission_attempt_inclusive',end-start)
   if len(self.admission_attempts)<65536:
    self.admission_attempts.append({'start_monotonic_ns':start,'end_monotonic_ns':end,'duration_ns':end-start,'status':out['queue']['status'] if out else 'RAISED','reason':out['queue'].get('reason') if out else None,'error':error,'append_calls':len(self.queue_calls)-before,'queue_receipt_clock':out['queue']['clock'] if out else None,'measurement_authority':'OFFLINE_OR_LIVE_RUNNER_TIMING_NOT_DURABLE_ACK'})
class Canary:
 def __init__(self,j,r,config,metrics):
  self.j=j;self.r=r;self.cfg=config;self.m=metrics;self.received=0;self.phase='SETUP';self.ended=False;self.deadline=None;self.reason='NOT_STARTED';self.transport=None
  self.deadline_ns=None;self.stop_lock=threading.RLock();self.stop_requested=None;self.stop_reason=None
  self.timer_arm_invoked=None;self.timer_arm_returned=None;self.timer_handler_observed=None
  self.socket_close_invoked=None;self.socket_close_returned=None;self.socket_closed=None;self.socket_close_status='NOT_ATTEMPTED';self._shutdown_attempted=False
 def request_stop(self,reason):
  with self.stop_lock:
   if self.stop_requested is None:self.stop_requested=common.stamp();self.stop_reason=reason
   self.ended=True
 def admission_allowed(self,received):
  # Direct offline fixtures have no attempt boundary; network paths always do.
  if self.deadline_ns is None:
   return not self.ended or bool(getattr(self,'worker',None) and threading.current_thread() is self.worker.thread)
  with self.stop_lock:
   in_worker=bool(getattr(self,'worker',None) and threading.current_thread() is self.worker.thread)
   if (self.ended and not in_worker) or received['monotonic_ns']>=self.deadline_ns or time.monotonic_ns()>=self.deadline_ns:
    self.request_stop('DURATION_LIMIT' if received['monotonic_ns']>=self.deadline_ns or time.monotonic_ns()>=self.deadline_ns else 'STOP_REQUESTED')
    return False
   return True
 def shutdown_transport(self,ws,peer):
  with self.stop_lock:
   if self._shutdown_attempted:return
   self._shutdown_attempted=True
  if ws is None:self.socket_close_status='NO_RETURNED_TRANSPORT';return
  self.socket_close_invoked=common.stamp()
  try:
   ws.shutdown()
  except BaseException as e:
   self.socket_close_status='RAISED';self.socket_close_error=type(e).__name__+':'+str(e)
  else:
   try:closed=ws.sock is None and peer is not None and peer.fileno()==-1
   except Exception:closed=False
   self.socket_close_status='RETURNED_LOCAL_CLOSED' if closed else 'RETURNED_UNPROVEN'
  finally:self.socket_close_returned=common.stamp()
  if self.socket_close_status=='RETURNED_LOCAL_CLOSED':self.socket_closed=self.socket_close_returned
  else:self.reason='FAILED:SOCKET_SHUTDOWN_UNPROVEN|'+self.reason
 def deadline_observation(self):
  cutoff=self.deadline_ns
  timely=self.socket_closed is not None and cutoff is not None and self.socket_closed['monotonic_ns']<=cutoff
  return {'deadline_ns':cutoff,'origin':getattr(self,'attempt_start',None),'timer_arm_invoked':self.timer_arm_invoked,'timer_arm_returned':self.timer_arm_returned,'timer_handler_observed':self.timer_handler_observed,'stop_requested':self.stop_requested,'stop_reason':self.stop_reason,'stop_accepting_observed':getattr(self,'accepting_stopped',None),'close_invoked':self.socket_close_invoked,'close_return_observed':self.socket_close_returned,'local_close_completion_observed':self.socket_closed,'close_status':self.socket_close_status,'socket_close_error':getattr(self,'socket_close_error',None),'strict_transport_result':'OBSERVED_LOCAL_CLOSE_BY_BOUNDARY' if timely else 'NOT_PROVEN','physical_remote_close':'NOT_MEASURED','no_realtime_scheduling_guarantee':True}
 def alarm(self,*args):
  self.timer_handler_observed=common.stamp();self.request_stop('DURATION_LIMIT')
  if self.phase in ('NETWORK','CONNECT','MONITOR'):raise Deadline('DURATION_LIMIT')
 def callback(self,message):
  received=common.stamp() # FIRST application callback instruction; not kernel receive.
  return self.accept_received(message,received)
 def accept_received(self,message,received):
  self.first_message=getattr(self,'first_message',None) or received;self.last_message=received
  worker=getattr(self,'worker',None)
  if worker is not None:
   if not self.admission_allowed(received):
    worker.reject(message,received,'CALLBACK_OUTSIDE_ADMISSION');raise Deadline('CALLBACK_OUTSIDE_ADMISSION')
   self.input_received_count=getattr(self,'input_received_count',self.received)+1
   if self.input_received_count>self.cfg['max_delivered']:
    worker.reject(message,received,'DELIVERY_LIMIT');raise Stop('DELIVERY_LIMIT')
   if common.rss_bytes()>self.cfg['rss_bytes']:
    worker.reject(message,received,'RECORDER_RSS_CAP');raise Stop('RECORDER_RSS_CAP')
   return worker.offer(message,received)
  return self.process(message,received)
 def process(self,message,received):
  self.received+=1
  if self.received>self.cfg['max_delivered']:raise Stop('DELIVERY_LIMIT')
  row={'received':received,'payload_sha256':common.sha(message.encode('utf-8') if isinstance(message,str) else message),'bytes':len(message.encode('utf-8')) if isinstance(message,str) else len(message),'status':'RECEIVED','receive_origin':'APPLICATION_CALLBACK_NOT_KERNEL','error':None}
  self.m.rows.append(row)
  try:
   if not self.admission_allowed(received):
    row['status']='NOT_ADMITTED_STOP_OR_DEADLINE';raise Deadline('CALLBACK_OUTSIDE_ADMISSION')
   out=self.m.receive_attempt(self.r._receive,message,received)
   row['native_ack_completion_observed']=common.stamp() # after actual successful durable receive return
   row.update(delivery_id=out['delivery_id'],queue=out['queue'],mapping_status=out['mapping']['status'] if out['mapping'] else None,publication=out['publication'],status='ACK_OBSERVED')
   if out['mapping'] and out['mapping']['core']:
    native=out['mapping']['core'];row.update(native_id=native['native_id'],E=out['mapping']['fields']['E']['value'],T=out['mapping']['fields']['T']['value'],exchange_event_to_callback_ms=received['wall_ns']/1e6-out['mapping']['fields']['E']['value'],exchange_trade_to_callback_ms=received['wall_ns']/1e6-out['mapping']['fields']['T']['value'],coverage=out['coverage'])
   self.m.queue_max=max(self.m.queue_max,len(self.r.q));self.m.queue_bytes_max=max(self.m.queue_bytes_max,self.r.qbytes)
   if out['queue']['status']=='ADMITTED':
    if getattr(self,'dequeue_admitted',True):self.r.dequeue()
   elif out['queue'].get('reason')=='QUEUE_CAPACITY_REJECTED':raise Stop('QUEUE_OVERFLOW')
   elif out['queue'].get('reason')=='CONFLICTING_NATIVE_IDENTITY':raise Stop('NATIVE_IDENTITY_CONFLICT')
   elif row['mapping_status']!='ACCEPTED':raise Stop('PARSE_OR_NORMALIZATION_REJECTION')
   if common.rss_bytes()>self.cfg['rss_bytes']:
    worker.reject(message,received,'RECORDER_RSS_CAP');raise Stop('RECORDER_RSS_CAP')
   return out
  except BaseException as e:
   row['error']=type(e).__name__+':'+str(e)
   if row['status']=='RECEIVED':row['status']='INCOMPLETE'
   raise
  finally:
   row['callback_return_observed']=common.stamp();row['callback_ms']=(time.monotonic_ns()-received['monotonic_ns'])/1e6
   self.m.add('callback',row['callback_ms']*1e6)
 def _reply_ping(self,ws,data):
  control=self.transport['control'];control['ping_count']+=1
  control['last_ping_received']=common.stamp();control['last_ping_payload_sha256']=common.sha(data)
  ws.pong(data)
  control['pong_count']+=1;control['last_pong_sent']=common.stamp()
 def run_network(self,factory=None,*,continuous=False):
  if factory is None:raise Stop('NETWORK_DISABLED_OFFLINE_DEADLINE_QUALIFICATION')
  import websocket
  config=self.cfg
  context=ssl.create_default_context();context.verify_mode=ssl.CERT_REQUIRED;context.check_hostname=True
  if context.verify_mode!=ssl.CERT_REQUIRED or not context.check_hostname:raise Stop('TLS_POLICY')
  self.attempt_start=common.stamp();self.deadline_ns=None if continuous else self.attempt_start['monotonic_ns']+int(config['duration_seconds']*1_000_000_000);self.deadline=None if continuous else self.deadline_ns/1e9;self.phase='CONNECT'
  old=signal.signal(signal.SIGALRM,self.alarm)
  base=bounded_socket_class(65536);canary=self
  class DeadlineSocket(base):
   def _recv(self,n):
    remaining=None if canary.deadline_ns is None else (canary.deadline_ns-time.monotonic_ns())/1e9
    if canary.ended or (remaining is not None and remaining<=0):raise Deadline(canary.stop_reason or 'DURATION_LIMIT')
    self.settimeout(2.0 if remaining is None else min(2.0,remaining));return super()._recv(n)
  ws=None;peer=None;partial=bytearray();opcode=None;self.first_message=None;self.last_message=None
  try:
   self.timer_arm_invoked=common.stamp();remaining_ns=None if continuous else self.deadline_ns-time.monotonic_ns()
   if remaining_ns is not None and remaining_ns<=0:raise Deadline('DURATION_LIMIT')
   signal.setitimer(signal.ITIMER_REAL,0 if continuous else remaining_ns/1e9);self.timer_arm_returned=common.stamp()
   ws=(factory or websocket.create_connection)(ENDPOINT,timeout=10,sslopt={'context':context,'cert_reqs':ssl.CERT_REQUIRED,'check_hostname':True},class_=DeadlineSocket,redirect_limit=0,http_no_proxy=['stream.binance.com'],enable_multithread=False)
   peer=ws.sock
   if not isinstance(peer,ssl.SSLSocket) or peer.context.verify_mode!=ssl.CERT_REQUIRED or not peer.context.check_hostname:raise Stop('AUTHENTICATED_TLS_NOT_PROVEN')
   cert=peer.getpeercert(binary_form=True)
   if not cert:raise Stop('TLS_PEER_RECEIPT_MISSING')
   self.transport={'endpoint':ENDPOINT,'certificate_sha256':common.sha(cert),'certificate_verified':True,'hostname_verified':True,'tls_version':peer.version(),'cipher':peer.cipher(),'websocket_client_version':websocket.__version__,'peer_address':peer.getpeername(),'network_sessions':1,'api_keys_used':False,'reconnects':0}
   self.transport['control']={'ping_count':0,'pong_count':0,'last_ping_received':None,'last_pong_sent':None}
   self.phase='JOURNAL'
   if getattr(self,'worker',None):self.worker.transport(self.transport)
   else:self.r.transport_observation(self.transport)
   self.reason='DURATION_LIMIT';next_resource=time.monotonic()+10
   while not self.ended and (self.deadline_ns is None or time.monotonic_ns()<self.deadline_ns):
    if len(self.r.seen)>=config['max_unique'] or getattr(self,'input_received_count',self.received)>=config['max_delivered']:self.reason='EVENT_LIMIT';break
    self.phase='NETWORK';ws.frame_buffer.remaining=65536-len(partial)
    try:frame=ws.recv_frame()
    except websocket.WebSocketTimeoutException:
     if self.deadline_ns is not None and time.monotonic_ns()>=self.deadline_ns:break
     continue
    if frame.opcode==8:
     self.peer_close={**peer_close_details(frame.data),'observed_clock':common.stamp()}
     self.transport['peer_close']=self.peer_close
     if getattr(self,'worker',None):self.worker.transport({**self.transport,'event':'PEER_CLOSE'})
     else:self.r.transport_observation({**self.transport,'event':'PEER_CLOSE'})
     self.reason='PEER_CLOSE';break
    if frame.opcode==9:self._reply_ping(ws,frame.data);continue
    if frame.opcode==10:continue
    if frame.opcode in (1,2):
     if opcode is not None:raise Stop('OVERLAPPING_WS_MESSAGE')
     opcode=frame.opcode
    elif frame.opcode!=0 or opcode is None:raise Stop('WS_FRAGMENT_ORDER')
    if len(partial)+len(frame.data)>65536:raise Stop('WS_MESSAGE_CAP')
    partial.extend(frame.data)
    if frame.fin:
     if self.ended or (self.deadline_ns is not None and time.monotonic_ns()>=self.deadline_ns):break
     raw=bytes(partial);message=raw.decode('utf-8') if opcode==1 else raw
     self.phase='CALLBACK';self.callback(message)
     # Receive clocks are fixed by callback, not by the consumer's last row.
     partial.clear();opcode=None
     # Byte observations only, never claimed as message arrival timestamps.
     import fcntl,termios
     available=array.array('i',[0]);fcntl.ioctl(peer.fileno(),termios.FIONREAD,available,True)
     tls_pending=peer.pending();buffered=sum(len(v) for v in getattr(ws.frame_buffer,'recv_buffer',[]))
     observation={'tcp_encrypted_bytes':max(0,available[0]),'tls_decrypted_bytes':tls_pending,'frame_buffer_bytes':buffered,'not_market_event_count':True}
     if getattr(self,'worker',None):self.transport['last_buffers_observed']=observation
     else:self.m.rows[-1]['transport_buffers_observed']=observation
     if tls_pending+buffered>config['queue_bytes']:raise Stop('OBSERVED_TRANSPORT_BYTE_CAP')
    if time.monotonic()>=next_resource and not self.ended:
     self.phase='MONITOR';self.m.resources.append(resources('DURING'));next_resource=time.monotonic()+10
   if partial:self.partial_at_end=len(partial)
  except Deadline:
   # _recv interrupts both an elapsed deadline and an already requested stop.
   # request_stop records the first cause; a normal stop is not a timeout.
   self.reason=self.stop_reason or 'DURATION_LIMIT';self.partial_at_end=len(partial)
  except BaseException as e:
   self.reason='FAILED:'+type(e).__name__+':'+str(e)
   if self.transport is not None:self.transport['failure']={'type':type(e).__name__,'message':str(e),'phase':self.phase,'clock':common.stamp(),'partial_message_bytes':len(partial)}
  finally:
   # Also preserve the first cause when the receive loop exits without raising.
   # Real transport failures and PEER_CLOSE keep their own result.
   with self.stop_lock:
    if self.stop_reason and self.reason in ('FULL_M15_PROCESSED','DURATION_LIMIT'):
     self.reason=self.stop_reason
   self.phase='FINALIZE';self.request_stop(self.reason);self.accepting_stopped=common.stamp()
   signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)
   self.shutdown_transport(ws,peer)
  return self.reason

def execute(*, network_factory=None):
 qualified=pins();cfg=json.loads((ROOT/'canary_config.json').read_text());j=Journal(ROOT/'captures/live-one',quota=cfg['quota_bytes'])
 if 'one-authorized-attempt' in j.keys:j.close();raise Stop('ONE_ATTEMPT_ALREADY_RESERVED')
 m=Metrics();before=resources('BEFORE');m.resources.append(before)
 m.instrument() # must precede __init__ AND _restore queue construction
 r=Recorder(j,origin=cfg['origin']);m.verify_queue(r);c=Canary(j,r,cfg,m)
 j.commit('one-authorized-attempt',{'type':'ONE_AUTHORIZED_CANARY_ATTEMPT','configuration_sha256':common.sha((ROOT/'canary_config.json').read_bytes()),'pins':qualified,'clock':common.stamp(),'no_second_attempt':True})
 cpu=time.process_time();start=time.monotonic()
 reason=c.run_network() if network_factory is None else c.run_network(factory=network_factory)
 final_error=None
 try:
  j.guard.check()
  if not r.blocked:
   while r.q:r.dequeue()
   r.end()
  j.commit('canary-session-ended',{'type':'CANARY_SESSION_ENDED','reason':reason,'clock':common.stamp(),'actual_attempt_start':c.attempt_start,'accepting_stopped':c.accepting_stopped,'socket_closed':c.socket_closed,'first_callback':c.first_message,'last_callback':c.last_message,'partial_transport_bytes':getattr(c,'partial_at_end',0),'received_application_messages':c.received,'pending_queue':len(r.q),'network_session_count':1 if c.transport else 0,'source_coverage':'UNQUALIFIED','own_context_witness':'NOT_QUALIFIED'},emergency=True)
 except BaseException as e:final_error=type(e).__name__+':'+str(e)
 j.close();m.resources.append(resources('AFTER'))
 results={'reason':reason,'deadline_observation':c.deadline_observation(),'transport':c.transport,'attempt_start':c.attempt_start,'accepting_stopped':c.accepting_stopped,'socket_closed':c.socket_closed,'first_callback':c.first_message,'last_callback':c.last_message,'received_messages':c.received,'rows':m.rows,'metrics_ms':{k:list(v) for k,v in m.samples.items()},'queue_append_calls':m.queue_calls,'receive_admission_attempts':m.admission_attempts,'instrumentation_errors':m.instrumentation_errors,'queue_max':m.queue_max,'queue_bytes_max':m.queue_bytes_max,'resource_observations':m.resources,'cpu_seconds':time.process_time()-cpu,'wall_seconds_including_finalization':time.monotonic()-start,'rss_peak_bytes':common.rss_bytes(),'capture_root':str(j.root),'quota_charge_bytes':j.used,'finalization_error':final_error,'source_qualification':'NOT_PROVEN','context_observer_enabled':False,'own_context_witness':'NOT_QUALIFIED','kernel_and_socket_arrivals':'NOT_MEASURED','transport_backlog':'UNKNOWN_SYNCHRONOUS_CALLBACK_CAN_HIDE_BUFFERING','capacity_sustained_verdict':'PENDING_INDEPENDENT_VALIDATION'}
 # All output writes remain under verified new external project; no fallback.
 g=storage.ExternalGuard(ROOT/'captures/live-one')
 try:
  g.check();(ROOT/'evidence/LIVE_RESULT.json').write_text(json.dumps(results,indent=2)+'\n')
 finally:g.close()
 print(json.dumps({k:results[k] for k in ['reason','received_messages','rss_peak_bytes','cpu_seconds','quota_charge_bytes','finalization_error']}))
 return 0 if final_error is None else 1

def main(argv=None):
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--execute-one-authorized-canary',action='store_true');a=p.parse_args(argv)
 if not a.execute_one_authorized_canary:print('NETWORK_DISABLED_DEFAULT');return 0
 raise Stop('NETWORK_DISABLED_OFFLINE_DEADLINE_QUALIFICATION')
if __name__=='__main__':raise SystemExit(main())
