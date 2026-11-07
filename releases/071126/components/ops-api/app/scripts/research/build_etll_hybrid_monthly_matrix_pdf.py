#!/usr/bin/env python3
"""Альбомная помесячная матрица канонической тестовой книги Hybrid Tick.

Holdout не раскрывается. Текст тёмный, фон светлый, все подписи по-русски.
"""

from __future__ import annotations

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
from matplotlib.colors import to_hex
from matplotlib.patches import FancyBboxPatch, Rectangle

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

from report_etll_hybrid_tick_performance import TIMEFRAMES, _prepare  # noqa: E402

SPLIT_PATH = ROOT / "config" / "research" / "etll_hybrid_calibration_split.json"
DEFAULT_TRADES = Path(
    "/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive/"
    "ETLL_HYBRID_TICK_V1_20260905_092610/lived_trades.parquet"
)
DOWNLOADS = Path.home() / "Downloads"
A4_LANDSCAPE = (11.69, 8.27)
TFS = ("ALL",) + TIMEFRAMES
TF_LABELS = {"ALL": "Все ТФ", "M15": "M15", "M30": "M30", "H1": "H1", "H4": "H4"}
STATUS_RU = {
    "TRAIN": "обучение",
    "VAL": "проверка",
    "SEALED": "запечатано",
    "NO_DATA": "нет сделок",
    "PURGE": "пауза",
}

# Светлая бумага, без кислотного RdYlGn.
C_BG = "#F4F1EA"
C_PAPER = "#FFFdf8"
C_INK = "#1B1E23"
C_MUTED = "#5C6370"
C_LINE = "#D7D0C5"
C_HEADER = "#2C333D"
C_PLUS = np.array([0.82, 0.89, 0.84])  # приглушённый шалфей
C_MINUS = np.array([0.91, 0.82, 0.80])  # приглушённая роза
C_NEUT = np.array([0.96, 0.94, 0.90])
C_SEAL = np.array([0.90, 0.88, 0.82])
C_EMPTY = np.array([0.93, 0.91, 0.87])


def _setup() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": C_BG,
            "axes.facecolor": C_PAPER,
            "text.color": C_INK,
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "pdf.fonttype": 42,
        }
    )


def _load_split() -> dict[str, Any]:
    return json.loads(SPLIT_PATH.read_text(encoding="utf-8"))


def _ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).tz_convert("UTC")


def _segment_for(ts: pd.Timestamp, split: dict[str, Any]) -> str:
    segs = split["segments"]
    train_from, train_to = _ts(segs["train"]["from"]), _ts(segs["train"]["to"])
    val_from, val_to = _ts(segs["validation"]["from"]), _ts(segs["validation"]["to"])
    hold_from = _ts(segs["holdout"]["from"])
    if ts < train_from:
        return "NONE"
    if ts < train_to:
        return "TRAIN"
    if ts < val_from:
        return "PURGE"
    if ts < val_to:
        return "VAL"
    if ts < hold_from:
        return "PURGE"
    return "SEALED"


def _status_ru(status: str) -> str:
    if "+" in status:
        parts = [STATUS_RU.get(p, p) for p in status.split("+")]
        return " + ".join(parts)
    return STATUS_RU.get(status, status)


def _cell_metrics(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame is None or not len(frame):
        return None
    net = pd.to_numeric(frame["net_pnl"], errors="coerce").fillna(0.0)
    n = int(len(frame))
    return {
        "n": n,
        "wins": int((net > 0).sum()),
        "losses": int((net < 0).sum()),
        "wr": float((net > 0).mean()) if n else None,
        "net": float(net.sum()),
    }


def _month_index(start: str, end: str) -> list[str]:
    return [str(p) for p in pd.period_range(start=start, end=end, freq="M")]


def build_matrix(prepared: pd.DataFrame, split: dict[str, Any]) -> pd.DataFrame:
    prepared = prepared.copy()
    prepared["segment"] = prepared["exit_ts"].map(lambda t: _segment_for(t, split))
    rows: list[dict[str, Any]] = []
    for month in _month_index("2023-01", "2026-09"):
        part = prepared[prepared["month"] == month]
        segs = set(part["segment"].tolist()) if len(part) else set()
        if not segs:
            status = "NO_DATA"
        elif segs <= {"SEALED"}:
            status = "SEALED"
        elif segs <= {"PURGE"}:
            status = "PURGE"
        elif "SEALED" in segs:
            status = "SEALED"
        elif segs <= {"TRAIN"}:
            status = "TRAIN"
        elif segs <= {"VAL"}:
            status = "VAL"
        else:
            status = "+".join(sorted(s for s in segs if s not in {"SEALED"}))
        row: dict[str, Any] = {"month": month, "status": status}
        allowed = part[part["segment"].isin({"TRAIN", "VAL"})] if len(part) else part
        if status == "SEALED":
            for tf in TFS:
                row[tf] = {"sealed": True}
        elif status in {"NO_DATA", "PURGE"}:
            for tf in TFS:
                row[tf] = None
        else:
            row["ALL"] = _cell_metrics(allowed)
            for tf in TIMEFRAMES:
                row[tf] = _cell_metrics(allowed[allowed["timeframe"] == tf])
        rows.append(row)
    return pd.DataFrame(rows)


def _fmt_cell(cell: Any) -> str:
    if cell is None:
        return "—"
    if isinstance(cell, dict) and cell.get("sealed"):
        return "запечатано"
    if not isinstance(cell, dict) or not cell.get("n"):
        return "—"
    wr = f"{cell['wr'] * 100:.0f}%" if cell.get("wr") is not None else "—"
    net = f"{cell['net']:+,.0f}".replace(",", " ")
    return f"{cell['n']} сд.   {wr}\n{net} $"


def _net_of(cell: Any) -> float | None:
    if isinstance(cell, dict) and not cell.get("sealed") and cell.get("n"):
        return float(cell["net"])
    return None


def _tint(net: float | None, vmax: float) -> np.ndarray:
    if net is None or vmax <= 0:
        return C_NEUT
    t = max(-1.0, min(1.0, net / vmax))
    if t >= 0:
        return C_NEUT * (1 - t) + C_PLUS * t
    t = -t
    return C_NEUT * (1 - t) + C_MINUS * t


def _cell_face(cell: Any, vmax: float) -> str:
    if cell is None:
        return to_hex(C_EMPTY)
    if isinstance(cell, dict) and cell.get("sealed"):
        return to_hex(C_SEAL)
    return to_hex(_tint(_net_of(cell), vmax))


def _vmax(matrix: pd.DataFrame) -> float:
    vals: list[float] = []
    for _, row in matrix.iterrows():
        for tf in TFS:
            net = _net_of(row[tf])
            if net is not None:
                vals.append(abs(net))
    if not vals:
        return 1.0
    return float(np.percentile(vals, 85)) or 1.0


def _legend_bar(ax: Any, y: float) -> None:
    items = [
        (to_hex(C_PLUS), "месяц в плюсе"),
        (to_hex(C_MINUS), "месяц в минусе"),
        (to_hex(C_SEAL), "запечатано — цифр нет"),
        (to_hex(C_EMPTY), "нет сделок"),
    ]
    x = 0.04
    for color, label in items:
        ax.add_patch(Rectangle((x, y), 0.028, 0.035, transform=ax.transAxes, color=color, ec=C_LINE))
        ax.text(x + 0.034, y + 0.006, label, transform=ax.transAxes, fontsize=8, color=C_MUTED)
        x += 0.24


def _cover(fig: plt.Figure, split: dict[str, Any], allowed: pd.DataFrame) -> None:
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ref = split["reference_book"]
    ax.text(0.05, 0.92, "Как читать эту матрицу", fontsize=26, color=C_INK, fontweight="bold")
    ax.text(
        0.05,
        0.86,
        "Тестовая книга Hybrid Tick · бумажные сделки по историческому рынку, не живой VPS",
        fontsize=11,
        color=C_MUTED,
    )

    cards = [
        (
            "Обучение",
            "17 дек 2023 — 28 фев 2025",
            "На этом отрезке модель разрешено подбирать.\nЭто не «экзамен», а учебник.",
        ),
        (
            "Проверка",
            "7 мар 2025 — 31 дек 2025",
            "Сюда смотрят, чтобы выбрать уже готовый вариант.\nНельзя бесконечно подкручивать под эти месяцы.",
        ),
        (
            "Запечатано",
            "7 янв 2026 — 24 июл 2026",
            "Финальный экзамен. Цифры специально скрыты.\nОткрывается один раз, в конце.",
        ),
    ]
    for i, (title, dates, body) in enumerate(cards):
        x = 0.05 + i * 0.31
        ax.add_patch(
            FancyBboxPatch(
                (x, 0.58),
                0.29,
                0.24,
                boxstyle="round,pad=0.012,rounding_size=0.012",
                facecolor=C_PAPER,
                edgecolor=C_LINE,
                mutation_aspect=0.4,
            )
        )
        ax.text(x + 0.015, 0.78, title, fontsize=14, color=C_INK, fontweight="bold")
        ax.text(x + 0.015, 0.735, dates, fontsize=8, color=C_MUTED)
        ax.text(x + 0.015, 0.62, body, fontsize=9, color=C_INK, va="bottom", linespacing=1.35)

    how = (
        "Строка — календарный месяц. Столбец — таймфрейм (Все / M15 / M30 / H1 / H4).\n"
        "В клетке три числа: сколько сделок закрылось, доля прибыльных, суммарный результат в долларах.\n"
        "Зелёный фон — месяц в плюсе, розовый — в минусе. Чем насыщеннее, тем больше сумма.\n"
        "Январь–ноябрь 2023 пустые: книга начинается 17 декабря 2023.\n"
        "Пауза — семь дней между кусками, чтобы сделка из обучения не залезла в проверку.\n"
        "Живой VPS 7–10 сентября 2026 сюда не входит: другой механизм выхода (конец контекста на границе часа/H4)."
    )
    ax.text(0.05, 0.545, "Что в клетке", fontsize=13, color=C_INK, fontweight="bold")
    ax.text(0.05, 0.515, how, fontsize=10, color=C_INK, va="top", linespacing=1.45)

    n = int(len(allowed))
    wr = float((allowed["net_pnl"] > 0).mean()) if n else 0.0
    net = float(allowed["net_pnl"].sum()) if n else 0.0
    ax.text(
        0.05,
        0.13,
        f"Обучение + проверка (без запечатанного):  {n:,} сделок   ·   прибыльных {wr * 100:.1f}%   ·   итог {net:+,.0f} $".replace(
            ",", " "
        ),
        fontsize=11,
        color=C_INK,
        fontweight="bold",
    )
    ax.text(
        0.05,
        0.07,
        f"Эпоха {ref['paper_epoch_id']}   ·   собрано {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC",
        fontsize=8,
        color=C_MUTED,
    )


def _draw_grid(fig: plt.Figure, matrix: pd.DataFrame, *, title: str, start: int, end: int) -> None:
    ax = fig.add_axes([0.02, 0.07, 0.96, 0.86])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=14, color=C_INK, pad=8)
    slice_df = matrix.iloc[start:end].reset_index(drop=True)
    n_rows = len(slice_df)
    n_cols = 2 + len(TFS)
    col_w = [0.09, 0.11] + [0.80 / len(TFS)] * len(TFS)
    row_h = 0.90 / (n_rows + 1)
    vmax = _vmax(matrix)
    headers = ["Месяц", "Роль отрезка"] + [TF_LABELS[tf] for tf in TFS]
    x0 = 0.0
    y0 = 1.0
    # header
    x = x0
    for j, head in enumerate(headers):
        ax.add_patch(Rectangle((x, y0 - row_h), col_w[j], row_h, facecolor=C_HEADER, edgecolor="white"))
        ax.text(x + col_w[j] / 2, y0 - row_h / 2, head, ha="center", va="center", color="white", fontsize=8, fontweight="bold")
        x += col_w[j]
    for i, row in slice_df.iterrows():
        y = y0 - row_h * (i + 2)
        x = x0
        status = str(row["status"])
        left_vals = [row["month"], _status_ru(status)]
        for j, val in enumerate(left_vals):
            ax.add_patch(Rectangle((x, y), col_w[j], row_h, facecolor=C_PAPER, edgecolor=C_LINE, linewidth=0.4))
            ax.text(x + col_w[j] / 2, y + row_h / 2, val, ha="center", va="center", color=C_INK, fontsize=7.5)
            x += col_w[j]
        for j, tf in enumerate(TFS):
            cell = row[tf]
            face = _cell_face(cell, vmax)
            ax.add_patch(Rectangle((x, y), col_w[2 + j], row_h, facecolor=face, edgecolor=C_LINE, linewidth=0.4))
            ax.text(
                x + col_w[2 + j] / 2,
                y + row_h / 2,
                _fmt_cell(cell),
                ha="center",
                va="center",
                color=C_INK,
                fontsize=6.6,
                linespacing=1.2,
            )
            x += col_w[2 + j]
    _legend_bar(ax, 0.01)


def _heatmap_page(fig: plt.Figure, matrix: pd.DataFrame, *, kind: str, title: str) -> None:
    ax = fig.add_axes([0.12, 0.10, 0.84, 0.82])
    months = matrix["month"].tolist()
    n_r, n_c = len(months), len(TFS)
    vmax = _vmax(matrix)
    wr_mid = 70.0
    ax.set_xlim(-0.5, n_c - 0.5)
    ax.set_ylim(n_r - 0.5, -0.5)
    for i, row in matrix.iterrows():
        ii = int(i)
        for j, tf in enumerate(TFS):
            cell = row[tf]
            if kind == "wr" and isinstance(cell, dict) and cell.get("wr") is not None:
                # шкала winrate вокруг 70%, без кислотного зелёного
                wr = cell["wr"] * 100.0
                t = max(-1.0, min(1.0, (wr - wr_mid) / 25.0))
                face = C_NEUT * (1 - abs(t)) + (C_PLUS if t >= 0 else C_MINUS) * abs(t)
                label = f"{wr:.0f}%"
            elif kind == "net":
                face = np.array(matplotlib.colors.to_rgb(_cell_face(cell, vmax)))
                net = _net_of(cell)
                if cell is None:
                    label = "—"
                elif isinstance(cell, dict) and cell.get("sealed"):
                    label = "запеч."
                    face = C_SEAL
                elif net is None:
                    label = "—"
                else:
                    label = f"{net:+,.0f}".replace(",", " ")
            else:
                face = C_EMPTY
                label = "—"
            if cell is None:
                face, label = C_EMPTY, "—"
            elif isinstance(cell, dict) and cell.get("sealed"):
                face, label = C_SEAL, "запеч."
            ax.add_patch(
                Rectangle((j - 0.5, ii - 0.5), 1, 1, facecolor=face, edgecolor="white", linewidth=0.8)
            )
            ax.text(j, ii, label, ha="center", va="center", color=C_INK, fontsize=7)
    ax.set_xticks(range(n_c))
    ax.set_xticklabels([TF_LABELS[tf] for tf in TFS], fontsize=9, color=C_INK)
    ax.set_yticks(range(n_r))
    ax.set_yticklabels(months, fontsize=7, color=C_INK)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_color(C_LINE)
    ax.set_title(title, loc="left", fontsize=13, color=C_INK, pad=10)
    ax.set_yticklabels(
        [f"{m}   {_status_ru(s)}" for m, s in zip(months, matrix["status"].tolist())],
        fontsize=6.5,
        color=C_MUTED,
    )
    _legend_bar(ax, -0.08)


def main() -> int:
    _setup()
    split = _load_split()
    prepared = _prepare(pd.read_parquet(DEFAULT_TRADES))
    prepared["segment"] = prepared["exit_ts"].map(lambda t: _segment_for(t, split))
    allowed = prepared[prepared["segment"].isin({"TRAIN", "VAL"})].copy()
    matrix = build_matrix(prepared, split)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    out = DOWNLOADS / "HYBRID_TICK_MONTHLY_MATRIX_2023_2026_LANDSCAPE.pdf"
    with PdfPages(out) as pdf:
        fig = plt.figure(figsize=A4_LANDSCAPE)
        _cover(fig, split, allowed)
        pdf.savefig(fig)
        plt.close(fig)

        mid = 24  # 2023-01 .. 2024-12
        fig = plt.figure(figsize=A4_LANDSCAPE)
        _draw_grid(fig, matrix, title="Матрица по месяцам  ·  2023–2024", start=0, end=mid)
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=A4_LANDSCAPE)
        _draw_grid(fig, matrix, title="Матрица по месяцам  ·  2025–2026", start=mid, end=len(matrix))
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=A4_LANDSCAPE)
        _heatmap_page(fig, matrix, kind="net", title="Итог месяца, $")
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=A4_LANDSCAPE)
        _heatmap_page(fig, matrix, kind="wr", title="Доля прибыльных сделок, %")
        pdf.savefig(fig)
        plt.close(fig)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
