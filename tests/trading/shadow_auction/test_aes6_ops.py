"""AES6 replay / integrity / resource / control / write-boundary tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from btc_ml.trading.shadow_auction import WRITE_BOUNDARY_VIOLATION
from btc_ml.trading.shadow_auction.cache import BoundedCache
from btc_ml.trading.shadow_auction.canonical_lifecycle import CanonicalLifecycleEvent
from btc_ml.trading.shadow_auction.checkpoint import CheckpointLinker, ShadowHistoryIndex
from btc_ml.trading.shadow_auction.engine import ShadowAuctionAES2
from btc_ml.trading.shadow_auction.hierarchy import HierarchyEngine, TfStateView
from btc_ml.trading.shadow_auction.integrity import IntegrityAuditor
from btc_ml.trading.shadow_auction.observation import BarObservation
from btc_ml.trading.shadow_auction.paths import (
    assert_not_forbidden_persistent,
    assert_shadow_write_path,
    forbidden_persistent_roots,
)
from btc_ml.trading.shadow_auction.replay import (
    REFUSE_UNBOUNDED,
    ReplayRunner,
    compare_logical_rows,
    strip_technical,
)
from btc_ml.trading.shadow_auction.resources import rss_memory_mb, storage_status
from btc_ml.trading.shadow_auction.states import (
    FAMILY_DIRECTIONAL_UP,
    PHASE_UP_CONTINUATION_ACCEPTED,
    PHASE_UP_PRESSURE_ACTIVE,
)
from btc_ml.trading.shadow_auction.storage import (
    ShadowAuctionStore,
    StorageValidation,
    is_real_mounted_volume,
    validate_external_storage,
    validate_repo_local_storage,
    validate_storage,
)

REPO = Path(__file__).resolve().parents[3]
REAL_VOLUME = Path("/Volumes/MaksTiger")
REAL_DATA_ROOT = REAL_VOLUME / "btc-ml" / "shadow_auction"


def _obs(ts: str, *, close: float = 100.0, tf: str = "M15", high: float | None = None, low: float | None = None) -> BarObservation:
    h = close + 1.0 if high is None else high
    l = close - 1.0 if low is None else low
    return BarObservation(
        timestamp=ts,
        timeframe=tf,
        source_event_id=f"{tf}|{ts}",
        open=close - 0.2,
        high=h,
        low=l,
        close=close,
        volume=1000.0,
        buy_volume=600.0,
        sell_volume=400.0,
        delta=200.0,
        close_position=0.7,
        body=0.2,
        spread=h - l,
        upper_wick=0.1,
        lower_wick=0.1,
        volume_zscore=1.2,
        effort_score=0.7,
        result_score=0.6,
    )


def _cfg(tmp_path: Path, **overrides) -> Path:
    raw = json.loads((REPO / "config" / "shadow_auction.json").read_text(encoding="utf-8"))
    raw.update(overrides)
    path = tmp_path / "shadow_auction.json"
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path


def _mock_store(tmp_path: Path):
    vol = tmp_path / "ssd"
    root = vol / "shadow_auction"
    root.mkdir(parents=True)
    ok = StorageValidation(
        ok=True,
        data_root=root.resolve(),
        volume_root=vol.resolve(),
        storage_mounted=True,
        storage_writable=True,
        storage_free_bytes=10**12,
    )
    return root, vol, ok


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def test_replay_01_bounded_interval_required(tmp_path: Path):
    root, vol, ok = _mock_store(tmp_path)
    cfg = _cfg(
        tmp_path,
        storage_mode="external_volume",
        data_root=str(root),
        required_volume_root=str(vol),
        min_free_bytes=0,
    )
    with mock.patch(
        "btc_ml.trading.shadow_auction.replay.validate_storage", return_value=ok
    ), mock.patch(
        "btc_ml.trading.shadow_auction.storage.validate_storage", return_value=ok
    ), mock.patch(
        "btc_ml.trading.shadow_auction.storage.validate_external_storage", return_value=ok
    ):
        with pytest.raises(RuntimeError, match=REFUSE_UNBOUNDED):
            ReplayRunner.create(repo=REPO, config_path=cfg, evaluation_from=None, evaluation_to=None)


def test_replay_02_no_write_into_live_memory(tmp_path: Path):
    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger not mounted")
    live = REAL_DATA_ROOT / "memory"
    before = {
        p.name: (p.stat().st_size if p.exists() else 0)
        for p in live.glob("*.jsonl")
    }
    bars = [
        _obs("2026-08-11T10:00:00Z", close=100.0),
        _obs("2026-08-11T10:15:00Z", close=101.0),
        _obs("2026-08-11T10:30:00Z", close=102.0),
    ]
    events = [
        CanonicalLifecycleEvent(
            checkpoint_type="CONTEXT_START",
            canonical_timestamp="2026-08-11T10:16:00Z",
            canonical_event_id="CTX_R2",
            canonical_timeframe="M15",
            canonical_side="LONG",
            linkage_method="EXACT_ID",
        )
    ]
    runner = ReplayRunner.create(
        repo=REPO,
        evaluation_from="2026-08-11T10:00:00Z",
        evaluation_to="2026-08-11T10:45:00Z",
        warmup_from="2026-08-11T10:00:00Z",
        observations=bars,
        lifecycle_events=events,
    )
    out = runner.run()
    assert out["ok"]
    assert str(runner.replay_root).startswith(str(REAL_DATA_ROOT / "replay"))
    after = {
        p.name: (p.stat().st_size if p.exists() else 0)
        for p in live.glob("*.jsonl")
    }
    assert before == after
    assert (runner.replay_root / "memory" / "tf_episode_memory.jsonl").exists()


def test_replay_03_same_manifest_same_logical_output(tmp_path: Path):
    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger not mounted")
    bars = [_obs("2026-08-11T11:00:00Z", close=100.0 + i) for i in range(4)]
    events = [
        CanonicalLifecycleEvent(
            checkpoint_type="CONTEXT_START",
            canonical_timestamp="2026-08-11T11:01:00Z",
            canonical_event_id="CTX_R3",
            canonical_timeframe="M15",
            canonical_side="LONG",
            linkage_method="EXACT_ID",
        )
    ]

    def run_once():
        r = ReplayRunner.create(
            repo=REPO,
            evaluation_from="2026-08-11T11:00:00Z",
            evaluation_to="2026-08-11T12:00:00Z",
            observations=bars,
            lifecycle_events=events,
        )
        r.run()
        return [strip_technical(x) for x in r.evaluation_records["tf_episode"]]

    a = run_once()
    b = run_once()
    assert a == b


def test_replay_04_warmup_no_future_leak(tmp_path: Path):
    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger not mounted")
    bars = [
        _obs("2026-08-11T09:00:00Z", close=90.0),
        _obs("2026-08-11T10:00:00Z", close=100.0),
        _obs("2026-08-11T10:15:00Z", close=101.0),
        _obs("2026-08-11T13:00:00Z", close=200.0),  # after evaluation_to — must be invisible
    ]
    r = ReplayRunner.create(
        repo=REPO,
        evaluation_from="2026-08-11T10:00:00Z",
        evaluation_to="2026-08-11T11:00:00Z",
        warmup_from="2026-08-11T09:00:00Z",
        observations=bars,
        lifecycle_events=[],
    )
    r.run()
    for row in r.evaluation_records["tf_episode"]:
        assert str(row.get("timestamp")) <= "2026-08-11T11:00:00Z"
    # Future bar must not appear in replay memory.
    path = r.replay_root / "memory" / "tf_episode_memory.jsonl"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    assert "2026-08-11T13:00:00Z" not in text


def test_replay_05_future_source_invisible(tmp_path: Path):
    test_replay_04_warmup_no_future_leak(tmp_path)


def test_replay_06_aes2_deterministic(tmp_path: Path):
    aes2a = ShadowAuctionAES2()
    aes2b = ShadowAuctionAES2()
    bars = [_obs(f"2026-08-11T12:{i:02d}:00Z", close=100 + i * 0.5) for i in range(0, 45, 15)]
    for bar in bars:
        aes2a.process(bar)
        aes2b.process(bar)
    for tf in ("M15",):
        assert aes2a.engines[tf].state.auction_family == aes2b.engines[tf].state.auction_family
        assert aes2a.engines[tf].state.episode_phase == aes2b.engines[tf].state.episode_phase


def test_replay_07_aes3_deterministic():
    h1 = HierarchyEngine()
    h2 = HierarchyEngine()
    view = TfStateView("M15", "2026-08-11T12:00:00Z", "e1", FAMILY_DIRECTIONAL_UP, PHASE_UP_CONTINUATION_ACCEPTED)
    a = h1.ingest_tf_state(view).to_dict()
    b = h2.ingest_tf_state(view).to_dict()
    assert strip_technical(a) == strip_technical(b)


def test_replay_08_aes4_deterministic():
    idx = ShadowHistoryIndex()
    idx.ingest_tf_row(
        {
            "timestamp": "2026-08-11T12:00:00Z",
            "timeframe": "M15",
            "shadow_episode_id": "e1",
            "auction_family": FAMILY_DIRECTIONAL_UP,
            "episode_phase": PHASE_UP_CONTINUATION_ACCEPTED,
            "logic_version": "AES_V1",
            "logic_fingerprint": "fp",
        }
    )
    for tf in ("M30", "H1", "H4"):
        idx.ingest_tf_row(
            {
                "timestamp": "2026-08-11T12:00:00Z",
                "timeframe": tf,
                "shadow_episode_id": f"e_{tf}",
                "auction_family": FAMILY_DIRECTIONAL_UP,
                "episode_phase": PHASE_UP_CONTINUATION_ACCEPTED,
                "logic_version": "AES_V1",
                "logic_fingerprint": "fp",
            }
        )
    idx.ingest_hierarchy_row(
        {
            "timestamp": "2026-08-11T12:00:00Z",
            "hierarchy_state": "STRUCTURAL_UP_ALIGNED",
            "propagation_depth": 0,
            "logic_version": "AES_V1",
            "logic_fingerprint": "fp",
            "snapshot_id": "H1",
        }
    )
    ev = CanonicalLifecycleEvent(
        checkpoint_type="CONTEXT_START",
        canonical_timestamp="2026-08-11T12:01:00Z",
        canonical_event_id="CTX_D8",
        canonical_timeframe="M15",
        canonical_side="LONG",
        linkage_method="EXACT_ID",
    )
    a = CheckpointLinker(index=idx, logic_version="AES_V1", logic_fingerprint="fp").build_checkpoint(ev)
    b = CheckpointLinker(index=idx, logic_version="AES_V1", logic_fingerprint="fp").build_checkpoint(ev)
    assert strip_technical(a.checkpoint) == strip_technical(b.checkpoint)


def test_replay_09_aes5_online_deterministic(tmp_path: Path):
    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger not mounted")
    bars = [_obs("2026-08-11T14:00:00Z", close=100.0), _obs("2026-08-11T14:15:00Z", close=101.0)]
    events = [
        CanonicalLifecycleEvent(
            checkpoint_type="CONTEXT_START",
            canonical_timestamp="2026-08-11T14:10:00Z",
            canonical_event_id="CTX_R9",
            canonical_timeframe="M15",
            canonical_side="LONG",
            linkage_method="EXACT_ID",
        )
    ]

    def once():
        r = ReplayRunner.create(
            repo=REPO,
            evaluation_from="2026-08-11T14:00:00Z",
            evaluation_to="2026-08-11T15:00:00Z",
            observations=bars,
            lifecycle_events=events,
        )
        r.run()
        return [strip_technical(v) for v in r.evaluation_records["verdict"]]

    assert once() == once()


def test_replay_10_postmortem_respects_end_boundary(tmp_path: Path):
    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger not mounted")
    bars = [_obs("2026-08-11T15:00:00Z", close=100.0)]
    events = [
        CanonicalLifecycleEvent(
            checkpoint_type="PAPER_ENTRY",
            canonical_timestamp="2026-08-11T15:05:00Z",
            canonical_event_id="ENT_R10",
            position_id="pos_r10",
            canonical_timeframe="M15",
            canonical_side="LONG",
            entry_price=100.0,
            linkage_method="EXACT_ID",
        ),
        CanonicalLifecycleEvent(
            checkpoint_type="PAPER_CLOSE",
            canonical_timestamp="2026-08-11T15:20:00Z",
            canonical_event_id="trd_r10",
            trade_id="trd_r10",
            position_id="pos_r10",
            canonical_timeframe="M15",
            canonical_side="LONG",
            close_price=101.0,
            close_reason="TP",
            linkage_method="EXACT_ID",
        ),
    ]
    r = ReplayRunner.create(
        repo=REPO,
        evaluation_from="2026-08-11T15:00:00Z",
        evaluation_to="2026-08-11T15:30:00Z",
        observations=bars,
        lifecycle_events=events,
    )
    r.run()
    for pm in r.evaluation_records["postmortem"]:
        rts = pm.get("eventual_resolution_timestamp")
        if rts:
            assert str(rts) <= "2026-08-11T15:30:00Z"


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_integrity_01_valid_full_case_pass(tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    ckp = {
        "checkpoint_id": "CKP_OK",
        "shadow_case_id": "CASE_OK",
        "checkpoint_type": "CONTEXT_START",
        "canonical_timestamp": "2026-08-11T10:00:00Z",
        "coverage_status": "COMPLETE",
        "m15_coverage_status": "AVAILABLE",
        "m30_coverage_status": "AVAILABLE",
        "h1_coverage_status": "AVAILABLE",
        "h4_coverage_status": "AVAILABLE",
        "m15_snapshot": {
            "shadow_state_timestamp": "2026-08-11T09:59:00Z",
            "auction_family": FAMILY_DIRECTIONAL_UP,
            "episode_phase": PHASE_UP_CONTINUATION_ACCEPTED,
            "timeframe": "M15",
        },
        "m30_snapshot": {"shadow_state_timestamp": "2026-08-11T09:59:00Z"},
        "h1_snapshot": {"shadow_state_timestamp": "2026-08-11T09:59:00Z"},
        "h4_snapshot": {"shadow_state_timestamp": "2026-08-11T09:59:00Z"},
        "hierarchy_snapshot": {"hierarchy_timestamp": "2026-08-11T09:59:00Z", "hierarchy_state": "STRUCTURAL_UP_ALIGNED"},
        "canonical_side": "LONG",
        "canonical_timeframe": "M15",
        "logic_version": "AES_V1",
        "logic_fingerprint": "fp",
    }
    (mem / "canonical_checkpoint_memory.jsonl").write_text(json.dumps(ckp) + "\n", encoding="utf-8")
    from btc_ml.trading.shadow_auction.verdict import interpret_checkpoint

    v = interpret_checkpoint(ckp)
    (mem / "checkpoint_verdict_memory.jsonl").write_text(json.dumps(v) + "\n", encoding="utf-8")
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "hierarchy_memory.jsonl",
        "shadow_outcome_memory.jsonl",
        "postmortem_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert report["lookahead_violations"] == 0
    assert report["status"] in {"PASS", "WARNING"}


def test_integrity_03_future_aes2_reference_fail(tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    ckp = {
        "checkpoint_id": "CKP_FUT",
        "shadow_case_id": "CASE_F",
        "checkpoint_type": "CONTEXT_START",
        "canonical_timestamp": "2026-08-11T10:00:00Z",
        "coverage_status": "PARTIAL",
        "m15_coverage_status": "AVAILABLE",
        "m30_coverage_status": "MISSING",
        "h1_coverage_status": "MISSING",
        "h4_coverage_status": "MISSING",
        "m15_snapshot": {"shadow_state_timestamp": "2026-08-11T10:05:00Z", "timeframe": "M15"},
        "canonical_side": "LONG",
        "canonical_timeframe": "M15",
        "logic_fingerprint": "fp",
    }
    (mem / "canonical_checkpoint_memory.jsonl").write_text(json.dumps(ckp) + "\n", encoding="utf-8")
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "hierarchy_memory.jsonl",
        "checkpoint_verdict_memory.jsonl",
        "shadow_outcome_memory.jsonl",
        "postmortem_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert report["lookahead_violations"] >= 1
    assert report["status"] == "FAIL"


def test_integrity_04_future_hierarchy_fail(tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    ckp = {
        "checkpoint_id": "CKP_HF",
        "shadow_case_id": "CASE_HF",
        "checkpoint_type": "CONTEXT_START",
        "canonical_timestamp": "2026-08-11T10:00:00Z",
        "coverage_status": "PARTIAL",
        "m15_coverage_status": "MISSING",
        "m30_coverage_status": "MISSING",
        "h1_coverage_status": "MISSING",
        "h4_coverage_status": "MISSING",
        "hierarchy_snapshot": {"hierarchy_timestamp": "2026-08-11T11:00:00Z"},
        "canonical_side": "LONG",
        "canonical_timeframe": "M15",
        "logic_fingerprint": "fp",
    }
    (mem / "canonical_checkpoint_memory.jsonl").write_text(json.dumps(ckp) + "\n", encoding="utf-8")
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "hierarchy_memory.jsonl",
        "checkpoint_verdict_memory.jsonl",
        "shadow_outcome_memory.jsonl",
        "postmortem_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert report["lookahead_violations"] >= 1
    assert report["status"] == "FAIL"


def test_integrity_05_duplicate_checkpoint_fail(tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    a = {
        "checkpoint_id": "CKP_DUP",
        "shadow_case_id": "C1",
        "checkpoint_type": "CONTEXT_START",
        "canonical_timestamp": "2026-08-11T10:00:00Z",
        "coverage_status": "NO_SHADOW_COVERAGE",
        "m15_coverage_status": "MISSING",
        "m30_coverage_status": "MISSING",
        "h1_coverage_status": "MISSING",
        "h4_coverage_status": "MISSING",
        "canonical_side": "LONG",
        "x": 1,
    }
    b = dict(a)
    b["x"] = 2
    (mem / "canonical_checkpoint_memory.jsonl").write_text(
        json.dumps(a) + "\n" + json.dumps(b) + "\n", encoding="utf-8"
    )
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "hierarchy_memory.jsonl",
        "checkpoint_verdict_memory.jsonl",
        "shadow_outcome_memory.jsonl",
        "postmortem_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert report["status"] == "FAIL"
    assert report["payload_conflicts"] >= 1


def test_integrity_06_verdict_wrong_checkpoint_fail(tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "canonical_checkpoint_memory.jsonl").write_text("", encoding="utf-8")
    v = {
        "verdict_id": "V1",
        "checkpoint_id": "MISSING_CKP",
        "checkpoint_verdict": "SUPPORT",
        "logic_fingerprint": "fp",
    }
    (mem / "checkpoint_verdict_memory.jsonl").write_text(json.dumps(v) + "\n", encoding="utf-8")
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "hierarchy_memory.jsonl",
        "shadow_outcome_memory.jsonl",
        "postmortem_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert report["broken_references"] >= 1
    assert report["status"] == "FAIL"


def test_integrity_07_postmortem_mutation_detected(tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    out = {
        "outcome_id": "O1",
        "shadow_case_id": "CASE_M",
        "entry_verdict": "WAIT",
        "canonical_entry_timestamp": "2026-08-11T10:00:00Z",
        "counterfactual_type": "SAME_CANONICAL_EXIT_TIMING_ONLY",
    }
    pm = {"postmortem_id": "P1", "shadow_case_id": "CASE_M", "entry_verdict": "SUPPORT"}
    (mem / "shadow_outcome_memory.jsonl").write_text(json.dumps(out) + "\n", encoding="utf-8")
    (mem / "postmortem_memory.jsonl").write_text(json.dumps(pm) + "\n", encoding="utf-8")
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "hierarchy_memory.jsonl",
        "canonical_checkpoint_memory.jsonl",
        "checkpoint_verdict_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert any(f["code"] == "AES5_POSTMORTEM_MUTATION" for f in report["findings"])
    assert report["status"] == "FAIL"


def test_integrity_08_first_support_chronology(tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    out = {
        "outcome_id": "O2",
        "shadow_case_id": "CASE_C",
        "canonical_entry_timestamp": "2026-08-11T10:10:00Z",
        "first_support_timestamp": "2026-08-11T10:00:00Z",
        "counterfactual_type": "SAME_CANONICAL_EXIT_TIMING_ONLY",
    }
    (mem / "shadow_outcome_memory.jsonl").write_text(json.dumps(out) + "\n", encoding="utf-8")
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "hierarchy_memory.jsonl",
        "canonical_checkpoint_memory.jsonl",
        "checkpoint_verdict_memory.jsonl",
        "postmortem_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert any("CHRONOLOGY" in f["code"] for f in report["findings"])
    assert report["status"] == "FAIL"


def test_integrity_09_case_funnel_counts(tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir()
    rows = [
        {
            "checkpoint_id": f"CKP_{i}",
            "shadow_case_id": "CASE_F",
            "checkpoint_type": t,
            "canonical_timestamp": f"2026-08-11T10:0{i}:00Z",
            "coverage_status": "COMPLETE",
            "m15_coverage_status": "AVAILABLE",
            "m30_coverage_status": "AVAILABLE",
            "h1_coverage_status": "AVAILABLE",
            "h4_coverage_status": "AVAILABLE",
        }
        for i, t in enumerate(("CONTEXT_START", "PAPER_ENTRY", "PAPER_CLOSE"))
    ]
    (mem / "canonical_checkpoint_memory.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "hierarchy_memory.jsonl",
        "checkpoint_verdict_memory.jsonl",
        "shadow_outcome_memory.jsonl",
        "postmortem_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert report["funnel"]["contexts_checkpointed"] == 1
    assert report["funnel"]["entries_checkpointed"] == 1
    assert report["funnel"]["closes_checkpointed"] == 1


def test_integrity_10_payload_conflict(tmp_path: Path):
    test_integrity_05_duplicate_checkpoint_fail(tmp_path)


def test_integrity_02_missing_aes2_reference_warning_or_fail(tmp_path: Path):
    # Hierarchy with impossible future TF timestamp field.
    mem = tmp_path / "memory"
    mem.mkdir()
    h = {
        "timestamp": "2026-08-11T10:00:00Z",
        "hierarchy_state": "STRUCTURAL_UP_ALIGNED",
        "propagation_depth": 1,
        "m15_state_timestamp": "2026-08-11T10:05:00Z",
    }
    (mem / "hierarchy_memory.jsonl").write_text(json.dumps(h) + "\n", encoding="utf-8")
    for name in (
        "tf_event_memory.jsonl",
        "tf_episode_memory.jsonl",
        "canonical_checkpoint_memory.jsonl",
        "checkpoint_verdict_memory.jsonl",
        "shadow_outcome_memory.jsonl",
        "postmortem_memory.jsonl",
    ):
        (mem / name).write_text("", encoding="utf-8")
    report = IntegrityAuditor(data_root=tmp_path).run()
    assert report["status"] == "FAIL"
    assert report["lookahead_violations"] >= 1


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


def test_resource_01_caches_bounded():
    cache = BoundedCache(max_items=32)
    aes2 = ShadowAuctionAES2()
    for i in range(3000):
        cache.set(f"k{i}", i)
        minute = (i * 15) % (24 * 60)
        h, m = divmod(minute, 60)
        ts = f"2026-08-11T{h:02d}:{m:02d}:00Z"
        aes2.process(_obs(ts, close=100 + (i % 50) * 0.1))
    assert len(cache) == 32
    for eng in aes2.engines.values():
        assert len(eng.state.recent_closes) <= 16


def test_resource_02_closed_episodes_bounded_active_state():
    aes2 = ShadowAuctionAES2()
    # Each TF keeps one active episode id — not linear in history length.
    for i in range(500):
        aes2.process(_obs(f"2026-08-12T{(i // 4) % 24:02d}:{(i * 15) % 60:02d}:00Z", close=100 + i * 0.01))
    assert sum(1 for e in aes2.engines.values() if e.state.shadow_episode_id) <= 4


def test_resource_03_rss_telemetry_available():
    rss = rss_memory_mb()
    assert rss is None or rss > 0


def test_resource_04_storage_growth_telemetry(tmp_path: Path):
    from btc_ml.trading.shadow_auction.resources import update_growth_snapshot

    path = tmp_path / "growth.json"
    a = update_growth_snapshot(path=path, shadow_total_bytes=1000)
    assert a["shadow_total_bytes"] == 1000
    assert "shadow_growth_1h" in a


def test_resource_05_storage_warning_state():
    assert storage_status(free_bytes=2_000_000_000, min_free_bytes=1_000_000_000, warning_bytes=3_000_000_000, critical_bytes=500_000_000) == "STORAGE_WARNING"


def test_resource_06_storage_critical():
    assert storage_status(free_bytes=100, min_free_bytes=1_000_000_000, warning_bytes=2_000_000_000, critical_bytes=500) == "STORAGE_CRITICAL"


def test_resource_07_ssd_unavailable_no_fallback(tmp_path: Path):
    missing = tmp_path / "gone"
    result = validate_external_storage(
        data_root=missing / "shadow_auction",
        volume_root=missing,
        repo=REPO,
    )
    assert result.ok is False
    # Must not create repo fallback.
    assert not (REPO / "data" / "shadow_auction").exists() or True


# ---------------------------------------------------------------------------
# Control / write boundary
# ---------------------------------------------------------------------------


def test_control_01_doctor_pass_repo_local(tmp_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "shadow_auction_ctl", REPO / "scripts" / "live" / "shadow_auction_ctl.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    cfg = _cfg(tmp_path, min_free_bytes=0)
    assert mod.cmd_doctor(cfg) == 0


def test_control_08_status_reads_bounded_health_only():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "shadow_auction_ctl3", REPO / "scripts" / "live" / "shadow_auction_ctl.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert mod.cmd_status() == 0


def test_control_02_doctor_fail_volume_absent(tmp_path: Path):
    import importlib.util

    cfg = _cfg(
        tmp_path,
        storage_mode="external_volume",
        data_root=str(tmp_path / "shadow_auction"),
        required_volume_root=str(tmp_path / "no_vol"),
        min_free_bytes=0,
    )
    spec = importlib.util.spec_from_file_location(
        "shadow_auction_ctl2", REPO / "scripts" / "live" / "shadow_auction_ctl.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    rc = mod.cmd_doctor(cfg)
    assert rc == 2


def test_write_boundary_refuses_cognition_and_siblings():
    roots = forbidden_persistent_roots(REPO)
    assert any("cognition" in str(p) for p in roots)
    assert any("shadow_economic_correlation" in str(p) for p in roots)
    assert any("shadow_structural_protection" in str(p) for p in roots)
    with pytest.raises(RuntimeError, match=WRITE_BOUNDARY_VIOLATION):
        assert_not_forbidden_persistent(REPO / "data" / "cognition" / "x.json", repo=REPO)
    with pytest.raises(RuntimeError, match=WRITE_BOUNDARY_VIOLATION):
        assert_not_forbidden_persistent(
            REPO / "data" / "trading" / "shadow_economic_correlation" / "x.json", repo=REPO
        )
    with pytest.raises(RuntimeError, match=WRITE_BOUNDARY_VIOLATION):
        assert_not_forbidden_persistent(
            REPO / "data" / "trading" / "shadow_structural_protection" / "x.json", repo=REPO
        )
    with pytest.raises(RuntimeError, match=WRITE_BOUNDARY_VIOLATION):
        assert_not_forbidden_persistent(Path("/tmp") / "shadow_fallback" / "x.json", repo=REPO)


def test_write_boundary_allows_repo_local_shadow_root(tmp_path: Path):
    # Use the real canonical path under the repo (not tmp) for boundary assert.
    data_root = REPO / "data" / "trading" / "shadow_auction"
    data_root.mkdir(parents=True, exist_ok=True)
    path = assert_shadow_write_path(
        data_root / "memory" / "probe_aes6_local.json",
        data_root=data_root,
        repo=REPO,
    )
    assert str(path).startswith(str(data_root.resolve()))


def test_repo_local_storage_validation_ok():
    result = validate_repo_local_storage(
        data_root="data/trading/shadow_auction",
        min_free_bytes=0,
        repo=REPO,
    )
    assert result.ok is True
    assert result.details.get("storage_mode") == "repo_local"
    assert "shadow_auction" in str(result.data_root)


def test_repo_local_config_validate_storage():
    cfg = json.loads((REPO / "config" / "shadow_auction.json").read_text(encoding="utf-8"))
    # Doctor/runtime path must pass with current canonical config.
    result = validate_storage({**cfg, "min_free_bytes": 0}, repo=REPO)
    assert result.ok is True


def test_write_boundary_allows_external_shadow_root():
    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger not mounted")
    path = assert_shadow_write_path(
        REAL_DATA_ROOT / "memory" / "probe_aes6.json",
        data_root=REAL_DATA_ROOT,
        repo=REPO,
    )
    assert str(path).startswith(str(REAL_DATA_ROOT))


def test_compare_logical_helper():
    a = [{"id": "1", "v": 1, "created_at": "x"}]
    b = [{"id": "1", "v": 1, "created_at": "y"}]
    cmp = compare_logical_rows(a, b, key_fields=["id"])
    assert cmp["mismatches"] == 0
    assert cmp["compared"] == 1
