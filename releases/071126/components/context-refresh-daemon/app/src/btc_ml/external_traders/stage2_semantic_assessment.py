"""Pure, deterministic R07.2a descriptive semantics. No Lifecycle/OPEN policy.

Meanings are native code semantics, not calibrated economic validity. Non-directional
structural support and native internal confidence conflict never imply LONG/SHORT.
Numeric values remain untouched. Shared ancestry is not a voting system.
"""
from numbers import Real

from btc_ml.external_traders import context_stage2_evidence as E

# (native meaning, descriptive properties). Source proofs are pinned in the report.
STATES = {
    "synthesis_state": {
        "LOCAL_EXHAUSTION": ("M15 event without confirmed M30 or H1 event", ("WEAK_CONFIRMATION",)),
        "INTERMEDIATE_REVERSAL": ("M30 event confirmed, no H1 event", ("STRUCTURAL_CONFIRMATION", "PERSISTENCE")),
        "STRUCTURAL_REVERSAL": ("H1 event confirmed (native else branch)", ("STRUCTURAL_CONFIRMATION", "PERSISTENCE")),
    },
    "structural_rank": {
        "LOW": ("Native local-only hierarchy rank", ("WEAK_CONFIRMATION",)),
        "MEDIUM": ("Native M30 hierarchy rank", ("STRUCTURAL_CONFIRMATION",)),
        "HIGH": ("Native H1 hierarchy rank", ("STRUCTURAL_CONFIRMATION",)),
    },
    "persistence": {
        "M15_ONLY": ("Local M15 event only", ("WEAK_CONFIRMATION",)),
        "M30_CONFIRMED": ("M30 event present in native causal window", ("PERSISTENCE",)),
        "H1_CONFIRMED": ("H1 event present in native causal window", ("PERSISTENCE",)),
    },
    "auction_state": {
        "NEUTRAL": ("No synthesis condition selected", ("UNCERTAINTY",)),
        "COUNTER_TREND_ABSORPTION": ("Absorption response against bearish HTF", ("ABSORPTION_PATTERN",)),
        "BALANCED_DISTRIBUTION": ("Localized distribution inside HTF balance", ("DISTRIBUTION_PATTERN",)),
        "STRUCTURAL_COMPRESSION": ("HTF compression with unfinished auction", ("UNRESOLVED_STRUCTURE",)),
        "FAILED_EXPANSION": ("Expansion into distribution", ("STRUCTURAL_FAILURE", "QUALITY_DETERIORATION")),
    },
    "localized_behavior": {
        "neutral": ("Localization default (not necessarily emitted)", ("UNCERTAINTY",)),
        "localized_absorption": ("Lower rejection localization", ("ABSORPTION_PATTERN",)),
        "localized_distribution": ("Upper rejection localization", ("DISTRIBUTION_PATTERN",)),
        "body_participation": ("Body localization", ("BODY_PARTICIPATION",)),
    },
    "convergence_state": {
        "NEUTRAL": ("No native convergence count condition selected", ("UNCERTAINTY",)),
        "PERSISTENT_ABSORPTION": ("Repeated absorption responses in native window", ("PERSISTENCE",)),
        "UNRESOLVED_AUCTION": ("Repeated unfinished auctions", ("UNRESOLVED_STRUCTURE",)),
        "PERSISTENT_DISTRIBUTION": ("Repeated localized distribution in native window", ("PERSISTENCE",)),
    },
    "belief_state": {
        "NEUTRAL_CONVICTION": ("Native default belief class", ("UNCERTAINTY",)),
        "MODERATE_CONVICTION": ("Native moderate belief class", ("CONFIDENCE_SUPPORT",)),
        "HIGH_CONVICTION": ("Native high belief class", ("CONFIDENCE_SUPPORT",)),
    },
    "auction_regime": {
        "UNCERTAIN": ("No native regime condition selected", ("UNCERTAINTY",)),
        "DISTRIBUTION_REGIME": ("Native distribution frequency regime", ("DISTRIBUTION_PATTERN",)),
        "ABSORPTION_REGIME": ("Native absorption frequency regime", ("ABSORPTION_PATTERN",)),
        "HIGH_CONVICTION_AUCTION": ("Native high-conviction frequency regime", ("CONFIDENCE_SUPPORT",)),
        "STRUCTURAL_REGIME": ("Native persistence regime override", ("PERSISTENCE",)),
    },
    "meta_state": {
        "BALANCED_COGNITION": ("Neither native Meta warning branch selected", ("NO_META_WARNING",)),
        "OVERCONFIDENCE_DETECTED": ("Native overconfidence penalty branch selected", ("QUALITY_DETERIORATION",)),
        "LOW_CONFIDENCE_ENVIRONMENT": ("Native low recalibrated conviction branch selected", ("WEAK_CONFIRMATION",)),
    },
}
# Only fields actually exported by each accepted producer are interpreted.
SOURCE_FIELDS = {
    "runtime": ("synthesis_state", "structural_rank", "persistence", "auction_state"),
    "mtf": ("synthesis_state", "structural_rank", "persistence"),
    "composite": ("synthesis_state", "structural_rank", "persistence", "auction_state"),
    "synthesis": ("auction_state",), "convergence": ("convergence_state", "localized_behavior"),
    "reinforcement": ("belief_state", "auction_state", "localized_behavior"),
    "probabilistic": ("auction_regime",), "meta": ("meta_state",),
    "volume_response": ("localized_behavior",),
}
ANCESTRY = {
    "volume_response": ("STAGE1_AUCTION",),
    "convergence": ("STAGE1_AUCTION",), "synthesis": ("STAGE1_AUCTION",),
    "mtf": ("MTF_EVENT_SYNTHESIS",), "runtime": ("MTF_EVENT_SYNTHESIS", "STAGE1_AUCTION"),
    "composite": ("MTF_EVENT_SYNTHESIS", "STAGE1_AUCTION"),
    "reinforcement": ("MTF_EVENT_SYNTHESIS", "STAGE1_AUCTION"),
    "probabilistic": ("MTF_EVENT_SYNTHESIS", "STAGE1_AUCTION", "REINFORCEMENT"),
    "meta": ("MTF_EVENT_SYNTHESIS", "STAGE1_AUCTION", "REINFORCEMENT", "PROBABILISTIC"),
}
# Localized behavior is also inherited by convergence/reinforcement. Retain it as
# diagnostics there, but never count it again as a new analytical confirmation.
EXCLUDED_FIELDS = {"trigger_event", "location_bias", "localized_behavior"}
SUPPORT = {"STRUCTURAL_CONFIRMATION", "PERSISTENCE", "CONFIDENCE_SUPPORT"}
CONTRADICTION = {"STRUCTURAL_FAILURE", "INTERNAL_CONFIDENCE_CONFLICT"}


def describe_state(field, value):
    entry = STATES.get(field, {}).get(value) if isinstance(value, str) else None
    return {"field": field, "value": value, "mapping": "NATIVE_CODE_PROVEN" if entry else "UNMAPPED",
            "meaning": entry[0] if entry else "UNMAPPED",
            "properties": list(entry[1]) if entry else [],
            "directional_meaning": "UNMAPPED"}


def summarize_properties(properties, has_evidence):
    """Descriptive combination only; no probabilities or new market thresholds."""
    support = bool(set(properties) & SUPPORT)
    contradiction = bool(set(properties) & CONTRADICTION)
    if not has_evidence:
        status = "NO_PROVEN_EVIDENCE"
    elif support and contradiction:
        status = "MIXED_EVIDENCE"
    elif contradiction:
        status = "PROVEN_NON_DIRECTIONAL_CONTRADICTION"
    elif support:
        status = "PROVEN_NON_DIRECTIONAL_SUPPORT"
    else:
        status = "INCOMPLETE_OR_INDETERMINATE_EVIDENCE"
    return status


def assess_stage2(evidence):
    """Describe an authenticated pre-decision view; never modifies its inputs."""
    body = {k: v for k, v in evidence.items() if k != "evidence_set_sha256"}
    if (body.get("schema") != "STAGE2_PREDECISION_EVIDENCE_V1"
            or E._sha(E._bytes(body)) != evidence.get("evidence_set_sha256")):
        raise ValueError("INVALID_PREDECISION_EVIDENCE")
    close = E._time(body["binding"]["bar_close"])
    if close is None:
        raise ValueError("INVALID_CONTEXT_CUTOFF")
    results = {}; usable = []; properties = set(); incomplete = False; unmapped = []
    # The caller's admitted list or asserted availability is not used.
    for key, item in sorted(body["observations"].items()):
        fields = item.get("fields", {})
        available = E._time(item.get("available_by"))
        admitted = (item.get("status") == "GENUINE_CANONICAL_EVIDENCE"
                    and item.get("causal_status") == "AT_OR_BEFORE_CLOSE"
                    and available is not None and available <= close
                    and item.get("freshness") != "STALE")
        excluded = key == "volume_response"
        states = [describe_state(f, fields[f]) for f in SOURCE_FIELDS.get(key, ()) if f in fields]
        effective = []
        if admitted and not excluded:
            for state in states:
                if state["field"] not in EXCLUDED_FIELDS:
                    effective.extend(state["properties"])
                    if state["mapping"] == "UNMAPPED":
                        unmapped.append({"source": key, **state})
            # Native exported conflict_penalty is the actual internal conflict
            # magnitude, not a new probability threshold or an opposite direction.
            penalty = fields.get("conflict_penalty")
            if key in ("reinforcement", "probabilistic") and isinstance(penalty, Real) and not isinstance(penalty, bool) and penalty > 0:
                effective.append("INTERNAL_CONFIDENCE_CONFLICT")
            if states or key in ("reinforcement", "probabilistic", "meta"):
                usable.append(key)
        if key in SOURCE_FIELDS and not excluded and not admitted:
            incomplete = True
        numeric = {k: v for k, v in fields.items() if isinstance(v, Real) and not isinstance(v, bool)}
        results[key] = {"admitted": admitted, "excluded_as_already_used_by_auction": excluded,
                        "raw_observation": item, "states": states,
                        "effective_properties": sorted(set(effective)),
                        "numeric_qualifiers": numeric if admitted and not excluded else {},
                        "raw_numeric_diagnostics": numeric,
                        "shared_ancestry": list(ANCESTRY.get(key, ())),
                        "own_timeframe_confirmation": bool(admitted and item.get("source_timeframe") == body["binding"]["timeframe"])}
        properties.update(effective)
    support = bool(properties & SUPPORT); contradiction = bool(properties & CONTRADICTION)
    status = summarize_properties(properties, bool(usable))
    output = {"schema": "STAGE2_SEMANTIC_ASSESSMENT_V1", "binding": body["binding"],
              "evidence_set_sha256": evidence["evidence_set_sha256"], "status": status,
              "proven_support": support, "proven_contradiction": contradiction,
              "contradiction_scope": "STRUCTURAL_FAILURE_OR_INTERNAL_CONFIDENCE_ONLY",
              "directional_support": {"LONG": "UNMAPPED", "SHORT": "UNMAPPED"},
              "directional_contradiction": {"LONG": "UNMAPPED", "SHORT": "UNMAPPED"},
              "incomplete": incomplete or bool(unmapped), "unmapped": unmapped,
              "properties": sorted(properties), "sources": results,
              "aggregation": "DESCRIPTIVE_UNION_NO_VOTES_WEIGHTS_OR_STRENGTH",
              "lifecycle_influence": "NOT_ACTIVATED", "trading_authority": "NONE",
              "directional_episode_assessment": directional_episode_assessment(
                  body["observations"], body["binding"], {key: value["admitted"] for key, value in results.items()})}
    return {**output, "assessment_sha256": E._sha(E._bytes(output))}

# R07.2b: semantic metadata only. These contracts do not provide a native
# Stage2 -> own-TF Final episode foreign key. None grants Lifecycle influence.
DIRECTIONAL_SOURCE_FIELDS = {
    **SOURCE_FIELDS,
    'runtime': (*SOURCE_FIELDS['runtime'], 'trigger_event', 'location_bias'),
    'mtf': (*SOURCE_FIELDS['mtf'], 'trigger_event', 'location_bias'),
    'composite': (*SOURCE_FIELDS['composite'], 'effective_state', 'tier1_trigger_event', 'tier1_location_bias'),
    'probabilistic': ('auction_regime', 'regime_state', 'drift_direction', 'contradiction_flags', 'trigger_event'),
    'intermediate': ('intermediate_state', 'anchor_stage2_state'),
    'arbitration': ('raw_chosen_context', 'calibrated_context', 'anchor_status',
                    'cognition_tier1_trigger_event', 'cognition_tier1_location_bias'),
    'decay': ('reset_state',), 'transition': ('transition_state', 'current_state', 'current_regime'),
}
FIELD_ALIASES = {
    'tier1_trigger_event': 'trigger_event', 'cognition_tier1_trigger_event': 'trigger_event',
    'tier1_location_bias': 'location_bias', 'cognition_tier1_location_bias': 'location_bias',
    'anchor_stage2_state': 'synthesis_state', 'current_state': 'auction_state', 'current_regime': 'auction_regime',
}
EXTRA_STATES = {
    'trigger_event': {
        'NORMAL': 'Initial no-event label; filtered from native climax event rows',
        'BUYING_CLIMAX': 'Positive delta upper-range buying effort; not a SHORT/LONG context verdict',
        'SELLING_CLIMAX': 'Negative delta lower-range capitulation branch; not a SHORT context verdict',
        'STOPPING_VOLUME': 'Negative delta with absorption/recovery predicates; not guaranteed LONG',
        'HIGH_AVERAGE_VOLUME': 'Middle-range high volume with relatively narrow spread; no signed direction',
    },
    'location_bias': {
        'NEUTRAL': 'No selected climax localization',
        'UPPER_DISTRIBUTION': 'Upper-range buying climax localization, not a seller process',
        'LOWER_ABSORPTION': 'Lower-range stopping/absorption localization, not a buyer process',
        'LOWER_CAPITULATION': 'Lower-range selling climax localization, not a signed reversal',
        'MID_AUCTION_TRANSFER': 'Middle-range high-average-volume localization',
    },
    'intermediate_state': {
        'IC_CONTINUATION_WEAKENING': 'Signed effort/price divergence in either direction; enum loses the sign',
        'IC_INITIATIVE_DETERIORATION': 'Initiative mean sign flip in either direction; enum loses the sign',
        'IC_ROTATIONAL_PRESSURE': 'Delta sign alternation/stopping pressure; not a signed context verdict',
    },
    'reset_state': {
        'NO_RESET': 'No native decay reset condition selected',
        'LOW_CONVICTION_RESET': 'Native belief decay condition, not a market direction reset',
        'DISTRIBUTION_MEMORY_RESET': 'Native distribution decay condition',
        'AUCTION_RESOLUTION_RESET': 'Native unfinished-auction decay condition',
    },
    'transition_state': {
        'STABLE_STATE': 'No change in synthesis state or probabilistic regime labels',
        'AUCTION_STATE_TRANSITION': 'Synthesis state label changed',
        'REGIME_TRANSITION': 'Probabilistic regime label changed',
        'FULL_COGNITIVE_TRANSITION': 'Both labels changed; no signed Final transition implied',
    },
    'regime_state': {
        'TREND_EXPANSION': 'Conviction-based trend regime likelihood; no trend sign exported',
        'TREND_EXHAUSTION': 'Local exhaustion/structural-regime likelihood; no trend sign exported',
        'COMPRESSION': 'Low participation/conviction/spread-variation likelihood',
        'VOLATILITY_EXPANSION': 'Increasing spread/variation likelihood; not price-up',
        'VOLATILITY_COLLAPSE': 'Decreasing spread/variation likelihood; not price-down',
        'LIQUIDATION_EVENT': 'Climax/capitulation likelihood, includes either side',
        'ABSORPTION_RECOVERY': 'Absorption likelihood; no signed context verdict',
        'BALANCED_AUCTION': 'Uncertainty/conflict/weak-persistence likelihood, not Final OBSERVE',
    },
    'drift_direction': {
        'stable': 'Calibration drift quality below native warning levels; not flat market direction',
        'elevated': 'Calibration drift quality elevated; not price-up',
        'degrading': 'Calibration drift quality deteriorating; not price-down',
    },
    'contradiction_flags': {
        'continuation_plus_distribution': 'Native coexistence of conviction and distribution components',
        'high_alignment_rising_entropy': 'Native alignment/entropy inconsistency',
        'unfinished_auction_weak_persistence': 'Native unfinished-auction/persistence inconsistency',
        'absorption_distribution_coexistence': 'Both behaviors present in reinforcement window',
    },
    'raw_chosen_context': {
        'LONG_CONTEXT': 'Raw LONG hypothesis before calibrated suppression; SHADOW ONLY',
        'SHORT_CONTEXT': 'Raw SHORT hypothesis before calibrated suppression; SHADOW ONLY',
        'OBSERVE': 'Raw non-directional hypothesis; SHADOW ONLY',
    },
    'calibrated_context': {
        'LONG_CONTEXT': 'Calibrated LONG hypothesis; SHADOW ONLY',
        'SHORT_CONTEXT': 'Calibrated SHORT hypothesis; SHADOW ONLY',
        'OBSERVE': 'Calibrated non-directional/deferred hypothesis; SHADOW ONLY',
    },
    'anchor_status': {
        'HELD': 'Location/price anchor held under native rules, not a Final episode reference',
        'FAILED': 'Location/price anchor failed under native rules, not a Final episode invalidation',
        'UNRESOLVED': 'Native location/price anchor unresolved',
        'NONE': 'No usable native price anchor',
    },
}
DEFINITION_SITES = {
    'synthesis_state': 'multi_timeframe_synthesis_engine.py::synthesize_multi_timeframe_behavior',
    'structural_rank': 'multi_timeframe_synthesis_engine.py::synthesize_multi_timeframe_behavior',
    'persistence': 'multi_timeframe_synthesis_engine.py::synthesize_multi_timeframe_behavior',
    'auction_state': 'auction_synthesis_engine_v1.py::module-level synthesis predicates',
    'localized_behavior': 'volume_localization_engine_v2.py::localization predicates; inherited by native readers',
    'convergence_state': 'auction_convergence_engine_v1.py::native tail(10) predicates',
    'belief_state': 'auction_reinforcement_engine_v1.py::run',
    'auction_regime': 'probabilistic_auction_engine_v1.py::run',
    'meta_state': 'adaptive_meta_cognition_engine_v1.py::run',
    'trigger_event': 'auction_climax_engine_v1.py::process_auction_climax + ontology_refinement.py::apply_ontology_pipeline',
    'location_bias': 'auction_climax_engine_v1.py::process_auction_climax + ontology_refinement.py::apply_ontology_pipeline',
    'intermediate_state': 'intermediate_cognition_engine_v1.py::detect_candidates',
    'effective_state': 'UNMAPPED_IN_ACCEPTED_RUNTIME_COGNITION_EXPORTER',
    'reset_state': 'auction_decay_engine_v1.py::module-level reset predicates',
    'transition_state': 'state_transition_engine_v1.py::run',
    'regime_state': 'regime_segmentation.py::infer_regime_segmentation',
    'drift_direction': 'calibration_drift_engine.py::compute_calibration_drift',
    'contradiction_flags': 'calibration_diagnostics.py::compute_conflict_density',
    'raw_chosen_context': 'auction_context_arbitration_engine_v1.py::_build_evidence_and_score + auction_context_arbitrator.py::score_auction_context',
    'calibrated_context': 'auction_context_arbitration_engine_v1.py::_build_evidence_and_score + auction_context_arbitrator.py::score_auction_context',
    'anchor_status': 'auction_context_arbitrator.py::resolve_anchor_status',
}


def describe_directional_state(source_key, field, value):
    """Native definition, independent of whether this occurrence is eligible."""
    native_field = FIELD_ALIASES.get(field, field)
    entry = STATES.get(native_field, {}).get(value) if isinstance(value, str) else None
    meaning = entry[0] if entry else EXTRA_STATES.get(native_field, {}).get(value) if isinstance(value, str) else None
    # A neutral pattern/default is not a neutral position or an instruction to
    # neutralize a Final context. Confidence/quality enums are not mapped by name.
    direction = 'UNMAPPED'
    if isinstance(value, str) and (native_field, value) in {('auction_state', 'NEUTRAL'), ('convergence_state', 'NEUTRAL')}:
        direction = 'NEUTRAL'
    if source_key == 'arbitration' and native_field in ('raw_chosen_context', 'calibrated_context') and isinstance(value, str):
        direction = {'LONG_CONTEXT': 'LONG', 'SHORT_CONTEXT': 'SHORT', 'OBSERVE': 'NEUTRAL'}.get(value, 'UNMAPPED')
    known = meaning is not None and field in DIRECTIONAL_SOURCE_FIELDS.get(source_key, ())
    excluded = source_key == 'volume_response' or native_field in EXCLUDED_FIELDS
    return {'field': field, 'native_field': native_field, 'value': value,
            'producer': E.SOURCES.get(source_key, (None, None))[1],
            'definition_site': DEFINITION_SITES.get(native_field),
            'native_semantics': meaning if known else 'UNMAPPED',
            'direction_binding': direction if known else 'UNMAPPED',
            'semantic_mapping': 'NATIVE_CODE_PROVEN' if known else 'UNMAPPED',
            'already_used_by_auction': excluded,
            'source_contract': 'SHADOW_ONLY' if source_key == 'arbitration' else 'NATIVE_ANALYTICAL_OUTPUT'}


def compare_documented_direction(source_direction, final_context):
    """Compare already-defined enums ONLY; this is not occurrence qualification."""
    target = {'LONG_CONTEXT': 'LONG', 'SHORT_CONTEXT': 'SHORT'}.get(final_context)
    if source_direction == 'NEUTRAL':
        return 'NEUTRAL'
    if source_direction not in ('LONG', 'SHORT') or target is None:
        return 'UNMAPPED'
    return 'CONFIRM' if source_direction == target else 'CONTRADICT'


def episode_binding(item, target):
    """Describe the native missing edge, never invent an episode join by time.

    Accepted R06 Stage2 writers export lineage clocks (or an anchor timestamp),
    not a foreign key to the separately generated own-TF Final/Lifecycle episode.
    Even matching caller-added ID strings cannot create that missing contract.
    """
    fields = item.get('fields', {})
    recorded = {k: fields[k] for k in ('event_id', 'auction_event_id', 'episode_id', 'context_episode_id',
                                      'stage2_anchor_id', 'anchor_timestamp', 'cycle_id',
                                      'lineage_event_timestamp', 'auction_event_timestamp') if k in fields}
    reasons = ['NO_NATIVE_STAGE2_TO_FINAL_EPISODE_CONTRACT']
    if item.get('source_timeframe') is None:
        reasons.append('SOURCE_TF_NOT_RECORDED')
    elif item['source_timeframe'] != target['timeframe']:
        reasons.append('NO_APPROVED_CROSS_TF_EPISODE_MAPPING')
    return {'status': 'EPISODE_UNMAPPED', 'reasons': reasons,
            'source_timeframe': item.get('source_timeframe'),
            'source_record_identity': {'artifact_sha256': item.get('sha256'),
                                       'row_sha256': item.get('source_row_sha256')},
            'recorded_references_not_episode_proof': recorded,
            'target': {k: target.get(k) for k in ('timeframe', 'bar_open', 'bar_close',
                                                 'final_row_sha256', 'market_context')},
            'join_by_timestamp_or_direction': 'NOT_PERMITTED'}


def qualify_directional_state(source_key, field, value, item, target, *, admitted):
    """No changes to native admission: `admitted` comes from assess_stage2.

    Qualification is separate from descriptive structure/quality support. There
    is no accepted episode mapping with which to issue directional influence.
    """
    native = describe_directional_state(source_key, field, value)
    binding = episode_binding(item, target)
    reason = None
    expected = E.SOURCES.get(source_key)
    if (not admitted or expected is None or item.get('source_module') != expected[1]
            or item.get('source_path') != expected[0]):
        status, reason = 'INELIGIBLE', 'PROVENANCE_OR_CAUSAL_ADMISSION_FAILED'
    elif native['source_contract'] == 'SHADOW_ONLY':
        status, reason = 'INELIGIBLE', 'NATIVE_PRODUCER_IS_SHADOW_ONLY'
    elif native['already_used_by_auction']:
        status, reason = 'INELIGIBLE', 'ALREADY_ACCOUNTED_IN_AUCTION_NOT_AN_INDEPENDENT_CONTRIBUTION'
    elif native['direction_binding'] == 'NEUTRAL':
        status, reason = 'NEUTRAL', 'DOCUMENTED_NON_DIRECTIONAL_PATTERN_NOT_A_FINAL_POSITION'
    elif native['direction_binding'] == 'UNMAPPED':
        status, reason = 'UNMAPPED', 'NO_DOCUMENTED_SIGNED_FINAL_DIRECTION_SEMANTICS'
    else:
        # Current contracts never reach an approved occurrence-to-episode edge.
        status, reason = 'UNMAPPED', 'EPISODE_UNMAPPED'
    return {**native, 'qualification_status': status, 'qualification_reason': reason,
            'episode_binding': binding, 'lifecycle_influence_eligible': False}


def directional_episode_assessment(observations, target, admitted_by_source):
    occurrences = {}
    for key, item in sorted(observations.items()):
        fields = item.get('fields', {})
        states = []
        for field in DIRECTIONAL_SOURCE_FIELDS.get(key, ()):
            if field not in fields:
                continue
            values = fields[field].split('|') if field == 'contradiction_flags' and isinstance(fields[field], str) else [fields[field]]
            for value in values:
                if field == 'contradiction_flags' and value == '':
                    continue
                states.append(qualify_directional_state(key, field, value, item, target,
                                                       admitted=admitted_by_source[key]))
        occurrences[key] = {'occurrence_status': 'ADMITTED_FOR_DESCRIPTION' if admitted_by_source[key] else 'INELIGIBLE',
                            'source_status': item.get('status'), 'states': states,
                            'episode_binding': episode_binding(item, target)}
    statuses = sorted({s['qualification_status'] for source in occurrences.values() for s in source['states']})
    return {'schema': 'STAGE2_DIRECTIONAL_EPISODE_ASSESSMENT_V1', 'qualification_statuses': statuses,
            'episode_binding_status': 'EPISODE_UNMAPPED', 'occurrences': occurrences,
            'qualified_directional_support': [], 'qualified_directional_contradictions': [],
            'lifecycle_influence_eligible': False, 'policy': 'NO_APPROVED_DIRECTIONAL_EPISODE_INFLUENCE'}
