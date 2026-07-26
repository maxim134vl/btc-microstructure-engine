"""Relative-order hardening invariants for Stage 1B volume localization."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from runtime_hardening import (  # noqa: E402
    ACTIVATED_PIPELINE_STEP_COUNT,
    BASE_CANONICAL_PIPELINE_ORDER,
    BASE_PIPELINE_STEP_COUNT,
    VOLUME_LOCALIZATION_ENGINE,
    validate_canonical_pipeline_order,
)
from btc_ml.runtime import pipeline as pipeline_mod  # noqa: E402


def _base() -> list[str]:
    return list(BASE_CANONICAL_PIPELINE_ORDER)


def _activated() -> list[str]:
    return pipeline_mod.canonical_pipeline_with_volume_localization_candidate(_base())


def test_base_constants_match_live_pre_activation_shape():
    assert BASE_PIPELINE_STEP_COUNT == 20
    assert ACTIVATED_PIPELINE_STEP_COUNT == 21
    assert len(pipeline_mod.CANONICAL_PIPELINE) in (20, 21)


def test_20_step_pipeline_passes():
    failures = validate_canonical_pipeline_order(_base(), BASE_PIPELINE_STEP_COUNT)
    assert failures == []


def test_21_step_candidate_pipeline_passes():
    cand = _activated()
    assert len(cand) == 21
    failures = validate_canonical_pipeline_order(cand, ACTIVATED_PIPELINE_STEP_COUNT)
    assert failures == []


def test_localization_after_candle_before_response():
    cand = _activated()
    assert cand.index("candle_structure_engine_v1.py") < cand.index(
        VOLUME_LOCALIZATION_ENGINE
    )
    assert cand.index(VOLUME_LOCALIZATION_ENGINE) < cand.index(
        "volume_response_engine_v1.py"
    )


def test_existing_cognition_relative_order_preserved():
    cand = _activated()
    base_obs = [e for e in cand if e != VOLUME_LOCALIZATION_ENGINE]
    assert base_obs == list(BASE_CANONICAL_PIPELINE_ORDER)
    assert cand.index("stage2_cognition_runtime_v1.py") < cand.index(
        "runtime_cognition_engine_v1.py"
    )
    assert cand.index("runtime_cognition_engine_v1.py") < cand.index(
        "intermediate_cognition_engine_v1.py"
    )


def test_negative_duplicate_localization_fails():
    bad = _activated() + [VOLUME_LOCALIZATION_ENGINE]
    failures = validate_canonical_pipeline_order(bad, len(bad))
    # unexpected count OR duplicate — either surfaces the defect
    assert any("duplicat" in f or "step count" in f for f in failures)

    # Same length 21 with duplicate (drop last base engine):
    bad21 = _activated()
    bad21[-1] = VOLUME_LOCALIZATION_ENGINE
    failures = validate_canonical_pipeline_order(bad21, ACTIVATED_PIPELINE_STEP_COUNT)
    assert any("more than once" in f or "duplicated" in f or "missing" in f for f in failures)


def test_negative_missing_localization_in_active_mode_fails():
    failures = validate_canonical_pipeline_order(
        _base(), ACTIVATED_PIPELINE_STEP_COUNT
    )
    assert any("missing in activated pipeline" in f for f in failures)


def test_negative_localization_before_candle_fails():
    bad = [VOLUME_LOCALIZATION_ENGINE] + _base()
    # trim to 21 by dropping last
    bad = bad[:21]
    failures = validate_canonical_pipeline_order(bad, ACTIVATED_PIPELINE_STEP_COUNT)
    assert any("order invalid" in f or "relative order" in f for f in failures)


def test_negative_localization_after_volume_response_fails():
    base = _base()
    resp = base.index("volume_response_engine_v1.py")
    bad = base[: resp + 1] + [VOLUME_LOCALIZATION_ENGINE] + base[resp + 1 :]
    assert len(bad) == 21
    failures = validate_canonical_pipeline_order(bad, ACTIVATED_PIPELINE_STEP_COUNT)
    assert any("order invalid" in f for f in failures)


def test_negative_missing_required_cognition_engine_fails():
    bad = [e for e in _base() if e != "intermediate_cognition_engine_v1.py"]
    # Keep expected mode = 20 so presence checks run despite length mismatch.
    failures = validate_canonical_pipeline_order(bad, BASE_PIPELINE_STEP_COUNT)
    assert any("required engine missing: intermediate_cognition" in f for f in failures)


def test_negative_wrong_cognition_relative_order_fails():
    bad = _base()
    i_stage = bad.index("stage2_cognition_runtime_v1.py")
    i_inter = bad.index("intermediate_cognition_engine_v1.py")
    bad[i_stage], bad[i_inter] = bad[i_inter], bad[i_stage]
    failures = validate_canonical_pipeline_order(bad, BASE_PIPELINE_STEP_COUNT)
    assert any("cognition relative order" in f or "base cognition" in f for f in failures)


def test_negative_unexpected_step_count_fails():
    failures = validate_canonical_pipeline_order(_base(), 19)
    assert any("step count" in f for f in failures)


def test_live_check_package_imports_uses_relative_validator():
    from runtime_hardening import HardeningReport, check_package_imports

    report = HardeningReport()
    check_package_imports(report)
    assert report.ok, report.failures
    assert "canonical package imports" in report.passed
    # Absolute index coupling removed from source.
    src = (REPO / "runtime_hardening.py").read_text()
    assert 'CANONICAL_PIPELINE[12]' not in src
