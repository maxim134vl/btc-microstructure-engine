"""R07.1: optional, immutable evidence delivery; never a trading input or gate.

The existing Final/Lifecycle writer remains the sole context authority. Sidecars
are visible only against matching published own-TF rows. Raw diagnostics are
separate from causally admitted evidence. No TTL or qualification is invented.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile

import pandas as pd

TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}
SIDECAR_ROOT = Path("data/cognition/context_stage2_evidence_v1")
# Exact installed native storage routes, not alternative root-file fallbacks.
SOURCES = {
    "volume_response": ("data/cognition/volume_response_state.parquet", "volume_response_engine_v1.py"),
    "convergence": ("data/reinforcement/auction_convergence_memory.parquet", "auction_convergence_engine_v1.py"),
    "runtime": ("data/cognition/runtime_cognition_memory.parquet", "stage2_cognition_runtime_v1.py"),
    "mtf": ("data/cognition/multi_timeframe_synthesis.parquet", "stage2_cognition_runtime_v1.py"),
    "probabilistic": ("data/probabilistic/probabilistic_auction_memory.parquet", "probabilistic_auction_engine_v1.py"),
    "meta": ("data/cognition/adaptive_meta_cognition_state.parquet", "adaptive_meta_cognition_engine_v1.py"),
    "intermediate": ("data/cognition/intermediate_cognition_memory.parquet", "intermediate_cognition_engine_v1.py"),
    "reinforcement": ("data/reinforcement/auction_reinforcement_memory.parquet", "auction_reinforcement_engine_v1.py"),
    "arbitration": ("data/cognition/auction_context_arbitration_memory.parquet", "auction_context_arbitration_engine_v1.py"),
    "decay": ("data/reinforcement/auction_decay_memory.parquet", "auction_decay_engine_v1.py"),
    "synthesis": ("data/reinforcement/auction_synthesis_memory.parquet", "auction_synthesis_engine_v1.py"),
    "transition": ("data/probabilistic/state_transition_memory.parquet", "state_transition_engine_v1.py"),
    "composite": ("data/cognition/runtime_cognition_composite.parquet", "runtime_cognition_engine_v1.py"),
}
# Original accepted R06 evidence, authenticated against its retained stdout,
# worker and exact execution command. These are evidence identities, not grants.
# No generated receipt can replace these bytes. No absolute research path is used.
RECORDED_PROOF_ROOT = SIDECAR_ROOT / "publication_records" / "r06-20261016"
RECORDED_PROOF_SHA256 = {
    "FIXED_FIRST_RESULT.json": "811f2a254b347b4efa870bf117a2ec500fecb6f3a306d264a9c0efa462b71b56",
    "fixed-first.log": "ac97e082e5a6ff7c1df069a0f40a584b5647b01a0a7ce178ea9668f32c02785c",
    "fixed-first-command.json": "21304b092d505383d68d40bc1ce50272ff3b2ad2a1105b1b1efa9d6e5fad9899",
    "SECOND_RESULT.json": "9c4e6cdc7f3911c179092cb5d4cd265eee5a51d7ec2c73c1e7f8b3b4ad64db4d",
    "second.log": "0e57e1e9c387d6a96ada9a64a3ccca6badcafe8fcd74cc7e37bcc2b0e034b3e2",
    "r06_worker.py": "0b4da8356fc51804d455b82b5c21da54a0a0c626608a14952243069fe5ebfbc0",
    "second-command.json": "fadfb3b1c7e1c4a6a882101ba3040086308218049fe88b3c0cc607d657001166",
}
R06_FIRST_IMAGE = "sha256:03d70d44da8a2f967640c638d4cfbf8440b74b45979148db7ec61eb7cd4a4fe3"
R06_IMAGE = "sha256:8945e8b09b0bd5e0310870cf86ed074d24ce00469757e8722df52723eda594f5"
CLOCKS = ("information_available_at", "available_at", "evaluated_at",
          "cognition_observed_at", "lineage_propagation_timestamp", "first_published_at",
          "auction_event_timestamp")


def _value(value):
    if isinstance(value, dict):
        return {str(k): _value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_value(v) for v in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if hasattr(value, "item"):
        return _value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_float": str(value)}
    return value


def _bytes(value):
    return json.dumps(_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _time(value):
    if value is None or value is pd.NaT:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed


def _iso(value):
    parsed = _time(value)
    return None if parsed is None else parsed.isoformat()


def _row_hash(row):
    # All columns, including decisions and version/episode identities, are bound.
    return _sha(_bytes(row.to_dict()))


def final_path(tf):
    if tf not in TF_MINUTES:
        raise ValueError("UNKNOWN_TIMEFRAME")
    base = Path("data/cognition") if tf == "M15" else Path("data/cognition/timeframes") / tf
    return base / "final_market_context_memory.parquet"


def _own_row(frame, tf, opened):
    if "timeframe" not in frame:
        raise ValueError("UNPROVEN_CONTEXT_OWNER")
    rows = frame.loc[(frame.timeframe.astype(str) == tf)
                     & (pd.to_datetime(frame.timestamp, utc=True) == opened)]
    if len(rows) != 1:
        raise ValueError("EXACT_CONTEXT_ROW_UNAVAILABLE")
    return rows.iloc[0]


def freeze_sources(root, stage):
    """Freeze raw bytes once; evidence copies never replace analytical inputs.

    Metadata is useful only if its native SHA matches these exact bytes. Missing
    metadata is retained as missing; neither mtime nor copying time is backdated.
    """
    folder = Path(stage) / SIDECAR_ROOT / "sources"
    folder.mkdir(parents=True, exist_ok=True)
    # Optional exact original execution records; never manufacture replacements.
    for name in RECORDED_PROOF_SHA256:
        original = Path(root) / RECORDED_PROOF_ROOT / name
        if original.exists():
            destination = Path(stage) / RECORDED_PROOF_ROOT / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(original.read_bytes())
    identities = {}
    for key, (rel, _) in {**SOURCES, **TF_NATIVE_SOURCES}.items():
        source = Path(stage) / rel
        if not source.exists():
            source = Path(root) / rel
        if not source.exists():
            continue
        raw = source.read_bytes()
        (folder / (key + ".parquet")).write_bytes(raw)
        original = (Path(root) / rel).resolve()
        identities[key] = str(original)
        version = Path(str(original) + ".publication") / (_sha(raw) + ".meta.json")
        if version.exists():
            (folder / (key + ".publication.json")).write_bytes(version.read_bytes())
        meta = Path(str(Path(root) / rel) + ".meta.json")
        if meta.exists():
            (folder / (key + ".meta.json")).write_bytes(meta.read_bytes())
    (folder / "source_paths.json").write_text(json.dumps(identities, sort_keys=True))


def recorded_publication_proof(stage):
    """Verify retained native execution evidence, not test-generated metadata.

    In the exact worker, each inputs proof (read bytes + SHA) precedes started_at.
    This proves availability NO LATER THAN that timestamp, not first publication.
    finished_at precedes outputs hashing, so it is not used as an availability
    witness. In particular the final Meta stage has no subsequent read witness.
    """
    folder = Path(stage) / RECORDED_PROOF_ROOT
    raw = {}
    for name, expected in RECORDED_PROOF_SHA256.items():
        path = folder / name
        if not path.exists():
            return {"status": "MISSING", "missing": name}
        raw[name] = path.read_bytes()
        if _sha(raw[name]) != expected:
            return {"status": "REJECTED_SHA", "file": name}
    reports = []
    for record_name, log, cmd, image in (
            ("FIXED_FIRST_RESULT.json", "fixed-first.log", "fixed-first-command.json", R06_FIRST_IMAGE),
            ("SECOND_RESULT.json", "second.log", "second-command.json", R06_IMAGE)):
        report = json.loads(raw[record_name])
        records = [line[len("R06_RESULT "):] for line in raw[log].decode().splitlines()
                   if line.startswith("R06_RESULT ")]
        command = json.loads(raw[cmd])
        if len(records) != 1 or json.loads(records[0]) != report or image not in command:
            return {"status": "REJECTED_PROVENANCE"}
        reports.append({"name": record_name, "report": report, "image": image})
    return {"status": "VERIFIED_ORIGINAL_EXECUTION_RECORD", "reports": reports,
            "sha256": RECORDED_PROOF_SHA256.copy()}


def _read_witness(source, proof):
    if proof["status"] != "VERIFIED_ORIGINAL_EXECUTION_RECORD":
        return None
    expected_path = "/app/" + source["source_path"]
    witnesses = []
    for original in proof["reports"]:
        stages = original["report"]["stages"]
        producer_indexes = [i for i, stage in enumerate(stages)
                            if (stage["status"] == "SUCCESS" or
                                (stage["status"] == "SKIPPED" and stage.get("reason") == "INPUT_UNCHANGED"))
                            and stage["engine"] == source["source_module"]
                            and any(record.get("path") == expected_path and record.get("sha256") == source["sha256"]
                                    for record in stage.get("outputs", {}).values())]
        if not producer_indexes:
            continue
        for i, stage in enumerate(stages):
            if i <= min(producer_indexes):
                continue
            matched = [record for record in stage.get("inputs", {}).values()
                       if record.get("path") == expected_path and record.get("sha256") == source["sha256"]]
            at = _time(stage.get("started_at"))
            if matched and at is not None:
                witnesses.append({"kind": "ORIGINAL_EXECUTION_SHA_READ_BEFORE_CLOCK",
                                  "available_by": at.isoformat(), "exact_publication_timestamp": None,
                                  "consumer": stage["engine"], "consumer_stage_index": i,
                                  "producer_stage_index": min(producer_indexes),
                                  "producer_status": stages[min(producer_indexes)]["status"],
                                  "claim": "ALREADY_PUBLISHED_BYTES_OBSERVED_NOT_A_NEW_PUBLICATION",
                                  "source_path": expected_path, "source_sha256": source["sha256"],
                                  "image": original["image"], "original_record_name": original["name"],
                                  "original_records_sha256": proof["sha256"]})
    return min(witnesses, key=lambda w: _time(w["available_by"])) if witnesses else None


def _metadata_witness(source, lower):
    meta = source["metadata"]
    if meta.get("publication_evidence_version"):
        # Extended post-write records require their immutable version receipt;
        # never downgrade a malformed new manifest into generic legacy authority.
        return None
    written = _time(meta.get("written_at"))
    expected_writers = {source["source_module"]}
    if source["source_path"] == SOURCES["runtime"][0]:
        expected_writers.add("runtime_cognition_engine_v1.py")
    valid = (meta.get("file_sha256") == source["sha256"]
             and meta.get("dataset_path") == source["source_path"]
             and meta.get("dataset_id") == Path(source["source_path"]).stem
             and meta.get("writer_entrypoint") in expected_writers
             and meta.get("metadata_origin") == "LIVE_WRITER"
             and meta.get("last_write_status") == "OK" and not meta.get("error_code")
             and written is not None and written >= lower)
    if not valid:
        return None
    # Existing build_dataset_metadata hashes the public bytes BEFORE written_at.
    # Thus written_at is an observation bound, not the replace/first-publication instant.
    return {"kind": "SHA_BOUND_LIVE_WRITER_METADATA", "available_by": written.isoformat(),
            "exact_publication_timestamp": None, "metadata_sha256": source["metadata_sha256"]}


def _post_write_witness(source, lower):
    meta = source.get("publication_metadata") or {}
    proof = meta.get("publication_evidence") or {}
    contract = proof.get("source_contract") or {}
    logical = source["source_path"]
    filename = Path(logical).name
    category = Path(logical).parent.name
    completed = _time(proof.get("publication_completed_at"))
    written = _time(meta.get("written_at"))
    producer = source["source_module"]
    expected_id = _sha(_bytes({"contract": "stage2_post_write_publication_v1",
                              "dataset_path": logical, "file_sha256": source["sha256"]}))
    valid = (meta.get("metadata_origin") == "LIVE_WRITER"
             and meta.get("publication_evidence_version") == "stage2_post_write_publication_v1"
             and meta.get("dataset_path") == logical and meta.get("dataset_id") == Path(logical).stem
             and meta.get("writer_entrypoint") == producer
             and meta.get("file_sha256") == source["sha256"]
             and meta.get("last_write_status") == "OK" and not meta.get("error_code")
             and meta.get("publication_evidence_sha256") == _sha(_bytes(proof))
             and proof.get("receipt_id") == expected_id and proof.get("artifact_sha256") == source["sha256"]
             and proof.get("dataset_path") == logical and proof.get("dataset_id") == Path(logical).stem
             and proof.get("artifact_absolute_path") == source.get("source_storage_path")
             and source.get("source_storage_path") is not None
             and proof.get("producer") == producer and proof.get("write_completed") is True
             and proof.get("publication_environment") == source.get("expected_publication_environment")
             and proof.get("publication_environment") in ("NATIVE_RUNTIME", "ISOLATED")
             and proof.get("write_method") in ("atomic_parquet_write", "append_state_row")
             and proof.get("timestamp_kind") == "POST_WRITE_COMPLETION_CONFIRMATION"
             and contract == {"registry": "storage.path_registry.PARQUET_REGISTRY",
                              "filename": filename, "category": category,
                              "producer": producer, "source_timestamp_field": "timestamp"}
             and isinstance(proof.get("producer_source_sha256"), str)
             and len(proof["producer_source_sha256"]) == 64
             and completed is not None and written is not None and lower <= completed <= written)
    if not valid:
        return None
    result = {"kind": "SHA_BOUND_NATIVE_POST_WRITE_PUBLICATION",
            "timestamp_kind": "POST_WRITE_COMPLETION_CONFIRMATION",
            "available_by": completed.isoformat(), "publication_completed_at": completed.isoformat(),
            "exact_first_historical_publication_timestamp": None,
            "source_path": logical, "source_sha256": source["sha256"],
            "producer_source_sha256": proof["producer_source_sha256"],
            "publication_environment": proof.get("publication_environment"),
            "version_receipt_sha256": source.get("publication_metadata_sha256")}
    if 'input_lineage' in proof:
        result['input_lineage'] = proof['input_lineage']
        result['input_lineage_sha256'] = proof.get('input_lineage_sha256')
    return result


def load_sources(stage, *, specifications=None):
    result = {}
    execution_proof = recorded_publication_proof(stage)
    folder = Path(stage) / SIDECAR_ROOT / "sources"
    identities_path = folder / "source_paths.json"
    identities = json.loads(identities_path.read_bytes()) if identities_path.exists() else {}
    for key, (rel, module) in (SOURCES if specifications is None else specifications).items():
        base = {"source_path": rel, "source_module": module,
                "source_storage_path": identities.get(key),
                "expected_publication_environment": os.environ.get("BTC_ML_PUBLICATION_EVIDENCE_SCOPE", "NATIVE_RUNTIME")}
        path = folder / (key + ".parquet")
        if not path.exists():
            result[key] = {**base, "status": "MISSING"}
            continue
        raw = path.read_bytes()
        try:
            frame = pd.read_parquet(io.BytesIO(raw))
            if "timestamp" not in frame:
                raise ValueError("SOURCE_TIMESTAMP_MISSING")
            frame = frame.copy()
            frame["_source_timestamp"] = pd.to_datetime(frame.timestamp, utc=True, errors="coerce")
            if frame._source_timestamp.isna().any():
                raise ValueError("SOURCE_TIMESTAMP_INVALID")
            meta_path = folder / (key + ".meta.json")
            meta_raw = meta_path.read_bytes() if meta_path.exists() else None
            meta = json.loads(meta_raw) if meta_raw else {}
            publication_path = folder / (key + ".publication.json")
            publication_raw = publication_path.read_bytes() if publication_path.exists() else None
            try:
                publication = json.loads(publication_raw) if publication_raw else None
            except (ValueError, TypeError):
                publication = None
            result[key] = {**base, "status": "PRESENT", "sha256": _sha(raw),
                           "frame": frame, "metadata": meta,
                           "metadata_sha256": _sha(meta_raw) if meta_raw else None,
                           "publication_metadata": publication,
                           "publication_metadata_sha256": _sha(publication_raw) if publication_raw else None}
            result[key]["execution_proof_status"] = execution_proof["status"]
            result[key]["recorded_read_witness"] = _read_witness(result[key], execution_proof)
        except (ValueError, OSError, TypeError) as exc:
            result[key] = {**base, "status": "UNREADABLE", "sha256": _sha(raw),
                           "reason": type(exc).__name__ + ":" + str(exc)}
    return result


def _observation(source, close):
    base = {k: v for k, v in source.items() if k not in ("frame", "metadata", "publication_metadata")}
    if source["status"] != "PRESENT":
        return base
    frame = source["frame"]
    # Latest already-labelled source observation, not nearest prior target TF state.
    rows = frame.loc[frame._source_timestamp <= close].sort_values("_source_timestamp", kind="stable")
    if not len(rows):
        return {**base, "status": "CAUSALLY_UNAVAILABLE", "reason": "NO_SOURCE_AT_OR_BEFORE_CLOSE"}
    timestamp = rows._source_timestamp.iloc[-1]
    latest = rows.loc[rows._source_timestamp == timestamp]
    # Never pick an arbitrary row among conflicting same-clock observations.
    if len({_row_hash(r.drop(labels=["_source_timestamp"])) for _, r in latest.iterrows()}) != 1:
        return {**base, "status": "CONFLICTING", "reason": "AMBIGUOUS_SOURCE_TIMESTAMP"}
    row = latest.iloc[-1].drop(labels=["_source_timestamp"])
    fields = _value(row.to_dict())
    clocks = {k: _iso(row.get(k)) for k in CLOCKS if _time(row.get(k)) is not None}
    lower = max([timestamp] + [_time(v) for v in clocks.values()])
    meta = source["metadata"]
    # Preserve the observed bound separately from the unknown publication instant.
    recorded = source.get("recorded_read_witness")
    if recorded is not None and (recorded.get("source_sha256") != source["sha256"]
                                 or recorded.get("source_path") != "/app/" + source["source_path"]):
        recorded = None
    witnesses = [w for w in (_metadata_witness(source, lower), _post_write_witness(source, lower), recorded)
                 if w is not None and _time(w["available_by"]) >= lower]
    witness = min(witnesses, key=lambda w: _time(w["available_by"])) if witnesses else None
    available_by = _time(witness["available_by"]) if witness else None
    causal_status = ("CAUSALLY_UNAVAILABLE" if lower > close else
                     "AT_OR_BEFORE_CLOSE" if available_by is not None and available_by <= close
                     else "AVAILABILITY_NOT_PROVEN")
    origin = str(row.get("lifecycle_source", row.get("source_origin", "")))
    proxy = "PROXY" in origin.upper()
    shadow = row.get("shadow_only", False)
    status = "GENUINE_CANONICAL_EVIDENCE"
    if proxy:
        status = "HTF_PROXY"
    elif shadow is not pd.NA and pd.notna(shadow) and bool(shadow):
        status = "SHADOW_EVIDENCE"
    elif causal_status == "CAUSALLY_UNAVAILABLE":
        status = "CAUSALLY_UNAVAILABLE"
    elif causal_status != "AT_OR_BEFORE_CLOSE":
        status = "AVAILABILITY_NOT_PROVEN"
    original_tf = row.get("source_timeframe", row.get("timeframe"))
    # UNSPECIFIED is not M15, and the target TF is never assigned to the source.
    original_tf = None if original_tf is None or pd.isna(original_tf) else str(original_tf)
    return {**base, "status": status, "fields": fields, "source_row_sha256": _row_hash(row),
            "source_timeframe": original_tf,
            "source_scope": "RECORDED" if original_tf else "NOT_RECORDED",
            "source_event_timestamp": _iso(row.get("lineage_event_timestamp", row.get("source_candle_timestamp"))),
            "timestamp_role": ("PROCESSING_TIME" if source["source_module"] in
                               ("auction_synthesis_engine_v1.py", "auction_decay_engine_v1.py",
                                "auction_convergence_engine_v1.py", "volume_response_engine_v1.py")
                               else "SOURCE_OBSERVATION"),
            "causal_status": causal_status,
            "publication_metadata": {k: meta.get(k) for k in
                                     ("file_sha256", "written_at", "metadata_origin", "last_write_status")},
            "source_observation_timestamp": timestamp.isoformat(),
            "recorded_clocks": clocks, "availability_lower_bound": lower.isoformat(),
            "actual_available_at": None, "available_by": _iso(available_by),
            "availability_timestamp_kind": witness.get("timestamp_kind", "OBSERVED_UPPER_BOUND") if witness else "NOT_PROVEN",
            "publication_completed_at": witness.get("publication_completed_at") if witness else None,
            "availability_witness": witness,
            "availability_proof": witness["kind"] if witness else "MISSING_OR_UNBOUND_PUBLICATION_METADATA",
            "freshness": "NOT_ESTABLISHED_NO_NEW_TTL",
            "own_timeframe_confirmation": False}


def _path(root, tf, opened):
    if tf not in TF_MINUTES:
        raise ValueError("UNKNOWN_TIMEFRAME")
    return Path(root) / SIDECAR_ROOT / tf / (opened.strftime("%Y%m%dT%H%M%SZ") + ".json")


def _binding(root, tf, opened):
    final = _own_row(pd.read_parquet(Path(root) / final_path(tf)), tf, opened)
    life = _own_row(pd.read_parquet(Path(root) / "data/cognition/market_context_lifecycle_memory.parquet"), tf, opened)
    close = opened + pd.Timedelta(minutes=TF_MINUTES[tf])
    for row in (final, life):
        for name, expected in (("source_bar_open", opened), ("source_bar_close", close)):
            actual = _time(row.get(name))
            if actual is not None and actual != expected:
                raise ValueError("CONFLICTING_CONTEXT_BAR_BINDING")
    return {"timeframe": tf, "bar_open": opened.isoformat(), "bar_close": close.isoformat(),
            "final_row_sha256": _row_hash(final), "lifecycle_row_sha256": _row_hash(life),
            "context_episode_id": _value(life.get("context_episode_id")),
            "final_builder_version": _value(final.get("builder_version")),
            "context_origin": _value(life.get("lifecycle_source")),
            "historical_context_publication_authority": "NOT_PROVEN"}


def deliver_bar(root, tf, opened, sources, *, consumer_record=None):
    opened = _time(opened)
    if opened is None or opened != opened.floor(str(TF_MINUTES[tf]) + "min"):
        raise ValueError("INVALID_CONTEXT_BAR")
    binding = _binding(root, tf, opened)
    path = _path(root, tf, opened)
    if path.exists():
        # First immutable delivery wins, including missing/late diagnostics.
        read_context_evidence(root, tf, opened)
        return {"status": "UNCHANGED", "path": str(path)}
    close = _time(binding["bar_close"])
    observations = {key: _observation(value, close) for key, value in sources.items() if key in SOURCES}
    bind_meta_target_inputs(sources, observations, tf, close)
    context = (consumer_record or {}).get('own_tf_decision_snapshot')
    own = load_tf_native_evidence_from_sources(sources, tf, opened, decision_context=context)
    if own is not None:
        observations['own_tf_stage2'] = own
    for key, item in observations.items():
        if tf == "M15" and key in ("runtime", "composite") and item.get("source_observation_timestamp"):
            # Unchanged native build_auction_episode_memory.py cognition_max_age.
            age = opened - _time(item["source_observation_timestamp"])
            item["native_m15_asof_freshness"] = {
                "status": "STALE" if age > pd.Timedelta(minutes=45) else "WITHIN_NATIVE_MAX_AGE",
                "age_seconds": age.total_seconds(), "max_age_seconds": 2700,
                "contract": "build_auction_episode_memory.py::build_auction_episode_rows::_asof_cols",
                "applies_to": ["trigger_event", "location_bias"], "diagnostic_only": True}
        item["own_timeframe_confirmation"] = (item["status"] == "GENUINE_CANONICAL_EVIDENCE"
                                                and item.get("source_timeframe") == tf)
    body = {"schema": "CONTEXT_STAGE2_EVIDENCE_V1", "binding": binding,
            "recorded_at": datetime.now(timezone.utc).isoformat(), "observations": observations,
            "use": "METADATA_ONLY_NO_QUALIFICATION_OR_TRADING_AUTHORITY"}
    if consumer_record is not None:
        from btc_ml.external_traders.stage2_predecision_evidence import bind_consumption_after_decision
        final = _own_row(pd.read_parquet(Path(root) / final_path(tf)), tf, opened)
        life = _own_row(pd.read_parquet(Path(root) / 'data/cognition/market_context_lifecycle_memory.parquet'), tf, opened)
        body['native_consumption'] = bind_consumption_after_decision(
            consumer_record, binding, observations, final, life)
    payload = _bytes({"content_sha256": _sha(_bytes(body)), "evidence": body})
    path.parent.mkdir(parents=True, exist_ok=True)
    # Existing publisher single-writer ownership is unchanged.
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"status": "CREATED", "path": str(path)}


def read_context_evidence(root, tf, opened):
    """Explicit read-only interface; diagnostic values are never silently admitted."""
    opened = _time(opened)
    envelope = json.loads(_path(root, tf, opened).read_bytes())
    body = envelope["evidence"]
    if _sha(_bytes(body)) != envelope["content_sha256"]:
        raise ValueError("CORRUPT_EVIDENCE")
    if body["binding"] != _binding(root, tf, opened):
        raise ValueError("EVIDENCE_CONTEXT_BINDING_MISMATCH")
    admitted = {k: v for k, v in body["observations"].items()
                if v["status"] == "GENUINE_CANONICAL_EVIDENCE"
                and _time(v.get("available_by", v.get("actual_available_at"))) is not None
                and _time(v.get("available_by", v.get("actual_available_at"))) <= _time(body["binding"]["bar_close"])}
    return {**body, "admitted": admitted}


def publish_completed_with_evidence(root, stage, tf, lifecycle, episodes, artifacts, *, context_phase=False, context_phase_scope="NATIVE_RUNTIME"):
    """Keep native activation intact. Evidence failure cannot become a new gate."""
    from btc_ml.external_traders.incremental_context_publication import publish_completed
    life_path = Path(root) / "data/cognition/market_context_lifecycle_memory.parquet"
    old = pd.read_parquet(life_path) if life_path.exists() else None
    previous = None if old is None else old.loc[old.timeframe.astype(str) == tf]
    phase_witness = None
    if context_phase:
        from btc_ml.external_traders.context_phase_publication import prepare_native_publication
        phase_witness = prepare_native_publication(root, stage, tf, lifecycle)
    record = publish_completed(root, stage, tf, lifecycle, episodes, artifacts)
    try:
        candidates = lifecycle
        if previous is not None and len(previous):
            candidates = lifecycle.loc[pd.to_datetime(lifecycle.timestamp, utc=True)
                                       > pd.to_datetime(previous.timestamp, utc=True).max()]
        # Retry an interrupted evidence delivery for the current tip only.
        if not len(candidates):
            candidates = lifecycle.tail(1)
        sources = load_sources(stage)
        sources.update(load_sources(stage, specifications=TF_NATIVE_SOURCES))
        from btc_ml.external_traders.stage2_predecision_evidence import load_prepared_consumption
        deliveries = [deliver_bar(root, tf, row.timestamp, sources,
                                 consumer_record=load_prepared_consumption(stage, tf, row.timestamp))
                      for _, row in candidates.iterrows()]
        record["stage2_evidence"] = {"status": "DELIVERED", "deliveries": deliveries}
    except Exception as exc:
        record["stage2_evidence"] = {"status": "UNAVAILABLE", "reason": type(exc).__name__ + ":" + str(exc)}
    if context_phase:
        try:
            from btc_ml.external_traders.context_phase_publication import publish_context_phase
            phase_witness["source_publication_completed_at"] = record["published_at"]
            record["context_phase"] = publish_context_phase(
                root, tf, source_witness=phase_witness, scope=context_phase_scope)
        except Exception as exc:
            # A failed sidecar is NOT_PROVEN to its reader; canonical publication
            # remains untouched, and an older phase cannot bind to a new bar.
            record["context_phase"] = {"status":"NOT_PROVEN", "reason":type(exc).__name__+":"+str(exc)}
    return record


def bind_meta_target_inputs(sources, observations, tf, close):
    """Bind the SAME reader-selected pair to this own-TF candidate computation.

    No source TF is assigned, no source event is reparented to Lifecycle.
    For old Meta receipts without input lineage, preserve the old view exactly.
    """
    meta = observations.get('meta', {})
    witness = meta.get('availability_witness') or {}
    if 'input_lineage' not in witness:
        return
    import stage2_publication_metadata as H
    inputs = {}
    for key in ('probabilistic', 'reinforcement'):
        source = sources[key];item = observations[key]
        descriptor = {'source_path': SOURCES[key][0], 'artifact_sha256': source.get('sha256'),
                      'artifact_absolute_path': source.get('source_storage_path'),
                      'status': item.get('status'), 'causal_status': item.get('causal_status'),
                      'freshness': item.get('freshness')}
        if 'frame' in source:
            frame = source['frame'].drop(columns=['_source_timestamp'])
            if key == 'probabilistic':
                match = item.get('source_row_sha256')
                indexes = [i for i in range(len(frame)) if _row_hash(frame.iloc[i]) == match]
                selected = frame.iloc[indexes[-1:]]
            else:
                selected = frame.tail(50)
            descriptor.update({'used_frame': H.meta_frame_identity(frame),
                'selection': H.meta_selection_identity(selected),
                'selection_rule': 'STATE.iloc[-1]' if key == 'probabilistic' else 'tail(50)'})
        inputs[key] = descriptor
    meta['target_inputs'] = {'timeframe': tf, 'cutoff': _iso(close), 'inputs': inputs}


TF_NATIVE_SOURCES = {'own_tf_' + tf: ('data/cognition/stage2_' + tf.lower() + '_native_memory.parquet',
                                    'stage2_cognition_runtime_v1.py') for tf in TF_MINUTES}
TF_NATIVE_PRODUCER_SHA256 = '1a263350750d7402001785e2fb48a6c40ce4532eab5e4815c37ebdd498539e71'
# Exact accepted producer implementations; numerical methodology is unchanged.
TF_NATIVE_PRODUCER_SHA256_ACCEPTED = frozenset({TF_NATIVE_PRODUCER_SHA256,
    '4912f8ddf7d3e7fc6744cfb7ef573ff665440e6dc08ab352f5c2bd003d596f9d', '71ea175d892e7afce12a9ca53e9d22da0e397cc4b120821d2f7a6656c759c02d'})


def load_tf_native_evidence_from_sources(sources, tf, opened, *, decision_context=None):
    source = sources.get('own_tf_' + tf)
    if source is None or source.get('status') == 'MISSING':
        return None
    if source.get('status') == 'PRESENT':
        rows=source['frame'].loc[source['frame']._source_timestamp == opened]
        if len(rows):source={**source,'frame':rows}
    item = _observation(source, opened + pd.Timedelta(minutes=TF_MINUTES[tf]))
    fields = item.get('fields', {})
    if fields:
        if (fields.get('target_tf') != tf or _time(fields.get('target_bar')) != opened
                or _time(fields.get('target_bar_close')) != opened + pd.Timedelta(minutes=TF_MINUTES[tf])):
            item['status'] = 'INCOMPATIBLE_TF_OR_BAR'
            item['reason'] = 'EXACT_OWN_TF_RESULT_REQUIRED_NO_ASOF_OTHER_TARGET'
        witness = item.get('availability_witness') or {}
        if (witness.get('kind') != 'SHA_BOUND_NATIVE_POST_WRITE_PUBLICATION'
                or witness.get('producer_source_sha256') not in TF_NATIVE_PRODUCER_SHA256_ACCEPTED):
            item['status'] = 'AVAILABILITY_NOT_PROVEN'
        try:
            provenance = json.loads(fields['provenance_json'])
            if provenance['source_identity_status'] != 'EXACT_NATIVE_READ_BYTES':
                item['status'] = 'SOURCE_ARTIFACT_ORIGIN_NOT_PROVEN'
        except (KeyError, TypeError, ValueError):
            item['status'] = 'SOURCE_ARTIFACT_ORIGIN_NOT_PROVEN'
    item['analysis_available'] = str(fields.get('analysis_status','')).startswith(('CALCULATED','PARTIAL_'))
    completed = _time((item.get('availability_witness') or {}).get('publication_completed_at'))
    if completed is not None and completed < opened + pd.Timedelta(minutes=TF_MINUTES[tf]):
        item['status'] = 'CAUSALLY_UNAVAILABLE'
    item['own_timeframe_confirmation'] = (item.get('status') == 'GENUINE_CANONICAL_EVIDENCE' and item.get('source_timeframe') == tf)
    if decision_context is not None:
        item['decision_admission'] = _own_tf_processing_admission(item,source,tf,opened,decision_context)
    item['scope'] = 'OWN_TF_NATIVE_COMPONENTS_NOT_SHARED_META'
    return item


def load_tf_native_evidence(stage, tf, opened, *, decision_context=None):
    sources = load_sources(stage, specifications=TF_NATIVE_SOURCES)
    return load_tf_native_evidence_from_sources(sources, tf, opened, decision_context=decision_context)


# Separate processing-time admission. _observation and all historical/shared
# status/cutoff semantics above remain EXACTLY unchanged.
def _own_tf_processing_admission(item, source, tf, opened, context):
    result={'admitted':False,'decision_as_of':context.get('decision_as_of'),
            'market_data_cutoff':context.get('market_data_cutoff'),
            'snapshot_sha256':context.get('snapshot_sha256'),'reason':'OWN_TF_EVIDENCE_UNPROVEN'}
    fields=item.get('fields',{});witness=item.get('availability_witness') or {}
    if not context.get('candidate_new'):
        result['reason']=context.get('candidate_reason');return result
    if (not item.get('analysis_available') or fields.get('target_tf')!=tf
            or fields.get('source_timeframe')!=tf or _time(fields.get('target_bar'))!=opened
            or item.get('scope') not in (None,'OWN_TF_NATIVE_COMPONENTS_NOT_SHARED_META')
            or witness.get('kind')!='SHA_BOUND_NATIVE_POST_WRITE_PUBLICATION'
            or witness.get('producer_source_sha256') not in TF_NATIVE_PRODUCER_SHA256_ACCEPTED):return result
    pub=_time(witness.get('publication_completed_at'));asof=_time(context.get('decision_as_of'))
    cutoff=_time(context.get('market_data_cutoff'));closed=_time(fields.get('target_bar_close'))
    result.update(source_bar_close=_iso(closed),publication_completed_at=_iso(pub))
    if asof is None or pub is None or pub>asof:
        result['reason']='PUBLICATION_AFTER_DECISION_AS_OF';return result
    pinned=context.get('source_versions',{}).get('own_tf_'+tf,{})
    if (pinned.get('sha256')!=source.get('sha256')
            or pinned.get('receipt_sha256')!=source.get('publication_metadata_sha256')):
        result['reason']='SOURCE_VERSION_CHANGED_AFTER_SNAPSHOT';return result
    try:
        provenance=json.loads(fields['provenance_json'])
        used=_time(provenance.get('own_last_observation_close'));read=_time(provenance.get('source_read_at'))
        events=json.loads(fields['native_events_json'])
        duration=pd.Timedelta(minutes=TF_MINUTES[tf])
        if (provenance.get('source_identity_status')!='EXACT_NATIVE_READ_BYTES'
                or closed!=opened+duration or used!=closed or cutoff is None
                or used is None or used>cutoff or cutoff>asof
                or read is None or not closed<=read<=pub
                or any(_time(e.get('timestamp')) is None or _time(e['timestamp'])+duration>used for e in events)):
            result['reason']='MARKET_OR_QUALIFIER_CUTOFF_NOT_PROVEN';return result
    except (KeyError,ValueError,TypeError):return result
    result.update(admitted=True,reason='OWN_TF_PUBLICATION_AVAILABLE_BEFORE_FIXED_DECISION',
                  values_evaluated_asof=_iso(used),source_read_at=_iso(read))
    return result
