"""Regression: execution-time BBO fill vs occurrence provenance clocks."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from btc_ml.live.intrabar.cognition_pipeline import IntrabarCognitionEngine
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal
from btc_ml.live.intrabar.partial_bar_state import TF_SECONDS
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch


@pytest.fixture
def cfg(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[3] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    raw["entry_source"] = "context_journal"
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(raw, indent=2) + "\n", encoding="utf-8"
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    return load_intrabar_paper_config(repo_root=repo), repo


def _engine(cfg) -> IntrabarPaperEngine:
    ep = activate_epoch(
        create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=cfg.initial_equity_usd, utc_stamp="EXEC1"),
        epochs_root=cfg.epochs_root,
    )
    eng = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=1_000_000,
        receive_timestamp="2026-08-13T16:00:00Z",
        book_update_id="seed",
        domain="context",
    )
    return eng


def _fresh(seconds_ago: int = 20) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _stale(hours_ago: int = 6) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _start(
    *,
    eid: str,
    tf: str = "M15",
    episode: str = "ep_exec",
    mono: int = 2_000_000,
    bid: float = 100.0,
    ask: float = 100.2,
    occurrence_ts: str | None = None,
    decision_available_at: str | None = None,
    occurrence_price: float | str | None = 100.1,
    evaluation_mode: str = "CLOSED_BAR_CONTEXT_DECISION",
    extra: dict | None = None,
) -> dict:
    decision = decision_available_at or _fresh(20)
    occurrence = occurrence_ts or decision
    payload = {
        "context_event_id": eid,
        "event_type": "CONTEXT_START",
        "timeframe": tf,
        "previous_context": "OBSERVE",
        "new_context": "LONG_CONTEXT",
        "event_monotonic_ns": mono,
        "event_timestamp": occurrence,
        "context_occurrence_timestamp": occurrence,
        "decision_available_at": decision,
        "materialized_timestamp": _fresh(5),
        "ingested_at": _fresh(5),
        "best_bid": bid,
        "best_ask": ask,
        "bbo_receive_monotonic_ns": mono - 1000,
        "book_update_id": "b1",
        "lifecycle_episode_id": episode,
        "evaluation_mode": evaluation_mode,
        "delivery_mode": "LIVE",
    }
    if occurrence_price is not None:
        payload["context_event_price"] = occurrence_price
    if extra:
        payload.update(extra)
    return payload


def _end(
    *,
    eid: str,
    episode: str,
    mono: int,
    occurrence_ts: str,
    decision_available_at: str | None = None,
    occurrence_price: float | str | None = 100.1,
    bid: float = 100.0,
    ask: float = 100.2,
    extra: dict | None = None,
) -> dict:
    payload = _start(
        eid=eid,
        episode=episode,
        mono=mono,
        occurrence_ts=occurrence_ts,
        decision_available_at=decision_available_at or occurrence_ts,
        occurrence_price=occurrence_price,
        bid=bid,
        ask=ask,
        evaluation_mode="PROVISIONAL_INTRABAR",
        extra=extra,
    )
    payload["event_type"] = "CONTEXT_END"
    payload["previous_context"] = "LONG_CONTEXT"
    payload["new_context"] = "OBSERVE"
    return payload


def _flip(
    *,
    eid: str,
    episode: str,
    mono: int,
    occurrence_ts: str,
    decision_available_at: str | None = None,
    occurrence_price: float | str | None = 100.1,
    bid: float = 100.0,
    ask: float = 100.2,
    extra: dict | None = None,
    from_side: str = "LONG",
    to_side: str = "SHORT",
) -> dict:
    payload = _start(
        eid=eid,
        episode=episode,
        mono=mono,
        occurrence_ts=occurrence_ts,
        decision_available_at=decision_available_at or occurrence_ts,
        occurrence_price=occurrence_price,
        bid=bid,
        ask=ask,
        evaluation_mode="PROVISIONAL_INTRABAR",
        extra=extra,
    )
    payload["event_type"] = "CONTEXT_FLIP"
    payload["previous_context"] = f"{from_side}_CONTEXT"
    payload["new_context"] = f"{to_side}_CONTEXT"
    payload["from_side"] = from_side
    payload["to_side"] = to_side
    return payload


def _journal_append(cfg, event: dict) -> None:
    path = cfg.context_journal_root / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")


def test_a_fresh_immediate_execution(cfg):
    c, _ = cfg
    eng = _engine(c)
    now_before = datetime.now(timezone.utc)
    acts = eng.process_context_event(_start(eid="a_fresh"))
    now_after = datetime.now(timezone.utc)
    assert acts[0]["status"] == "ENTERED"
    fill = acts[0]["fill"]
    pos = eng.books.read_all("positions")[-1]
    assert fill["paper_fill_price"] == pytest.approx(100.2)
    assert fill["execution_price"] == pytest.approx(100.2)
    exec_ts = datetime.fromisoformat(str(fill["execution_timestamp"]).replace("Z", "+00:00"))
    assert now_before - timedelta(seconds=2) <= exec_ts <= now_after + timedelta(seconds=2)
    assert pos["opened_at"] == fill["execution_timestamp"]
    assert pos["ts"] == fill["execution_timestamp"] if "ts" in pos else True
    for table in ("signals", "commands", "orders", "fills"):
        row = eng.books.read_all(table)[-1]
        assert row["ts"] == fill["execution_timestamp"]


def test_b_delayed_m15_10_style_execution_uses_processing_time_bbo(cfg):
    c, _ = cfg
    eng = _engine(c)
    eng.update_bbo_from_market(
        best_bid=64000.0,
        best_ask=64001.5,
        receive_monotonic_ns=9_000_000,
        receive_timestamp=_fresh(1),
        book_update_id="mkt_now",
    )
    event = _start(
        eid="m15_10",
        episode="996",
        occurrence_ts="2026-08-13T16:15:00Z",
        decision_available_at=_fresh(25),
        occurrence_price=63361.48,
        bid=63360.0,
        ask=63362.0,
    )
    acts = eng.process_context_event(event)
    assert acts[0]["status"] == "ENTERED"
    fill = acts[0]["fill"]
    assert fill["paper_fill_price"] == pytest.approx(64001.5)
    assert fill["execution_price"] == pytest.approx(64001.5)
    assert fill["paper_fill_price"] != pytest.approx(63361.48)
    assert fill["paper_fill_price"] != pytest.approx(63362.0)
    assert fill["context_event_price"] == pytest.approx(63361.48)
    assert fill["context_occurrence_timestamp"] == "2026-08-13T16:15:00Z"
    assert fill["decision_available_at"] != fill["context_occurrence_timestamp"]
    assert fill["execution_timestamp"] != fill["context_occurrence_timestamp"]
    assert fill["entry_price_source"] == "execution_market_bbo"
    assert fill["execution_bbo_domain"] == "local"


def test_b_delayed_m15_11_style_short_uses_processing_time_bid(cfg):
    c, _ = cfg
    eng = _engine(c)
    eng.update_bbo_from_market(
        best_bid=62990.0,
        best_ask=62992.0,
        receive_monotonic_ns=9_000_000,
        receive_timestamp=_fresh(1),
        book_update_id="mkt_now",
    )
    event = _start(
        eid="m15_11",
        episode="997",
        occurrence_ts="2026-08-13T16:30:00Z",
        decision_available_at=_fresh(25),
        occurrence_price=62996.0,
        bid=62995.0,
        ask=62997.0,
        extra={"new_context": "SHORT_CONTEXT"},
    )
    acts = eng.process_context_event(event)
    assert acts[0]["status"] == "ENTERED"
    fill = acts[0]["fill"]
    assert fill["paper_fill_price"] == pytest.approx(62990.0)
    assert fill["paper_fill_price"] != pytest.approx(62996.0)
    assert fill["context_event_price"] == pytest.approx(62996.0)
    assert fill["entry_price_source"] == "execution_market_bbo"


def test_tp_then_same_episode_can_reenter(cfg):
    c, _ = cfg
    eng = _engine(c)
    episode = "ep_live"
    assert eng.process_context_event(_start(eid="tp_in", episode=episode))[0]["status"] == "ENTERED"
    assert eng._exit_position(
        tf="M15",
        trigger_type="TP",
        trigger_event_id="tp_out",
        trigger_timestamp=_fresh(10),
        trigger_monotonic_ns=2_500_000,
        trigger_price=None,
        context_event_id="tp_out",
        episode_id=episode,
        use_local_bbo=True,
    )["status"] == "EXITED"
    assert "M15" not in eng.positions
    acts = eng.process_context_event(_start(eid="tp_reenter", episode=episode, mono=3_000_000))
    assert acts[0]["status"] == "ENTERED"
    assert eng.positions["M15"].lifecycle_episode_id == episode


def test_sl_then_same_episode_can_reenter(cfg):
    c, _ = cfg
    eng = _engine(c)
    episode = "ep_sl"
    assert eng.process_context_event(_start(eid="sl_in", episode=episode))[0]["status"] == "ENTERED"
    assert eng._exit_position(
        tf="M15",
        trigger_type="SL",
        trigger_event_id="sl_out",
        trigger_timestamp=_fresh(10),
        trigger_monotonic_ns=2_500_000,
        trigger_price=None,
        context_event_id="sl_out",
        episode_id=episode,
        use_local_bbo=True,
    )["status"] == "EXITED"
    acts = eng.process_context_event(_start(eid="sl_reenter", episode=episode, mono=3_000_000))
    assert acts[0]["status"] == "ENTERED"


def test_s41_open_uses_local_bbo_not_context_clock(cfg):
    """Hybrid OPEN is priced from websocket local BBO, not cognition-domain quotes."""
    import time as time_mod

    c, _ = cfg
    eng = _engine(c)
    # Stale context-domain quote (cognition clock) must not gate the entry.
    eng.bbo.update_from_book_ticker(
        best_bid=90.0,
        best_ask=90.2,
        receive_monotonic_ns=1_000_000,
        receive_timestamp="2026-08-13T16:00:00Z",
        book_update_id="stale_context",
        domain="context",
    )
    now = time_mod.monotonic_ns()
    eng.update_bbo_from_market(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=now - 1_000,
        receive_timestamp=_fresh(0),
        book_update_id="live_local",
    )
    result = eng.apply_s41_manager_command(
        {
            "command_id": "TF_CMD_local_bbo",
            "timeframe": "M15",
            "intent": "OPEN_LONG",
            "action_allowed": True,
            "lifecycle_episode_id": "M15:live",
            "evaluation_timestamp": _fresh(20),
            "context_origin_price": 100.1,
        }
    )
    assert result["status"] == "ENTERED"
    assert result["fill"]["paper_fill_price"] == pytest.approx(100.2)
    assert result["fill"]["entry_price_source"] == "execution_market_bbo"


def test_s41_open_retries_after_missing_local_bbo(cfg):
    import time as time_mod

    c, _ = cfg
    eng = _engine(c)
    cmd = {
        "command_id": "TF_CMD_retry_local",
        "timeframe": "M15",
        "intent": "OPEN_LONG",
        "action_allowed": True,
        "lifecycle_episode_id": "M15:live",
        "evaluation_timestamp": _fresh(20),
        "context_origin_price": 100.1,
    }
    first = eng.apply_s41_manager_command(cmd)
    assert first["status"] == "ENTRY_BLOCKED_NO_CAUSAL_BBO"
    now = time_mod.monotonic_ns()
    eng.update_bbo_from_market(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=now - 1_000,
        receive_timestamp=_fresh(0),
        book_update_id="retry_local",
    )
    assert eng.apply_s41_manager_command(cmd)["status"] == "ENTERED"


def test_s41_second_engine_cannot_open_second_m15(cfg):
    import time as time_mod

    c, _ = cfg
    first = _engine(c)
    now = time_mod.monotonic_ns()
    first.update_bbo_from_market(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=now - 1_000,
        receive_timestamp=_fresh(0),
        book_update_id="dual_a",
    )
    cmd = {
        "command_id": "TF_CMD_dual_a",
        "timeframe": "M15",
        "intent": "OPEN_SHORT",
        "action_allowed": True,
        "lifecycle_episode_id": "M15:128",
        "evaluation_timestamp": _fresh(20),
        "context_origin_price": 100.1,
    }
    assert first.apply_s41_manager_command(cmd)["status"] == "ENTERED"
    second = IntrabarPaperEngine(cfg=c, epoch=first.epoch, activation_monotonic_ns=2_000_000)
    now2 = time_mod.monotonic_ns()
    second.update_bbo_from_market(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=now2 - 1_000,
        receive_timestamp=_fresh(0),
        book_update_id="dual_b",
    )
    other = dict(cmd)
    other["command_id"] = "TF_CMD_dual_b"
    result = second.apply_s41_manager_command(other)
    assert result["status"] == "ENTRY_BLOCKED_ACTIVE_POSITION"
    opens = second.books.open_positions()
    assert len(opens) == 1
    assert opens[0]["entry_context_event_id"] == "TF_CMD_dual_a"


def test_s41_open_reenters_after_tp(cfg):
    c, _ = cfg
    eng = _engine(c)
    episode = "M15:live"
    import time as time_mod

    now = time_mod.monotonic_ns()
    eng.update_bbo_from_market(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=now - 1_000,
        receive_timestamp=_fresh(0),
        book_update_id="s41_reentry",
    )
    first = {
        "command_id": "TF_CMD_reentry_a",
        "timeframe": "M15",
        "intent": "OPEN_LONG",
        "action_allowed": True,
        "lifecycle_episode_id": episode,
        "evaluation_timestamp": _fresh(20),
        "context_origin_price": 100.1,
    }
    assert eng.apply_s41_manager_command(first)["status"] == "ENTERED"
    assert eng._exit_position(
        tf="M15",
        trigger_type="TP",
        trigger_event_id="s41_tp",
        trigger_timestamp=_fresh(10),
        trigger_monotonic_ns=2_500_000,
        trigger_price=None,
        context_event_id="s41_tp",
        episode_id=episode,
        use_local_bbo=True,
    )["status"] == "EXITED"
    now2 = time_mod.monotonic_ns()
    eng.update_bbo_from_market(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=now2 - 1_000,
        receive_timestamp=_fresh(0),
        book_update_id="s41_reentry2",
    )
    second = dict(first)
    second["command_id"] = "TF_CMD_reentry_b"
    assert eng.apply_s41_manager_command(second)["status"] == "ENTERED"


def test_c_ended_episode_cannot_reenter(cfg):
    c, _ = cfg
    eng = _engine(c)
    assert eng.process_context_event(_start(eid="c1", episode="ep_ended"))[0]["status"] == "ENTERED"
    end = _start(eid="c_end", episode="ep_ended", mono=3_000_000)
    end["event_type"] = "CONTEXT_END"
    end["previous_context"] = "LONG_CONTEXT"
    end["new_context"] = "OBSERVE"
    assert eng.process_context_event(end)[0]["status"] == "EXITED"
    retry = _start(eid="c_retry", episode="ep_ended", mono=4_000_000)
    acts = eng.process_context_event(retry)
    assert acts == []
    assert "M15" not in eng.positions
    blocked = eng.books.read_all("blocked")
    assert blocked and blocked[-1]["reason"] == "ENTRY_BLOCKED_EPISODE_ALREADY_TRADED"


def test_d_new_episode_can_enter(cfg):
    c, _ = cfg
    eng = _engine(c)
    assert eng.process_context_event(_start(eid="d1", episode="ep_old"))[0]["status"] == "ENTERED"
    end = _start(eid="d_end", episode="ep_old", mono=3_000_000)
    end["event_type"] = "CONTEXT_END"
    end["previous_context"] = "LONG_CONTEXT"
    end["new_context"] = "OBSERVE"
    eng.process_context_event(end)
    acts = eng.process_context_event(_start(eid="d2", episode="ep_new", mono=4_000_000))
    assert acts[0]["status"] == "ENTERED"
    assert eng.positions["M15"].lifecycle_episode_id == "ep_new"


def test_e_flip_exit_then_entry_ordering(cfg):
    c, _ = cfg
    eng = _engine(c)
    eng.process_context_event(_start(eid="e0", tf="H4", episode="ep_flip", mono=2_000_000))
    eng.update_bbo_from_market(
        best_bid=100.5, best_ask=100.7, receive_monotonic_ns=3_000_000, book_update_id="2"
    )
    flip = {
        "context_event_id": "e_flip",
        "event_type": "CONTEXT_FLIP",
        "timeframe": "H4",
        "previous_context": "LONG_CONTEXT",
        "new_context": "SHORT_CONTEXT",
        "from_side": "LONG",
        "to_side": "SHORT",
        "event_monotonic_ns": 4_000_000,
        "event_timestamp": _fresh(10),
        "decision_available_at": _fresh(10),
        "context_event_price": "100.1",
        "best_bid": 100.5,
        "best_ask": 100.7,
        "bbo_receive_monotonic_ns": 3_999_000,
        "lifecycle_episode_id": "ep_flip",
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
        "ingested_at": _fresh(1),
    }
    acts = eng.process_context_event(flip)
    assert [a["status"] for a in acts] == ["EXITED", "ENTERED"]
    assert acts[0]["fill"].get("trigger_monotonic_ns", 4_000_000) < acts[1]["fill"]["fill_monotonic_ns"]
    assert acts[1]["fill"]["fill_monotonic_ns"] == acts[0]["fill"]["fill_monotonic_ns"] + 1
    assert eng.positions["H4"].side == "SHORT"


def test_f_stale_decision_blocked(cfg):
    c, _ = cfg
    eng = _engine(c)
    event = _start(eid="f_stale", decision_available_at=_stale(6), occurrence_ts=_stale(6))
    acts = eng.process_context_event(event)
    assert acts[0]["status"] == "ENTRY_BLOCKED_STALE_CONTEXT_EVENT"
    assert eng.positions == {}


def test_g_recovery_restart_non_entry(cfg):
    c, _ = cfg
    eng = _engine(c)
    event = _start(
        eid="g_recovery",
        extra={
            "restart_backfill": True,
            "materialization_class": "RESTART_BACKFILL",
            "revalidated_after_restart": True,
            "delivery_mode": "RECOVERY",
        },
    )
    acts = eng.process_context_event(event)
    assert acts[0]["status"] == "ENTRY_BLOCKED_REPLAY_SIGNAL"
    assert eng.positions == {}


def test_h_occurrence_price_retained_never_used_as_fill(cfg):
    c, _ = cfg
    eng = _engine(c)
    event = _start(
        eid="h_prov",
        occurrence_price=63361.48,
        bid=100.0,
        ask=100.2,
        occurrence_ts="2026-08-13T16:15:00Z",
        decision_available_at=_fresh(15),
    )
    acts = eng.process_context_event(event)
    fill = acts[0]["fill"]
    pos = eng.books.read_all("positions")[-1]
    assert fill["context_event_price"] == pytest.approx(63361.48)
    assert fill["paper_fill_price"] == pytest.approx(100.2)
    assert fill["execution_price"] == pytest.approx(100.2)
    assert pos["entry_price"] == pytest.approx(100.2)
    assert pos["context_event_price"] == pytest.approx(63361.48)
    assert pos["context_occurrence_timestamp"] == "2026-08-13T16:15:00Z"
    assert pos["decision_available_at"] != pos["context_occurrence_timestamp"]
    assert pos["execution_timestamp"] == pos["opened_at"]
    assert pos["materialized_timestamp"]


def test_kinematics_a_immediate_start_is_not_next_candle(cfg):
    c, _ = cfg
    eng = _engine(c)
    occurrence = _fresh(1)
    acts = eng.process_context_event(
        _start(eid="kin_a", occurrence_ts=occurrence, decision_available_at=occurrence)
    )
    assert acts[0]["status"] == "ENTERED"
    pos = eng.books.read_all("positions")[-1]
    opened = datetime.fromisoformat(str(pos["opened_at"]).replace("Z", "+00:00"))
    occ = datetime.fromisoformat(occurrence.replace("Z", "+00:00"))
    assert abs((opened - occ).total_seconds()) < 5
    next_candle = occ + timedelta(minutes=15)
    assert abs((opened - next_candle).total_seconds()) > 60


def test_kinematics_d_context_end_exits_now_at_current_bid(cfg):
    c, _ = cfg
    eng = _engine(c)
    assert eng.process_context_event(_start(eid="kin_d", episode="ep_end"))[0]["status"] == "ENTERED"
    eng.update_bbo_from_market(
        best_bid=63380.0,
        best_ask=63381.0,
        receive_monotonic_ns=9_000_000,
        receive_timestamp=_fresh(1),
        book_update_id="end_now",
    )
    occurrence = "2026-08-13T16:15:00Z"
    end = _start(
        eid="kin_d_end",
        episode="ep_end",
        mono=3_000_000,
        occurrence_ts=occurrence,
        occurrence_price=63361.48,
        bid=63300.0,
        ask=63302.0,
    )
    end["event_type"] = "CONTEXT_END"
    end["previous_context"] = "LONG_CONTEXT"
    end["new_context"] = "OBSERVE"
    now_before = datetime.now(timezone.utc)
    acts = eng.process_context_event(end)
    now_after = datetime.now(timezone.utc)
    assert acts[0]["status"] == "EXITED"
    fill = acts[0]["fill"]
    closed = [p for p in eng.books.read_all("positions") if p.get("status") == "CLOSED"][-1]
    assert fill["paper_fill_price"] == pytest.approx(63380.0)
    assert fill["execution_price"] == pytest.approx(63380.0)
    assert fill["paper_fill_price"] != pytest.approx(63361.48)
    assert fill["context_event_price"] == pytest.approx(63361.48)
    assert closed["closed_at"] == fill["execution_timestamp"]
    assert closed["closed_at"] != occurrence
    closed_ts = datetime.fromisoformat(str(closed["closed_at"]).replace("Z", "+00:00"))
    assert now_before - timedelta(seconds=2) <= closed_ts <= now_after + timedelta(seconds=2)
    assert "M15" not in eng.positions


def test_kinematics_e_flip_exits_and_enters_same_cycle_at_current_bbo(cfg):
    c, _ = cfg
    eng = _engine(c)
    eng.process_context_event(_start(eid="kin_e0", tf="H4", episode="ep_flip_k", mono=2_000_000))
    eng.update_bbo_from_market(
        best_bid=63410.0,
        best_ask=63412.0,
        receive_monotonic_ns=9_000_000,
        receive_timestamp=_fresh(1),
        book_update_id="flip_now",
    )
    flip = {
        "context_event_id": "kin_e_flip",
        "event_type": "CONTEXT_FLIP",
        "timeframe": "H4",
        "previous_context": "LONG_CONTEXT",
        "new_context": "SHORT_CONTEXT",
        "from_side": "LONG",
        "to_side": "SHORT",
        "event_monotonic_ns": 4_000_000,
        "event_timestamp": "2026-08-13T16:15:00Z",
        "context_occurrence_timestamp": "2026-08-13T16:15:00Z",
        "decision_available_at": _fresh(10),
        "context_event_price": "63361.48",
        "best_bid": 63360.0,
        "best_ask": 63362.0,
        "bbo_receive_monotonic_ns": 3_999_000,
        "lifecycle_episode_id": "ep_flip_k",
        "evaluation_mode": "PROVISIONAL_INTRABAR",
        "ingested_at": _fresh(1),
    }
    acts = eng.process_context_event(flip)
    assert [a["status"] for a in acts] == ["EXITED", "ENTERED"]
    assert acts[0]["fill"]["paper_fill_price"] == pytest.approx(63410.0)
    assert acts[1]["fill"]["paper_fill_price"] == pytest.approx(63410.0)
    assert acts[0]["fill"]["execution_timestamp"] != "2026-08-13T16:15:00Z"
    assert acts[1]["fill"]["opened_at"] != "2026-08-13T16:15:00Z" if "opened_at" in acts[1]["fill"] else True
    assert acts[0]["fill"]["fill_monotonic_ns"] < acts[1]["fill"]["fill_monotonic_ns"]
    assert acts[1]["fill"]["fill_monotonic_ns"] == acts[0]["fill"]["fill_monotonic_ns"] + 1
    assert eng.positions["H4"].side == "SHORT"


def test_kinematics_g_provisional_enters_without_closed_bar(cfg):
    c, _ = cfg
    eng = _engine(c)
    event = _start(
        eid="kin_g",
        episode="M15:prov:1",
        evaluation_mode="PROVISIONAL_INTRABAR",
        occurrence_ts=_fresh(2),
        decision_available_at=_fresh(2),
    )
    acts = eng.process_context_event(event)
    assert acts[0]["status"] == "ENTERED"
    assert eng.positions["M15"].lifecycle_episode_id == "M15:prov:1"
    assert all(
        row.get("evaluation_mode") != "CLOSED_BAR_CONTEXT_DECISION"
        for row in eng.books.read_all("signals")
    )


def test_kinematics_h_closed_bar_catchup_does_not_second_enter(cfg):
    c, _ = cfg
    eng = _engine(c)
    prov = _start(
        eid="kin_h_prov",
        episode="M15:prov:1",
        evaluation_mode="PROVISIONAL_INTRABAR",
        occurrence_ts="2026-08-13T16:15:00Z",
        decision_available_at=_fresh(10),
    )
    assert eng.process_context_event(prov)[0]["status"] == "ENTERED"
    closed = _start(
        eid="kin_h_closed",
        episode="M15:closed:2026-08-13T16:15:00Z:LONG",
        evaluation_mode="CLOSED_BAR_CONTEXT_DECISION",
        occurrence_ts="2026-08-13T16:15:00Z",
        decision_available_at=_fresh(5),
        mono=5_000_000,
    )
    acts = eng.process_context_event(closed)
    assert acts == []
    blocked = eng.books.read_all("blocked")
    assert blocked and blocked[-1]["reason"] == "ENTRY_BLOCKED_ACTIVE_POSITION"
    entry_fills = [f for f in eng.books.read_all("fills") if f.get("action") == "ENTRY"]
    assert len(entry_fills) == 1
    assert list(eng.positions) == ["M15"]


def test_i_h1_provisional_execution_remains_functional(cfg):
    c, _ = cfg
    eng = _engine(c)
    eng.update_bbo_from_market(
        best_bid=63280.0,
        best_ask=63281.25,
        receive_monotonic_ns=9_000_000,
        receive_timestamp=_fresh(1),
        book_update_id="h1_now",
    )
    event = _start(
        eid="h1_5",
        tf="H1",
        episode="H1:prov:5",
        occurrence_price=63286.53,
        bid=63285.0,
        ask=63287.0,
        evaluation_mode="PROVISIONAL_INTRABAR",
        extra={"new_context": "LONG_CONTEXT"},
    )
    acts = eng.process_context_event(event)
    assert acts[0]["status"] == "ENTERED"
    fill = acts[0]["fill"]
    assert fill["paper_fill_price"] == pytest.approx(63281.25)
    assert fill["paper_fill_price"] != pytest.approx(63286.53)
    assert fill["context_event_price"] == pytest.approx(63286.53)
    assert fill["entry_price_source"] == "execution_market_bbo"
    assert eng.positions["H1"].side == "LONG"


# --- LIVE1B producer → consumer intrabar kinematics (no injected START) ---

PREV_M15_CLOSE = 99.0
OCCURRENCE_PRICE = 99.5
BAR_OPEN_TS = "2026-08-13T16:15:00Z"
START_TS = "2026-08-13T16:17:00Z"
BAR_CLOSE_TS = "2026-08-13T16:30:00Z"
ENTRY_CLOCK = datetime(2026, 8, 13, 16, 17, 1, tzinfo=timezone.utc)
FLIP_CLOCK = datetime(2026, 8, 13, 16, 18, 1, tzinfo=timezone.utc)
END_CLOCK = datetime(2026, 8, 13, 17, 2, 1, tzinfo=timezone.utc)
END_TS = "2026-08-13T17:02:00Z"
END_BAR_OPEN_TS = "2026-08-13T17:00:00Z"
END_BAR_CLOSE_TS = "2026-08-13T17:15:00Z"
FLIP_TS = "2026-08-13T16:18:00Z"
FLIP_OCCURRENCE_PRICE = 98.2
EXECUTION_BID = 100.0
EXECUTION_ASK = 100.2
EXIT_BID = 101.0
EXIT_ASK = 101.2


def _freeze_entry_clock(monkeypatch, now: datetime) -> None:
    """Pin wall-clock used by journal ingest, freshness, and ENTRY stamps."""

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return now
            return now.astimezone(tz)

    for target in (
        "btc_ml.trading.intrabar_paper.engine.datetime",
        "btc_ml.trading.intrabar_paper.epoch.datetime",
        "btc_ml.trading.intrabar_paper.entry_eligibility.datetime",
        "btc_ml.live.intrabar.context_event_freshness.datetime",
        "btc_ml.live.intrabar.context_event_journal.datetime",
    ):
        monkeypatch.setattr(target, FrozenDateTime)


def _agg_trade(*, price: float, qty: float, ts: str, mono: int, tid: int, sell: bool = False) -> dict:
    return {
        "price": str(price),
        "quantity": str(qty),
        "quote_quantity": str(float(price) * float(qty)),
        "exchange_trade_timestamp": ts,
        "local_receive_timestamp": ts,
        "local_receive_monotonic_ns": mono,
        "aggregate_trade_id": tid,
        "buyer_is_market_maker": sell,
        "connection_session_id": "sess",
        "reconnect_generation": 1,
    }


def _prev_m15_geometry(*, close: float = PREV_M15_CLOSE) -> pd.DataFrame:
    spread = 1.6
    return pd.DataFrame(
        [
            {
                "timestamp": "2026-08-13T16:00:00Z",
                "open": close - 0.2,
                "high": close + spread / 2.0,
                "low": close - spread / 2.0,
                "close": close,
                "volume": 10.0,
                "delta": 1.0,
                "spread": spread,
                "timeframe": "M15",
                "estimated_local_volume": 10.0,
            }
        ]
    )


def _open_m15_active_trades() -> list[dict]:
    """Intrabar prints that make existing classifiers return ACTIVE before 16:30.

    Previous M15 close is 99.0. The 16:17 last print is 99.5 so follow-through
    vs prev_close is YES; mixed buy/sell keeps delta small enough for
    localized_absorption → ACCEPTANCE_HIGHER / CONFIRMED / ACTIVE.
    """
    return [
        _agg_trade(price=99.10, qty=2.0, ts="2026-08-13T16:15:01Z", mono=2_100_000, tid=1, sell=False),
        _agg_trade(price=98.00, qty=2.0, ts="2026-08-13T16:16:00Z", mono=2_200_000, tid=2, sell=True),
        _agg_trade(price=99.60, qty=2.0, ts="2026-08-13T16:16:30Z", mono=2_300_000, tid=3, sell=False),
        _agg_trade(price=OCCURRENCE_PRICE, qty=2.0, ts=START_TS, mono=2_400_000, tid=4, sell=True),
    ]


def _cognition_engine(
    repo: Path,
    *,
    localization_history: pd.DataFrame | None = None,
) -> IntrabarCognitionEngine:
    journal_root = repo / "data" / "cognition" / "intrabar_context_events"
    return IntrabarCognitionEngine(
        context_journal=ContextEventJournal(journal_root),
        localization_history=localization_history,
    )


def _volume_baseline() -> pd.DataFrame:
    """Causal localization history so relative_volume can reach STOPPING_VOLUME.

    Empty history makes relative_volume NaN; STOPPING (needed for confirmed
    SHORT / FLIP) never fires. This is the same class of fixture as prev_close.
    """
    return pd.DataFrame(
        [
            {
                "timestamp": f"2026-08-13T15:{i:02d}:00Z",
                "estimated_local_volume": 5.0,
                "spread": 1.6,
            }
            for i in range(20)
        ]
    )


def _m15(events: list[dict], etype: str) -> list[dict]:
    return [e for e in events if e.get("event_type") == etype and e.get("timeframe") == "M15"]


def _expected_bar_close(bar) -> pd.Timestamp:
    return bar.bar_open_timestamp + pd.Timedelta(seconds=TF_SECONDS[bar.timeframe])


def test_live1b_provisional_start_executes_intrabar_before_current_bar_close(cfg, monkeypatch):
    """aggTrade on an OPEN M15 → PROVISIONAL START → poll_context_journal → ENTRY < 16:30."""
    _freeze_entry_clock(monkeypatch, ENTRY_CLOCK)
    c, repo = cfg
    cog = _cognition_engine(repo)
    cog.geometry_by_tf["M15"] = _prev_m15_geometry()

    emitted = []
    for trade in _open_m15_active_trades():
        emitted.extend(cog.on_agg_trade(trade))

    bar = cog.bars.bars["M15"]
    bar_close = bar.bar_open_timestamp + pd.Timedelta(seconds=TF_SECONDS["M15"])
    assert bar.is_closed is False
    assert bar.bar_open_timestamp == pd.Timestamp(BAR_OPEN_TS)
    assert bar_close == pd.Timestamp(BAR_CLOSE_TS)

    synth = cog.last_eval["M15"]["synthesis"]
    assert synth["follow_through"] == "YES"
    assert synth["episode_status"] == "CONFIRMED"
    assert synth["context_status"] == "ACTIVE"
    assert synth["is_closed"] is False

    starts = [e for e in emitted if e.get("event_type") == "CONTEXT_START" and e.get("timeframe") == "M15"]
    assert len(starts) == 1
    start = starts[0]
    assert start["evaluation_mode"] == "PROVISIONAL_INTRABAR"
    assert start["event_type"] == "CONTEXT_START"
    assert start["event_timestamp"] == START_TS
    assert start["event_timestamp"] != BAR_CLOSE_TS
    start_ts = pd.Timestamp(start["event_timestamp"])
    assert start_ts < bar_close
    assert start.get("materialization_source") not in {
        "closed_bar_context_decision",
        "CLOSED_BAR_CONTEXT_DECISION",
    }
    assert start.get("evaluation_mode") != "CLOSED_BAR_CONTEXT_DECISION"
    assert start.get("context_occurrence_timestamp") == START_TS
    assert start.get("decision_available_at") == START_TS
    # Provisional producer stamps ingested_at, not a closed-bar materialized_timestamp.
    assert start.get("materialized_timestamp") in (None, "")
    assert start.get("ingested_at")
    assert float(start["context_event_price"]) == pytest.approx(OCCURRENCE_PRICE)

    journal_path = c.context_journal_root / "events.jsonl"
    raw_events = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(e.get("context_event_id") == start["context_event_id"] for e in raw_events)
    assert all(e.get("evaluation_mode") != "CLOSED_BAR_CONTEXT_DECISION" for e in raw_events)

    paper = _engine(c)
    paper.update_bbo_from_market(
        best_bid=EXECUTION_BID,
        best_ask=EXECUTION_ASK,
        receive_monotonic_ns=2_350_000,
        receive_timestamp=START_TS,
        book_update_id="exec_mkt",
    )
    acts = paper.poll_context_journal()
    entered = [a for a in acts if a.get("status") == "ENTERED"]
    assert len(entered) == 1
    fill = entered[0]["fill"]
    pos = paper.books.read_all("positions")[-1]

    exec_ts = pd.Timestamp(fill["execution_timestamp"])
    assert exec_ts < bar_close
    assert str(fill["execution_timestamp"]) != BAR_CLOSE_TS
    assert pos["opened_at"] == fill["execution_timestamp"]
    assert pos["opened_at"] != start["context_occurrence_timestamp"]
    assert fill["paper_fill_price"] == pytest.approx(EXECUTION_ASK)
    assert fill["execution_price"] == pytest.approx(EXECUTION_ASK)
    assert fill["entry_price_source"] == "execution_market_bbo"
    assert fill["paper_fill_price"] != pytest.approx(OCCURRENCE_PRICE)
    assert fill["context_event_price"] == pytest.approx(OCCURRENCE_PRICE)

    # Current M15 is still the open 16:15 bar after ENTRY.
    assert cog.bars.bars["M15"].is_closed is False
    assert cog.bars.bars["M15"].bar_open_timestamp == pd.Timestamp(BAR_OPEN_TS)


def test_live1b_provisional_start_requires_previous_closed_bar(cfg, monkeypatch):
    """Same open M15 / 16:17 aggTrade, but no previous closed geometry → no START, no ENTRY."""
    _freeze_entry_clock(monkeypatch, ENTRY_CLOCK)
    c, repo = cfg
    cog = _cognition_engine(repo)
    assert len(cog.geometry_by_tf["M15"]) == 0

    emitted = []
    for trade in _open_m15_active_trades():
        emitted.extend(cog.on_agg_trade(trade))

    bar = cog.bars.bars["M15"]
    assert bar.is_closed is False
    assert bar.bar_open_timestamp == pd.Timestamp(BAR_OPEN_TS)
    assert cog.last_eval["M15"]["prev_close"] is None
    assert cog.last_eval["M15"]["synthesis"]["context_status"] != "ACTIVE"
    assert cog.event_counts["CONTEXT_START"] == 0
    assert not any(e.get("event_type") == "CONTEXT_START" for e in emitted)

    journal_path = c.context_journal_root / "events.jsonl"
    if journal_path.exists():
        lines = [ln for ln in journal_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines == []

    paper = _engine(c)
    paper.update_bbo_from_market(
        best_bid=EXECUTION_BID,
        best_ask=EXECUTION_ASK,
        receive_monotonic_ns=2_350_000,
        receive_timestamp=START_TS,
        book_update_id="exec_mkt",
    )
    acts = paper.poll_context_journal()
    assert [a.get("status") for a in acts] == []
    assert paper.positions == {}
    assert paper.books.read_all("fills") == []


def test_live1b_provisional_end_not_emitted_before_min_hold_same_open_bar(cfg, monkeypatch):
    """Same-candle 16:18 neutralizing prints do not END — min-hold, not candle-close wait.

    This is case A: cognition does not produce CONTEXT_END intrabar one minute
    after START because MIN_ACTIVE_CONTEXT_HOLD_BARS=3 (45 minutes of M15
    event time). The 16:15 bar stays open; the manager is never given an END.
    """
    _freeze_entry_clock(monkeypatch, ENTRY_CLOCK)
    c, repo = cfg
    cog = _cognition_engine(repo)
    cog.geometry_by_tf["M15"] = _prev_m15_geometry()
    for trade in _open_m15_active_trades():
        cog.on_agg_trade(trade)
    assert cog.event_counts["CONTEXT_START"] == 1

    neutralizing = [
        _agg_trade(price=99.50, qty=2.0, ts="2026-08-13T16:18:00Z", mono=2_500_000, tid=5, sell=True),
        _agg_trade(price=99.50, qty=2.0, ts="2026-08-13T16:18:30Z", mono=2_600_000, tid=6, sell=False),
    ]
    emitted_end = []
    for trade in neutralizing:
        emitted_end.extend(cog.on_agg_trade(trade))

    bar = cog.bars.bars["M15"]
    assert bar.is_closed is False
    assert bar.bar_open_timestamp == pd.Timestamp(BAR_OPEN_TS)
    assert _expected_bar_close(bar) == pd.Timestamp(BAR_CLOSE_TS)
    assert cog.event_counts["CONTEXT_END"] == 0
    assert cog.event_counts["CONTEXT_FLIP"] == 0
    assert not _m15(emitted_end, "CONTEXT_END")
    assert cog.last_eval["M15"]["lifecycle"]["active_market_context"] == "LONG_CONTEXT"
    assert cog.last_eval["M15"]["lifecycle"]["lifecycle_state"] in {"ACTIVE", "CHALLENGED"}


def test_live1b_provisional_end_executes_intrabar_before_current_bar_close(cfg, monkeypatch):
    """After min-hold, CONTEXT_END on the still-open 17:00 M15 → poll → EXIT < 17:15.

    START is at 16:17 on the 16:15 bar. END cannot legally fire at 16:18
    (min-hold). The first legal END is 17:02, during the open 17:00–17:15 bar.
    That is still provisional/intrabar: no current-candle close, no bridge.
    """
    _freeze_entry_clock(monkeypatch, ENTRY_CLOCK)
    c, repo = cfg
    cog = _cognition_engine(repo)
    cog.geometry_by_tf["M15"] = _prev_m15_geometry()
    for trade in _open_m15_active_trades():
        cog.on_agg_trade(trade)
    starts = _m15([cog.last_context_event["M15"]], "CONTEXT_START")
    assert starts and starts[0]["evaluation_mode"] == "PROVISIONAL_INTRABAR"
    assert starts[0]["event_timestamp"] == START_TS

    paper = _engine(c)
    paper.update_bbo_from_market(
        best_bid=EXECUTION_BID,
        best_ask=EXECUTION_ASK,
        receive_monotonic_ns=2_350_000,
        receive_timestamp=START_TS,
        book_update_id="exec_mkt_entry",
    )
    entry_acts = paper.poll_context_journal()
    assert [a.get("status") for a in entry_acts] == ["ENTERED"]
    assert pd.Timestamp(entry_acts[0]["fill"]["execution_timestamp"]) < pd.Timestamp(BAR_CLOSE_TS)

    _freeze_entry_clock(monkeypatch, END_CLOCK)
    hold_and_end = [
        _agg_trade(price=99.50, qty=1.0, ts="2026-08-13T16:30:01Z", mono=3_000_000, tid=10, sell=False),
        _agg_trade(price=99.50, qty=1.0, ts="2026-08-13T16:45:01Z", mono=4_000_000, tid=11, sell=False),
        _agg_trade(price=99.50, qty=1.0, ts="2026-08-13T17:00:01Z", mono=5_000_000, tid=12, sell=False),
        _agg_trade(price=OCCURRENCE_PRICE, qty=2.0, ts=END_TS, mono=6_000_000, tid=13, sell=True),
    ]
    emitted = []
    for trade in hold_and_end:
        emitted.extend(cog.on_agg_trade(trade))

    bar = cog.bars.bars["M15"]
    bar_close = _expected_bar_close(bar)
    assert bar.is_closed is False
    assert bar.bar_open_timestamp == pd.Timestamp(END_BAR_OPEN_TS)
    assert bar_close == pd.Timestamp(END_BAR_CLOSE_TS)

    ends = _m15(emitted, "CONTEXT_END")
    assert len(ends) == 1
    end = ends[0]
    assert end["evaluation_mode"] == "PROVISIONAL_INTRABAR"
    assert end["event_timestamp"] == END_TS
    assert end["event_timestamp"] != END_BAR_CLOSE_TS
    assert pd.Timestamp(end["event_timestamp"]) < bar_close
    assert end.get("materialization_source") not in {
        "closed_bar_context_decision",
        "CLOSED_BAR_CONTEXT_DECISION",
    }
    assert float(end["context_event_price"]) == pytest.approx(OCCURRENCE_PRICE)

    paper.update_bbo_from_market(
        best_bid=EXIT_BID,
        best_ask=EXIT_ASK,
        receive_monotonic_ns=5_900_000,
        receive_timestamp=END_TS,
        book_update_id="exec_mkt_exit",
    )
    exit_acts = paper.poll_context_journal()
    exited = [a for a in exit_acts if a.get("status") == "EXITED"]
    assert len(exited) == 1
    fill = exited[0]["fill"]
    closed_pos = [p for p in paper.books.read_all("positions") if p.get("status") == "CLOSED"][-1]
    exec_ts = pd.Timestamp(fill["execution_timestamp"])
    assert exec_ts < bar_close
    assert str(fill["execution_timestamp"]) != END_BAR_CLOSE_TS
    assert closed_pos["closed_at"] == fill["execution_timestamp"]
    assert closed_pos["closed_at"] != end.get("context_occurrence_timestamp")
    assert fill["paper_fill_price"] == pytest.approx(EXIT_BID)
    assert fill["execution_price"] == pytest.approx(EXIT_BID)
    assert fill["paper_fill_price"] != pytest.approx(OCCURRENCE_PRICE)
    assert fill["context_event_price"] == pytest.approx(OCCURRENCE_PRICE)
    assert paper.positions == {}
    assert cog.bars.bars["M15"].is_closed is False


def test_live1b_provisional_flip_executes_intrabar_before_current_bar_close(cfg, monkeypatch):
    """Open M15: LONG START at 16:17 → SHORT FLIP at 16:18 → EXIT then ENTRY, both < 16:30."""
    _freeze_entry_clock(monkeypatch, ENTRY_CLOCK)
    c, repo = cfg
    cog = _cognition_engine(repo, localization_history=_volume_baseline())
    cog.geometry_by_tf["M15"] = _prev_m15_geometry()
    for trade in _open_m15_active_trades():
        cog.on_agg_trade(trade)
    assert cog.event_counts["CONTEXT_START"] == 1
    assert cog.bars.bars["M15"].is_closed is False

    paper = _engine(c)
    paper.update_bbo_from_market(
        best_bid=EXECUTION_BID,
        best_ask=EXECUTION_ASK,
        receive_monotonic_ns=2_350_000,
        receive_timestamp=START_TS,
        book_update_id="exec_mkt_entry",
    )
    entry_acts = paper.poll_context_journal()
    assert [a.get("status") for a in entry_acts] == ["ENTERED"]
    assert paper.positions["M15"].side == "LONG"
    assert pd.Timestamp(entry_acts[0]["fill"]["execution_timestamp"]) < pd.Timestamp(BAR_CLOSE_TS)

    _freeze_entry_clock(monkeypatch, FLIP_CLOCK)
    flip_prints = [
        _agg_trade(price=100.80, qty=2.0, ts="2026-08-13T16:17:20Z", mono=2_450_000, tid=5, sell=False),
        _agg_trade(price=FLIP_OCCURRENCE_PRICE, qty=4.0, ts=FLIP_TS, mono=2_500_000, tid=6, sell=True),
    ]
    emitted = []
    for trade in flip_prints:
        emitted.extend(cog.on_agg_trade(trade))

    bar = cog.bars.bars["M15"]
    bar_close = _expected_bar_close(bar)
    assert bar.is_closed is False
    assert bar.bar_open_timestamp == pd.Timestamp(BAR_OPEN_TS)
    assert bar_close == pd.Timestamp(BAR_CLOSE_TS)

    flips = _m15(emitted, "CONTEXT_FLIP")
    assert len(flips) == 1
    flip = flips[0]
    assert flip["evaluation_mode"] == "PROVISIONAL_INTRABAR"
    assert flip["event_timestamp"] == FLIP_TS
    assert flip["previous_context"] == "LONG_CONTEXT"
    assert flip["new_context"] == "SHORT_CONTEXT"
    assert pd.Timestamp(flip["event_timestamp"]) < bar_close
    assert flip["event_timestamp"] != BAR_CLOSE_TS
    assert flip.get("materialization_source") not in {
        "closed_bar_context_decision",
        "CLOSED_BAR_CONTEXT_DECISION",
    }
    assert float(flip["context_event_price"]) == pytest.approx(FLIP_OCCURRENCE_PRICE)

    paper.update_bbo_from_market(
        best_bid=EXIT_BID,
        best_ask=EXIT_ASK,
        receive_monotonic_ns=2_490_000,
        receive_timestamp=FLIP_TS,
        book_update_id="exec_mkt_flip",
    )
    flip_acts = paper.poll_context_journal()
    assert [a.get("status") for a in flip_acts] == ["EXITED", "ENTERED"]
    exit_fill = flip_acts[0]["fill"]
    entry_fill = flip_acts[1]["fill"]
    assert pd.Timestamp(exit_fill["execution_timestamp"]) < bar_close
    assert pd.Timestamp(entry_fill["execution_timestamp"]) < bar_close
    assert exit_fill["fill_monotonic_ns"] < entry_fill["fill_monotonic_ns"]
    # LONG EXIT = bid; SHORT ENTRY = bid
    assert exit_fill["paper_fill_price"] == pytest.approx(EXIT_BID)
    assert exit_fill["execution_price"] == pytest.approx(EXIT_BID)
    assert entry_fill["paper_fill_price"] == pytest.approx(EXIT_BID)
    assert entry_fill["execution_price"] == pytest.approx(EXIT_BID)
    assert exit_fill["paper_fill_price"] != pytest.approx(FLIP_OCCURRENCE_PRICE)
    assert entry_fill["paper_fill_price"] != pytest.approx(FLIP_OCCURRENCE_PRICE)
    assert exit_fill["context_event_price"] == pytest.approx(FLIP_OCCURRENCE_PRICE)
    assert entry_fill["entry_price_source"] == "execution_market_bbo"
    closed_pos = [p for p in paper.books.read_all("positions") if p.get("status") == "CLOSED"][-1]
    assert closed_pos["closed_at"] == exit_fill["execution_timestamp"]
    assert closed_pos["closed_at"] != flip.get("context_occurrence_timestamp")
    assert paper.positions["M15"].side == "SHORT"
    assert cog.bars.bars["M15"].is_closed is False
    assert cog.bars.bars["M15"].bar_open_timestamp == pd.Timestamp(BAR_OPEN_TS)


def test_live1b_completed_episode_is_dead_for_new_episode(cfg, monkeypatch):
    """Completed episode A has no trading effect on independent episode C.

    Runtime path: events.jsonl → poll_context_journal() → ENTRY/EXIT.
    """
    c, _ = cfg
    timeline: list[str] = []

    def _row(time: str, episode: str, event: str, execution: str, price, position: str, result: str) -> None:
        timeline.append(
            f"{time} | {episode} | {event:5} | {execution} | {price} | {position} | {result}"
        )

    def _poll(eng, *, bid: float, ask: float, mono: int, ts: str, clock: datetime):
        _freeze_entry_clock(monkeypatch, clock)
        eng.update_bbo_from_market(
            best_bid=bid,
            best_ask=ask,
            receive_monotonic_ns=mono,
            receive_timestamp=ts,
            book_update_id=f"bbo_{mono}",
        )
        return eng.poll_context_journal()

    _freeze_entry_clock(monkeypatch, datetime(2026, 8, 13, 10, 2, tzinfo=timezone.utc))
    eng = _engine(c)

    start_a = _start(
        eid="ctx_A_start",
        episode="A",
        mono=2_000_000,
        occurrence_ts="2026-08-13T10:01:00Z",
        decision_available_at="2026-08-13T10:01:00Z",
        occurrence_price=100.0,
        bid=100.8,
        ask=101.0,
        evaluation_mode="PROVISIONAL_INTRABAR",
        extra={
            "materialized_timestamp": "2026-08-13T10:02:00Z",
            "ingested_at": "2026-08-13T10:02:00Z",
        },
    )
    _journal_append(c, start_a)
    acts = _poll(
        eng,
        bid=100.8,
        ask=101.0,
        mono=1_999_000,
        ts="2026-08-13T10:02:00Z",
        clock=datetime(2026, 8, 13, 10, 2, tzinfo=timezone.utc),
    )
    assert [a.get("status") for a in acts] == ["ENTERED"]
    fill_a_in = acts[0]["fill"]
    pos_a = eng.books.read_all("positions")[-1]
    assert pos_a["lifecycle_episode_id"] == "A"
    assert fill_a_in["paper_fill_price"] == pytest.approx(101.0)
    assert fill_a_in["execution_price"] == pytest.approx(101.0)
    assert fill_a_in["context_event_price"] == pytest.approx(100.0)
    assert fill_a_in["paper_fill_price"] != pytest.approx(100.0)
    assert pos_a["opened_at"] == fill_a_in["execution_timestamp"]
    assert fill_a_in["context_occurrence_timestamp"] == "2026-08-13T10:01:00Z"
    _row("10:01", "A", "START", fill_a_in["execution_timestamp"], fill_a_in["paper_fill_price"], "LONG", "ENTERED")

    end_a = _end(
        eid="ctx_A_end",
        episode="A",
        mono=3_000_000,
        occurrence_ts="2026-08-13T10:10:00Z",
        occurrence_price=100.0,
        bid=98.8,
        ask=99.0,
        extra={
            "materialized_timestamp": "2026-08-13T10:10:00Z",
            "ingested_at": "2026-08-13T10:10:00Z",
        },
    )
    _journal_append(c, end_a)
    acts = _poll(
        eng,
        bid=99.0,
        ask=99.2,
        mono=2_999_000,
        ts="2026-08-13T10:10:00Z",
        clock=datetime(2026, 8, 13, 10, 10, tzinfo=timezone.utc),
    )
    assert [a.get("status") for a in acts] == ["EXITED"]
    fill_a_out = acts[0]["fill"]
    closed_a = [p for p in eng.books.read_all("positions") if p.get("status") == "CLOSED"][-1]
    assert closed_a["lifecycle_episode_id"] == "A"
    assert closed_a["closed_at"] == fill_a_out["execution_timestamp"]
    assert fill_a_out["paper_fill_price"] == pytest.approx(99.0)
    assert fill_a_out["execution_price"] == pytest.approx(99.0)
    assert "M15" not in eng.positions
    _row("10:10", "A", "END", fill_a_out["execution_timestamp"], fill_a_out["paper_fill_price"], "FLAT", "EXITED")

    retry_a = _start(
        eid="ctx_A_restart",
        episode="A",
        mono=3_500_000,
        occurrence_ts="2026-08-13T10:11:00Z",
        decision_available_at="2026-08-13T10:11:00Z",
        occurrence_price=100.0,
        bid=100.8,
        ask=101.0,
        evaluation_mode="PROVISIONAL_INTRABAR",
        extra={
            "materialized_timestamp": "2026-08-13T10:11:00Z",
            "ingested_at": "2026-08-13T10:11:00Z",
        },
    )
    _journal_append(c, retry_a)
    acts = _poll(
        eng,
        bid=100.8,
        ask=101.0,
        mono=3_499_000,
        ts="2026-08-13T10:11:00Z",
        clock=datetime(2026, 8, 13, 10, 11, tzinfo=timezone.utc),
    )
    assert acts == []
    assert "M15" not in eng.positions
    blocked = eng.books.read_all("blocked")
    assert blocked and blocked[-1]["reason"] == "ENTRY_BLOCKED_EPISODE_ALREADY_TRADED"
    assert blocked[-1]["context_event_id"] == "ctx_A_restart"
    assert "A" in eng.traded_episodes
    _row("10:11", "A", "START", "-", "-", "FLAT", "ENTRY_BLOCKED_EPISODE_ALREADY_TRADED")

    start_c = _start(
        eid="ctx_C_start",
        episode="C",
        mono=4_000_000,
        occurrence_ts="2026-08-13T11:00:00Z",
        decision_available_at="2026-08-13T11:00:00Z",
        occurrence_price=200.0,
        bid=200.8,
        ask=201.0,
        evaluation_mode="PROVISIONAL_INTRABAR",
        extra={
            "materialized_timestamp": "2026-08-13T11:01:00Z",
            "ingested_at": "2026-08-13T11:01:00Z",
        },
    )
    _journal_append(c, start_c)
    acts = _poll(
        eng,
        bid=200.8,
        ask=201.0,
        mono=3_999_000,
        ts="2026-08-13T11:01:00Z",
        clock=datetime(2026, 8, 13, 11, 1, tzinfo=timezone.utc),
    )
    assert [a.get("status") for a in acts] == ["ENTERED"], (
        "stale completed A must not make fresh C untradable: "
        f"acts={acts} blocked={eng.books.read_all('blocked')[-3:]}"
    )
    fill_c_in = acts[0]["fill"]
    pos_c = eng.positions["M15"]
    assert pos_c.lifecycle_episode_id == "C"
    assert fill_c_in["decision_available_at"] == "2026-08-13T11:00:00Z"
    assert fill_c_in["context_occurrence_timestamp"] == "2026-08-13T11:00:00Z"
    assert fill_c_in["context_occurrence_timestamp"] != "2026-08-13T10:01:00Z"
    assert fill_c_in["paper_fill_price"] == pytest.approx(201.0)
    assert fill_c_in["execution_price"] == pytest.approx(201.0)
    assert fill_c_in["context_event_price"] == pytest.approx(200.0)
    assert fill_c_in["paper_fill_price"] != pytest.approx(100.0)
    assert fill_c_in["paper_fill_price"] != pytest.approx(101.0)
    assert fill_c_in["paper_fill_price"] != pytest.approx(200.0)
    assert "A" in eng.traded_episodes and "C" in eng.traded_episodes
    _row("11:00", "C", "START", fill_c_in["execution_timestamp"], fill_c_in["paper_fill_price"], "LONG", "ENTERED")

    delayed_a_start = _start(
        eid="ctx_A_delayed_start",
        episode="A",
        mono=5_000_000,
        occurrence_ts="2026-08-13T10:01:00Z",
        decision_available_at="2026-08-13T10:01:00Z",
        occurrence_price=100.0,
        bid=100.8,
        ask=101.0,
        evaluation_mode="CLOSED_BAR_CONTEXT_DECISION",
        extra={
            "delivery_mode": "RECOVERY",
            "restart_backfill": True,
            "materialization_class": "RESTART_BACKFILL",
            "materialized_timestamp": "2026-08-13T11:02:00Z",
            "ingested_at": "2026-08-13T11:02:00Z",
        },
    )
    _journal_append(c, delayed_a_start)
    delayed_a_end = _end(
        eid="ctx_A_delayed_end",
        episode="A",
        mono=5_100_000,
        occurrence_ts="2026-08-13T10:10:00Z",
        occurrence_price=100.0,
        bid=98.8,
        ask=99.0,
        extra={
            "delivery_mode": "RECOVERY",
            "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
            "restart_backfill": True,
            "materialization_class": "RESTART_BACKFILL",
            "materialized_timestamp": "2026-08-13T11:02:00Z",
            "ingested_at": "2026-08-13T11:02:00Z",
        },
    )
    _journal_append(c, delayed_a_end)
    c_before = dict(eng.positions["M15"].__dict__)
    acts_delayed = _poll(
        eng,
        bid=200.8,
        ask=201.0,
        mono=5_050_000,
        ts="2026-08-13T11:02:00Z",
        clock=datetime(2026, 8, 13, 11, 2, tzinfo=timezone.utc),
    )
    delayed_statuses = [a.get("status") for a in acts_delayed]
    assert "ENTERED" not in delayed_statuses
    assert eng.positions["M15"].lifecycle_episode_id == "C"
    assert eng.positions["M15"].side == "LONG"
    assert eng.positions["M15"].position_id == c_before["position_id"]
    assert "EXITED" not in delayed_statuses, (
        "delayed END(A) closed position C; "
        f"acts={acts_delayed} pos={eng.positions.get('M15')}"
    )
    blocked_reasons = {row.get("reason") for row in eng.books.read_all("blocked")}
    assert "SAME_CONTEXT_CONTINUATION" not in blocked_reasons
    _row("11:02", "A", "DELAY", "-", "-", "LONG/C", ",".join(delayed_statuses) or "NO_TRADE")

    end_c = _end(
        eid="ctx_C_end",
        episode="C",
        mono=6_000_000,
        occurrence_ts="2026-08-13T11:10:00Z",
        occurrence_price=200.0,
        bid=197.8,
        ask=198.0,
        extra={
            "materialized_timestamp": "2026-08-13T11:10:00Z",
            "ingested_at": "2026-08-13T11:10:00Z",
        },
    )
    _journal_append(c, end_c)
    acts = _poll(
        eng,
        bid=198.0,
        ask=198.2,
        mono=5_999_000,
        ts="2026-08-13T11:10:00Z",
        clock=datetime(2026, 8, 13, 11, 10, tzinfo=timezone.utc),
    )
    assert [a.get("status") for a in acts] == ["EXITED"]
    fill_c_out = acts[0]["fill"]
    closed_c = [
        p
        for p in eng.books.read_all("positions")
        if p.get("status") == "CLOSED" and p.get("lifecycle_episode_id") == "C"
    ][-1]
    assert closed_c["closed_at"] == fill_c_out["execution_timestamp"]
    assert fill_c_out["paper_fill_price"] == pytest.approx(198.0)
    assert fill_c_out["paper_fill_price"] != pytest.approx(100.0)
    assert fill_c_out["paper_fill_price"] != pytest.approx(101.0)
    assert fill_c_out["paper_fill_price"] != pytest.approx(99.0)
    assert fill_c_out["context_event_price"] == pytest.approx(200.0)
    assert "M15" not in eng.positions
    _row("11:10", "C", "END", fill_c_out["execution_timestamp"], fill_c_out["paper_fill_price"], "FLAT", "EXITED")

    print("time | episode | event | execution | price | position | result")
    print("\n".join(timeline))
    print(
        "A traded: YES\n"
        "A closed: YES\n"
        "C traded: YES\n"
        "C closed: YES\n"
        "C reused A: NO\n"
        "C freshness based on A: NO\n"
        "C fill based on A: NO\n"
        "A delayed event affected C: NO"
    )


def _poll_journal(eng, monkeypatch, *, bid: float, ask: float, mono: int, ts: str, clock: datetime):
    _freeze_entry_clock(monkeypatch, clock)
    eng.update_bbo_from_market(
        best_bid=bid,
        best_ask=ask,
        receive_monotonic_ns=mono,
        receive_timestamp=ts,
        book_update_id=f"bbo_{mono}",
    )
    return eng.poll_context_journal()


def _action_episode(action: dict) -> str | None:
    """Episode id on the trade/position payload; fills do not carry it."""
    for key in ("position", "trade"):
        row = action.get(key) or {}
        ep = row.get("lifecycle_episode_id") or row.get("episode_id")
        if ep:
            return str(ep)
    fill = action.get("fill") or {}
    ep = fill.get("lifecycle_episode_id") or fill.get("episode_id")
    return str(ep) if ep else None


@pytest.mark.parametrize("delayed_kind", ["CONTEXT_END", "CONTEXT_FLIP"])
def test_live1b_delayed_dead_episode_does_not_mutate_active_episode(cfg, monkeypatch, delayed_kind):
    """Completed episode A is dead: delayed END(A) / FLIP(A) must not mutate live C.

    Runtime path: events.jsonl → poll_context_journal() → ENTRY/EXIT.
    """
    c, _ = cfg
    timeline: list[str] = []

    def _row(time: str, episode: str, event: str, execution: str, price, position: str, result: str) -> None:
        timeline.append(
            f"{time} | {episode} | {event:5} | {execution} | {price} | {position} | {result}"
        )

    _freeze_entry_clock(monkeypatch, datetime(2026, 8, 13, 10, 2, tzinfo=timezone.utc))
    eng = _engine(c)

    start_a = _start(
        eid="iso_A_start",
        episode="A",
        mono=2_000_000,
        occurrence_ts="2026-08-13T10:01:00Z",
        decision_available_at="2026-08-13T10:01:00Z",
        occurrence_price=100.0,
        bid=100.8,
        ask=101.0,
        evaluation_mode="PROVISIONAL_INTRABAR",
        extra={
            "materialized_timestamp": "2026-08-13T10:02:00Z",
            "ingested_at": "2026-08-13T10:02:00Z",
        },
    )
    _journal_append(c, start_a)
    acts = _poll_journal(
        eng,
        monkeypatch,
        bid=100.8,
        ask=101.0,
        mono=1_999_000,
        ts="2026-08-13T10:02:00Z",
        clock=datetime(2026, 8, 13, 10, 2, tzinfo=timezone.utc),
    )
    assert [a.get("status") for a in acts] == ["ENTERED"]
    assert acts[0]["position"]["lifecycle_episode_id"] == "A"
    assert eng.positions["M15"].lifecycle_episode_id == "A"
    _row("10:01", "A", "START", acts[0]["fill"]["execution_timestamp"], acts[0]["fill"]["paper_fill_price"], "LONG", "ENTERED")

    end_a = _end(
        eid="iso_A_end",
        episode="A",
        mono=3_000_000,
        occurrence_ts="2026-08-13T10:10:00Z",
        occurrence_price=100.0,
        bid=98.8,
        ask=99.0,
        extra={
            "materialized_timestamp": "2026-08-13T10:10:00Z",
            "ingested_at": "2026-08-13T10:10:00Z",
        },
    )
    _journal_append(c, end_a)
    acts = _poll_journal(
        eng,
        monkeypatch,
        bid=99.0,
        ask=99.2,
        mono=2_999_000,
        ts="2026-08-13T10:10:00Z",
        clock=datetime(2026, 8, 13, 10, 10, tzinfo=timezone.utc),
    )
    assert [a.get("status") for a in acts] == ["EXITED"]
    assert acts[0]["trade"]["lifecycle_episode_id"] == "A"
    assert "M15" not in eng.positions
    _row("10:10", "A", "END", acts[0]["fill"]["execution_timestamp"], acts[0]["fill"]["paper_fill_price"], "FLAT", "EXITED")

    start_c = _start(
        eid="iso_C_start",
        episode="C",
        mono=4_000_000,
        occurrence_ts="2026-08-13T11:00:00Z",
        decision_available_at="2026-08-13T11:00:00Z",
        occurrence_price=200.0,
        bid=200.8,
        ask=201.0,
        evaluation_mode="PROVISIONAL_INTRABAR",
        extra={
            "materialized_timestamp": "2026-08-13T11:01:00Z",
            "ingested_at": "2026-08-13T11:01:00Z",
        },
    )
    _journal_append(c, start_c)
    acts = _poll_journal(
        eng,
        monkeypatch,
        bid=200.8,
        ask=201.0,
        mono=3_999_000,
        ts="2026-08-13T11:01:00Z",
        clock=datetime(2026, 8, 13, 11, 1, tzinfo=timezone.utc),
    )
    assert [a.get("status") for a in acts] == ["ENTERED"]
    fill_c_in = acts[0]["fill"]
    assert acts[0]["position"]["lifecycle_episode_id"] == "C"
    assert eng.positions["M15"].lifecycle_episode_id == "C"
    assert eng.positions["M15"].side == "LONG"
    c_position_id = eng.positions["M15"].position_id
    _row("11:00", "C", "START", fill_c_in["execution_timestamp"], fill_c_in["paper_fill_price"], "LONG", "ENTERED")

    delayed_extra = {
        "delivery_mode": "RECOVERY",
        "restart_backfill": True,
        "materialization_class": "RESTART_BACKFILL",
        "materialized_timestamp": "2026-08-13T11:02:00Z",
        "ingested_at": "2026-08-13T11:02:00Z",
        "evaluation_mode": "CLOSED_BAR_CONTEXT_DECISION",
    }
    if delayed_kind == "CONTEXT_END":
        delayed = _end(
            eid="iso_A_delayed_end",
            episode="A",
            mono=5_000_000,
            occurrence_ts="2026-08-13T10:10:00Z",
            occurrence_price=100.0,
            bid=98.8,
            ask=99.0,
            extra=delayed_extra,
        )
        delayed_label = "END"
    else:
        delayed = _flip(
            eid="iso_A_delayed_flip",
            episode="A",
            mono=5_000_000,
            occurrence_ts="2026-08-13T10:10:00Z",
            occurrence_price=100.0,
            bid=200.8,
            ask=201.0,
            extra=delayed_extra,
        )
        delayed_label = "FLIP"
    _journal_append(c, delayed)
    acts_delayed = _poll_journal(
        eng,
        monkeypatch,
        bid=200.8,
        ask=201.0,
        mono=4_999_000,
        ts="2026-08-13T11:02:00Z",
        clock=datetime(2026, 8, 13, 11, 2, tzinfo=timezone.utc),
    )
    delayed_statuses = [a.get("status") for a in acts_delayed]
    delayed_a_exits = [
        a for a in acts_delayed if a.get("status") == "EXITED" and _action_episode(a) == "A"
    ]
    delayed_a_entries = [
        a for a in acts_delayed if a.get("status") == "ENTERED" and _action_episode(a) == "A"
    ]
    pos_after = eng.positions.get("M15")
    _row(
        "11:02",
        "A",
        delayed_label,
        "-",
        "-",
        f"{getattr(pos_after, 'side', 'FLAT')}/{getattr(pos_after, 'lifecycle_episode_id', '-')}",
        ",".join(str(s) for s in delayed_statuses) or "NO_TRADE",
    )
    print("time | episode | event | execution | price | position | result")
    print("\n".join(timeline))
    print(f"delayed_kind={delayed_kind} statuses={delayed_statuses} pos={pos_after}")

    assert not delayed_a_exits, (
        f"delayed {delayed_kind}(A) produced EXIT from A against live C: {delayed_a_exits}"
    )
    assert not delayed_a_entries, (
        f"delayed {delayed_kind}(A) produced ENTRY from A against live C: {delayed_a_entries}"
    )
    assert "EXITED" not in delayed_statuses, (
        f"delayed {delayed_kind}(A) closed or flipped position C: "
        f"acts={acts_delayed} pos={pos_after}"
    )
    assert "ENTERED" not in delayed_statuses, (
        f"delayed {delayed_kind}(A) opened/flipped a position: acts={acts_delayed}"
    )
    assert pos_after is not None, f"delayed {delayed_kind}(A) removed position C; acts={acts_delayed}"
    assert pos_after.lifecycle_episode_id == "C"
    assert pos_after.side == "LONG"
    assert pos_after.position_id == c_position_id
    assert not eng.pending_exits

    if delayed_kind == "CONTEXT_FLIP":
        flip_c = _flip(
            eid="iso_C_flip",
            episode="C",
            mono=6_000_000,
            occurrence_ts="2026-08-13T11:10:00Z",
            occurrence_price=200.0,
            bid=197.8,
            ask=198.0,
            extra={
                "materialized_timestamp": "2026-08-13T11:10:00Z",
                "ingested_at": "2026-08-13T11:10:00Z",
            },
        )
        _journal_append(c, flip_c)
        acts = _poll_journal(
            eng,
            monkeypatch,
            bid=197.8,
            ask=198.0,
            mono=5_999_000,
            ts="2026-08-13T11:10:00Z",
            clock=datetime(2026, 8, 13, 11, 10, tzinfo=timezone.utc),
        )
        assert [a.get("status") for a in acts] == ["EXITED", "ENTERED"]
        assert acts[0]["trade"]["lifecycle_episode_id"] == "C"
        assert acts[1]["position"]["lifecycle_episode_id"] == "C"
        assert eng.positions["M15"].lifecycle_episode_id == "C"
        assert eng.positions["M15"].side == "SHORT"
        assert acts[0]["fill"].get("trigger_monotonic_ns", 6_000_000) < acts[1]["fill"]["fill_monotonic_ns"]
        assert acts[1]["fill"]["fill_monotonic_ns"] == acts[0]["fill"]["fill_monotonic_ns"] + 1
        _row("11:10", "C", "FLIP", acts[1]["fill"]["execution_timestamp"], acts[1]["fill"]["paper_fill_price"], "SHORT", "EXITED,ENTERED")
        matching = "FLIP(C) EXIT then ENTRY: YES"
    else:
        end_c = _end(
            eid="iso_C_end",
            episode="C",
            mono=6_000_000,
            occurrence_ts="2026-08-13T11:10:00Z",
            occurrence_price=200.0,
            bid=197.8,
            ask=198.0,
            extra={
                "materialized_timestamp": "2026-08-13T11:10:00Z",
                "ingested_at": "2026-08-13T11:10:00Z",
            },
        )
        _journal_append(c, end_c)
        acts = _poll_journal(
            eng,
            monkeypatch,
            bid=198.0,
            ask=198.2,
            mono=5_999_000,
            ts="2026-08-13T11:10:00Z",
            clock=datetime(2026, 8, 13, 11, 10, tzinfo=timezone.utc),
        )
        assert [a.get("status") for a in acts] == ["EXITED"]
        fill_c_out = acts[0]["fill"]
        assert acts[0]["trade"]["lifecycle_episode_id"] == "C"
        closed_c = [
            p
            for p in eng.books.read_all("positions")
            if p.get("status") == "CLOSED" and p.get("lifecycle_episode_id") == "C"
        ]
        assert closed_c, "END(C) did not close episode C"
        assert closed_c[-1]["closed_at"] == fill_c_out["execution_timestamp"]
        assert fill_c_out["paper_fill_price"] == pytest.approx(198.0)
        assert "M15" not in eng.positions
        _row("11:10", "C", "END", fill_c_out["execution_timestamp"], fill_c_out["paper_fill_price"], "FLAT", "EXITED")
        matching = "END(C) closed C: YES"

    print("time | episode | event | execution | price | position | result")
    print("\n".join(timeline))
    print(
        f"delayed_kind={delayed_kind}\n"
        "A closed before C: YES\n"
        "C lifecycle after delayed A: C\n"
        "delayed A EXIT/ENTRY: NO\n"
        f"{matching}"
    )


def test_live1b_matching_end_c_still_exits(cfg):
    c, _ = cfg
    eng = _engine(c)
    assert eng.process_context_event(_start(eid="m_c_start", episode="C"))[0]["status"] == "ENTERED"
    assert eng.positions["M15"].lifecycle_episode_id == "C"
    acts = eng.process_context_event(
        _end(eid="m_c_end", episode="C", mono=3_000_000, occurrence_ts=_fresh(5))
    )
    assert [a.get("status") for a in acts] == ["EXITED"]
    assert acts[0]["trade"]["lifecycle_episode_id"] == "C"
    assert "M15" not in eng.positions


def test_live1b_matching_flip_c_still_flips(cfg):
    c, _ = cfg
    eng = _engine(c)
    eng.process_context_event(_start(eid="f_c_start", episode="C"))
    eng.update_bbo_from_market(
        best_bid=100.5, best_ask=100.7, receive_monotonic_ns=3_000_000, book_update_id="2"
    )
    acts = eng.process_context_event(
        _flip(
            eid="f_c_flip",
            episode="C",
            mono=4_000_000,
            occurrence_ts=_fresh(5),
            bid=100.5,
            ask=100.7,
        )
    )
    assert [a.get("status") for a in acts] == ["EXITED", "ENTERED"]
    assert acts[0]["trade"]["lifecycle_episode_id"] == "C"
    assert acts[1]["position"]["lifecycle_episode_id"] == "C"
    assert eng.positions["M15"].lifecycle_episode_id == "C"
    assert eng.positions["M15"].side == "SHORT"
    assert acts[0]["fill"].get("trigger_monotonic_ns", 4_000_000) < acts[1]["fill"]["fill_monotonic_ns"]
    assert acts[1]["fill"]["fill_monotonic_ns"] == acts[0]["fill"]["fill_monotonic_ns"] + 1


def test_live1b_observe_end_a_cannot_close_long_c(cfg):
    """END(A) with side OBSERVE must not close LONG(C)."""
    c, _ = cfg
    eng = _engine(c)
    assert eng.process_context_event(_start(eid="o_a_start", episode="A"))[0]["status"] == "ENTERED"
    assert eng.process_context_event(
        _end(eid="o_a_end", episode="A", mono=3_000_000, occurrence_ts=_fresh(5))
    )[0]["status"] == "EXITED"
    assert eng.process_context_event(_start(eid="o_c_start", episode="C", mono=4_000_000))[0]["status"] == "ENTERED"
    assert eng.positions["M15"].lifecycle_episode_id == "C"
    observe_end = _end(eid="o_a_observe", episode="A", mono=5_000_000, occurrence_ts=_fresh(2))
    assert observe_end["new_context"] == "OBSERVE"
    acts = eng.process_context_event(observe_end)
    assert [a.get("status") for a in acts] == []
    assert eng.positions["M15"].lifecycle_episode_id == "C"
    assert eng.positions["M15"].side == "LONG"
    assert not eng.pending_exits


