"""Post-Lifecycle phase sidecar of the EXISTING native context publisher.

No market runtime or phase policy. Uses the cognitive atomic/fsync primitive and
existing post-write metadata IO. Archived classifications never gain LIVE status
from a fresh receipt. Source proofs and every phase ancestor must be native/new.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from btc_ml.runtime.cognitive_cycle import atomic, sync_dir
from btc_ml.trend.context_phase_qualification import (
    PinnedContextObservations, ContextPhaseQualifier, MINUTES, VERSION as PHASE_VERSION,
    M2_AMENDMENT, _clean, _hash, _time)

SCHEMA = 'CONTEXT_PHASE_POST_LIFECYCLE_PUBLICATION_V1'
HOME = Path('data/cognition/context_trend_phase_v1')
CLASSIFIER = Path(__file__).resolve().parents[1] / 'trend/context_phase_qualification.py'
PRODUCER = Path(__file__).resolve()


def _now(): return datetime.now(timezone.utc).isoformat()
def _bytes(value): return json.dumps(_clean(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def _sha(raw): return sha256(raw).hexdigest()
def _load(path): return json.loads(Path(path).read_bytes())
def _semantic(value):
    if isinstance(value, dict): return {k:_semantic(v) for k,v in value.items() if k != 'artifact_sha256'}
    if isinstance(value, (tuple,list)): return [_semantic(v) for v in value]
    return value


def _paths(tf):
    if tf not in MINUTES: raise ValueError('OWN_TF_REQUIRED')
    base = 'cognition/' + ('' if tf == 'M15' else 'timeframes/'+tf+'/')
    result = [base+name+'.parquet' for name in ('auction_episode_memory','cognitive_market_state_memory','final_market_context_memory','market_context_lifecycle_memory')]
    result.append('cognition/candle_structure_memory.parquet' if tf == 'M15' else base+'native_closed_candles.parquet')
    return result


def prepare_native_publication(root, stage, tf, lifecycle):
    """Called BEFORE native publish_completed, never creates a historical proof."""
    from btc_ml.external_traders.stage2_predecision_evidence import load_own_tf_decision_snapshot
    opened = pd.to_datetime(lifecycle.timestamp,utc=True).max()
    try: snapshot = load_own_tf_decision_snapshot(stage,tf,opened,validate_unpublished=True)
    except (OSError,ValueError,KeyError,TypeError): snapshot = None
    body = {'timeframe':tf,'opened':opened.isoformat(),'started_at':_now(),
            'root':str(Path(root).resolve()),'snapshot':snapshot}
    return body


def _new_native_target(witness, tf, opened, root):
    if not witness or witness.get('root') != str(Path(root).resolve()) or witness.get('timeframe') != tf:
        return False
    s = witness.get('snapshot')
    if (not s or s.get('schema')!='OWN_TF_PROCESSING_SNAPSHOT_V1'
            or not s.get('candidate_new') or s.get('candidate_reason') != 'NEW_UNPUBLISHED_CANDIDATE'): return False
    try:
        at, close = _time(opened), _time(opened)+pd.Timedelta(minutes=MINUTES[tf])
        original={k:v for k,v in s.items() if k not in ('snapshot_sha256','candidate_new','candidate_reason')}
        if _hash(original)!=s.get('snapshot_sha256'): return False
        history = s['history'][tf]
        # Missing/cleared histories cannot manufacture a new live generation.
        if not history['proven'] or history['tip'] is None or not at > _time(history['tip']): return False
        if at != _time(witness['opened']) or s['history_root'] != str(Path(root).resolve()): return False
        if close != _time(s['market_data_cutoff']).floor(str(MINUTES[tf])+'min'): return False
        return close <= _time(s['decision_as_of']) <= _time(witness['started_at']) <= _time(witness['source_publication_completed_at'])
    except (KeyError,ValueError,TypeError): return False


def _json_receipt(receipt, destination):
    from stage2_publication_metadata import _json_at
    _json_at(receipt,destination)  # Existing post-write atomic metadata primitive.


def publish_context_phase(root, tf, *, source_witness=None, scope='ISOLATED', market='BINANCE_SPOT', instrument='BTCUSDT'):
    """Only invoked by the existing completed-context publisher or isolated test.

    Snapshot files below this sidecar are evidence, never inputs to a new market
    producer. Generation/head belong to the same own-TF publication call.
    """
    if scope not in ('NATIVE_RUNTIME','ISOLATED'): raise ValueError('PUBLICATION_SCOPE')
    root=Path(root).resolve();folder=root/HOME/tf;folder.mkdir(parents=True,exist_ok=True)
    with (folder/'writer.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        return _publish_locked(root,tf,folder,source_witness,scope,market,instrument)


def calculate_phase_history(observations, tf, phase_as_of):
    """Same complete replay, one deep history copy; no classifier/state shortcut."""
    qualifier=ContextPhaseQualifier(observations,m2_w1_r1=True)
    final,_=observations._frame(_paths(tf)[2])
    if set(final.timeframe.astype(str))!={tf}:
        if tf!='M15' or observations.legacy_m15_owner is None:raise ValueError('PHASE_FINAL_OWNER')
        observations.legacy_m15_owner.verify_files()
        observations.legacy_m15_owner.validate_frame(final,'final')
    opened=pd.to_datetime(final.timestamp,utc=True).sort_values()
    results=[qualifier.process(tf,t.isoformat(),phase_as_of) for t in opened]
    if not results or not results[-1].get('bar_open'):raise ValueError('PHASE_TARGET_UNAVAILABLE')
    packet=observations.read(tf,results[-1]['bar_open'],phase_as_of)
    events=qualifier.history
    # All original event forms (including BREAK) bind the emitting source rows.
    # Derive the target delta once; never copy every growing prefix per bar.
    target_events=[e for e in events if e.get('sources',e.get('source_rows'))==packet['sources']]
    return {'results':results,'events':events,'target_events':target_events},packet


def _publish_locked(root,tf,folder,witness,scope,market,instrument):
    classifier_sha=_sha(CLASSIFIER.read_bytes());producer_sha=_sha(PRODUCER.read_bytes())
    raw={rel:(root/'data'/rel).read_bytes() for rel in _paths(tf)}
    pins={rel:_sha(b) for rel,b in raw.items()}
    from btc_ml.trend.legacy_m15_phase_owner import load_owner
    owner=load_owner(root) if tf=='M15' else None
    # Same activated generation + freshly verified identical bytes: validate
    # the retained proof and return it, without replay or re-publication clocks.
    pending_path=folder/'pending.json'
    pending=_load(pending_path) if pending_path.exists() else None
    if pending is not None:
        if (pending.get('schema')!=SCHEMA or pending.get('sources')!=pins
                or pending.get('timeframe')!=tf or pending.get('scope')!=scope
                or pending.get('market')!=market or pending.get('instrument')!=instrument
                or pending.get('classifier_sha256')!=classifier_sha
                or pending.get('producer_sha256')!=producer_sha):
            raise ValueError('PHASE_PENDING_RECOVERY_INPUT_CONFLICT')
        # Recovery retains the original calculation clock and source witness.
        # A later caller clock cannot promote an interrupted archived decision.
        witness=pending['witness']
    head_path=folder/'head.json'
    if not head_path.exists() and pending is None and (
            any((folder/'generations').glob('*')) or any((folder/'bars').glob('*.json'))):
        raise ValueError('PHASE_HEAD_MISSING_WITH_RETAINED_HISTORY')
    if head_path.exists() and pending is None:
        pointer=_load(head_path);prior_folder=folder/'generations'/pointer['generation_id']
        prior_manifest=_load(prior_folder/'manifest.json')
        if (prior_manifest['sources']==pins and prior_manifest['scope']==scope
                and prior_manifest['market']==market and prior_manifest['instrument']==instrument
                and prior_manifest.get('legacy_m15_owner')==(owner.identity() if owner else None)):
            prior=_verified_generation(root,tf,pointer)
            slots=folder/'bars';tip=_time(prior['manifest']['target_bar_open']).strftime('%Y%m%dT%H%M%SZ')
            if any(p.stem>tip for p in slots.glob('*.json')):raise ValueError('PHASE_HEAD_BEHIND_IMMUTABLE_HISTORY')
            return {'status':'UNCHANGED','generation_id':pointer['generation_id'],'receipt_sha256':pointer['receipt_sha256']}
    # A private input snapshot: no classifier sees a mixed concurrent generation.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='.phase-input-',dir=folder) as name:
        source=Path(name)
        for rel,b in raw.items(): atomic(source/rel,b)
        observations=PinnedContextObservations(source,pins,market=market,instrument=instrument,legacy_m15_owner=owner)
        phase_as_of=pending['phase_as_of'] if pending else _now()  # Fixed before classifier; retained on recovery.
        analysis,packet=calculate_phase_history(observations,tf,phase_as_of)
        target=analysis['results'][-1]
    # Actual activated files must still be those measured by this publication.
    if any(_sha((root/'data'/rel).read_bytes())!=h for rel,h in pins.items()): raise ValueError('CONTEXT_CHANGED_DURING_PHASE_CALCULATION')
    semantic=_hash(_semantic(analysis))
    # Processing clocks do not create a second publication of unchanged input.
    identity=_hash({'schema':SCHEMA,'tf':tf,'market':market,'instrument':instrument,
                    'target':target['bar_open'],'semantic':_semantic_without_clock(analysis),
                    'classifier_sha256':classifier_sha,'producer_sha256':producer_sha,'scope':scope})
    head_path=folder/'head.json';actual_head=_load(head_path) if head_path.exists() else None
    head=pending['parent_generation'] if pending else actual_head
    if pending and (identity!=pending['generation_id'] or _sha(_bytes(analysis))!=pending['analysis_sha256']):
        raise ValueError('PHASE_PENDING_REPLAY_CONFLICT')
    slot=folder/'bars'/(_time(target['bar_open']).strftime('%Y%m%dT%H%M%SZ')+'.json')
    if slot.exists() and pending is None:
        previous=_load(slot)
        if previous['generation_id'] != identity: raise ValueError('CONFLICTING_CONTEXT_PHASE_GENERATION')
        _verified_generation(root,tf,previous)
        if head != previous: raise ValueError('HISTORICAL_PHASE_GENERATION_NOT_CURRENT')
        return {'status':'UNCHANGED','generation_id':identity,'receipt_sha256':previous['receipt_sha256']}
    if head:
        prior=_verified_generation(root,tf,head)
        if _time(target['bar_open']) <= _time(prior['manifest']['target_bar_open']): raise ValueError('PHASE_HISTORY_REPAINT')
        tip=_time(prior['manifest']['target_bar_open']).strftime('%Y%m%dT%H%M%SZ')
        if pending is None and any(p.stem>tip for p in (folder/'bars').glob('*.json')):
            raise ValueError('PHASE_HEAD_BEHIND_IMMUTABLE_HISTORY')
    gen=folder/'generations'/identity
    if gen.exists() and pending is None: raise ValueError('INCOMPLETE_OR_CONFLICTING_PHASE_GENERATION')
    analysis_raw=_bytes(analysis)
    if pending is None:
        pending={'schema':SCHEMA,'generation_id':identity,'parent_generation':head,
                 'timeframe':tf,'sources':pins,'scope':scope,'market':market,'instrument':instrument,
                 'classifier_sha256':classifier_sha,'producer_sha256':producer_sha,
                 'phase_as_of':phase_as_of,'witness':witness,'analysis_sha256':_sha(analysis_raw)}
        atomic(pending_path,_bytes(pending))
    gen.mkdir(parents=True,exist_ok=True)
    for rel,b in raw.items(): _retain(gen/'sources'/rel,b)
    _retain(gen/'phase.json',analysis_raw)
    snapshot=witness.get('snapshot') if witness else None
    admission=bool(scope=='NATIVE_RUNTIME' and _new_native_target(witness,tf,target['bar_open'],root))
    phase_event=_context_event(target,analysis['events'])
    manifest={'schema':SCHEMA,'generation_id':identity,'parent_generation':head,
              'market':market,'instrument':instrument,'timeframe':tf,
              'canonical_context_episode_id':target.get('final_context_episode_id'),
              'direction':target.get('direction'),'target_bar_open':target['bar_open'],
              'target_bar_close':target['bar_close'],'phase_event_id':phase_event.get('event_id'),
              'previous_event_id':phase_event.get('previous_event_id'),
              'target_phase_event_ids':[e['event_id'] for e in analysis['target_events']],
              'sources':pins,'target_source_rows':packet['sources'],
              'source_observation_ids':packet['source_observation_ids'],
              'analysis_sha256':_sha(analysis_raw),'analysis_semantic_sha256':semantic,
              'producer':str(PRODUCER.name),'producer_sha256':producer_sha,
              'classifier_sha256':classifier_sha,'phase_contract':PHASE_VERSION,'amendment':M2_AMENDMENT,
              'scope':scope,'source_admission':'NATIVE_NEW_TARGET' if admission else 'RESEARCH_ONLY',
              'native_publication_witness':witness,
              'source_publisher_sha256':_sha(Path(__file__).with_name('incremental_context_publication.py').read_bytes()),'context_decision_as_of':snapshot.get('decision_as_of') if snapshot else None,
              'phase_calculation_as_of':phase_as_of,'source_observation_available_at':packet['source_availability_at']}
    if owner:
        manifest['legacy_m15_owner']=owner.identity()
        for name,b in owner.verify_files().items():_retain(gen/'legacy_owner'/name,b)
    _retain(gen/'manifest.json',_bytes(manifest))
    receipt_path=gen/'receipt.meta.json'
    if receipt_path.exists():
        receipt=_load(receipt_path)
        if (receipt.get('schema')!=SCHEMA or receipt.get('generation_id')!=identity
                or receipt.get('manifest_sha256')!=_sha((gen/'manifest.json').read_bytes())
                or receipt.get('phase_sha256')!=_sha(analysis_raw) or receipt.get('scope')!=scope
                or receipt.get('timestamp_kind')!='POST_WRITE_COMPLETION_CONFIRMATION'
                or receipt.get('first_historical_publication_at') is not None
                or receipt.get('decision_available_from')!=receipt.get('publication_completed_at')
                or _time(receipt['publication_completed_at'])<_time(phase_as_of)):
            raise ValueError('PHASE_RECOVERY_RECEIPT_CONFLICT')
    else:
        completed=_now()  # New post-write clock; never reconstruct a lost completion.
        receipt={'schema':SCHEMA,'generation_id':identity,'manifest_sha256':_sha((gen/'manifest.json').read_bytes()),
                 'phase_sha256':_sha(analysis_raw),'publication_completed_at':completed,
                 'decision_available_from':completed,'timestamp_kind':'POST_WRITE_COMPLETION_CONFIRMATION',
                 'first_historical_publication_at':None,'scope':scope}
        _json_receipt(receipt,receipt_path)
    pointer={'generation_id':identity,'receipt_sha256':_sha(receipt_path.read_bytes())}
    if actual_head not in (head,pointer): raise ValueError('PHASE_RECOVERY_HEAD_CONFLICT')
    _retain(slot,_bytes(pointer))
    if actual_head!=pointer:atomic(head_path,_bytes(pointer))
    # Pending masks both old and new heads until actual activation is confirmed.
    # Existing completion bytes are immutable; a missing completion is measured NOW.
    if not (gen/'activation.meta.json').exists():
        activation={'schema':SCHEMA,'generation_id':identity,'pointer':pointer,
                    'head_sha256':_sha(head_path.read_bytes()),
                    'publication_completed_at':_now(),'timestamp_kind':'POST_HEAD_ACTIVATION_CONFIRMATION'}
        activation['activation_sha256']=_hash(activation)
        _json_receipt(activation,gen/'activation.meta.json')
    _verified_generation(root,tf,pointer)
    pending_path.unlink();sync_dir(folder)
    return {'status':'CREATED','generation_id':identity,'receipt_sha256':pointer['receipt_sha256'],
            'context_trend_phase':target['context_trend_phase'],'scope':scope,'source_admission':manifest['source_admission']}


def _retain(path,raw):
    """Complete only this reserved transaction; never overwrite evidence."""
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('PHASE_RECOVERY_IMMUTABLE_CONFLICT')
    else:atomic(path,raw)


def _semantic_without_clock(value):
    if isinstance(value,dict): return {k:_semantic_without_clock(v) for k,v in value.items() if k not in ('decision_as_of','artifact_sha256')}
    if isinstance(value,(list,tuple)): return [_semantic_without_clock(x) for x in value]
    return value


def _context_event(result,events):
    scope=(result['timeframe'],result.get('final_context_episode_id'),result.get('direction'))
    for event in reversed(events):
        own=(event.get('timeframe'),event.get('final_context_episode_id'),event.get('direction'))
        if own==scope or tuple(event.get('closed_scope',()))==scope:
            return event
    return {}


def _verified_generation(root,tf,pointer):
    ident=pointer['generation_id']
    if not isinstance(ident,str) or len(ident)!=64 or any(c not in '0123456789abcdef' for c in ident): raise ValueError('PHASE_GENERATION_ID')
    gen=Path(root)/HOME/tf/'generations'/ident
    receipt_raw=(gen/'receipt.meta.json').read_bytes()
    if _sha(receipt_raw)!=pointer['receipt_sha256']: raise ValueError('PHASE_RECEIPT_SHA')
    receipt=json.loads(receipt_raw);manifest_raw=(gen/'manifest.json').read_bytes();m=json.loads(manifest_raw)
    phase_raw=(gen/'phase.json').read_bytes();analysis=json.loads(phase_raw)
    if (receipt['schema']!=SCHEMA or m['schema']!=SCHEMA or m['generation_id']!=ident
            or receipt['generation_id']!=ident or m['timeframe']!=tf
            or receipt['manifest_sha256']!=_sha(manifest_raw)
            or receipt['phase_sha256']!=_sha(phase_raw) or m['analysis_sha256']!=_sha(phase_raw)
            or receipt['timestamp_kind']!='POST_WRITE_COMPLETION_CONFIRMATION'
            or receipt['scope']!=m['scope'] or receipt['first_historical_publication_at'] is not None):
        raise ValueError('PHASE_MANIFEST_IDENTITY')
    if (m.get('phase_contract')!=PHASE_VERSION or m.get('amendment')!=M2_AMENDMENT
            or m.get('source_publisher_sha256')!=_sha(Path(__file__).with_name('incremental_context_publication.py').read_bytes())):
        raise ValueError('PHASE_SOURCE_PUBLISHER_VERSION')
    if m['classifier_sha256']!=_sha(CLASSIFIER.read_bytes()) or m['producer_sha256']!=_sha(PRODUCER.read_bytes()): raise ValueError('PHASE_PRODUCER_VERSION')
    if set(m['sources'])!=set(_paths(tf)): raise ValueError('PHASE_SOURCE_CATALOG')
    for rel,h in m['sources'].items():
        if _sha((gen/'sources'/rel).read_bytes())!=h: raise ValueError('PHASE_SOURCE_SHA')
    expected_id=_hash({'schema':SCHEMA,'tf':tf,'market':m['market'],'instrument':m['instrument'],
        'target':m['target_bar_open'],'semantic':_semantic_without_clock(analysis),
        'classifier_sha256':m['classifier_sha256'],'producer_sha256':m['producer_sha256'],'scope':m['scope']})
    if expected_id!=ident or m['analysis_semantic_sha256']!=_hash(_semantic(analysis)):
        raise ValueError('PHASE_GENERATION_CONTENT_IDENTITY')
    result=analysis['results'][-1];phase_event=_context_event(result,analysis['events'])
    if (result['timeframe']!=tf or result['bar_open']!=m['target_bar_open']
            or result['bar_close']!=m['target_bar_close']
            or (result.get('market'),result.get('instrument'))!=(m['market'],m['instrument'])
            or result['decision_as_of']!=m['phase_calculation_as_of']
            or result.get('final_context_episode_id')!=m['canonical_context_episode_id']
            or result.get('direction')!=m['direction'] or phase_event.get('event_id')!=m['phase_event_id']
            or phase_event.get('previous_event_id')!=m['previous_event_id']
            or [e['event_id'] for e in analysis['target_events']]!=m['target_phase_event_ids']):
        raise ValueError('PHASE_ROW_IDENTITY')
    owner=None
    if m.get('legacy_m15_owner') is not None:
        from btc_ml.trend.legacy_m15_phase_owner import LegacyM15Owner
        if tf!='M15':raise ValueError('LEGACY_OWNER_WRONG_TF')
        owner=LegacyM15Owner(gen/'legacy_owner')
        if m['legacy_m15_owner']!=owner.identity():raise ValueError('LEGACY_OWNER_MANIFEST_IDENTITY')
    observations=PinnedContextObservations(gen/'sources',m['sources'],market=m['market'],instrument=m['instrument'],legacy_m15_owner=owner)
    packet=observations.read(tf,result['bar_open'],m['phase_calculation_as_of'])
    if (packet['sources']!=m['target_source_rows']
            or packet['source_observation_ids']!=m['source_observation_ids']
            or packet['source_availability_at']!=m['source_observation_available_at']):
        raise ValueError('PHASE_SOURCE_ROW_IDENTITY')
    if not _time(packet['source_availability_at'])<=_time(m['phase_calculation_as_of'])<=_time(receipt['publication_completed_at']): raise ValueError('NONCAUSAL_PHASE_PUBLICATION')
    witness=m.get('native_publication_witness')
    if witness and witness.get('source_publication_completed_at') and _time(witness['source_publication_completed_at'])>_time(m['phase_calculation_as_of']):
        raise ValueError('PHASE_BEFORE_CONTEXT_PUBLICATION')
    if receipt['decision_available_from']!=receipt['publication_completed_at']: raise ValueError('PHASE_AVAILABLE_CLOCK')
    slot=Path(root)/HOME/tf/'bars'/(_time(m['target_bar_open']).strftime('%Y%m%dT%H%M%SZ')+'.json')
    if _load(slot)!=pointer: raise ValueError('PHASE_GENERATION_NOT_ACTIVATED')
    activation=_load(gen/'activation.meta.json')
    if (activation.get('schema')!=SCHEMA or activation.get('generation_id')!=ident
            or activation.get('pointer')!=pointer
            or activation.get('head_sha256')!=_sha(_bytes(pointer))
            or activation.get('timestamp_kind')!='POST_HEAD_ACTIVATION_CONFIRMATION'
            or activation.get('activation_sha256')!=_hash({k:v for k,v in activation.items() if k!='activation_sha256'})
            or _time(activation['publication_completed_at'])<_time(receipt['publication_completed_at'])):
        raise ValueError('PHASE_ACTIVATION_RECEIPT')
    return {'manifest':m,'receipt':receipt,'activation':activation,'analysis':analysis,'result':result,'pointer':pointer,'legacy_owner':owner}


def verify_consumer_clock(manifest,receipt,activation,consumer_as_of):
    """Pure clock relation, NOT a source/phase/LIVE permission or clock creator."""
    phase=_time(manifest['phase_calculation_as_of'])
    payload=_time(receipt['publication_completed_at'])
    active=_time(activation['publication_completed_at'])
    consumer=_time(consumer_as_of)
    if not phase<=payload<=active:raise ValueError('NONCAUSAL_PHASE_CLOCK_ORDER')
    if active>consumer:raise ValueError('PHASE_PUBLICATION_AFTER_DECISION')
    witness=manifest.get('native_publication_witness') or {}
    source=witness.get('source_publication_completed_at')
    decision=manifest.get('context_decision_as_of')
    if source is not None:
        if _time(source)>phase:raise ValueError('PHASE_BEFORE_CONTEXT_PUBLICATION')
        if decision is not None:
            snapshot=witness.get('snapshot') or {}
            if decision!=snapshot.get('decision_as_of'):raise ValueError('CONTEXT_DECISION_CLOCK_UNBOUND')
            if _time(decision)>_time(source):raise ValueError('CONTEXT_PUBLICATION_BEFORE_DECISION')
    elif decision is not None:raise ValueError('CONTEXT_PUBLICATION_CLOCK_NOT_PROVEN')
    return {'consumer_as_of':consumer.isoformat(),'context_decision_as_of':decision,
            'phase_calculation_as_of':manifest['phase_calculation_as_of']}


def verify_live_context_phase(root,tf,state,cutoff,*,market='BINANCE_SPOT',instrument='BTCUSDT'):
    """Read-only, fail-closed lineage verifier. Never reclassifies Research as LIVE.

    Native/current source admission alone is insufficient: every event ancestor
    must have a genuine native new-target receipt. A research seed cannot qualify.
    """
    root=Path(root).resolve();folder=root/HOME/tf
    if (folder/'pending.json').exists():raise ValueError('PHASE_PUBLICATION_PENDING')
    head=_load(folder/'head.json');current=_verified_generation(root,tf,head)
    tip=_time(current['manifest']['target_bar_open'])
    slot=folder/'bars'/(tip.strftime('%Y%m%dT%H%M%SZ')+'.json')
    if _load(slot)!=head: raise ValueError('PHASE_HEAD_SLOT_CONFLICT')
    if any(p.stem>tip.strftime('%Y%m%dT%H%M%SZ') for p in (folder/'bars').glob('*.json')):
        raise ValueError('PHASE_HEAD_BEHIND_IMMUTABLE_HISTORY')
    m,receipt,r=current['manifest'],current['receipt'],deepcopy(current['result'])
    if (m['market'],m['instrument'])!=(market,instrument): raise ValueError('PHASE_MARKET_INSTRUMENT_BINDING')
    consumer_clocks=verify_consumer_clock(m,receipt,current['activation'],cutoff)
    if (state.get('timeframe')!=tf or state.get('lifecycle_episode_id')!=m['canonical_context_episode_id']
            or state.get('timeframe_direction')!=m['direction']
            or _time(state.get('source_bar_open'))!=_time(m['target_bar_open'])
            or _time(state.get('source_bar_close'))!=_time(m['target_bar_close'])): raise ValueError('PHASE_TARGET_BINDING')
    # Current context rows must match; another TF's shared-file append is allowed.
    pins={rel:_sha((root/'data'/rel).read_bytes()) for rel in _paths(tf)}
    packet=PinnedContextObservations(root/'data',pins,market=m['market'],instrument=m['instrument'],legacy_m15_owner=current['legacy_owner']).read(tf,m['target_bar_open'],cutoff)
    if {k:v['source_row_sha'] for k,v in packet['sources'].items()}!={k:v['source_row_sha'] for k,v in m['target_source_rows'].items()}: raise ValueError('CURRENT_CONTEXT_PHASE_SOURCE_CONFLICT')
    native=(m['scope']=='NATIVE_RUNTIME' and m['source_admission']=='NATIVE_NEW_TARGET'
            and _new_native_target(m['native_publication_witness'],tf,m['target_bar_open'],root))
    previous_id=(r.get('event') or {}).get('previous_event_id')
    cursor=m.get('parent_generation');seen=set();child_tip=_time(m['target_bar_open']);last_receipt_time=_time(current['activation']['publication_completed_at'])
    while cursor:
        ident=cursor['generation_id']
        if ident in seen: raise ValueError('PHASE_PARENT_CYCLE')
        seen.add(ident);parent=_verified_generation(root,tf,cursor);pm=parent['manifest']
        if not _time(pm['target_bar_open'])<child_tip: raise ValueError('PHASE_PARENT_ORDER')
        child_tip=_time(pm['target_bar_open'])
        if _time(parent['activation']['publication_completed_at'])>last_receipt_time: raise ValueError('PHASE_PARENT_CLOCK')
        last_receipt_time=_time(parent['activation']['publication_completed_at'])
        pe=parent['result'].get('event') or {}
        if previous_id and pe.get('event_id')==previous_id:
            native = native and pm['scope']=='NATIVE_RUNTIME' and pm['source_admission']=='NATIVE_NEW_TARGET' and _new_native_target(pm['native_publication_witness'],tf,pm['target_bar_open'],root)
            if (pm['canonical_context_episode_id'],pm['direction'],pm['market'],pm['instrument'])!=(m['canonical_context_episode_id'],m['direction'],m['market'],m['instrument']): raise ValueError('PHASE_PARENT_SCOPE')
            previous_id=pe.get('previous_event_id')
        cursor=pm.get('parent_generation')
    if previous_id: native=False  # Missing original phase ancestor receipt; never bootstrap it.
    qualified=bool(native and r.get('current_evidence') and r.get('event'))
    r.update(qualification='LIVE_QUALIFIED' if qualified else 'RESEARCH_OBSERVED',
             publication_qualification='LIVE_QUALIFIED' if qualified else 'NOT_PROVEN',
             publication_reason='NATIVE_PUBLICATION_CHAIN_VERIFIED' if qualified else 'NATIVE_NEW_SOURCE_OR_PHASE_ANCESTRY_NOT_PROVEN',
             generation_id=head['generation_id'],publication_receipt=receipt,
             source_publication_ref=head,publication_completed_at=current['activation']['publication_completed_at'],
             decision_available_from=current['activation']['publication_completed_at'],
             **consumer_clocks,
             publication_activation=current['activation'],
             live_blocker=None if qualified else 'NATIVE_NEW_SOURCE_OR_PHASE_ANCESTRY_NOT_PROVEN')
    # Do not return a view straddling a concurrent activation.
    if (folder/'pending.json').exists() or _load(folder/'head.json')!=head:
        raise ValueError('PHASE_CHANGED_DURING_CONSUMPTION')
    # No ALLOW is persisted. Existing entry guard must evaluate the phase again.
    return r


class PublishedContextPhaseReader:
    """Existing attachment's read-only phase source, not a runtime or publisher."""
    def __init__(self,root): self.root=Path(root).resolve()
    def read(self,tf,state,cutoff):
        try: return verify_live_context_phase(self.root,tf,state,cutoff)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            return {'context_trend_phase':'NOT_PROVEN','qualification':'NOT_PROVEN','current_evidence':False,
                    'reason':str(exc),'context_veto':'BLOCK','publication_qualification':'NOT_PROVEN'}
