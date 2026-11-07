#!/usr/bin/env python3
"""ETLL Hybrid lived replay: S4.1 manager → LIVE1B execution (all 4 TF).

Canonical model (docs/design/S41_LIVE1B_HYBRID.md):
  - Manager emits OPEN/CLOSE/HOLD (HOLD_UNTIL → CLOSE mainly on context flip)
  - LIVE1B owns books/fills/PnL and protective TP/SL on price path
  - No S4.1 TimeframeTrader writers

Historical fills: completed-bar mid as synthetic local BBO (bid=ask=close),
same research fill approximation as prior ETLL, but exits include TP/SL.
Same-bar SL+TP → stop-first (trading contract / evaluate_exit_preview OFF path).

Isolated under data/research/external_traders/etll_hybrid_replay/ — does not
touch production LIVE1B epoch or manager activation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.external_traders.shadow_lab import default_pack_dir  # noqa: E402
from btc_ml.trading.command_bus import COMMAND_COLUMNS, CommandBusPaths  # noqa: E402
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config  # noqa: E402
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine  # noqa: E402
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch  # noqa: E402
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading.timeframe_manager import TimeframeManager  # noqa: E402
from btc_ml.trading.timeframe_state_adapter import load_sources  # noqa: E402
from btc_ml.trading.timeframe_trader import TraderBook  # noqa: E402

from scripts.research.run_etll_btc_m15_lived_replay import (  # noqa: E402
    BufferedCommandBus,
    evaluation_timestamps,
    load_feed,
    with_bar_close,
)

TIMEFRAMES = ("M15", "M30", "H1", "H4")
SANDBOX = ROOT / "data/research/external_traders/etll_hybrid_replay"


def _utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat().replace("+00:00", "Z")


def _merge_pack_sources() -> Any:
    frames_a = []
    frames_l = []
    for tf in TIMEFRAMES:
        pack = default_pack_dir(tf)
        a = pack / "context" / "multi_timeframe_availability_memory.parquet"
        l = pack / "context" / "market_context_lifecycle_memory.parquet"
        if not a.exists() or not l.exists():
            raise FileNotFoundError(f"missing context for {tf}: {a} / {l}")
        frames_a.append(pd.read_parquet(a))
        frames_l.append(pd.read_parquet(l))
    avail = pd.concat(frames_a, ignore_index=True)
    life = pd.concat(frames_l, ignore_index=True)
    out_ctx = SANDBOX / "context"
    out_ctx.mkdir(parents=True, exist_ok=True)
    avail_path = out_ctx / "multi_timeframe_availability_memory.parquet"
    life_path = out_ctx / "market_context_lifecycle_memory.parquet"
    avail.to_parquet(avail_path, index=False)
    life.to_parquet(life_path, index=False)
    return load_sources(availability_path=avail_path, lifecycle_path=life_path)


def _load_feeds() -> dict[str, pd.DataFrame]:
    feeds: dict[str, pd.DataFrame] = {}
    for tf in TIMEFRAMES:
        path = default_pack_dir(tf) / f"feed_{tf.lower()}.parquet"
        feed = with_bar_close(load_feed(path)).sort_values("bar_close_timestamp").reset_index(drop=True)
        ts = pd.to_datetime(feed["bar_close_timestamp"], utc=True)
        feed["_bar_close_ns"] = ts.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
        feeds[tf] = feed
    return feeds


def _ts_iso(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _inject_bbo(engine: IntrabarPaperEngine, *, price: float, ts: str, mono: int | None = None) -> int:
    """Inject synthetic local BBO. Mono must be wall-clock fresh for LIVE1B age gates."""
    import time as _time

    px = float(price)
    mono_n = int(mono if mono is not None else _time.monotonic_ns())
    engine.update_bbo_from_market(
        best_bid=px,
        best_ask=px,
        receive_monotonic_ns=mono_n,
        receive_timestamp=ts,
        book_update_id=f"hist_bbo_{mono_n}",
        source_event_id=f"hist_bbo_{mono_n}",
    )
    return mono_n


def _process_protective_until(
    engine: IntrabarPaperEngine,
    feeds: dict[str, pd.DataFrame],
    cursors: dict[str, int],
    *,
    until_ts: pd.Timestamp,
) -> list[dict[str, Any]]:
    import time as _time

    actions: list[dict[str, Any]] = []
    until64 = until_ts.to_datetime64()
    for tf in TIMEFRAMES:
        feed = feeds[tf]
        start = int(cursors.get(tf, 0))
        closes = feed["_bar_close_ns"].to_numpy()
        end = int(pd.Series(closes).searchsorted(until64, side="right"))
        if end <= start:
            continue
        for i in range(start, end):
            row = feed.iloc[i]
            ts = _ts_iso(row["bar_close_timestamp"])
            close_px = float(row["close"])
            mono_n = _inject_bbo(engine, price=close_px, ts=ts)
            if tf in engine.positions:
                acts = _protective_on_bar(
                    engine,
                    tf=tf,
                    high=float(row["high"]),
                    low=float(row["low"]),
                    ts=ts,
                    mono_base=mono_n,
                )
                if acts:
                    actions.extend(acts)
        cursors[tf] = end
    return actions


def _protective_on_bar(
    engine: IntrabarPaperEngine,
    *,
    tf: str,
    high: float,
    low: float,
    ts: str,
    mono_base: int,
) -> list[dict[str, Any]]:
    """Apply Hybrid protective TP/SL using bar OHLC; same-bar → stop-first."""
    import time as _time

    pos = engine.positions.get(tf)
    if pos is None:
        return []
    actions: list[dict[str, Any]] = []
    side = pos.side
    sl = float(pos.stop_loss_price)
    tp = float(pos.take_profit_price)
    hi = float(high)
    lo = float(low)

    if side == "LONG":
        hit_sl = lo <= sl
        hit_tp = hi >= tp
    else:
        hit_sl = hi >= sl
        hit_tp = lo <= tp

    prices: list[float] = []
    if hit_sl and hit_tp:
        prices.append(sl)
    elif hit_sl:
        prices.append(sl)
    elif hit_tp:
        prices.append(tp)
    else:
        return []

    for i, px in enumerate(prices):
        if tf not in engine.positions:
            break
        # refresh BBO at protective level for exit fill pricing
        _inject_bbo(engine, price=float(px), ts=ts)
        out = engine.update_from_trade(
            price=float(px),
            receive_monotonic_ns=int(_time.monotonic_ns()),
            receive_timestamp=ts,
            source_event_id=f"hist_prot_{tf}_{ts}_{i}",
        )
        if out:
            if isinstance(out, list):
                actions.extend(out)
            else:
                actions.append(out)
    return actions


def _apply_commands(engine: IntrabarPaperEngine, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for cmd in commands:
        intent = str(cmd.get("intent") or "").upper()
        if intent not in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}:
            continue
        if not bool(cmd.get("action_allowed")):
            continue
        if intent.startswith("OPEN") and engine.bbo.latest is None:
            continue
        # Refresh BBO age gate immediately before OPEN/CLOSE fill
        if engine.bbo.latest is not None:
            last = engine.bbo.latest
            _inject_bbo(engine, price=float(last.mid), ts=str(last.receive_timestamp or _utc_now()))
        result = engine.apply_s41_manager_command(cmd)
        if result:
            actions.append(result)
    return actions


def _export_trades(engine: IntrabarPaperEngine, out_dir: Path) -> pd.DataFrame:
    trades_path = engine.books.root / "trades.jsonl"
    rows: list[dict[str, Any]] = []
    if trades_path.exists():
        with trades_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    frame = pd.DataFrame(rows)
    if len(frame):
        frame.to_parquet(out_dir / "lived_trades.parquet", index=False)
        # also copy jsonl books pointer summary
    return frame


def _bucket(frame: pd.DataFrame) -> dict[str, Any]:
    if not len(frame):
        return {"n": 0}
    net = pd.to_numeric(frame.get("net_pnl_usd"), errors="coerce").fillna(0.0)
    wins = net[net > 0]
    losses = net[net < 0]
    gp = float(wins.sum())
    gl = float(abs(losses.sum()))
    return {
        "n": int(len(frame)),
        "wr": float((net > 0).mean()),
        "pf": (gp / gl) if gl > 0 else None,
        "net_pnl_usd": float(net.sum()),
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
    }


def run_hybrid(
    *,
    limit: int | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    flush_every: int = 500,
    fresh: bool = True,
) -> dict[str, Any]:
    started = time.time()
    if fresh and SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir(parents=True, exist_ok=True)

    # Research-only config overlay (hybrid entry source); costs from canonical JSON.
    cfg = load_intrabar_paper_config(ROOT / "config" / "intrabar_paper_execution.json", repo_root=ROOT)
    # Point books/epochs/journal into sandbox via object replace
    raw = dict(cfg.raw)
    raw["entry_source"] = "s41_command_bus"
    raw["s41_consume_commands_after"] = "1970-01-01T00:00:00Z"
    raw["books_root"] = str(SANDBOX / "data" / "trading" / "intrabar_paper")
    raw["epochs_root"] = str(SANDBOX / "data" / "trading" / "paper_epochs")
    raw["context_journal_root"] = str(SANDBOX / "data" / "cognition" / "intrabar_context_events")
    cfg_path = SANDBOX / "config" / "intrabar_paper_execution.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    cfg = load_intrabar_paper_config(cfg_path, repo_root=SANDBOX)

    (SANDBOX / "data" / "cognition" / "intrabar_context_events").mkdir(parents=True, exist_ok=True)
    (SANDBOX / "data" / "cognition" / "intrabar_context_events" / "events.jsonl").write_text("", encoding="utf-8")

    epoch = create_epoch(
        epochs_root=cfg.epochs_root,
        initial_equity_usd=float(cfg.initial_equity_usd),
        epoch_id_prefix="ETLL_HYBRID_V1",
    )
    epoch = activate_epoch(epoch, epochs_root=cfg.epochs_root)

    engine = IntrabarPaperEngine(cfg=cfg, epoch=epoch, activation_monotonic_ns=1)

    # Manager bus in sandbox (not production)
    bus_root = SANDBOX / "data" / "trading" / "manager"
    bus_root.mkdir(parents=True, exist_ok=True)
    bus_paths = CommandBusPaths(
        memory=bus_root / "timeframe_command_memory.parquet",
        latest=bus_root / "latest_commands.json",
        manager_state=bus_root / "manager_state.json",
        portfolio_summary=bus_root / "portfolio_summary.json",
    )
    # Dummy trader books unused when live1b views forced on
    books = {tf: TraderBook.candidate(tf) for tf in TIMEFRAMES}
    for tf, book in books.items():
        book.root.mkdir(parents=True, exist_ok=True)

    bus = BufferedCommandBus(bus_paths)
    manager = TimeframeManager(
        bus=bus,
        books=books,
        risk=PortfolioRiskCoordinator.load(),
        timeframes=TIMEFRAMES,
    )

    # Force Hybrid position views → sandbox LIVE1B epoch
    epoch_id = epoch.paper_epoch_id

    def _hybrid_views(self: TimeframeManager, *, mark_price: float | None = None) -> dict[str, dict[str, Any]]:
        from btc_ml.trading.live1b_position_views import live1b_trader_views

        return live1b_trader_views(
            timeframes=self.timeframes,
            mark_price=mark_price,
            repo_root=SANDBOX,
            paper_epoch_id=epoch_id,
        )

    TimeframeManager.trader_views = _hybrid_views  # type: ignore[method-assign]
    TimeframeManager._use_live1b_position_views = staticmethod(lambda: True)  # type: ignore[method-assign]

    sources = _merge_pack_sources()
    feeds = _load_feeds()
    # Drive on M15 evaluation grid (finest live clock)
    stamps = evaluation_timestamps(
        SANDBOX / "context" / "multi_timeframe_availability_memory.parquet",
        timeframe="M15",
        limit=limit,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    if not stamps:
        raise RuntimeError("no M15 evaluation timestamps in merged availability")

    cursors = {tf: 0 for tf in TIMEFRAMES}
    prot_n = 0
    cmd_n = 0
    open_ok = 0
    open_block: dict[str, int] = {}
    empty_decision_index: dict[str, dict] = {"open": {}, "close": {}}
    feed_m15 = feeds["M15"]
    m15_closes = feed_m15["_bar_close_ns"].to_numpy()

    for index, evaluation in enumerate(stamps):
        boundary = pd.Timestamp(evaluation)
        if boundary.tzinfo is None:
            boundary = boundary.tz_localize("UTC")
        else:
            boundary = boundary.tz_convert("UTC")

        # 1) Protective TP/SL on all TF bars up to this tip (LIVE1B market path)
        acts = _process_protective_until(engine, feeds, cursors, until_ts=boundary)
        prot_n += len(acts)

        # 2) BBO at M15 tip for manager/OPEN fills
        cut = int(pd.Series(m15_closes).searchsorted(boundary.to_datetime64(), side="right"))
        if cut <= 0:
            continue
        tip = feed_m15.iloc[cut - 1]
        tip_ts = _ts_iso(tip["bar_close_timestamp"])
        _inject_bbo(engine, price=float(tip["close"]), ts=tip_ts)
        visible = feed_m15.iloc[max(0, cut - 16) : cut]

        # 3) S4.1 manager cycle (reads LIVE1B opens)
        cycle = manager.run_cycle(
            evaluation_timestamp=evaluation,
            sources=sources,
            feed=visible,
            persist=True,
            decision_index=empty_decision_index,
        )
        commands = list(cycle.get("commands") or [])
        applied = _apply_commands(engine, commands)
        for r in applied:
            st = str((r or {}).get("status") or "")
            if "OPEN" in str((r or {}).get("action") or "").upper() or st in {"FILLED", "OPENED", "ENTRY"}:
                open_ok += 1
            if st.startswith("ENTRY_BLOCKED") or st.startswith("REJECTED"):
                open_block[st] = open_block.get(st, 0) + 1
            # successful enter often returns dict with position / status without ENTRY_BLOCKED
            if st and "BLOCK" not in st and "REJECT" not in st and "IGNORE" not in st:
                if any(k in r for k in ("position_id", "fill_id", "entry_price")) or st in {
                    "EXECUTED",
                    "CLOSED",
                    "EXITED",
                }:
                    pass
        cmd_n += len(applied)

        if flush_every > 0 and (index + 1) % flush_every == 0:
            bus.flush()
            engine.write_health()
            elapsed = time.time() - started
            done = index + 1
            rate = done / elapsed if elapsed > 0 else 0.0
            eta = (len(stamps) - done) / rate if rate > 0 else None
            print(
                json.dumps(
                    {
                        "progress_cycle": done,
                        "of": len(stamps),
                        "evaluation_timestamp": str(evaluation),
                        "open_tfs": sorted(engine.positions.keys()),
                        "protective_actions": prot_n,
                        "command_applies": cmd_n,
                        "open_blocks": open_block,
                        "elapsed_s": round(elapsed, 1),
                        "eta_s": None if eta is None else round(eta, 1),
                    }
                ),
                flush=True,
            )

    bus.flush()
    engine.write_health()
    if stamps:
        last = pd.Timestamp(stamps[-1])
        if last.tzinfo is None:
            last = last.tz_localize("UTC")
        acts = _process_protective_until(engine, feeds, cursors, until_ts=last)
        prot_n += len(acts)

    out_dir = SANDBOX / "lived_replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    trades = _export_trades(engine, out_dir)
    # snapshot commands
    commands_df = bus.frame()
    if len(commands_df):
        commands_df[COMMAND_COLUMNS].to_parquet(out_dir / "manager_commands.parquet", index=False)

    exit_counts: dict[str, int] = {}
    if len(trades) and "exit_reason" in trades.columns:
        exit_counts = trades["exit_reason"].astype(str).value_counts().to_dict()
    elif len(trades) and "trigger_type" in trades.columns:
        exit_counts = trades["trigger_type"].astype(str).value_counts().to_dict()

    # normalize exit reason field
    reason_col = None
    for c in ("exit_reason", "trigger_type"):
        if len(trades) and c in trades.columns:
            reason_col = c
            break

    by_tf = {}
    if len(trades) and "timeframe" in trades.columns:
        for tf, g in trades.groupby(trades["timeframe"].astype(str).str.upper()):
            by_tf[tf] = _bucket(g)
            if reason_col:
                by_tf[tf]["exit_reasons"] = g[reason_col].astype(str).value_counts().to_dict()

    summary = {
        "stage": "ETLL_HYBRID_LIVED_REPLAY",
        "status": "HYBRID_REPLAY_DONE",
        "model": "S41_MANAGER_PLUS_LIVE1B_EXECUTION",
        "timeframes": list(TIMEFRAMES),
        "paper_epoch_id": epoch.paper_epoch_id,
        "sandbox": str(SANDBOX),
        "cycles": len(stamps),
        "closed_trades": int(len(trades)),
        "overall": _bucket(trades),
        "by_timeframe": by_tf,
        "exit_reason_counts": exit_counts if exit_counts else (
            trades[reason_col].astype(str).value_counts().to_dict() if reason_col else {}
        ),
        "protective_actions_recorded": prot_n,
        "command_applies": cmd_n,
        "open_block_statuses": open_block,
        "elapsed_seconds": round(time.time() - started, 1),
        "generated_at": _utc_now(),
        "fill_note": "historical bar close as synthetic local BBO; TP/SL via LIVE1B update_from_trade; same-bar stop-first",
        "external_trades_used": False,
    }
    (out_dir / "lived_replay_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--from-ts", type=str, default=None)
    parser.add_argument("--to-ts", type=str, default=None)
    parser.add_argument("--flush-every", type=int, default=500)
    parser.add_argument("--no-fresh", action="store_true")
    args = parser.parse_args()
    summary = run_hybrid(
        limit=args.limit,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        flush_every=args.flush_every,
        fresh=not args.no_fresh,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
