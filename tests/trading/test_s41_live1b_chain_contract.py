"""S4.1 → LIVE1B chain contract.

Locks: closed-bar cognition → S4.1 commands → LIVE1B books.
LIVE1A journal is observe-only. Do not xfail these tests.
Do not flip production config in this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from btc_ml.trading.command_bus import VALID_INTENTS
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.s41_command_consumer import S41CommandConsumer
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator
from btc_ml.trading.proofs import build_synthetic_feed, isolated_environment, synthetic_command
from btc_ml.trading.timeframe_manager import ANTI_SAW_ENABLED, TimeframeManager, _preview_context_for_open_position
from btc_ml.trading.timeframe_state_adapter import (
    TimeframeSources,
    _scoped_lifecycle,
    load_sources,
    resolve_timeframe_state,
)

CONTRACT_PATH = ROOT / "config" / "trading" / "s41_live1b_chain_contract.json"

pytestmark = pytest.mark.s41_chain_contract


def _contract() -> dict:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert payload["contract_id"] == "S41_LIVE1B_CHAIN_V1"
    assert payload["entry_source"] == "s41_command_bus"
    return payload


def _production_paper_json() -> dict:
    return json.loads((ROOT / "config" / "intrabar_paper_execution.json").read_text(encoding="utf-8"))


def _lifecycle_builder():
    import importlib.util

    path = ROOT / "scripts" / "research" / "build_market_context_lifecycle_memory.py"
    spec = importlib.util.spec_from_file_location("build_market_context_lifecycle_memory", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _availability(*, tf: str, evaluation: str, bar_open: str, bar_close: str) -> dict:
    return {
        "evaluation_timestamp": evaluation,
        "timeframe": tf,
        "source_bar_open": bar_open,
        "source_bar_close": bar_close,
        "source_state_timestamp": bar_open,
        "source_event_timestamp": bar_open,
        "availability_status": "FRESH_EVENT",
        "availability_reason": "completed_bar_closed_at_or_before_evaluation",
        "is_new_event": True,
        "writer_state": "RUNNING",
    }


def _life_row(*, ts: str, tf: str, context: str, episode: str) -> dict:
    return {
        "timestamp": ts,
        "timeframe": tf,
        "active_market_context": context,
        "lifecycle_state": "ACTIVE",
        "context_episode_id": episode,
        "invalidation_reason": None,
        "active_context_started_at": ts,
        "context_origin_price": 60500.0,
    }


def _sources_for(context_by_tf: dict[str, str], *, evaluation: str = "2026-07-01T04:00:00Z") -> TimeframeSources:
    availability = [
        _availability(
            tf="M15",
            evaluation=evaluation,
            bar_open="2026-07-01T03:45:00Z",
            bar_close="2026-07-01T04:00:00Z",
        ),
        _availability(
            tf="M30",
            evaluation=evaluation,
            bar_open="2026-07-01T03:30:00Z",
            bar_close="2026-07-01T04:00:00Z",
        ),
        _availability(
            tf="H1",
            evaluation=evaluation,
            bar_open="2026-07-01T03:00:00Z",
            bar_close="2026-07-01T04:00:00Z",
        ),
        _availability(
            tf="H4",
            evaluation=evaluation,
            bar_open="2026-07-01T00:00:00Z",
            bar_close="2026-07-01T04:00:00Z",
        ),
    ]
    lifecycle = [
        _life_row(
            ts="2026-07-01T03:45:00Z",
            tf=tf,
            context=ctx,
            episode=f"{tf}-ep",
        )
        for tf, ctx in context_by_tf.items()
    ]
    return TimeframeSources(
        availability=pd.DataFrame(availability),
        lifecycle=pd.DataFrame(lifecycle),
        synthesis=pd.DataFrame(),
        lifecycle_source="parquet",
    )


# --------------------------------------------------------------------------- #
# Contract file itself
# --------------------------------------------------------------------------- #
def test_contract_file_lists_every_invariant():
    payload = _contract()
    ids = [row["id"] for row in payload["invariants"]]
    assert ids == [
        "OWNER_SINGLE",
        "JOURNAL_OBSERVE_ONLY",
        "PROVISIONAL_NOT_MANAGER",
        "NO_M15_INHERITANCE",
        "HOLD_ZERO",
        "EPISODE_ONESHOT",
        "ATOMIC_FLIP",
        "RETRY_MARKET",
        "VOLUME_CLASS_LINEAGE",
        "CHART_FOLLOWS_OWNER",
        "CUTOVER_SCRIPTS",
        "LOADER_ALLOWS_S41",
        "COGNITION_OWNS_S41",
    ]
    assert payload["forbidden_production_entry_source"] == "context_journal"
    assert "LIVE1A journal OPEN/FLIP/END fills" in payload["do_not_restore"]


# --------------------------------------------------------------------------- #
# Green locks — already true, must stay true
# --------------------------------------------------------------------------- #
def test_hold_zero_and_no_bar_count_anti_saw():
    mod = _lifecycle_builder()
    assert mod.MIN_ACTIVE_CONTEXT_HOLD_BARS == 0
    assert mod.CONFIRMED_OPPOSITE_CONFIRM_BARS == 1
    assert ANTI_SAW_ENABLED is False


def test_provisional_intrabar_is_never_s41_actionable():
    state = resolve_timeframe_state(
        timeframe="M15",
        evaluation_timestamp="2026-07-01T04:00:00.100Z",
        sources=TimeframeSources(),
        allow_provisional=True,
        evaluation_mode="PROVISIONAL_INTRABAR",
        provisional_lifecycle={
            "active_market_context": "SHORT_CONTEXT",
            "lifecycle_state": "ACTIVE",
            "context_episode_id": "M15:prov:1",
        },
    )
    assert state["actionable"] is False
    assert state["no_action_reason"] == "PROVISIONAL_NOT_ROUTED_TO_MANAGER"
    assert state["evaluation_mode"] == "PROVISIONAL_INTRABAR"


def test_untagged_lifecycle_does_not_broadcast_m15_to_h1():
    untagged = pd.DataFrame(
        [
            {
                "timestamp": "2026-07-01T03:45:00Z",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": "only-m15",
            }
        ]
    )
    assert len(_scoped_lifecycle(untagged, "M15")) == 1
    assert len(_scoped_lifecycle(untagged, "H1")) == 0
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="H1",
                    evaluation="2026-07-01T04:00:00Z",
                    bar_open="2026-07-01T03:00:00Z",
                    bar_close="2026-07-01T04:00:00Z",
                )
            ]
        ),
        lifecycle=untagged,
        lifecycle_source="parquet",
    )
    h1 = resolve_timeframe_state(
        timeframe="H1",
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=sources,
    )
    assert h1["actionable"] is False
    assert h1["no_action_reason"] == "NO_LIFECYCLE_ROW_AT_OR_BEFORE_BAR_CLOSE"
    assert h1["timeframe_direction"] != "LONG"


def test_chart_s41_owner_paints_parquet_not_journal():
    import sys

    viz = ROOT / "apps" / "context_visualizer"
    if str(viz) not in sys.path:
        sys.path.insert(0, str(viz))
    from timeframe_chart_truth import context_band_source

    assert context_band_source(live1b=True, entry_source="s41_command_bus") == (
        "market_context_lifecycle_episodes"
    )
    assert context_band_source(live1b=True, entry_source="context_journal") == (
        "LIVE1A_INTRABAR_CONTEXT_JOURNAL"
    )


def test_retry_market_does_not_consume_command_id(tmp_path: Path):
    bus, _books, _ = isolated_environment(tmp_path / "bus")
    command = synthetic_command(
        timeframe="M15",
        intent="OPEN_LONG",
        evaluation_timestamp="2026-07-01T04:00:00Z",
        episode="M15:closed:keep",
    )
    bus.append([command])

    class _Cfg:
        timeframes = ("M15",)
        max_bbo_age_ms = 2000.0

    class _Engine:
        cfg = _Cfg()
        bbo = type(
            "BBO",
            (),
            {"resolve_live_local_entry_bbo": staticmethod(lambda **_k: (object(), None, 0.0, "local"))},
        )()

        def execution_market_ready_for_entry(self) -> bool:
            return False

        def apply_s41_manager_command(self, _command: dict) -> dict:
            raise AssertionError("not-ready command must not be applied")

    consumer = S41CommandConsumer(
        _Engine(),
        checkpoint_path=tmp_path / "s41_command_cursor.json",
        consume_after=None,
        bus=bus,
    )
    assert consumer.poll() == []
    cursor = tmp_path / "s41_command_cursor.json"
    if cursor.exists():
        stored = json.loads(cursor.read_text(encoding="utf-8"))
        assert command["command_id"] not in stored.get("processed_command_ids", [])


def test_consumer_raises_stale_cursor_floor_to_configured(tmp_path: Path):
    from btc_ml.trading.intrabar_paper.s41_command_consumer import later_iso

    assert later_iso("2026-09-07T09:54:42.626102Z", "2026-09-11T20:50:00Z") == (
        "2026-09-11T20:50:00Z"
    )
    cursor = tmp_path / "s41_command_cursor.json"
    cursor.write_text(
        json.dumps(
            {
                "consume_after": "2026-09-07T09:54:42.626102Z",
                "processed_command_ids": ["TF_CMD_OLD"],
                "schema_version": "s41_live1b_command_cursor_v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class _Cfg:
        timeframes = ("M15",)
        max_bbo_age_ms = 2000.0

    class _Engine:
        cfg = _Cfg()

    consumer = S41CommandConsumer(
        _Engine(),
        checkpoint_path=cursor,
        consume_after="2026-09-11T22:28:00Z",
        bus=type("Bus", (), {})(),
    )
    assert consumer._state["consume_after"] == "2026-09-11T22:28:00Z"
    assert consumer._state["processed_command_ids"] == ["TF_CMD_OLD"]
    stored = json.loads(cursor.read_text(encoding="utf-8"))
    assert stored["consume_after"] == "2026-09-11T22:28:00Z"


def test_journal_start_does_not_open_when_entry_source_is_s41(tmp_path: Path):
    from datetime import datetime, timedelta, timezone

    from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
    from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch

    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    raw = _production_paper_json()
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    raw["entry_source"] = "s41_command_bus"
    (repo / "config" / "intrabar_paper_execution.json").write_text(json.dumps(raw) + "\n", encoding="utf-8")
    journal = repo / "data" / "cognition" / "intrabar_context_events"
    journal.mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    event = {
        "context_event_id": "CTX_phase0_observe",
        "event_type": "CONTEXT_START",
        "timeframe": "M15",
        "new_context": "LONG_CONTEXT",
        "event_timestamp": ts,
        "event_monotonic_ns": 2_000_000,
        "context_event_price": 100.1,
        "lifecycle_episode_id": "M15:closed:phase0",
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
        "decision_available_at": ts,
        "best_bid": 100.0,
        "best_ask": 100.2,
    }
    (journal / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    cfg = load_intrabar_paper_config(repo_root=repo)
    assert cfg.entry_source == "s41_command_bus"
    engine = IntrabarPaperEngine(
        cfg=cfg,
        epoch=activate_epoch(
            create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=cfg.initial_equity_usd, utc_stamp="P0"),
            epochs_root=cfg.epochs_root,
        ),
        activation_monotonic_ns=1,
    )
    actions = engine.poll_context_journal()
    assert actions == []
    assert engine.positions == {}


def test_volume_class_lineage_is_closed_bar_parquet_not_live1a_stub():
    pipeline = (ROOT / "src" / "btc_ml" / "live" / "intrabar" / "cognition_pipeline.py").read_text(
        encoding="utf-8"
    )
    auction = (ROOT / "scripts" / "research" / "build_auction_episode_memory.py").read_text(
        encoding="utf-8"
    )
    adapter = (ROOT / "src" / "btc_ml" / "trading" / "timeframe_state_adapter.py").read_text(
        encoding="utf-8"
    )
    assert 'classification_row={"volume_class": "unknown"}' in pipeline
    assert "volume_classification_memory" not in auction
    assert "volume_response" in auction
    assert "market_context_lifecycle_memory.parquet" in adapter
    assert _contract()["owners"]["volume_classes"].startswith("volume_classification_memory.parquet")


# --------------------------------------------------------------------------- #
# Owner locks — production entry_source is S4.1
# --------------------------------------------------------------------------- #
def test_owner_single_production_entry_source_is_s41():
    raw = _production_paper_json()
    assert raw["entry_source"] == "s41_command_bus"
    cfg = load_intrabar_paper_config(repo_root=ROOT)
    assert cfg.entry_source == "s41_command_bus"


def test_loader_allows_canonical_s41_command_bus():
    src = (ROOT / "src" / "btc_ml" / "trading" / "intrabar_paper" / "config.py").read_text(
        encoding="utf-8"
    )
    assert "production entry_source must be context_journal" not in src
    assert "s41_command_bus waits for S4.1 closed bars" not in src


def test_cutover_and_bootstrap_write_s41_as_entry_authority():
    cutover = (ROOT / "scripts" / "ops" / "s41_live1b_hybrid_cutover.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts" / "deploy" / "bootstrap_vps_environment.py").read_text(
        encoding="utf-8"
    )
    assert '"entry_source": "s41_command_bus"' in cutover
    assert '"entry_source": "s41_command_bus"' in bootstrap
    assert "S4.1 is not entry authority" not in cutover
    assert "S4.1 is not entry authority" not in bootstrap
    assert "do not restore s41_command_bus" not in cutover


def test_logic1_live_policy_must_not_forbid_s41_owner():
    payload = json.loads(
        (ROOT / "config" / "research" / "logic1_a_lag_execution.json").read_text(encoding="utf-8")
    )
    joined = " ".join(str(x) for x in payload.get("what_live_must_do") or [])
    assert "never s41_command_bus on production" not in joined
    assert "entry_source=s41_command_bus" in joined


def test_journal_open_is_not_production_lock():
    live1b = (ROOT / "tests" / "trading" / "intrabar_paper" / "test_live1b_intrabar_paper.py").read_text(
        encoding="utf-8"
    )
    lag = (ROOT / "tests" / "trading" / "test_m15_no_45min_context_lag.py").read_text(encoding="utf-8")
    assert "test_production_entry_source_is_context_journal_not_s41_bar_close" not in live1b
    assert "assert raw[\"entry_source\"] == \"context_journal\"" not in lag


def test_public_ws_payloads_are_queued_off_the_ping_thread():
    src = (ROOT / "scripts" / "live" / "run_intrabar_paper_manager.py").read_text(encoding="utf-8")
    public_block = src.split("thread_name=\"live1b-futures-public\"", 1)[1].split(
        "thread_name=\"live1b-futures-market\"", 1
    )[0]
    assert "queued_payloads=True" in public_block
    assert "ping_timeout=20" in src


def test_paper_manager_does_not_wait_on_live1a_health():
    compose = (ROOT / "deploy" / "vps" / "docker-compose.yml").read_text(encoding="utf-8")
    paper = compose.split("paper-manager:", 1)[1].split("timeframe-manager:", 1)[0]
    assert "cognition-runtime:" not in paper
    assert "check_paper_manager.py" in paper


def test_episode_oneshot_manager_does_not_reopen_same_episode(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())
    sources = _sources_for({"M15": "LONG_CONTEXT", "M30": "LONG_CONTEXT", "H1": "LONG_CONTEXT", "H4": "LONG_CONTEXT"})
    kwargs = dict(sources=sources, feed=build_synthetic_feed(), persist=True)
    first = manager.run_cycle(evaluation_timestamp="2026-07-01T04:00:00Z", **kwargs)
    second = manager.run_cycle(evaluation_timestamp="2026-07-01T04:15:00Z", **kwargs)
    m15_first = next(cmd for cmd in first["commands"] if cmd["timeframe"] == "M15")
    m15_second = next(cmd for cmd in second["commands"] if cmd["timeframe"] == "M15")
    assert m15_first["intent"] == "OPEN_LONG"
    assert m15_second["intent"] != "OPEN_LONG"
    assert "EPISODE_ALREADY_TRADED" in json.loads(m15_second["reason_codes"])


def test_s41_open_uses_traded_episode_gate_like_journal():
    text = (ROOT / "src" / "btc_ml" / "trading" / "intrabar_paper" / "engine.py").read_text(
        encoding="utf-8"
    )
    assert "FLIP and S4.1 command-bus are not this gate" not in text


def test_atomic_flip_same_cycle_closes_and_opens_opposite(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())

    def views(*, mark_price=None):
        return {
            "M15": {
                "open_position": {
                    "position_id": "pos_long",
                    "direction": "LONG",
                    "quantity": 0.1,
                    "entry_price": 60500.0,
                    "stop_loss_price": 59900.0,
                    "take_profit_price": 61400.0,
                    "entry_fee_usd": 1.0,
                    "status": "OPEN",
                },
                "open_risk_usd": 250.0,
            },
            "M30": {"open_position": None, "open_risk_usd": 0.0},
            "H1": {"open_position": None, "open_risk_usd": 0.0},
            "H4": {"open_position": None, "open_risk_usd": 0.0},
        }

    monkeypatch.setattr(manager, "trader_views", views)
    sources = _sources_for({"M15": "SHORT_CONTEXT"})
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=sources,
        feed=build_synthetic_feed(),
        persist=True,
    )
    m15 = [cmd for cmd in cycle["commands"] if cmd["timeframe"] == "M15"]
    intents = [cmd["intent"] for cmd in m15]
    assert "CLOSE" in intents or "FLIP" in intents
    assert "OPEN_SHORT" in intents or "FLIP" in intents


def test_valid_intents_include_flip_or_same_cycle_pair():
    """FLIP may be a first-class intent; if not, ATOMIC_FLIP test still binds the pair."""
    assert set(VALID_INTENTS) >= {"OPEN_LONG", "OPEN_SHORT", "CLOSE", "HOLD", "NO_ACTION"}


def test_s41_load_sources_ignores_live1a_journal(tmp_path, monkeypatch):
    from btc_ml.trading import timeframe_state_adapter as ad

    life = tmp_path / "life.parquet"
    pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-01T03:45:00Z"),
                "timeframe": "M15",
                "active_market_context": "LONG_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "context_episode_id": 321,
            }
        ]
    ).to_parquet(life, index=False)
    journal = tmp_path / "events.jsonl"
    journal.write_text(
        json.dumps(
            {
                "timeframe": "M15",
                "event_type": "CONTEXT_FLIP",
                "new_context": "SHORT_CONTEXT",
                "event_timestamp": "2026-09-11T15:55:42Z",
                "lifecycle_episode_id": "M15:prov:1",
                "evidence": {"lifecycle_state": "ACTIVE"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ad, "LIFECYCLE_MEMORY", life)
    monkeypatch.setattr(ad, "CONTEXT_JOURNAL", journal)
    monkeypatch.setattr(ad, "AVAILABILITY_MEMORY", tmp_path / "no_avail.parquet")
    monkeypatch.setattr(ad, "SYNTHESIS_MEMORY", tmp_path / "no_syn.parquet")
    monkeypatch.setattr(ad, "PAPER_EXECUTION_OVERLAY", tmp_path / "no_overlay.json")
    monkeypatch.setattr(ad, "PAPER_EXECUTION_CONFIG", tmp_path / "no_cfg.json")
    monkeypatch.setattr(ad, "ACTIVATION_PATH", tmp_path / "no_act.json")
    sources = load_sources()
    assert sources.lifecycle_source == "parquet"
    assert str(sources.lifecycle.iloc[-1]["active_market_context"]).upper() == "LONG_CONTEXT"


def test_uncertain_cognition_keeps_long_and_s41_holds_open_long(tmp_path, monkeypatch):
    life_mod = _lifecycle_builder()
    src = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-07-01 03:30:00", tz="UTC"),
                "close": 60500.0,
                "market_context": "LONG_CONTEXT",
                "context_status": "ACTIVE",
                "cognitive_market_state": "LOWER_ABSORPTION",
                "state_direction": "LONG",
                "context_reason": "LONG/ACTIVE",
                "auction_episode": "LOWER_ABSORPTION",
                "action_allowed": False,
                "action_reason": "shadow",
            },
            {
                "timestamp": pd.Timestamp("2026-07-01 03:45:00", tz="UTC"),
                "close": 60510.0,
                "market_context": "OBSERVE",
                "context_status": "OBSERVE",
                "cognitive_market_state": "UNCERTAIN",
                "state_direction": "UNKNOWN",
                "context_reason": "OBSERVE/OBSERVE",
                "auction_episode": "UNKNOWN",
                "action_allowed": False,
                "action_reason": "shadow",
            },
        ]
    )
    memory = life_mod.build_lifecycle_memory(src)
    memory["timeframe"] = "M15"
    assert list(memory["active_market_context"]) == ["LONG_CONTEXT", "LONG_CONTEXT"]
    sources = TimeframeSources(
        availability=pd.DataFrame(
            [
                _availability(
                    tf="M15",
                    evaluation="2026-07-01T04:00:00Z",
                    bar_open="2026-07-01T03:45:00Z",
                    bar_close="2026-07-01T04:00:00Z",
                )
            ]
        ),
        lifecycle=memory,
        lifecycle_source="parquet",
    )
    state = resolve_timeframe_state(
        timeframe="M15",
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=sources,
    )
    assert state["timeframe_state"] == "LONG_CONTEXT"
    assert state["lifecycle_phase"] == "ACTIVE"
    assert state["actionable"] is True
    assert _preview_context_for_open_position(
        "LONG", state["timeframe_state"], state["lifecycle_phase"]
    ) == "LONG_CONTEXT"

    monkeypatch.setattr(TimeframeManager, "_use_live1b_position_views", staticmethod(lambda: False))
    bus, books, _ = isolated_environment(tmp_path / "books")
    manager = TimeframeManager(bus=bus, books=books, risk=PortfolioRiskCoordinator.load())

    def views(*, mark_price=None):
        return {
            "M15": {
                "open_position": {
                    "position_id": "pos_long",
                    "direction": "LONG",
                    "quantity": 0.1,
                    "entry_price": 60500.0,
                    "stop_loss_price": 59900.0,
                    "take_profit_price": 61400.0,
                    "entry_fee_usd": 1.0,
                    "status": "OPEN",
                },
                "open_risk_usd": 250.0,
            },
            "M30": {"open_position": None, "open_risk_usd": 0.0},
            "H1": {"open_position": None, "open_risk_usd": 0.0},
            "H4": {"open_position": None, "open_risk_usd": 0.0},
        }

    monkeypatch.setattr(manager, "trader_views", views)
    cycle = manager.run_cycle(
        evaluation_timestamp="2026-07-01T04:00:00Z",
        sources=sources,
        feed=build_synthetic_feed(),
        persist=True,
    )
    m15 = next(cmd for cmd in cycle["commands"] if cmd["timeframe"] == "M15")
    assert m15["intent"] == "HOLD"
    assert m15["timeframe_state"] == "LONG_CONTEXT"
