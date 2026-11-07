"""Direct callback adapter; no archive reader or new source trust protocol."""
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
from .trend_event import Trade, canonical, utc
from .trend_evidence import RawOccurrence
from .trend_journal import Blocked, digest
from .r08_baseline_provider import prepare_research_system
from .context_trend_integration import ContextTrendIntegration
from .entry_kill_switch import EntryOnlyKillSwitch

def now():return datetime.now(timezone.utc).isoformat()

class RecorderLiveAdapter:
    def __init__(self, recorder, rows, contexts, *, journal_path, log_path, declared_at, on_cycle=None, max_r08_events=4096, runtime_config=None, capture_family=None):
        self.recorder=recorder;self.rows=rows;self.contexts=contexts;self.journal_path=Path(journal_path)
        self.log_path=Path(log_path);self.declared_at=declared_at;self.on_cycle=on_cycle
        self.max_r08_events=max_r08_events;self.previous=None;self.first_T=None;self.current=None;self.system=None;self.prepared=None
        self.baseline_capture=None;self.baseline_summary=None;self.delivered=0;self.cycle_delivered=False
        self.integration=None;self.last_decisions={};self.s0_result=None;self.on_s0=None
        self.runtime_config=dict(runtime_config or {});self.capture_family=capture_family or recorder.session
        self.bars={tf:{} for tf in contexts};self.close_seen={};self.partial_closed=set();self.waiting={};self.boundaries=[];self.last_source_T=None
    def log(self,event,**data):
        with self.log_path.open('a') as f:f.write(json.dumps(dict(at=now(),event=event,**data),default=str)+'\n');f.flush()
    def owns_current(self,raw,config):
        return bool(self.current and raw.packet()==self.current['packet']
                    and config['capture_family']==raw.capture_family==self.capture_family
                    and config['coverage_ref']==str(self.recorder.j.root))
    def paper_source(self,config,raw,cutoff):
        if not self.owns_current(raw,config):raise Blocked('LIVE_DELIVERY_NOT_CURRENT')
        raw.validate(cutoff)
        return dict(level='OBSERVED',receipt_sha256=self.current['ack_sha256'],
                    venue_completeness='UNKNOWN_NOT_ASSERTED',aggressor_semantics='PROJECT_MAPPING_ONLY / VENUE_UNQUALIFIED')
    def context_baseline(self,config,tf,cutoff,verify):
        from .live_direct_source import cached_context_baseline
        return cached_context_baseline(self,config,tf,cutoff,verify)
    def fixed_baseline(self,config):
        expected=getattr(self,'_prepared_config',None)
        if expected is None:expected=self.prepared.config;self._prepared_config=expected
        if (config['predecessor'],config['baseline_available_at'],config['coverage_ref']) != (expected['predecessor'],expected['baseline_available_at'],expected['coverage_ref']):
            raise Blocked('LIVE_BASELINE_BINDING')
        # Native INIT/config immutability is unchanged. This input was built once
        # by the accepted provider from these same completed callback deliveries.
    def accept(self,out,row):
        if out['queue']['status']!='ADMITTED':
            self.log('SOURCE_NO_NEW_MEMBER',reason=out['queue'].get('reason'));return
        pub=out['publication'];ack_path=self.recorder.j.root/'receipts'/('ack-'+pub['manifest_sha']+'.json')
        cached=getattr(self.recorder.j,'committed_ack',None)
        ack_raw=(cached[2] if cached is not None and cached[:2]==(pub['seq'],pub['manifest_sha'])
                 else ack_path.read_bytes())
        ack=json.loads(ack_raw)
        core=out['mapping']['core'];trade=Trade(**core,receive_time=out['message_received']['wall_utc'],payload_sha=out['mapping']['core_sha256'])
        raw=RawOccurrence(trade,canonical(core),'REAL_CANDIDATE',self.capture_family,str(self.recorder.j.root/out['coverage_ref']),self.previous,ack['observed_clock']['wall_utc'])
        admission_cutoff=now()
        try:raw.validate(admission_cutoff)
        except Blocked as exc:
            if str(exc)=='RAW_AVAILABILITY':
                self.log('RAW_AVAILABILITY_REJECTED',event_id=trade.native_id,
                         ack_available_at=raw.available_at,cutoff=admission_cutoff,
                         ack_minus_cutoff_us=(utc(raw.available_at)-utc(admission_cutoff))//timedelta(microseconds=1),
                         call_site='RecorderLiveAdapter.accept:raw.validate',
                         cutoff_source='datetime.now(timezone.utc).isoformat():ADAPTER_ADMISSION')
            raise
        if self.previous is not None and trade.native_id!=self.previous+1:raise Blocked('LIVE_NATIVE_SEQUENCE_GAP')
        self.previous=trade.native_id
        d=dict(delivery_id=out['delivery_id'],packet=raw.packet(),available_by=raw.available_at,
               ack_sha256=__import__('hashlib').sha256(ack_raw).hexdigest(),manifest_seq=pub['seq'],manifest_sha256=pub['manifest_sha'],
               ack_monotonic_ns=ack['observed_clock']['monotonic_ns'],clock_domain=out['clock_domain'],
               message_received=dict(out['message_received']),receive_sequence=getattr(self.recorder,'_dispatch_current',None).get('_dispatch_sequence') if getattr(self.recorder,'_dispatch_current',None) is not None else None)
        row['r08_delivery']=d;self.current=d;self.delivered+=1
        at=utc(trade.trade_time);self.first_T=self.first_T or at
        self._observe_trade(out,trade)
        if getattr(self,'queue_handoff',False):
            with self.recorder.dispatch_condition:
                item=next((x for x in reversed(self.recorder.q) if x.get('delivery_id')==out['delivery_id']),None)
            if item is None:raise Blocked('LIVE_QUEUE_HANDOFF_MISSING')
            item['r08_delivery']=d
        if self.system is None:
            if (at-self.first_T).total_seconds()<300:
                if self.delivered%100==0:
                    self.log('PREFIX_PROGRESS',events=self.delivered,T_coverage_seconds=(at-self.first_T).total_seconds())
                    print(json.dumps(dict(stage='PREFIX',events=self.delivered,T_coverage_seconds=(at-self.first_T).total_seconds())),flush=True)
                if getattr(self,'queue_handoff',False):self.recorder.dequeue()
                return
            # Existing launcher rows are the preceding stream buffer. A view is
            # formed once at fixation; it is not reconstructed for each message.
            capture=dict(root=str(self.recorder.j.root),deliveries=[r['r08_delivery'] for r in self.rows if 'r08_delivery' in r],pending_queue=[])
            template=dict(mode='REAL_CANDIDATE',market='BINANCE_SPOT',capture_family=self.capture_family,
                coverage_ref=str(self.recorder.j.root),sequence='CONTIGUOUS_PLUS_ONE',source_transport='RECORDER_LIVE',
                timeframes=list(self.contexts),contexts={tf:dict(id=c['episode'],direction=c['direction'],available_at=c['available_at']) for tf,c in self.contexts.items()},authority_sha=None)
            template.update(self.runtime_config)
            template['baseline_source_receipts']=[dict(native_id=x['packet']['trade']['native_id'],payload_sha=x['packet']['trade']['payload_sha'],ack_path=str(self.recorder.j.root/'receipts'/('ack-'+x['manifest_sha256']+'.json')),ack_sha256=x['ack_sha256'],manifest_sha256=x['manifest_sha256'],available_at=x['available_by']) for x in capture['deliveries']]
            self.prepared,self.system=prepare_research_system(self.journal_path,template,capture,
                confirmed_cursor=trade.native_id,method_declared_at=self.declared_at)
            if self.system is None:raise Blocked('BASELINE_NOT_READY:'+self.prepared.reason)
            self.system.max_raw_events=self.max_r08_events;self.system.live_source=self;self.baseline_capture=capture
            self.integration=ContextTrendIntegration({tf:self.system for tf in self.contexts})
            b=self.prepared.config['baseline'];Q=sum(__import__('decimal').Decimal(t['quantity']) for t in b)
            span=__import__('decimal').Decimal(str((utc(b[-1]['trade_time'])-utc(b[0]['trade_time'])).total_seconds()))
            self.baseline_summary=dict(t_cut=self.prepared.t_cut,predecessor=trade.native_id,contributors=len(b),Q_BTC=str(Q),T_span_seconds=str(span),rate_BTC_per_second=str(Q/span),fixed_at=self.prepared.fixed_at,config_sha256=digest(self.system.j.state['config']))
            # This stamp is taken only AFTER the provider and native INIT commit
            # returned and all consumer dependencies above are installed. Reader
            # continues receiving; queued originals retain their receive clocks.
            self.system.begin_live_handoff(self.recorder.clock(),self.recorder.domain)
            self.log('LIVE_INIT_HANDOFF_READY',**dict(self.system.j.state['live_handoff']))
            self.log('BASELINE_FIXED',**self.baseline_summary)
            if getattr(self,'queue_handoff',False):self.recorder.dequeue()
            return
        if getattr(self,'queue_handoff',False):return self.drain_live()
        return self._ingest_delivery(d)
    def _ingest_delivery(self,d):
        self.current=d;raw=RawOccurrence.from_dict(d['packet']);trade=raw.trade
        cutoff=now()
        try:result=self.system.ingest(raw.packet(),cutoff)
        except Blocked as exc:
            if str(exc)=='RAW_AVAILABILITY':
                self.log('RAW_AVAILABILITY_REJECTED',event_id=trade.native_id,
                         ack_available_at=raw.available_at,cutoff=cutoff,
                         ack_minus_cutoff_us=(utc(raw.available_at)-utc(cutoff))//timedelta(microseconds=1),
                         call_site='RecorderLiveAdapter.accept:ResearchSystem.ingest/RawOccurrence.validate',
                         cutoff_source='datetime.now(timezone.utc).isoformat():R08_INGEST')
            raise
        snapshot=self.system.j.state;calculations={}
        for tf,t in snapshot['tf'].items():
            look=t['looks'][-1] if t['looks'] else None
            calculations[tf]=dict(result=look['result'] if look else None,participation=look.get('P') if look else None,
                role=t['role'],blocked=t['blocked'],baseline_rate=self.baseline_summary['rate_BTC_per_second'])
        handoff=snapshot.get('live_handoff')
        if handoff and result.get('status')=='PREACTIVATION_ACCOUNTED':
            self.log('PREACTIVATION_ACCOUNTED',native_id=trade.native_id,receive_clock=d['message_received'],
                     source_predecessor=raw.predecessor,count=handoff['preactivation_count'])
            return
        if handoff and handoff['first_eligible'] and handoff['first_eligible']['native_id']==trade.native_id:
            self.log('FIRST_ELIGIBLE_RECEIVE',**dict(handoff['first_eligible']))
        self.log('R08_INGEST',native_id=trade.native_id,native_result=result,calculations=calculations)
        errors={tf:v['blocked'] for tf,v in calculations.items() if v['blocked']}
        if errors:raise Blocked('R08_INPUT:'+json.dumps(errors))
        seeds={k:seg for k,seg in snapshot['economic'].items() if seg.get('kind')=='OBSERVED_SEED'}
        if seeds and self.s0_result is None:
            self.s0_result=seeds
            self.log('S0_CONFIRMED',seeds=seeds)
            if self.on_s0:self.on_s0()
        if not self.cycle_delivered and all(v['participation'] is not None for v in calculations.values()):
            for tf,c in self.contexts.items():
                identity=dict(timeframe=tf,canonical_episode_id=c['episode'],side=c['direction'],source_bar_open=c['target_open'],source_bar_close=c['target_close'])
                state=c.get('state',{})
                decision=EntryOnlyKillSwitch().evaluate_paper(identity,state,self.integration,cutoff).to_dict()
                self.last_decisions[tf]=decision
                self.log('EXECUTION_INPUT_RESULT',timeframe=tf,committed_R08_head=self.system.j.records[-1]['sha'],
                         calculations=calculations[tf],native_entry_result=decision)
            self.cycle_delivered=True
            if self.on_cycle:self.on_cycle()

    # UTC Spot intervals only. Kline volume never enters raw or baseline.
    INTERVALS={'M15':'15m','M30':'30m','H1':'1h','H4':'4h'}
    SECONDS={'M15':900,'M30':1800,'H1':3600,'H4':14400}
    def _observe_trade(self,out,trade):
        T=utc(trade.trade_time);a=trade.native_id
        f=out['mapping']['fields']['f']['value'];l=out['mapping']['fields']['l']['value']
        for tf,states in self.bars.items():
            sec=self.SECONDS[tf];opened=int(T.timestamp())//sec*sec
            b=states.get(opened)
            if b is None:
                # A bracket from the previous bar distinguishes an observed full
                # bar from the initial partial capture. No wall/exchange compare.
                covered_start=bool(self.last_source_T is not None and self.last_source_T.timestamp()<opened)
                b=states[opened]=dict(open=opened,first_a=a,last_a=a,first_f=f,last_l=l,
                    members=0,trades=0,continuous=True,observed_start=covered_start)
            if not b['members']:
                b.update(first_a=a,last_a=a,first_f=f,last_l=l,observed_start=bool(self.last_source_T is not None and self.last_source_T.timestamp()<opened))
            if b['members'] and (a!=b['last_a']+1 or f!=b['last_l']+1):b['continuous']=False
            b.update(last_a=a,last_l=l,members=b['members']+1,trades=b['trades']+l-f+1)
            seal=self.system.j.state['tf'][tf]['seal'] if self.system else None
            if seal:
                for old in list(states):
                    if old+sec<utc(seal).timestamp():states.pop(old)
            if len(states)>self.recorder.items:raise Blocked('LIVE_QUEUE_SCOPE_CAP')
        self.last_source_T=T
    def accept_kline(self,payload,*,stream,receipt):
        k=payload.get('k',{});inverse={v:t for t,v in self.INTERVALS.items()}
        tf=inverse.get(k.get('i'))
        if (payload.get('e')!='kline' or payload.get('s')!='BTCUSDT' or k.get('s')!='BTCUSDT'
                or tf not in self.bars or stream!='btcusdt@kline_'+k.get('i','')):
            raise Blocked('SPOT_KLINE_DOMAIN_OR_TF')
        if type(k.get('x')) is not bool:raise Blocked('SPOT_KLINE_CLOSED_FLAG')
        if not k['x']:return 'OPEN_KLINE_NO_EFFECT'
        if any(type(k.get(key)) is not int for key in ('t','T','f','L','n')):raise Blocked('SPOT_KLINE_INTEGER_FIELDS')
        duration=self.SECONDS[tf]*1000
        if k['t']%duration or k['T']!=k['t']+duration-1 or k['f']<0 or k['L']<k['f'] or k['n']!=k['L']-k['f']+1:
            raise Blocked('SPOT_KLINE_BAR_OR_RANGE')
        if (receipt['session']!=self.recorder.session or receipt['clock_domain']!=self.recorder.domain):
            raise Blocked('SPOT_KLINE_SESSION')
        opened=k['t']//1000;close=(k['T']+1)//1000;key=(tf,opened)
        identity=(k['t'],k['T'],k['f'],k['L'],k['n'])
        if key in self.close_seen:
            if self.close_seen[key]!=identity:raise Blocked('SPOT_KLINE_CLOSE_CONFLICT')
            return 'DUPLICATE_CLOSE_NO_EFFECT'
        self.close_seen[key]=identity
        b=self.bars[tf].setdefault(opened,dict(open=opened,members=0,trades=0,continuous=True,observed_start=False))
        b['close_input']=dict(tf=tf,open=opened,close=close,f=k['f'],L=k['L'],n=k['n'],receipt=receipt)
        self.log('SPOT_BAR_CLOSE_RECEIVED',timeframe=tf,open=opened,close=close,
                 session=receipt['session'],ACK_available_at=receipt['available_at'],raw_ref=receipt['native_ref'])
        if self.system is not None:self.drain_live()
        return 'CLOSE_RETAINED'
    def _coverage_ready(self,tf,opened,cutoff):
        b=self.bars[tf].get(opened,{})
        c=b.get('close_input')
        if c is None:return False,'WAITING_FOR_KLINE_CLOSE'
        if not b.get('observed_start'):return False,'INITIAL_PARTIAL_BAR'
        if not b.get('members'):return False,'WAITING_FOR_AGGTRADE_COVERAGE'
        if not b.get('continuous'):return False,'AGGTRADE_COVERAGE_DISCONTINUITY'
        if b['first_f']!=c['f']:return False,'BAR_HEAD_NOT_COVERED'
        if b['last_l']<c['L']:return False,'WAITING_FOR_AGGTRADE_TAIL'
        if b['last_l']!=c['L'] or b['trades']!=c['n']:return False,'BAR_TRADE_RANGE_CONFLICT'
        if utc(c['receipt']['available_at'])>utc(cutoff) or datetime.fromtimestamp(c['close'],timezone.utc)>utc(cutoff):
            return False,'WAITING_FOR_CLOSE_AVAILABILITY'
        return True,c
    def drain_live(self):
        while self.system is not None:
            with self.recorder.dispatch_condition:
                if not self.recorder.q:return 'DRAINED'
                item=self.recorder.q[0]
            if item.get('_dispatch_state') in ('RECEIVE_PENDING','PROCESSING'):return 'WAITING_FOR_INPUT_PROCESSING'
            d=item.get('r08_delivery')
            if d is None:raise Blocked('LIVE_QUEUE_PACKET_MISSING')
            raw=RawOccurrence.from_dict(d['packet']);state=self.system.j.state
            if raw.trade.source_key in state['raw']:
                if state['raw'][raw.trade.source_key]['trade']['payload_sha']!=raw.trade.payload_sha:raise Blocked('CONFLICTING_NATIVE_IDENTITY')
                self.recorder.dequeue();continue
            T=utc(raw.trade.trade_time);required=[];cutoff=now()
            for tf,t in state['tf'].items():
                if not t['prefix']:continue
                old=utc(state['raw'][t['prefix'][0]]['trade']['trade_time']);sec=self.SECONDS[tf]
                opened=int(old.timestamp())//sec*sec
                if int(T.timestamp())//sec==opened//sec:continue
                # Match the closing prefix bar, never the new event's bar.
                ready,info=self._coverage_ready(tf,opened,cutoff)
                if not ready:
                    if self.runtime_config and info=='INITIAL_PARTIAL_BAR':
                        bar=self.bars[tf][opened];close_input=bar['close_input']
                        actual=now();close=datetime.fromtimestamp(close_input['close'],timezone.utc).isoformat()
                        # Requires this bar's actual Spot close ACK, never a
                        # trade from the next bar alone. No verified seal.
                        if utc(close_input['receipt']['available_at'])>utc(actual) or utc(close)>utc(actual):return 'WAITING_FOR_CLOSE_AVAILABILITY'
                        key=(tf,opened)
                        if key not in self.partial_closed:
                            self.system.observed_partial_close(tf,close,actual);self.partial_closed.add(key)
                            self.log('INITIAL_PARTIAL_BAR_RETAINED',timeframe=tf,bar_open=opened,bar_close=close_input['close'],coverage='INCOMPLETE_CAPTURE_NOT_SEALED',ACK_available_at=close_input['receipt']['available_at'])
                        continue
                    marker=(opened,info)
                    if self.waiting.get(tf)!=marker:
                        self.waiting[tf]=marker
                        self.log('BAR_CLOSE_WAITING',timeframe=tf,bar_open=opened,bar_close=opened+sec,
                                 reason=info,pending_native_id=raw.trade.native_id,queue_depth=len(self.recorder.q))
                    return 'WAITING_FOR_COVERAGE'
                required.append((tf,info))
            for tf,info in required:
                close=datetime.fromtimestamp(info['close'],timezone.utc).isoformat()
                seal=self.system.j.state['tf'][tf]['seal']
                if seal is None or utc(seal)<utc(close):
                    # Fresh actual calculation time, after close ACK. No backdating.
                    actual=now();self.system.watermark(tf,close,actual,state['config']['coverage_ref'])
                    evidence=dict(timeframe=tf,bar_open=info['open'],bar_close=info['close'],
                        cutoff=actual,ACK_available_at=info['receipt']['available_at'],
                        coverage_ref=state['config']['coverage_ref'],native_ref=info['receipt']['native_ref'])
                    self.boundaries.append(evidence);self.log('BAR_CLOSE_COMMITTED',**evidence)
                self.waiting.pop(tf,None)
            self._ingest_delivery(d)
            self.recorder.dequeue()
        return 'DRAINED'
