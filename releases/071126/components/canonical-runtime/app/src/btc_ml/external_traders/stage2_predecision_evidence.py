"""R07.2a read-only evidence before Lifecycle publication; not a decision gate.

`stage` is an existing R07.1 frozen source bundle plus the candidate Final file.
The caller pins the complete Final row SHA from its own Final builder. This SHA
binds identity, not approval or proof of historical Final publication. No wall
clock, writer, default context, receipt synthesis or Lifecycle input is used.
"""
from pathlib import Path

import pandas as pd

from btc_ml.external_traders import context_stage2_evidence as E


def read_predecision_evidence(stage, tf, opened, *, expected_final_row_sha256, validate_unpublished=True, _history_cache=None):
    if tf not in E.TF_MINUTES:
        raise ValueError("UNKNOWN_TIMEFRAME")
    opened = E._time(opened)
    if opened is None or opened != opened.floor(str(E.TF_MINUTES[tf]) + "min"):
        raise ValueError("INVALID_CONTEXT_BAR")
    final = E._own_row(pd.read_parquet(Path(stage) / E.final_path(tf)), tf, opened)
    actual_hash = E._row_hash(final)
    if actual_hash != expected_final_row_sha256:
        raise ValueError("FINAL_IDENTITY_MISMATCH")
    close = opened + pd.Timedelta(minutes=E.TF_MINUTES[tf])
    for field, expected in (("source_bar_open", opened), ("source_bar_close", close)):
        if field in final and E._time(final[field]) != expected:
            raise ValueError("CONFLICTING_FINAL_BAR_BINDING")
    if not isinstance(final.get("builder_version"), str) or not final.builder_version:
        raise ValueError("FINAL_VERSION_MISSING")
    observations = {}
    # Re-read actual bytes and original receipts, never a caller-supplied admitted cache.
    sources = E.load_sources(stage)
    for key, source in sources.items():
        item = E._observation(source, close)
        if tf == "M15" and key in ("runtime", "composite") and item.get("source_observation_timestamp"):
            age = opened - E._time(item["source_observation_timestamp"])
            item["native_m15_asof_freshness"] = {
                "status": "STALE" if age > pd.Timedelta(minutes=45) else "WITHIN_NATIVE_MAX_AGE",
                "age_seconds": age.total_seconds(), "max_age_seconds": 2700,
                "contract": "build_auction_episode_memory.py::build_auction_episode_rows::_asof_cols",
                "applies_to": ["trigger_event", "location_bias"], "diagnostic_only": True}
        item["own_timeframe_confirmation"] = (item["status"] == "GENUINE_CANONICAL_EVIDENCE"
                                                and item.get("source_timeframe") == tf)
        observations[key] = item
    E.bind_meta_target_inputs(sources, observations, tf, close)
    decision_context=load_own_tf_decision_snapshot(stage,tf,opened,validate_unpublished=validate_unpublished, _history_cache=_history_cache)
    own = E.load_tf_native_evidence(stage, tf, opened, decision_context=decision_context)
    if own is not None:
        observations['own_tf_stage2'] = own
    body = {"schema": "STAGE2_PREDECISION_EVIDENCE_V1",
            "binding": {"timeframe": tf, "bar_open": opened.isoformat(), "bar_close": close.isoformat(),
                        "final_row_sha256": actual_hash, "final_builder_version": final.builder_version,
                        "market_context": E._value(final.get("market_context")),
                        "historical_context_publication_authority": "NOT_PROVEN"},
            "observations": observations,
            "use": "ASSESSMENT_ONLY_NO_DECISION_OR_TRADING_AUTHORITY"}
    if decision_context is not None:body['own_tf_decision_snapshot']=decision_context
    return {**body, "evidence_set_sha256": E._sha(E._bytes(body))}


def read_postpublication_assessment(root, stage, tf, opened, *, expected_final_row_sha256):
    """Keep the installed strict post-reader; also prove the same source view.

    A changed snapshot cannot silently replace an immutable first-delivery sidecar.
    Missing Lifecycle still fails in the original post-publication reader.
    """
    from btc_ml.external_traders.stage2_semantic_assessment import assess_stage2
    pre = read_predecision_evidence(stage, tf, opened,
                                   expected_final_row_sha256=expected_final_row_sha256,validate_unpublished=False)
    post = E.read_context_evidence(root, tf, opened)
    if post["binding"]["final_row_sha256"] != pre["binding"]["final_row_sha256"]:
        raise ValueError("FINAL_IDENTITY_MISMATCH")
    if E._bytes(post["observations"]) != E._bytes(pre["observations"]):
        raise ValueError("PRE_POST_SOURCE_EVIDENCE_MISMATCH")
    return assess_stage2(pre)

# R07.2c: structured native inputs and an audit of their actual consumption.
# No assessment/classifier is called and no native conclusion changes a decision.
NATIVE_CONCLUSION_SOURCES = ('runtime', 'mtf', 'synthesis', 'probabilistic', 'reinforcement', 'meta', 'convergence')
ALREADY_AUCTION_FIELDS = frozenset({'trigger_event', 'location_bias', 'tier1_trigger_event',
    'tier1_location_bias', 'localized_behavior', 'volume_event', 'climax_state', 'effort_result_state'})
FINAL_DECISION_FIELDS = ('market_context', 'context_status', 'context_reason', 'state_direction',
    'cognitive_market_state', 'state_status', 'living_process', 'process_strength', 'action_allowed')
LIFECYCLE_DECISION_FIELDS = ('raw_market_context', 'raw_context_status', 'active_market_context',
    'lifecycle_state', 'candidate_context', 'challenge_context', 'invalidation_type', 'invalidation_reason',
    'transition_reason', 'transition_block_reason', 'living_process', 'process_strength', 'action_allowed')


def decision_fields(row, fields):
    result = {}
    for name in fields:
        value = row.get(name)
        # Native nullable categorical columns round-trip None as NaN/NaT.
        # Canonicalize only those nulls; numeric qualifiers are never changed.
        if name not in ('process_strength', 'action_allowed') and not isinstance(value, (dict, list, tuple)):
            if value is None or value is pd.NA or value is pd.NaT or pd.isna(value):
                value = None
        result[name] = E._value(value)
    return result


def lifecycle_conclusions_reader(stage, final_frame, *, previous_tip=None):
    """Supply the same R072a reader before native Lifecycle, never a future ID.

    Review new publication candidates; on an unchanged/initial historical tree
    review only its current tip. Old history is not assigned new source knowledge.
    """
    frame = final_frame.copy()
    if frame.empty:
        return lambda row: None
    times = pd.to_datetime(frame.timestamp, utc=True)
    selected = times.loc[times > E._time(previous_tip)] if previous_tip is not None else times.iloc[0:0]
    if selected.empty:
        selected = times.tail(1)
    selected = set(selected)
    views = {}
    # Cache only decoded history identities within this reader. Every use
    # still reads and hashes the current bytes; changed content is reparsed.
    history_cache = {}

    def reader(row):
        opened = E._time(row.get('timestamp'))
        if opened not in selected:
            return None
        tf = str(row.get('timeframe'))
        expected = E._own_row(frame, tf, opened)
        expected_sha = E._row_hash(expected)
        # Lifecycle augments Final with auction/freshness columns. The original
        # Final columns must still be the exact input, not just equal direction.
        if E._row_hash(row.reindex(expected.index)) != expected_sha:
            raise ValueError('CONSUMER_FINAL_INPUT_IDENTITY_MISMATCH')
        key = (tf, opened)
        if key not in views:
            views[key] = read_predecision_evidence(stage, tf, opened,
                                                   expected_final_row_sha256=expected_sha, _history_cache=history_cache)
        return views[key]
    return reader


def consume_native_conclusions(evidence, final_row, *, consumer):
    """Called IN the native Lifecycle function BEFORE step_lifecycle.

    Native values are actually inspected and accepted as structured input. The
    existing reducers have no handling of these conclusions: decision use is an
    empty list, not a fabricated success, opposite direction or mandatory gate.
    """
    from datetime import datetime, timezone
    body = {k: v for k, v in evidence.items() if k != 'evidence_set_sha256'}
    if (body.get('schema') != 'STAGE2_PREDECISION_EVIDENCE_V1'
            or E._sha(E._bytes(body)) != evidence.get('evidence_set_sha256')):
        raise ValueError('INVALID_PREDECISION_EVIDENCE')
    binding = body['binding']
    if (str(final_row.get('timeframe')) != binding['timeframe']
            or E._iso(final_row.get('timestamp')) != binding['bar_open']
            or final_row.get('market_context') != binding['market_context']):
        raise ValueError('CONSUMER_CONTEXT_MISMATCH')
    close = E._time(binding['bar_close'])
    received = {}; unavailable = {}; excluded = {}
    for key in NATIVE_CONCLUSION_SOURCES:
        item = body['observations'][key]
        available = E._time(item.get('available_by'))
        allowed = (item.get('status') == 'GENUINE_CANONICAL_EVIDENCE'
                   and item.get('causal_status') == 'AT_OR_BEFORE_CLOSE'
                   and available is not None and available <= close
                   and item.get('freshness') != 'STALE')
        if not allowed:
            unavailable[key] = {'status': item.get('status'), 'causal_status': item.get('causal_status'),
                                'available_by': item.get('available_by'), 'sha256': item.get('sha256')}
            continue
        fields = item.get('fields', {})
        excluded[key] = {k: v for k, v in fields.items() if k in ALREADY_AUCTION_FIELDS}
        values = {k: v for k, v in fields.items()
                  if k not in ALREADY_AUCTION_FIELDS and not k.startswith('lineage_') and k != 'timestamp'}
        received[key] = {'native_values': values,
                        'producer': item['source_module'], 'source_path': item['source_path'],
                        'artifact_sha256': item['sha256'], 'row_sha256': item['source_row_sha256'],
                        'source_timeframe': item.get('source_timeframe'),
                        'source_observation_timestamp': item.get('source_observation_timestamp'),
                        'source_event_timestamp': item.get('source_event_timestamp'),
                        'available_by': item['available_by'], 'availability_proof': item.get('availability_proof'),
                        'availability_witness': item.get('availability_witness'),
                        'freshness': item.get('freshness'), 'handler': 'NO_APPROVED_NATIVE_CONCLUSION_HANDLER'}
        if key == 'meta' and 'target_inputs' in item:
            received[key]['target_inputs'] = item['target_inputs']
    own = body['observations'].get('own_tf_stage2')
    tf_review = {'status': 'MISSING_OWN_TF_STAGE2', 'target_tf': binding['timeframe']}
    if own is not None:
        fields = own.get('fields', {})
        exact = (fields.get('target_tf') == binding['timeframe']
                 and E._iso(fields.get('target_bar')) == binding['bar_open'])
        tf_review = {'status': own.get('status') if exact else 'INCOMPATIBLE_TF_OR_BAR',
                     'target_tf': binding['timeframe'], 'artifact_sha256': own.get('sha256'),
                     'row_sha256': own.get('source_row_sha256'), 'available_by': own.get('available_by'),
                     'native_component': fields.get('native_component'),
                     'analysis_status': fields.get('analysis_status'), 'mtf_status': fields.get('mtf_status'),
                     'native_event_count': fields.get('native_event_count'),
                     'native_events_json': fields.get('native_events_json'),
                     'native_mtf_json': fields.get('native_mtf_json'),
                     'considered_before_reducer': True, 'decision_use': False,
                     'decision_admission':own.get('decision_admission')}
        if exact and own.get('analysis_available') and (own.get('decision_admission') or {}).get('admitted'):
            received['own_tf_stage2'] = {'native_values': fields, 'producer': own['source_module'],
                'artifact_sha256':own['sha256'],'source_timeframe':binding['timeframe'],
                'available_by':own['available_by'],'handler':'NO_NEW_DECISION_POLICY'}
    return {'schema': 'STAGE2_NATIVE_CONSUMPTION_V1', 'consumption_status': 'INSPECTED', 'consumer': consumer,
            'tf_specific_review': tf_review,
            **({'own_tf_decision_snapshot':body['own_tf_decision_snapshot']} if 'own_tf_decision_snapshot' in body else {}),
            'shared_conclusion_keys': [k for k in received if k != 'own_tf_stage2'],
            'input_binding': binding, 'evidence_set_sha256': evidence['evidence_set_sha256'],
            'source_observations_sha256': E._sha(E._bytes(body['observations'])),
            'received_native_conclusions': received, 'unavailable': unavailable,
            'excluded_already_auction_fields': excluded,
            'native_final_decision': decision_fields(final_row, FINAL_DECISION_FIELDS),
            'received_before_native_reducer_at': datetime.now(timezone.utc).isoformat(),
            'used_for_decision': [], 'decision_influence': 'NOT_PROVEN',
            'market_event_episode_ownership': 'NOT_PROVEN'}


def _prepared_path(stage, tf, opened):
    return Path(stage) / E.SIDECAR_ROOT / 'prepared_consumption' / tf / (opened.strftime('%Y%m%dT%H%M%SZ') + '.json')


def prepare_consumption_records(stage, records):
    """Private staging metadata, delivered by the existing R071 sidecar writer."""
    for record in records:
        binding = record['input_binding']
        path = _prepared_path(stage, binding['timeframe'], E._time(binding['bar_open']))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(E._bytes({'record': record, 'content_sha256': E._sha(E._bytes(record))}))


def load_prepared_consumption(stage, tf, opened):
    path = _prepared_path(stage, tf, E._time(opened))
    if not path.exists():
        return None
    envelope = __import__('json').loads(path.read_bytes())
    if E._sha(E._bytes(envelope['record'])) != envelope['content_sha256']:
        raise ValueError('CORRUPT_PREPARED_CONSUMPTION')
    return envelope['record']


def bind_consumption_after_decision(record, binding, observations, final, life):
    """Technical result association only. No source-event episode claim."""
    original = record['input_binding']
    for key in ('timeframe', 'bar_open', 'bar_close'):
        if original[key] != binding[key]:
            raise ValueError('CONSUMPTION_TARGET_MISMATCH')
    if record.get('consumption_status') == 'UNAVAILABLE':
        if record['received_native_conclusions'] or record['source_observations_sha256'] is not None:
            raise ValueError('UNAVAILABLE_CONSUMPTION_CANNOT_CLAIM_SOURCE_PROOF')
    elif record['source_observations_sha256'] != E._sha(E._bytes(observations)):
        raise ValueError('CONSUMPTION_SOURCE_VIEW_MISMATCH')
    if record['native_final_decision'] != decision_fields(final, FINAL_DECISION_FIELDS):
        raise ValueError('CONSUMPTION_FINAL_DECISION_MISMATCH')
    if record['native_lifecycle_decision'] != decision_fields(life, LIFECYCLE_DECISION_FIELDS):
        raise ValueError('CONSUMPTION_LIFECYCLE_DECISION_MISMATCH')
    if record['used_for_decision']:
        admitted = meta_warning_admission(record, tf=binding['timeframe'], cutoff=binding['bar_close'])
        decision = record.get('meta_decision') or {}
        if (record['used_for_decision'] != ['meta'] or not admitted['eligible']
                or record['decision_influence'] != admitted['decision_influence']
                or not decision.get('applied') or decision.get('admission') != admitted
                or decision.get('policy') != 'R07_2D_OWNER_APPROVED_META_WARNING_V1'):
            raise ValueError('UNSUPPORTED_CONSUMPTION_RULE_CLAIM')
    elif record['decision_influence'] != 'NOT_PROVEN':
        raise ValueError('UNSUPPORTED_CONSUMPTION_RULE_CLAIM')
    return {**record, 'technical_result_binding': binding,
            'association': 'INPUT_CONSIDERED_IN_THIS_COMPUTATION_NOT_SOURCE_EVENT_OWNERSHIP'}


def unavailable_native_conclusions(final_row, *, consumer, error):
    """Evidence failure is explicit metadata, never a new Lifecycle gate."""
    from datetime import datetime, timezone
    tf = str(final_row.get('timeframe'))
    opened = E._time(final_row.get('timestamp'))
    return {'schema': 'STAGE2_NATIVE_CONSUMPTION_V1', 'consumption_status': 'UNAVAILABLE',
            'consumer': consumer, 'error': type(error).__name__ + ':' + str(error),
            'input_binding': {'timeframe': tf, 'bar_open': E._iso(opened),
                              'bar_close': E._iso(opened + pd.Timedelta(minutes=E.TF_MINUTES[tf]))},
            'source_observations_sha256': None, 'received_native_conclusions': {},
            'native_final_decision': decision_fields(final_row, FINAL_DECISION_FIELDS),
            'received_before_native_reducer_at': datetime.now(timezone.utc).isoformat(),
            'used_for_decision': [], 'decision_influence': 'NOT_PROVEN',
            'market_event_episode_ownership': 'NOT_PROVEN'}

# R07.2d owner-approved warning policy; not a direction/strength classifier.
META_CAPTURE_HELPER_SHA256 = '6c9110f2e7a8969c478fddef9b9d83b47ae64d80ba89db4fde4154b1ac859aad'
META_WARNING_STATES = frozenset({'OVERCONFIDENCE_DETECTED', 'LOW_CONFIDENCE_ENVIRONMENT'})
META_PRODUCER_SHA256 = 'f182025a4571a5907f60443f6513892094c091af6d99ddc09ff5877124720758'


def _native_meta_applicability(meta, *, tf, cutoff):
    """Exact two-source computation correspondence, not a TTL or global scope."""
    import stage2_publication_metadata as H
    witness = meta.get('availability_witness') or {}
    lineage = witness.get('input_lineage')
    target = meta.get('target_inputs')
    reasons = []
    base = {'eligible': False, 'scope': 'EXACT_SOURCE_PAIR_TO_OWN_TF_CALCULATION',
            'source_timeframe': meta.get('source_timeframe'), 'target_timeframe': tf,
            'cutoff': E._iso(cutoff), 'freshness_basis': 'INPUT_SET_CURRENTNESS_NO_TTL'}
    if (not isinstance(lineage, dict) or lineage.get('schema') != H.META_INPUT_SCHEMA
            or lineage.get('status') != 'EXACT_READS_BOUND'
            or lineage.get('capture_helper_source_sha256') != META_CAPTURE_HELPER_SHA256
            or witness.get('input_lineage_sha256') != H.digest(H.encode(lineage))):
        return {**base, 'reason_codes': ['META_TARGET_APPLICABILITY_NOT_PROVEN',
                'META_FRESHNESS_CONTRACT_NOT_PROVEN', 'META_INPUT_READ_ORIGIN_NOT_PROVEN']}
    if not isinstance(target, dict) or target.get('timeframe') != tf or target.get('cutoff') != E._iso(cutoff):
        return {**base, 'reason_codes': ['META_TARGET_APPLICABILITY_NOT_PROVEN', 'META_TARGET_INPUT_SET_MISSING']}
    captured = E._time(lineage.get('captured_at'))
    completed = E._time(witness.get('publication_completed_at'))
    if captured is None or completed is None or captured > completed or completed > E._time(cutoff):
        reasons.append('META_INPUT_CAPTURE_CAUSALLY_UNAVAILABLE')
    for key in ('probabilistic', 'reinforcement'):
        origin = lineage.get('inputs', {}).get(key) or {}
        actual = target.get('inputs', {}).get(key) or {}
        read = origin.get('read_witness') or {}
        if (origin.get('source_path') != E.SOURCES[key][0]
                or origin.get('read_status') != 'EXACT_NATIVE_READ_BYTES'
                or read.get('status') != 'EXACT_NATIVE_READ_BYTES'
                or read.get('reader_helper_source_sha256') != META_CAPTURE_HELPER_SHA256
                or read.get('artifact_sha256') != origin.get('artifact_sha256')
                or read.get('artifact_absolute_path') != origin.get('artifact_absolute_path')
                or read.get('frame_sha256') != origin.get('used_frame', {}).get('frame_sha256')):
            reasons.append('META_' + key.upper() + '_READ_IDENTITY_NOT_PROVEN')
        if (actual.get('artifact_sha256') != origin.get('artifact_sha256')
                or actual.get('source_path') != origin.get('source_path')
                or actual.get('artifact_absolute_path') != origin.get('artifact_absolute_path')
                or actual.get('used_frame') != origin.get('used_frame')
                or actual.get('selection') != origin.get('selection')
                or actual.get('selection_rule') != origin.get('selection_rule')):
            reasons.append('META_' + key.upper() + '_INPUT_SET_CHANGED')
        if actual.get('status') != 'GENUINE_CANONICAL_EVIDENCE' or actual.get('causal_status') != 'AT_OR_BEFORE_CLOSE':
            reasons.append('META_' + key.upper() + '_TARGET_EVIDENCE_INELIGIBLE')
        if actual.get('freshness') == 'STALE':
            reasons.append('META_' + key.upper() + '_SOURCE_STALE')
        selection = origin.get('selection') or {}
        if (selection.get('source_timeframes') != [tf] or selection.get('unrecorded_timeframe_rows') != 0):
            reasons.append('META_TARGET_APPLICABILITY_NOT_PROVEN')
        clocks = selection.get('observation_clocks') or []
        read_at = E._time(read.get('decoded_at'));raw_at = E._time(read.get('bytes_read_at'))
        if (not clocks or any(E._time(v) is None or E._time(v) > E._time(cutoff) for v in clocks)
                or read_at is None or raw_at is None or read_at < raw_at or captured is None
                or read_at > captured):
            reasons.append('META_' + key.upper() + '_INPUT_CLOCK_UNPROVEN')
    if reasons:
        return {**base, 'reason_codes': list(dict.fromkeys(reasons))}
    return {**base, 'eligible': True, 'reason_codes': ['META_EXACT_INPUT_SET_OWN_TF_CURRENT'],
            'input_lineage_sha256': witness['input_lineage_sha256']}


def meta_warning_admission(review, *, tf, cutoff):
    """Decision power requires more than R071 descriptive delivery admission."""
    result = {'eligible': False, 'decision_influence': 'NOT_PROVEN'}
    if not review or review.get('consumption_status') != 'INSPECTED':
        return {**result, 'reason_codes': ['META_EVIDENCE_UNAVAILABLE']}
    meta = review.get('received_native_conclusions', {}).get('meta')
    if meta is None:
        return {**result, 'reason_codes': ['META_NOT_CAUSALLY_ADMITTED'],
                'source_status': review.get('unavailable', {}).get('meta')}
    state = meta.get('native_values', {}).get('meta_state')
    result.update({'warning': state, 'source': meta})
    if state not in META_WARNING_STATES:
        return {**result, 'reason_codes': ['META_NO_WARNING' if state == 'BALANCED_COGNITION'
                                         else 'META_NATIVE_STATE_UNMAPPED']}
    if meta.get('source_timeframe') not in (None, tf):
        return {**result, 'reason_codes': ['META_FOREIGN_TIMEFRAME']}
    proof = meta.get('availability_witness') or {}
    if (meta.get('producer') != 'adaptive_meta_cognition_engine_v1.py'
            or meta.get('source_path') != E.SOURCES['meta'][0]
            or proof.get('kind') != 'SHA_BOUND_NATIVE_POST_WRITE_PUBLICATION'
            or proof.get('producer_source_sha256') not in (META_PRODUCER_SHA256, '8ad6db7822beda9a155190f37e20bf3bf51252ca1e5bf49f29c1f85e2bae5161')
            or proof.get('source_sha256') != meta.get('artifact_sha256')
            or proof.get('source_path') != meta.get('source_path')
            or not proof.get('version_receipt_sha256')):
        return {**result, 'reason_codes': ['META_NATIVE_PUBLICATION_RECEIPT_NOT_PROVEN']}
    available = E._time(meta.get('available_by'));completed = E._time(proof.get('publication_completed_at'))
    if (available is None or completed is None or available > E._time(cutoff)
            or completed > E._time(cutoff) or completed != available):
        return {**result, 'reason_codes': ['META_LATE_OR_INVALID_PUBLICATION_CLOCK']}
    if meta.get('freshness') == 'STALE':
        return {**result, 'reason_codes': ['META_STALE']}
    applicability = _native_meta_applicability(meta, tf=tf, cutoff=cutoff)
    if not applicability['eligible']:
        return {**result, 'applicability': applicability, 'reason_codes': applicability['reason_codes']}
    return {**result, 'eligible': True, 'applicability': applicability,
            'decision_influence': 'GENUINE_PROVEN', 'reason_codes': ['META_WARNING_ADMITTED']}


def apply_meta_warning(candidate, *, prev, review, reducer, reducer_inputs):
    """Single policy point called by BOTH native Lifecycle builders.

    A prevented genesis uses the original reducer's existing DEVELOPING ->
    CANDIDATE transition. This is an explicit policy projection, never a rewrite
    of raw Final/source status or an invented INVALIDATED/CHALLENGED episode.
    """
    if review is None:
        return candidate
    binding = review['input_binding'];tf = binding['timeframe']
    admission = meta_warning_admission(review, tf=tf, cutoff=binding['bar_close'])
    decision = {'policy': 'R07_2D_OWNER_APPROVED_META_WARNING_V1',
                'original_lifecycle_candidate': E._value(candidate),
                'admission': admission, 'target': binding,
                'applied': False, 'reason_code': admission['reason_codes'][0]}
    final = dict(candidate)
    if admission['eligible']:
        if candidate.get('lifecycle_state') != 'ACTIVE':
            decision['reason_code'] = 'META_NATIVE_STRICTER_OR_NONACTIVE_RESULT_PRESERVED'
        else:
            previous_active = (prev or {}).get('active_market_context', 'OBSERVE')
            if previous_active in ('LONG_CONTEXT', 'SHORT_CONTEXT'):
                # Existing ACTIVE/CHALLENGED -> CHALLENGED, same active identity.
                # Never replace a native opposite/neutralization challenge.
                final['lifecycle_state'] = 'CHALLENGED'
                old_challenge = (prev or {}).get('challenge_context')
                preserve = (prev or {}).get('lifecycle_state') == 'CHALLENGED' and old_challenge is not None and not pd.isna(old_challenge)
                final['challenge_context'] = old_challenge if preserve else previous_active
                final['challenge_started_at'] = ((prev or {}).get('challenge_started_at') if preserve
                                                 else reducer_inputs['timestamp'])
                final['challenge_reason'] = ((prev or {}).get('challenge_reason') if preserve
                                             else admission['warning'])
                decision['reason_code'] = 'META_WARNING_CHALLENGES_EXISTING_ACTIVE'
            else:
                # Select an existing legal transition, preserving the raw inputs
                # in the output and keeping the existing candidate clock logic.
                projected = {**reducer_inputs, 'raw_context_status': 'DEVELOPING'}
                final = reducer(**projected)
                if final.get('lifecycle_state') != 'CANDIDATE' or final.get('active_market_context') != 'OBSERVE':
                    raise RuntimeError('META_NO_LEGAL_NATIVE_ACTIVATION_DEFERRAL')
                decision['transition_projection'] = {'raw_context_status': 'DEVELOPING',
                    'meaning': 'POLICY_SELECTION_OF_EXISTING_CANDIDATE_TRANSITION_NOT_SOURCE_RECLASSIFICATION'}
                decision['reason_code'] = 'META_WARNING_DEFERS_NEW_ACTIVE_TO_NATIVE_CANDIDATE'
            final['transition_reason'] = decision['reason_code']
            decision['applied'] = True
            review['used_for_decision'] = ['meta']
            review['decision_influence'] = admission['decision_influence']
    decision['resulting_lifecycle_candidate'] = E._value(final)
    review['meta_decision'] = decision
    return final


# Own-TF native Climax enters the ALREADY EXISTING Auction cognition channel.
# No Final/Lifecycle is needed to read it: publication admission precedes Auction.
def auction_climax_reader(stage, tf):
    sources = E.load_sources(stage, specifications=E.TF_NATIVE_SOURCES)
    source = sources.get('own_tf_' + tf)

    def read(opened):
        opened = E._time(opened)
        if source is None or source.get('status') != 'PRESENT':
            return None
        if not (source['frame']._source_timestamp == opened).any():
            return None  # No borrowing another packet's target/history.
        context=load_own_tf_decision_snapshot(stage,tf,opened)
        item = E.load_tf_native_evidence_from_sources(sources, tf, opened,decision_context=context)
        fields = item.get('fields', {})
        result = {'schema':'NATIVE_CLIMAX_AUCTION_CONSUMPTION_V1',
            'timeframe':tf,'bar_open':E._iso(opened),'bar_close':E._iso(opened+pd.Timedelta(minutes=E.TF_MINUTES[tf])),
            'status':item.get('status'),'available_by':item.get('available_by'),
            'artifact_sha256':item.get('sha256'),'row_sha256':item.get('source_row_sha256'),
            'availability_witness':item.get('availability_witness'),
            'raw_native_fields':fields,'input_admitted':False,'transported_input_fields':[],
            'decision_admission':item.get('decision_admission'),
            'decision_as_of':context.get('decision_as_of') if context else None,
            'market_data_cutoff':context.get('market_data_cutoff') if context else None,
            'decision_snapshot_sha256':context.get('snapshot_sha256') if context else None}
        eligible=bool((item.get('decision_admission') or {}).get('admitted'))
        if eligible:
            import json
            provenance=json.loads(fields['provenance_json'])
            evaluated=E._time(provenance.get('own_last_observation_close'))
            published=E._time(item.get('available_by'))
            read_at=E._time(provenance.get('source_read_at'))
            if (evaluated is None or evaluated!=opened+pd.Timedelta(minutes=E.TF_MINUTES[tf])
                    or published is None or read_at is None or not evaluated<=read_at<=published):
                result['status']='CAUSALLY_UNAVAILABLE'
                result['reason']='SOURCE_COMPUTATION_CLOCK_NOT_ADMISSIBLE'
            else:
                result['native_events']=json.loads(fields['native_events_json'])
                result['input_admitted']=True
                result['values_evaluated_asof']=E._iso(evaluated)
                result['post_event_qualifiers_use']='DELIVERED_ONLY_NO_NATIVE_AUCTION_RULE'
        return result
    return read

# Processing-time snapshot for NEW own-TF decisions only. Replay never pins now.
def _own_tf_history(root, tf, *, _decoded_cache=None):
    import io
    root=Path(root)
    base=E.final_path(tf).parent
    required=[E.final_path(tf),base/'auction_episode_memory.parquet',
              Path('data/cognition/market_context_lifecycle_memory.parquet')]
    if tf!='M15':required.append(base/'market_context_lifecycle_memory.parquet')
    optional=[Path('data/live/context_decision_log.parquet')]
    if tf=='M15':
        optional.append(Path('data/cognition/auction_episode_observations.parquet'))
        home=Path('data/live/m15_september_shadow_v1')
        optional += [home/name for name in ('auction.parquet','cognitive_market_state_memory.parquet',
                                            'final_market_context_memory.parquet','market_context_lifecycle_memory.parquet')]
    else:optional.append(base/'auction_episode_confirmations.parquet')
    files={};tips=[];valid=root.is_dir()
    for rel in required+optional:
        path=root/rel
        if not path.exists():
            if rel in required:valid=False
            files[str(rel)]={'present':False};continue
        try:
            # Byte identity is checked on EVERY call, never mtime/size alone.
            # Reuse only the deterministic decoding/fingerprint of these exact
            # bytes in this own-TF scope. No admission or newness result is cached.
            raw=path.read_bytes()
            raw_sha=E._sha(raw)
            cache_key=(str(path.resolve()),tf)
            cached=None if _decoded_cache is None else _decoded_cache.get(cache_key)
            if cached is not None and cached[0]==raw_sha:
                entry=dict(cached[1]);files[str(rel)]=entry
                tip=E._time(entry['tip'])
                if tip is not None:tips.append(tip)
                continue
            frame=__import__('pandas').read_parquet(io.BytesIO(raw))
            if 'timeframe' in frame:
                # Existing publisher contract: untagged primary legacy rows
                # belong to M15. Never infer ownership for a per-TF file.
                if 'timeframes' in rel.parts and frame.timeframe.isna().any():
                    raise ValueError('HISTORY_TIMEFRAME_OWNER_UNPROVEN')
                owners=frame.timeframe.fillna('M15').astype(str)
                frame=frame.loc[owners==tf]
            elif tf!='M15' and rel.name=='context_decision_log.parquet':continue
            clock='candle_timestamp' if rel.name=='context_decision_log.parquet' else 'timestamp'
            times=pd.to_datetime(frame[clock],utc=True,errors='raise')
            if times.isna().any():raise ValueError('INVALID_COMMITTED_CLOCK')
            tip=times.max() if len(times) else None
            # Each TF is independent even when another TF updates merged Life.
            identity=E._sha(E._bytes(E._value(frame.to_dict('records'))))
            files[str(rel)]={'present':True,'rows':len(frame),'scope_sha256':identity,'tip':E._iso(tip)}
            if _decoded_cache is not None:
                # One current version per path/TF; no frames or old versions retained.
                _decoded_cache[cache_key]=(raw_sha,dict(files[str(rel)]))
            if tip is not None:tips.append(tip)
        except (ValueError,KeyError,OSError,TypeError):
            valid=False;files[str(rel)]={'present':True,'readable':False}
    return {'proven':valid,'tip':E._iso(max(tips)) if tips else None,'files':files}


def pin_new_own_tf_decision_snapshot(stage, history_root, *, market_data_cutoff):
    """Explicit LIVE publisher entry; never called by a historical reader.

    One existing private evidence stage owns the immutable snapshot. Re-entry
    reuses its original clock. Actual committed rows are never deleted/seeded.
    """
    import json,os,tempfile
    from datetime import datetime,timezone
    path=Path(stage)/E.SIDECAR_ROOT/'own_tf_processing_snapshot.json'
    if path.exists():
        old=json.loads(path.read_bytes());body=old['snapshot']
        if (E._sha(E._bytes(body))!=old['content_sha256']
                or body['history_root']!=str(Path(history_root).resolve())
                or body['market_data_cutoff']!=E._iso(market_data_cutoff)):
            raise ValueError('OWN_TF_DECISION_SNAPSHOT_CONFLICT')
        return body
    decision_as_of=datetime.now(timezone.utc).isoformat()  # BEFORE classifiers.
    cutoff=E._time(market_data_cutoff)
    if cutoff is None or cutoff>E._time(decision_as_of):raise ValueError('FUTURE_MARKET_CUTOFF')
    sources=E.load_sources(stage,specifications=E.TF_NATIVE_SOURCES)
    body={'schema':'OWN_TF_PROCESSING_SNAPSHOT_V1','decision_as_of':decision_as_of,
          'market_data_cutoff':E._iso(cutoff),'history_root':str(Path(history_root).resolve()),
          'history':{tf:_own_tf_history(history_root,tf) for tf in E.TF_MINUTES},
          'source_versions':{k:{'sha256':v.get('sha256'),'receipt_sha256':v.get('publication_metadata_sha256')}
                             for k,v in sources.items()}}
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=E._bytes({'snapshot':body,'content_sha256':E._sha(E._bytes(body))})
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
        tmp=Path(handle.name)
        try:
            handle.write(raw);handle.flush();os.fsync(handle.fileno());os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
    return body


def load_own_tf_decision_snapshot(stage, tf, opened, *, validate_unpublished=True, _history_cache=None):
    import json
    path=Path(stage)/E.SIDECAR_ROOT/'own_tf_processing_snapshot.json'
    if not path.exists():return None  # No processing clock inferred for replay.
    envelope=json.loads(path.read_bytes());body=envelope['snapshot']
    if (E._sha(E._bytes(body))!=envelope['content_sha256']
            or body.get('schema')!='OWN_TF_PROCESSING_SNAPSHOT_V1'):
        raise ValueError('CORRUPT_OWN_TF_DECISION_SNAPSHOT')
    history=body['history'][tf];opened=E._time(opened)
    tip=E._time(history['tip'])
    eligible=history['proven'] and (tip is None or opened>tip)
    reason='NEW_UNPUBLISHED_CANDIDATE' if eligible else 'COMMITTED_OR_UNPROVEN_HISTORY'
    if validate_unpublished:
        if _own_tf_history(body['history_root'],tf,_decoded_cache=_history_cache)!=history:
            eligible=False;reason='HISTORY_CHANGED_SINCE_DECISION_SNAPSHOT'
        if E._path(body['history_root'],tf,opened).exists():
            eligible=False;reason='IMMUTABLE_CONTEXT_ALREADY_PUBLISHED'
    # Audit reconstruction uses the original pinned pre-decision scope only;
    # it does not reopen or evaluate the now-published candidate.
    return {**body,'snapshot_sha256':envelope['content_sha256'],
            'candidate_new':bool(eligible),'candidate_reason':reason}
