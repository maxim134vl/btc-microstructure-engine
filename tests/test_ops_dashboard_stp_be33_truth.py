"""Read-only Operations Dashboard coverage for the independent STP_BE33 shadow."""

from __future__ import annotations

import ops_dashboard_runtime_truth as truth


def test_stp_be33_truth_uses_active_epoch_manifest_and_real_telemetry() -> None:
    payload = truth.build_runtime_truth_snapshot()["shadow_stp_be33"]

    assert payload["policy_id"] == "STP_BE33"
    assert payload["policy_version"] == "STP_BE33_V1"
    assert payload["binding_status"] == "BOUND_CURRENT"
    assert payload["epoch_match"] is True
    assert payload["policy_fingerprint_match"] is True
    assert payload["trigger_source"] == "BINANCE_FUTURES_AGG_TRADE_DURABLE_EXECUTION_WAL"
    assert payload["canonical_write_capability"] is False
    assert payload["live1b_command_capability"] is False
    assert payload["real_execution_capability"] is False
    assert payload["research_safety_status"] == "ISOLATED"
    assert payload["violations"] == []
    assert payload["pid"] == 13136
    assert payload["process_health"] == "RUNNING"
    assert payload["event_count"] == sum(payload["event_counts"].values())
    assert payload["outcome_count"] == sum(payload["outcomes_by_timeframe"].values())


def test_stp_be33_uses_epoch_scoped_state_when_legacy_root_state_is_absent() -> None:
    payload = truth.build_runtime_truth_snapshot()["shadow_stp_be33"]

    assert not (truth.ROOT / "data/trading/shadow_structural_protection/stp_be33/health.json").exists()
    assert payload["source_paths"]["health"].endswith(
        "/epochs/PER_TF_EQUITY_1PCT_V1_20260802_155305/health.json"
    )
    assert payload["source_epoch_id"] == "PER_TF_EQUITY_1PCT_V1_20260802_155305"
    assert payload["policy_fingerprint"].startswith("23048fa5e8336444")


def test_stp_be33_is_a_separate_dashboard_card() -> None:
    source = (
        truth.ROOT / "dashboard/frontend/src/components/ops/OpsUnifiedDashboard.tsx"
    ).read_text(encoding="utf-8")

    assert 'data-section="shadow-stp-be33"' in source
    assert "STP_BE33 Shadow" in source
    assert source.index("STP_BE33 Shadow") > source.index("Structural Stop/Take Shadow")
    assert "canonical writes, LIVE1B commands and real execution are disabled" in source
