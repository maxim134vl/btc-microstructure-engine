"""Post-write evidence for four native Stage2 outputs; no analytical changes.

Only these wrappers can create new receipts: the native writer must first return
successfully. UTC completion is sampled immediately after return, before reading
or hashing the public file. This is a post-write confirmation, not an invented
first historical publication. Existing metadata writer supplies atomic JSON IO.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
import warnings

import pandas as pd
from runtime_engine_guard import EngineTimeoutError

SCHEMA = "stage2_post_write_publication_v1"
TARGETS = {
    "runtime_cognition_memory.parquet": ("cognition", "stage2_cognition_runtime_v1.py"),
    "multi_timeframe_synthesis.parquet": ("cognition", "stage2_cognition_runtime_v1.py"),
    "probabilistic_auction_memory.parquet": ("probabilistic", "probabilistic_auction_engine_v1.py"),
    "adaptive_meta_cognition_state.parquet": ("cognition", "adaptive_meta_cognition_engine_v1.py"),
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _iso(value):
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(pd.to_datetime(value, utc=True)).isoformat()


def receipt_id(dataset_path, artifact_sha256):
    return digest(encode({"contract": SCHEMA, "dataset_path": dataset_path,
                          "file_sha256": artifact_sha256}))


def _sync_parent(path):
    fd = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _json_at(payload, destination):
    from runtime_dataset_metadata import write_dataset_metadata_atomic
    # Existing helper appends .meta.json. Explicit dataset_path controls only
    # destination; the payload retains its original canonical artifact identity.
    destination = Path(destination)
    assert str(destination).endswith(".meta.json")
    write_dataset_metadata_atomic(payload, dataset_path=str(destination)[:-len(".meta.json")])
    _sync_parent(destination)


def _atomic_original(raw, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(raw);handle.flush();os.fsync(handle.fileno())
            os.replace(temporary, destination)
            _sync_parent(destination)
        finally:
            temporary.unlink(missing_ok=True)


def _validate_existing(receipt, logical, expected_sha, absolute):
    proof = receipt.get("publication_evidence", {})
    if (receipt.get("publication_evidence_version") != SCHEMA
            or receipt.get("dataset_path") != logical or receipt.get("file_sha256") != expected_sha
            or proof.get("dataset_path") != logical or proof.get("artifact_sha256") != expected_sha
            or proof.get("write_completed") is not True
            or proof.get("timestamp_kind") != "POST_WRITE_COMPLETION_CONFIRMATION"
            or proof.get("artifact_absolute_path") != absolute
            or proof.get("receipt_id") != receipt_id(logical, expected_sha)
            or receipt.get("publication_evidence_sha256") != digest(encode(proof))):
        raise ValueError("PUBLICATION_HISTORY_IDENTITY_CONFLICT")


class _ParquetDigestSink(io.RawIOBase):
    """The same serialized bytes/SHA, without retaining another full artifact."""
    def __init__(self):
        super().__init__()
        self.sha256 = hashlib.sha256()
        self.position = 0
    def writable(self):
        return True
    def write(self, data):
        self.sha256.update(data)
        self.position += len(data)
        return len(data)
    def tell(self):
        return self.position


def _artifact_identity(path):
    # Hash all actual bytes through one open file, as read_bytes did, with
    # bounded memory. Existing subsequent replacement checks remain unchanged.
    value = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
            size += len(chunk)
    return value.hexdigest(), size


def _file_signature(path):
    st = Path(path).stat()
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


# One immediate caller may reuse the SHA just proven for the same native write.
# No persisted token, cross-process authority, or trading permission is created.
_CONFIRMED_NATIVE_WRITE = {}


def confirmed_artifact_sha(path):
    key = str(Path(path).resolve())
    saved = _CONFIRMED_NATIVE_WRITE.pop(key, None)
    if saved is not None and _file_signature(path) == saved[0]:
        return saved[1]
    return _artifact_identity(path)[0]


def _confirm(frame, name, producer, completed_at, method, input_lineage=None, expected_serialization_sha=None):
    from storage.path_registry import PARQUET_REGISTRY, resolve_canonical
    filename = Path(name).name
    category, owner = TARGETS[filename]
    source = Path(producer).resolve()
    if source.name != owner or PARQUET_REGISTRY.get(filename) != category:
        raise ValueError("PUBLICATION_SOURCE_CONTRACT_MISMATCH")
    target = Path(resolve_canonical(filename)).resolve()
    if Path(name).is_absolute() and Path(name).resolve() != target:
        raise ValueError("PUBLICATION_PATH_MISMATCH")
    logical = "data/" + category + "/" + filename
    # The unchanged native writer serializes index=False using the same API.
    # Match its returned/full input frame to the ACTUAL published bytes.
    if expected_serialization_sha is None:
        expected = _ParquetDigestSink();frame.to_parquet(expected, index=False)
        expected_sha = expected.sha256.hexdigest()
    else:
        expected_sha = expected_serialization_sha
    before_read = _file_signature(target)
    actual_sha, actual_size = _artifact_identity(target)
    confirmed_signature = _file_signature(target)
    if before_read != confirmed_signature:
        raise ValueError("PUBLICATION_CHANGED_DURING_CONFIRMATION")
    def current_sha():
        if _file_signature(target) == confirmed_signature:
            return actual_sha
        return _artifact_identity(target)[0]
    if actual_sha != expected_sha:
        raise ValueError("PUBLICATION_WRITTEN_BYTES_NOT_VERIFIED")
    if frame.empty or "timestamp" not in frame:
        raise ValueError("PUBLICATION_OBSERVATION_UNAVAILABLE")
    timestamps = pd.to_datetime(frame.timestamp, utc=True, errors="raise")
    if timestamps.isna().any():
        raise ValueError("PUBLICATION_OBSERVATION_INVALID")
    latest = frame.loc[timestamps.idxmax()]
    legacy_metadata_path = Path(str(target) + ".meta.json")
    history = target.parent / (target.name + ".publication")
    # Do not replace operational metadata or change writer-health consumers.
    metadata_path = history / "current.meta.json"
    version_path = history / (actual_sha + ".meta.json")
    absolute = str(target)
    if version_path.exists():
        metadata = json.loads(version_path.read_bytes())
        _validate_existing(metadata, logical, actual_sha, absolute)
        if input_lineage is not None and metadata['publication_evidence'].get('input_lineage') != input_lineage:
            raise ValueError('META_INPUT_LINEAGE_VERSION_CONFLICT_NO_RETROACTIVE_REWRITE')
    else:
        producer_sha = digest(source.read_bytes())
        tf = latest.get("source_timeframe", latest.get("timeframe"))
        tf = None if tf is None or pd.isna(tf) else str(tf)
        proof = {
            "receipt_id": receipt_id(logical, actual_sha), "artifact_sha256": actual_sha,
            "artifact_absolute_path": absolute, "dataset_path": logical,
            "dataset_id": target.stem, "producer": owner,
            "producer_source_sha256": producer_sha, "producer_version": "sha256:" + producer_sha,
            "write_method": method, "write_completed": True,
            "publication_completed_at": completed_at,
            "timestamp_kind": "POST_WRITE_COMPLETION_CONFIRMATION",
            "first_historical_publication_at": None,
            "source_observation_timestamp": _iso(timestamps.max()),
            "source_event_timestamp": _iso(latest.get("lineage_event_timestamp")),
            "source_timeframe": tf,
            "row_count": len(frame), "artifact_size_bytes": actual_size,
            "source_contract": {"registry": "storage.path_registry.PARQUET_REGISTRY",
                                "filename": filename, "category": category,
                                "producer": owner, "source_timestamp_field": "timestamp"},
            "publication_environment": os.environ.get("BTC_ML_PUBLICATION_EVIDENCE_SCOPE", "NATIVE_RUNTIME"),
        }
        if input_lineage is not None:
            proof['input_lineage'] = input_lineage
            proof['input_lineage_sha256'] = digest(encode(input_lineage))
        metadata = {
            "metadata_version": "runtime_dataset_metadata_v1",
            "metadata_origin": "LIVE_WRITER", "last_write_status": "OK", "error_code": None,
            "dataset_path": logical, "dataset_id": target.stem,
            "file_sha256": actual_sha, "row_count": len(frame), "column_count": len(frame.columns),
            "canonical_writer": "canonical_pipeline_loop", "writer_entrypoint": owner,
            "builder_version": "sha256:" + producer_sha,
            "source_market_timestamp": _iso(timestamps.max()),
            "evaluated_timestamp": _iso(timestamps.max()), "written_at": utc_now(),
            "publication_evidence_version": SCHEMA, "publication_evidence": proof,
            "publication_evidence_sha256": digest(encode(proof)),
        }
        # Never overwrite a legacy sidecar without preserving its exact bytes.
        if legacy_metadata_path.exists():
            previous = legacy_metadata_path.read_bytes()
            archive = history / ("prior-" + digest(previous) + ".original")
            if not archive.exists():
                archive = history / ("prior-" + digest(previous) + ".original")
                _atomic_original(previous, archive)
        # Recheck before a confirming manifest; a competing/unverified replacement
        # cannot be attributed to this write. Readers independently compare SHA.
        if current_sha() != actual_sha:
            raise ValueError("PUBLICATION_CHANGED_DURING_CONFIRMATION")
        _json_at(metadata, version_path)
    if current_sha() != actual_sha:
        raise ValueError("PUBLICATION_CURRENT_VERSION_CHANGED")
    # Reuse a valid receipt unchanged: no duplicate history or refreshed clocks.
    encoded = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    if not metadata_path.exists() or metadata_path.read_text() != encoded:
        _json_at(metadata, metadata_path)
    _CONFIRMED_NATIVE_WRITE[str(target)] = (confirmed_signature, actual_sha)
    # Keep this process-local immediate-write reuse bounded.
    while len(_CONFIRMED_NATIVE_WRITE) > len(TARGETS):
        _CONFIRMED_NATIVE_WRITE.pop(next(iter(_CONFIRMED_NATIVE_WRITE)))
    return metadata


def _publish(name, producer, write, full_frame, method, input_lineage=None, serialization_digest=None):
    result = write()  # Native exception propagates; no evidence on failed write.
    completed_at = utc_now()  # Sampled after writer return, BEFORE any re-read.
    try:
        _confirm(full_frame(result), name, producer, completed_at, method, input_lineage=input_lineage,
            expected_serialization_sha=(serialization_digest or {}).get("sha256"))
    except EngineTimeoutError:
        raise
    except Exception as exc:
        # Optional metadata must not alter analytical results or become a new gate.
        warnings.warn("STAGE2_PUBLICATION_UNPROVEN: " + type(exc).__name__ + ":" + str(exc),
                      RuntimeWarning, stacklevel=2)
        # Stage2 must not report success when its native confirmation failed.
        # Keep the existing optional behaviour for all other producers.
        if Path(producer).name == "stage2_cognition_runtime_v1.py":
            raise
    return result


def publish_atomic_frame(frame, name, *, producer, writer, input_lineage=None):
    from parquet_utils import atomic_parquet_write as native_writer
    if writer is native_writer and getattr(native_writer, "_supports_serialization_digest", False):
        serialized = {}
        return _publish(name, producer,
            lambda: writer(frame, name, _serialization_digest=serialized), lambda _: frame,
            "atomic_parquet_write", input_lineage=input_lineage, serialization_digest=serialized)
    return _publish(name, producer, lambda: writer(frame, name), lambda _: frame, "atomic_parquet_write", input_lineage=input_lineage)


def publish_append_frame(name, row, *, producer, writer):
    return _publish(name, producer, lambda: writer(name, row), lambda result: result, "append_state_row")

# R07.2e: exact source-read witnesses, carried in STATE attrs, never market rows.
META_INPUT_SCHEMA = 'META_COMPUTATION_INPUTS_V1'
META_READ_ATTR = '_stage2_exact_source_read_v1'


def meta_frame_identity(frame):
    # Row identity excludes DataFrame provenance attrs; retain them at owner.
    frame = pd.DataFrame(frame, copy=False)
    from btc_ml.external_traders import context_stage2_evidence as E
    rows = [E._row_hash(row) for _, row in frame.iterrows()]
    body = {'columns': list(frame.columns), 'dtypes': [str(v) for v in frame.dtypes],
            'index_dtype': str(frame.index.dtype), 'index': E._value(frame.index.tolist()),
            'rows': rows}
    return {'frame_sha256': digest(E._bytes(body)), 'row_sha256': rows, 'row_count': len(frame)}


def _source_snapshot_read(file_path, *, native_safe):
    """Same single-file pandas read; hash the VERY bytes decoded, not a reread.

    native_safe=True preserves safe_read_parquet's empty-on-missing/corrupt
    behavior at the final Probabilistic STATE synchronization call only.
    """
    from parquet_utils import _coerce_path
    resolved = _coerce_path(file_path, for_write=False)
    if native_safe and not os.path.exists(resolved):
        return pd.DataFrame()
    try:
        raw = Path(resolved).read_bytes()
        bytes_read_at = utc_now()
        frame = pd.read_parquet(io.BytesIO(raw))
        decoded_at = utc_now()
    except EngineTimeoutError:
        raise
    except Exception:
        if not native_safe:
            raise
        print();print('CORRUPTED PARQUET:');print(resolved)
        return pd.DataFrame()
    try:
        frame.attrs[META_READ_ATTR] = {
            'status': 'EXACT_NATIVE_READ_BYTES', 'reader_helper_source_sha256': digest(Path(__file__).read_bytes()), 'artifact_absolute_path': str(Path(resolved).resolve()),
            'artifact_sha256': digest(raw), 'artifact_size_bytes': len(raw),
            'bytes_read_at': bytes_read_at, 'decoded_at': decoded_at,
            **meta_frame_identity(frame)}
    except EngineTimeoutError:
        raise
    except Exception as exc:
        # Optional identity evidence cannot change native analytical inputs.
        warnings.warn('META_INPUT_READ_UNPROVEN:' + str(exc), RuntimeWarning)
    return frame


def read_probabilistic_state_with_evidence(file_path):
    return _source_snapshot_read(file_path, native_safe=True)


def read_meta_reinforcement_with_evidence(file_path):
    return _source_snapshot_read(file_path, native_safe=False)


def meta_selection_identity(frame):
    from btc_ml.external_traders import context_stage2_evidence as E
    identity = meta_frame_identity(frame)
    clocks = []
    for name in ('timestamp',) + E.CLOCKS:
        if name in frame:
            clocks.extend(E._iso(value) for value in frame[name] if E._time(value) is not None)
    tf_field = 'source_timeframe' if 'source_timeframe' in frame else 'timeframe'
    values = frame[tf_field] if tf_field in frame else pd.Series([None] * len(frame))
    identity.update({'source_timeframes': sorted({str(v) for v in values if pd.notna(v)}),
                     'unrecorded_timeframe_rows': int(sum(pd.isna(v) for v in values)),
                     'observation_clocks': sorted(set(clocks))})
    return identity


def capture_meta_inputs(probabilistic, reinforcement, latest, window):
    """Observe the actual STATE value/iloc[-1] and actual tail(50), unchanged."""
    from btc_ml.external_traders import context_stage2_evidence as E
    result = {'schema': META_INPUT_SCHEMA, 'capture_helper_source_sha256': digest(Path(__file__).read_bytes()), 'captured_at': utc_now(), 'inputs': {},
              'status': 'EXACT_READS_BOUND'}
    for key, frame, selection, logical, rule in (
            ('probabilistic', probabilistic, probabilistic.iloc[[-1]],
             'data/probabilistic/probabilistic_auction_memory.parquet', 'STATE.iloc[-1]'),
            ('reinforcement', reinforcement, window,
             'data/reinforcement/auction_reinforcement_memory.parquet', 'tail(50)')):
        read = frame.attrs.get(META_READ_ATTR)
        full = meta_frame_identity(frame)
        valid = (read is not None and read.get('status') == 'EXACT_NATIVE_READ_BYTES'
                 and read.get('frame_sha256') == full['frame_sha256'])
        if key == 'probabilistic':
            valid = valid and E._row_hash(latest) == E._row_hash(selection.iloc[0])
        else:
            valid = valid and meta_frame_identity(window) == meta_frame_identity(frame.tail(50))
        if not valid:
            result['status'] = 'INPUT_ORIGIN_NOT_PROVEN'
        result['inputs'][key] = {'source_path': logical, 'selection_rule': rule,
             'read_status': 'EXACT_NATIVE_READ_BYTES' if valid else 'UNBOUND_STATE_OR_SELECTION',
             'artifact_sha256': read.get('artifact_sha256') if valid else None,
             'artifact_absolute_path': read.get('artifact_absolute_path') if valid else None,
             'read_witness': read if valid else None,
             'used_frame': full, 'selection': meta_selection_identity(selection)}
    return result
