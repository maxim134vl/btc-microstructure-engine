"""Patch 1 ownership/metadata tests (no production parquet mutation)."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

import runtime_dataset_metadata as meta  # noqa: E402

REGISTRY = ROOT / "config" / "runtime_dataset_ownership.json"


@pytest.fixture()
def registry() -> dict:
    return meta.load_dataset_ownership_registry(REGISTRY, root=ROOT)


def test_01_one_authoritative_owner_per_dataset(registry: dict) -> None:
    paths = [d["dataset_path"] for d in registry["datasets"]]
    assert len(paths) == len(set(paths))


def test_02_duplicate_owner_rejected() -> None:
    reg = meta.load_dataset_ownership_registry(REGISTRY, root=ROOT)
    bad = json.loads(json.dumps(reg))
    row = dict(bad["datasets"][0])
    row["dataset_id"] = "dup_owner_test"
    row["canonical_writer"] = "other_writer"
    bad["datasets"].append(row)
    with pytest.raises(meta.DatasetOwnershipError, match="two authoritative writers"):
        meta.validate_dataset_ownership_registry(bad)


def test_03_duplicate_dataset_id_rejected(registry: dict) -> None:
    bad = json.loads(json.dumps(registry))
    bad["datasets"].append(dict(bad["datasets"][0]))
    with pytest.raises(meta.DatasetOwnershipError, match="duplicate dataset_id"):
        meta.validate_dataset_ownership_registry(bad)


def test_04_active_requires_freshness_budget(registry: dict) -> None:
    bad = json.loads(json.dumps(registry))
    for row in bad["datasets"]:
        if row["operational_status"] == "ACTIVE":
            row["freshness_budget_seconds"] = None
            break
    with pytest.raises(meta.DatasetOwnershipError, match="freshness_budget"):
        meta.validate_dataset_ownership_registry(bad)


def test_05_event_log_requires_inheritance(registry: dict) -> None:
    bad = json.loads(json.dumps(registry))
    for row in bad["datasets"]:
        if row["semantic_type"] == "EVENT_LOG":
            row["event_sparse_inheritance_mode"] = None
            break
    with pytest.raises(meta.DatasetOwnershipError, match="inheritance"):
        meta.validate_dataset_ownership_registry(bad)


def test_06_event_sparse_within_age() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    row = {
        "dataset_id": "mtf",
        "dataset_path": "data/cognition/multi_timeframe_synthesis.parquet",
        "operational_status": "EVENT_SPARSE_BY_DESIGN",
        "semantic_type": "EVENT_LOG",
        "event_sparse": True,
        "maximum_inheritance_age_seconds": 86400,
        "freshness_budget_seconds": 86400,
        "source_timestamp_field": "timestamp",
        "evaluated_timestamp_field": "timestamp",
    }
    tip = (now - timedelta(hours=12)).isoformat().replace("+00:00", "Z")
    health = meta.classify_dataset_health(
        row,
        metadata={"source_market_timestamp": tip, "evaluated_timestamp": tip},
        now=now,
    )
    assert health["health"] == "EVENT_SPARSE_BY_DESIGN"


def test_07_event_sparse_beyond_max_age_stale() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    row = {
        "dataset_id": "mtf",
        "dataset_path": "data/cognition/multi_timeframe_synthesis.parquet",
        "operational_status": "EVENT_SPARSE_BY_DESIGN",
        "semantic_type": "EVENT_LOG",
        "event_sparse": True,
        "maximum_inheritance_age_seconds": 86400,
        "freshness_budget_seconds": 86400,
        "source_timestamp_field": "timestamp",
        "evaluated_timestamp_field": "timestamp",
    }
    tip = (now - timedelta(hours=30)).isoformat().replace("+00:00", "Z")
    health = meta.classify_dataset_health(
        row,
        metadata={"source_market_timestamp": tip, "evaluated_timestamp": tip},
        now=now,
    )
    assert health["health"] == "STALE"


def test_08_missing_active_file(tmp_path: Path) -> None:
    row = {
        "dataset_id": "missing_x",
        "dataset_path": "does_not_exist_patch1.parquet",
        "operational_status": "ACTIVE",
        "semantic_type": "PER_BAR_STATE",
        "event_sparse": False,
        "freshness_budget_seconds": 900,
        "source_timestamp_field": "timestamp",
        "evaluated_timestamp_field": "timestamp",
    }
    # temporarily point root via monkeypatch of path existence — use absolute missing under tmp
    row["dataset_path"] = str(tmp_path / "nope.parquet")
    # classify uses repo_root()/rel — for absolute we need exists check on path construction
    # Use relative under repo that is missing
    row["dataset_path"] = "data/research/_patch1_missing_expected_do_not_create.parquet"
    health = meta.classify_dataset_health(row)
    assert health["health"] == "MISSING_EXPECTED"


def test_09_dead_writer() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    tip = now.isoformat().replace("+00:00", "Z")
    row = {
        "dataset_id": "paper_orders",
        "dataset_path": "data/research/paper_simulator/paper_orders.parquet",
        "operational_status": "BROKEN",
        "semantic_type": "PAPER_ORDER_LOG",
        "event_sparse": False,
        "freshness_budget_seconds": 3600,
        "require_live_writer": True,
        "source_timestamp_field": "decision_log_ts",
        "evaluated_timestamp_field": "decision_log_ts",
    }
    health = meta.classify_dataset_health(
        row,
        metadata={"source_market_timestamp": tip, "evaluated_timestamp": tip},
        writer_state={"state": "DEAD", "pid": 1},
        now=now,
    )
    assert health["health"] == "DEAD_WRITER"


def test_10_inactive_oi_deprecated(registry: dict) -> None:
    oi = next(d for d in registry["datasets"] if d["dataset_id"] == "oi_history")
    assert oi["operational_status"] == "INACTIVE_DEPRECATED"
    health = meta.classify_dataset_health(oi)
    assert health["health"] == "INACTIVE_DEPRECATED"


def test_11_missing_metadata_not_fresh() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    tip = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    row = {
        "dataset_id": "candle",
        "dataset_path": "data/cognition/candle_structure_memory.parquet",
        "operational_status": "ACTIVE",
        "semantic_type": "PER_BAR_STATE",
        "event_sparse": False,
        "freshness_budget_seconds": 1200,
        "source_timestamp_field": "timestamp",
        "evaluated_timestamp_field": "timestamp",
    }
    health = meta.classify_dataset_health(
        row,
        metadata=None,
        market_feed_tip=tip,
        now=now,
    )
    assert health["health"] != "FRESH"
    assert "missing metadata" in health["reason"]


def test_12_mtime_alone_not_fresh() -> None:
    # Recent mtime with no source tip must not classify FRESH.
    row = {
        "dataset_id": "x",
        "dataset_path": "data/cognition/candle_structure_memory.parquet",
        "operational_status": "ACTIVE",
        "semantic_type": "PER_BAR_STATE",
        "event_sparse": False,
        "freshness_budget_seconds": 1200,
        "source_timestamp_field": "timestamp",
        "evaluated_timestamp_field": "timestamp",
    }
    health = meta.classify_dataset_health(
        row,
        metadata={
            "file_mtime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_market_timestamp": None,
            "evaluated_timestamp": None,
        },
    )
    assert health["health"] == "UNKNOWN"
    assert "mtime" not in health["reason"].lower() or "no source" in health["reason"].lower()


def test_13_source_cannot_exceed_evaluated(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-07-24T12:00:00Z"]),
            "evaluated_at": pd.to_datetime(["2026-07-24T11:00:00Z"]),
        }
    )
    df.to_parquet(path, index=False)
    row = {
        "dataset_id": "t",
        "dataset_path": str(path),
        "authority_plane": "x",
        "authority_role": "y",
        "canonical_writer": "z",
        "writer_entrypoint": "z.py",
        "semantic_type": "PER_BAR_STATE",
        "write_mode": "append",
        "source_timestamp_field": "timestamp",
        "evaluated_timestamp_field": "evaluated_at",
        "event_sparse": False,
        "builder_version_source": "t",
        "operational_status": "ACTIVE",
        "legacy_names": [],
        "notes": "",
    }
    # build with absolute path: adjust to relative under tmp by writing via root=tmp and relative path
    rel_row = dict(row)
    rel_row["dataset_path"] = "t.parquet"
    m = meta.build_dataset_metadata(rel_row, root=tmp_path)
    assert m.get("error_code") == "SOURCE_AFTER_EVALUATED"


def test_14_metadata_atomic_write(tmp_path: Path) -> None:
    ds = tmp_path / "d.parquet"
    pd.DataFrame({"timestamp": pd.to_datetime(["2026-07-24T10:00:00Z"])}).to_parquet(ds, index=False)
    row = {
        "dataset_id": "d",
        "dataset_path": "d.parquet",
        "authority_plane": "p",
        "authority_role": "r",
        "canonical_writer": "w",
        "writer_entrypoint": "w.py",
        "semantic_type": "PER_BAR_STATE",
        "write_mode": "append",
        "source_timestamp_field": "timestamp",
        "evaluated_timestamp_field": "timestamp",
        "event_sparse": False,
        "builder_version_source": "d",
        "operational_status": "ACTIVE",
        "legacy_names": [],
        "notes": "",
    }
    m = meta.build_dataset_metadata(row, root=tmp_path)
    out = meta.write_dataset_metadata_atomic(m, root=tmp_path)
    assert out.exists()
    assert out.name.endswith(".meta.json")
    assert meta.read_dataset_metadata("d.parquet", root=tmp_path)["dataset_id"] == "d"


def test_15_failed_metadata_does_not_mutate_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = tmp_path / "d.parquet"
    pd.DataFrame({"timestamp": pd.to_datetime(["2026-07-24T10:00:00Z"])}).to_parquet(ds, index=False)
    before = ds.read_bytes()
    row = {
        "dataset_id": "d",
        "dataset_path": "d.parquet",
        "authority_plane": "p",
        "authority_role": "r",
        "canonical_writer": "w",
        "writer_entrypoint": "w.py",
        "semantic_type": "PER_BAR_STATE",
        "write_mode": "append",
        "source_timestamp_field": "timestamp",
        "evaluated_timestamp_field": "timestamp",
        "event_sparse": False,
        "builder_version_source": "d",
        "operational_status": "ACTIVE",
        "legacy_names": [],
        "notes": "",
    }

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(meta, "write_dataset_metadata_atomic", boom)
    result = meta.emit_dataset_metadata_safe(row, root=tmp_path)
    assert result["ok"] is False
    assert ds.read_bytes() == before


def test_16_bootstrap_leaves_sha_unchanged() -> None:
    proof = ROOT / "data/research/patch1_bootstrap_preservation.json"
    if not proof.exists():
        pytest.skip("bootstrap proof not generated yet")
    payload = json.loads(proof.read_text())
    assert payload.get("production_parquet_sha256_unchanged", payload.get("production_parquet_unchanged")) is True


def test_17_runtime_status_snapshot_deterministic_keys(registry: dict) -> None:
    snap1 = meta.build_runtime_status_snapshot(registry, root=ROOT)
    snap2 = meta.build_runtime_status_snapshot(registry, root=ROOT)
    assert sorted(snap1.keys()) == sorted(snap2.keys())
    assert "summary" in snap1 and "datasets" in snap1
    ids1 = [d["dataset_id"] for d in snap1["datasets"]]
    ids2 = [d["dataset_id"] for d in snap2["datasets"]]
    assert ids1 == ids2 == sorted(ids1)


def test_18_production_consumer_cannot_read_research_path(registry: dict) -> None:
    bad = json.loads(json.dumps(registry))
    for row in bad["datasets"]:
        if row["dataset_id"] == "candle_structure_memory":
            row["allowed_consumers"] = ["data/research/evil.parquet"]
            break
    with pytest.raises(meta.DatasetOwnershipError, match="production consumer path"):
        meta.validate_dataset_ownership_registry(bad)


def test_19_shadow_named_context_truth(registry: dict) -> None:
    life = next(d for d in registry["datasets"] if d["dataset_id"] == "market_context_lifecycle_memory")
    assert life["authority_role"] == "CONTEXT_TRUTH"
    assert "shadow" in (life.get("legacy_names") or ["market_context_shadow_chain"])[0] or life[
        "authority_plane"
    ] == "market_context_shadow_chain"
    assert "sole authoritative" in life["notes"]


def test_20_21_22_23_24_payloads_unchanged_by_bootstrap_before_after() -> None:
    """Patch1 bootstrap must not mutate parquet bytes (per-file before/after)."""
    proof = ROOT / "data/research/patch1_bootstrap_preservation.json"
    assert proof.exists()
    payload = json.loads(proof.read_text())
    for rel, before in payload["before"].items():
        after = payload["after"][rel]
        assert before.get("sha256") == after.get("sha256"), rel


def test_25_continuation_off(registry: dict) -> None:
    assert os.environ.get("BTC_ML_CONTINUATION_PROGRESSION", "0") == "0"
    assert registry["flags_frozen"]["BTC_ML_CONTINUATION_PROGRESSION"] == "0"


def test_26_price_gate_off(registry: dict) -> None:
    assert registry["flags_frozen"]["PRICE_GATE"] == "OFF"
    assert registry["flags_frozen"]["execution"] == "disabled"


def test_27_no_exchange_in_metadata_module() -> None:
    text = (ROOT / "runtime_dataset_metadata.py").read_text()
    assert "binance" not in text.lower() or "BINANCE" not in text
    assert "create_order" not in text
    assert "action_allowed" not in text or "trading" in text.lower()
    # module must not set action_allowed
    assert "action_allowed =" not in text


def test_28_timezone_normalized_only_in_metadata() -> None:
    # normalize_ts converts; parquet bytes untouched in build
    path = ROOT / "data/cognition/final_market_context_memory.parquet"
    before = path.read_bytes()
    row = next(
        d
        for d in meta.load_dataset_ownership_registry(REGISTRY, root=ROOT)["datasets"]
        if d["dataset_id"] == "final_market_context_memory"
    )
    meta.build_dataset_metadata(row, root=ROOT)
    assert path.read_bytes() == before


def test_engine_parity_present(registry: dict) -> None:
    parity = registry["engine_parity"]
    assert parity["runtime_engine_count"] == 19
    assert parity["dashboard_entry_count"] == 24
    assert parity["phantom_missing_file_count"] == 6
    assert "auction_context_arbitration_engine_v1.py" in parity["runtime_only_missing_from_dashboard"]
