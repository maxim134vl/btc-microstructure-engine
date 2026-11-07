#!/usr/bin/env python3
"""ETLL Hybrid lived replay on EXACT aggTrade ticks (S4.1 + LIVE1B).

Canonical model (docs/design/S41_LIVE1B_HYBRID.md):
  - S4.1 Manager emits OPEN/CLOSE commands (context flip path)
  - LIVE1B IntrabarPaperEngine owns books + protective TP/SL
  - Protective exits: engine.update_from_trade(price=aggTrade.price) — moment price
  - Entry BBO: last aggTrade as synthetic local BBO (bid=ask=last)

NOT bar-close Hybrid. Isolated research sandbox only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from btc_ml.external_traders.shadow_lab import default_pack_dir  # noqa: E402
from btc_ml.trading.command_bus import COMMAND_COLUMNS, CommandBusPaths  # noqa: E402
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config  # noqa: E402
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine  # noqa: E402
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch  # noqa: E402
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator  # noqa: E402
from btc_ml.trading.shadow_structural_protection.tick_cache import TickHourCache  # noqa: E402
from btc_ml.trading import timeframe_manager  # noqa: E402
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
_TF_MINUTES = {"M15": 15, "M30": 30, "H1": 60, "H4": 240}
SANDBOX = ROOT / "data/research/external_traders/etll_hybrid_tick"
PACK_ROOTS = (
    Path("/Volumes/MaksTiger/btc-ml/from-mac-20260907/btc-ml-cold/research/external_traders"),
    ROOT / "data/research/external_traders",
)
_PACK_ROOT: Path | None = None


def resolve_pack_dir(timeframe: str, pack_root: Path | None = None) -> Path:
    """Prefer packs that already have living-process lifecycle. Local feed-only dirs lose."""
    tf = str(timeframe or "M15").upper()
    roots: list[Path] = []
    explicit = pack_root if pack_root is not None else _PACK_ROOT
    if explicit is not None:
        roots.append(Path(explicit))
    roots.extend(PACK_ROOTS)
    for root in roots:
        pack = Path(root) / f"market_pack_btc_{tf.lower()}"
        life = pack / "context" / "market_context_lifecycle_memory.parquet"
        if life.exists():
            return pack
    return default_pack_dir(tf)


DEFAULT_TICK_REPO = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_tip/tick_pack_full_etll/repo"
)
# Durable store for Optuna / later calibration — survives local sandbox wipe.
DEFAULT_DURABLE_ARCHIVE = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive"
)


def _utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").isoformat().replace("+00:00", "Z")


def _ts_iso(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _as_utc(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _merge_pack_sources(*, lifecycle_align: str = "bar_close") -> Any:
    frames_a = []
    frames_l = []
    for tf in TIMEFRAMES:
        pack = resolve_pack_dir(tf)
        a = pack / "context" / "multi_timeframe_availability_memory.parquet"
        l = pack / "context" / "market_context_lifecycle_memory.parquet"
        if not a.exists() or not l.exists():
            raise FileNotFoundError(f"missing context for {tf}: {a} / {l}")
        # M15 pack lifecycle has no timeframe column; without an explicit tag,
        # concat with tagged M30/H1/H4 leaves NaN and _scoped_lifecycle drops M15.
        avail_tf = pd.read_parquet(a).copy()
        life_tf = pd.read_parquet(l).copy()
        avail_tf["timeframe"] = str(tf).upper()
        life_tf["timeframe"] = str(tf).upper()
        # Pack lifecycle rows are keyed by bar_OPEN while the adapter selects on
        # `timestamp <= source_bar_close` (availability is keyed by bar_close).
        # Left as-is that hands the manager the close of the bar still in flight,
        # i.e. one full TF period of look-ahead. Re-key to the availability moment.
        if str(lifecycle_align).lower() == "bar_close":
            stamps = pd.to_datetime(life_tf["timestamp"], utc=True, errors="coerce")
            life_tf["lifecycle_bar_open_timestamp"] = stamps
            life_tf["timestamp"] = stamps + pd.Timedelta(minutes=_TF_MINUTES[str(tf).upper()])
        if "living_process" not in life_tf.columns:
            raise RuntimeError(
                f"{tf} lifecycle has no living_process — refuse replay without the cognitive fix: {l}"
            )
        print(
            json.dumps(
                {
                    "pack_tf": tf,
                    "pack_dir": str(pack),
                    "lifecycle_rows": int(len(life_tf)),
                    "living_process": True,
                    "lifecycle_version": str(
                        life_tf["builder_version"].iloc[0] if "builder_version" in life_tf.columns else ""
                    ),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        frames_a.append(avail_tf)
        frames_l.append(life_tf)
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
        path = resolve_pack_dir(tf) / f"feed_{tf.lower()}.parquet"
        feed = with_bar_close(load_feed(path)).sort_values("bar_close_timestamp").reset_index(drop=True)
        ts = pd.to_datetime(feed["bar_close_timestamp"], utc=True)
        feed["_bar_close_ns"] = ts.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
        feeds[tf] = feed
    return feeds


def _inject_bbo(engine: IntrabarPaperEngine, *, price: float, ts: str, mono: int | None = None) -> int:
    """Inject synthetic local BBO. Mono must be wall-clock fresh for LIVE1B age gates."""
    px = float(price)
    mono_n = int(mono if mono is not None else time.monotonic_ns())
    engine.update_bbo_from_market(
        best_bid=px,
        best_ask=px,
        receive_monotonic_ns=mono_n,
        receive_timestamp=ts,
        book_update_id=f"tick_bbo_{mono_n}",
        source_event_id=f"tick_bbo_{mono_n}",
    )
    return mono_n


def _first_barrier_crossing(prices: Any, positions: list[Any]) -> int | None:
    """Index of the first tick that would trigger any open position's TP/SL.

    IntrabarPaperEngine._check_tp_sl_on_market compares the trade price against
    static levels and mutates nothing when neither is hit (no trailing stop, no
    break-even, no MFE tracking anywhere in the intrabar_paper package), so every
    tick before the first crossing is a no-op. Locating that tick with numpy lets
    the replay hand the engine only the ticks that can actually change its state
    instead of all ~660M ticks in the span, which is where the 10.8h runtime went.
    """
    mask = None
    for pos in positions:
        tp = float(pos.take_profit_price)
        sl = float(pos.stop_loss_price)
        if str(pos.side).upper() == "LONG":
            hit = (prices >= tp) | (prices <= sl)
        else:
            hit = (prices <= tp) | (prices >= sl)
        mask = hit if mask is None else (mask | hit)
    if mask is None or not mask.any():
        return None
    return int(np.argmax(mask))


def _stream_protective(
    engine: IntrabarPaperEngine,
    *,
    ticks: TickHourCache,
    start: pd.Timestamp,
    end: pd.Timestamp,
    scan: str = "vectorized",
) -> tuple[int, float | None]:
    """Drive LIVE1B protective TP/SL with aggTrades in (start, end].

    scan="vectorized" skips the runs of ticks that provably cannot trigger
    anything (see _first_barrier_crossing); scan="naive" hands the engine every
    tick. The two are expected to produce byte-identical books — "naive" is kept
    so that can be re-verified rather than taken on faith.
    """
    if end <= start:
        return 0, None
    ts_ns, prices, trade_ids = ticks.window(start=start, end=end)
    if not len(prices):
        return 0, None

    def _feed(j: int) -> int:
        tid = int(trade_ids[j])
        ts_iso = _ts_iso(pd.Timestamp(int(ts_ns[j]), tz="UTC"))
        acts = engine.update_from_trade(
            price=float(prices[j]),
            receive_monotonic_ns=time.monotonic_ns(),
            receive_timestamp=ts_iso,
            source_event_id=f"agg_{tid}",
            market_provenance={
                "stream": "aggTrade",
                "aggregate_trade_id": tid,
                "exchange_trade_timestamp": ts_iso,
            },
        )
        return len(acts) if acts else 0

    n_exit = 0
    n = len(prices)
    if str(scan).lower() == "naive":
        for j in range(n):
            if engine.positions:
                n_exit += _feed(j)
        return n_exit, float(prices[-1])

    i = 0
    while i < n and engine.positions:
        rel = _first_barrier_crossing(prices[i:], list(engine.positions.values()))
        if rel is None:
            break
        j = i + rel
        n_exit += _feed(j)
        # Advance past j even when the exit was deferred, so a position that stays
        # open on a pending fill cannot spin on the same tick.
        i = j + 1
    return n_exit, float(prices[-1])


def _apply_commands(
    engine: IntrabarPaperEngine,
    commands: list[dict[str, Any]],
    *,
    allow_close: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Apply S4.1 commands to LIVE1B; returns (actions, suppressed_close_count).

    allow_close=False is the barrier-only arm of the flip-close A/B: the manager's
    CLOSE on a context flip is dropped, so a position can only leave via TP or SL.
    Note this also suppresses the flip's reverse entry, because the position stays
    open and a timeframe holds at most one.
    """
    actions: list[dict[str, Any]] = []
    suppressed = 0
    for cmd in commands:
        intent = str(cmd.get("intent") or "").upper()
        if intent not in {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}:
            continue
        if not bool(cmd.get("action_allowed")):
            continue
        if intent == "CLOSE" and not allow_close:
            suppressed += 1
            continue
        if intent.startswith("OPEN") and engine.bbo.latest is None:
            continue
        if engine.bbo.latest is not None:
            last = engine.bbo.latest
            _inject_bbo(engine, price=float(last.mid), ts=str(last.receive_timestamp or _utc_now()))
        result = engine.apply_s41_manager_command(cmd)
        if result:
            actions.append(result)
    return actions, suppressed


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


def _archive_epoch_artifacts(
    *,
    epoch_id: str,
    books_src: Path,
    out_dir: Path,
    summary: dict[str, Any],
    durable_root: Path | None = None,
) -> list[str]:
    """Copy books + summary to local sandbox archive and MaksTiger durable store.

    durable_root=None means local-only: callers pass --no-durable-archive when a
    run is throwaway (speed calibration, A/B slices) and must not touch Tiger.
    """
    roots: list[Path] = [SANDBOX / "archive" / epoch_id]
    durable = durable_root
    if durable is not None:
        roots.append(Path(durable) / epoch_id)

    written: list[str] = []
    payload = dict(summary)
    for archive_root in roots:
        try:
            archive_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(json.dumps({"archive_mkdir_failed": str(archive_root), "error": str(exc)}), flush=True)
            continue
        if books_src.exists():
            dest_books = archive_root / "books"
            if dest_books.exists():
                shutil.rmtree(dest_books)
            shutil.copytree(books_src, dest_books)
        for name in ("lived_trades.parquet", "manager_commands.parquet", "lived_replay_summary.json"):
            src = out_dir / name
            if src.exists():
                shutil.copy2(src, archive_root / name)
        note = (
            f"archived_at={_utc_now()}\n"
            f"paper_epoch_id={epoch_id}\n"
            f"books_src={books_src}\n"
            f"archive_root={archive_root}\n"
            "purpose=durable Hybrid tick books for Optuna/calibration + performance report; "
            "survives sandbox fresh wipe\n"
        )
        (archive_root / "ARCHIVE_NOTE.txt").write_text(note, encoding="utf-8")
        payload["archive_root"] = str(archive_root)
        payload["durable_archive_root"] = str(Path(durable) / epoch_id) if durable else None
        (archive_root / "summary.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        written.append(str(archive_root))
    return written


def run_hybrid_tick(
    *,
    tick_repo: Path,
    limit: int | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    flush_every: int = 200,
    fresh: bool = True,
    durable_archive_root: Path | None = DEFAULT_DURABLE_ARCHIVE,
    lifecycle_align: str = "bar_close",
    protective_scan: str = "vectorized",
    allow_command_close: bool = True,
    anti_saw: bool = True,
    pack_root: Path | None = None,
) -> dict[str, Any]:
    global _PACK_ROOT
    _PACK_ROOT = Path(pack_root) if pack_root is not None else None
    started = time.time()
    if fresh and SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir(parents=True, exist_ok=True)

    # Bar-count anti-saw is archived. Setting this flag is a no-op.
    timeframe_manager.ANTI_SAW_ENABLED = False

    agg_root = tick_repo / "data" / "raw_market_events_v2" / "agg_trade"
    if not agg_root.exists():
        raise FileNotFoundError(f"agg_trade root missing under {tick_repo}")

    cfg = load_intrabar_paper_config(ROOT / "config" / "intrabar_paper_execution.json", repo_root=ROOT)
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
        epoch_id_prefix="ETLL_HYBRID_TICK_V1",
    )
    epoch = activate_epoch(epoch, epochs_root=cfg.epochs_root)
    engine = IntrabarPaperEngine(cfg=cfg, epoch=epoch, activation_monotonic_ns=1)

    bus_root = SANDBOX / "data" / "trading" / "manager"
    bus_root.mkdir(parents=True, exist_ok=True)
    bus_paths = CommandBusPaths(
        memory=bus_root / "timeframe_command_memory.parquet",
        latest=bus_root / "latest_commands.json",
        manager_state=bus_root / "manager_state.json",
        portfolio_summary=bus_root / "portfolio_summary.json",
    )
    books = {tf: TraderBook.candidate(tf) for tf in TIMEFRAMES}
    for book in books.values():
        book.root.mkdir(parents=True, exist_ok=True)

    bus = BufferedCommandBus(bus_paths)
    manager = TimeframeManager(
        bus=bus,
        books=books,
        risk=PortfolioRiskCoordinator.load(),
        timeframes=TIMEFRAMES,
    )

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

    sources = _merge_pack_sources(lifecycle_align=lifecycle_align)
    ticks = TickHourCache(repo=tick_repo)
    feeds = _load_feeds()
    stamps = evaluation_timestamps(
        SANDBOX / "context" / "multi_timeframe_availability_memory.parquet",
        timeframe="M15",
        limit=limit,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    if not stamps:
        raise RuntimeError("no M15 evaluation timestamps")

    feed_m15 = feeds["M15"]
    m15_closes = feed_m15["_bar_close_ns"].to_numpy()
    empty_decision_index: dict[str, dict] = {"open": {}, "close": {}}

    last_stream_end = _as_utc(stamps[0]) - pd.Timedelta(seconds=1)
    last_px: float | None = None
    prot_n = 0
    cmd_n = 0
    close_suppressed_n = 0
    tick_batches = 0
    open_block: dict[str, int] = {}

    for index, evaluation in enumerate(stamps):
        boundary = _as_utc(evaluation)

        # 1) Protective ticks while any LIVE1B position is open
        if engine.positions and boundary > last_stream_end:
            n_ex, px = _stream_protective(
                engine,
                ticks=ticks,
                start=last_stream_end,
                end=boundary,
                scan=protective_scan,
            )
            prot_n += n_ex
            tick_batches += 1
            if px is not None:
                last_px = px
            last_stream_end = boundary
        elif not engine.positions:
            last_stream_end = boundary

        # 2) Entry BBO = last trade at the tip. This must be re-read on EVERY cycle.
        # Previously it was refreshed only when flat and index % 4 == 0, while the
        # flat branch above streams no ticks at all, so an entry taken on a cycle
        # flat since the last refresh filled at a quote up to 45 minutes old —
        # worth +3.6 bps in the strategy's favour on exactly the fills that open
        # new positions.
        px = ticks.last_price_at_or_before(boundary)
        if px is not None:
            last_px = px
        if last_px is None:
            cut = int(pd.Series(m15_closes).searchsorted(boundary.to_datetime64(), side="right"))
            if cut <= 0:
                continue
            last_px = float(feed_m15.iloc[cut - 1]["close"])

        tip_ts = _ts_iso(boundary)
        _inject_bbo(engine, price=float(last_px), ts=tip_ts)

        cut = int(pd.Series(m15_closes).searchsorted(boundary.to_datetime64(), side="right"))
        if cut <= 0:
            continue
        visible = feed_m15.iloc[max(0, cut - 16) : cut]

        cycle = manager.run_cycle(
            evaluation_timestamp=evaluation,
            sources=sources,
            feed=visible,
            persist=True,
            decision_index=empty_decision_index,
        )
        applied, n_suppressed = _apply_commands(
            engine,
            list(cycle.get("commands") or []),
            allow_close=allow_command_close,
        )
        close_suppressed_n += n_suppressed
        for r in applied:
            st = str((r or {}).get("status") or "")
            if st.startswith("ENTRY_BLOCKED") or st.startswith("REJECTED"):
                open_block[st] = open_block.get(st, 0) + 1
        cmd_n += len(applied)

        if engine.positions and last_stream_end < boundary:
            last_stream_end = boundary

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
                        "protective_exits": prot_n,
                        "command_applies": cmd_n,
                        "tick_batches": tick_batches,
                        "last_px": last_px,
                        "open_blocks": open_block,
                        "elapsed_s": round(elapsed, 1),
                        "eta_s": None if eta is None else round(eta, 1),
                    },
                    default=str,
                ),
                flush=True,
            )

    bus.flush()
    engine.write_health()

    out_dir = SANDBOX / "lived_replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    trades = _export_trades(engine, out_dir)
    commands_df = bus.frame()
    if len(commands_df):
        commands_df[COMMAND_COLUMNS].to_parquet(out_dir / "manager_commands.parquet", index=False)

    reason_col = None
    for c in ("exit_reason", "trigger_type"):
        if len(trades) and c in trades.columns:
            reason_col = c
            break
    exit_counts: dict[str, int] = {}
    if reason_col:
        exit_counts = trades[reason_col].astype(str).value_counts().to_dict()

    by_tf: dict[str, Any] = {}
    if len(trades) and "timeframe" in trades.columns:
        for tf, g in trades.groupby(trades["timeframe"].astype(str).str.upper()):
            by_tf[str(tf)] = _bucket(g)
            if reason_col:
                by_tf[str(tf)]["exit_reasons"] = g[reason_col].astype(str).value_counts().to_dict()

    summary: dict[str, Any] = {
        "stage": "ETLL_HYBRID_TICK_LIVED_REPLAY",
        "status": "HYBRID_TICK_REPLAY_DONE",
        "model": "S41_MANAGER_PLUS_LIVE1B_EXECUTION_TICK",
        "contract": "S41_LIVE1B_HYBRID_TICK",
        "timeframes": list(TIMEFRAMES),
        "lifecycle_align": str(lifecycle_align),
        "lookahead_leak_present": str(lifecycle_align).lower() != "bar_close",
        "protective_scan": str(protective_scan),
        "entry_price_refresh": "every_cycle",
        "command_close": "enabled" if allow_command_close else "disabled",
        "ab_arm": "A_flip_close_on" if allow_command_close else "B_barrier_only",
        "anti_saw_enabled": False,
        "anti_saw_arm": "archived_bar_count_rails",
        "close_commands_suppressed": int(close_suppressed_n),
        "tick_cache": ticks.stats(),
        "paper_epoch_id": epoch.paper_epoch_id,
        "sandbox": str(SANDBOX),
        "tick_repo": str(tick_repo),
        "pack_root": str(resolve_pack_dir("M15").parent),
        "living_process_required": True,
        "cycles": len(stamps),
        "from_ts": str(stamps[0]),
        "to_ts": str(stamps[-1]),
        "closed_trades": int(len(trades)),
        "overall": _bucket(trades),
        "by_timeframe": by_tf,
        "exit_reason_counts": exit_counts,
        "protective_exits": prot_n,
        "command_applies": cmd_n,
        "tick_batches": tick_batches,
        "open_block_statuses": open_block,
        "open_at_end": sorted(engine.positions.keys()),
        "elapsed_seconds": round(time.time() - started, 1),
        "generated_at": _utc_now(),
        "fill_note": (
            "entry BBO = last aggTrade (bid=ask=last); "
            "protective TP/SL via LIVE1B update_from_trade on EXACT_AGG_TRADE"
        ),
        "external_trades_used": False,
    }
    (out_dir / "lived_replay_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    (SANDBOX / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    # Durable archive: local sandbox + MaksTiger (Optuna / calibration).
    books_src = Path(engine.books.root)
    written = _archive_epoch_artifacts(
        epoch_id=str(epoch.paper_epoch_id),
        books_src=books_src,
        out_dir=out_dir,
        summary=summary,
        durable_root=durable_archive_root,
    )
    summary["archive_roots"] = written
    if written:
        summary["archive_root"] = written[-1]
        summary["durable_archive_root"] = str(Path(durable_archive_root or DEFAULT_DURABLE_ARCHIVE) / epoch.paper_epoch_id)
    (SANDBOX / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    (out_dir / "lived_replay_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"archived": True, "archive_roots": written}, default=str), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tick-repo", type=Path, default=DEFAULT_TICK_REPO)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--from-ts", type=str, default=None)
    parser.add_argument("--to-ts", type=str, default=None)
    parser.add_argument("--flush-every", type=int, default=200)
    parser.add_argument(
        "--lifecycle-align",
        choices=("bar_close", "bar_open"),
        default="bar_close",
        help="bar_close = causal (default); bar_open = legacy one-period look-ahead",
    )
    parser.add_argument(
        "--protective-scan",
        choices=("vectorized", "naive"),
        default="vectorized",
        help="vectorized = skip provably non-triggering ticks (default); naive = feed every tick",
    )
    parser.add_argument(
        "--command-close",
        choices=("enabled", "disabled"),
        default="enabled",
        help="enabled = canonical Hybrid (arm A); disabled = barrier-only, TP/SL exits only (arm B)",
    )
    parser.add_argument(
        "--anti-saw",
        choices=("on", "off"),
        default="off",
        help="Ignored. Bar-count anti-saw is archived; this flag is a no-op.",
    )
    parser.add_argument("--no-fresh", action="store_true")
    parser.add_argument(
        "--durable-archive",
        type=Path,
        default=DEFAULT_DURABLE_ARCHIVE,
        help="MaksTiger (or other) durable archive root for books",
    )
    parser.add_argument(
        "--no-durable-archive",
        action="store_true",
        help="Skip MaksTiger durable copy (local sandbox archive only)",
    )
    parser.add_argument(
        "--pack-root",
        type=Path,
        default=None,
        help="ETLL pack root with living-process lifecycle. Default: MaksTiger cold packs.",
    )
    args = parser.parse_args()
    summary = run_hybrid_tick(
        tick_repo=args.tick_repo,
        limit=args.limit,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        flush_every=args.flush_every,
        fresh=not args.no_fresh,
        lifecycle_align=args.lifecycle_align,
        protective_scan=args.protective_scan,
        allow_command_close=(args.command_close == "enabled"),
        anti_saw=(args.anti_saw == "on"),
        durable_archive_root=None if args.no_durable_archive else args.durable_archive,
        pack_root=args.pack_root,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
