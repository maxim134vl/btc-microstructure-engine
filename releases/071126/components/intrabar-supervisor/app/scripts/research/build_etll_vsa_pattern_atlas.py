#!/usr/bin/env python3
"""Build VSA_PRACTICAL_V1 pattern atlas on full ETLL pack history.

Reads candle_structure + volume_response_V2; writes human atlas under audits.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from btc_ml.research.vsa_patterns import (  # noqa: E402
    PATTERN_IDS,
    combo_counts,
    compute_forward_outcomes,
    detect_vsa_patterns,
    load_vsa_config,
    summarize_outcomes,
)

DEFAULT_PACK = ROOT / "data/research/external_traders/market_pack_btc_m15"
DEFAULT_OUT = ROOT / "output/audits/etll_lived_replay_20260825/vsa_atlas"
DEFAULT_LIVED = (
    ROOT / "data/research/external_traders/market_pack_btc_m15/lived_replay/lived_trades.parquet"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _lived_appendix(flags: pd.DataFrame, lived: Path) -> dict:
    if not lived.exists():
        return {"status": "NO_LIVED"}
    trades = pd.read_parquet(lived)
    trades["entry_ts"] = pd.to_datetime(trades["entry_ts"], utc=True)
    # map entry to prior M15 open
    bar_open = trades["entry_ts"].dt.floor("15min") - pd.Timedelta(minutes=15)
    by_ts = flags.set_index("timestamp")
    rows = []
    for t, side, pnl, bo in zip(
        trades["trade_id"], trades["side"], trades["net_pnl_usd"], bar_open
    ):
        if bo not in by_ts.index:
            # try exact floor
            bo2 = trades.loc[trades["trade_id"] == t, "entry_ts"].iloc[0].floor("15min")
            if bo2 not in by_ts.index:
                continue
            bo = bo2
        row = by_ts.loc[bo]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        rows.append(
            {
                "trade_id": t,
                "side": str(side).upper(),
                "net_pnl_usd": float(pnl),
                "primary_pattern": str(row["primary_pattern"]),
                "signal": str(row["signal"]),
            }
        )
    if not rows:
        return {"status": "NO_MATCHES", "n": 0}
    df = pd.DataFrame(rows)
    out: dict = {"status": "OK", "n_trades_matched": int(len(df)), "by_primary_pattern": {}}
    for p, g in df.groupby("primary_pattern"):
        pnls = g["net_pnl_usd"]
        out["by_primary_pattern"][str(p)] = {
            "n": int(len(g)),
            "wr": round(float((pnls > 0).mean()), 4),
            "avg_pnl": round(float(pnls.mean()), 2),
            "net_pnl_sum": round(float(pnls.sum()), 2),
        }
    return out


def _examples(flags: pd.DataFrame, pattern: str, k: int = 5) -> list[str]:
    sub = flags[flags[pattern]].sort_values("relative_volume", ascending=False).head(k)
    return [ts.strftime("%Y-%m-%dT%H:%M:%SZ") for ts in sub["timestamp"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cfg", type=Path, default=None)
    parser.add_argument("--lived", type=Path, default=DEFAULT_LIVED)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_vsa_config(args.cfg)
    candle = pd.read_parquet(args.pack_dir / "context/candle_structure_memory.parquet")
    vr_path = args.pack_dir / "context/volume_response_state.parquet"
    vr = pd.read_parquet(vr_path) if vr_path.exists() else None
    print(f"bars={len(candle)} vr={'yes' if vr is not None else 'no'}", flush=True)

    flags = detect_vsa_patterns(candle, vr, cfg)
    counts = {p: int(flags[p].sum()) for p in PATTERN_IDS}
    primary_counts = flags["primary_pattern"].value_counts().to_dict()
    combos = combo_counts(flags)
    horizons = list(cfg.get("outcome_horizons_bars") or [1, 2, 4, 8])
    outcomes = compute_forward_outcomes(flags, horizons=horizons)
    summary = summarize_outcomes(outcomes, horizons=horizons)
    lived = _lived_appendix(flags, args.lived)

    # persist compact artifacts
    flags_out = args.out_dir / "vsa_bar_flags.parquet"
    # drop bulky raw if needed — full flags ok (~few MB)
    flags.to_parquet(flags_out, index=False)
    outcomes.to_parquet(args.out_dir / "vsa_outcomes.parquet", index=False)

    atlas = {
        "generated_at": _utc_now(),
        "version": cfg.get("version"),
        "n_bars": int(len(flags)),
        "span": {
            "from": str(flags["timestamp"].min()),
            "to": str(flags["timestamp"].max()),
        },
        "pattern_counts": counts,
        "primary_counts": {str(k): int(v) for k, v in primary_counts.items()},
        "combo_top": dict(list(combos.items())[:40]),
        "outcomes_by_pattern": summary,
        "examples": {p: _examples(flags, p) for p in PATTERN_IDS},
        "lived_appendix": lived,
        "stop_rule_ru": "Стоп за экстремум сигнальной свечи (high/low бара паттерна).",
        "note_ru": (
            "Атлас VSA_PRACTICAL_V1 на V2 bar volume. Не tip-engine. "
            "Главное — исходы цены/объёма после паттерна, не AES5 AGREE."
        ),
    }
    (args.out_dir / "vsa_atlas_summary.json").write_text(
        json.dumps(atlas, indent=2, default=str) + "\n", encoding="utf-8"
    )

    # Human MD
    lines = [
        "# VSA Practical Atlas (V1)",
        "",
        f"Спан: `{atlas['span']['from']}` → `{atlas['span']['to']}` ({atlas['n_bars']} M15)",
        "",
        "## Сколько раз срабатывал каждый паттерн",
        "",
    ]
    for p in PATTERN_IDS:
        lines.append(f"- **{p}**: {counts[p]}  (сигнал: `{cfg['signal_map'].get(p)}`)")
    lines += ["", "## Исходы (median displacement в ATR, горизонт 4 бара)", ""]
    for p in PATTERN_IDS:
        block = summary.get(p) or {}
        h4 = block.get("h4") or {}
        if not block:
            lines.append(f"- **{p}**: нет primary-событий")
            continue
        lines.append(
            f"- **{p}** (n={block.get('n')}): median_disp={h4.get('median_disp_atr')} ATR; "
            f"up={h4.get('pct_up')} down={h4.get('pct_down')} chop={h4.get('pct_chop')}; "
            f"follow_RV={h4.get('median_follow_rv')}"
        )
    lines += ["", "## Топ комбинаций на одном баре", ""]
    for k, v in list(combos.items())[:15]:
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Примеры timestamps (для ручной проверки)", ""]
    for p in PATTERN_IDS:
        lines.append(f"- **{p}**: {', '.join(atlas['examples'][p]) or '—'}")
    lines += ["", "## Lived trades (приложение, осторожно с n)", ""]
    if lived.get("status") == "OK":
        lines.append(f"Matched trades: {lived['n_trades_matched']}")
        for p, st in sorted(lived["by_primary_pattern"].items(), key=lambda x: -x[1]["n"]):
            lines.append(
                f"- `{p}`: n={st['n']} WR={st['wr']} avg={st['avg_pnl']} sum={st['net_pnl_sum']}"
            )
    else:
        lines.append(str(lived))
    lines += [
        "",
        "## Правило стопа",
        atlas["stop_rule_ru"],
        "",
        atlas["note_ru"],
        "",
    ]
    (args.out_dir / "VSA_ATLAS_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"pattern_counts": counts, "primary_top": dict(list(primary_counts.items())[:10])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
