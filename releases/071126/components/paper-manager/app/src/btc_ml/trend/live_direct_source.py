"""Read existing committed direct-source evidence; no grants or archive ingest."""
import hashlib,json
from pathlib import Path
from .trend_journal import Blocked
from .trend_evidence import RawOccurrence
from .trend_event import utc

def _signature(config,tf):
    from btc_ml.external_traders.context_phase_publication import _paths,HOME
    root=Path(config['paper_context_root'])
    files=[root/'data'/p for p in _paths(tf)]
    files += [root/'data/cognition/multi_timeframe_availability_memory.parquet',root/'data/cognition/market_context_lifecycle_memory.parquet',root/HOME/tf/'head.json',root/HOME/tf/'pending.json']
    result=[]
    for path in files:
        try:s=path.stat();result.append((str(path),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns))
        except FileNotFoundError:result.append((str(path),None))
    return tuple(result)

def cached_context_baseline(owner,config,tf,cutoff,verify):
    signature=_signature(config,tf);key=(tf,id(config))
    cache=getattr(owner,'_context_baseline_cache',{})
    prior=cache.get(key)
    if prior and prior[0]==signature and utc(prior[1])<=utc(cutoff):return
    result=verify()
    if _signature(config,tf)==signature:
        cache[key]=(signature,cutoff);owner._context_baseline_cache=cache
    return result

class CommittedDirectSource:
    """Facade over the SAME native C_E state and original Recorder receipts."""
    def __init__(self,system):self.system=system;self._baseline_config=None
    def fixed_baseline(self,config):
        actual=self.system.j.state['config']
        if actual is not config and actual!=config:raise Blocked('LIVE_BASELINE_BINDING')
        if self._baseline_config is actual:return
        refs={d['native_id']:d for d in config['baseline_source_receipts']}
        for trade in list(config['baseline'])+[{'native_id':config['predecessor']}]:
            ref=refs.get(trade['native_id'])
            if ref is None or (trade.get('payload_sha') and ref['payload_sha']!=trade['payload_sha']):raise Blocked('PAPER_BASELINE_SOURCE_NOT_PROVEN')
            data=Path(ref['ack_path']).read_bytes()
            if hashlib.sha256(data).hexdigest()!=ref['ack_sha256']:raise Blocked('PAPER_ORIGINAL_DELIVERY_RECEIPT_REQUIRED')
            ack=json.loads(data)
            if ack['manifest_sha']!=ref['manifest_sha256'] or utc(ack['observed_clock']['wall_utc'])>utc(config['baseline_available_at']):raise Blocked('PAPER_BASELINE_SOURCE_NOT_PROVEN')
        self._baseline_config=actual
    def paper_source(self,config,raw,cutoff):
        raw.validate(cutoff);saved=self.system.j.state['raw'].get(raw.trade.source_key)
        if not saved or {k:saved[k] for k in raw.packet()}!=raw.packet() or not saved.get('paper_authorized'):raise Blocked('PAPER_SOURCE_AUTHORITY_MISSING')
        ref=saved['source_delivery_ref'];root=Path(raw.coverage_ref).parent.parent
        data=(root/'receipts'/('ack-'+ref['manifest_sha256']+'.json')).read_bytes()
        if hashlib.sha256(data).hexdigest()!=ref['ack_sha256']:raise Blocked('PAPER_ORIGINAL_DELIVERY_RECEIPT_REQUIRED')
        return {'level':'OBSERVED','receipt_sha256':ref['ack_sha256'],'venue_completeness':'UNKNOWN_NOT_ASSERTED','aggressor_semantics':'PROJECT_MAPPING_ONLY / VENUE_UNQUALIFIED'}
    def context_baseline(self,config,tf,cutoff,verify):
        return cached_context_baseline(self,config,tf,cutoff,verify)
