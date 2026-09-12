#!/usr/bin/env python3
"""Render the live S4.1 → LIVE1B path diagram to a PNG."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
OUT = Path("/Users/fontecrypto/Downloads/s41_live1b_entry_path.png")

BG = "#0B1220"
INK = "#E8EEF7"
MUTED = "#9AA7B8"
CARD = "#152033"
STROKE = "#2A3A52"
COG = "#22D3EE"
S41 = "#3DDC97"
LIVE = "#60A5FA"
CHART = "#C4B5FD"
OBS = "#6B7280"
MARKET = "#FBBF24"
WARN = "#F59E0B"


def _font(size: float, bold: bool = False):
    path = BOLD if bold else FONT
    return font_manager.FontProperties(fname=path, size=size)


def card(ax, x, y, w, h, *, fc, ec, lw=1.6, r=0.035):
    p = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.012,rounding_size={r}",
        linewidth=lw,
        facecolor=fc,
        edgecolor=ec,
        mutation_aspect=0.6,
    )
    ax.add_patch(p)
    return p


def arrow(ax, x1, y1, x2, y2, *, color, lw=2.2, rad=0.0, style="-|>"):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle=f"{style},head_length=9,head_width=7",
            mutation_scale=1,
            linewidth=lw,
            color=color,
            connectionstyle=f"arc3,rad={rad}",
            zorder=3,
        )
    )


def dashed_arrow(ax, x1, y1, x2, y2, *, color):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle="-|>,head_length=8,head_width=6",
            linewidth=1.5,
            color=color,
            linestyle=(0, (4, 3)),
            connectionstyle="arc3,rad=0.05",
            zorder=3,
        )
    )


def block(ax, x, y, w, h, title, lines, *, color, title_size=11.5, body_size=9.4):
    card(ax, x, y, w, h, fc="#101A2B", ec=color, lw=1.8)
    ax.add_patch(Rectangle((x, y + h - 0.07), w, 0.012, facecolor=color, edgecolor="none", zorder=2))
    ax.text(
        x + 0.018,
        y + h - 0.055,
        title,
        fontproperties=_font(title_size, True),
        color=color,
        va="center",
        ha="left",
        zorder=4,
    )
    ax.text(
        x + 0.018,
        y + h - 0.125,
        "\n".join(lines),
        fontproperties=_font(body_size),
        color=INK,
        va="top",
        ha="left",
        linespacing=1.35,
        zorder=4,
    )


def render(path: Path) -> Path:
    font_manager.fontManager.addfont(FONT)
    font_manager.fontManager.addfont(BOLD)
    fig, ax = plt.subplots(figsize=(18, 10.2), dpi=180)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.03, 0.955, "Путь входа LIVE1B после cutover", fontproperties=_font(26, True), color=INK)
    ax.text(
        0.03,
        0.905,
        "Закрытый бар + volume class  →  S4.1  →  command-bus  →  LIVE1B books / BBO / TP-SL.   Journal не открывает сделки.",
        fontproperties=_font(12.2),
        color=MUTED,
    )

    # Column shells
    columns = [
        (0.025, "1. Рынок", MARKET),
        (0.215, "2. Cognition  —  правда контекста", COG),
        (0.405, "3. Journal  —  только observe", OBS),
        (0.595, "4. S4.1  —  единственный вход", S41),
        (0.785, "5. LIVE1B  —  исполнение", LIVE),
    ]
    for x, title, color in columns:
        card(ax, x, 0.33, 0.185, 0.54, fc=CARD, ec=STROKE, lw=1.2)
        ax.text(x + 0.01, 0.84, title, fontproperties=_font(11, True), color=color)

    block(
        ax,
        0.04,
        0.52,
        0.155,
        0.28,
        "Binance Futures WS",
        ["btcusdt@bookTicker", "btcusdt@aggTrade", "local BBO + tape", "paper-only, без real exec"],
        color=MARKET,
    )

    block(
        ax,
        0.23,
        0.62,
        0.155,
        0.18,
        "Закрытый бар",
        ["M15 / M30 / H1 / H4", "не tick, не provisional"],
        color=COG,
        title_size=11,
        body_size=9,
    )
    block(
        ax,
        0.23,
        0.38,
        0.155,
        0.21,
        "Volume lineage",
        ["volume_classification", "volume_response_state", "auction_episode_memory", "→ lifecycle parquet"],
        color=COG,
        title_size=11,
        body_size=9,
    )

    block(
        ax,
        0.42,
        0.48,
        0.155,
        0.32,
        "LIVE1A events.jsonl",
        ["CONTEXT_START / FLIP / END", "volume_class = unknown", "не вход в books", "observe-only"],
        color=OBS,
    )

    block(
        ax,
        0.61,
        0.62,
        0.155,
        0.18,
        "TimeframeManager",
        ["читает parquet, не journal", "PROVISIONAL не actionable"],
        color=S41,
        title_size=11,
        body_size=9,
    )
    block(
        ax,
        0.61,
        0.38,
        0.155,
        0.21,
        "Command bus",
        ["OPEN / CLOSE / NO_ACTION", "one-shot по episode", "atomic FLIP в одном цикле"],
        color=S41,
        title_size=11,
        body_size=9,
    )

    block(
        ax,
        0.80,
        0.64,
        0.155,
        0.16,
        "overlay.json",
        ["entry_source = s41_command_bus", "consume_after = пол курсора"],
        color=LIVE,
        title_size=10.5,
        body_size=8.8,
    )
    block(
        ax,
        0.80,
        0.46,
        0.155,
        0.155,
        "S41CommandConsumer",
        ["только command-bus", "нет BBO / не HEALTHY → retry"],
        color=LIVE,
        title_size=10.5,
        body_size=8.8,
    )
    block(
        ax,
        0.80,
        0.355,
        0.155,
        0.09,
        "Books + TP/SL",
        ["fill: local BBO + command_id"],
        color=LIVE,
        title_size=10.5,
        body_size=8.6,
    )

    # Main path arrows
    arrow(ax, 0.195, 0.66, 0.228, 0.72, color=COG)
    arrow(ax, 0.307, 0.62, 0.307, 0.59, color=COG)
    arrow(ax, 0.385, 0.48, 0.608, 0.70, color=S41, rad=-0.08)
    arrow(ax, 0.765, 0.48, 0.798, 0.535, color=S41)
    arrow(ax, 0.877, 0.64, 0.877, 0.615, color=LIVE)
    arrow(ax, 0.877, 0.46, 0.877, 0.445, color=LIVE)
    arrow(ax, 0.195, 0.54, 0.80, 0.385, color=MARKET, rad=0.12)

    dashed_arrow(ax, 0.575, 0.58, 0.80, 0.54, color=OBS)
    ax.text(0.72, 0.515, "не открывает позицию", fontproperties=_font(8.2), color="#9CA3AF", ha="left")
    arrow(ax, 0.307, 0.38, 0.307, 0.30, color=CHART)

    # Chart band
    card(ax, 0.025, 0.06, 0.95, 0.24, fc=CARD, ec=CHART, lw=1.6)
    ax.text(0.04, 0.255, "6. Чарт следует владельцу входа", fontproperties=_font(13, True), color=CHART)
    ax.text(
        0.04,
        0.20,
        "overlay.entry_source = s41_command_bus  →  полосы = market_context_lifecycle_episodes (parquet),\nне LIVE1A journal. CatBoost только sizing. Hold=0. Bar-count anti-saw выключен. M15 не наследуется на старшие ТФ.",
        fontproperties=_font(11),
        color=INK,
        va="top",
        linespacing=1.4,
    )

    # legend chips
    chips = [
        (S41, "боевой путь входа"),
        (OBS, "observe, без fills"),
        (LIVE, "исполнение paper"),
        (CHART, "тот же parquet"),
    ]
    x = 0.04
    for color, label in chips:
        ax.add_patch(Rectangle((x, 0.085), 0.018, 0.018, facecolor=color, edgecolor="none"))
        ax.text(x + 0.024, 0.093, label, fontproperties=_font(10), color=MUTED, va="center")
        x += 0.18

    ax.text(
        0.97,
        0.03,
        "S41_LIVE1B_CHAIN_V1  ·  paper-only",
        fontproperties=_font(9),
        color=MUTED,
        ha="right",
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=BG, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)
    return path


if __name__ == "__main__":
    out = render(OUT)
    print(out)
