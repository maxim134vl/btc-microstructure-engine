#!/usr/bin/env python3
"""Patch 3.2 — canonical runtime MTF availability read-model writer.

PIPELINE_POST_CYCLE_READ_MODEL. Operational only — never feeds trading decisions.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from multi_timeframe_availability import (
    LIVE_SUPPORTED_TIMEFRAMES,
    RUNTIME_EVALUATION_SET,
    SCHEMA_VERSION,
    UNSUPPORTED_LIVE_TIMEFRAMES,
    MTFAvailabilityError,
    assert_complete_evaluation_set,
    build_runtime_evaluation_rows,
    count_pit_violations,
    load_m15_candles,
    safe_m15_evaluation_timestamp,
    to_utc_ts,
)

ROOT = Path(__file__).resolve().parent

HISTORY_REL = "data/cognition/multi_timeframe_availability_memory.parquet"
LATEST_REL = "data/runtime/multi_timeframe_availability_latest.json"
STATUS_REL = "data/runtime/multi_timeframe_availability_status.json"

HISTORY_PATH = ROOT / HISTORY_REL
LATEST_PATH = ROOT / LATEST_REL
STATUS_PATH = ROOT / STATUS_REL

OWNER = "PIPELINE_POST_CYCLE_READ_MODEL"
WRITER = "mtf_availability_runtime_engine_v1.py"
STAGE_CLASS = "REQUIRED_OPERATIONAL_READ_MODEL"

HISTORY_COLUMNS = [
    "evaluation_timestamp",
    "timeframe",
    "state_asof",
    "source_state_timestamp",
    "source_event_timestamp",
    "source_bar_open",
    "source_bar_close",
    "is_new_event",
    "availability_status",
    "availability_reason",
    "age_seconds",
    "age_bars",
    "writer_state",
    "source_dataset",
    "source_row_key",
    "schema_version",
    "generated_at",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(target, raw)


def _atomic_write_parquet(target: Path, frame: pd.DataFrame) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".parquet.tmp",
        dir=str(target.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        frame.to_parquet(tmp_path, index=False)
        # validate temp before replace
        check = pd.read_parquet(tmp_path)
        if len(check) != len(frame):
            raise MTFAvailabilityError("temp parquet row count mismatch")
        os.replace(tmp_path, target)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["evaluation_timestamp"] = pd.to_datetime(out["evaluation_timestamp"], utc=True, errors="coerce")
    out["timeframe"] = out["timeframe"].astype(str)
    for col in HISTORY_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out = out[HISTORY_COLUMNS]
    out = out.dropna(subset=["evaluation_timestamp", "timeframe"])
    out = out.sort_values(["evaluation_timestamp", "timeframe"]).reset_index(drop=True)
    return out


def load_history(path: Path | None = None) -> pd.DataFrame:
    path = path or HISTORY_PATH
    if not path.exists():
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    frame = pd.read_parquet(path)
    return _normalize_history(frame)


def evaluation_set_complete(history: pd.DataFrame, evaluation_timestamp: Any) -> bool:
    if history is None or len(history) == 0:
        return False
    eval_ts = to_utc_ts(evaluation_timestamp)
    if eval_ts is None:
        return False
    subset = history.loc[history["evaluation_timestamp"] == eval_ts]
    if len(subset) == 0:
        return False
    try:
        assert_complete_evaluation_set(subset)
        return True
    except MTFAvailabilityError:
        return False


def latest_complete_evaluation(history: pd.DataFrame) -> pd.Timestamp | None:
    if history is None or len(history) == 0:
        return None
    for eval_ts in sorted(history["evaluation_timestamp"].dropna().unique(), reverse=True):
        if evaluation_set_complete(history, eval_ts):
            return pd.Timestamp(eval_ts)
    return None


def missing_evaluation_timestamps(
    history: pd.DataFrame,
    tip_eval: pd.Timestamp,
    *,
    m15: pd.DataFrame,
    bootstrap_window: int | None = None,
) -> list[pd.Timestamp]:
    """Return ascending missing complete-set evaluation timestamps up to tip_eval."""
    tip_eval = to_utc_ts(tip_eval)
    assert tip_eval is not None
    opens = pd.to_datetime(m15["timestamp"], utc=True).sort_values().unique()
    all_evals = [pd.Timestamp(o) + pd.Timedelta(seconds=900) for o in opens]
    all_evals = [e for e in all_evals if e <= tip_eval]

    last = latest_complete_evaluation(history)
    if last is None:
        if bootstrap_window is None:
            candidates = all_evals[-1:]
        else:
            candidates = all_evals[-int(bootstrap_window) :]
    else:
        candidates = [e for e in all_evals if e > last]

    missing: list[pd.Timestamp] = []
    for eval_ts in candidates:
        if not evaluation_set_complete(history, eval_ts):
            missing.append(eval_ts)
    return missing


def rows_for_latest_snapshot(history: pd.DataFrame, evaluation_timestamp: Any) -> list[dict[str, Any]]:
    eval_ts = to_utc_ts(evaluation_timestamp)
    subset = history.loc[history["evaluation_timestamp"] == eval_ts].copy()
    assert_complete_evaluation_set(subset)
    records = subset.sort_values("timeframe").to_dict(orient="records")
    # stringify timestamps for JSON
    out = []
    for rec in records:
        item = {}
        for k, v in rec.items():
            if isinstance(v, pd.Timestamp):
                item[k] = v.isoformat().replace("+00:00", "Z")
            elif pd.isna(v):
                item[k] = None
            else:
                item[k] = v
        out.append(item)
    return out


def build_latest_payload(history: pd.DataFrame, evaluation_timestamp: Any) -> dict[str, Any]:
    rows = rows_for_latest_snapshot(history, evaluation_timestamp)
    by_tf = {r["timeframe"]: r for r in rows}
    status_counts: dict[str, int] = {}
    for r in rows:
        key = str(r["availability_status"])
        status_counts[key] = status_counts.get(key, 0) + 1
    overall = "HEALTHY_WITH_UNSUPPORTED_TIMEFRAME"
    d1 = by_tf.get("D1") or {}
    if d1.get("availability_status") != "TIMEFRAME_NOT_LIVE":
        overall = "BROKEN"
    live_bad = [
        tf
        for tf in LIVE_SUPPORTED_TIMEFRAMES
        if (by_tf.get(tf) or {}).get("availability_status")
        in {"DATASET_MISSING", "SCHEMA_INVALID", "WRITER_DEAD", "UNKNOWN"}
    ]
    if live_bad:
        overall = "DEGRADED"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "owner": OWNER,
        "writer": WRITER,
        "stage_class": STAGE_CLASS,
        "latest_evaluation_timestamp": (
            to_utc_ts(evaluation_timestamp).isoformat().replace("+00:00", "Z")
            if to_utc_ts(evaluation_timestamp) is not None
            else None
        ),
        "overall_health": overall,
        "supported_timeframes": list(LIVE_SUPPORTED_TIMEFRAMES),
        "unsupported_timeframes": list(UNSUPPORTED_LIVE_TIMEFRAMES),
        "status_counts": status_counts,
        "timeframes": by_tf,
        "rows": rows,
        "trading_use_forbidden": True,
        "read_model_only": True,
    }


def build_status_metadata(
    history: pd.DataFrame,
    latest: dict[str, Any],
    *,
    writer_state: str,
    event: str,
    rows_added: int,
    source_tips: dict[str, Any],
) -> dict[str, Any]:
    pit = count_pit_violations(history)
    return {
        "writer": WRITER,
        "owner": OWNER,
        "writer_state": writer_state,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "latest_evaluation_timestamp": latest.get("latest_evaluation_timestamp"),
        "source_tips": source_tips,
        "rows": int(len(history)),
        "hash": sha256_file(HISTORY_PATH),
        "latest_hash": sha256_file(LATEST_PATH),
        "status_counts": latest.get("status_counts") or {},
        "future_join_count": pit["future_joins"],
        "unclosed_bar_join_count": pit["unclosed_bar_joins"],
        "duplicate_source_key_count": pit["duplicate_source_keys"],
        "duplicate_evaluation_timeframe_key_count": pit["duplicate_evaluation_timeframe_keys"],
        "supported_timeframes": list(LIVE_SUPPORTED_TIMEFRAMES),
        "unsupported_timeframes": list(UNSUPPORTED_LIVE_TIMEFRAMES),
        "overall_health": latest.get("overall_health"),
        "event": event,
        "rows_added": int(rows_added),
        "history_path": HISTORY_REL,
        "latest_path": LATEST_REL,
        "stage_class": STAGE_CLASS,
        "trading_use_forbidden": True,
    }


def _semantic_latest_equal(existing: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    if not existing:
        return False
    keys = ("latest_evaluation_timestamp", "timeframes", "overall_health", "status_counts")
    for key in keys:
        if existing.get(key) != new.get(key):
            return False
    return True


def refresh_runtime_status_registry() -> None:
    """Best-effort update of data/runtime/runtime_dataset_status.json."""
    try:
        from runtime_dataset_metadata import (
            emit_metadata_for_path,
            write_runtime_status_snapshot,
        )

        emit_metadata_for_path(HISTORY_REL, root=ROOT, metadata_origin="LIVE_WRITER")
        emit_metadata_for_path(LATEST_REL, root=ROOT, metadata_origin="LIVE_WRITER")
        write_runtime_status_snapshot(root=ROOT)
    except Exception as exc:  # noqa: BLE001
        print(f"MTF_AVAILABILITY_STATUS_WARN: {exc}")


def run_availability_cycle(
    *,
    bootstrap_window: int | None = None,
    enrich_climax: bool = False,
    m15_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Append missing evaluation sets and refresh latest snapshot.

    Fail-closed: on error previous artifacts remain and exception propagates to engine.
    """
    m15 = m15_frame if m15_frame is not None else load_m15_candles()
    tip_eval = safe_m15_evaluation_timestamp(m15)
    history = load_history()
    original_history = history.copy()
    prior_sha = sha256_file(HISTORY_PATH)
    prior_rows = int(len(history))

    missing = missing_evaluation_timestamps(
        history,
        tip_eval,
        m15=m15,
        bootstrap_window=bootstrap_window,
    )

    if not missing:
        # No-op path: do not rewrite history parquet.
        last = latest_complete_evaluation(history)
        if last is None:
            raise MTFAvailabilityError("NO_COMPLETE_EVALUATION_SET")
        latest = build_latest_payload(history, last)
        existing_latest = None
        if LATEST_PATH.exists():
            try:
                existing_latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
            except Exception:
                existing_latest = None
        latest_rewritten = False
        if not _semantic_latest_equal(existing_latest, latest):
            # keep generated_at from new payload only when rewriting
            _atomic_write_json(LATEST_PATH, latest)
            latest_rewritten = True
        else:
            latest = existing_latest or latest
        meta = build_status_metadata(
            history,
            latest,
            writer_state="RUNNING",
            event="MTF_AVAILABILITY_NO_NEW_EVALUATION",
            rows_added=0,
            source_tips={
                "m15_open_tip": to_utc_ts(m15["timestamp"].max()).isoformat().replace("+00:00", "Z"),
                "safe_evaluation_timestamp": tip_eval.isoformat().replace("+00:00", "Z"),
            },
        )
        _atomic_write_json(STATUS_PATH, meta)
        refresh_runtime_status_registry()
        print("MTF_AVAILABILITY_NO_NEW_EVALUATION")
        return {
            "ok": True,
            "event": "MTF_AVAILABILITY_NO_NEW_EVALUATION",
            "rows_added": 0,
            "history_rows": prior_rows,
            "history_sha_before": prior_sha,
            "history_sha_after": sha256_file(HISTORY_PATH),
            "history_rewritten": False,
            "latest_rewritten": latest_rewritten,
            "latest_evaluation_timestamp": tip_eval.isoformat().replace("+00:00", "Z"),
            "overall_health": latest.get("overall_health"),
        }

    # Build complete sets for each missing evaluation (atomic per eval).
    new_frames: list[pd.DataFrame] = []
    prev_eval = latest_complete_evaluation(history)
    generated_at = _utc_now()
    for eval_ts in missing:
        # If partial rows exist for this eval, drop them before rewrite of whole set.
        if len(history):
            history = history.loc[history["evaluation_timestamp"] != eval_ts].copy()
        rows = build_runtime_evaluation_rows(
            eval_ts,
            m15_frame=m15,
            previous_evaluation_timestamp=prev_eval,
            enrich_climax=enrich_climax,
            generated_at=generated_at,
        )
        assert_complete_evaluation_set(rows)
        chunk = _normalize_history(pd.DataFrame(rows))
        pit = count_pit_violations(chunk)
        if pit["future_joins"] or pit["unclosed_bar_joins"] or pit["duplicate_evaluation_timeframe_keys"]:
            raise MTFAvailabilityError(f"PIT gate failed for {eval_ts}: {pit}")
        new_frames.append(chunk)
        prev_eval = eval_ts

    added = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame(columns=HISTORY_COLUMNS)
    if len(history):
        combined = pd.concat([history, added], ignore_index=True)
    else:
        combined = added
    combined = _normalize_history(combined)
    if combined.duplicated(subset=["evaluation_timestamp", "timeframe"]).any():
        raise MTFAvailabilityError("duplicate_evaluation_timeframe_keys after merge")
    pit_all = count_pit_violations(combined)
    if (
        pit_all["future_joins"]
        or pit_all["unclosed_bar_joins"]
        or pit_all["duplicate_evaluation_timeframe_keys"]
    ):
        raise MTFAvailabilityError(f"PIT gate failed on combined history: {pit_all}")

    # Existing prefix must win: verify unchanged prefix when history existed.
    if prior_rows > 0:
        first_missing = missing[0]
        prefix_old = original_history.loc[
            original_history["evaluation_timestamp"] < first_missing
        ].copy()
        prefix_new = combined.loc[combined["evaluation_timestamp"] < first_missing].copy()
        cols = [
            "evaluation_timestamp",
            "timeframe",
            "availability_status",
            "availability_reason",
            "source_bar_close",
            "state_asof",
            "is_new_event",
        ]
        a = prefix_old[cols].astype(str).reset_index(drop=True)
        b = prefix_new[cols].astype(str).reset_index(drop=True)
        if not a.equals(b):
            raise MTFAvailabilityError("historical prefix changed — refuse write")

    _atomic_write_parquet(HISTORY_PATH, combined)
    last = latest_complete_evaluation(combined)
    if last is None:
        raise MTFAvailabilityError("post-write missing complete evaluation set")
    latest = build_latest_payload(combined, last)
    _atomic_write_json(LATEST_PATH, latest)
    meta = build_status_metadata(
        combined,
        latest,
        writer_state="RUNNING",
        event="MTF_AVAILABILITY_APPENDED",
        rows_added=int(len(added)),
        source_tips={
            "m15_open_tip": to_utc_ts(m15["timestamp"].max()).isoformat().replace("+00:00", "Z"),
            "safe_evaluation_timestamp": tip_eval.isoformat().replace("+00:00", "Z"),
            "appended_evaluations": [
                e.isoformat().replace("+00:00", "Z") for e in missing
            ],
        },
    )
    _atomic_write_json(STATUS_PATH, meta)
    # sidecar meta for history
    try:
        from runtime_dataset_metadata import write_dataset_metadata_atomic

        write_dataset_metadata_atomic(
            {
                **meta,
                "dataset_id": "multi_timeframe_availability_memory",
                "dataset_path": HISTORY_REL,
                "file_sha256": meta["hash"],
                "row_count": meta["rows"],
                "metadata_origin": "LIVE_WRITER",
            },
            root=ROOT,
            dataset_path=HISTORY_REL,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"MTF_AVAILABILITY_META_WARN: {exc}")
    refresh_runtime_status_registry()
    print(
        f"MTF_AVAILABILITY_APPENDED evaluations={len(missing)} rows_added={len(added)} tip={tip_eval}"
    )
    return {
        "ok": True,
        "event": "MTF_AVAILABILITY_APPENDED",
        "rows_added": int(len(added)),
        "evaluations_added": [e.isoformat().replace("+00:00", "Z") for e in missing],
        "history_rows": int(len(combined)),
        "history_sha_before": prior_sha,
        "history_sha_after": sha256_file(HISTORY_PATH),
        "history_rewritten": True,
        "latest_evaluation_timestamp": tip_eval.isoformat().replace("+00:00", "Z"),
        "overall_health": latest.get("overall_health"),
        "pit": pit_all,
    }
