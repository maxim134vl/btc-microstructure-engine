#!/usr/bin/env python3
"""Counterfactual M15 tape for 14–15 Sep 2026 (closed-bar exit authority).

Does not rewrite epoch books. Reads the frozen fixture next to this file
(or the embedded fallback) and writes markup JSON + HTML.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "docs" / "audit" / "m15_sep14_render"
FIXTURE = ROOT / "docs" / "audit" / "fixtures" / "m15_sep14_tape.json"

# Compact fallback: (bar_open UTC, context, phase, episode)
# 14:15–17:45 filled LONG 358 from the untruncated live slice.
_LIFECYCLE: list[tuple[str, str, str, int]] = []

_ACTUAL = [
    {
        "id": "M15_1",
        "side": "LONG",
        "entry": "2026-09-14T10:54:32Z",
        "exit": "2026-09-14T18:36:49Z",
        "exit_reason": "TAKE_PROFIT",
    },
    {
        "id": "M15_2",
        "side": "LONG",
        "entry": "2026-09-14T19:37:24Z",
        "exit": "2026-09-14T21:15:48Z",
        "exit_reason": "ATOMIC_FLIP",
    },
    {
        "id": "M15_3",
        "side": "SHORT",
        "entry": "2026-09-14T21:15:48Z",
        "exit": "2026-09-14T22:17:15Z",
        "exit_reason": "ATOMIC_FLIP",
    },
    {
        "id": "M15_4",
        "side": "LONG",
        "entry": "2026-09-14T22:17:15Z",
        "exit": "2026-09-15T00:21:53Z",
        "exit_reason": "STOP_LOSS",
    },
    {
        "id": "M15_5",
        "side": "SHORT",
        "entry": "2026-09-15T00:32:07Z",
        "exit": "2026-09-15T01:01:44Z",
        "exit_reason": "ATOMIC_FLIP",
    },
    {
        "id": "M15_6",
        "side": "LONG",
        "entry": "2026-09-15T01:01:44Z",
        "exit": "2026-09-15T05:36:12Z",
        "exit_reason": "S41_CLOSE",
    },
    {
        "id": "M15_7",
        "side": "LONG",
        "entry": "2026-09-15T05:47:55Z",
        "exit": "2026-09-15T08:35:54Z",
        "exit_reason": "STOP_LOSS",
    },
]


def _expand_ranges(ranges: list) -> list[dict]:
    from datetime import datetime, timedelta, timezone

    rows: list[dict] = []
    step = timedelta(minutes=15)
    for start, end, ctx, phase, ep in ranges:
        cur = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        while cur <= last:
            rows.append(
                {
                    "timestamp": cur.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "active_market_context": ctx,
                    "lifecycle_state": phase,
                    "context_episode_id": ep,
                }
            )
            cur += step
    return rows


def _seed_lifecycle() -> list[dict]:
    if FIXTURE.exists():
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        if payload.get("lifecycle"):
            return list(payload["lifecycle"])
        if payload.get("ranges"):
            return _expand_ranges(payload["ranges"])
    rows: list[dict] = []
    for ts, ctx, phase, ep in _LIFECYCLE:
        rows.append(
            {
                "timestamp": ts,
                "active_market_context": ctx,
                "lifecycle_state": phase,
                "context_episode_id": ep,
            }
        )
    return rows


def _iso_bar_close(bar_open: str) -> str:
    stamp = bar_open.replace("Z", "")
    date, time = stamp.split("T")
    hh, mm, ss = time.split(":")
    minutes = int(hh) * 60 + int(mm) + 15
    day_carry, minutes = divmod(minutes, 24 * 60)
    if day_carry:
        y, m, d = (int(x) for x in date.split("-"))
        from datetime import date as dtdate, timedelta

        nxt = dtdate(y, m, d) + timedelta(days=day_carry)
        date = nxt.isoformat()
    return f"{date}T{minutes // 60:02d}:{minutes % 60:02d}:{ss}Z"


def _occupies(trade: dict, bar_open: str, bar_close: str) -> bool:
    return str(trade["entry"]) <= bar_close and str(trade["exit"]) > bar_open


def _opposite(side: str) -> str:
    return "SHORT" if side == "LONG" else "LONG"


def _is_opposite_active(ctx: str, phase: str, side: str) -> bool:
    if str(phase or "").upper() != "ACTIVE":
        return False
    ctx_u = str(ctx or "").upper()
    if side == "LONG":
        return ctx_u in {"SHORT", "SHORT_CONTEXT"}
    return ctx_u in {"LONG", "LONG_CONTEXT"}


def simulate(lifecycle: list[dict]) -> tuple[list[dict], list[dict]]:
    """Seed from actual entries; exit on closed-bar opposite ACTIVE (plus actual TP/SL clocks)."""
    sim: list[dict] = []
    open_pos: dict | None = None
    seq = 0
    actual_by_id = {row["id"]: row for row in _ACTUAL}

    def _close(reason: str, when: str) -> None:
        nonlocal open_pos
        if open_pos is None:
            return
        open_pos["exit"] = when
        open_pos["exit_reason"] = reason
        sim.append(open_pos)
        open_pos = None

    for row in lifecycle:
        bar_open = str(row["timestamp"])
        bar_close = _iso_bar_close(bar_open)
        ctx = str(row.get("active_market_context") or "")
        phase = str(row.get("lifecycle_state") or "")
        if open_pos is not None:
            actual = actual_by_id.get(open_pos.get("source_id") or "")
            if actual and actual["exit_reason"] in {"TAKE_PROFIT", "STOP_LOSS"}:
                if actual["exit"] <= bar_close:
                    _close(actual["exit_reason"], actual["exit"])
            if open_pos is not None and _is_opposite_active(ctx, phase, open_pos["side"]):
                _close("CLOSED_BAR_OPPOSITE_ACTIVE", bar_close)
                seq += 1
                side = "SHORT" if ctx.upper().startswith("SHORT") else "LONG"
                open_pos = {
                    "id": f"SIM_{seq}",
                    "side": side,
                    "entry": bar_close,
                    "exit": None,
                    "exit_reason": None,
                    "source_id": None,
                    "note": "ATOMIC_FLIP from closed-bar opposite",
                }
        if open_pos is None:
            for actual in _ACTUAL:
                if actual["entry"] <= bar_close and actual["entry"] > bar_open:
                    seq += 1
                    open_pos = {
                        "id": f"SIM_{seq}",
                        "side": actual["side"],
                        "entry": actual["entry"],
                        "exit": None,
                        "exit_reason": None,
                        "source_id": actual["id"],
                        "note": f"seeded from {actual['id']}",
                    }
                    break
    if open_pos is not None:
        _close("STILL_OPEN", lifecycle[-1]["timestamp"] if lifecycle else "")
    tape = []
    for row in lifecycle:
        bar_open = str(row["timestamp"])
        bar_close = _iso_bar_close(bar_open)
        actual_hit = next((t["id"] for t in _ACTUAL if _occupies(t, bar_open, bar_close)), None)
        sim_hit = next((t["id"] for t in sim if t.get("exit") and _occupies(t, bar_open, bar_close)), None)
        would_close = False
        if actual_hit:
            actual = actual_by_id[actual_hit]
            would_close = _is_opposite_active(
                str(row.get("active_market_context") or ""),
                str(row.get("lifecycle_state") or ""),
                actual["side"],
            )
        tape.append(
            {
                "bar_open": bar_open,
                "bar_close": bar_close,
                "paint": row.get("active_market_context"),
                "phase": row.get("lifecycle_state"),
                "episode": row.get("context_episode_id"),
                "actual": actual_hit,
                "sim": sim_hit,
                "closed_bar_would_flatten": would_close,
            }
        )
    return tape, sim


def _color(ctx: str | None) -> str:
    u = str(ctx or "").upper()
    if "LONG" in u:
        return "#2e7d32"
    if "SHORT" in u:
        return "#c62828"
    return "#9e9e9e"


def render_html(tape: list[dict], sim: list[dict], path: Path) -> None:
    n = max(len(tape), 1)
    width = max(1200, n * 14)
    height = 280
    cells = []
    for i, row in enumerate(tape):
        x = int(i * (width / n))
        w = max(1, int(width / n) - 1)
        cells.append(
            f'<rect x="{x}" y="20" width="{w}" height="40" fill="{_color(row["paint"])}" />'
        )
        actual_fill = _color(next((t["side"] for t in _ACTUAL if t["id"] == row["actual"]), None)) if row["actual"] else "#111"
        sim_fill = _color(next((t["side"] for t in sim if t["id"] == row["sim"]), None)) if row["sim"] else "#111"
        if row["actual"]:
            cells.append(f'<rect x="{x}" y="80" width="{w}" height="24" fill="{actual_fill}" />')
        if row["sim"]:
            cells.append(f'<rect x="{x}" y="120" width="{w}" height="24" fill="{sim_fill}" />')
        if row["closed_bar_would_flatten"]:
            cells.append(f'<rect x="{x}" y="160" width="{w}" height="10" fill="#ff9800" />')
    marks = []
    for t in _ACTUAL:
        marks.append(
            f"<div><b>{t['id']}</b> {t['side']} {t['entry']} → {t['exit']} ({t['exit_reason']})</div>"
        )
    sim_marks = []
    for t in sim:
        sim_marks.append(
            f"<div><b>{t['id']}</b> {t['side']} {t['entry']} → {t.get('exit')} ({t.get('exit_reason')}) {t.get('note') or ''}</div>"
        )
    html = f"""<!doctype html>
<meta charset="utf-8"/>
<title>M15 14–15 Sep closed-bar counterfactual</title>
<body style="background:#111;color:#eee;font-family:sans-serif">
<h1>M15 14–15 Sep 2026 — второй рендер</h1>
<p>Верх: restated paint (зелёный LONG, красный SHORT, серый OBSERVE). Середина: факт M15_1…7. Ниже: контрфакт closed-bar flatten. Оранжевая полоса — бар, где closed opposite ACTIVE должен был закрыть фактическую сделку.</p>
<svg width="{width}" height="{height}" style="background:#000">{''.join(cells)}</svg>
<h2>Факт</h2>
{''.join(marks)}
<h2>Контрфакт</h2>
{''.join(sim_marks)}
</body>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    lifecycle = _seed_lifecycle()
    if not lifecycle:
        raise SystemExit(f"empty lifecycle; write {FIXTURE}")
    tape, sim = simulate(lifecycle)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    markup = {
        "window": {"start": "2026-09-14T10:00:00Z", "end": "2026-09-15T09:00:00Z"},
        "policy": "closed_bar_opposite_active_flattens_open_slot",
        "actual_trades": _ACTUAL,
        "simulated_trades": sim,
        "tape": tape,
    }
    json_path = OUT_DIR / "m15_sep14_counterfactual.json"
    html_path = OUT_DIR / "m15_sep14_counterfactual.html"
    json_path.write_text(json.dumps(markup, indent=2) + "\n", encoding="utf-8")
    render_html(tape, sim, html_path)
    flatten = [row for row in tape if row["closed_bar_would_flatten"]]
    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    print(f"bars={len(tape)} sim_trades={len(sim)} flatten_signals={len(flatten)}")
    for row in flatten:
        print(f"  flatten {row['bar_open']} paint={row['paint']} actual={row['actual']}")


if __name__ == "__main__":
    main()
