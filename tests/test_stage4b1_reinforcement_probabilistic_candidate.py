"""Stage 4B1 — reinforcement/probabilistic consume canonical runtime cognition."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
UNPATCHED_REINF = (
    REPO
    / "data/candidate/architecture_recovery/stage4b1_reinforcement_probabilistic_candidate"
    / "unpatched_auction_reinforcement_engine_v1.py"
)


def _write_cog(root: Path, rows: list[dict]) -> Path:
    path = root / "cognition" / "runtime_cognition_memory.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if "lineage_event_timestamp" in frame.columns:
        frame["lineage_event_timestamp"] = pd.to_datetime(
            frame["lineage_event_timestamp"], utc=True
        )
    if "auction_event_timestamp" in frame.columns:
        frame["auction_event_timestamp"] = pd.to_datetime(
            frame["auction_event_timestamp"], utc=True
        )
    frame.to_parquet(path)
    return path


def _seed_state_frames(root: Path) -> None:
    (root / "reinforcement").mkdir(parents=True, exist_ok=True)
    (root / "probabilistic").mkdir(parents=True, exist_ok=True)
    (root / "cognition").mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-26 20:00:00", tz="UTC"),
                "auction_state": "STRUCTURAL_COMPRESSION",
                "interpretation": "STRUCTURAL_COMPRESSION",
            }
        ]
    ).to_parquet(root / "reinforcement" / "auction_synthesis_memory.parquet")

    pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-26 20:00:00", tz="UTC"),
                "effort_result_state": "NEUTRAL",
                "localized_behavior": "neutral",
                "unfinished_auction": False,
            }
        ]
    ).to_parquet(root / "cognition" / "volume_response_state.parquet")

    pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-26 19:45:00", tz="UTC"),
                "auction_state": "NEUTRAL",
                "belief_state": "NEUTRAL_CONVICTION",
                "belief_strength": 0.4,
                "localized_behavior": "neutral",
                "effort_result_state": "NEUTRAL",
                "alignment_status": "MISSING",
                "alignment_component": 0.0,
                "persistence_component": 0.0,
                "location_component": 0.0,
                "unfinished_auction_component": 0.0,
                "entropy_penalty": 0.0,
                "conflict_penalty": 0.0,
                "reinforcement_component": 0.5,
            }
        ]
    ).to_parquet(root / "reinforcement" / "auction_reinforcement_memory.parquet")

    # Rich enough history for calibration_stability walk-forward helpers.
    prob_rows = []
    for i in range(40):
        prob_rows.append(
            {
                "timestamp": pd.Timestamp("2026-07-26 10:00:00", tz="UTC")
                + pd.Timedelta(minutes=15 * i),
                "auction_regime": "UNCERTAIN",
                "absorption_probability": 0.0,
                "distribution_probability": 0.0,
                "conviction_probability": 0.0,
                "alignment_status": "MISSING",
                "alignment_component": 1.0,
                "persistence_component": 0.0,
                "location_component": 1.0,
                "unfinished_auction_component": 0.0,
                "entropy_penalty": 0.0,
                "conflict_penalty": 0.0,
                "conflict_density": 0.0,
                "reinforcement_component": 0.0,
            }
        )
    pd.DataFrame(prob_rows).to_parquet(
        root / "probabilistic" / "probabilistic_auction_memory.parquet"
    )

    # Satisfy state_manager optional loads under DATA_ROOT.
    for rel in (
        "reinforcement/auction_convergence_memory.parquet",
        "cognition/behavioral_sequence_memory.parquet",
        "cognition/adaptive_meta_cognition_state.parquet",
        "cognition/candle_structure_memory.parquet",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {"timestamp": [pd.Timestamp("2026-07-26 19:00:00", tz="UTC")]}
        ).to_parquet(path)


def _activate(root: Path, monkeypatch: pytest.MonkeyPatch, *, stub_prob_diagnostics: bool = False):
    monkeypatch.setenv("BTC_ML_DATA_ROOT", str(root))
    import storage.path_registry as pr
    import state_manager_v1 as sm
    import auction_reinforcement_engine_v1 as reinf
    import probabilistic_auction_engine_v1 as prob
    import runtime_dependency_map as depmap
    import runtime_dependency_guard as guard

    importlib.reload(pr)
    importlib.reload(sm)
    importlib.reload(reinf)
    importlib.reload(prob)
    importlib.reload(depmap)
    importlib.reload(guard)
    if stub_prob_diagnostics:
        # Isolate bridge I/O from climax/ontology side-loads that need live OHLCV.
        monkeypatch.setattr(
            prob,
            "build_ontology_stabilization_exports",
            lambda *args, **kwargs: {
                "ontology_stabilization_active": False,
                "ontology_stability_score": 0.0,
                "semantic_fragility_score": 0.0,
            },
        )
        monkeypatch.setattr(
            prob,
            "build_adversarial_exports",
            lambda *args, **kwargs: {"adversarial_diagnostics_active": False},
        )
        monkeypatch.setattr(
            prob,
            "compute_runtime_stability_exports",
            lambda *args, **kwargs: {},
        )
        monkeypatch.setattr(
            prob,
            "infer_regime_segmentation",
            lambda *args, **kwargs: {
                "regime_state": "UNKNOWN",
                "regime_confidence": 0.0,
            },
        )
        monkeypatch.setattr(prob, "compute_calibration_drift", lambda *args, **kwargs: {})
        monkeypatch.setattr(prob, "log_drift_warning", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            prob,
            "build_diagnostic_exports",
            lambda *args, **kwargs: {
                col: 0.0 for col in getattr(prob, "DIAGNOSTIC_EXPORT_COLUMNS", [])
            },
        )
        monkeypatch.setattr(
            prob,
            "apply_probabilistic_discipline",
            lambda **kwargs: {
                "calibrated_conviction": kwargs.get("raw_conviction", 0.0),
                "disciplined_conviction": kwargs.get("raw_conviction", 0.0),
            },
        )
        monkeypatch.setattr(
            prob,
            "resolve_runtime_conviction",
            lambda raw, *_args, **_kwargs: raw,
        )
        monkeypatch.setattr(prob, "get_calibration_settings", lambda: type("S", (), {"use_disciplined_conviction_at_runtime": False})())
    sm.refresh_state()
    return reinf, prob, sm, depmap, guard, pr


def _cog_row(ts: str, **overrides) -> dict:
    base = {
        "timestamp": ts,
        "synthesis_state": "INTERMEDIATE_REVERSAL",
        "trigger_event": "STOPPING_VOLUME",
        "persistence": "M30_CONFIRMED",
        "persistence_score": 0.5,
        "structural_rank": "MEDIUM",
        "alignment_score": 0.5,
        "location_bias": "LOWER_ABSORPTION",
        "auction_state": "STRUCTURAL_COMPRESSION",
        "auction_event_timestamp": "2026-07-26 20:05:00",
        "lineage_event_timestamp": "2026-07-25 08:45:00",
    }
    base.update(overrides)
    return base


def test_empty_state_reads_canonical_parquet(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    _write_cog(root, [_cog_row("2026-07-26 21:15:00")])
    reinf, _prob, sm, _dep, _guard, pr = _activate(root, monkeypatch)
    sm.STATE["runtime_cognition"] = {}
    reinf.run()
    out = pd.read_parquet(root / "reinforcement" / "auction_reinforcement_memory.parquet")
    latest = out.iloc[-1]
    assert pd.to_datetime(latest["timestamp"], utc=True) == pd.Timestamp(
        "2026-07-26 21:15:00", tz="UTC"
    )
    assert float(latest["persistence_component"]) == pytest.approx(0.1)
    assert float(latest["location_component"]) == pytest.approx(0.2)
    assert str(pr.resolve_canonical("runtime_cognition_memory.parquet")).endswith(
        "cognition/runtime_cognition_memory.parquet"
    )


def test_conflicting_state_does_not_override_parquet(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    _write_cog(root, [_cog_row("2026-07-26 21:15:00", persistence_score=0.5)])
    reinf, _prob, sm, *_ = _activate(root, monkeypatch)
    sm.STATE["runtime_cognition"] = {
        "persistence_score": 0.0,
        "structural_rank": "LOW",
        "synthesis_state": "NONE",
        "location_bias": "NEUTRAL",
        "alignment_status": "VALID",
        "alignment_score": 1.0,
    }
    reinf.run()
    latest = pd.read_parquet(
        root / "reinforcement" / "auction_reinforcement_memory.parquet"
    ).iloc[-1]
    assert float(latest["persistence_component"]) == pytest.approx(0.1)
    assert float(latest["location_component"]) == pytest.approx(0.2)
    assert pd.to_datetime(latest["timestamp"], utc=True) == pd.Timestamp(
        "2026-07-26 21:15:00", tz="UTC"
    )


def test_missing_cognition_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    reinf, prob, sm, *_ = _activate(root, monkeypatch)
    before_r = pd.read_parquet(
        root / "reinforcement" / "auction_reinforcement_memory.parquet"
    ).copy()
    before_p = pd.read_parquet(
        root / "probabilistic" / "probabilistic_auction_memory.parquet"
    ).copy()
    reinf.run()
    prob.run()
    after_r = pd.read_parquet(
        root / "reinforcement" / "auction_reinforcement_memory.parquet"
    )
    after_p = pd.read_parquet(
        root / "probabilistic" / "probabilistic_auction_memory.parquet"
    )
    assert len(after_r) == len(before_r)
    assert len(after_p) == len(before_p)
    pd.testing.assert_frame_equal(after_r, before_r)
    pd.testing.assert_frame_equal(after_p, before_p)


def test_missing_required_field_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    row = _cog_row("2026-07-26 21:15:00")
    del row["location_bias"]
    _write_cog(root, [row])
    reinf, _prob, sm, *_ = _activate(root, monkeypatch)
    before = len(
        pd.read_parquet(root / "reinforcement" / "auction_reinforcement_memory.parquet")
    )
    reinf.run()
    after = len(
        pd.read_parquet(root / "reinforcement" / "auction_reinforcement_memory.parquet")
    )
    assert after == before


def test_timestamp_and_lineage_propagation(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    _write_cog(root, [_cog_row("2026-07-26 21:15:00")])
    reinf, prob, sm, *_ = _activate(root, monkeypatch, stub_prob_diagnostics=True)
    reinf.run()
    prob.run()
    reinf_row = pd.read_parquet(
        root / "reinforcement" / "auction_reinforcement_memory.parquet"
    ).iloc[-1]
    prob_row = pd.read_parquet(
        root / "probabilistic" / "probabilistic_auction_memory.parquet"
    ).iloc[-1]
    eval_ts = pd.Timestamp("2026-07-26 21:15:00", tz="UTC")
    assert pd.to_datetime(reinf_row["timestamp"], utc=True) == eval_ts
    assert pd.to_datetime(prob_row["timestamp"], utc=True) == eval_ts
    assert pd.to_datetime(reinf_row["lineage_event_timestamp"], utc=True) == pd.Timestamp(
        "2026-07-25 08:45:00", tz="UTC"
    )
    assert pd.to_datetime(reinf_row["auction_event_timestamp"], utc=True) == pd.Timestamp(
        "2026-07-26 20:05:00", tz="UTC"
    )


def test_dependency_map_and_guard(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    _write_cog(
        root,
        [
            _cog_row("2026-07-26 21:00:00"),
            _cog_row("2026-07-26 21:15:00"),
        ],
    )
    _reinf, _prob, _sm, depmap, guard, _pr = _activate(root, monkeypatch)
    assert "runtime_cognition_memory.parquet" in depmap.DEPENDENCIES[
        "auction_reinforcement_engine_v1.py"
    ]
    assert "runtime_cognition_memory.parquet" in depmap.DEPENDENCIES[
        "probabilistic_auction_engine_v1.py"
    ]
    assert "auction_synthesis_memory.parquet" not in depmap.DEPENDENCIES[
        "probabilistic_auction_engine_v1.py"
    ]

    assert guard.should_run_engine(
        "auction_reinforcement_engine_v1.py",
        depmap.DEPENDENCIES["auction_reinforcement_engine_v1.py"],
    )
    assert not guard.should_run_engine(
        "auction_reinforcement_engine_v1.py",
        depmap.DEPENDENCIES["auction_reinforcement_engine_v1.py"],
    )

    # New cognition tip makes reinforcement eligible again.
    cog = pd.read_parquet(root / "cognition" / "runtime_cognition_memory.parquet")
    extra = cog.iloc[[-1]].copy()
    extra["timestamp"] = pd.Timestamp("2026-07-26 21:30:00", tz="UTC")
    pd.concat([cog, extra], ignore_index=True).to_parquet(
        root / "cognition" / "runtime_cognition_memory.parquet"
    )
    os.utime(root / "cognition" / "runtime_cognition_memory.parquet", None)
    assert guard.should_run_engine(
        "auction_reinforcement_engine_v1.py",
        depmap.DEPENDENCIES["auction_reinforcement_engine_v1.py"],
    )


def test_duplicate_evaluation_rejected(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    _write_cog(root, [_cog_row("2026-07-26 21:15:00")])
    reinf, _prob, sm, *_ = _activate(root, monkeypatch)
    reinf.run()
    n1 = len(
        pd.read_parquet(root / "reinforcement" / "auction_reinforcement_memory.parquet")
    )
    reinf.run()
    n2 = len(
        pd.read_parquet(root / "reinforcement" / "auction_reinforcement_memory.parquet")
    )
    assert n2 == n1


@pytest.mark.skipif(not UNPATCHED_REINF.exists(), reason="unpatched fixture missing")
def test_formula_invariance_same_cognition_dict(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    _write_cog(root, [_cog_row("2026-07-26 21:15:00")])
    reinf, _prob, sm, *_ = _activate(root, monkeypatch)
    cog = reinf._load_latest_runtime_cognition()
    assert cog is not None
    reinf.run()
    patched = pd.read_parquet(
        root / "reinforcement" / "auction_reinforcement_memory.parquet"
    ).iloc[-1]

    root_old = tmp_path / "data_old"
    _seed_state_frames(root_old)
    _write_cog(root_old, [_cog_row("2026-07-26 21:15:00")])
    monkeypatch.setenv("BTC_ML_DATA_ROOT", str(root_old))
    import storage.path_registry as pr
    import state_manager_v1 as sm2

    importlib.reload(pr)
    importlib.reload(sm2)
    sm2.refresh_state()
    sm2.STATE["runtime_cognition"] = {
        "persistence_score": cog["persistence_score"],
        "structural_rank": cog["structural_rank"],
        "synthesis_state": cog["synthesis_state"],
        "location_bias": cog["location_bias"],
        "alignment_status": cog["alignment_status"],
        "alignment_score": cog["alignment_score"],
    }
    spec = importlib.util.spec_from_file_location("unpatched_reinf", UNPATCHED_REINF)
    unpatched = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(unpatched)
    unpatched.run()
    old = pd.read_parquet(
        root_old / "reinforcement" / "auction_reinforcement_memory.parquet"
    ).iloc[-1]

    for col in (
        "belief_strength",
        "belief_state",
        "persistence_component",
        "location_component",
        "alignment_component",
        "reinforcement_component",
        "alignment_status",
    ):
        if isinstance(patched[col], float) or isinstance(old[col], float):
            assert float(patched[col]) == pytest.approx(float(old[col]), abs=0.0)
        else:
            assert str(patched[col]) == str(old[col])


def test_consumer_schema_accepted(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _seed_state_frames(root)
    _write_cog(root, [_cog_row("2026-07-26 21:15:00")])
    reinf, prob, sm, *_ = _activate(root, monkeypatch, stub_prob_diagnostics=True)
    reinf.run()
    prob.run()
    frame = pd.read_parquet(root / "probabilistic" / "probabilistic_auction_memory.parquet")
    for col in (
        "timestamp",
        "auction_regime",
        "absorption_probability",
        "distribution_probability",
        "conviction_probability",
        "alignment_status",
    ):
        assert col in frame.columns
    assert "datetime64" in str(frame["timestamp"].dtype)
