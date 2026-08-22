"""Hybrid host launcher must start S4.1 manager and never start S4.1 traders."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = (ROOT / "scripts" / "btc_ml_host.py").read_text(encoding="utf-8")


def test_model_start_uses_manager_not_traders() -> None:
    assert 'run_tf_ctl("start", "manager")' in HOST
    assert 'run_tf_ctl("stop", "traders")' in HOST
    assert 'run_tf_ctl("start", "traders")' not in HOST
    assert 'run_tf_ctl("start", "all")' not in HOST


def test_stop_wrappers_exist() -> None:
    assert (ROOT / "scripts" / "stop_model.sh").is_file()
    assert (ROOT / "scripts" / "stop_dashboard.sh").is_file()
    assert "model stop" in (ROOT / "scripts" / "stop_model.sh").read_text(encoding="utf-8")
    assert "dashboard stop" in (ROOT / "scripts" / "stop_dashboard.sh").read_text(encoding="utf-8")


def test_model_ctls_include_shadow_structural_protection() -> None:
    assert "scripts/live/shadow_structural_protection_ctl.py" in HOST
    assert "run_shadow_structural_protection.py" in HOST
