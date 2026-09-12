"""TP/SL must not fire on gap-recovery prints from before the position opened."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch

REPO = Path(__file__).resolve().parents[3]


def _cfg(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    raw = (REPO / "config" / "intrabar_paper_execution.json").read_text(encoding="utf-8")
    import json

    payload = json.loads(raw)
    payload["context_journal_root"] = "data/cognition/intrabar_context_events"
    payload["books_root"] = "data/trading/intrabar_paper"
    payload["epochs_root"] = "data/trading/paper_epochs"
    payload["entry_source"] = "context_journal"
    (repo / "config" / "intrabar_paper_execution.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (repo / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True)
    (repo / "data" / "trading" / "intrabar_paper").mkdir(parents=True)
    (repo / "data" / "trading" / "paper_epochs").mkdir(parents=True)
    return load_intrabar_paper_config(repo_root=repo), repo


def _engine(tmp_path: Path) -> IntrabarPaperEngine:
    cfg, repo = _cfg(tmp_path)
    ep = create_epoch(
        epochs_root=cfg.epochs_root,
        initial_equity_usd=cfg.initial_equity_usd,
        utc_stamp="TESTPREENTRY",
    )
    ep = activate_epoch(ep, epochs_root=cfg.epochs_root)
    eng = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    eng.bbo.update_from_book_ticker(
        best_bid=100.0,
        best_ask=100.2,
        receive_monotonic_ns=1_000_000,
        receive_timestamp="2026-09-11T12:34:00Z",
        book_update_id="1",
        domain="context",
    )
    return eng


def _start(eng: IntrabarPaperEngine) -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    acts = eng.process_context_event(
        {
            "context_event_id": "CTX_pre_entry_1",
            "event_type": "CONTEXT_START",
            "timeframe": "M15",
            "previous_context": "OBSERVE",
            "new_context": "LONG_CONTEXT",
            "event_monotonic_ns": 2_000_000,
            "event_timestamp": now,
            "decision_available_at": now,
            "context_event_price": "100.1",
            "best_bid": 100.0,
            "best_ask": 100.2,
            "bbo_receive_monotonic_ns": 1_999_000,
            "book_update_id": "b1",
            "lifecycle_episode_id": "M15:prov:99",
        }
    )
    assert acts and acts[0]["status"] == "ENTERED"


def _ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def test_backfill_print_from_before_entry_does_not_stop_long(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    _start(eng)
    pos = eng.positions["M15"]
    opened = datetime.fromisoformat(str(pos.opened_at).replace("Z", "+00:00"))
    pre = opened - timedelta(minutes=4)
    receive = opened + timedelta(minutes=12)

    acts = eng.update_from_trade(
        price=float(pos.stop_loss_price) - 0.5,
        receive_monotonic_ns=9_000_000,
        receive_timestamp=receive.isoformat().replace("+00:00", "Z"),
        source_event_id="agg_pre_entry",
        market_provenance={
            "exchange_trade_timestamp": _ms(pre),
            "backfill": True,
            "aggregate_trade_id": 3446452763,
        },
    )
    assert acts == []
    assert "M15" in eng.positions


def test_live_print_after_entry_still_stops_long(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    _start(eng)
    pos = eng.positions["M15"]
    opened = datetime.fromisoformat(str(pos.opened_at).replace("Z", "+00:00"))
    live = opened + timedelta(seconds=8)

    acts = eng.update_from_trade(
        price=float(pos.stop_loss_price) - 0.5,
        receive_monotonic_ns=9_000_000,
        receive_timestamp=live.isoformat().replace("+00:00", "Z"),
        source_event_id="agg_live_sl",
        market_provenance={
            "exchange_trade_timestamp": _ms(live),
            "backfill": False,
            "aggregate_trade_id": 3446459000,
        },
    )
    assert acts and acts[0]["status"] == "EXITED"
    assert "M15" not in eng.positions
    assert eng.books.read_all("trades")[-1]["exit_reason"] == "SL"
