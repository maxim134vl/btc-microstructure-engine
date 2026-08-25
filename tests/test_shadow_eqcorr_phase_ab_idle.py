"""Shadow EQCORR Phase A/B: idle checkpoint skip preserves semantics."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from btc_ml.trading.shadow_economic_correlation import (
    EXPECTED_ACTIVE_FP,
    EXPECTED_EPOCH,
    EXPECTED_PARENT_FP,
)
from btc_ml.trading.shadow_economic_correlation.engine import (
    ShadowEconomicCorrelationEngine,
)


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def shadow_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    shutil.copy(
        REPO / "config/intrabar_paper_execution.json",
        repo / "config/intrabar_paper_execution.json",
    )
    books = repo / "data/trading/intrabar_paper" / EXPECTED_EPOCH / "books"
    books.mkdir(parents=True)
    for name in ("signals", "commands", "orders", "fills", "positions", "trades"):
        (books / f"{name}.jsonl").write_text("", encoding="utf-8")
    epochs = repo / "data/trading/paper_epochs"
    epochs.mkdir(parents=True)
    (epochs / "active.json").write_text(
        json.dumps(
            {
                "paper_epoch_id": EXPECTED_EPOCH,
                "trading_contract_fingerprint": EXPECTED_ACTIVE_FP,
                "parent_trading_contract_fingerprint": EXPECTED_PARENT_FP,
                "epoch_status": "ACTIVE",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "data/cognition/intrabar_context_events").mkdir(parents=True)
    (repo / "data/cognition/intrabar_context_events" / "events.jsonl").write_text(
        "", encoding="utf-8"
    )
    (repo / "data/runtime").mkdir(parents=True)
    return repo


def test_idle_poll_skips_checkpoint_and_caches_reads(shadow_repo: Path) -> None:
    engine = ShadowEconomicCorrelationEngine(repo=shadow_repo, strict_epoch=True)
    gen0 = engine.state_generation
    first = engine.poll_once()
    gen1 = engine.state_generation
    assert first["entries"] == 0
    assert first["closes"] == 0
    assert first["enrichments"] == 0
    assert gen1 == gen0  # no idle checkpoint inflation
    assert engine.observe.idle_checkpoint_skips >= 1
    assert "io_observe" in first
    assert first["poll_ms"] >= 0

    # Second idle poll should hit JSONL cache for unchanged paper/shadow tables.
    misses_before = engine.observe.cache_misses
    second = engine.poll_once()
    assert second["entries"] == 0
    assert engine.state_generation == gen1
    # After reset_poll, cache_hits accumulate within the poll; health exposes them.
    health = engine.write_health()
    assert "io_observe" in health
    assert engine.observe.cache_hits >= 1 or engine.observe.cache_misses <= misses_before + 2
