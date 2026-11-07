#!/usr/bin/env python3
"""Календарный отчёт живого процесса: день / месяц / квартал / полугодие / год.

Читает исторический pack 2023-12-17…2026-07-24. Live cognition не трогает.
Holdout в калибровке не открывался: в таблицах он помечен, но не использовался
для выбора правила.

  python3 scripts/research/report_living_context_calendar.py
"""

from __future__ import annotations

import argparse
import json
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

from btc_ml.research.living_context_vsa_calibration import (  # noqa: E402
    assign_bar_segment,
)


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = pd.Series(tr).rolling(n, min_periods=max(3, n // 2)).mean().to_numpy()
    return np.where(np.isfinite(out) & (out > 0), out, np.nanmedian(tr))

PACK_ROOTS = (
    ROOT / "data/research/external_traders",
    Path("/Volumes/MaksTiger/btc-ml/from-mac-20260907/btc-ml-cold/research/external_traders"),
)
TIMEFRAMES = ("M15", "M30", "H1", "H4")
HORIZON = 4
C_BG = "#F4F1EA"
C_PAPER = "#FFFDF8"
C_INK = "#1B1E23"
C_MUTED = "#5C6370"
C_PLUS = "#2F6F4E"
C_MINUS = "#8C3A32"
SEGMENT_RU = {
    "train": "обучение",
    "validation": "проверка",
    "holdout": "запечатано",
    "purged": "пауза",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pack_root() -> Path:
    for root in PACK_ROOTS:
        if (root / "market_pack_btc_m15" / "feed_m15.parquet").exists():
            return root
    return PACK_ROOTS[0]


def _star(ts: pd.Series) -> pd.Series:
    year = ts.dt.year
    month = ts.dt.month
    mark = pd.Series([""] * len(ts), index=ts.index)
    mark[year == 2023] = "*"
    mark[(year == 2026) & (month >= 8)] = "*"
    mark[(year == 2026) & (month == 7)] = "*"
    return mark


def load_tf(pack_dir: Path, timeframe: str) -> pd.DataFrame:
    ctx = pack_dir / "context"
    final = pd.read_parquet(ctx / "final_market_context_memory.parquet")
    candle = pd.read_parquet(ctx / "candle_structure_memory.parquet")
    final["timestamp"] = pd.to_datetime(final["timestamp"], utc=True, errors="coerce")
    candle["timestamp"] = pd.to_datetime(candle["timestamp"], utc=True, errors="coerce")
    keep_c = [c for c in ("timestamp", "open", "high", "low", "close") if c in candle.columns]
    work = final.merge(candle[keep_c], on="timestamp", how="left", suffixes=("", "_c"))
    if "close" not in work.columns or work["close"].isna().all():
        work["close"] = work.get("close_c")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    high = pd.to_numeric(work.get("high"), errors="coerce").to_numpy()
    low = pd.to_numeric(work.get("low"), errors="coerce").to_numpy()
    close = pd.to_numeric(work["close"], errors="coerce")
    work["atr"] = _atr(high, low, close.to_numpy(), 14)
    atr = pd.to_numeric(work["atr"], errors="coerce").replace(0, np.nan)
    work["fwd_atr_return"] = (close.shift(-HORIZON) - close) / atr
    ctx = work["market_context"].astype(str).str.upper()
    fwd = work["fwd_atr_return"]
    work["signed_atr"] = np.where(
        ctx.isin({"LONG", "LONG_CONTEXT"}),
        fwd,
        np.where(ctx.isin({"SHORT", "SHORT_CONTEXT"}), -fwd, np.nan),
    )
    work["is_long"] = ctx.isin({"LONG", "LONG_CONTEXT"})
    work["is_short"] = ctx.isin({"SHORT", "SHORT_CONTEXT"})
    work["is_observe"] = ~(work["is_long"] | work["is_short"])
    work["timeframe"] = str(timeframe).upper()
    work["segment"] = assign_bar_segment(work["timestamp"])
    naive = work["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
    work["day"] = naive.dt.strftime("%Y-%m-%d")
    work["month"] = naive.dt.strftime("%Y-%m")
    work["quarter"] = naive.dt.to_period("Q").astype(str)
    work["half"] = naive.dt.year.astype(str) + "-H" + np.where(naive.dt.month <= 6, "1", "2")
    work["year"] = naive.dt.strftime("%Y")
    work["partial"] = np.where(naive.dt.year.isin([2023, 2026]), "*", "")
    return work


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or not len(frame):
        return {
            "bars": 0,
            "long": 0,
            "short": 0,
            "observe": 0,
            "long_pct": None,
            "short_pct": None,
            "observe_pct": None,
            "mean_strength": None,
            "directional": 0,
            "hit_rate": None,
            "mean_signed_atr": None,
            "median_signed_atr": None,
        }
    n = int(len(frame))
    long_n = int(frame["is_long"].sum())
    short_n = int(frame["is_short"].sum())
    obs_n = int(frame["is_observe"].sum())
    signed = pd.to_numeric(frame["signed_atr"], errors="coerce")
    directional = int(signed.notna().sum())
    hit = float((signed > 0).sum() / directional) if directional else None
    return {
        "bars": n,
        "long": long_n,
        "short": short_n,
        "observe": obs_n,
        "long_pct": round(100.0 * long_n / n, 2) if n else None,
        "short_pct": round(100.0 * short_n / n, 2) if n else None,
        "observe_pct": round(100.0 * obs_n / n, 2) if n else None,
        "mean_strength": round(float(pd.to_numeric(frame["process_strength"], errors="coerce").mean()), 3),
        "directional": directional,
        "hit_rate": None if hit is None else round(hit, 4),
        "mean_signed_atr": None if directional == 0 else round(float(signed.mean()), 4),
        "median_signed_atr": None if directional == 0 else round(float(signed.median()), 4),
    }


def period_table(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, grp in frame.groupby(key, sort=True):
        row = summarize(grp)
        row["period"] = str(name)
        row["partial"] = "*" if bool((grp.get("partial") == "*").any()) else ""
        segs = grp["segment"].value_counts().to_dict()
        row["обучение"] = int(segs.get("train", 0))
        row["проверка"] = int(segs.get("validation", 0))
        row["запечатано"] = int(segs.get("holdout", 0))
        row["пауза"] = int(segs.get("purged", 0))
        rows.append(row)
    return pd.DataFrame(rows)


def daily_by_month(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for month, grp in frame.groupby("month", sort=True):
        table = period_table(grp, "day")
        table = table.rename(columns={"period": "day"})
        out[str(month)] = table
    return out


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _md_table(frame: pd.DataFrame, columns: list[tuple[str, str, int | None]]) -> str:
    head = "| " + " | ".join(title for _, title, _ in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [head, sep]
    for _, row in frame.iterrows():
        cells = []
        for col, _, digits in columns:
            val = row.get(col)
            if col == "period":
                mark = row.get("partial") or ""
                cells.append(f"{val}{mark}")
            elif digits is None:
                cells.append("" if val is None else str(int(val) if isinstance(val, float) and val == int(val) else val))
            else:
                cells.append(_fmt(val, digits))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


COLS = [
    ("period", "период", None),
    ("bars", "баров", None),
    ("long_pct", "лонг %", 1),
    ("short_pct", "шорт %", 1),
    ("observe_pct", "пауза %", 1),
    ("mean_strength", "сила", 2),
    ("directional", "направл.", None),
    ("hit_rate", "попадание", 3),
    ("mean_signed_atr", "ср. ATR", 3),
    ("обучение", "обуч.", None),
    ("проверка", "пров.", None),
    ("запечатано", "запеч.", None),
]


def write_markdown(
    *,
    out_dir: Path,
    overall: dict[str, Any],
    by_tf: dict[str, dict[str, Any]],
    yearly: pd.DataFrame,
    half: pd.DataFrame,
    quarter: pd.DataFrame,
    monthly: pd.DataFrame,
    daily: dict[str, pd.DataFrame],
) -> Path:
    lines = [
        "# Живой процесс — календарный отчёт",
        "",
        f"Собрано: `{_utc_now()}`. История pack 2023-12-17 → 2026-07-24. Live не трогали.",
        "",
        "Метрики с бара закрытия. Подпись «попадание» — цена через 4 бара ушла в сторону живого процесса, в ATR. "
        "2023* — только хвост декабря. 2026* — до 24 июля.",
        "",
        "Калибровка входа (Optuna/лес) на валидации не выжила. Holdout не открывали. "
        "Ниже — как жил **контекст**, не бумажная книга сделок.",
        "",
        "## Сводка",
        "",
        f"- баров: **{overall['bars']}**",
        f"- лонг {overall['long_pct']}% / шорт {overall['short_pct']}% / пауза {overall['observe_pct']}%",
        f"- средняя сила: **{overall['mean_strength']}**",
        f"- попадание направленного контекста: **{_fmt(overall['hit_rate'], 3)}**",
        f"- средний signed ATR (4 бара): **{_fmt(overall['mean_signed_atr'], 3)}**",
        "",
        "По графикам:",
        "",
    ]
    tf_rows = []
    for tf in TIMEFRAMES:
        row = dict(by_tf[tf])
        row["period"] = tf
        tf_rows.append(row)
    lines.append(_md_table(pd.DataFrame(tf_rows), COLS))
    lines += ["", "## Год", "", _md_table(yearly, COLS), ""]
    lines += ["## Полугодие", "", _md_table(half, COLS), ""]
    lines += ["## Квартал", "", _md_table(quarter, COLS), ""]
    lines += ["## Месяц", "", _md_table(monthly, COLS), ""]
    lines.append("## Дни внутри месяца")
    lines.append("")
    for month in sorted(daily):
        lines.append(f"### {month}")
        lines.append("")
        day_cols = [(a if a != "period" else "day", b, c) for a, b, c in COLS]
        table = daily[month].rename(columns={"day": "period"})
        lines.append(_md_table(table, day_cols))
        lines.append("")
    path = out_dir / "REPORT.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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


def _kpi_color(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return C_MUTED
    return C_PLUS if value > 0 else C_MINUS if value < 0 else C_MUTED


def _draw_table(ax, frame: pd.DataFrame, title: str) -> None:
    ax.set_axis_off()
    ax.set_title(title, loc="left", fontsize=11, color=C_INK, pad=8)
    show = frame.copy()
    if "period" in show.columns and "partial" in show.columns:
        show["period"] = show["period"].astype(str) + show["partial"].fillna("").astype(str)
    cols = [c for c, _, _ in COLS if c in show.columns]
    headers = [t for c, t, _ in COLS if c in show.columns]
    cells: list[list[str]] = []
    for _, row in show.iterrows():
        line = []
        for col, _, digits in COLS:
            if col not in show.columns:
                continue
            if col in {"period", "day"}:
                line.append(str(row[col]))
            elif digits is None:
                val = row[col]
                line.append("" if val is None else f"{int(val):,}".replace(",", " "))
            else:
                line.append(_fmt(row[col], digits))
        cells.append(line)
    table = ax.table(cellText=cells, colLabels=headers, loc="upper center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(6.5)
    table.scale(1.0, 1.25)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor("#D7D0C5")
        if r == 0:
            cell.set_facecolor("#2C333D")
            cell.set_text_props(color="white", weight="bold")
        else:
            cell.set_facecolor(C_PAPER if r % 2 else "#F7F3EC")
            if headers[c] in {"попадание", "ср. ATR"} and r > 0:
                raw = show.iloc[r - 1]["hit_rate" if headers[c] == "попадание" else "mean_signed_atr"]
                cell.get_text().set_color(_kpi_color(raw if isinstance(raw, float) else None))


def _bar_page(pdf: PdfPages, frame: pd.DataFrame, key: str, title: str) -> None:
    g = frame.groupby(key, sort=True)
    labels = list(g.groups)
    hits = [summarize(part)["mean_signed_atr"] or 0.0 for _, part in g]
    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    fig.suptitle(title, color=C_INK)
    colors = [C_PLUS if v >= 0 else C_MINUS for v in hits]
    ax.bar(range(len(labels)), hits, color=colors)
    ax.axhline(0, color=C_MUTED, linewidth=0.8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([str(x) for x in labels], rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("средний signed ATR, 4 бара")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


def build_pdf(
    *,
    out_path: Path,
    overall: dict[str, Any],
    by_tf: dict[str, dict[str, Any]],
    yearly: pd.DataFrame,
    half: pd.DataFrame,
    quarter: pd.DataFrame,
    monthly: pd.DataFrame,
    daily: dict[str, pd.DataFrame],
    m15: pd.DataFrame,
) -> Path:
    _setup()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(out_path) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27))
        ax = fig.add_axes([0.08, 0.08, 0.84, 0.84])
        ax.set_axis_off()
        ax.set_title("Живой процесс рынка — календарь", loc="left", fontsize=18, color=C_INK)
        text = (
            f"История {m15['timestamp'].min().date()} → {m15['timestamp'].max().date()}\n"
            f"Баров (все ТФ в CSV, здесь акцент M15): {overall['bars']}\n"
            f"Лонг {overall['long_pct']}% · шорт {overall['short_pct']}% · пауза {overall['observe_pct']}%\n"
            f"Сила {overall['mean_strength']} · попадание {overall['hit_rate']} · ATR {overall['mean_signed_atr']}\n\n"
            "Попадание: через 4 закрытых бара цена ушла в сторону живого процесса.\n"
            "2023* только декабрь с 17-го. 2026* до 24 июля.\n"
            "Optuna/лес на вход не прошли проверку. Holdout не открыт.\n"
            "Это не книга бумажных сделок."
        )
        ax.text(0.0, 0.78, text, va="top", fontsize=11, color=C_INK, family="DejaVu Sans")
        pdf.savefig(fig)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        tf_rows = []
        for tf in TIMEFRAMES:
            row = dict(by_tf[tf])
            row["period"] = tf
            tf_rows.append(row)
        _draw_table(ax, pd.DataFrame(tf_rows), "Сводка по графикам")
        pdf.savefig(fig)
        plt.close(fig)

        for title, table in (
            ("Год", yearly),
            ("Полугодие", half),
            ("Квартал", quarter),
            ("Месяц", monthly),
        ):
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            _draw_table(ax, table, title)
            pdf.savefig(fig)
            plt.close(fig)

        _bar_page(pdf, m15, "year", "Год · средний signed ATR (M15)")
        _bar_page(pdf, m15, "half", "Полугодие · средний signed ATR (M15)")
        _bar_page(pdf, m15, "quarter", "Квартал · средний signed ATR (M15)")
        _bar_page(pdf, m15, "month", "Месяц · средний signed ATR (M15)")

        for month in sorted(daily):
            fig, ax = plt.subplots(figsize=(11.69, 8.27))
            table = daily[month].rename(columns={"day": "period"})
            _draw_table(ax, table, f"Дни · {month} (M15)")
            pdf.savefig(fig)
            plt.close(fig)

        d = pdf.infodict()
        d["Title"] = "Живой процесс — календарь"
        d["Author"] = "btc-ml research"
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-root", type=Path, default=None)
    parser.add_argument("--timeframe", default="M15", help="Календарь дней строится по этому ТФ")
    args = parser.parse_args()
    root = args.pack_root or _pack_root()
    frames = []
    by_tf: dict[str, dict[str, Any]] = {}
    for tf in TIMEFRAMES:
        pack = root / f"market_pack_btc_{tf.lower()}"
        if not (pack / "context" / "final_market_context_memory.parquet").exists():
            continue
        frame = load_tf(pack, tf)
        frames.append(frame)
        by_tf[tf] = summarize(frame)
        print(json.dumps({"tf": tf, "bars": int(len(frame)), **by_tf[tf]}, ensure_ascii=False))
    if not frames:
        raise FileNotFoundError(f"no rebuilt context under {root}")
    all_tf = pd.concat(frames, ignore_index=True)
    focus_tf = str(args.timeframe).upper()
    focus = next((f for f in frames if str(f["timeframe"].iloc[0]).upper() == focus_tf), frames[0])
    overall = summarize(focus)
    yearly = period_table(focus, "year")
    half = period_table(focus, "half")
    quarter = period_table(focus, "quarter")
    monthly = period_table(focus, "month")
    daily = daily_by_month(focus)

    out_dir = ROOT / "output" / "research" / "living_context_calendar"
    out_dir.mkdir(parents=True, exist_ok=True)
    yearly.to_csv(out_dir / "yearly.csv", index=False)
    half.to_csv(out_dir / "halfyear.csv", index=False)
    quarter.to_csv(out_dir / "quarterly.csv", index=False)
    monthly.to_csv(out_dir / "monthly.csv", index=False)
    days = pd.concat(
        [t.assign(month=m) for m, t in daily.items()],
        ignore_index=True,
    )
    days.to_csv(out_dir / "daily.csv", index=False)
    all_tf.to_parquet(out_dir / "bars_all_tf.parquet", index=False)
    md = write_markdown(
        out_dir=out_dir,
        overall=overall,
        by_tf=by_tf,
        yearly=yearly,
        half=half,
        quarter=quarter,
        monthly=monthly,
        daily=daily,
    )
    pdf_path = out_dir / "LIVING_CONTEXT_CALENDAR_RU.pdf"
    build_pdf(
        out_path=pdf_path,
        overall=overall,
        by_tf=by_tf,
        yearly=yearly,
        half=half,
        quarter=quarter,
        monthly=monthly,
        daily=daily,
        m15=focus,
    )
    downloads = Path.home() / "Downloads" / "LIVING_CONTEXT_CALENDAR_RU.pdf"
    downloads.write_bytes(pdf_path.read_bytes())
    summary = {
        "generated_at": _utc_now(),
        "pack_root": str(root),
        "focus_timeframe": focus_tf,
        "markdown": str(md),
        "pdf": str(pdf_path),
        "downloads": str(downloads),
        "csv": {
            "daily": str(out_dir / "daily.csv"),
            "monthly": str(out_dir / "monthly.csv"),
            "quarterly": str(out_dir / "quarterly.csv"),
            "halfyear": str(out_dir / "halfyear.csv"),
            "yearly": str(out_dir / "yearly.csv"),
        },
        "overall": overall,
        "by_timeframe": by_tf,
        "live_cognition_touched": False,
        "holdout_opened": False,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
