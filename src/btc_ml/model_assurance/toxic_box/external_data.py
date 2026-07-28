"""External Data Toxicity monitoring (MODEL-2).

OBSERVATIONAL / NON-BLOCKING — does not alter LIVE1A/LIVE1B or System Health.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq

from btc_ml.model_assurance.registry import read_active_runtime

AGG_REQUIRED = (
    "aggregate_trade_id",  # trade_id contract
    "price",
    "quantity",
    "exchange_trade_timestamp",  # trade_timestamp
    "local_receive_timestamp",
    "local_receive_monotonic_ns",
    "connection_session_id",
    "reconnect_generation",
)
BOOK_REQUIRED = (
    "update_id",
    "best_bid_price",  # best_bid
    "best_ask_price",  # best_ask
    "local_receive_timestamp",
    "local_receive_monotonic_ns",
    "connection_session_id",
    "reconnect_generation",
)
M15_REQUIRED = ("timestamp", "open", "high", "low", "close", "volume")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _iso(stamp: datetime | None) -> str | None:
    if stamp is None:
        return None
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "toxic_box" / "external_data"
    return {
        "root": base,
        "events": base / "events" / "external_data_events.jsonl",
        "sources": base / "sources" / "current_sources.json",
        "summary": base / "snapshots" / "latest_summary.json",
        "checkpoint": base / "runtime" / "checkpoint.json",
        "health": base / "runtime" / "health.json",
        "config": root / "config" / "model_assurance_external_sources.json",
        "cognition_health": root / "data" / "runtime" / "intrabar_cognition_health.json",
        "raw_root": root / "data" / "raw_market_events_v2",
        "live_feed": root / "data" / "live" / "live_market_feed.parquet",
    }


def load_external_source_registry(repo_root: Path | None = None) -> dict[str, Any]:
    path = paths(repo_root)["config"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("sources"), list) or not payload["sources"]:
        raise ValueError("external sources config missing sources[]")
    return payload


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_canonical_json(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def toxic_event_id(*, source_id: str, subtype: str, status: str, detected_at: str) -> str:
    return "TOX_" + _sha256_text(
        _canonical_json(
            {
                "source_id": source_id,
                "subtype": subtype,
                "status": status,
                "detected_at": detected_at,
                "nonce": uuid.uuid4().hex,
            }
        )
    )[:32]


def severity_for(subtype: str) -> str:
    critical = {
        "DATA_SOURCE_UNAVAILABLE",
        "DATA_SCHEMA_BREAK",
        "DATA_FUTURE_LEAKAGE",
        "DATA_PIPELINE_BACKPRESSURE",
    }
    warning = {
        "DATA_STALE",
        "DATA_GAP",
        "DATA_DUPLICATE",
        "DATA_SEQUENCE_REWIND",
        "DATA_PROVENANCE_MISSING",
        "DATA_TIMESTAMP_AMBIGUOUS",
    }
    if subtype in critical:
        return "CRITICAL"
    if subtype in warning:
        return "WARNING"
    return "WATCH"


def _list_recent_parquet(stream_root: Path, *, limit_files: int = 4) -> list[Path]:
    if not stream_root.exists():
        return []
    dates = sorted([p for p in stream_root.glob("date=*") if p.is_dir()])
    files: list[Path] = []
    for date_dir in reversed(dates[-2:]):
        hours = sorted([p for p in date_dir.glob("hour=*") if p.is_dir()])
        for hour_dir in reversed(hours[-2:]):
            chunk = sorted(
                [
                    p
                    for p in hour_dir.iterdir()
                    if p.is_file() and p.suffix == ".parquet" and not p.name.endswith(".tmp")
                ]
            )
            files.extend(chunk)
    return files[-limit_files:]


def _read_parquet_rows(path: Path, *, max_rows: int = 500) -> list[dict[str, Any]]:
    try:
        table = pq.read_table(path)
    except Exception:
        return []
    names = [n for n in table.column_names if n not in {"date", "hour"}]
    table = table.select(names) if names else table
    if table.num_rows > max_rows:
        table = table.slice(table.num_rows - max_rows)
    rows: list[dict[str, Any]] = []
    for batch in table.to_batches(max_chunksize=256):
        data = batch.to_pydict()
        n = len(next(iter(data.values()), []))
        for i in range(n):
            rows.append({k: data[k][i] for k in data})
    return rows


def _check_schema(row: dict[str, Any], required: Iterable[str]) -> list[str]:
    missing = []
    for key in required:
        if key not in row or row.get(key) is None:
            missing.append(key)
    return missing


def _scan_agg_sequence(rows: list[dict[str, Any]], *, prev_id: int | None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    last = prev_id
    seen: set[int] = set()
    for row in rows:
        tid = row.get("aggregate_trade_id")
        if tid is None:
            continue
        try:
            tid_i = int(tid)
        except (TypeError, ValueError):
            continue
        if tid_i in seen:
            issues.append(
                {
                    "subtype": "DATA_DUPLICATE",
                    "observed_value": tid_i,
                    "expected_value": "unique_trade_id",
                    "sequence_start": tid_i,
                    "sequence_end": tid_i,
                }
            )
        seen.add(tid_i)
        if last is not None:
            if tid_i < last:
                issues.append(
                    {
                        "subtype": "DATA_SEQUENCE_REWIND",
                        "observed_value": tid_i,
                        "expected_value": f">={last}",
                        "sequence_start": last,
                        "sequence_end": tid_i,
                    }
                )
            elif tid_i > last + 1:
                issues.append(
                    {
                        "subtype": "DATA_GAP",
                        "observed_value": tid_i,
                        "expected_value": last + 1,
                        "sequence_start": last + 1,
                        "sequence_end": tid_i - 1,
                    }
                )
        last = tid_i
        # future leakage
        ex = _parse_ts(row.get("exchange_event_timestamp") or row.get("exchange_trade_timestamp"))
        loc = _parse_ts(row.get("local_receive_timestamp"))
        if ex is not None and loc is not None:
            skew_ms = (ex - loc).total_seconds() * 1000.0
            # filled later with config tolerance
            row["_future_skew_ms"] = skew_ms
    return issues


def _scan_book_sequence(rows: list[dict[str, Any]], *, prev_id: int | None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    last = prev_id
    seen: set[int] = set()
    for row in rows:
        uid = row.get("update_id")
        if uid is None:
            continue
        try:
            uid_i = int(uid)
        except (TypeError, ValueError):
            continue
        if uid_i in seen:
            issues.append(
                {
                    "subtype": "DATA_DUPLICATE",
                    "observed_value": uid_i,
                    "expected_value": "unique_update_id",
                    "sequence_start": uid_i,
                    "sequence_end": uid_i,
                }
            )
        seen.add(uid_i)
        if last is not None and uid_i < last:
            issues.append(
                {
                    "subtype": "DATA_SEQUENCE_REWIND",
                    "observed_value": uid_i,
                    "expected_value": f">={last}",
                    "sequence_start": last,
                    "sequence_end": uid_i,
                }
            )
        # do NOT require update_id + 1
        last = uid_i
        bid = row.get("best_bid_price")
        ask = row.get("best_ask_price")
        try:
            bid_f = float(bid) if bid is not None else None
            ask_f = float(ask) if ask is not None else None
        except (TypeError, ValueError):
            bid_f = ask_f = None
        if bid_f is not None and ask_f is not None:
            if bid_f <= 0 or ask_f <= 0 or bid_f > ask_f:
                issues.append(
                    {
                        "subtype": "DATA_SCHEMA_BREAK",
                        "observed_value": {"best_bid": bid_f, "best_ask": ask_f},
                        "expected_value": "best_bid>0 and best_ask>0 and best_bid<=best_ask",
                    }
                )
        # exchange timestamp absent is NOT_APPLICABLE
        if row.get("exchange_event_timestamp") is None:
            row["_exchange_ts_status"] = "NOT_APPLICABLE_NO_EXCHANGE_TIMESTAMP"
        else:
            ex = _parse_ts(row.get("exchange_event_timestamp"))
            loc = _parse_ts(row.get("local_receive_timestamp"))
            if ex is not None and loc is not None:
                row["_future_skew_ms"] = (ex - loc).total_seconds() * 1000.0
    return issues


def append_toxicity_transition(
    *,
    events_path: Path,
    open_issues: dict[str, dict[str, Any]],
    source_id: str,
    subtype: str,
    healthy_now: bool,
    active: dict[str, Any] | None,
    threshold: Any = None,
    expected_value: Any = None,
    observed_value: Any = None,
    evidence: dict[str, Any] | None = None,
    sequence_start: Any = None,
    sequence_end: Any = None,
    connection_session_id: Any = None,
    reconnect_generation: Any = None,
    event_time: str | None = None,
) -> dict[str, Any] | None:
    """Emit OPEN on HEALTHY→issue and RESOLVED on issue→HEALTHY. No spam."""
    key = f"{source_id}|{subtype}"
    now = _utc_now_iso()
    if not healthy_now:
        if key in open_issues:
            return None
        row = {
            "toxic_event_id": toxic_event_id(
                source_id=source_id, subtype=subtype, status="OPEN", detected_at=now
            ),
            "branch": "EXTERNAL_DATA",
            "subtype": subtype,
            "severity": severity_for(subtype),
            "status": "OPEN",
            "source_id": source_id,
            "detected_at": now,
            "event_time": event_time or now,
            "resolved_at": None,
            "expected_value": expected_value,
            "observed_value": observed_value,
            "threshold": threshold,
            "sequence_start": sequence_start,
            "sequence_end": sequence_end,
            "connection_session_id": connection_session_id,
            "reconnect_generation": reconnect_generation,
            "registry_record_id": (active or {}).get("registry_record_id"),
            "model_id": (active or {}).get("model_id"),
            "model_version": (active or {}).get("model_version"),
            "runtime_fingerprint": (active or {}).get("runtime_fingerprint"),
            "paper_epoch_id": (active or {}).get("paper_epoch_id"),
            "evidence": evidence or {},
        }
        _append_jsonl(events_path, row)
        open_issues[key] = row
        return row

    # healthy_now
    if key not in open_issues:
        return None
    opened = open_issues.pop(key)
    row = {
        "toxic_event_id": toxic_event_id(
            source_id=source_id, subtype=subtype, status="RESOLVED", detected_at=now
        ),
        "branch": "EXTERNAL_DATA",
        "subtype": subtype,
        "severity": opened.get("severity") or severity_for(subtype),
        "status": "RESOLVED",
        "source_id": source_id,
        "detected_at": opened.get("detected_at"),
        "event_time": event_time or now,
        "resolved_at": now,
        "expected_value": expected_value if expected_value is not None else opened.get("expected_value"),
        "observed_value": observed_value if observed_value is not None else opened.get("observed_value"),
        "threshold": threshold if threshold is not None else opened.get("threshold"),
        "sequence_start": sequence_start,
        "sequence_end": sequence_end,
        "connection_session_id": connection_session_id,
        "reconnect_generation": reconnect_generation,
        "registry_record_id": (active or {}).get("registry_record_id"),
        "model_id": (active or {}).get("model_id"),
        "model_version": (active or {}).get("model_version"),
        "runtime_fingerprint": (active or {}).get("runtime_fingerprint"),
        "paper_epoch_id": (active or {}).get("paper_epoch_id"),
        "evidence": {"resolved_from": opened.get("toxic_event_id"), **(evidence or {})},
    }
    _append_jsonl(events_path, row)
    return row


def _open_issues_from_events(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    open_map: dict[str, dict[str, Any]] = {}
    for row in events:
        if str(row.get("branch") or "") != "EXTERNAL_DATA":
            continue
        key = f"{row.get('source_id')}|{row.get('subtype')}"
        status = str(row.get("status") or "").upper()
        if status == "OPEN":
            open_map[key] = row
        elif status == "RESOLVED":
            open_map.pop(key, None)
    return open_map


def _service_started_at(cognition: dict[str, Any] | None) -> datetime | None:
    if not cognition:
        return None
    return _parse_ts(cognition.get("started_at"))


def evaluate_stream_source(
    *,
    source: dict[str, Any],
    cognition: dict[str, Any] | None,
    raw_root: Path,
    checkpoint: dict[str, Any],
    config: dict[str, Any],
    now: datetime,
    grace_ok: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (lineage_snapshot, issue_specs). issue_specs are active problems."""
    source_id = str(source["source_id"])
    stream_key = source.get("health_stream_key")
    stream_dir = source.get("stream_dir")
    max_age = float(source["max_age_seconds"])
    skew_tol = float(config.get("future_clock_skew_tolerance_ms", 2000))
    issues: list[dict[str, Any]] = []

    streams = (cognition or {}).get("streams") or {}
    stream_health = streams.get(stream_key) or {}
    last_received = _parse_ts(stream_health.get("last"))
    age = None if last_received is None else max(0.0, (now - last_received).total_seconds())

    provenance_path = raw_root / str(stream_dir) if stream_dir else None
    if provenance_path is None or not provenance_path.exists():
        if grace_ok:
            issues.append(
                {
                    "subtype": "DATA_SOURCE_UNAVAILABLE",
                    "observed_value": str(provenance_path),
                    "expected_value": "path_exists",
                    "threshold": None,
                }
            )
            issues.append(
                {
                    "subtype": "DATA_PROVENANCE_MISSING",
                    "observed_value": str(provenance_path),
                    "expected_value": source.get("provenance"),
                }
            )

    if grace_ok and (last_received is None or (age is not None and age > max_age)):
        issues.append(
            {
                "subtype": "DATA_STALE",
                "observed_value": age,
                "expected_value": f"<={max_age}",
                "threshold": max_age,
                "event_time": _iso(last_received),
            }
        )

    # chunk scan for schema/sequence (only newest files after checkpoint)
    ck_src = (checkpoint.get("sources") or {}).get(source_id) or {}
    prev_seq = ck_src.get("last_sequence_id")
    try:
        prev_seq_i = int(prev_seq) if prev_seq is not None else None
    except (TypeError, ValueError):
        prev_seq_i = None

    last_seq = prev_seq_i
    last_mono = ck_src.get("last_receive_monotonic_ns")
    last_exchange = ck_src.get("last_exchange_event_at")
    conn = ck_src.get("connection_session_id")
    recon = ck_src.get("reconnect_generation")
    first_available = ck_src.get("first_available_at")
    seen_files = list(ck_src.get("seen_files") or [])

    if provenance_path and provenance_path.exists():
        files = _list_recent_parquet(provenance_path, limit_files=3)
        new_files = [f for f in files if str(f) not in seen_files]
        tip_only = False
        if not new_files:
            tip_files = files[-1:] if files else []
            tip_only = True
        else:
            tip_files = new_files
        for path in tip_files:
            rows = _read_parquet_rows(path, max_rows=300)
            if not rows:
                continue
            if first_available is None:
                first_available = _iso(_parse_ts(rows[0].get("local_receive_timestamp")))
            required = AGG_REQUIRED if stream_dir == "agg_trade" else BOOK_REQUIRED
            miss = _check_schema(rows[-1], required)
            if miss and grace_ok:
                issues.append(
                    {
                        "subtype": "DATA_SCHEMA_BREAK",
                        "observed_value": miss,
                        "expected_value": list(required),
                        "evidence": {"file": str(path)},
                    }
                )
            if not tip_only:
                if stream_dir == "agg_trade":
                    # Within-chunk only — avoid false rewinds from overlapping re-reads.
                    seq_issues = _scan_agg_sequence(rows, prev_id=None)
                else:
                    seq_issues = _scan_book_sequence(rows, prev_id=None)
                if grace_ok:
                    by_sub: dict[str, dict[str, Any]] = {}
                    for issue in seq_issues:
                        by_sub.setdefault(str(issue["subtype"]), issue)
                    issues.extend(by_sub.values())
                for row in rows:
                    skew = row.get("_future_skew_ms")
                    if (
                        skew is not None
                        and skew > skew_tol
                        and grace_ok
                        and source.get("exchange_timestamp_available")
                    ):
                        issues.append(
                            {
                                "subtype": "DATA_FUTURE_LEAKAGE",
                                "observed_value": skew,
                                "expected_value": f"<={skew_tol}",
                                "threshold": skew_tol,
                            }
                        )
                        break
            tip = rows[-1]
            seq_field = source.get("sequence_field")
            if seq_field and tip.get(seq_field) is not None:
                try:
                    last_seq = int(tip.get(seq_field))
                except (TypeError, ValueError):
                    pass
            last_mono = tip.get("local_receive_monotonic_ns")
            last_exchange = tip.get("exchange_event_timestamp") or tip.get("exchange_trade_timestamp")
            conn = tip.get("connection_session_id")
            recon = tip.get("reconnect_generation")
            if not tip_only:
                seen_files.append(str(path))
        seen_files = seen_files[-20:]

    health = "HEALTHY"
    subtypes = {i["subtype"] for i in issues}
    if "DATA_SOURCE_UNAVAILABLE" in subtypes or "DATA_SCHEMA_BREAK" in subtypes or "DATA_FUTURE_LEAKAGE" in subtypes:
        health = "CRITICAL"
    elif subtypes:
        health = "DEGRADED"
    if not grace_ok and not subtypes:
        health = "STARTING"

    lineage = {
        "source_id": source_id,
        "provider": source.get("provider"),
        "dataset_name": source.get("dataset_name"),
        "schema_version": source.get("schema_version"),
        "first_available_at": first_available,
        "last_exchange_event_at": last_exchange,
        "last_received_at": _iso(last_received),
        "last_receive_monotonic_ns": last_mono,
        "last_sequence_id": last_seq,
        "connection_session_id": conn,
        "reconnect_generation": recon,
        "checkpoint": {"seen_files": seen_files[-5:]},
        "source_health": health,
        "freshness_age_seconds": age,
        "updated_at": _iso(now),
        "exchange_timestamp_status": (
            "AVAILABLE"
            if source.get("exchange_timestamp_available")
            else "NOT_APPLICABLE_NO_EXCHANGE_TIMESTAMP"
        ),
    }
    # persist checkpoint fields via caller
    lineage["_checkpoint_update"] = {
        "last_sequence_id": last_seq,
        "last_receive_monotonic_ns": last_mono,
        "last_exchange_event_at": last_exchange,
        "connection_session_id": conn,
        "reconnect_generation": recon,
        "first_available_at": first_available,
        "seen_files": seen_files,
    }
    return lineage, issues


def evaluate_m15_source(
    *,
    source: dict[str, Any],
    live_feed: Path,
    checkpoint: dict[str, Any],
    now: datetime,
    grace_ok: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_id = str(source["source_id"])
    max_age = float(source["max_age_seconds"])
    issues: list[dict[str, Any]] = []
    ck_src = (checkpoint.get("sources") or {}).get(source_id) or {}
    first_available = ck_src.get("first_available_at")

    if not live_feed.exists():
        if grace_ok:
            issues.append(
                {
                    "subtype": "DATA_SOURCE_UNAVAILABLE",
                    "observed_value": str(live_feed),
                    "expected_value": "live_market_feed.parquet exists",
                }
            )
            issues.append(
                {
                    "subtype": "DATA_PROVENANCE_MISSING",
                    "observed_value": str(live_feed),
                    "expected_value": source.get("provenance"),
                }
            )
        lineage = {
            "source_id": source_id,
            "provider": source.get("provider"),
            "dataset_name": source.get("dataset_name"),
            "schema_version": source.get("schema_version"),
            "first_available_at": first_available,
            "last_exchange_event_at": None,
            "last_received_at": None,
            "last_receive_monotonic_ns": None,
            "last_sequence_id": None,
            "connection_session_id": None,
            "reconnect_generation": None,
            "checkpoint": {},
            "source_health": "CRITICAL" if grace_ok else "STARTING",
            "freshness_age_seconds": None,
            "updated_at": _iso(now),
            "exchange_timestamp_status": "AVAILABLE",
            "_checkpoint_update": {"first_available_at": first_available},
        }
        return lineage, issues

    try:
        table = pq.read_table(live_feed)
        if table.num_rows == 0:
            raise ValueError("empty feed")
        tip = {name: table.column(name)[table.num_rows - 1].as_py() for name in table.column_names}
    except Exception as exc:
        if grace_ok:
            issues.append(
                {
                    "subtype": "DATA_SCHEMA_BREAK",
                    "observed_value": str(exc),
                    "expected_value": list(M15_REQUIRED),
                }
            )
        tip = {}

    miss = [k for k in M15_REQUIRED if k not in tip or tip.get(k) is None]
    if miss and grace_ok:
        issues.append(
            {
                "subtype": "DATA_SCHEMA_BREAK",
                "observed_value": miss,
                "expected_value": list(M15_REQUIRED),
            }
        )

    # completed bar open time; age relative to expected close = open + 900s
    bar_open = _parse_ts(tip.get("timestamp"))
    last_exchange = None
    age = None
    if bar_open is not None:
        completed_close = bar_open.timestamp() + 900.0
        # compare now to completed close
        age = max(0.0, now.timestamp() - completed_close)
        last_exchange = _iso(bar_open)
        if first_available is None:
            first_available = last_exchange
    if grace_ok and (age is None or age > max_age):
        issues.append(
            {
                "subtype": "DATA_STALE",
                "observed_value": age,
                "expected_value": f"<={max_age}",
                "threshold": max_age,
                "event_time": last_exchange,
            }
        )

    subtypes = {i["subtype"] for i in issues}
    if "DATA_SOURCE_UNAVAILABLE" in subtypes or "DATA_SCHEMA_BREAK" in subtypes:
        health = "CRITICAL"
    elif subtypes:
        health = "DEGRADED"
    elif not grace_ok:
        health = "STARTING"
    else:
        health = "HEALTHY"

    lineage = {
        "source_id": source_id,
        "provider": source.get("provider"),
        "dataset_name": source.get("dataset_name"),
        "schema_version": source.get("schema_version"),
        "first_available_at": first_available,
        "last_exchange_event_at": last_exchange,
        "last_received_at": _iso(now) if tip else None,
        "last_receive_monotonic_ns": None,
        "last_sequence_id": None,
        "connection_session_id": None,
        "reconnect_generation": None,
        "checkpoint": {"last_bar_open": last_exchange},
        "source_health": health,
        "freshness_age_seconds": age,
        "updated_at": _iso(now),
        "exchange_timestamp_status": "AVAILABLE",
        "_checkpoint_update": {
            "first_available_at": first_available,
            "last_bar_open": last_exchange,
        },
    }
    return lineage, issues


def evaluate_pipeline_pressure(
    *,
    cognition: dict[str, Any] | None,
    config: dict[str, Any],
    grace_ok: bool,
) -> list[dict[str, Any]]:
    if not grace_ok or not cognition:
        return []
    pipe = config.get("pipeline") or {}
    queue = cognition.get("queue") or {}
    writer = cognition.get("writer") or {}
    issues: list[dict[str, Any]] = []
    rejected = int(queue.get("enqueue_rejected") or 0)
    write_errors = int(writer.get("write_errors") or 0)
    current = int(queue.get("queue_current_events") or 0)
    lag = float(writer.get("writer_lag_ms") or queue.get("writer_lag_ms") or 0.0)
    max_q = int(pipe.get("max_queue_current_events") or 40000)
    max_lag = float(pipe.get("max_writer_lag_ms") or 5000)
    if rejected > 0 or write_errors > 0 or current > max_q or lag > max_lag:
        issues.append(
            {
                "subtype": "DATA_PIPELINE_BACKPRESSURE",
                "source_id": "BINANCE_SPOT_BTCUSDT_AGGTRADE",
                "observed_value": {
                    "enqueue_rejected": rejected,
                    "write_errors": write_errors,
                    "queue_current_events": current,
                    "writer_lag_ms": lag,
                },
                "expected_value": {
                    "enqueue_rejected": 0,
                    "write_errors": 0,
                    "queue_current_events": f"<={max_q}",
                    "writer_lag_ms": f"<={max_lag}",
                },
                "threshold": {"max_queue_current_events": max_q, "max_writer_lag_ms": max_lag},
            }
        )
    return issues


def build_external_data_summary(
    *,
    active: dict[str, Any] | None,
    sources: list[dict[str, Any]],
    events: list[dict[str, Any]],
    starting: bool,
) -> dict[str, Any]:
    healthy = sum(1 for s in sources if s.get("source_health") == "HEALTHY")
    degraded = sum(1 for s in sources if s.get("source_health") == "DEGRADED")
    unavailable = sum(
        1 for s in sources if s.get("source_health") in {"CRITICAL", "UNAVAILABLE"}
    )
    open_events = [e for e in events if str(e.get("status")).upper() == "OPEN"]
    watch = sum(1 for e in open_events if e.get("severity") == "WATCH")
    warning = sum(1 for e in open_events if e.get("severity") == "WARNING")
    critical = sum(1 for e in open_events if e.get("severity") == "CRITICAL")
    counts_by_source: dict[str, int] = {}
    counts_by_subtype: dict[str, int] = {}
    for e in open_events:
        sid = str(e.get("source_id"))
        sub = str(e.get("subtype"))
        counts_by_source[sid] = counts_by_source.get(sid, 0) + 1
        counts_by_subtype[sub] = counts_by_subtype.get(sub, 0) + 1
    last_event_at = None
    last_resolved_at = None
    for e in events:
        if e.get("detected_at"):
            last_event_at = e.get("detected_at")
        if e.get("resolved_at"):
            last_resolved_at = e.get("resolved_at")

    if starting:
        status = "STARTING"
    elif critical > 0 or unavailable > 0:
        status = "CURRENT_CRITICAL"
    elif warning > 0 or degraded > 0:
        status = "CURRENT_DEGRADED"
    else:
        status = "CURRENT_HEALTHY"

    return {
        "status": status,
        "runtime_impact": "NON_BLOCKING",
        "monitoring_mode": "LIVE_CURRENT",
        "registry_record_id": (active or {}).get("registry_record_id"),
        "model_id": (active or {}).get("model_id"),
        "model_version": (active or {}).get("model_version"),
        "paper_epoch_id": (active or {}).get("paper_epoch_id"),
        "configured_sources": len(sources),
        "healthy_sources": healthy,
        "degraded_sources": degraded,
        "unavailable_sources": unavailable,
        "open_events": len(open_events),
        "watch_events": watch,
        "warning_events": warning,
        "critical_events": critical,
        "counts_by_source": counts_by_source,
        "counts_by_subtype": counts_by_subtype,
        "last_event_at": last_event_at,
        "last_resolved_at": last_resolved_at,
        "updated_at": _utc_now_iso(),
    }


def evaluate_external_sources(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    cognition_override: dict[str, Any] | None = None,
    registry_override: dict[str, Any] | None = None,
    live_feed_override: Path | None = None,
    raw_root_override: Path | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    p = paths(root)
    config = registry_override or load_external_source_registry(root)
    active = read_active_runtime(repo_root=root)
    cognition = cognition_override if cognition_override is not None else _read_json(p["cognition_health"])
    now = now or _utc_now()
    grace = float(config.get("startup_grace_period_seconds", 30))
    started = _service_started_at(cognition)
    grace_ok = True
    if started is not None:
        grace_ok = (now - started).total_seconds() >= grace
    starting = not grace_ok

    checkpoint = _read_json(p["checkpoint"]) or {"sources": {}}
    events_existing = _read_jsonl(p["events"])
    open_issues = _open_issues_from_events(events_existing)

    raw_root = raw_root_override or p["raw_root"]
    live_feed = live_feed_override or p["live_feed"]

    source_snapshots: list[dict[str, Any]] = []
    ck_sources = dict(checkpoint.get("sources") or {})

    for source in config["sources"]:
        if source.get("stream_dir"):
            lineage, issues = evaluate_stream_source(
                source=source,
                cognition=cognition,
                raw_root=raw_root,
                checkpoint=checkpoint,
                config=config,
                now=now,
                grace_ok=grace_ok,
            )
        else:
            lineage, issues = evaluate_m15_source(
                source=source,
                live_feed=live_feed,
                checkpoint=checkpoint,
                now=now,
                grace_ok=grace_ok,
            )
        ck_sources[str(source["source_id"])] = lineage.pop("_checkpoint_update", {})
        # Apply transitions for this source's issue set
        present = {i["subtype"] for i in issues}
        # Resolve previously open subtypes that are healthy now for this source
        for key in list(open_issues.keys()):
            sid, subtype = key.split("|", 1)
            if sid != source["source_id"]:
                continue
            if subtype not in present:
                append_toxicity_transition(
                    events_path=p["events"],
                    open_issues=open_issues,
                    source_id=sid,
                    subtype=subtype,
                    healthy_now=True,
                    active=active,
                )
        for issue in issues:
            append_toxicity_transition(
                events_path=p["events"],
                open_issues=open_issues,
                source_id=str(source["source_id"]),
                subtype=str(issue["subtype"]),
                healthy_now=False,
                active=active,
                threshold=issue.get("threshold"),
                expected_value=issue.get("expected_value"),
                observed_value=issue.get("observed_value"),
                evidence=issue.get("evidence"),
                sequence_start=issue.get("sequence_start"),
                sequence_end=issue.get("sequence_end"),
                event_time=issue.get("event_time"),
            )
        source_snapshots.append(lineage)

    pipe_issues = evaluate_pipeline_pressure(cognition=cognition, config=config, grace_ok=grace_ok)
    if pipe_issues:
        for pipe_issue in pipe_issues:
            append_toxicity_transition(
                events_path=p["events"],
                open_issues=open_issues,
                source_id=str(pipe_issue.get("source_id") or "BINANCE_SPOT_BTCUSDT_AGGTRADE"),
                subtype="DATA_PIPELINE_BACKPRESSURE",
                healthy_now=False,
                active=active,
                threshold=pipe_issue.get("threshold"),
                expected_value=pipe_issue.get("expected_value"),
                observed_value=pipe_issue.get("observed_value"),
            )
    elif grace_ok:
        append_toxicity_transition(
            events_path=p["events"],
            open_issues=open_issues,
            source_id="BINANCE_SPOT_BTCUSDT_AGGTRADE",
            subtype="DATA_PIPELINE_BACKPRESSURE",
            healthy_now=True,
            active=active,
        )

    events_all = _read_jsonl(p["events"])
    summary = build_external_data_summary(
        active=active,
        sources=source_snapshots,
        events=events_all,
        starting=starting,
    )
    sources_payload = {
        "updated_at": _utc_now_iso(),
        "runtime_impact": "NON_BLOCKING",
        "monitoring_mode": "LIVE_CURRENT",
        "sources": source_snapshots,
    }
    _atomic_write_json(p["sources"], sources_payload)
    _atomic_write_json(p["summary"], summary)
    _atomic_write_json(
        p["checkpoint"],
        {"sources": ck_sources, "updated_at": _utc_now_iso(), "service_started_at": _iso(started)},
    )
    _atomic_write_json(
        p["health"],
        {
            "status": summary["status"],
            "alive": True,
            "runtime_impact": "NON_BLOCKING",
            "monitoring_mode": "LIVE_CURRENT",
            "pid": os.getpid(),
            "configured_sources": summary["configured_sources"],
            "healthy_sources": summary["healthy_sources"],
            "degraded_sources": summary["degraded_sources"],
            "unavailable_sources": summary["unavailable_sources"],
            "open_events": summary["open_events"],
            "paper_only": (active or {}).get("paper_only", True),
            "real_execution": (active or {}).get("real_execution", False),
            "updated_at": _utc_now_iso(),
        },
    )
    return {
        "summary": summary,
        "sources": source_snapshots,
        "open_issues": list(open_issues.keys()),
    }
