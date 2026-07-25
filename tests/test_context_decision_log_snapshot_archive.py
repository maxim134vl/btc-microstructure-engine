"""Tests for Decision Log Snapshot Archive."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "live" / "archive_context_decision_log_snapshot.py"

spec = importlib.util.spec_from_file_location("archive_context_decision_log_snapshot", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["archive_context_decision_log_snapshot"] = mod
spec.loader.exec_module(mod)


def _ts(i: int) -> pd.Timestamp:
    return pd.Timestamp("2026-07-19 10:00:00", tz="UTC") + pd.Timedelta(minutes=15 * i)


def _decision_frame(*, conflict: bool = False, include_safety: bool = True) -> pd.DataFrame:
    rows = []
    for i in range(3):
        row = {
            "decision_id": f"id-{i}",
            "decision_written_at_utc": (_ts(i) + pd.Timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
            "candle_timestamp": _ts(i),
            "decision_payload_hash": f"{'a' * 63}{i}",
            "source_files_hash": f"{'b' * 63}{i}",
            "schema_version": "context_decision_log_v1",
            "logger_version": "append_context_decision_log_v1",
        }
        if include_safety:
            row.update(
                {
                    "action_allowed": False,
                    "shadow_only": True,
                    "execution_enabled": False,
                    "orders_created": False,
                    "paper_orders_created": False,
                    "visual_json_used_for_execution": False,
                }
            )
        rows.append(row)
    if conflict:
        rows.append(
            {
                "decision_id": "id-conflict",
                "decision_written_at_utc": (_ts(0) + pd.Timedelta(seconds=40)).isoformat().replace("+00:00", "Z"),
                "candle_timestamp": _ts(0),
                "decision_payload_hash": "c" * 64,
                "source_files_hash": "d" * 64,
                "schema_version": "context_decision_log_v1",
                "logger_version": "append_context_decision_log_v1",
                "action_allowed": False,
                "shadow_only": True,
                "execution_enabled": False,
                "orders_created": False,
                "paper_orders_created": False,
                "visual_json_used_for_execution": False,
            }
        )
    return pd.DataFrame(rows)


def test_missing_decision_log_returns_missing_decision_log(tmp_path: Path):
    out = mod.run_archive(
        source_path=tmp_path / "missing.parquet",
        snapshot_dir=tmp_path / "snaps",
        log_path=tmp_path / "archive.log",
    )
    assert out["status"] == "MISSING_DECISION_LOG"
    assert out["snapshot_created"] is False
    assert not list((tmp_path / "snaps").glob("*.parquet"))


def test_snapshot_created_for_new_decision_log(tmp_path: Path):
    src = tmp_path / "context_decision_log.parquet"
    _decision_frame().to_parquet(src, index=False)
    out = mod.run_archive(source_path=src, snapshot_dir=tmp_path / "snaps", log_path=tmp_path / "a.log")
    assert out["status"] == "SNAPSHOT_CREATED"
    assert out["snapshot_created"] is True
    assert Path(out["snapshot_path"]).exists()
    assert isinstance(out, dict)


def test_manifest_jsonl_appended(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    snap_dir = tmp_path / "snaps"
    out = mod.run_archive(source_path=src, snapshot_dir=snap_dir, log_path=tmp_path / "a.log")
    manifest = snap_dir / "manifest.jsonl"
    assert manifest.exists()
    lines = [ln for ln in manifest.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["source_file_sha256"] == out["source_file_sha256"]
    assert entry["rows"] == 3


def test_latest_snapshot_json_written(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    snap_dir = tmp_path / "snaps"
    out = mod.run_archive(source_path=src, snapshot_dir=snap_dir, log_path=tmp_path / "a.log")
    latest = json.loads((snap_dir / "latest_snapshot.json").read_text(encoding="utf-8"))
    assert latest["latest_status"] == "SNAPSHOT_CREATED"
    assert latest["latest_snapshot_path"] == out["snapshot_path"]
    assert latest["execution_readiness"] == "BLOCKED"


def test_source_sha_duplicate_is_skipped(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    snap_dir = tmp_path / "snaps"
    first = mod.run_archive(source_path=src, snapshot_dir=snap_dir, log_path=tmp_path / "a.log")
    second = mod.run_archive(source_path=src, snapshot_dir=snap_dir, log_path=tmp_path / "a.log")
    assert first["status"] == "SNAPSHOT_CREATED"
    assert second["status"] == "SKIPPED_DUPLICATE_SOURCE_SHA"
    assert second["skipped_duplicate_source_sha"] is True
    assert len(list(snap_dir.glob("context_decision_log_snapshot_*.parquet"))) == 1
    lines = [ln for ln in (snap_dir / "manifest.jsonl").read_text().splitlines() if ln.strip()]
    assert len(lines) == 1


def test_existing_snapshot_is_not_overwritten(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    snap_dir = tmp_path / "snaps"
    out = mod.run_archive(source_path=src, snapshot_dir=snap_dir, log_path=tmp_path / "a.log")
    snap = Path(out["snapshot_path"])
    before = snap.read_bytes()
    # force path collision by creating same-name empty file before force archive of changed content
    frame2 = _decision_frame()
    frame2.loc[0, "decision_payload_hash"] = "e" * 64
    frame2.to_parquet(src, index=False)
    out2 = mod.run_archive(source_path=src, snapshot_dir=snap_dir, log_path=tmp_path / "a.log", force=False)
    # new sha -> new snapshot, old untouched
    assert out2["status"] == "SNAPSHOT_CREATED"
    assert snap.read_bytes() == before
    assert out2["existing_snapshot_overwritten"] is False


def test_context_decision_log_parquet_is_not_mutated(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    before = src.read_bytes()
    mod.run_archive(source_path=src, snapshot_dir=tmp_path / "snaps", log_path=tmp_path / "a.log")
    assert src.read_bytes() == before


def test_duplicate_candle_different_hash_is_detected(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame(conflict=True).to_parquet(src, index=False)
    out = mod.run_archive(source_path=src, snapshot_dir=tmp_path / "snaps", log_path=tmp_path / "a.log")
    assert out["duplicate_different_hash_count"] >= 1
    assert out["mutation_conflict_count"] >= 1


def test_execution_safety_flags_are_calculated(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    out = mod.run_archive(source_path=src, snapshot_dir=tmp_path / "snaps", log_path=tmp_path / "a.log")
    assert out["action_allowed_all_false"] is True
    assert out["shadow_only_all_true"] is True
    assert out["execution_enabled_all_false"] is True
    assert out["orders_created_all_false"] is True
    assert out["paper_orders_created_all_false"] is True
    assert out["visual_json_used_for_execution_all_false"] is True


def test_missing_optional_safety_columns_does_not_fail(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame(include_safety=False).to_parquet(src, index=False)
    out = mod.run_archive(source_path=src, snapshot_dir=tmp_path / "snaps", log_path=tmp_path / "a.log")
    assert out["status"] == "SNAPSHOT_CREATED"
    assert out["action_allowed_all_false"] == "FIELD_MISSING"
    assert out["execution_readiness"] == "BLOCKED"


def test_snapshot_file_sha_equals_copied_content(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    out = mod.run_archive(source_path=src, snapshot_dir=tmp_path / "snaps", log_path=tmp_path / "a.log")
    assert out["snapshot_file_sha256"] == mod.sha256_file(Path(out["snapshot_path"]))
    assert out["snapshot_matches_source_sha"] is True
    assert out["snapshot_file_sha256"] == out["source_file_sha256"]


def test_manifest_contains_required_fields(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    snap_dir = tmp_path / "snaps"
    mod.run_archive(source_path=src, snapshot_dir=snap_dir, log_path=tmp_path / "a.log")
    entry = json.loads((snap_dir / "manifest.jsonl").read_text().splitlines()[0])
    required = {
        "snapshot_id",
        "created_at_utc",
        "source_path",
        "snapshot_path",
        "source_file_sha256",
        "snapshot_file_sha256",
        "rows",
        "unique_candle_timestamps",
        "first_candle_timestamp",
        "latest_candle_timestamp",
        "first_decision_written_at_utc",
        "latest_decision_written_at_utc",
        "duplicate_candle_count",
        "duplicate_different_hash_count",
        "mutation_conflict_count",
        "decision_payload_hash_present",
        "source_files_hash_present",
        "schema_version_present",
        "logger_version_present",
        "action_allowed_all_false",
        "shadow_only_all_true",
        "execution_enabled_all_false",
        "orders_created_all_false",
        "paper_orders_created_all_false",
        "visual_json_used_for_execution_all_false",
        "archive_schema_version",
        "archive_script_version",
    }
    assert required.issubset(entry.keys())


def test_atomic_temp_files_are_cleaned_or_ignored(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    snap_dir = tmp_path / "snaps"
    mod.run_archive(source_path=src, snapshot_dir=snap_dir, log_path=tmp_path / "a.log")
    temps = list(snap_dir.glob(".*.tmp"))
    assert temps == []


def test_status_json_is_returned(tmp_path: Path):
    src = tmp_path / "log.parquet"
    _decision_frame().to_parquet(src, index=False)
    out = mod.run_archive(source_path=src, snapshot_dir=tmp_path / "snaps", log_path=tmp_path / "a.log")
    # JSON-serializable
    dumped = json.dumps(out, default=str)
    assert "SNAPSHOT_CREATED" in dumped
    assert out["execution_readiness"] == "BLOCKED"
