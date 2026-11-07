"""One consumer of Recorder's existing bounded deque. Enqueue is never ACK."""
import threading,time,json,base64
from decimal import getcontext,setcontext
from r08_spot import common

class ReceiveWorker:
    def __init__(self,canary,handler,*,replay=False):
        self.c=canary;self.r=canary.r;self.handler=handler;self.replay=replay
        self.closing=False;self.error=None;self.failure_traceback=None;self.rejected=None;self.sequence=0
        self.completed=0;self.native_completed=0;self.max_depth=0;self.max_bytes=0
        self.last_completion=None;self.latencies=[];self.callback_ns=[];self.thread=None
        self.context=getcontext().copy();self.r.on_dequeued=self._dequeued
        adapter=getattr(canary,'adapter',None)
        if adapter is not None:
            adapter.processing_stopped=lambda:bool(self.closing or self.error or
                (self.c.deadline_ns is not None and time.monotonic_ns()>=self.c.deadline_ns))
    def start(self):
        if self.thread is not None:raise RuntimeError('ONE_WORKER_ONLY')
        self.thread=threading.Thread(target=self._run,name='recorder-r08-worker',daemon=False);self.thread.start()
    def offer(self,message,received,*,service=None):
        start=time.monotonic_ns();self.sequence+=1
        if self.closing or self.error:
            if self.rejected is None:self.reject(message,received,'RECEIVE_WORKER_STOPPED')
            raise RuntimeError('RECEIVE_WORKER_STOPPED')
        queued=common.stamp()
        item,rejected=self.r.offer_received(message,received,self.sequence,queued,service=service)
        if rejected is not None:
            self.rejected=rejected;self._fail('RECEIVE_QUEUE_OVERFLOW_INCOMPLETE')
            raise common.Capacity('RECEIVE_QUEUE_OVERFLOW_INCOMPLETE')
        with self.r.dispatch_condition:
            self.max_depth=max(self.max_depth,len(self.r.q));self.max_bytes=max(self.max_bytes,self.r.qbytes)
        self.callback_ns.append(time.monotonic_ns()-start)
        return item
    def reject(self,message,received,reason):
        self.sequence+=1
        self.rejected={'_dispatch_state':'REJECTED','_dispatch_message':message,
            '_dispatch_received':dict(received),'_dispatch_sequence':self.sequence,
            '_dispatch_queued_clock':common.stamp()}
        self._fail(reason)
    def transport(self,record):
        record={**record,'clock':common.stamp()}
        return self.offer(json.dumps(record,separators=(',',':')),record['clock'],service='TRANSPORT')
    def _fail(self,reason):
        if (reason=='RECEIVE_QUEUE_OVERFLOW_INCOMPLETE' and self.error is None
                and self.failure_traceback is None and self.thread is not None):
            try:
                import sys,traceback
                frame=sys._current_frames().get(self.thread.ident)
                if frame is not None:
                    self.failure_traceback=('WORKER_STACK_AT_RECEIVE_OVERFLOW (not an exception traceback)\n'
                        +''.join(traceback.format_stack(frame,limit=20)))
            except Exception:
                pass  # Original explicit incomplete/stop handling must run.
        with self.c.stop_lock:
            if self.error is None:self.error=reason
            self.c.reason='FAILED:'+self.error;self.c.request_stop(self.c.reason)
        with self.r.dispatch_condition:self.r.dispatch_condition.notify_all()
    def _dequeued(self,item):
        if '_dispatch_received' not in item:return
        done=common.stamp();origin=item['_dispatch_queued_clock'] if self.replay else item['_dispatch_received']
        elapsed=done['monotonic_ns']-origin['monotonic_ns']
        self.native_completed+=1;self.latencies.append(elapsed)
        self.last_completion={'native_id':item['native_id'],'received':item['_dispatch_received'],'completed':done,
                              'receive_to_complete_ns':elapsed,'latency_origin':'REPLAY_REAL_ENQUEUE' if self.replay else 'ORIGINAL_RECEIVE'}
    def _run(self):
        setcontext(self.context)
        try:
            while True:
                with self.r.dispatch_condition:
                    while True:
                        if self.error:return
                        if self.c.deadline_ns is not None and time.monotonic_ns()>=self.c.deadline_ns:return
                        item=next((x for x in self.r.q if x.get('_dispatch_state')=='RECEIVE_PENDING'),None)
                        if item is not None:break
                        if self.closing:return
                        self.r.dispatch_condition.wait()
                    item['_dispatch_state']='PROCESSING'
                self.r._dispatch_current=item
                if item.get('_dispatch_service')=='TRANSPORT':
                    self.r.transport_observation(json.loads(item['_dispatch_message']))
                else:
                    self.handler(item['_dispatch_message'],item['_dispatch_received'])
                    self.completed+=1
                self.r.finish_received(item)
        except BaseException as exc:
            self.failure_traceback=__import__('traceback').format_exc()
            self._fail(type(exc).__name__+':'+str(exc))
        finally:
            self.r._dispatch_current=None
    def close(self):
        self.closing=True
        with self.r.dispatch_condition:self.r.dispatch_condition.notify_all()
        if self.thread is not None:self.thread.join()
    def snapshot(self):
        with self.r.dispatch_condition:
            return dict(queue_depth=len(self.r.q),queue_bytes=self.r.qbytes,
                pending_receive=sum(x.get('_dispatch_state') in ('RECEIVE_PENDING','PROCESSING') for x in self.r.q),
                pending_durable=self.r.durable_depth(),completed_messages=self.completed,
                completed_native=self.native_completed,max_queue_depth=self.max_depth,max_queue_bytes=self.max_bytes,
                error=self.error,worker_alive=bool(self.thread and self.thread.is_alive()),last_completion=self.last_completion)
    def persist_unprocessed(self):
        # One bounded batch in the existing capture WAL, not per-event files.
        with self.r.dispatch_condition:items=list(self.r.q)
        if self.rejected is not None:items.append(self.rejected)
        chunks={};buffer=bytearray(b'[');count=0
        def append(raw):
            buffer.extend(raw)
            while len(buffer)>=2*1024*1024:
                n=len(chunks);chunks[f'native/unprocessed-receive-{n:02d}.jsonpart']=bytes(buffer[:2*1024*1024]);del buffer[:2*1024*1024]
        for item in items:
            message=item.get('_dispatch_message')
            if message is None:continue
            raw=message.encode('utf-8',errors='surrogatepass') if isinstance(message,str) else message
            entry=dict(sequence=item['_dispatch_sequence'],received=item['_dispatch_received'],
                representation='TEXT_UTF8_SURROGATEPASS' if isinstance(message,str) else 'BYTES',
                payload_base64=base64.b64encode(raw).decode(),state='RECEIVED_NOT_ACKNOWLEDGED',service=item.get('_dispatch_service'))
            if count:append(b',')
            append(json.dumps(entry,separators=(',',':')).encode());count+=1
        if not count:return None
        append(b']')
        if buffer:chunks[f'native/unprocessed-receive-{len(chunks):02d}.jsonpart']=bytes(buffer)
        publication=self.r.j.commit('unprocessed-receive-snapshot',dict(type='CAPTURE_BLOCKED',
            reason=self.error or 'UNPROCESSED_RECEIVE_AT_DEADLINE',state='INCOMPLETE',clock=common.stamp(),
            pending_receive_count=count,pending_receive_refs=list(chunks),not_delivery_ACK=True),chunks,emergency=True)
        return dict(count=count,publication=publication,refs=list(chunks),not_delivery_ACK=True)
