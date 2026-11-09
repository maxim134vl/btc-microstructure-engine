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
import re
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


# Optimization domain only, not an admission date range: all other values
# retain the ORIGINAL coerce/UTC parser. Keep global historical _time unchanged.
_NATIVE_ISO_EVENT_CLOCK = re.compile(r"^20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})?$")


def _native_event_time(value):
    if isinstance(value, str) and _NATIVE_ISO_EVENT_CLOCK.fullmatch(value):
        try:
            stamp = pd.Timestamp(value)
            return stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')
        except (ValueError, TypeError, OverflowError):
            pass
    return _time(value)


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


def freeze_sources(root, stage, *, _native_pass=None):
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
        # The private snapshot needs identical bytes and their full SHA, not a
        # second whole-file Python allocation. Publish the private copy only
        # after its sequential copy/hash has completed successfully.
        import tempfile
        digest = hashlib.sha256()
        temporary = None
        try:
            with source.open("rb") as incoming:
                with tempfile.NamedTemporaryFile(dir=folder, prefix=".freeze-", delete=False) as outgoing:
                    temporary = Path(outgoing.name)
                    for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                        outgoing.write(chunk)
                        digest.update(chunk)
            os.replace(temporary, folder / (key + ".parquet"))
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        original = (Path(root) / rel).resolve()
        identities[key] = str(original)
        pin = digest.hexdigest()
        if _native_pass is not None:
            _native_pass.frozen(folder / (key + ".parquet"), pin)
        version = Path(str(original) + ".publication") / (pin + ".meta.json")
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


def _decode_source_frame(raw, *, key=None, source_timestamps=False):
    file_source = isinstance(raw, Path)
    source_size = raw.stat().st_size if file_source else len(raw)
    if key is not None and Path(str(key)).name in {"own_tf_M15.parquet", "own_tf_M30.parquet", "own_tf_H1.parquet", "own_tf_H4.parquet"} and source_size > 64 * 1024 * 1024:
        # Decode every row and every column while bounding temporary Arrow
        # batches. The bytes, hashes, timestamp and receipt checks remain
        # unchanged; small files keep the original pandas reader.
        import pyarrow as pa
        import pyarrow.parquet as pq
        parquet = pq.ParquetFile(pa.memory_map(str(raw), "r") if file_source else pa.BufferReader(raw))
        parts = []
        for batch in parquet.iter_batches(batch_size=16, use_threads=False):
            parts.append(batch.to_pandas(split_blocks=True, use_threads=False))
            del batch
        frame = pd.concat(parts, ignore_index=True) if parts else parquet.read().to_pandas()
        del parts, parquet
    else:
        frame = pd.read_parquet(raw if file_source else io.BytesIO(raw))
    if source_timestamps:
        if "timestamp" not in frame:
            raise ValueError("SOURCE_TIMESTAMP_MISSING")
        frame["_source_timestamp"] = pd.to_datetime(frame.timestamp, utc=True, errors="coerce")
        if frame._source_timestamp.isna().any():
            raise ValueError("SOURCE_TIMESTAMP_INVALID")
    return frame


class NativeSourcePass:
    """One launcher's private frozen sources; no cross-cycle frame cache.

    SHA values come from the exact bytes freeze_sources has just written.
    Only one M15 frame can be handed from snapshot preparation to its reader.
    Taking it transfers ownership, so no later caller can mutate that handoff.
    Receipts, source identities and admission are deliberately not retained.
    """
    def __init__(self, stage):
        self.folder = Path(stage).absolute() / SIDECAR_ROOT / 'sources'
        self._pins = {}
        self._handoff = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._handoff = None
        self._pins.clear()

    def accepts(self, path):
        path = Path(path).absolute()
        return (path.parent == self.folder
                and path.stem in TF_NATIVE_SOURCES and path.suffix == '.parquet')

    @staticmethod
    def _version(path):
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size,
                stat.st_mtime_ns, stat.st_ctime_ns)

    def frozen(self, path, pin):
        path = Path(path).absolute()
        if self.accepts(path):
            self._pins[path] = (self._version(path), pin)

    def read(self, path):
        path = Path(path).absolute()
        before = self._version(path)
        saved = self._handoff
        self._handoff = None
        if saved is not None and saved[:2] == (path, before):
            return None, saved[2], saved[3]
        raw = path.read_bytes()
        after = self._version(path)
        pinned = self._pins.get(path)
        pin = (pinned[1] if pinned is not None and pinned[0] == before == after
               else _sha(raw))
        if before == after:
            self._pins[path] = (after, pin)
        return raw, pin, None

    def read_for_decode(self, path):
        """Reuse this pass's unchanged private file without a full raw buffer.

        Ordinary/mutated inputs keep read() and its full-byte SHA semantics.
        The M15 handoff still transfers the exact already-decoded frame.
        """
        path = Path(path).absolute()
        before = self._version(path)
        saved = self._handoff
        if saved is not None and saved[:2] == (path, before):
            return self.read(path)
        pinned = self._pins.get(path)
        if self.accepts(path) and pinned is not None and pinned[0] == before:
            self._handoff = None
            return path, pinned[1], None
        return self.read(path)

    def handoff(self, path, pin, frame):
        path = Path(path).absolute()
        self._handoff = None
        pinned = self._pins.get(path)
        if (path.name == 'own_tf_M15.parquet' and self.accepts(path)
                and pinned == (self._version(path), pin)):
            self._handoff = (path, pinned[0], pin, frame)


# At most one native TF decoded frame for this private publication operation.
# Only deterministic decoded values are reused; every call hashes all actual raw
# bytes first, and all receipts/TF/cutoff/admission checks remain outside here.
_PRIVATE_M15_DECODE = None


def _private_m15_scope(key, source_timestamps):
    if not source_timestamps or key is None:
        return None
    path = Path(str(key))
    if path.name not in {"own_tf_M15.parquet", "own_tf_M30.parquet", "own_tf_H1.parquet", "own_tf_H4.parquet"}:
        return None
    for parent in path.parents:
        if parent.name.startswith(".primary-context-stage-"):
            return str(parent.resolve() / path.name)
    return None


def _decoded_parquet(raw, *, cache=None, key=None, source_timestamps=False, with_sha=False):
    """Decode exact bytes once; no receipt, availability or admission is cached.

    UTC source timestamps are a deterministic part of decoding these bytes.
    Every caller still reads the actual file and hashes it anew; receipts and
    cutoff/TF/target checks run on every use. Separate cache tokens prevent a
    plain Final decode from masquerading as a validated source timestamp frame.
    """
    global _PRIVATE_M15_DECODE
    pin = _sha(raw)  # Full actual bytes, including on shared decode reuse.
    token = (key, bool(source_timestamps))
    private_scope = _private_m15_scope(key, source_timestamps)
    shared = _PRIVATE_M15_DECODE
    if private_scope is not None and shared is not None and shared[:2] == (private_scope, pin):
        frame = shared[2].copy()
        if cache is not None:
            cache[token] = (pin, frame.copy())
        return (frame, pin) if with_sha else frame
    saved = None if cache is None else cache.get(token)
    if saved is not None and saved[0] == pin:
        frame = saved[1].copy()
    else:
        frame = _decode_source_frame(raw, key=key, source_timestamps=source_timestamps)
        if cache is not None:
            cache[token] = (pin, frame.copy())
    if private_scope is not None:
        _PRIVATE_M15_DECODE = (private_scope, pin, frame.copy())
    return (frame, pin) if with_sha else frame


def load_sources(stage, *, specifications=None, _decoded_cache=None, _native_pass=None):
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
        # Explicit owner scope only. Retained/default readers keep their
        # original full-byte checks and defensive decoded-frame copies.
        owned = _native_pass is not None and _native_pass.accepts(path)
        frame = None
        if owned:
            raw, raw_sha, frame = _native_pass.read_for_decode(path)
        else:
            # Strict full-byte read/hash by default. The private frozen-input
            # branch below reuses only this operation's unchanged file version.
            cache_key = (str(path.resolve()), True)
            cached = None if _decoded_cache is None else _decoded_cache.get(cache_key)
            raw = None
            raw_sha = None
            # freeze_sources owns this private operation's immutable input. Reuse
            # its already full-hashed bytes only while this exact file version and
            # the caller's decoded pin agree. Retained/archive reads stay strict.
            private_scope = None
            if path.name in {"own_tf_M15.parquet", "own_tf_M30.parquet", "own_tf_H1.parquet", "own_tf_H4.parquet"}:
                for parent in path.resolve().parents:
                    if parent.name.startswith(".primary-context-stage-"):
                        private_scope = str(parent)
                        break
            def file_version():
                stat = path.stat()
                return (stat.st_dev, stat.st_ino, stat.st_size,
                        stat.st_mtime_ns, stat.st_ctime_ns)
            version = file_version() if private_scope is not None else None
            version_key = ("private_source_version", private_scope, str(path.resolve()))
            saved_file = None if _decoded_cache is None else _decoded_cache.get(version_key)
            if (private_scope is not None and cached is not None
                    and saved_file == (version, cached[0])):
                raw_sha = cached[0]
            elif key == "own_tf_M15" and cached is not None:
                with path.open("rb") as handle:
                    raw_sha = hashlib.file_digest(handle, "sha256").hexdigest()
            if raw_sha is None or raw_sha != cached[0]:
                raw = path.read_bytes()
        try:
            if owned:
                if frame is None:
                    try:
                        frame = _decode_source_frame(raw, key=str(path), source_timestamps=True)
                    except (ValueError, OSError, TypeError):
                        if not isinstance(raw, Path):
                            raise
                        # Preserve the original byte-reader errors/reasons too.
                        raw, raw_sha, _ = _native_pass.read(raw)
                        frame = _decode_source_frame(raw, key=str(path), source_timestamps=True)
                    # Only the exact still-frozen generation can use the file
                    # reader. A changed version falls back to the original full
                    # byte snapshot/hash/decode before any evidence is returned.
                    if (isinstance(raw, Path)
                            and _native_pass._pins.get(raw) != (_native_pass._version(raw), raw_sha)):
                        raw, raw_sha, _ = _native_pass.read(raw)
                        frame = _decode_source_frame(raw, key=str(path), source_timestamps=True)
            elif raw is None:
                frame = cached[1].copy()
            else:
                frame, raw_sha = _decoded_parquet(raw, cache=_decoded_cache,
                    key=str(path.resolve()), source_timestamps=True, with_sha=True)
            if not owned and private_scope is not None and _decoded_cache is not None and version == file_version():
                _decoded_cache[version_key] = (version, raw_sha)
            meta_path = folder / (key + ".meta.json")
            meta_raw = meta_path.read_bytes() if meta_path.exists() else None
            meta = json.loads(meta_raw) if meta_raw else {}
            publication_path = folder / (key + ".publication.json")
            publication_raw = publication_path.read_bytes() if publication_path.exists() else None
            try:
                publication = json.loads(publication_raw) if publication_raw else None
            except (ValueError, TypeError):
                publication = None
            result[key] = {**base, "status": "PRESENT", "sha256": raw_sha,
                           "frame": frame, "metadata": meta,
                           "metadata_sha256": _sha(meta_raw) if meta_raw else None,
                           "publication_metadata": publication,
                           "publication_metadata_sha256": _sha(publication_raw) if publication_raw else None}
            result[key]["execution_proof_status"] = execution_proof["status"]
            result[key]["recorded_read_witness"] = _read_witness(result[key], execution_proof)
        except (ValueError, OSError, TypeError) as exc:
            result[key] = {**base, "status": "UNREADABLE", "sha256": raw_sha if raw is None or isinstance(raw, Path) else _sha(raw),
                           "reason": type(exc).__name__ + ":" + str(exc)}
    return result


def _observation(source, close):
    base = {k: v for k, v in source.items() if k not in ("frame", "metadata", "publication_metadata")}
    if source["status"] != "PRESENT":
        return base
    frame = source["frame"]
    # Select native TF by its clock before copying its large provenance
    # columns. Preserve the original stable order for duplicate timestamps.
    if source.get("source_path") in {spec[0] for spec in TF_NATIVE_SOURCES.values()}:
        times = frame._source_timestamp
        eligible = times <= close
        if not eligible.any():
            return {**base, "status": "CAUSALLY_UNAVAILABLE", "reason": "NO_SOURCE_AT_OR_BEFORE_CLOSE"}
        timestamp = times.loc[eligible].max()
        mask = times == timestamp
        positions = mask.to_numpy().nonzero()[0]
        if len(positions) == 1:
            pos = int(positions[0])
            latest = frame.iloc[pos:pos + 1]
        else:
            latest = frame.loc[mask]
    else:
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



def _validated_early_phase_witness(root, stage, tf, lifecycle, witness):
    """Revalidate public history, allowing only THIS calculation's shadow write.

    Original unpublished admission was captured by the native launcher before
    prepare_m15 writes its private state/log. The original pinned decision clock
    is retained. This is not a historical reader or a new-target reconstruction.
    """
    from copy import deepcopy
    from btc_ml.external_traders import stage2_predecision_evidence as P
    from btc_ml.external_traders.context_phase_publication import HOME as phase_home
    opened = pd.to_datetime(lifecycle.timestamp, utc=True).max()
    result = deepcopy(witness) if isinstance(witness, dict) else {
        'root': str(Path(root).resolve()), 'timeframe': tf, 'opened': _iso(opened),
        'started_at': None, 'snapshot': None}
    try:
        if (tf != 'M15' or result.get('root') != str(Path(root).resolve())
                or result.get('timeframe') != tf or _time(result.get('opened')) != opened):
            raise ValueError('EARLY_PHASE_TARGET_BINDING')
        original = result.get('snapshot')
        audited = P.load_own_tf_decision_snapshot(stage, tf, opened, validate_unpublished=False)
        if (not isinstance(original, dict) or original != audited
                or original.get('candidate_new') is not True
                or original.get('candidate_reason') != 'NEW_UNPUBLISHED_CANDIDATE'):
            raise ValueError('EARLY_PHASE_UNPUBLISHED_PROOF')
        before = original['history'][tf]
        if not before.get('proven') or before.get('tip') is None:
            raise ValueError('EARLY_PHASE_PRIOR_HISTORY_REQUIRED')
        start, decision = _time(result.get('started_at')), _time(original.get('decision_as_of'))
        if start is None or decision is None or start < decision:
            raise ValueError('EARLY_PHASE_CLOCK_BINDING')
        current = P._own_tf_history(root, tf)
        if not current['proven']:
            raise ValueError('EARLY_PHASE_CURRENT_HISTORY_UNREADABLE')
        shadow = {'data/live/m15_september_shadow_v1/' + name for name in (
            'auction.parquet', 'cognitive_market_state_memory.parquet',
            'final_market_context_memory.parquet', 'market_context_lifecycle_memory.parquet')}
        owned = shadow | {'data/live/context_decision_log.parquet'}
        public_before = {k:v for k,v in before['files'].items() if k not in owned}
        public_current = {k:v for k,v in current['files'].items() if k not in owned}
        if public_before != public_current:
            raise ValueError('EARLY_PHASE_PUBLIC_HISTORY_CHANGED')
        if any(not current['files'].get(k,{}).get('present')
                or _time(current['files'][k].get('tip')) != opened for k in owned):
            raise ValueError('EARLY_PHASE_OWN_SHADOW_TARGET_MISMATCH')
        phase_slot = Path(root)/phase_home/tf/'bars'/(opened.strftime('%Y%m%dT%H%M%SZ')+'.json')
        if _path(root, tf, opened).exists() or phase_slot.exists():
            raise ValueError('EARLY_PHASE_IMMUTABLE_TARGET_EXISTS')
        result['post_calculation_validation'] = {'status':'PUBLIC_HISTORY_REVALIDATED',
            'allowed_mutation':'OWN_PREPARED_M15_SHADOW_AND_SHADOW_ONLY_LOG',
            'original_snapshot_sha256':original['snapshot_sha256']}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Evidence failure cannot block native context or upgrade an old target.
        if isinstance(result.get('snapshot'), dict):
            result['snapshot']['candidate_new'] = False
            result['snapshot']['candidate_reason'] = 'EARLY_PHASE_WITNESS_NOT_PROVEN'
        result['post_calculation_validation'] = {'status':'NOT_PROVEN',
            'reason':type(exc).__name__+':'+str(exc)}
    return result


def _anchored_retained_stages(root, tf, *, exclude=None):
    """Use an already-delivered receipt to identify retained original staging."""
    from btc_ml.external_traders.stage2_predecision_evidence import load_prepared_consumption
    root = Path(root); live = root / "data/live"; result = []
    if not live.exists():
        return result
    for stage in sorted(live.glob('.primary-context-stage-*')):
        if not stage.is_dir() or stage.is_symlink() or (exclude is not None and stage.resolve() == Path(exclude).resolve()):
            continue
        prepared = stage / SIDECAR_ROOT / 'prepared_consumption' / tf
        paths = stage / SIDECAR_ROOT / 'sources/source_paths.json'
        if not prepared.is_dir() or not paths.is_file():
            continue
        # A single already-delivered, still-valid receipt anchors this stage.
        for file in sorted(prepared.glob('*.json')):
            try:
                opened = pd.to_datetime(file.stem, format='%Y%m%dT%H%M%SZ', utc=True)
                if not _path(root, tf, opened).exists():
                    continue
                original = load_prepared_consumption(stage, tf, opened)
                delivered = read_context_evidence(root, tf, opened)
                native = delivered.get('native_consumption')
                if not isinstance(original, dict) or not isinstance(native, dict):
                    continue
                reduced = {k: v for k, v in native.items()
                           if k not in ('technical_result_binding', 'association')}
                if _bytes(reduced) == _bytes(original):
                    result.append(stage)
                    break
            except (ValueError, KeyError, TypeError, OSError):
                continue
    return result


def _recoverable_stage(stages, tf, opened):
    name = opened.strftime('%Y%m%dT%H%M%SZ') + '.json'
    matches = [stage for stage in stages
               if (stage / SIDECAR_ROOT / 'prepared_consumption' / tf / name).is_file()]
    # Different snapshots / first-publication clocks must never be guessed.
    return matches[0] if len(matches) == 1 else None


def _stage_sources(stage, tf, cache):
    key = (str(stage), tf)
    if key not in cache:
        # Keep at most one frozen source set in memory across recoveries.
        cache.clear()
        sources = load_sources(stage)
        sources.update(load_sources(stage, specifications={'own_tf_' + tf: TF_NATIVE_SOURCES['own_tf_' + tf]}))
        cache[key] = sources
    return cache[key]


def publish_completed_with_evidence(root, stage, tf, lifecycle, episodes, artifacts, *, context_phase=False, context_phase_scope="NATIVE_RUNTIME", context_phase_witness=None):
    """Resume only from original prepared records and authenticated sidecars."""
    from btc_ml.external_traders.incremental_context_publication import publish_completed
    from btc_ml.external_traders.stage2_predecision_evidence import load_prepared_consumption
    life_path = Path(root) / "data/cognition/market_context_lifecycle_memory.parquet"
    old = pd.read_parquet(life_path) if life_path.exists() else None
    previous = None if old is None else old.loc[old.timeframe.astype(str) == tf]
    phase_witness = None
    if context_phase:
        from btc_ml.external_traders.context_phase_publication import prepare_native_publication
        phase_witness = (prepare_native_publication(root, stage, tf, lifecycle)
                         if context_phase_witness is None else
                         _validated_early_phase_witness(root, stage, tf, lifecycle, context_phase_witness))
    record = publish_completed(root, stage, tf, lifecycle, episodes, artifacts)
    try:
        previous_tip = (pd.to_datetime(previous.timestamp, utc=True).max()
                        if previous is not None and len(previous) else None)
        retained = _anchored_retained_stages(root, tf, exclude=stage)
        new_rows, recoverable, blocked = [], [], []
        for _, row in lifecycle.iterrows():
            opened = _time(row.timestamp)
            if opened is None:
                raise ValueError("INVALID_CONTEXT_BAR")
            new_row = previous_tip is None or opened > previous_tip
            if _path(root, tf, opened).exists() and not new_row:
                continue
            if new_row:
                new_rows.append((opened, Path(stage)))
            else:
                original_stage = _recoverable_stage(retained, tf, opened)
                (recoverable if original_stage is not None else blocked).append((opened, original_stage))
        # Live publication advances only new rows; historical evidence remains
        # explicitly partial and may be resumed separately by the operator.
        new_rows.sort(key=lambda item: item[0]); recoverable.sort(key=lambda item: item[0])
        chosen = new_rows
        if not chosen and not blocked and not recoverable and len(lifecycle):
            # Revalidate the existing tip without manufacturing a new receipt.
            tip = _time(lifecycle.iloc[-1].timestamp)
            read_context_evidence(root, tf, tip)
        cache = {}; deliveries = []
        for opened, source_stage in chosen:
            consumer = load_prepared_consumption(source_stage, tf, opened)
            if consumer is None:
                blocked.append((opened, source_stage))
                continue
            sources = _stage_sources(source_stage, tf, cache)
            # Existing bind_consumption_after_decision validates exact original
            # observation SHA, target rows, decision and clocks before writing.
            deliveries.append(deliver_bar(root, tf, opened, sources, consumer_record=consumer))
            del sources
        remaining = len(recoverable) + len(blocked)
        record["stage2_evidence"] = {"status": "PARTIAL" if remaining else "DELIVERED",
                                     "deliveries": deliveries, "remaining": remaining,
                                     "blocked_original_snapshot": len(blocked)}
    except Exception as exc:
        record["stage2_evidence"] = {"status": "UNAVAILABLE", "reason": type(exc).__name__ + ":" + str(exc)}
    if context_phase:
        try:
            from btc_ml.external_traders.context_phase_publication import publish_context_phase
            phase_witness["source_publication_completed_at"] = record["published_at"]
            record["context_phase"] = publish_context_phase(
                root, tf, source_witness=phase_witness, scope=context_phase_scope)
        except Exception as exc:
            record["context_phase"] = {"status":"NOT_PROVEN", "reason":type(exc).__name__+":"+str(exc)}
    return record


def resume_undelivered_evidence(root, *, limit=32):
    """Resume only receipt-anchored original prepared evidence; never backdate."""
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("INVALID_EVIDENCE_RESUME_LIMIT")
    from btc_ml.external_traders.stage2_predecision_evidence import load_prepared_consumption
    root = Path(root); life_path = root / "data/cognition/market_context_lifecycle_memory.parquet"
    if not life_path.exists():
        return {"status": "NOT_AVAILABLE", "reason": "LIFECYCLE_MISSING"}
    life = pd.read_parquet(life_path)
    if "timeframe" not in life or "timestamp" not in life:
        raise ValueError("UNPROVEN_CONTEXT_OWNER")
    missing = {tf: [] for tf in TF_MINUTES}
    for _, row in life.iterrows():
        tf = str(row.timeframe)
        if tf not in TF_MINUTES:
            continue
        opened = _time(row.timestamp)
        if opened is None or opened != opened.floor(str(TF_MINUTES[tf]) + "min"):
            raise ValueError("INVALID_CONTEXT_BAR")
        if not _path(root, tf, opened).exists():
            missing[tf].append(opened)
    for rows in missing.values(): rows.sort()
    total = sum(map(len, missing.values()))
    if not total:
        return {"status": "NO_MISSING_PATHS", "delivered": 0, "remaining": 0, "blocked_original_snapshot": 0}
    anchored = {tf: _anchored_retained_stages(root, tf) for tf in TF_MINUTES if missing[tf]}
    cache = {}; chosen = []; delivered = []; blocked = 0
    while len(chosen) < limit and any(missing.values()):
        for tf in TF_MINUTES:
            if len(chosen) >= limit: break
            if not missing[tf]: continue
            opened = missing[tf].pop(0)
            source_stage = _recoverable_stage(anchored[tf], tf, opened)
            if source_stage is None:
                blocked += 1
                continue
            consumer = load_prepared_consumption(source_stage, tf, opened)
            if consumer is None:
                blocked += 1
                continue
            chosen.append((tf, opened, source_stage, consumer))
    # Selection is fair across TF; group execution to avoid concurrent source
    # snapshots and retain at most one decoded source set in memory.
    chosen.sort(key=lambda item: (str(item[2]), item[0], item[1]))
    for tf, opened, source_stage, consumer in chosen:
        sources = _stage_sources(source_stage, tf, cache)
        delivered.append(deliver_bar(root, tf, opened, sources, consumer_record=consumer))
        del sources
    remaining = total - len(delivered)
    return {"status": "PARTIAL" if delivered and remaining else "BLOCKED" if remaining else "COMPLETE",
            "delivered": len(delivered), "remaining": remaining, "blocked_original_snapshot": blocked}


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
# Explicit version binding: retain verified historical producer and accept only
# the new timeout-propagation producer; receipts remain individually SHA-bound.
TF_NATIVE_PRODUCER_SHA256_ACCEPTED = frozenset({TF_NATIVE_PRODUCER_SHA256,
    '4912f8ddf7d3e7fc6744cfb7ef573ff665440e6dc08ab352f5c2bd003d596f9d',
    '71ea175d892e7afce12a9ca53e9d22da0e397cc4b120821d2f7a6656c759c02d'})


def load_tf_native_evidence_from_sources(sources, tf, opened, *, decision_context=None):
    source = sources.get('own_tf_' + tf)
    if source is None or source.get('status') == 'MISSING':
        return None
    if source.get('status') == 'PRESENT':
        mask=source['frame']._source_timestamp == opened
        positions=mask.to_numpy().nonzero()[0]
        if len(positions) == 0:
            # Original empty selection left source unchanged. Avoid making an
            # empty Arrow take over the large history before the same fallback.
            rows=None
        elif len(positions) == 1:
            pos=int(positions[0])
            rows=source['frame'].iloc[pos:pos+1]
        else:
            rows=source['frame'].loc[mask]
        if rows is not None and len(rows):source={**source,'frame':rows}
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


def load_tf_native_evidence(stage, tf, opened, *, decision_context=None, _decoded_cache=None):
    sources = load_sources(stage, specifications={'own_tf_' + tf: TF_NATIVE_SOURCES['own_tf_' + tf]},
                           _decoded_cache=_decoded_cache)
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
                or any(_native_event_time(e.get('timestamp')) is None or _native_event_time(e['timestamp'])+duration>used for e in events)):
            result['reason']='MARKET_OR_QUALIFIER_CUTOFF_NOT_PROVEN';return result
    except (KeyError,ValueError,TypeError):return result
    result.update(admitted=True,reason='OWN_TF_PUBLICATION_AVAILABLE_BEFORE_FIXED_DECISION',
                  values_evaluated_asof=_iso(used),source_read_at=_iso(read))
    return result
