"""Path-density anti-saw gates OPEN only. Exits stay free."""

from __future__ import annotations

from btc_ml.trading.anti_saw_path_density import BLOCK_REASON, PathDensitySawFilter, SawDecision
from tests.trading.intrabar_paper.test_live1b_intrabar_paper import _ctx, _engine

pytest_plugins = ["tests.trading.intrabar_paper.test_live1b_intrabar_paper"]


class _FixedSaw:
    def __init__(self, block: bool) -> None:
        self.block = block

    def evaluate(self, *, timeframe: str, as_of=None) -> SawDecision:
        return SawDecision(
            block=self.block,
            reason=BLOCK_REASON if self.block else None,
            timeframe=str(timeframe).upper(),
            score=None,
            source="test",
        )


def test_start_blocked_when_saw(cfg) -> None:
    c, repo = cfg
    eng = _engine(c, repo)
    eng.saw_filter = _FixedSaw(True)
    acts = eng.process_context_event(
        _ctx(eid="saw1", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    assert acts[0]["status"] == BLOCK_REASON
    assert "M15" not in eng.positions
    blocked = eng.books.read_all("blocked")
    assert blocked[-1]["reason"] == BLOCK_REASON


def test_end_still_flattens_through_saw(cfg) -> None:
    c, repo = cfg
    eng = _engine(c, repo)
    eng.saw_filter = _FixedSaw(False)
    eng.process_context_event(
        _ctx(eid="in", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    assert "M15" in eng.positions
    eng.saw_filter = _FixedSaw(True)
    acts = eng.process_context_event(
        _ctx(eid="out", etype="CONTEXT_END", tf="M15", prev="LONG_CONTEXT", new="OBSERVE", mono=3_000_000)
    )
    assert acts[0]["status"] == "EXITED"
    assert "M15" not in eng.positions


def test_flip_closes_then_skips_new_open_in_saw(cfg) -> None:
    c, repo = cfg
    eng = _engine(c, repo)
    eng.saw_filter = _FixedSaw(False)
    eng.process_context_event(
        _ctx(eid="long", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    eng.saw_filter = _FixedSaw(True)
    eng.update_bbo_from_market(
        best_bid=100.5, best_ask=100.7, receive_monotonic_ns=3_000_000, book_update_id="2"
    )
    acts = eng.process_context_event(
        _ctx(
            eid="flip",
            etype="CONTEXT_FLIP",
            tf="M15",
            prev="LONG_CONTEXT",
            new="SHORT_CONTEXT",
            mono=4_000_000,
            bid=100.5,
            ask=100.7,
        )
    )
    statuses = [a["status"] for a in acts]
    assert "EXITED" in statuses
    assert BLOCK_REASON in statuses
    assert "M15" not in eng.positions


def test_missing_bars_fail_open(cfg) -> None:
    c, repo = cfg
    eng = _engine(c, repo)
    eng.saw_filter = PathDensitySawFilter(
        {"anti_saw_path_density": {"enabled": True, "mode": "enforce"}},
        bars_by_tf={"M15": []},
    )
    acts = eng.process_context_event(
        _ctx(eid="ok", etype="CONTEXT_START", tf="M15", prev="OBSERVE", new="LONG_CONTEXT", mono=2_000_000)
    )
    assert acts[0]["status"] == "ENTERED"


def test_s41_open_is_not_blocked_by_saw(cfg) -> None:
    from datetime import datetime, timezone

    c, repo = cfg
    eng = _engine(c, repo)
    eng.saw_filter = _FixedSaw(True)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = eng.apply_s41_manager_command(
        {
            "command_id": "TF_CMD_cognition_open",
            "timeframe": "M15",
            "intent": "OPEN_LONG",
            "action_allowed": True,
            "lifecycle_episode_id": "M15:334",
            "evaluation_timestamp": ts,
            "context_origin_price": 100.1,
        }
    )
    assert result["status"] == "ENTERED"
    assert "M15" in eng.positions
