"""Regression tests for PAPER-epoch-isolated shadow state."""

from __future__ import annotations

import json
from pathlib import Path

from btc_ml.model_assurance.shadow import unified_snapshot as usm
from btc_ml.trading.shadow_economic_correlation import engine as eq_engine
from btc_ml.trading.shadow_economic_correlation.paths import (
    shadow_epoch_root as eqcorr_epoch_root,
)
from btc_ml.trading.shadow_structural_protection import engine as stp_engine
from btc_ml.trading.shadow_structural_protection.paths import (
    shadow_epoch_root as stp_epoch_root,
)


def test_shadow_roots_are_isolated_by_paper_epoch(tmp_path: Path) -> None:
    eq_a = eqcorr_epoch_root(tmp_path, epoch_id="EPOCH_A")
    eq_b = eqcorr_epoch_root(tmp_path, epoch_id="EPOCH_B")
    stp_a = stp_epoch_root(tmp_path, epoch_id="EPOCH_A")
    stp_b = stp_epoch_root(tmp_path, epoch_id="EPOCH_B")

    assert eq_a != eq_b
    assert stp_a != stp_b
    assert eq_a == tmp_path / "data/trading/shadow_economic_correlation/epochs/EPOCH_A"
    assert stp_a == tmp_path / "data/trading/shadow_structural_protection/epochs/EPOCH_A"


def test_unified_snapshot_resolves_active_epoch_shadow_dirs(tmp_path: Path) -> None:
    active = tmp_path / "data/trading/paper_epochs/active.json"
    active.parent.mkdir(parents=True)
    active.write_text(
        json.dumps({"paper_epoch_id": "CURRENT_EPOCH"}) + "\n",
        encoding="utf-8",
    )

    paths = usm.unified_paths(tmp_path)

    assert paths["eqcorr_dir"] == (
        tmp_path / "data/trading/shadow_economic_correlation/epochs/CURRENT_EPOCH"
    )
    assert paths["stp_dir"] == (
        tmp_path / "data/trading/shadow_structural_protection/epochs/CURRENT_EPOCH"
    )


def test_strict_shadow_contract_is_fingerprint_based_not_epoch_locked() -> None:
    eq_source = Path(eq_engine.__file__).read_text(encoding="utf-8")
    stp_source = Path(stp_engine.__file__).read_text(encoding="utf-8")

    assert "self.epoch_id != EXPECTED_EPOCH" not in eq_source
    assert "self.epoch_id != EXPECTED_EPOCH" not in stp_source
    assert "self.source_fp != EXPECTED_ACTIVE_FP" in eq_source
    assert "self.parent_fp != EXPECTED_PARENT_FP" in eq_source
    assert "self.source_fp != EXPECTED_ACTIVE_FP" in stp_source
    assert "self.parent_fp != EXPECTED_PARENT_FP" in stp_source
