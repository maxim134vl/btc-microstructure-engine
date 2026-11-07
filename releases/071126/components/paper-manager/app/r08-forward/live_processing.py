from datetime import datetime,timezone
import json,uuid
from r08_spot import common
import canary_runner as cr
class LiveCanary(cr.Canary):
    dequeue_admitted=False
    def process(self,message,received):
        # One combined Spot socket. Only aggTrade enters Recorder.q/baseline.
        obj=json.loads(message);payload=obj.get('data',obj)
        if payload.get('e')=='kline':
            self.received+=1
            if self.received>self.cfg['max_delivered']:raise cr.Stop('DELIVERY_LIMIT')
            row=dict(received=received,status='KLINE_OPEN_NO_EFFECT',stream=obj.get('stream'),bytes=len(message),type='kline')
            self.m.rows.append(row)
            if not self.admission_allowed(received):raise cr.Deadline('CALLBACK_OUTSIDE_ADMISSION')
            if payload.get('k',{}).get('x') is True:
                raw=message.encode() if isinstance(message,str) else message
                native_ref='native/kline-'+str(uuid.uuid4())+'.bin'
                pub=self.r._commit('kline:'+str(uuid.uuid4()),dict(type='SPOT_KLINE_CLOSED',session=self.r.session,
                    message_received=received,clock_domain=self.r.domain,stream=obj.get('stream'),
                    native_ref=native_ref,native_message_sha256=common.sha(raw)),{native_ref:raw})
                ack_path=self.r.j.root/'receipts'/('ack-'+pub['manifest_sha']+'.json')
                ack=json.loads(ack_path.read_bytes())
                receipt=dict(session=self.r.session,clock_domain=self.r.domain,native_ref=str(self.r.j.root/native_ref),
                    manifest_sha256=pub['manifest_sha'],available_at=ack['observed_clock']['wall_utc'],
                    ack_monotonic_ns=ack['observed_clock']['monotonic_ns'],received=received)
                row.update(status='KLINE_CLOSE_COMMITTED',kline_publication=pub,receipt=receipt)
                row['adapter_result']=self.adapter.accept_kline(payload,stream=obj.get('stream'),receipt=receipt)
            return None
        if obj.get('stream')!='btcusdt@aggTrade':raise cr.Stop('COMBINED_STREAM_DOMAIN')
        out=super().process(message,received)
        self.adapter.accept(out,self.m.rows[-1])
        # Finish on actual target close + a successfully processed next-bar
        # trade; a plan, close reception, or S0 alone does not satisfy this.
        a=self.adapter
        if not getattr(self,'stop_on_target_bar',True):return out
        expected_open=self.target_open;expected_close=self.target_close
        if any(b['timeframe']=='M15' and b['bar_open']==expected_open and b['bar_close']==expected_close for b in a.boundaries):
            last=a.system.j.state['raw_order'][-1]
            T=datetime.fromisoformat(a.system.j.state['raw'][last]['trade']['trade_time'].replace('Z','+00:00'))
            if T.timestamp()>=expected_close and not any('delivery_id' in item for item in self.r.q):
                a.log('TARGET_M15_CONTINUED',native_id=a.system.j.state['source_cursor'],bar_open=expected_open,bar_close=expected_close,clock=common.stamp())
                self.reason='FULL_M15_PROCESSED';self.request_stop(self.reason)
        return out
