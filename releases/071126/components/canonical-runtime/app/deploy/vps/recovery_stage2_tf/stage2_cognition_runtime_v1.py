import pandas as pd

from deploy.vps.recovery_stage2_tf.auction_climax_engine_v1 import process_auction_climax
from deploy.vps.recovery_stage2_tf.multi_timeframe_dataset_builder import aggregate_behavioral_timeframe
from deploy.vps.recovery_stage2_tf.multi_timeframe_synthesis_engine import synthesize_multi_timeframe_behavior
from parquet_utils import atomic_parquet_write, safe_read_parquet
from stage2_publication_metadata import publish_atomic_frame
from runtime_lineage import apply_lineage_metadata
from state_manager_v1 import STATE, refresh_state

SYNTHESIS_OUTPUT_PATH = "multi_timeframe_synthesis.parquet"
RUNTIME_COGNITION_MEMORY_PATH = "runtime_cognition_memory.parquet"
CANDLE_STRUCTURE_SOURCE = "candle_structure_memory.parquet"
AUCTION_SYNTHESIS_SOURCE = "auction_synthesis_memory.parquet"

COGNITION_COLUMNS = [
    "timestamp",
    "synthesis_state",
    "trigger_event",
    "persistence",
    "persistence_score",
    "structural_rank",
    "alignment_score",
    "location_bias",
]

AUCTION_BRIDGE_COLUMNS = [
    "auction_state",
    "auction_event_timestamp",
]

STAGE2_ENGINE = "stage2_cognition_runtime_v1.py"


def build_stage2_synthesis(base_dataset: pd.DataFrame, *, components=None) -> pd.DataFrame:
    """Run Stage 2 climax + MTF synthesis on the provided dataset."""

    if components is not None:
        r = components['results']
        if len(r) != 4:
            raise ValueError('TF_STAGE2_M15_MTF_MISSING_NATIVE_COMPONENT')
        return synthesize_multi_timeframe_behavior(
            m15_states=r['M15']['auction_states'],m30_states=r['M30']['auction_states'],
            h1_states=r['H1']['auction_states'],h4_states=r['H4']['auction_states'])
    m15_dataset = base_dataset.copy()

    m30_dataset = aggregate_behavioral_timeframe(
        base_dataset.copy(),
        "M30",
    )

    h1_dataset = aggregate_behavioral_timeframe(
        base_dataset.copy(),
        "H1",
    )

    h4_dataset = aggregate_behavioral_timeframe(
        base_dataset.copy(),
        "H4",
    )

    m15_result = process_auction_climax(
        dataset=m15_dataset,
        timeframe="M15",
    )

    m30_result = process_auction_climax(
        dataset=m30_dataset,
        timeframe="M30",
    )

    h1_result = process_auction_climax(
        dataset=h1_dataset,
        timeframe="H1",
    )

    h4_result = process_auction_climax(
        dataset=h4_dataset,
        timeframe="H4",
    )

    return synthesize_multi_timeframe_behavior(
        m15_states=m15_result["auction_states"],
        m30_states=m30_result["auction_states"],
        h1_states=h1_result["auction_states"],
        h4_states=h4_result["auction_states"],
    )


def _prepare_auction_frame(auction_synthesis: pd.DataFrame | None) -> pd.DataFrame:
    if auction_synthesis is None or len(auction_synthesis) == 0:
        return pd.DataFrame(columns=["auction_event_timestamp", "auction_state"])
    if "timestamp" not in auction_synthesis.columns or "auction_state" not in auction_synthesis.columns:
        return pd.DataFrame(columns=["auction_event_timestamp", "auction_state"])
    frame = auction_synthesis[["timestamp", "auction_state"]].copy()
    frame["auction_event_timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.dropna(subset=["auction_event_timestamp"]).sort_values(
        "auction_event_timestamp"
    )
    return frame[["auction_event_timestamp", "auction_state"]].reset_index(drop=True)


def export_runtime_cognition_memory(
    synthesis_output: pd.DataFrame,
    candle_structure: pd.DataFrame | None = None,
    auction_synthesis: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build evaluation-time decision snapshots from event-sparse MTF + auction carry.

    multi_timeframe_synthesis remains event-sparse structural memory.
    runtime_cognition_memory becomes decision snapshots where:
      timestamp                 = evaluation bar (candle identity)
      lineage_event_timestamp   = climax/MTF event time (set by apply_lineage_metadata)
      auction_state / auction_event_timestamp = latest valid auction asof evaluation
    """

    if synthesis_output is None or len(synthesis_output) == 0:
        return pd.DataFrame(columns=COGNITION_COLUMNS + AUCTION_BRIDGE_COLUMNS)

    mtf = synthesis_output.dropna(subset=["synthesis_state"]).copy()
    if len(mtf) == 0:
        return pd.DataFrame(columns=COGNITION_COLUMNS + AUCTION_BRIDGE_COLUMNS)

    missing = [c for c in COGNITION_COLUMNS if c not in mtf.columns]
    if missing:
        raise ValueError(f"MTF synthesis missing required cognition columns: {missing}")

    mtf["mtf_event_timestamp"] = pd.to_datetime(mtf["timestamp"], utc=True)
    mtf = mtf.sort_values("mtf_event_timestamp").reset_index(drop=True)

    # Legacy path: no candle frame → keep prior event-sparse export semantics.
    if candle_structure is None or len(candle_structure) == 0 or "timestamp" not in candle_structure.columns:
        out = mtf[COGNITION_COLUMNS].copy().reset_index(drop=True)
        out["auction_state"] = pd.NA
        out["auction_event_timestamp"] = pd.NaT
        return out

    eval_frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(candle_structure["timestamp"], utc=True),
        }
    )
    eval_frame = (
        eval_frame.dropna(subset=["timestamp"])
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if len(eval_frame) == 0:
        return pd.DataFrame(columns=COGNITION_COLUMNS + AUCTION_BRIDGE_COLUMNS)

    mtf_for_asof = mtf[
        [
            "mtf_event_timestamp",
            "synthesis_state",
            "trigger_event",
            "persistence",
            "persistence_score",
            "structural_rank",
            "alignment_score",
            "location_bias",
        ]
    ].copy()

    merged = pd.merge_asof(
        eval_frame,
        mtf_for_asof,
        left_on="timestamp",
        right_on="mtf_event_timestamp",
        direction="backward",
    )
    merged = merged.dropna(subset=["synthesis_state"]).reset_index(drop=True)
    if len(merged) == 0:
        return pd.DataFrame(columns=COGNITION_COLUMNS + AUCTION_BRIDGE_COLUMNS)

    auction = _prepare_auction_frame(auction_synthesis)
    if len(auction) == 0:
        merged["auction_state"] = pd.NA
        merged["auction_event_timestamp"] = pd.NaT
    else:
        # Normalize only this join's keys, without discarding subsecond precision.
        evaluation_unit = merged["timestamp"].dtype.unit
        auction_unit = auction["auction_event_timestamp"].dtype.unit
        merged["timestamp"] = merged["timestamp"].dt.as_unit("ns")
        auction["auction_event_timestamp"] = auction["auction_event_timestamp"].dt.as_unit("ns")
        merged = pd.merge_asof(
            merged,
            auction,
            left_on="timestamp",
            right_on="auction_event_timestamp",
            direction="backward",
        )
        # Restore the original public column units after the lossless join.
        merged["timestamp"] = merged["timestamp"].dt.as_unit(evaluation_unit)
        merged["auction_event_timestamp"] = merged["auction_event_timestamp"].dt.as_unit(auction_unit)
        # Same-cycle wall-clock skew: auction_synthesis timestamps with utcnow
        # can land after the current M15 bar-open identity. Carry the latest
        # valid auction state onto the current evaluation tip only.
        latest_auc = auction.iloc[-1]
        tip_eval = merged["timestamp"].max()
        if pd.notna(latest_auc["auction_event_timestamp"]) and latest_auc[
            "auction_event_timestamp"
        ] > tip_eval:
            tip_mask = merged["timestamp"] == tip_eval
            merged.loc[tip_mask, "auction_state"] = latest_auc["auction_state"]
            merged.loc[tip_mask, "auction_event_timestamp"] = latest_auc[
                "auction_event_timestamp"
            ]

    # Temporarily place MTF event time in timestamp so lineage_event_timestamp
    # captures event time; caller restores evaluation timestamps afterward.
    out = merged[
        [
            "mtf_event_timestamp",
            "timestamp",
            "synthesis_state",
            "trigger_event",
            "persistence",
            "persistence_score",
            "structural_rank",
            "alignment_score",
            "location_bias",
            "auction_state",
            "auction_event_timestamp",
        ]
    ].copy()
    out = out.rename(
        columns={
            "timestamp": "evaluation_timestamp",
            "mtf_event_timestamp": "timestamp",
        }
    )
    return out.reset_index(drop=True)


def _publish_new_observations(frame: pd.DataFrame, path: str) -> None:
    """Append newly observed timestamps; never rewrite published history/lineage.

    Domain computations above remain unchanged. Newly computed past observations
    retain their actual current lineage availability, not historical authority.
    """
    from storage.path_registry import resolve_canonical
    from pathlib import Path
    target = Path(resolve_canonical(path))
    if not target.exists():
        publish_atomic_frame(frame, path, producer=__file__, writer=atomic_parquet_write)
        return
    old = pd.read_parquet(target)  # corrupt existing history is not an empty start
    if old.empty:
        publish_atomic_frame(frame, path, producer=__file__, writer=atomic_parquet_write)
        return
    times = pd.to_datetime(old["timestamp"], utc=True)
    if times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError("R06_INVALID_EXISTING_PUBLICATION_HISTORY:" + path)
    fresh = frame.loc[pd.to_datetime(frame["timestamp"], utc=True) > times.max()]
    if fresh.empty:
        return
    combined = pd.concat([old, fresh], ignore_index=True)
    publish_atomic_frame(combined, path, producer=__file__, writer=atomic_parquet_write)


def run() -> None:
    print()
    print("STAGE 2 COGNITION RUNTIME")
    print()

    # This guard executes before the first Stage2 state refresh or publication.
    # Existing computational evaluation is unchanged; it has NO historical authority.
    from cog01a_temporal_admission import enforce_stage2_admission_from_environment
    enforce_stage2_admission_from_environment()

    refresh_state()

    base_dataset = STATE["candle_structure"].copy()

    if len(base_dataset) == 0:
        print("NO CANDLE STRUCTURE DATA")
        print()
        return

    market_cutoff = pd.to_datetime(base_dataset.timestamp,utc=True).max()+pd.Timedelta(minutes=15)
    tf_components = build_tf_components(base_dataset,market_cutoff=market_cutoff)
    if len(tf_components['results']) != 4:
        # Explicit unavailable own-TF output even when the original M15 MTF
        # path cannot execute. Its original failure/guard semantics remain.
        try:
            publish_tf_native_results(build_tf_native_results(
                base_dataset,market_cutoff=market_cutoff,components=tf_components))
        except Exception as exc:
            import warnings
            warnings.warn('TF_STAGE2_PUBLICATION_UNPROVEN:'+str(exc),RuntimeWarning)
    synthesis_output = build_stage2_synthesis(base_dataset,components=tf_components) if len(tf_components['results']) == 4 else build_stage2_synthesis(base_dataset)

    synthesis_output = apply_lineage_metadata(
        synthesis_output,
        engine_name=STAGE2_ENGINE,
        source_parquet=CANDLE_STRUCTURE_SOURCE,
        dependency_chain=[
            CANDLE_STRUCTURE_SOURCE,
            STAGE2_ENGINE,
            SYNTHESIS_OUTPUT_PATH,
        ],
    )

    _publish_new_observations(
        synthesis_output,
        SYNTHESIS_OUTPUT_PATH,
    )

    # New publications are optional additions; no change to legacy formulas,
    # State/guard/currentness or canonical publication ownership.
    try:
        tf_frames = build_tf_native_results(base_dataset,market_cutoff=market_cutoff,
            components=tf_components,m15_synthesis=synthesis_output)
        publish_tf_native_results(tf_frames)
    except Exception as exc:
        import warnings
        warnings.warn('TF_STAGE2_PUBLICATION_UNPROVEN:'+str(exc),RuntimeWarning)

    auction_synthesis = safe_read_parquet(AUCTION_SYNTHESIS_SOURCE)
    if len(auction_synthesis) == 0:
        print("AUCTION SYNTHESIS UNAVAILABLE — decision bridge omits auction state")

    runtime_cognition_memory = export_runtime_cognition_memory(
        synthesis_output,
        candle_structure=base_dataset,
        auction_synthesis=auction_synthesis,
    )

    if len(runtime_cognition_memory) == 0:
        print("NO RUNTIME COGNITION SNAPSHOTS")
        print()
        return

    evaluation_timestamps = runtime_cognition_memory["evaluation_timestamp"].copy()
    domain = runtime_cognition_memory.drop(columns=["evaluation_timestamp"])

    domain = apply_lineage_metadata(
        domain,
        engine_name=STAGE2_ENGINE,
        source_parquet=SYNTHESIS_OUTPUT_PATH,
        dependency_chain=[
            CANDLE_STRUCTURE_SOURCE,
            AUCTION_SYNTHESIS_SOURCE,
            STAGE2_ENGINE,
            SYNTHESIS_OUTPUT_PATH,
            RUNTIME_COGNITION_MEMORY_PATH,
        ],
        event_timestamp_col="timestamp",
    )
    # timestamp = evaluation bar; lineage_event_timestamp retains climax/MTF event time.
    domain["timestamp"] = pd.to_datetime(evaluation_timestamps, utc=True).to_numpy()

    _publish_new_observations(
        domain,
        RUNTIME_COGNITION_MEMORY_PATH,
    )

    print(
        "SYNTHESIS ROWS:",
        len(synthesis_output),
    )

    print(
        "COGNITION ROWS:",
        len(domain),
    )

    if len(domain) > 0:
        latest = domain.iloc[-1]
        print(
            "LATEST COGNITION TIMESTAMP:",
            latest["timestamp"],
        )
        print(
            "LATEST SYNTHESIS STATE:",
            latest["synthesis_state"],
        )
        print(
            "LATEST LINEAGE EVENT TIMESTAMP:",
            latest.get("lineage_event_timestamp"),
        )
        print(
            "LATEST AUCTION STATE:",
            latest.get("auction_state"),
        )

    print()



# TF-specific extension of the existing native Stage2 computation.
TF_MINUTES = {'M15': 15, 'M30': 30, 'H1': 60, 'H4': 240}
TF_OUTPUTS = {tf: 'stage2_' + tf.lower() + '_native_memory.parquet' for tf in TF_MINUTES}


def build_tf_components(base_dataset, *, market_cutoff):
    """Share the SAME four native aggregation/climax calls with M15 synthesis."""
    from ontology_config import ontology_refinement_active
    close = pd.Timestamp(market_cutoff)
    close = close.tz_localize('UTC') if close.tzinfo is None else close.tz_convert('UTC')
    times = pd.to_datetime(base_dataset.timestamp, utc=True)
    if times.isna().any() or times.duplicated().any():
        raise ValueError('TF_STAGE2_INVALID_NATIVE_INPUT_CLOCK')
    base = base_dataset.loc[times + pd.Timedelta(minutes=15) <= close].copy()
    datasets = {};results = {};status = {}
    for tf, minutes in TF_MINUTES.items():
        try:
            dataset = base.copy() if tf == 'M15' else aggregate_behavioral_timeframe(base.copy(), tf)
            completed = pd.to_datetime(dataset.timestamp, utc=True) + pd.Timedelta(minutes=minutes)
            dataset = dataset.loc[completed <= close].copy()
            if dataset.empty:
                raise ValueError('NO_CLOSED_OWN_TF_OBSERVATIONS')
            datasets[tf] = dataset
            if not ontology_refinement_active():
                status[tf] = 'BLOCKED_NATIVE_LEGACY_LOOKAHEAD_MODE';continue
            results[tf] = process_auction_climax(dataset=dataset, timeframe=tf)
            status[tf] = 'CALCULATED_NATIVE_OWN_TF_COMPONENT'
        except ValueError as exc:
            if 'COG02_NO_COMPLETE_HTF_BARS' not in str(exc) and str(exc) != 'NO_CLOSED_OWN_TF_OBSERVATIONS':
                raise
            status[tf] = 'MISSING_CLOSED_OWN_TF_DATA'
    return {'datasets': datasets, 'results': results, 'status': status,
            'market_cutoff': close, 'base': base}


def _tf_original_source_publication(read, source_bound):
    """Original retained metadata only; today's decode clock never backdates it."""
    import json
    from pathlib import Path
    import stage2_publication_metadata as H
    result = {'status':'AVAILABILITY_NOT_PROVEN','reason':'SOURCE_IDENTITY_NOT_PROVEN'}
    if not source_bound:return result
    path = Path(str(read['artifact_absolute_path']) + '.meta.json')
    if not path.exists():return {'status':'AVAILABILITY_NOT_PROVEN','reason':'SOURCE_MANIFEST_MISSING'}
    raw=path.read_bytes()
    try:
        meta=json.loads(raw);written=pd.Timestamp(meta.get('written_at'))
        matches=(meta.get('file_sha256') == read['artifact_sha256'])
        valid=(matches and meta.get('dataset_path') == 'data/cognition/candle_structure_memory.parquet'
               and meta.get('writer_entrypoint') == 'candle_structure_engine_v1.py'
               and meta.get('metadata_origin') == 'LIVE_WRITER' and meta.get('last_write_status') == 'OK'
               and not meta.get('error_code') and not pd.isna(written) and written.tzinfo is not None)
        return {'status':'SHA_BOUND_ORIGINAL_SOURCE_PUBLICATION' if valid else 'AVAILABILITY_NOT_PROVEN',
                'reason':'MATCHING_ORIGINAL_LIVE_WRITER' if valid else ('SOURCE_METADATA_SHA_MISMATCH' if not matches else 'SOURCE_METADATA_CONTRACT_UNPROVEN'),
                'metadata_sha256':H.digest(raw),'recorded_artifact_sha256':meta.get('file_sha256'),
                'recorded_written_at':meta.get('written_at'),
                'available_by':written.tz_convert('UTC').isoformat() if valid else None}
    except (TypeError,ValueError,KeyError):
        return {'status':'AVAILABILITY_NOT_PROVEN','reason':'SOURCE_METADATA_INVALID','metadata_sha256':H.digest(raw)}


def _tf_frame_identity(frame):
    # STATE attrs carry provenance for the whole dataset. They are not row
    # values; avoid pandas copying that whole receipt for EVERY iterrows row.
    import stage2_publication_metadata as H
    clean=frame.copy(deep=False);clean.attrs={}
    return H.meta_frame_identity(clean)


def build_tf_native_results(base_dataset, *, market_cutoff, components=None, m15_synthesis=None):
    """Actual own-TF native event sets, never re-label the M15 MTF roles.

    MTF synthesis is mathematically M15-anchored (M30/H1 confirmations). It is
    not generalized by self-confirming M30, by scaling scores or replacing enum.
    Higher TFs expose their actually calculated native climax component and an
    explicit blocked structural component. No OHLCV proxy is emitted as Stage2.
    """
    import json,hashlib
    import stage2_publication_metadata as H
    from btc_ml.external_traders import context_stage2_evidence as E
    components = components or build_tf_components(base_dataset, market_cutoff=market_cutoff)
    if m15_synthesis is None and len(components['results']) == 4:
        m15_synthesis = build_stage2_synthesis(base_dataset, components=components)
    read = base_dataset.attrs.get(H.META_READ_ATTR) or {}
    source_bound = (read.get('status') == 'EXACT_NATIVE_READ_BYTES'
                    and read.get('frame_sha256') == _tf_frame_identity(base_dataset)['frame_sha256'])
    source_publication = _tf_original_source_publication(read,source_bound)
    result = {}
    for tf, minutes in TF_MINUTES.items():
        dataset = components['datasets'].get(tf)
        target_close = components['market_cutoff'].floor(str(minutes) + 'min')
        target_bar = target_close - pd.Timedelta(minutes=minutes)
        if dataset is not None and len(dataset):
            target_bar = pd.to_datetime(dataset.timestamp,utc=True).max()
            target_close = target_bar + pd.Timedelta(minutes=minutes)
        native = components['results'].get(tf)
        events = native['auction_states'] if native is not None else pd.DataFrame()
        # Event timestamps are source identities. These are event SETS evaluated
        # at this target cutoff, not invented current ACTIVE/trading conclusions.
        columns = [c for c in ['timestamp','auction_event_type','volume_percentile_50','spread_percentile_50','delta','spread','event_strength','efficiency_decay','effort_result_zone','delta_behavior_shift','recovery_structure_score','climax_resolution_behavior','absorption_persistence_score','cluster_behavior_resolution','location_bias'] if c in events]
        values = E._value(events[columns].to_dict('records')) if columns else []
        identity = _tf_frame_identity(dataset) if dataset is not None else None
        mtf = {};mtf_status = 'BLOCKED_M15_ANCHORED_MTF_METHOD'
        if tf == 'M15':
            mtf_status = 'MISSING_NATIVE_MTF_CONCLUSION'
            if m15_synthesis is not None and len(m15_synthesis):
                rows = m15_synthesis.loc[pd.to_datetime(m15_synthesis.timestamp,utc=True) <= target_bar]
                if len(rows):
                    mtf = E._value(rows.iloc[-1][COGNITION_COLUMNS].to_dict());mtf_status = 'CALCULATED_NATIVE_M15_MTF'
        status = components['status'][tf]
        if native is not None and events.empty:status = 'MISSING_NATIVE_OWN_TF_EVENTS'
        if status.startswith('CALCULATED') and tf != 'M15':status = 'PARTIAL_NATIVE_COMPONENT_MTF_BLOCKED'
        if tf == 'M15' and mtf and native is not None:status = 'CALCULATED_NATIVE_M15_MTF'
        own_times = pd.to_datetime(dataset.timestamp,utc=True) if dataset is not None else pd.DatetimeIndex([])
        source_times = pd.to_datetime(components['base'].timestamp,utc=True)
        complete_own_opens = set(own_times) if len(own_times) else set()
        used = components['base'].loc[(source_times+pd.Timedelta(minutes=15)<=target_close)
            & source_times.dt.floor(str(minutes)+'min').isin(complete_own_opens)]
        provenance = {'source_contract': CANDLE_STRUCTURE_SOURCE,'source_artifact_sha256':read.get('artifact_sha256') if source_bound else None,
            'source_path':read.get('artifact_absolute_path') if source_bound else None,
            'source_read_at':read.get('decoded_at') if source_bound else None,
            'source_identity_status':'EXACT_NATIVE_READ_BYTES' if source_bound else 'SOURCE_ARTIFACT_ORIGIN_NOT_PROVEN',
            'own_tf':tf,'own_observations':identity,'used_m15_constituents':_tf_frame_identity(used),
            'own_last_observation_close':E._iso(own_times.max()+pd.Timedelta(minutes=minutes)) if len(own_times) else None,
            'mtf_inputs':{k:_tf_frame_identity(v['auction_states']) for k,v in components['results'].items()} if tf=='M15' else {},
            'historical_source_publication':source_publication,
            'historical_result_availability':'NOT_EXISTING_BEFORE_NATIVE_PUBLICATION'}
        payload = {'timestamp':target_bar,'target_tf':tf,'source_timeframe':tf,'target_bar':target_bar,
            'target_bar_close':target_close,'analysis_status':status,'mtf_status':mtf_status,
            'native_component':'process_auction_climax','native_event_count':len(events),
            'native_events_json':E._bytes(values).decode(),'native_mtf_json':E._bytes(mtf).decode(),
            'provenance_json':E._bytes(provenance).decode(),'producer':STAGE2_ENGINE,
            'producer_version':'sha256:'+hashlib.sha256(__import__('pathlib').Path(__file__).read_bytes()).hexdigest(),
            'decision_influence':'NONE_NO_NEW_POLICY'}
        result[tf] = pd.DataFrame([payload])
    return result


def publish_tf_native_results(frames):
    """Four native datasets via the existing post-write SHA/UTC writer."""
    from pathlib import Path
    import json
    import stage2_publication_metadata as H
    from storage.path_registry import resolve_canonical
    from btc_ml.external_traders import context_stage2_evidence as E
    publications = {}
    for tf, frame in frames.items():
        name=TF_OUTPUTS[tf];H.TARGETS[name]=('cognition',STAGE2_ENGINE)
        path=Path(resolve_canonical(name))
        history=pd.read_parquet(path) if path.exists() else pd.DataFrame()
        if len(history):
            duplicates=history.loc[pd.to_datetime(history.timestamp,utc=True)==pd.to_datetime(frame.timestamp,utc=True).iloc[0]]
            if len(duplicates):
                # Immutable first publication. Never replace past analytical
                # output merely because current computation knows more.
                old=duplicates.iloc[-1]
                keys=['target_tf','target_bar','target_bar_close','analysis_status','mtf_status','native_event_count','native_events_json','native_mtf_json']
                if E._bytes(E._value(old[keys].to_dict()))!=E._bytes(E._value(frame.iloc[0][keys].to_dict())):
                    raise ValueError('TF_STAGE2_EXISTING_BAR_CONCLUSION_CONFLICT:'+tf)
                publications[tf]={'status':'UNCHANGED','artifact_sha256':H.digest(path.read_bytes())};continue
            frame=pd.concat([history,frame],ignore_index=True)
        H.publish_atomic_frame(frame,name,producer=__file__,writer=atomic_parquet_write)
        receipt=Path(str(path)+'.publication')/(H.digest(path.read_bytes())+'.meta.json')
        publications[tf]={'status':'PUBLISHED' if receipt.exists() else 'PUBLICATION_NOT_PROVEN',
            'artifact_sha256':H.digest(path.read_bytes()),'path':str(path)}
    return publications


if __name__ == "__main__":
    run()
