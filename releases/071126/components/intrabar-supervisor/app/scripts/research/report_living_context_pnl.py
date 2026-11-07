#!/usr/bin/env python3
"""Книга сделок живого процесса: доходность, PF, просадка, восстановление, стоп/тейк/раннее.

  PYTHONPATH=src python scripts/research/report_living_context_pnl.py
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.research.living_context_s41_book import (  # noqa: E402
    INITIAL_EQUITY,
    TIMEFRAMES,
    simulate_book,
)
from btc_ml.research.living_context_vsa_calibration import assign_bar_segment  # noqa: E402

OUT_DIR = ROOT / "output/research/living_context_pnl"
DOWNLOADS = Path.home() / "Downloads"
C_BG = "#F4F1EA"
C_PAPER = "#FFFDF8"
C_INK = "#1B1E23"
C_MUTED = "#5C6370"
C_PLUS = "#2F6F4E"
C_MINUS = "#8C3A32"
C_LINE = "#D7D0C5"
BUCKET_RU = {"STOP": "стоп", "TAKE": "тейк", "EARLY": "раннее"}
SIDE_RU = {"LONG": "лонг", "SHORT": "шорт"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        if isinstance(value, float) and (not math.isfinite(value)):
            return "—"
        return f"{float(value):,.{digits}f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _pct(value: Any, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{100.0 * float(value):.{digits}f}%"


def _money(value: Any) -> str:
    if value is None:
        return "—"
    v = float(value)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f} $".replace(",", " ")


def _hours_ru(hours: float | None) -> str:
    if hours is None or not math.isfinite(hours):
        return "не восст."
    if hours < 48:
        return f"{hours:.1f} ч"
    return f"{hours / 24.0:.1f} дн"


def prepare(trades: pd.DataFrame) -> pd.DataFrame:
    out = trades.copy()
    out["exit_ts"] = pd.to_datetime(out["exit_ts"], utc=True)
    out["entry_ts"] = pd.to_datetime(out["entry_ts"], utc=True)
    out["net_pnl"] = pd.to_numeric(out["net_pnl_usd"], errors="coerce").fillna(0.0)
    naive = out["exit_ts"].dt.tz_convert("UTC").dt.tz_localize(None)
    out["day"] = naive.dt.strftime("%Y-%m-%d")
    out["month"] = naive.dt.strftime("%Y-%m")
    out["quarter"] = naive.dt.to_period("Q").astype(str)
    out["half"] = naive.dt.year.astype(str) + "-H" + np.where(naive.dt.month <= 6, "1", "2")
    out["year"] = naive.dt.strftime("%Y")
    out["partial"] = np.where(naive.dt.year.isin([2023, 2026]), "*", "")
    out["segment"] = assign_bar_segment(out["exit_ts"])
    return out.sort_values("exit_ts").reset_index(drop=True)


def _equity(pnls: list[float], initial: float) -> np.ndarray:
    eq = np.empty(len(pnls) + 1, dtype=float)
    eq[0] = initial
    for i, pnl in enumerate(pnls):
        eq[i + 1] = eq[i] + pnl
    return eq


def _max_dd(equity: np.ndarray) -> tuple[float, float, int, int]:
    peak = equity[0]
    peak_i = 0
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    trough_i = 0
    start_i = 0
    for i, eq in enumerate(equity):
        if eq >= peak:
            peak = eq
            peak_i = i
        dd_usd = eq - peak
        dd_pct = dd_usd / peak if peak > 0 else 0.0
        if dd_pct < max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd_usd
            trough_i = i
            start_i = peak_i
    return max_dd_pct, max_dd_usd, start_i, trough_i


def _recovery_hours(equity: np.ndarray, times: pd.Series, trough_i: int, peak_i: int) -> float | None:
    if trough_i <= 0 or trough_i >= len(equity) or times is None or len(times) == 0:
        return None
    peak_level = equity[peak_i]
    for j in range(trough_i, len(equity)):
        if equity[j] >= peak_level:
            t_trough = times.iloc[trough_i - 1] if trough_i >= 1 else times.iloc[0]
            t_rec = times.iloc[j - 1] if j >= 1 else times.iloc[0]
            return max(0.0, (t_rec - t_trough).total_seconds() / 3600.0)
    return None


def slice_stats(frame: pd.DataFrame, *, initial: float = INITIAL_EQUITY) -> dict[str, Any]:
    if frame is None or not len(frame):
        return {
            "n": 0,
            "net": 0.0,
            "ret": None,
            "wr": None,
            "pf": None,
            "max_dd": None,
            "max_dd_usd": None,
            "recovery_hours": None,
            "recovery_factor": None,
            "long_n": 0,
            "short_n": 0,
            "long_wr": None,
            "short_wr": None,
            "stop_n": 0,
            "take_n": 0,
            "early_n": 0,
            "end_n": 0,
        }
    net = pd.to_numeric(frame["net_pnl"], errors="coerce").fillna(0.0)
    equity = _equity(net.tolist(), initial)
    dd_pct, dd_usd, peak_i, trough_i = _max_dd(equity)
    wins = net[net > 0]
    losses = net[net < 0]
    gp = float(wins.sum())
    gl = float(abs(losses.sum()))
    long = frame[frame["side"].astype(str).str.upper() == "LONG"]
    short = frame[frame["side"].astype(str).str.upper() == "SHORT"]
    buckets = frame["exit_bucket"].astype(str).str.upper()
    reasons = frame["exit_reason"].astype(str).str.upper()
    rec_h = _recovery_hours(equity, frame["exit_ts"], trough_i, peak_i)
    return {
        "n": int(len(frame)),
        "net": float(net.sum()),
        "ret": float(equity[-1] / initial - 1.0) if initial else None,
        "wr": float((net > 0).mean()),
        "pf": (gp / gl) if gl > 0 else None,
        "max_dd": dd_pct,
        "max_dd_usd": dd_usd,
        "recovery_hours": rec_h,
        "recovery_factor": (float(net.sum()) / abs(dd_usd)) if dd_usd < 0 else None,
        "long_n": int(len(long)),
        "short_n": int(len(short)),
        "long_wr": float((long["net_pnl"] > 0).mean()) if len(long) else None,
        "short_wr": float((short["net_pnl"] > 0).mean()) if len(short) else None,
        "stop_n": int((buckets == "STOP").sum()),
        "take_n": int((buckets == "TAKE").sum()),
        "early_n": int(((buckets == "EARLY") & ~reasons.str.contains("END_OF_SAMPLE")).sum()),
        "end_n": int(reasons.str.contains("END_OF_SAMPLE").sum()),
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "expectancy": float(net.mean()),
        "equity_end": float(equity[-1]),
    }


def period_table(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    rows = []
    for period, part in frame.groupby(key, sort=True):
        row = slice_stats(part)
        row["period"] = str(period)
        row["partial"] = "*" if str(part["partial"].iloc[0]) == "*" else ""
        rows.append(row)
    return pd.DataFrame(rows)


def daily_running_table(frame: pd.DataFrame, *, initial: float = INITIAL_EQUITY) -> pd.DataFrame:
    """One row per calendar day. Return is vs equity at the start of that day."""
    if frame is None or not len(frame):
        return pd.DataFrame()
    work = frame.sort_values("exit_ts")
    start = work["exit_ts"].min().tz_convert("UTC").normalize()
    end = work["exit_ts"].max().tz_convert("UTC").normalize()
    days = pd.date_range(start, end, freq="D", tz="UTC")
    grouped = {
        ts.normalize(): part for ts, part in work.groupby(work["exit_ts"].dt.tz_convert("UTC").dt.normalize())
    }
    equity = float(initial)
    rows: list[dict[str, Any]] = []
    for day in days:
        part = grouped.get(day)
        naive = day.tz_convert("UTC").tz_localize(None)
        stamp = naive.strftime("%Y-%m-%d")
        year = int(naive.year)
        month_i = int(naive.month)
        month = naive.strftime("%Y-%m")
        partial = "*" if year in {2023, 2026} else ""
        if part is None or not len(part):
            rows.append(
                {
                    "day": stamp,
                    "period": stamp,
                    "month": month,
                    "year": str(year),
                    "dom": int(naive.day),
                    "month_i": month_i,
                    "partial": partial,
                    "n": 0,
                    "net": 0.0,
                    "ret": 0.0,
                    "wr": None,
                    "long_n": 0,
                    "short_n": 0,
                    "long_wr": None,
                    "short_wr": None,
                    "equity_start": equity,
                    "equity_end": equity,
                    "stop_n": 0,
                    "take_n": 0,
                    "early_n": 0,
                }
            )
            continue
        stats = slice_stats(part)
        pnl = float(pd.to_numeric(part["net_pnl"], errors="coerce").fillna(0.0).sum())
        ret = (pnl / equity) if equity else 0.0
        rows.append(
            {
                "day": stamp,
                "period": stamp,
                "month": month,
                "year": str(year),
                "dom": int(naive.day),
                "month_i": month_i,
                "partial": partial,
                "n": stats["n"],
                "net": pnl,
                "ret": ret,
                "wr": stats["wr"],
                "long_n": stats["long_n"],
                "short_n": stats["short_n"],
                "long_wr": stats["long_wr"],
                "short_wr": stats["short_wr"],
                "equity_start": equity,
                "equity_end": equity + pnl,
                "stop_n": stats["stop_n"],
                "take_n": stats["take_n"],
                "early_n": stats["early_n"],
            }
        )
        equity += pnl
    return pd.DataFrame(rows)


def daily_by_month(daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for month, part in daily.groupby("month", sort=True):
        out[str(month)] = part.reset_index(drop=True)
    return out


def daily_by_timeframe(frame: pd.DataFrame, *, initial: float = INITIAL_EQUITY) -> pd.DataFrame:
    parts = [daily_running_table(frame, initial=initial).assign(timeframe="ALL")]
    for tf in TIMEFRAMES:
        scoped = frame[frame["timeframe"] == tf]
        if len(scoped):
            parts.append(daily_running_table(scoped, initial=initial).assign(timeframe=tf))
    return pd.concat(parts, ignore_index=True)


COLS = [
    ("period", "период", "s"),
    ("n", "сделок", "i"),
    ("net", "PnL $", "m"),
    ("ret", "доходн.", "p"),
    ("wr", "WR", "p"),
    ("pf", "PF", "n2"),
    ("max_dd", "max DD", "p"),
    ("recovery_hours", "восст.", "h"),
    ("long_wr", "WR лонг", "p"),
    ("short_wr", "WR шорт", "p"),
    ("stop_n", "стоп", "i"),
    ("take_n", "тейк", "i"),
    ("early_n", "раннее", "i"),
]
DAILY_COLS = [
    ("day", "день", "s"),
    ("n", "сделок", "i"),
    ("wr", "WR", "p"),
    ("long_wr", "WR лонг", "p"),
    ("short_wr", "WR шорт", "p"),
    ("long_n", "лонг n", "i"),
    ("short_n", "шорт n", "i"),
    ("net", "PnL $", "m"),
    ("ret", "доходн. дня", "p"),
]


def _cell(row: pd.Series, col: str, kind: str) -> str:
    val = row.get(col)
    if kind == "s":
        return f"{row.get('period', row.get('day', ''))}{row.get('partial') or ''}"
    if kind == "i":
        return "—" if val is None else str(int(val))
    if kind == "m":
        return _money(val)
    if kind == "p":
        return _pct(val, 1)
    if kind == "n2":
        return _fmt(val, 2)
    if kind == "h":
        return _hours_ru(None if val is None or (isinstance(val, float) and not math.isfinite(val)) else float(val))
    return str(val)


def _md_table(frame: pd.DataFrame, first: str = "period") -> str:
    if frame is None or not len(frame):
        return "_нет сделок_\n"
    cols = list(DAILY_COLS if first == "day" else COLS)
    if first != "day":
        cols = [(first if c == "period" else c, t, k) for c, t, k in cols]
    header = "| " + " | ".join(t for _, t, _ in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [header, sep]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(_cell(row, c, k) for c, _, k in cols) + " |")
    return "\n".join(lines) + "\n"


def write_markdown(path: Path, *, overall: dict[str, Any], by_tf: dict[str, dict[str, Any]], by_side: dict[str, dict[str, Any]], yearly, half, quarterly, monthly, daily, generated: str) -> None:
    tf_rows = []
    for tf, stats in by_tf.items():
        row = dict(stats)
        row["period"] = tf
        row["partial"] = ""
        tf_rows.append(row)
    side_rows = []
    for side, stats in by_side.items():
        row = dict(stats)
        row["period"] = SIDE_RU.get(side, side)
        row["partial"] = ""
        side_rows.append(row)
    parts = [
        "# Живой процесс — книга сделок",
        "",
        f"Собрано: `{generated}`. История 2023-12-17 → 2026-07-24. Live не трогали.",
        "",
        "Сделка: вход по закрытию бара, когда lifecycle ACTIVE и статус подтверждён. "
        "Стоп 100 б.п. / тейк 150 б.п. по high/low следующих баров. "
        "Пауза (OBSERVE) и противоположный CHALLENGED — держим. "
        "Раннее закрытие — противоположный ACTIVE. Не тиковый Hybrid, не Optuna.",
        "",
        f"- сделок: **{overall['n']}**",
        f"- доходность: **{_pct(overall['ret'])}** · PnL **{_money(overall['net'])}**",
        f"- profit factor: **{_fmt(overall['pf'], 2)}**",
        f"- max DD: **{_pct(overall['max_dd'])}** ({_money(overall['max_dd_usd'])})",
        f"- восстановление после max DD: **{_hours_ru(overall['recovery_hours'])}**",
        f"- WR лонг: **{_pct(overall['long_wr'])}** (n={overall['long_n']}) · WR шорт: **{_pct(overall['short_wr'])}** (n={overall['short_n']})",
        f"- выходы: стоп **{overall['stop_n']}** · тейк **{overall['take_n']}** · раннее **{overall['early_n']}**",
        "",
        "## По графикам",
        "",
        _md_table(pd.DataFrame(tf_rows)),
        "## Лонг / шорт",
        "",
        _md_table(pd.DataFrame(side_rows)),
        "## Год",
        "",
        _md_table(yearly),
        "## Полугодие",
        "",
        _md_table(half),
        "## Квартал",
        "",
        _md_table(quarterly),
        "## Месяц",
        "",
        _md_table(monthly),
        "## Каждый день · WR и доходность к equity на утро",
        "",
    ]
    for month, table in daily.items():
        parts.extend([f"### {month}", "", _md_table(table, first="day")])
    path.write_text("\n".join(parts), encoding="utf-8")


def _setup() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": C_BG,
            "axes.facecolor": C_PAPER,
            "text.color": C_INK,
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "pdf.fonttype": 42,
        }
    )


def _draw_table(ax, frame: pd.DataFrame, title: str, first: str = "period") -> None:
    ax.set_axis_off()
    ax.set_title(title, loc="left", fontsize=11, color=C_INK, pad=8)
    cols = list(DAILY_COLS if first == "day" else COLS)
    headers = [t for _, t, _ in cols]
    cells = []
    for _, row in frame.iterrows():
        cells.append([_cell(row, c, k) for c, _, k in cols])
    table = ax.table(cellText=cells, colLabels=headers, loc="upper center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(7.2 if first == "day" else 6.2)
    table.scale(1.0, 1.28 if first == "day" else 1.22)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(C_LINE)
        if r == 0:
            cell.set_facecolor("#2C333D")
            cell.set_text_props(color="white", weight="bold")
        else:
            cell.set_facecolor(C_PAPER if r % 2 else "#F7F3EC")
            if headers[c] in {"PnL $", "доходн.", "доходн. дня", "max DD", "WR", "WR лонг", "WR шорт"} and r > 0:
                raw = frame.iloc[r - 1]
                key = {
                    "PnL $": "net",
                    "доходн.": "ret",
                    "доходн. дня": "ret",
                    "max DD": "max_dd",
                    "WR": "wr",
                    "WR лонг": "long_wr",
                    "WR шорт": "short_wr",
                }[headers[c]]
                val = raw.get(key)
                if val is None or (isinstance(val, float) and not np.isfinite(val)):
                    continue
                if headers[c].startswith("WR"):
                    cell.set_text_props(color=C_MINUS if val < 0.5 else C_PLUS if val > 0.5 else C_MUTED)
                elif headers[c] == "max DD" or val < 0:
                    cell.set_text_props(color=C_MINUS)
                elif val > 0:
                    cell.set_text_props(color=C_PLUS)


def _kpi_page(pdf: PdfPages, overall: dict[str, Any], generated: str) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.text(0.06, 0.90, "Живой процесс · книга сделок 2023–2026", fontsize=20, color=C_INK, weight="bold")
    ax.text(0.06, 0.84, "BTCUSDT · M15/M30/H1/H4 · вход по закрытию · стоп/тейк по high/low", fontsize=10, color=C_MUTED)
    ax.text(0.06, 0.80, generated, fontsize=9, color=C_MUTED)
    cards = [
        ("Сделок", str(overall["n"])),
        ("Доходность", _pct(overall["ret"])),
        ("PnL", _money(overall["net"])),
        ("Profit factor", _fmt(overall["pf"], 2)),
        ("Max DD", _pct(overall["max_dd"])),
        ("Восстановление", _hours_ru(overall["recovery_hours"])),
        ("WR лонг", _pct(overall["long_wr"])),
        ("WR шорт", _pct(overall["short_wr"])),
        ("Стоп", str(overall["stop_n"])),
        ("Тейк", str(overall["take_n"])),
        ("Раннее закрытие", str(overall["early_n"])),
        ("WR все", _pct(overall["wr"])),
    ]
    for i, (label, val) in enumerate(cards):
        x = 0.06 + (i % 4) * 0.23
        y = 0.62 - (i // 4) * 0.18
        ax.add_patch(plt.Rectangle((x, y), 0.21, 0.15, facecolor=C_PAPER, edgecolor=C_LINE, lw=1.2))
        ax.text(x + 0.01, y + 0.10, label, fontsize=9, color=C_MUTED)
        ax.text(x + 0.01, y + 0.03, val, fontsize=16, color=C_INK, weight="bold")
    ax.text(
        0.06,
        0.08,
        "Пауза не закрывает. Противоположный CHALLENGED не закрывает.\n"
        "Holdout в калибровке запечатан. Кандидат Optuna в live не ставили.\n"
        "Это не 9-часовой lived replay менеджера: проход по закрытым барам + evaluate_exit_preview.",
        fontsize=9,
        color=C_MUTED,
    )
    pdf.savefig(fig)
    plt.close(fig)


def _bar_page(pdf: PdfPages, frame: pd.DataFrame, key: str, title: str) -> None:
    if frame is None or not len(frame):
        return
    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    labels = [f"{r.period}{r.partial}" for r in frame.itertuples()]
    vals = frame["net"].astype(float).to_numpy()
    colors = [C_PLUS if v >= 0 else C_MINUS for v in vals]
    ax.bar(range(len(vals)), vals, color=colors)
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("PnL, $")
    ax.set_title(title, loc="left")
    ax.axhline(0, color=C_MUTED, lw=0.6)
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


MONTH_RU = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


def _mix(plus: np.ndarray, minus: np.ndarray, t: float) -> str:
    t = float(np.clip(t, 0.0, 1.0))
    rgb = plus * t + minus * (1.0 - t)
    return "#%02x%02x%02x" % tuple(int(x * 255) for x in rgb)


def _heatmap_year(pdf: PdfPages, daily: pd.DataFrame, year: str) -> None:
    part = daily[daily["year"].astype(str) == str(year)]
    if not len(part):
        return
    fig, axes = plt.subplots(1, 2, figsize=(11.69, 8.27))
    fig.suptitle(f"{year} · каждый день: винрейт и доходность к equity на утро", color=C_INK, fontsize=13)
    months = sorted(part["month_i"].unique())
    for ax, field, title, scale in (
        (axes[0], "wr", "WR", 1.0),
        (axes[1], "ret", "доходность дня", 0.03),
    ):
        grid = np.full((len(months), 31), np.nan)
        for _, row in part.iterrows():
            r = months.index(int(row["month_i"]))
            c = int(row["dom"]) - 1
            val = row.get(field)
            if val is not None and np.isfinite(val):
                grid[r, c] = float(val)
        for r in range(len(months)):
            for c in range(31):
                val = grid[r, c]
                if not np.isfinite(val):
                    color = "#EDE7DC"
                    text = ""
                elif field == "wr":
                    # 0.35 → rose, 0.5 → paper, 0.8 → sage
                    t = (val - 0.45) / 0.35
                    color = _mix(np.array([0.82, 0.89, 0.84]), np.array([0.91, 0.82, 0.80]), t)
                    text = f"{100.0 * val:.0f}"
                else:
                    t = 0.5 + val / (2 * scale)
                    color = _mix(np.array([0.82, 0.89, 0.84]), np.array([0.91, 0.82, 0.80]), t)
                    text = f"{100.0 * val:.1f}"
                ax.add_patch(plt.Rectangle((c, r), 1, 1, facecolor=color, edgecolor="#F4F1EA", lw=0.4))
                if text:
                    ax.text(c + 0.5, r + 0.5, text, ha="center", va="center", fontsize=5.5, color=C_INK)
        ax.set_xlim(0, 31)
        ax.set_ylim(len(months), 0)
        ax.set_xticks([i + 0.5 for i in range(31)])
        ax.set_xticklabels([str(i + 1) for i in range(31)], fontsize=6)
        ax.set_yticks([i + 0.5 for i in range(len(months))])
        ax.set_yticklabels([MONTH_RU.get(int(m), str(m)) for m in months], fontsize=8)
        ax.set_title(title, loc="left")
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


def build_daily_pdf(path: Path, *, daily_all: pd.DataFrame, by_month: dict[str, pd.DataFrame], generated: str) -> None:
    _setup()
    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ax.text(0.06, 0.88, "Каждый день · винрейт и доходность", fontsize=22, color=C_INK, weight="bold")
        ax.text(0.06, 0.80, "Живой процесс · книга сделок · 2023-12-17 → 2026-07-24", fontsize=12, color=C_MUTED)
        ax.text(
            0.06,
            0.62,
            "WR — доля прибыльных сделок, закрытых в этот день.\n"
            "WR лонг / WR шорт — то же по стороне.\n"
            "Доходность дня — PnL дня / equity на утро, не от $100k заново.\n"
            "Пустой день — сделок не было, WR нет, доходность 0.",
            fontsize=12,
            color=C_INK,
            linespacing=1.5,
        )
        ax.text(
            0.06,
            0.22,
            "Почему быстро: это не lived replay менеджера (тот шёл ~9 часов).\n"
            "Здесь один проход по уже пересобранному lifecycle и OHLC.",
            fontsize=11,
            color=C_MUTED,
        )
        ax.text(0.06, 0.10, generated, fontsize=9, color=C_MUTED)
        pdf.savefig(fig)
        plt.close(fig)
        for year in sorted(daily_all["year"].astype(str).unique()):
            _heatmap_year(pdf, daily_all, year)
        for month, table in by_month.items():
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            _draw_table(ax, table, f"День · {month} · WR и доходность к equity на утро", first="day")
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)


def build_pdf(
    path: Path,
    *,
    overall: dict[str, Any],
    tf_rows: pd.DataFrame,
    side_rows: pd.DataFrame,
    yearly: pd.DataFrame,
    half: pd.DataFrame,
    quarterly: pd.DataFrame,
    monthly: pd.DataFrame,
    daily: dict[str, pd.DataFrame],
    generated: str,
) -> None:
    _setup()
    with PdfPages(path) as pdf:
        _kpi_page(pdf, overall, generated)
        for year in sorted({str(y) for tables in daily.values() for y in tables.get("year", pd.Series(dtype=str)).astype(str).tolist()}):
            _heatmap_year(pdf, pd.concat(daily.values(), ignore_index=True), year)
        for month, table in daily.items():
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            _draw_table(ax, table, f"День · {month} · WR и доходность к equity на утро", first="day")
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        _draw_table(ax, tf_rows, "Сводка по графикам")
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        _draw_table(ax, side_rows, "Лонг / шорт")
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)
        for frame, title in (
            (yearly, "Год"),
            (half, "Полугодие"),
            (quarterly, "Квартал"),
            (monthly, "Месяц"),
        ):
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            _draw_table(ax, frame, title)
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)
        _bar_page(pdf, yearly, "year", "Год · PnL")
        _bar_page(pdf, half, "half", "Полугодие · PnL")
        _bar_page(pdf, quarterly, "quarter", "Квартал · PnL")
        _bar_page(pdf, monthly, "month", "Месяц · PnL")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-root", type=Path, default=None)
    parser.add_argument("--trades", type=Path, default=None, help="Готовая книга. Если нет — симулируем заново.")
    parser.add_argument("--resimulate", action="store_true")
    args = parser.parse_args()
    generated = _utc_now()
    default_trades = OUT_DIR / "lived_trades.parquet"
    if args.resimulate or (args.trades is None and not default_trades.exists()):
        trades = simulate_book(pack_root=args.pack_root)
    else:
        trades = pd.read_parquet(args.trades or default_trades)
    if not len(trades):
        raise SystemExit("no trades")
    prepared = prepare(trades)
    overall = slice_stats(prepared)
    by_tf = {tf: slice_stats(prepared[prepared["timeframe"] == tf]) for tf in TIMEFRAMES}
    by_side = {
        "LONG": slice_stats(prepared[prepared["side"] == "LONG"]),
        "SHORT": slice_stats(prepared[prepared["side"] == "SHORT"]),
    }
    yearly = period_table(prepared, "year")
    half = period_table(prepared, "half")
    quarterly = period_table(prepared, "quarter")
    monthly = period_table(prepared, "month")
    daily_all = daily_running_table(prepared)
    daily = daily_by_month(daily_all)
    tf_daily = daily_by_timeframe(prepared)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prepared.to_parquet(OUT_DIR / "lived_trades.parquet", index=False)
    prepared.to_csv(OUT_DIR / "lived_trades.csv", index=False)
    yearly.to_csv(OUT_DIR / "yearly.csv", index=False)
    half.to_csv(OUT_DIR / "halfyear.csv", index=False)
    quarterly.to_csv(OUT_DIR / "quarterly.csv", index=False)
    monthly.to_csv(OUT_DIR / "monthly.csv", index=False)
    daily_all.to_csv(OUT_DIR / "daily.csv", index=False)
    tf_daily.to_csv(OUT_DIR / "daily_by_timeframe.csv", index=False)
    tf_rows = pd.DataFrame([{**v, "period": k, "partial": ""} for k, v in by_tf.items()])
    side_rows = pd.DataFrame([{**v, "period": SIDE_RU.get(k, k), "partial": ""} for k, v in by_side.items()])
    write_markdown(
        OUT_DIR / "REPORT.md",
        overall=overall,
        by_tf=by_tf,
        by_side=by_side,
        yearly=yearly,
        half=half,
        quarterly=quarterly,
        monthly=monthly,
        daily=daily,
        generated=generated,
    )
    pdf_path = OUT_DIR / "LIVING_CONTEXT_PNL_RU.pdf"
    build_pdf(
        pdf_path,
        overall=overall,
        tf_rows=tf_rows,
        side_rows=side_rows,
        yearly=yearly,
        half=half,
        quarterly=quarterly,
        monthly=monthly,
        daily=daily,
        generated=generated,
    )
    daily_pdf = OUT_DIR / "LIVING_CONTEXT_DAILY_WR_RU.pdf"
    build_daily_pdf(daily_pdf, daily_all=daily_all, by_month=daily, generated=generated)
    dest = DOWNLOADS / "LIVING_CONTEXT_PNL_RU.pdf"
    dest_daily = DOWNLOADS / "LIVING_CONTEXT_DAILY_WR_RU.pdf"
    shutil.copy2(pdf_path, dest)
    shutil.copy2(daily_pdf, dest_daily)
    summary = {
        "generated_at": generated,
        "markdown": str(OUT_DIR / "REPORT.md"),
        "pdf": str(pdf_path),
        "daily_pdf": str(daily_pdf),
        "downloads": str(dest),
        "downloads_daily": str(dest_daily),
        "overall": overall,
        "by_timeframe": by_tf,
        "by_side": by_side,
        "days": int(len(daily_all)),
        "lived_replay_hours": False,
        "live_cognition_touched": False,
        "holdout_opened": False,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "pdf": str(dest),
                "daily_pdf": str(dest_daily),
                "days": int(len(daily_all)),
                "n": overall["n"],
                "net": overall["net"],
                "pf": overall["pf"],
                "ret": overall["ret"],
            },
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
