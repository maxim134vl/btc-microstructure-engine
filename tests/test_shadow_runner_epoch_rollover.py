"""Runner-level PAPER epoch rollover regression tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str, relative_path: str) -> ModuleType:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_active(repo: Path, epoch_id: str) -> None:
    path = repo / "data/trading/paper_epochs/active.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"paper_epoch_id": epoch_id}) + "\n",
        encoding="utf-8",
    )


def test_eqcorr_runner_rolls_engine_to_active_epoch(tmp_path, monkeypatch) -> None:
    module = _load_script(
        "test_eqcorr_runner",
        "scripts/live/run_shadow_economic_correlation.py",
    )
    _write_active(tmp_path, "EPOCH_B")
    monkeypatch.setattr(module, "REPO", tmp_path)

    class FakeEngine:
        def __init__(self, *, repo: Path, strict_epoch: bool) -> None:
            assert repo == tmp_path
            assert strict_epoch is True
            self.epoch_id = module._active_epoch_id()
            self.errors: list[str] = []

        def write_health(self) -> dict[str, object]:
            return {"source_epoch_id": self.epoch_id}

    monkeypatch.setattr(module, "ShadowEconomicCorrelationEngine", FakeEngine)

    current = FakeEngine.__new__(FakeEngine)
    current.epoch_id = "EPOCH_A"
    current.errors = []

    replacement = module._rollover_if_needed(current)

    assert replacement is not current
    assert replacement.epoch_id == "EPOCH_B"


def test_stp_runner_rolls_only_to_valid_active_engine(tmp_path, monkeypatch) -> None:
    module = _load_script(
        "test_stp_runner",
        "scripts/live/run_shadow_structural_protection.py",
    )
    _write_active(tmp_path, "EPOCH_B")
    monkeypatch.setattr(module, "REPO", tmp_path)

    class FakeEngine:
        def __init__(self, *, repo: Path, strict_epoch: bool) -> None:
            assert repo == tmp_path
            assert strict_epoch is True
            self.epoch_id = module._active_epoch_id()
            self.errors: list[str] = []
            self.exact_ok = True

        def write_health(self) -> dict[str, object]:
            return {
                "source_epoch_id": self.epoch_id,
                "baseline_divergence_count": 0,
            }

    monkeypatch.setattr(module, "StructuralProtectionEngine", FakeEngine)

    current = FakeEngine.__new__(FakeEngine)
    current.epoch_id = "EPOCH_A"
    current.errors = []
    current.exact_ok = True

    replacement = module._rollover_if_needed(current)

    assert replacement is not current
    assert replacement.epoch_id == "EPOCH_B"
    assert replacement.exact_ok is True


def test_eqcorr_runner_fails_closed_when_active_epoch_unreadable(
    tmp_path, monkeypatch
) -> None:
    module = _load_script(
        "test_eqcorr_runner_missing_active",
        "scripts/live/run_shadow_economic_correlation.py",
    )
    monkeypatch.setattr(module, "REPO", tmp_path)

    class Current:
        epoch_id = "EPOCH_A"
        errors: list[str] = []

    with pytest.raises(RuntimeError, match="ACTIVE_EPOCH_UNREADABLE"):
        module._rollover_if_needed(Current())


def test_stp_runner_fails_closed_when_active_epoch_unreadable(
    tmp_path, monkeypatch
) -> None:
    module = _load_script(
        "test_stp_runner_missing_active",
        "scripts/live/run_shadow_structural_protection.py",
    )
    monkeypatch.setattr(module, "REPO", tmp_path)

    class Current:
        epoch_id = "EPOCH_A"
        errors: list[str] = []

    with pytest.raises(RuntimeError, match="ACTIVE_EPOCH_UNREADABLE"):
        module._rollover_if_needed(Current())
