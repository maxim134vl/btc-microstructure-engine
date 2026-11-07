#!/usr/bin/env python3
"""Полный PDF-отчёт Hybrid Tick (RU) с инфографикой → local + MaksTiger."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = ROOT / "data/research/external_traders/etll_hybrid_tick"
DEFAULT_TRADES = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive/"
    "ETLL_HYBRID_TICK_V1_20260904_054345/books/trades.jsonl"
)
TIGER_ARCHIVE_ROOT = Path("/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive")
LOCAL_OUT = SANDBOX / "reports"
TIMEFRAMES = ("M15", "M30", "H1", "H4")
INITIAL_EQUITY = 100_000.0

# RU palette
C_BG = "#0f1419"
C_CARD = "#1a2332"
C_TEXT = "#e7ecf3"
C_MUTED = "#9aa7b8"
C_GREEN = "#3dd68c"
C_RED = "#f07178"
C_BLUE = "#59c2ff"
C_AMBER = "#ffcc66"
C_PURPLE = "#c3a6ff"


def _mpl(s: str) -> str:
    """Escape $ so Agg/PDF backends do not parse labels as mathtext."""
    return s.replace("$", r"\$")

TF_COLORS = {"M15": "#59c2ff", "M30": "#3dd68c", "H1": "#ffcc66", "H4": "#c3a6ff"}


def _setup_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": C_BG,
            "axes.facecolor": C_CARD,
            "axes.edgecolor": "#2a3545",
            "axes.labelcolor": C_TEXT,
            "text.color": C_TEXT,
            "xtick.color": C_MUTED,
            "ytick.color": C_MUTED,
            "grid.color": "#2a3545",
            "font.size": 9,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "figure.titlesize": 16,
        }
    )


def _money(v: float | None, digits: int = 0) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    sign = "+" if v > 0 else ""
    if abs(v) >= 1_000_000:
        s = f"{sign}{v/1_000_000:.{max(digits,1)}f} млн $"
    elif abs(v) >= 1_000:
        s = f"{sign}{v:,.{digits}f} $".replace(",", " ")
    else:
        s = f"{sign}{v:.{digits}f} $"
    return _mpl(s)


def _pct(v: float | None, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:+.{digits}f}%"


def _num(v: float | None, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{v:.{digits}f}"


def load_trades(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    df["timeframe"] = df["timeframe"].astype(str).str.upper()
    df["net_pnl_usd"] = pd.to_numeric(df["net_pnl_usd"], errors="coerce").fillna(0.0)
    df["gross_pnl_usd"] = pd.to_numeric(df.get("gross_pnl_usd"), errors="coerce")
    df["fees_usd"] = pd.to_numeric(df.get("fees_usd"), errors="coerce").fillna(0.0)
    df["slippage_usd"] = pd.to_numeric(df.get("slippage_usd"), errors="coerce").fillna(0.0)
    df["side"] = df.get("side", "UNK").astype(str).str.upper()
    df["exit_reason"] = df.get("exit_reason", "UNKNOWN").astype(str)

    # CRITICAL: equity / period charts MUST use market time.
    # exit_ts / execution_timestamp are wall-clock of the replay host (all collapse to run day).
    if "context_occurrence_timestamp" not in df.columns:
        raise RuntimeError("context_occurrence_timestamp missing — cannot build market-time analytics")
    market_ts = pd.to_datetime(df["context_occurrence_timestamp"], utc=True, errors="coerce", format="ISO8601")
    if int(market_ts.isna().sum()) > 0:
        raise RuntimeError(
            f"context_occurrence_timestamp has {int(market_ts.isna().sum())} nulls — refuse wall-clock fallback"
        )
    # Sanity: must span historical window, not only replay day
    span_days = (market_ts.max() - market_ts.min()).total_seconds() / 86400.0
    if span_days < 30:
        raise RuntimeError(
            f"market timestamp span only {span_days:.1f} days — refusing (likely wrong clock)"
        )

    df["market_ts"] = market_ts
    # Keep wall clock separately for forensics only (never for period/equity axes)
    df["wall_exit_ts"] = pd.to_datetime(df.get("exit_ts"), utc=True, errors="coerce")
    df["entry_ts"] = pd.to_datetime(df.get("entry_ts"), utc=True, errors="coerce")
    # Hold unknown when entry_ts absent (Hybrid paper often nulls entry_ts)
    df["hold_hours"] = (df["market_ts"] - df["entry_ts"]).dt.total_seconds() / 3600.0

    df = df.sort_values("market_ts").reset_index(drop=True)
    # Alias used by chart code
    df["exit_ts"] = df["market_ts"]
    market_naive = df["market_ts"].dt.tz_convert("UTC").dt.tz_localize(None)
    df["day"] = market_naive.dt.strftime("%Y-%m-%d")
    df["month"] = market_naive.dt.strftime("%Y-%m")
    df["quarter"] = market_naive.dt.to_period("Q").astype(str)
    df["year"] = market_naive.dt.strftime("%Y")
    return df


@dataclass
class SliceStats:
    n: int
    wr: float
    pf: float | None
    net: float
    ret_pct: float
    avg_win: float | None
    avg_loss: float | None
    expectancy: float
    max_dd_pct: float
    max_dd_usd: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    recovery_factor: float | None
    recovery_hours: float | None
    best_trade: dict[str, Any] | None
    worst_trade: dict[str, Any] | None
    max_daily_ret_pct: float | None
    min_daily_ret_pct: float | None
    max_daily_pnl: float | None
    min_daily_pnl: float | None
    avg_hold_h: float | None
    exit_mix: dict[str, int]
    equity_end: float


def _equity_curve(pnls: list[float], initial: float) -> np.ndarray:
    eq = np.empty(len(pnls) + 1, dtype=float)
    eq[0] = initial
    for i, p in enumerate(pnls):
        eq[i + 1] = eq[i] + p
    return eq


def _max_dd(equity: np.ndarray) -> tuple[float, float, int, int]:
    peak = equity[0]
    peak_i = 0
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    trough_i = 0
    start_i = 0
    for i, e in enumerate(equity):
        if e >= peak:
            peak = e
            peak_i = i
        dd_usd = e - peak
        dd_pct = dd_usd / peak * 100.0 if peak > 0 else 0.0
        if dd_pct < max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd_usd
            trough_i = i
            start_i = peak_i
    return max_dd_pct, max_dd_usd, start_i, trough_i


def _recovery_hours(equity: np.ndarray, times: pd.Series, trough_i: int, peak_start_i: int) -> float | None:
    """Hours from trough until equity recovers to pre-drawdown peak."""
    if trough_i <= 0 or trough_i >= len(equity):
        return None
    peak_level = equity[peak_start_i]
    for j in range(trough_i, len(equity)):
        if equity[j] >= peak_level:
            t0 = times.iloc[max(0, trough_i - 1)] if trough_i > 0 else times.iloc[0]
            # equity index 0 = start; trade i closes at times[i-1]
            t_trough = times.iloc[trough_i - 1] if trough_i >= 1 else times.iloc[0]
            t_rec = times.iloc[j - 1] if j >= 1 else times.iloc[0]
            return max(0.0, (t_rec - t_trough).total_seconds() / 3600.0)
    return None  # not recovered


def _risk_ratios(equity: np.ndarray, times: pd.Series) -> tuple[float | None, float | None, float | None]:
    if len(equity) < 3:
        return None, None, None
    rets = np.diff(equity) / equity[:-1]
    rets = rets[np.isfinite(rets)]
    if len(rets) < 2:
        return None, None, None
    mean_r = float(np.mean(rets))
    std = float(np.std(rets, ddof=1))
    downside = rets[rets < 0]
    dstd = float(np.sqrt(np.mean(downside**2))) if len(downside) else 0.0
    span_days = max((times.iloc[-1] - times.iloc[0]).total_seconds() / 86400.0, 1e-9)
    ppy = len(rets) / (span_days / 365.25)
    scale = math.sqrt(ppy) if ppy > 0 else 1.0
    sharpe = (mean_r / std * scale) if std > 0 else None
    sortino = (mean_r / dstd * scale) if dstd > 0 else None
    max_dd_pct, _, _, _ = _max_dd(equity)
    total_ret = equity[-1] / equity[0] - 1.0
    try:
        ann = (equity[-1] / equity[0]) ** (365.25 / span_days) - 1.0
    except OverflowError:
        ann = None
    calmar = None
    if ann is not None and math.isfinite(ann) and max_dd_pct < 0:
        calmar = ann * 100.0 / abs(max_dd_pct)
    return sharpe, sortino, calmar


def analyze(df: pd.DataFrame, *, initial: float) -> SliceStats:
    pnls = df["net_pnl_usd"].astype(float).tolist()
    equity = _equity_curve(pnls, initial)
    max_dd_pct, max_dd_usd, peak_i, trough_i = _max_dd(equity)
    sharpe, sortino, calmar = _risk_ratios(equity, df["exit_ts"])
    wins = df.loc[df["net_pnl_usd"] > 0, "net_pnl_usd"]
    losses = df.loc[df["net_pnl_usd"] < 0, "net_pnl_usd"]
    gp = float(wins.sum()) if len(wins) else 0.0
    gl = float(abs(losses.sum())) if len(losses) else 0.0
    pf = (gp / gl) if gl > 0 else None
    net = float(df["net_pnl_usd"].sum())
    best_idx = int(df["net_pnl_usd"].idxmax()) if len(df) else None
    worst_idx = int(df["net_pnl_usd"].idxmin()) if len(df) else None

    def _trade_card(idx: int | None) -> dict[str, Any] | None:
        if idx is None:
            return None
        r = df.loc[idx]
        return {
            "trade_id": str(r.get("trade_id") or r.get("position_id") or ""),
            "timeframe": str(r["timeframe"]),
            "side": str(r["side"]),
            "net_pnl_usd": float(r["net_pnl_usd"]),
            "exit_reason": str(r["exit_reason"]),
            "entry_ts": r["entry_ts"].isoformat() if pd.notna(r["entry_ts"]) else None,
            "exit_ts": r["exit_ts"].isoformat() if pd.notna(r["exit_ts"]) else None,
            "hold_hours": float(r["hold_hours"]) if pd.notna(r["hold_hours"]) else None,
            "entry_price": float(r["entry_price"]) if pd.notna(r.get("entry_price")) else None,
            "exit_price": float(r["exit_price"]) if pd.notna(r.get("exit_price")) else None,
        }

    daily = df.groupby("day", sort=True)["net_pnl_usd"].sum()
    # daily return vs running equity at start of day
    eq_map = {}
    run_eq = initial
    daily_ret = {}
    for day, pnl in daily.items():
        daily_ret[day] = pnl / run_eq * 100.0 if run_eq else 0.0
        eq_map[day] = run_eq + pnl
        run_eq += pnl

    recovery_h = _recovery_hours(equity, df["exit_ts"], trough_i, peak_i)
    recovery_factor = (net / abs(max_dd_usd)) if max_dd_usd < 0 else None

    return SliceStats(
        n=int(len(df)),
        wr=float((df["net_pnl_usd"] > 0).mean()) if len(df) else 0.0,
        pf=pf,
        net=net,
        ret_pct=(equity[-1] / initial - 1.0) * 100.0 if initial else 0.0,
        avg_win=float(wins.mean()) if len(wins) else None,
        avg_loss=float(losses.mean()) if len(losses) else None,
        expectancy=float(df["net_pnl_usd"].mean()) if len(df) else 0.0,
        max_dd_pct=max_dd_pct,
        max_dd_usd=max_dd_usd,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        recovery_factor=recovery_factor,
        recovery_hours=recovery_h,
        best_trade=_trade_card(best_idx),
        worst_trade=_trade_card(worst_idx),
        max_daily_ret_pct=max(daily_ret.values()) if daily_ret else None,
        min_daily_ret_pct=min(daily_ret.values()) if daily_ret else None,
        max_daily_pnl=float(daily.max()) if len(daily) else None,
        min_daily_pnl=float(daily.min()) if len(daily) else None,
        avg_hold_h=float(df["hold_hours"].mean()) if len(df) else None,
        exit_mix=df["exit_reason"].astype(str).value_counts().to_dict(),
        equity_end=float(equity[-1]),
    )


def _page_cover(pdf: PdfPages, overall: SliceStats, epoch: str, span: str) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape
    fig.patch.set_facecolor(C_BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0.05, 0.88, "HYBRID TICK · S4.1 + LIVE1B", fontsize=14, color=C_BLUE, fontweight="bold")
    ax.text(0.05, 0.78, "Полная аналитика результатов модели", fontsize=26, color=C_TEXT, fontweight="bold")
    ax.text(0.05, 0.70, "BTCUSDT · exact aggTrade · 4 таймфрейма (M15/M30/H1/H4)", fontsize=12, color=C_MUTED)
    ax.text(0.05, 0.62, f"Эпоха: {epoch}", fontsize=10, color=C_MUTED)
    ax.text(0.05, 0.57, f"Окно: {span}", fontsize=10, color=C_MUTED)
    ax.text(0.05, 0.52, f"Стартовый депозит: {_money(INITIAL_EQUITY)}", fontsize=10, color=C_MUTED)

    cards = [
        ("Сделок", f"{overall.n}"),
        ("Доходность", _pct(overall.ret_pct, 1)),
        ("Чистый PnL", _money(overall.net, 0)),
        ("Win Rate", f"{overall.wr*100:.1f}%"),
        ("Profit Factor", _num(overall.pf, 2)),
        ("Max DD", _pct(overall.max_dd_pct, 2)),
        ("Sharpe", _num(overall.sharpe, 2)),
        ("Recovery", _num(overall.recovery_factor, 1)),
    ]
    for i, (label, val) in enumerate(cards):
        x = 0.05 + (i % 4) * 0.23
        y = 0.32 - (i // 4) * 0.18
        ax.add_patch(plt.Rectangle((x, y), 0.21, 0.14, facecolor=C_CARD, edgecolor="#2a3545", lw=1.5))
        ax.text(x + 0.01, y + 0.09, label, fontsize=9, color=C_MUTED)
        ax.text(x + 0.01, y + 0.03, val, fontsize=16, color=C_GREEN if i in (1, 2, 3, 4, 6, 7) else C_TEXT, fontweight="bold")

    ax.text(
        0.05,
        0.08,
        "Ось времени: context_occurrence_timestamp (рынок 2023-12→2026-07).\n"
        "НЕ используется wall-clock exit_ts прогона.",
        fontsize=9,
        color=C_AMBER,
    )
    pdf.savefig(fig)
    plt.close(fig)


def _kpi_table_page(pdf: PdfPages, by_tf: dict[str, SliceStats], overall: SliceStats) -> None:
    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    fig.patch.set_facecolor(C_BG)
    ax.set_axis_off()
    ax.set_title("Сводные KPI · overall и по таймфреймам", pad=20, color=C_TEXT)

    headers = [
        "Срез",
        "N",
        "Доходность",
        "Net PnL",
        "WR",
        "PF",
        "Sharpe",
        "Sortino",
        "Calmar",
        "MaxDD%",
        "Recovery",
        "Восст. ч",
    ]
    rows = []
    rows.append(
        [
            "ALL",
            str(overall.n),
            _pct(overall.ret_pct, 1),
            _money(overall.net, 0),
            f"{overall.wr*100:.1f}%",
            _num(overall.pf, 2),
            _num(overall.sharpe, 2),
            _num(overall.sortino, 2),
            _num(overall.calmar, 2),
            _pct(overall.max_dd_pct, 2),
            _num(overall.recovery_factor, 1),
            _num(overall.recovery_hours, 1) if overall.recovery_hours is not None else "не восст.",
        ]
    )
    for tf in TIMEFRAMES:
        s = by_tf[tf]
        rows.append(
            [
                tf,
                str(s.n),
                _pct(s.ret_pct, 1),
                _money(s.net, 0),
                f"{s.wr*100:.1f}%",
                _num(s.pf, 2),
                _num(s.sharpe, 2),
                _num(s.sortino, 2),
                _num(s.calmar, 2),
                _pct(s.max_dd_pct, 2),
                _num(s.recovery_factor, 1),
                _num(s.recovery_hours, 1) if s.recovery_hours is not None else "не восст.",
            ]
        )

    table = ax.table(cellText=rows, colLabels=headers, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.1, 1.8)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#2a3545")
        if r == 0:
            cell.set_facecolor("#243044")
            cell.set_text_props(color=C_TEXT, fontweight="bold")
        else:
            cell.set_facecolor(C_CARD if r % 2 else "#15202b")
            cell.set_text_props(color=C_TEXT)
    fig.text(
        0.05,
        0.06,
        _mpl("Recovery = Net / |MaxDD$| · Восст. ч = часы от дна просадки до возврата к пику (market time)."),
        color=C_MUTED,
        fontsize=8,
    )
    pdf.savefig(fig)
    plt.close(fig)


def _returns_bars(pdf: PdfPages, by_tf: dict[str, SliceStats], overall: SliceStats) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.69, 8.27))
    fig.suptitle("Итоговая доходность и чистый PnL по таймфреймам", color=C_TEXT)

    tfs = list(TIMEFRAMES)
    rets = [by_tf[t].ret_pct for t in tfs]
    nets = [by_tf[t].net for t in tfs]
    colors = [TF_COLORS[t] for t in tfs]

    ax = axes[0]
    bars = ax.bar(tfs, rets, color=colors)
    ax.axhline(0, color=C_MUTED, lw=0.8)
    ax.set_ylabel("Доходность, % к депозиту 100k")
    ax.set_title("Доходность %")
    ax.grid(axis="y", alpha=0.3)
    for b, v in zip(bars, rets):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{v:+.0f}%", ha="center", va="bottom", fontsize=8)

    ax = axes[1]
    bars = ax.bar(tfs, [n / 1e6 for n in nets], color=colors)
    ax.set_ylabel(_mpl("Net PnL, млн $"))
    ax.set_title("Чистый PnL")
    ax.grid(axis="y", alpha=0.3)
    for b, v in zip(bars, nets):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{v/1e6:.2f}", ha="center", va="bottom", fontsize=8)

    fig.text(0.5, 0.02, f"ALL: {_pct(overall.ret_pct, 1)} · {_money(overall.net, 0)}", ha="center", color=C_MUTED)
    pdf.savefig(fig)
    plt.close(fig)


def _equity_page(pdf: PdfPages, df: pd.DataFrame, by_tf: dict[str, SliceStats]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27), sharex=False)
    fig.suptitle("Кривые капитала (market time = context_occurrence_timestamp)", color=C_TEXT)

    # overall
    ax = axes[0]
    eq = _equity_curve(df["net_pnl_usd"].tolist(), INITIAL_EQUITY)
    ax.plot(df["exit_ts"], eq[1:], color=C_BLUE, lw=1.2)
    ax.fill_between(df["exit_ts"], INITIAL_EQUITY, eq[1:], where=eq[1:] >= INITIAL_EQUITY, color=C_GREEN, alpha=0.15)
    ax.fill_between(df["exit_ts"], INITIAL_EQUITY, eq[1:], where=eq[1:] < INITIAL_EQUITY, color=C_RED, alpha=0.2)
    ax.set_title("ALL · кумулятивный equity")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M"))
    ax.grid(alpha=0.3)

    ax = axes[1]
    for tf in TIMEFRAMES:
        part = df[df["timeframe"] == tf]
        if not len(part):
            continue
        eq_tf = _equity_curve(part["net_pnl_usd"].tolist(), INITIAL_EQUITY)
        ax.plot(part["exit_ts"], eq_tf[1:], color=TF_COLORS[tf], lw=1.1, label=f"{tf} ({_pct(by_tf[tf].ret_pct,0)})")
    ax.legend(loc="upper left", facecolor=C_CARD, edgecolor="#2a3545")
    ax.set_title("По таймфреймам (каждый от отдельного депозита 100k)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M"))
    ax.grid(alpha=0.3)
    fig.tight_layout(rect=[0, 0.02, 1, 0.95])
    pdf.savefig(fig)
    plt.close(fig)


def _daily_page(pdf: PdfPages, df: pd.DataFrame, overall: SliceStats) -> None:
    daily = df.groupby("day", sort=True)["net_pnl_usd"].sum()
    run_eq = INITIAL_EQUITY
    daily_ret = []
    for pnl in daily.values:
        daily_ret.append(pnl / run_eq * 100.0 if run_eq else 0.0)
        run_eq += pnl
    days = list(daily.index)
    rets = np.array(daily_ret)
    pnls = daily.values

    fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
    fig.suptitle("Дневная доходность и PnL", color=C_TEXT)

    ax = axes[0]
    colors = [C_GREEN if v >= 0 else C_RED for v in rets]
    ax.bar(range(len(rets)), rets, color=colors, width=1.0)
    ax.set_title(
        f"Дневная доходность % · макс {_pct(overall.max_daily_ret_pct)} · мин {_pct(overall.min_daily_ret_pct)}"
    )
    ax.set_ylabel("%")
    ax.grid(axis="y", alpha=0.3)
    step = max(1, len(days) // 12)
    ax.set_xticks(range(0, len(days), step))
    ax.set_xticklabels([days[i] for i in range(0, len(days), step)], rotation=30, ha="right")

    ax = axes[1]
    colors = [C_GREEN if v >= 0 else C_RED for v in pnls]
    ax.bar(range(len(pnls)), pnls, color=colors, width=1.0)
    ax.set_title(_mpl(f"Дневной PnL $ · макс {_money(overall.max_daily_pnl)} · мин {_money(overall.min_daily_pnl)}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}k"))
    ax.grid(axis="y", alpha=0.3)
    ax.set_xticks(range(0, len(days), step))
    ax.set_xticklabels([days[i] for i in range(0, len(days), step)], rotation=30, ha="right")
    fig.tight_layout(rect=[0, 0.02, 1, 0.95])
    pdf.savefig(fig)
    plt.close(fig)


def _best_worst_page(pdf: PdfPages, df: pd.DataFrame, by_tf: dict[str, SliceStats], overall: SliceStats) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.suptitle("Лучшие и худшие сделки · recovery", color=C_TEXT)
    ax = fig.add_axes([0.04, 0.05, 0.92, 0.85])
    ax.set_axis_off()

    def block(title: str, trade: dict[str, Any] | None, y: float, color: str) -> None:
        ax.text(0.02, y, title, fontsize=12, color=color, fontweight="bold")
        if not trade:
            ax.text(0.02, y - 0.05, "нет данных", color=C_MUTED)
            return
        lines = [
            f"TF {trade['timeframe']} · {trade['side']} · {_money(trade['net_pnl_usd'], 2)}",
            f"Выход: {trade['exit_reason']} · удержание {_num(trade.get('hold_hours'), 2)} ч",
            f"Entry {trade.get('entry_price')} → Exit {trade.get('exit_price')}",
            f"ID: {trade.get('trade_id')}",
            f"Время: {trade.get('entry_ts')} → {trade.get('exit_ts')}",
        ]
        for i, line in enumerate(lines):
            ax.text(0.02, y - 0.04 - i * 0.035, line, fontsize=9, color=C_TEXT, family="monospace")

    block("ЛУЧШАЯ СДЕЛКА (ALL)", overall.best_trade, 0.92, C_GREEN)
    block("ХУДШАЯ СДЕЛКА (ALL)", overall.worst_trade, 0.68, C_RED)

    y = 0.42
    ax.text(0.02, y, "По таймфреймам", fontsize=12, color=C_BLUE, fontweight="bold")
    y -= 0.04
    for tf in TIMEFRAMES:
        s = by_tf[tf]
        b, w = s.best_trade, s.worst_trade
        ax.text(
            0.02,
            y,
            f"{tf}: best {_money(b['net_pnl_usd'] if b else None, 0)} ({b['exit_reason'] if b else '—'})  |  "
            f"worst {_money(w['net_pnl_usd'] if w else None, 0)} ({w['exit_reason'] if w else '—'})  |  "
            f"recovery {_num(s.recovery_factor,1)} · восст. {_num(s.recovery_hours,1) if s.recovery_hours is not None else '∞'} ч",
            fontsize=9,
            color=C_TEXT,
        )
        y -= 0.045

    ax.text(
        0.02,
        0.08,
        f"ALL recovery factor {_num(overall.recovery_factor, 2)} · скорость восстановления после MaxDD: "
        f"{_num(overall.recovery_hours, 1) if overall.recovery_hours is not None else 'не восстановлен до конца выборки'} ч",
        fontsize=10,
        color=C_AMBER,
    )
    pdf.savefig(fig)
    plt.close(fig)

    # Top-10 table page
    fig, axes = plt.subplots(1, 2, figsize=(11.69, 8.27))
    fig.suptitle("Топ-10 лучших и худших сделок", color=C_TEXT)
    top = df.nlargest(10, "net_pnl_usd")
    bot = df.nsmallest(10, "net_pnl_usd")

    def _tbl(ax, frame: pd.DataFrame, title: str) -> None:
        ax.set_axis_off()
        ax.set_title(title)
        data = []
        for _, r in frame.iterrows():
            data.append(
                [
                    str(r["timeframe"]),
                    str(r["side"])[:1],
                    f"{r['net_pnl_usd']:.0f}",
                    str(r["exit_reason"])[:12],
                    r["exit_ts"].strftime("%Y-%m-%d"),
                ]
            )
        t = ax.table(
            cellText=data,
            colLabels=["TF", "S", "PnL$", "Exit", "Дата"],
            loc="center",
            cellLoc="center",
        )
        t.auto_set_font_size(False)
        t.set_fontsize(8)
        t.scale(1.0, 1.5)
        for (r, c), cell in t.get_celld().items():
            cell.set_edgecolor("#2a3545")
            cell.set_facecolor("#243044" if r == 0 else C_CARD)
            cell.set_text_props(color=C_TEXT)

    _tbl(axes[0], top, "Top-10 прибыль")
    _tbl(axes[1], bot, "Top-10 убыток")
    pdf.savefig(fig)
    plt.close(fig)


def _period_incomplete_note(df: pd.DataFrame) -> str:
    t0 = df["market_ts"].min()
    t1 = df["market_ts"].max()
    return _mpl(
        f"Окно выборки: {t0.date()} → {t1.date()}. "
        f"2023* = неполный год (только хвост декабря, ~{ (pd.Timestamp('2024-01-01', tz='UTC') - t0).days } дн.). "
        f"2026* = неполный год (данные до {t1.date()}, не весь календарный год). "
        "Главный график = абсолютный Net $ и доля от суммарного PnL. "
        "Доходность % к equity на начало периода раздувает ранние месяцы (маленькая база) — см. вторичную ось/подпись, не путать с «весь профит»."
    )


def _label_period(key: str, kind: str) -> str:
    k = str(key)
    if kind == "year":
        if k == "2023":
            return "2023*"
        if k == "2026":
            return "2026*"
        return k
    if kind == "quarter":
        if k.startswith("2023"):
            return f"{k}*"
        if k.startswith("2026Q3") or k == "2026Q3":
            return f"{k}*"
        return k
    if kind == "month":
        if k.startswith("2023-") or k.startswith("2026-08") or k.startswith("2026-09") or k.startswith("2026-10") or k.startswith("2026-11") or k.startswith("2026-12"):
            return f"{k}*"
        if k.startswith("2026-07"):
            return f"{k}*"
        return k
    return k


def _period_page(pdf: PdfPages, df: pd.DataFrame, period: str, title: str) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
    fig.suptitle(_mpl(title + " · абсолютный Net $ (не % к депозиту)"), color=C_TEXT)

    g = df.groupby(period, sort=True)["net_pnl_usd"].sum()
    total = float(g.sum()) if float(g.sum()) else 1.0
    shares = (g / total * 100.0).values
    labels = [_label_period(k, period) for k in g.index]

    # Primary: absolute $
    ax = axes[0]
    colors = [C_GREEN if v >= 0 else C_RED for v in g.values]
    bars = ax.bar(range(len(g)), g.values / 1e3, color=colors)
    ax.set_ylabel(_mpl("Net PnL, тыс. $"))
    ax.set_title(_mpl("Абсолютный PnL периода (тыс. $) + доля от всего, %"))
    ax.grid(axis="y", alpha=0.3)
    ax.set_xticks(range(len(g)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    for i, (b, sh) in enumerate(zip(bars, shares)):
        ax.text(
            b.get_x() + b.get_width() / 2,
            b.get_height(),
            f"{sh:.0f}%",
            ha="center",
            va="bottom",
            fontsize=6,
            color=C_MUTED,
        )

    # Secondary: stacked $ by TF (absolute)
    ax = axes[1]
    pivot = df.pivot_table(index=period, columns="timeframe", values="net_pnl_usd", aggfunc="sum", fill_value=0)
    for tf in TIMEFRAMES:
        if tf not in pivot.columns:
            pivot[tf] = 0.0
    pivot = pivot[list(TIMEFRAMES)]
    bottom = np.zeros(len(pivot))
    x = range(len(pivot))
    for tf in TIMEFRAMES:
        vals = pivot[tf].values.astype(float)
        ax.bar(x, vals / 1e3, bottom=bottom / 1e3, color=TF_COLORS[tf], label=tf)
        bottom = bottom + vals
    ax.legend(facecolor=C_CARD, edgecolor="#2a3545", fontsize=8)
    ax.set_title(_mpl("Net PnL по TF, тыс. $ (stacked)"))
    ax.set_xticks(list(x))
    ax.set_xticklabels([_label_period(k, period) for k in pivot.index], rotation=45, ha="right", fontsize=7)
    ax.set_ylabel(_mpl("тыс. $"))
    ax.grid(axis="y", alpha=0.3)

    fig.text(0.5, 0.01, _period_incomplete_note(df), ha="center", va="bottom", fontsize=7, color=C_AMBER, wrap=True)
    fig.tight_layout(rect=[0, 0.06, 1, 0.94])
    pdf.savefig(fig)
    plt.close(fig)

    # Companion page: return% ONLY as secondary view with explicit warning
    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    fig.suptitle(title + " · доходность % к equity на СТАРТ периода (вторичный вид)", color=C_TEXT)
    run = INITIAL_EQUITY
    rets = []
    eq_starts = []
    for pnl in g.values:
        eq_starts.append(run)
        rets.append(pnl / run * 100.0 if run else 0.0)
        run += float(pnl)
    colors = [C_GREEN if v >= 0 else C_RED for v in rets]
    ax.bar(range(len(g)), rets, color=colors)
    ax.set_ylabel("% к equity на начало периода")
    ax.set_xticks(range(len(g)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.grid(axis="y", alpha=0.3)
    ax.set_title("ВНИМАНИЕ: ранние периоды выглядят огромными из‑за маленькой базы equity")
    for i, (r, eq0, pnl) in enumerate(zip(rets, eq_starts, g.values)):
        if i % max(1, len(g) // 8) == 0 or abs(r) == max(abs(x) for x in rets):
            ax.text(i, r, f"база {eq0/1e3:.0f}k", ha="center", va="bottom", fontsize=6, color=C_MUTED)
    fig.text(
        0.5,
        0.02,
        _mpl("Не интерпретировать как «весь профит здесь». Смотрите страницу с абсолютным Net $ и долей % от суммарного PnL. ")
        + _period_incomplete_note(df),
        ha="center",
        fontsize=7,
        color=C_AMBER,
    )
    fig.tight_layout(rect=[0, 0.08, 1, 0.93])
    pdf.savefig(fig)
    plt.close(fig)


def _exits_holds_page(pdf: PdfPages, df: pd.DataFrame, by_tf: dict[str, SliceStats]) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27))
    fig.suptitle("Типы выходов · S41 CLOSE · удержание", color=C_TEXT)

    # overall exits
    ax = axes[0, 0]
    mix = df["exit_reason"].value_counts()
    ax.pie(mix.values, labels=mix.index, autopct="%1.0f%%", colors=[C_GREEN, C_BLUE, C_RED, C_AMBER][: len(mix)])
    ax.set_title("ALL · причины выхода")

    ax = axes[0, 1]
    pivot = df.pivot_table(index="timeframe", columns="exit_reason", values="trade_id", aggfunc="count", fill_value=0)
    pivot = pivot.reindex(list(TIMEFRAMES))
    pivot.plot(kind="bar", stacked=True, ax=ax, color=[C_GREEN, C_BLUE, C_RED, C_AMBER, C_PURPLE][: pivot.shape[1]])
    ax.set_title("Выходы по TF")
    ax.legend(fontsize=7, facecolor=C_CARD)
    ax.grid(axis="y", alpha=0.3)

    # S41 COMMAND CLOSE win/loss
    ax = axes[1, 0]
    s41 = df[df["exit_reason"].astype(str).str.upper().str.contains("S41_COMMAND_CLOSE")]
    if len(s41):
        wins = int((s41["net_pnl_usd"] > 0).sum())
        losses = int((s41["net_pnl_usd"] < 0).sum())
        flats = int((s41["net_pnl_usd"] == 0).sum())
        ax.bar(
            ["Прибыль", "Убыток", "0"],
            [wins, losses, flats],
            color=[C_GREEN, C_RED, C_MUTED],
        )
        ax.set_title(f"S41_COMMAND_CLOSE · win/loss (n={len(s41)})")
        ax.grid(axis="y", alpha=0.3)
        for i, v in enumerate([wins, losses, flats]):
            ax.text(i, v, str(v), ha="center", va="bottom", fontsize=9, color=C_TEXT)
    else:
        ax.set_axis_off()
        ax.text(0.5, 0.5, "нет S41_COMMAND_CLOSE", ha="center", color=C_MUTED)

    ax = axes[1, 1]
    ax.set_axis_off()
    lines = ["S41_COMMAND_CLOSE — разрез", ""]
    if len(s41):
        w_pnl = float(s41.loc[s41["net_pnl_usd"] > 0, "net_pnl_usd"].sum())
        l_pnl = float(s41.loc[s41["net_pnl_usd"] < 0, "net_pnl_usd"].sum())
        lines.append(f"Всего: {len(s41)}  WR={(s41['net_pnl_usd']>0).mean()*100:.1f}%")
        lines.append(f"Прибыльных: {wins} · сумма {_money(w_pnl, 0)}")
        lines.append(f"Убыточных: {losses} · сумма {_money(l_pnl, 0)}")
        lines.append(f"Net S41: {_money(float(s41['net_pnl_usd'].sum()), 0)}")
        lines.append("")
        lines.append("По TF (win / loss / net):")
        for tf in TIMEFRAMES:
            part = s41[s41["timeframe"] == tf]
            if not len(part):
                continue
            tw = int((part["net_pnl_usd"] > 0).sum())
            tl = int((part["net_pnl_usd"] < 0).sum())
            lines.append(f"  {tf}: {tw}/{tl} · {_money(float(part['net_pnl_usd'].sum()), 0)}")
        hold_ok = df["hold_hours"].dropna()
        lines.append("")
        if len(hold_ok):
            lines.append(f"Hold (где есть entry_ts): n={len(hold_ok)} median={hold_ok.median():.1f}ч")
        else:
            lines.append("Hold: entry_ts в books пустой — длительность по market clock недоступна")
    ax.text(0.0, 0.95, "\n".join(lines), fontsize=9, color=C_TEXT, family="monospace", va="top")
    fig.tight_layout(rect=[0, 0.02, 1, 0.95])
    pdf.savefig(fig)
    plt.close(fig)

    # Extra page: S41 PnL distribution + by TF stacked win/loss
    fig, axes = plt.subplots(1, 2, figsize=(11.69, 8.27))
    fig.suptitle("S41_COMMAND_CLOSE · прибыль vs убыток детально", color=C_TEXT)
    ax = axes[0]
    if len(s41):
        ax.hist(
            [s41.loc[s41["net_pnl_usd"] > 0, "net_pnl_usd"], s41.loc[s41["net_pnl_usd"] < 0, "net_pnl_usd"]],
            bins=40,
            color=[C_GREEN, C_RED],
            label=["Прибыль", "Убыток"],
            stacked=False,
        )
        ax.legend(facecolor=C_CARD)
        ax.set_title("Распределение PnL S41 CLOSE")
        ax.set_xlabel("net_pnl_usd")
        ax.grid(axis="y", alpha=0.3)
    ax = axes[1]
    if len(s41):
        rows_w = []
        rows_l = []
        for tf in TIMEFRAMES:
            part = s41[s41["timeframe"] == tf]
            rows_w.append(int((part["net_pnl_usd"] > 0).sum()))
            rows_l.append(int((part["net_pnl_usd"] < 0).sum()))
        x = np.arange(len(TIMEFRAMES))
        ax.bar(x - 0.2, rows_w, width=0.4, color=C_GREEN, label="Прибыль")
        ax.bar(x + 0.2, rows_l, width=0.4, color=C_RED, label="Убыток")
        ax.set_xticks(x)
        ax.set_xticklabels(list(TIMEFRAMES))
        ax.legend(facecolor=C_CARD)
        ax.set_title("S41 CLOSE · число сделок win/loss по TF")
        ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(rect=[0, 0.02, 1, 0.95])
    pdf.savefig(fig)
    plt.close(fig)


def _methodology_page(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_axes([0.06, 0.06, 0.88, 0.88])
    ax.set_axis_off()
    ax.set_title("Методология и ограничения", color=C_TEXT, fontsize=14, pad=12)
    text = """
Контракт исполнения: S4.1 Manager → LIVE1B IntrabarPaperEngine (Hybrid).
Вход: синтетический локальный BBO = last aggTrade (bid=ask=last).
Защитные TP/SL: engine.update_from_trade на EXACT_AGG_TRADE (цена в моменте).
Закрытие по контексту: команды S4.1 CLOSE (CONTEXT_FLIP / lifecycle).

Депозит: 100 000 USD на каждый срез отчёта (overall и каждый TF считаются
отдельной кривой капитала от 100k — так сравнимы доходности по ТФ).
Overall = одна общая книга всех TF (портфельный путь).

Время: market occurrence (context_occurrence_timestamp), не wall-clock.
Издержки: fees + slippage из paper config (уже в net_pnl_usd).

Неполные календарные периоды (важно):
• 2023* — в выборке только хвост декабря (~с 17.12), не год.
• 2026* — данные до ~24.07, не полный календарный год.
Помечены звёздочкой на срезах. Не сравнивать с полными годами «в лоб».

Как читать срезы месяц/квартал/год:
• Основной график = абсолютный Net $ и доля от суммарного PnL.
• Доходность % к equity на СТАРТ периода — вторичный вид: ранние периоды
  выглядят огромными из‑за маленькой базы (~100–160k). Это НЕ значит, что
  «весь профит сделал 2024Q1». В долларах профит распределён по 2024–2026.

Метрики:
• Доходность % = (equity_end / 100k − 1) × 100
• MaxDD % / $ — от пика equity
• Recovery factor = Net PnL / |MaxDD $|
• Скорость восстановления — часы от дна MaxDD до возврата к пику
• Sharpe / Sortino / Calmar — на event-time доходностях сделок, annualised по календарю
• Дневная доходность — PnL дня / equity на начало дня

Ограничения: paper replay; BBO без исторического bookTicker; не live fills.
Книги для Optuna: MaksTiger .../etll_hybrid_tick/archive/<epoch>/books/
"""
    ax.text(0.0, 0.98, _mpl(text.strip()), va="top", fontsize=9, color=C_TEXT, family="monospace")
    pdf.savefig(fig)
    plt.close(fig)


def build_pdf(df: pd.DataFrame, *, out_path: Path, epoch: str) -> dict[str, Any]:
    _setup_style()
    overall = analyze(df, initial=INITIAL_EQUITY)
    by_tf = {tf: analyze(df[df["timeframe"] == tf].copy(), initial=INITIAL_EQUITY) for tf in TIMEFRAMES}
    span = f"{df['exit_ts'].iloc[0].date()} → {df['exit_ts'].iloc[-1].date()}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(out_path) as pdf:
        _page_cover(pdf, overall, epoch, span)
        _kpi_table_page(pdf, by_tf, overall)
        _returns_bars(pdf, by_tf, overall)
        _equity_page(pdf, df, by_tf)
        _daily_page(pdf, df, overall)
        _best_worst_page(pdf, df, by_tf, overall)
        _period_page(pdf, df, "month", "Месячный разрез")
        _period_page(pdf, df, "quarter", "Квартальный разрез")
        _period_page(pdf, df, "year", "Годовой разрез")
        _exits_holds_page(pdf, df, by_tf)
        _methodology_page(pdf)
        d = pdf.infodict()
        d["Title"] = "Hybrid Tick — полная аналитика"
        d["Author"] = "btc-ml research"
        d["Subject"] = epoch

    payload = {
        "epoch": epoch,
        "span": span,
        "overall": overall.__dict__,
        "by_timeframe": {tf: by_tf[tf].__dict__ for tf in TIMEFRAMES},
        "pdf": str(out_path),
    }
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    ap.add_argument("--epoch", type=str, default="ETLL_HYBRID_TICK_V1_20260904_054345")
    ap.add_argument("--out-name", type=str, default="HYBRID_TICK_FULL_ANALYTICS_RU.pdf")
    args = ap.parse_args()

    trades_path = args.trades
    if not trades_path.exists():
        alt = (
            SANDBOX
            / "data/trading/intrabar_paper"
            / args.epoch
            / "books"
            / "trades.jsonl"
        )
        if alt.exists():
            trades_path = alt
        else:
            raise FileNotFoundError(trades_path)

    df = load_trades(trades_path)
    year_counts = df["year"].value_counts().sort_index().to_dict()
    print(json.dumps({"market_span": [str(df["market_ts"].min()), str(df["market_ts"].max())], "year_counts": year_counts}, ensure_ascii=False), flush=True)
    local_pdf = LOCAL_OUT / args.out_name
    payload = build_pdf(df, out_path=local_pdf, epoch=args.epoch)

    # JSON sidecar (serializable)
    def _clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj

    side = LOCAL_OUT / args.out_name.replace(".pdf", "_metrics.json")
    side.write_text(json.dumps(_clean(payload), indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    # Copy to MaksTiger, under the epoch the report was actually built from
    tiger_out = TIGER_ARCHIVE_ROOT / args.epoch / "reports"
    tiger_out.mkdir(parents=True, exist_ok=True)
    tiger_pdf = tiger_out / args.out_name
    shutil.copy2(local_pdf, tiger_pdf)
    shutil.copy2(side, tiger_out / side.name)
    # also archive folder under sandbox
    arch = SANDBOX / "archive" / args.epoch / "reports"
    arch.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_pdf, arch / args.out_name)
    shutil.copy2(side, arch / side.name)

    print(
        json.dumps(
            {
                "status": "OK",
                "local_pdf": str(local_pdf),
                "tiger_pdf": str(tiger_pdf),
                "trades": int(len(df)),
                "overall_return_pct": payload["overall"]["ret_pct"],
                "overall_net": payload["overall"]["net"],
                "by_tf_return_pct": {tf: payload["by_timeframe"][tf]["ret_pct"] for tf in TIMEFRAMES},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
