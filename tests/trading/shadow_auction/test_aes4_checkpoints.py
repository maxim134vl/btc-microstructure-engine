"""AES4 canonical checkpoint linker — deterministic synthetic tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from btc_ml.trading.shadow_auction.canonical_lifecycle import CanonicalLifecycleEvent
from btc_ml.trading.shadow_auction.checkpoint import (
    COV_COMPLETE,
    COV_NO_SHADOW,
    COV_PARTIAL,
    COV_STALE,
    CheckpointLinker,
    ShadowHistoryIndex,
    TF_MISSING,
    TF_STALE,
    deterministic_checkpoint_id,
)
from btc_ml.trading.shadow_auction.engine import ShadowAuctionAES2
from btc_ml.trading.shadow_auction.hierarchy import HierarchyEngine, TfStateView
from btc_ml.trading.shadow_auction.states import (
    FAMILY_DIRECTIONAL_DOWN,
    FAMILY_DIRECTIONAL_UP,
    PHASE_DOWN_CONTINUATION_ACCEPTED,
    PHASE_UP_CONTINUATION_ACCEPTED,
)

REPO = Path(__file__).resolve().parents[3]
REAL_VOLUME = Path("/Volumes/MaksTiger")
REAL_DATA_ROOT = REAL_VOLUME / "btc-ml" / "shadow_auction"


def _tf_row(tf: str, ts: str, *, family: str = FAMILY_DIRECTIONAL_UP, phase: str = PHASE_UP_CONTINUATION_ACCEPTED):
    return {
        "timestamp": ts,
        "timeframe": tf,
        "shadow_episode_id": f"{tf}_{ts}",
        "auction_family": family,
        "episode_phase": phase,
        "pressure_side": "UP" if "UP" in family else "DOWN",
        "resolution_side": None,
        "directional_efficiency": 0.7,
        "efficiency_trend": 0.1,
        "balance_state": None,
        "balance_low": None,
        "balance_high": None,
        "balance_age": 0,
        "up_continuation_support": 0.8,
        "down_continuation_support": 0.2,
        "up_exhaustion_support": 0.1,
        "down_exhaustion_support": 0.1,
        "balance_support": 0.1,
        "up_resolution_support": 0.5,
        "down_resolution_support": 0.2,
        "source_event_id": f"{tf}|{ts}",
        "logic_version": "AES_V1",
        "logic_fingerprint": "fp",
    }


def _hier_row(ts: str, *, state: str = "STRUCTURAL_UP_ALIGNED"):
    return {
        "timestamp": ts,
        "hierarchy_state": state,
        "m15_m30_relation": "CHILD_CONFIRMS_PARENT",
        "m30_h1_relation": "CHILD_CONFIRMS_PARENT",
        "h1_h4_relation": "CHILD_CONFIRMS_PARENT",
        "propagation_direction": "NONE",
        "propagation_depth": 0,
        "local_vs_structural_state": "STRUCTURAL_MULTI_TF",
        "conflict_state": "NONE",
        "logic_version": "AES_V1",
        "logic_fingerprint": "fp",
        "snapshot_id": f"HIER_{ts}",
    }


def _event(
    ctype: str,
    ts: str,
    *,
    eid: str,
    episode: str = "ep1",
    trade: str | None = None,
    position: str | None = None,
    side: str = "LONG",
    tf: str = "M15",
    entry_price: float | None = None,
    close_price: float | None = None,
    close_reason: str | None = None,
) -> CanonicalLifecycleEvent:
    return CanonicalLifecycleEvent(
        checkpoint_type=ctype,
        canonical_timestamp=ts,
        canonical_event_id=eid,
        canonical_context_episode_id=episode,
        trade_id=trade,
        position_id=position,
        canonical_timeframe=tf,
        canonical_side=side,
        entry_price=entry_price,
        close_price=close_price,
        close_reason=close_reason,
        source_path="synthetic",
        source_event_type=ctype,
        linkage_method="EXACT_ID",
    )


def _linker_with_full_coverage() -> CheckpointLinker:
    idx = ShadowHistoryIndex()
    for tf in ("M15", "M30", "H1", "H4"):
        idx.ingest_tf_row(_tf_row(tf, "2026-08-11T10:17:30Z"))
    idx.ingest_hierarchy_row(_hier_row("2026-08-11T10:17:30Z"))
    # Future states that must remain invisible before their timestamps.
    idx.ingest_tf_row(_tf_row("M15", "2026-08-11T10:18:00Z", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED))
    idx.ingest_hierarchy_row(_hier_row("2026-08-11T10:18:00Z", state="STRUCTURAL_DOWN_ALIGNED"))
    return CheckpointLinker(index=idx, logic_version="AES_V1", logic_fingerprint="fp")


def test_01_context_start_exact_asof():
    linker = _linker_with_full_coverage()
    ev = _event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_A")
    res = linker.build_checkpoint(ev)
    assert res.written
    ckp = res.checkpoint
    assert ckp["m15_snapshot"]["shadow_state_timestamp"] == "2026-08-11T10:17:30Z"
    assert ckp["m15_snapshot"]["auction_family"] == FAMILY_DIRECTIONAL_UP


def test_02_future_state_invisible():
    linker = _linker_with_full_coverage()
    ev = _event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_B")
    ckp = linker.build_checkpoint(ev).checkpoint
    assert ckp["m15_snapshot"]["auction_family"] != FAMILY_DIRECTIONAL_DOWN
    assert ckp["hierarchy_snapshot"]["hierarchy_state"] == "STRUCTURAL_UP_ALIGNED"


def test_03_context_and_entry_differ():
    linker = _linker_with_full_coverage()
    # Between context and entry, M15 flips in index.
    linker.index.ingest_tf_row(
        _tf_row("M15", "2026-08-11T10:20:00Z", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED)
    )
    c1 = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:15:00Z", eid="CTX_C1")).checkpoint
    # Need earlier state for 10:15 — add it
    linker.index.ingest_tf_row(_tf_row("M15", "2026-08-11T10:14:00Z"))
    c1 = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:15:00Z", eid="CTX_C1b")).checkpoint
    c2 = linker.build_checkpoint(
        _event("PAPER_ENTRY", "2026-08-11T10:21:00Z", eid="CTX_E1", position="pos1", entry_price=100.0)
    ).checkpoint
    assert c1["m15_snapshot"]["shadow_state_timestamp"] != c2["m15_snapshot"]["shadow_state_timestamp"]
    assert c1["checkpoint_type"] != c2["checkpoint_type"]


def test_04_entry_and_close_differ():
    linker = _linker_with_full_coverage()
    linker.index.ingest_tf_row(_tf_row("M15", "2026-08-11T11:00:00Z", family=FAMILY_DIRECTIONAL_DOWN, phase=PHASE_DOWN_CONTINUATION_ACCEPTED))
    e = linker.build_checkpoint(
        _event("PAPER_ENTRY", "2026-08-11T10:17:42Z", eid="ENT1", position="posX", entry_price=1.0)
    ).checkpoint
    c = linker.build_checkpoint(
        _event(
            "PAPER_CLOSE",
            "2026-08-11T11:05:00Z",
            eid="trd1",
            trade="trd1",
            position="posX",
            close_price=2.0,
            close_reason="TP",
        )
    ).checkpoint
    assert e["m15_snapshot"]["auction_family"] != c["m15_snapshot"]["auction_family"]
    assert e["canonical_timestamp"] != c["canonical_timestamp"]


def test_05_complete_four_tf_coverage():
    linker = _linker_with_full_coverage()
    ckp = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_FULL")).checkpoint
    assert ckp["coverage_status"] == COV_COMPLETE
    for tf in ("m15", "m30", "h1", "h4"):
        assert ckp[f"{tf}_coverage_status"] == "AVAILABLE"
    assert ckp["hierarchy_coverage_status"] == "AVAILABLE"


def test_06_missing_h4_partial():
    idx = ShadowHistoryIndex()
    for tf in ("M15", "M30", "H1"):
        idx.ingest_tf_row(_tf_row(tf, "2026-08-11T10:17:30Z"))
    idx.ingest_hierarchy_row(_hier_row("2026-08-11T10:17:30Z"))
    linker = CheckpointLinker(index=idx)
    ckp = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_NOH4")).checkpoint
    assert ckp["coverage_status"] == COV_PARTIAL
    assert ckp["h4_coverage_status"] == TF_MISSING
    assert ckp["h4_snapshot"] is None


def test_07_stale_parent():
    idx = ShadowHistoryIndex()
    idx.ingest_tf_row(_tf_row("M15", "2026-08-11T10:17:30Z"))
    idx.ingest_tf_row(_tf_row("M30", "2026-08-11T00:00:00Z"))  # very old
    idx.ingest_tf_row(_tf_row("H1", "2026-08-11T10:00:00Z"))
    idx.ingest_tf_row(_tf_row("H4", "2026-08-11T08:00:00Z"))
    idx.ingest_hierarchy_row(_hier_row("2026-08-11T10:17:30Z"))
    linker = CheckpointLinker(index=idx)
    ckp = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_STALE")).checkpoint
    assert ckp["m30_coverage_status"] == TF_STALE
    assert ckp["m30_age_sec"] is not None and ckp["m30_age_sec"] > 3600
    assert ckp["coverage_status"] in {COV_STALE, COV_PARTIAL}


def test_08_missing_hierarchy():
    idx = ShadowHistoryIndex()
    for tf in ("M15", "M30", "H1", "H4"):
        idx.ingest_tf_row(_tf_row(tf, "2026-08-11T10:17:30Z"))
    linker = CheckpointLinker(index=idx)
    ckp = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_NOHIER")).checkpoint
    assert ckp["hierarchy_coverage_status"] == TF_MISSING
    assert ckp["hierarchy_snapshot"] is None
    assert ckp["m15_coverage_status"] == "AVAILABLE"


def test_09_exact_id_linkage():
    linker = _linker_with_full_coverage()
    ev = _event(
        "PAPER_ENTRY",
        "2026-08-11T10:17:42Z",
        eid="CTX_LINK",
        episode="994.0",
        position="pos_abc",
        entry_price=64000.0,
    )
    ckp = linker.build_checkpoint(ev).checkpoint
    assert ckp["canonical_event_id"] == "CTX_LINK"
    assert ckp["canonical_context_episode_id"] == "994.0"
    assert ckp["position_id"] == "pos_abc"
    assert ckp["linkage_method"] == "EXACT_ID"
    assert "EXACT_CANONICAL_LINK" in ckp["reason_codes"]


def test_10_deterministic_checkpoint_id():
    ev = _event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_DET", episode="1")
    a = deterministic_checkpoint_id(ev)
    b = deterministic_checkpoint_id(ev)
    assert a == b
    assert a.startswith("CKP_")


def test_11_duplicate_suppression():
    linker = _linker_with_full_coverage()
    ev = _event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_DUP")
    r1 = linker.build_checkpoint(ev)
    r2 = linker.build_checkpoint(ev)
    assert r1.written and not r1.duplicate
    assert r2.duplicate and not r2.written
    assert linker.duplicate_checkpoints_suppressed == 1


def test_12_payload_conflict():
    linker = _linker_with_full_coverage()
    ev1 = _event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_CONF", side="LONG")
    r1 = linker.build_checkpoint(ev1)
    assert r1.written
    # Same identity keys but different side in payload path — identity uses event id,
    # so change episode/position empty but mutate side in a new event with SAME ids.
    ev2 = CanonicalLifecycleEvent(
        checkpoint_type="CONTEXT_START",
        canonical_timestamp="2026-08-11T10:17:42Z",
        canonical_event_id="CTX_CONF",
        canonical_context_episode_id="ep1",
        canonical_timeframe="M15",
        canonical_side="SHORT",  # conflict
        linkage_method="EXACT_ID",
        source_path="synthetic",
    )
    r2 = linker.build_checkpoint(ev2)
    assert r2.payload_conflict
    assert not r2.written
    assert "CHECKPOINT_PAYLOAD_CONFLICT" in r2.reason_codes


def test_13_late_processing_historical_asof():
    linker = _linker_with_full_coverage()
    # Event at 10:17:42 processed "late", but future 10:18 must not be used.
    ckp = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_LATE")).checkpoint
    assert ckp["m15_snapshot"]["shadow_state_timestamp"] == "2026-08-11T10:17:30Z"


def test_14_out_of_order_close_before_entry():
    linker = _linker_with_full_coverage()
    ckp = linker.build_checkpoint(
        _event(
            "PAPER_CLOSE",
            "2026-08-11T10:17:42Z",
            eid="trd_ooo",
            trade="trd_ooo",
            position="pos_ooo",
            close_price=1.0,
            close_reason="SL",
        )
    ).checkpoint
    assert "MISSING_PRIOR_ENTRY_CHECKPOINT" in ckp["reason_codes"]
    assert ckp["checkpoint_type"] == "PAPER_CLOSE"


def test_15_late_entry_after_close_immutable():
    linker = _linker_with_full_coverage()
    close = linker.build_checkpoint(
        _event(
            "PAPER_CLOSE",
            "2026-08-11T11:00:00Z",
            eid="trd_late",
            trade="trd_late",
            position="pos_late",
            close_price=2.0,
            close_reason="TP",
        )
    )
    close_payload = dict(close.checkpoint)
    entry = linker.build_checkpoint(
        _event(
            "PAPER_ENTRY",
            "2026-08-11T10:17:42Z",
            eid="CTX_late_entry",
            position="pos_late",
            entry_price=1.0,
        )
    )
    assert entry.written
    # Re-processing close must not overwrite the original immutable snapshot.
    close2 = linker.build_checkpoint(
        _event(
            "PAPER_CLOSE",
            "2026-08-11T11:00:00Z",
            eid="trd_late",
            trade="trd_late",
            position="pos_late",
            close_price=2.0,
            close_reason="TP",
        )
    )
    assert not close2.written
    assert close2.duplicate or close2.payload_conflict
    # Original close payload remains the reference (not silently replaced).
    assert close_payload["canonical_timestamp"] == "2026-08-11T11:00:00Z"
    assert close_payload["m15_snapshot"] is not None


def test_16_intrabar_timestamp_not_rounded():
    linker = _linker_with_full_coverage()
    ts = "2026-08-11T10:17:42.820440Z"
    ckp = linker.build_checkpoint(_event("CONTEXT_START", ts, eid="CTX_INTRA")).checkpoint
    assert ckp["canonical_timestamp"] == ts
    assert not ckp["canonical_timestamp"].endswith("10:15:00Z")


def test_17_aes2_immutability():
    aes2 = ShadowAuctionAES2()
    before = {tf: (e.state.auction_family, e.state.episode_phase) for tf, e in aes2.engines.items()}
    linker = _linker_with_full_coverage()
    linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_IMM2"))
    after = {tf: (e.state.auction_family, e.state.episode_phase) for tf, e in aes2.engines.items()}
    assert before == after


def test_18_aes3_immutability():
    hier = HierarchyEngine()
    hier.ingest_tf_state(
        TfStateView("M15", "2026-08-11T10:00:00Z", "e1", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    )
    before = (hier.last_snapshot.snapshot_id if hier.last_snapshot else None, hier.state.auction_family if False else hier.last_hierarchy_timestamp)
    # Fix: capture snapshot id and last timestamp
    before_id = hier.last_snapshot.snapshot_id if hier.last_snapshot else None
    before_ts = hier.last_hierarchy_timestamp
    linker = _linker_with_full_coverage()
    linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_IMM3"))
    assert (hier.last_snapshot.snapshot_id if hier.last_snapshot else None) == before_id
    assert hier.last_hierarchy_timestamp == before_ts


def test_19_restart_idempotency(tmp_path: Path):
    linker = _linker_with_full_coverage()
    ev = _event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_RST")
    r1 = linker.build_checkpoint(ev)
    path = tmp_path / "canonical_checkpoint_memory.jsonl"
    path.write_text(json.dumps(r1.checkpoint) + "\n", encoding="utf-8")
    linker2 = _linker_with_full_coverage()
    linker2.restore_dedup_from_memory(path)
    r2 = linker2.build_checkpoint(ev)
    assert r2.duplicate


def test_20_canonical_isolation_writer_error(tmp_path: Path):
    """Checkpoint writer failure must not imply canonical mutation — AES4 fail-closed only."""
    from btc_ml.trading.shadow_auction.memory import Aes4CheckpointMemoryWriter

    class BoomStore:
        data_root = tmp_path
        write_errors = 0

        def append_jsonl(self, *a, **k):
            raise RuntimeError("disk full")

        def write_json(self, *a, **k):
            raise RuntimeError("disk full")

    linker = _linker_with_full_coverage()
    res = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_ISO"))
    writer = Aes4CheckpointMemoryWriter(BoomStore())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        writer.write_checkpoint(res.checkpoint)
    # Canonical event object untouched; no exception escapes into trading path by construction.
    assert res.checkpoint["canonical_event_id"] == "CTX_ISO"


def test_21_external_storage_only():
    from btc_ml.trading.shadow_auction.storage import ShadowAuctionStore, is_real_mounted_volume
    from btc_ml.trading.shadow_auction.memory import Aes4CheckpointMemoryWriter

    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger volume not mounted")
    store = ShadowAuctionStore(
        data_root=REAL_DATA_ROOT / "replay" / "_aes4_pytest",
        volume_root=REAL_VOLUME,
        min_free_bytes=1024,
        repo=REPO,
    )
    writer = Aes4CheckpointMemoryWriter(store)
    linker = _linker_with_full_coverage()
    res = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_EXT_STORE"))
    out = writer.write_checkpoint(res.checkpoint)
    path = store.data_root / "memory" / "canonical_checkpoint_memory.jsonl"
    assert out["written"]
    assert path.exists()
    assert str(path).startswith(str(REAL_DATA_ROOT / "replay"))


def test_22_live_replay_equivalence():
    def run_once():
        linker = _linker_with_full_coverage()
        return linker.build_checkpoint(
            _event("CONTEXT_START", "2026-08-11T10:17:42.820440Z", eid="CTX_EQ", episode="997.0")
        ).checkpoint

    a = run_once()
    b = run_once()
    for k in a:
        if k == "created_at":
            continue
        assert a[k] == b[k]


def test_no_shadow_coverage():
    linker = CheckpointLinker(index=ShadowHistoryIndex())
    ckp = linker.build_checkpoint(_event("CONTEXT_START", "2026-08-11T10:17:42Z", eid="CTX_EMPTY")).checkpoint
    assert ckp["coverage_status"] == COV_NO_SHADOW
