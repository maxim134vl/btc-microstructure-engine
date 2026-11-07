#!/usr/bin/env python3
"""Step D: baseline vs Shadow Auction overlay metrics + wiring verdict.

Reads lived trades + Step C join. Produces full risk/PnL metrics per scenario:
baseline, context overlays, entry-gate counterfactuals. LONG/SHORT and hold-duration
splits. Period max drawdowns (month/quarter/half-year/year) + daily equity DD.

Writes under tip_full_footprint/d/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts" / "live") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "live"))

from paper_pnl_engine import INITIAL_CAPITAL, build_equity_curve, summarize_trades  # type: ignore

DEFAULT_LIVED = (
    ROOT / "data/research/external_traders/market_pack_btc_m15/lived_replay/lived_trades.parquet"
)
DEFAULT_JOIN = (
    ROOT
    / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_full_footprint"
    / "join/lived_x_auction_x_footprint.parquet"
)
DEFAULT_OUT = (
    ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_full_footprint/d"
)

FP_NON_NEUTRAL = {
    "STOPPING_VOLUME",
    "ABSORPTION_VOLUME",
    "EXHAUSTION_VOLUME",
    "CONTINUATION_VOLUME",
}
PRESSURE_PHASES = {
    "BALANCE_UPPER_PRESSURE",
    "BALANCE_LOWER_PRESSURE",
    "EXTREME_UP_PARTICIPATION",
    "EXTREME_DOWN_PARTICIPATION",
    "UP_PRESSURE_ACTIVE",
    "DOWN_PRESSURE_ACTIVE",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(ts) else ts


def _trade_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append(
            {
                "trade_id": r.get("trade_id"),
                "side": str(r.get("side") or "").upper(),
                "entry_ts": r.get("entry_ts"),
                "exit_ts": r.get("exit_ts"),
                "net_pnl": float(r["net_pnl_usd"]) if pd.notna(r.get("net_pnl_usd")) else 0.0,
                "r_multiple": float(r["r_multiple"]) if pd.notna(r.get("r_multiple")) else 0.0,
            }
        )
    return rows


def _max_drawdown_on_series(values: np.ndarray) -> tuple[float, float, int]:
    """Return max_dd_pct, max_dd_usd, trough_idx (relative to series)."""
    if len(values) == 0:
        return 0.0, 0.0, 0
    peak = values[0]
    max_dd_pct = 0.0
    max_dd_usd = 0.0
    trough_idx = 0
    peak_idx = 0
    for i, eq in enumerate(values):
        if eq >= peak:
            peak = eq
            peak_idx = i
        if peak <= 0:
            continue
        dd_usd = eq - peak
        dd_pct = dd_usd / peak * 100.0
        if dd_pct < max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd_usd
            trough_idx = i
    return round(max_dd_pct, 6), round(max_dd_usd, 6), trough_idx


def _daily_equity_series(
    trades: list[dict[str, Any]], *, initial_capital: float = INITIAL_CAPITAL
) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    ordered = sorted(trades, key=lambda t: str(t.get("exit_ts") or t.get("entry_ts") or ""))
    start = _parse_ts(ordered[0].get("entry_ts")) or pd.Timestamp.now(tz="UTC")
    end = _parse_ts(ordered[-1].get("exit_ts")) or start
    days = pd.date_range(start.normalize(), end.normalize(), freq="D", tz="UTC")
    equity = float(initial_capital)
    curve: dict[pd.Timestamp, float] = {days[0]: equity}
    for trade in ordered:
        equity += float(trade.get("net_pnl") or 0.0)
        ts = _parse_ts(trade.get("exit_ts") or trade.get("entry_ts"))
        if ts is not None:
            curve[ts.normalize()] = equity
    series = pd.Series(curve).sort_index()
    full = pd.Series(index=days, dtype=float)
    for d in days:
        prior = series[series.index <= d]
        full[d] = prior.iloc[-1] if len(prior) else float(initial_capital)
    return full


def _period_drawdown_table(daily_eq: pd.Series, freq: str) -> list[dict[str, Any]]:
    if daily_eq.empty:
        return []
    grouped = daily_eq.groupby(pd.Grouper(freq=freq))
    out: list[dict[str, Any]] = []
    for period, chunk in grouped:
        if chunk.empty or pd.isna(period):
            continue
        vals = chunk.to_numpy(dtype=float)
        dd_pct, dd_usd, _ = _max_drawdown_on_series(vals)
        out.append(
            {
                "period": str(period),
                "freq": freq,
                "max_drawdown_pct": dd_pct,
                "max_drawdown_usd": dd_usd,
                "start_equity": round(float(vals[0]), 2),
                "end_equity": round(float(vals[-1]), 2),
                "period_pnl": round(float(vals[-1] - vals[0]), 2),
            }
        )
    return out


def _recovery_days(daily_eq: pd.Series) -> dict[str, Any]:
    if daily_eq.empty:
        return {"recovery_days": None, "max_drawdown_pct": None, "trough_date": None, "recovered_date": None}
    vals = daily_eq.to_numpy(dtype=float)
    dates = daily_eq.index
    dd_pct, dd_usd, trough_idx = _max_drawdown_on_series(vals)
    if trough_idx <= 0:
        return {
            "max_drawdown_pct": dd_pct,
            "max_drawdown_usd": dd_usd,
            "trough_date": str(dates[trough_idx]),
            "recovery_days": 0,
            "recovered_date": str(dates[trough_idx]),
        }
    peak_before = float(np.max(vals[:trough_idx + 1]))
    recovered_date = None
    recovery_days = None
    for j in range(trough_idx, len(vals)):
        if vals[j] >= peak_before:
            recovered_date = dates[j]
            recovery_days = (dates[j] - dates[trough_idx]).days
            break
    return {
        "max_drawdown_pct": dd_pct,
        "max_drawdown_usd": dd_usd,
        "trough_date": str(dates[trough_idx]),
        "peak_equity_before_trough": round(peak_before, 2),
        "recovery_days": recovery_days,
        "recovered_date": str(recovered_date) if recovered_date is not None else None,
        "still_underwater_at_end": recovered_date is None,
    }


def _side_breakdown(df: pd.DataFrame) -> dict[str, Any]:
    sides: dict[str, Any] = {}
    total = len(df)
    for side in ("LONG", "SHORT"):
        g = df[df["side"].astype(str).str.upper() == side]
        n = len(g)
        if n == 0:
            sides[side] = {"n": 0, "pct_of_book": 0.0, "win_rate": None, "net_pnl_usd": 0.0}
            continue
        net = pd.to_numeric(g["net_pnl_usd"], errors="coerce").fillna(0.0)
        wins = net[net > 0]
        losses = net[net < 0]
        pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
        sides[side] = {
            "n": int(n),
            "pct_of_book": round(n / total * 100.0, 2) if total else 0.0,
            "win_rate": round(float((net > 0).mean()), 6),
            "net_pnl_usd": round(float(net.sum()), 2),
            "profit_factor": round(pf, 4) if pf is not None else None,
            "avg_win_usd": round(float(wins.mean()), 2) if len(wins) else None,
            "avg_loss_usd": round(float(losses.mean()), 2) if len(losses) else None,
            "expectancy_usd": round(float(net.mean()), 2),
        }
    return sides


def _hold_duration_breakdown(df: pd.DataFrame) -> dict[str, Any]:
    work = df.copy()
    work["entry_ts"] = pd.to_datetime(work["entry_ts"], utc=True)
    work["exit_ts"] = pd.to_datetime(work["exit_ts"], utc=True)
    work["hold_minutes"] = (work["exit_ts"] - work["entry_ts"]).dt.total_seconds() / 60.0
    median_hold = float(work["hold_minutes"].median()) if len(work) else 0.0
    out: dict[str, Any] = {"median_hold_minutes": round(median_hold, 2)}
    for label, mask in (
        ("short_hold_lt_median", work["hold_minutes"] < median_hold),
        ("long_hold_gte_median", work["hold_minutes"] >= median_hold),
    ):
        g = work[mask]
        n = len(g)
        net = pd.to_numeric(g["net_pnl_usd"], errors="coerce").fillna(0.0)
        out[label] = {
            "n": int(n),
            "win_rate": round(float((net > 0).mean()), 6) if n else None,
            "net_pnl_usd": round(float(net.sum()), 2),
            "avg_hold_minutes": round(float(g["hold_minutes"].mean()), 2) if n else None,
        }
    return out


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or (isinstance(v, str) and v in ("Infinity", "inf")):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _metrics_package(df: pd.DataFrame, *, scenario_id: str, label: str) -> dict[str, Any]:
    trades = _trade_rows(df)
    summary = summarize_trades(trades, initial_capital=INITIAL_CAPITAL)
    detailed = summary["detailed_pnl"]
    metrics = summary["model_evaluation_metrics"]
    daily_eq = _daily_equity_series(trades)
    daily_dd_pct, daily_dd_usd, _ = _max_drawdown_on_series(daily_eq.to_numpy(dtype=float))

    period_rows: list[dict[str, Any]] = []
    for freq, name in (
        ("ME", "month"),
        ("QE", "quarter"),
        ("6ME", "half_year"),
        ("YE", "year"),
    ):
        for row in _period_drawdown_table(daily_eq, freq):
            row["bucket"] = name
            period_rows.append(row)

    recovery = _recovery_days(daily_eq)

    pf = metrics.get("profit_factor")
    if isinstance(pf, str):
        pf_display = pf
        pf_num = float("inf") if pf.lower().startswith("inf") else None
    else:
        pf_display = pf
        pf_num = _safe_float(pf)

    return {
        "scenario_id": scenario_id,
        "label": label,
        "n_trades": int(len(df)),
        "pct_of_baseline": None,  # filled later
        "net_pnl_usd": round(detailed.get("realized_pnl", 0.0), 2),
        "total_return_pct": detailed.get("total_return_pct"),
        "win_rate": round(_safe_float(metrics.get("win_rate_pct")) / 100.0, 6),
        "loss_rate": round(_safe_float(metrics.get("loss_rate_pct")) / 100.0, 6),
        "profit_factor": pf_display,
        "profit_factor_numeric": pf_num,
        "payoff_ratio": metrics.get("payoff_ratio"),
        "expectancy_per_trade_usd": metrics.get("expectancy_per_trade"),
        "expectancy_r": metrics.get("expectancy_r"),
        "avg_r_multiple": metrics.get("average_r"),
        "median_r_multiple": metrics.get("median_r"),
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "sortino_ratio": metrics.get("sortino_ratio"),
        "calmar_ratio": metrics.get("calmar_ratio"),
        "max_drawdown_pct_trade_curve": metrics.get("max_drawdown_pct"),
        "max_drawdown_usd_trade_curve": metrics.get("max_drawdown_usd"),
        "max_drawdown_duration_trade_curve": metrics.get("max_drawdown_duration"),
        "max_drawdown_pct_daily": daily_dd_pct,
        "max_drawdown_usd_daily": daily_dd_usd,
        "recovery_factor": metrics.get("recovery_factor"),
        "recovery_daily": recovery,
        "exposure_time_pct": metrics.get("exposure_time_pct"),
        "trades_per_day": metrics.get("trades_per_day"),
        "avg_holding_minutes": metrics.get("average_holding_minutes"),
        "consecutive_wins": metrics.get("consecutive_wins"),
        "consecutive_losses": metrics.get("consecutive_losses"),
        "side_breakdown": _side_breakdown(df),
        "hold_duration_breakdown": _hold_duration_breakdown(df),
        "period_max_drawdowns": period_rows,
        "equity_curve_trade_close": summary.get("equity_curve"),
    }


def _compare_to_baseline(baseline: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    b_n = baseline["n_trades"] or 1
    s_n = scenario["n_trades"]
    b_pnl = _safe_float(baseline["net_pnl_usd"])
    s_pnl = _safe_float(scenario["net_pnl_usd"])
    proportional_pnl = b_pnl * (s_n / b_n) if b_n else 0.0
    pnl_retention_vs_proportional = (s_pnl / proportional_pnl) if proportional_pnl else None

    def delta(key: str, sub: bool = False) -> float | None:
        a = scenario.get(key)
        b = baseline.get(key)
        if a is None or b is None:
            return None
        if isinstance(a, str) or isinstance(b, str):
            return None
        return round(float(a) - float(b), 6)

    return {
        "n_trades_delta": s_n - b_n,
        "pct_retained": round(s_n / b_n * 100.0, 2) if b_n else 0.0,
        "net_pnl_delta_usd": round(s_pnl - b_pnl, 2),
        "pnl_retention_vs_proportional": (
            round(pnl_retention_vs_proportional, 4) if pnl_retention_vs_proportional is not None else None
        ),
        "win_rate_delta_pp": round((scenario.get("win_rate") - baseline.get("win_rate")) * 100.0, 2),
        "profit_factor_delta": delta("profit_factor_numeric"),
        "sharpe_delta": delta("sharpe_ratio"),
        "sortino_delta": delta("sortino_ratio"),
        "calmar_delta": delta("calmar_ratio"),
        "max_dd_daily_delta_pp": delta("max_drawdown_pct_daily"),
        "expectancy_delta_usd": delta("expectancy_per_trade_usd"),
    }


def _gate_verdict(
    scenario: dict[str, Any],
    compare: dict[str, Any],
    *,
    mode: str,
) -> str:
    n = scenario["n_trades"]
    if mode == "context":
        return "GO_CONTEXT_LAYER"
    if n < 50:
        return "NO_GO_LOW_SAMPLE"
    wr_d = compare.get("win_rate_delta_pp") or 0.0
    pnl_ret = compare.get("pnl_retention_vs_proportional") or 0.0
    sharpe_d = compare.get("sharpe_delta") or 0.0
    dd_d = compare.get("max_dd_daily_delta_pp") or 0.0  # more negative = worse DD
    if wr_d >= 2.0 and pnl_ret >= 0.85 and sharpe_d >= -0.15 and dd_d >= -1.0:
        return "GO_ENTRY_GATE"
    if wr_d >= 1.0 and pnl_ret >= 0.70:
        return "REVIEW_ENTRY_GATE"
    if pnl_ret < 0.50 or (wr_d < 0 and sharpe_d < -0.3):
        return "NO_GO_HURTS_EDGE"
    return "REVIEW_MIXED"


def _overlay_scenarios(join: pd.DataFrame) -> list[tuple[str, str, str, Callable[[pd.DataFrame], pd.Series]]]:
    interesting = (join["interesting_before"].fillna("").str.len() > 0) | (
        join["fp_volume_event"].isin(list(FP_NON_NEUTRAL))
    )
    hold_balance_then = join["hold_path_label"].astype(str).str.startswith("BALANCE_THEN_", na=False)
    pressure = join["episode_phase"].isin(PRESSURE_PHASES)
    complete = join["coverage_status"] == "COMPLETE"
    no_shadow_excluded = join["coverage_status"] != "NO_SHADOW_COVERAGE"

    return [
        (
            "baseline_all",
            "Baseline — all lived trades (canonical book)",
            "baseline",
            lambda df: pd.Series(True, index=df.index),
        ),
        (
            "context_only",
            "Context-only — same book, Auction as annotation layer",
            "context",
            lambda df: pd.Series(True, index=df.index),
        ),
        (
            "overlay_interesting_context",
            "Entry gate — interesting Auction sequence OR non-neutral footprint",
            "entry_gate",
            lambda df: interesting,
        ),
        (
            "overlay_fp_exhaustion",
            "Entry gate — footprint EXHAUSTION_VOLUME at entry",
            "entry_gate",
            lambda df: df["fp_volume_event"] == "EXHAUSTION_VOLUME",
        ),
        (
            "overlay_fp_non_neutral",
            "Entry gate — any non-NEUTRAL footprint event",
            "entry_gate",
            lambda df: df["fp_volume_event"].isin(list(FP_NON_NEUTRAL)),
        ),
        (
            "overlay_fp_climactic",
            "Entry gate — CLIMACTIC_PARTICIPATION at entry",
            "entry_gate",
            lambda df: df["fp_participation_state"] == "CLIMACTIC_PARTICIPATION",
        ),
        (
            "overlay_hold_balance_then",
            "Entry gate — hold_path BALANCE_THEN_*",
            "entry_gate",
            lambda df: hold_balance_then,
        ),
        (
            "overlay_auction_pressure",
            "Entry gate — balance pressure / extreme phase at entry",
            "entry_gate",
            lambda df: pressure,
        ),
        (
            "overlay_skip_no_shadow",
            "Veto-lite — exclude NO_SHADOW_COVERAGE trades",
            "veto",
            lambda df: no_shadow_excluded,
        ),
        (
            "overlay_coverage_complete",
            "Strict — COMPLETE shadow coverage only (small n)",
            "entry_gate",
            lambda df: complete,
        ),
    ]


def _wiring_verdict(
    scenarios: list[dict[str, Any]],
    compares: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    baseline = next(s for s in scenarios if s["scenario_id"] == "baseline_all")
    gates = []
    for s in scenarios:
        if s["scenario_id"] in ("baseline_all", "context_only"):
            continue
        mode = s.get("mode", "entry_gate")
        if mode == "context":
            verdict = "GO_CONTEXT_LAYER"
        elif mode == "baseline":
            verdict = "BASELINE_REFERENCE"
        else:
            verdict = _gate_verdict(s, compares[s["scenario_id"]], mode=mode)
        gates.append(
            {
                "scenario_id": s["scenario_id"],
                "label": s["label"],
                "mode": mode,
                "n_trades": s["n_trades"],
                "win_rate": s["win_rate"],
                "net_pnl_usd": s["net_pnl_usd"],
                "profit_factor": s["profit_factor"],
                "sharpe_ratio": s["sharpe_ratio"],
                "max_drawdown_pct_daily": s["max_drawdown_pct_daily"],
                "verdict": verdict,
                "compare": compares.get(s["scenario_id"]),
            }
        )

    go_gates = [g for g in gates if g["verdict"] == "GO_ENTRY_GATE"]
    review = [g for g in gates if g["verdict"].startswith("REVIEW")]
    no_go = [g for g in gates if g["verdict"].startswith("NO_GO")]

    overall = "GO_WIRING_CONTEXT_PLUS_SELECTIVE_GATES"
    if not go_gates and review:
        overall = "REVIEW_WIRING_CONTEXT_ONLY"
    if not go_gates and not review:
        overall = "NO_GO_ENTRY_GATES_CONTEXT_ONLY"

    return {
        "overall_verdict": overall,
        "fidelity": "PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1",
        "baseline_reference": {
            "n_trades": baseline["n_trades"],
            "win_rate": baseline["win_rate"],
            "net_pnl_usd": baseline["net_pnl_usd"],
            "profit_factor": baseline["profit_factor"],
            "sharpe_ratio": baseline["sharpe_ratio"],
            "max_drawdown_pct_daily": baseline["max_drawdown_pct_daily"],
            "side_breakdown": baseline["side_breakdown"],
        },
        "scenario_gates": gates,
        "go_entry_gates": [g["scenario_id"] for g in go_gates],
        "review_scenarios": [g["scenario_id"] for g in review],
        "no_go_scenarios": [g["scenario_id"] for g in no_go],
        "wiring_recommendation_ru": (
            "1) Подключить Shadow Auction + footprint как brain/context (regime, sequence, fp labels) — GO. "
            "2) Entry hard-gate только на сценарии с GO_ENTRY_GATE и pnl_retention≥0.85. "
            "3) Не gate на STOPPING_VOLUME alone (редкий). "
            "4) Учитывать PARTIAL/NO_SHADOW coverage при live wiring. "
            "5) Не использовать post-hoc метрики (price after entry, sliding lookback windows) — "
            "не часть канонической модели; исключены из D-сценариев."
        ),
        "cognition_symlinks_note": (
            "Symlink volume_response_state + volume_classification_memory to footprint_full_etll "
            "for replay fidelity; candle_structure stays canonical unless footprint candle plane added."
        ),
    }


def _write_md(
    out_dir: Path,
    scenarios: list[dict[str, Any]],
    compares: dict[str, dict[str, Any]],
    wiring: dict[str, Any],
) -> None:
    baseline = next(s for s in scenarios if s["scenario_id"] == "baseline_all")
    lines = [
        "# D — Baseline vs Shadow Auction overlays",
        "",
        f"Generated: {_utc_now()}",
        f"Fidelity: `PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1`",
        "",
        f"## Overall wiring verdict: **{wiring['overall_verdict']}**",
        "",
        wiring["wiring_recommendation_ru"],
        "",
        "## Baseline (canonical lived book)",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Trades | {baseline['n_trades']} |",
        f"| Net PnL | {baseline['net_pnl_usd']:,.0f} USD |",
        f"| Win rate | {baseline['win_rate']*100:.1f}% |",
        f"| Profit factor | {baseline['profit_factor']} |",
        f"| Sharpe | {baseline['sharpe_ratio']} |",
        f"| Sortino | {baseline['sortino_ratio']} |",
        f"| Calmar | {baseline['calmar_ratio']} |",
        f"| Max DD (daily) | {baseline['max_drawdown_pct_daily']:.2f}% |",
        f"| Recovery factor | {baseline['recovery_factor']} |",
        "",
        "### LONG / SHORT (baseline)",
        "",
        "| Side | n | % book | Win rate | Net PnL | PF |",
        "|------|---|--------|----------|---------|-----|",
    ]
    for side in ("LONG", "SHORT"):
        sb = baseline["side_breakdown"][side]
        lines.append(
            f"| {side} | {sb['n']} | {sb['pct_of_book']:.1f}% | "
            f"{sb['win_rate']*100:.1f}% | {sb['net_pnl_usd']:,.0f} | {sb.get('profit_factor')} |"
        )
    lines.extend(["", "## Overlay scenarios vs baseline", "", "| Scenario | n | % kept | Win | Δ win | PnL | PF | Sharpe | MaxDD daily | Verdict |"])
    for s in scenarios:
        if s["scenario_id"] == "baseline_all":
            continue
        c = compares.get(s["scenario_id"], {})
        verdict = next(
            (g["verdict"] for g in wiring["scenario_gates"] if g["scenario_id"] == s["scenario_id"]),
            "",
        )
        lines.append(
            f"| {s['scenario_id']} | {s['n_trades']} | {c.get('pct_retained', 0):.1f}% | "
            f"{s['win_rate']*100:.1f}% | {c.get('win_rate_delta_pp'):+.1f}pp | "
            f"{s['net_pnl_usd']:,.0f} | {s['profit_factor']} | {s['sharpe_ratio']} | "
            f"{s['max_drawdown_pct_daily']:.2f}% | {verdict} |"
        )
    lines.extend(
        [
            "",
            "## GO entry gates",
            "",
            ", ".join(wiring["go_entry_gates"]) or "none",
            "",
            "## Artifacts",
            "",
            "- `D_BASELINE_METRICS.json`",
            "- `D_OVERLAY_SCENARIOS.json`",
            "- `D_WIRING_VERDICT.json`",
            "- `period_drawdowns.parquet`",
            "- `daily_drawdowns.parquet`",
            "",
        ]
    )
    (out_dir / "D_BASELINE_VS_OVERLAY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lived", type=Path, default=DEFAULT_LIVED)
    parser.add_argument("--join", type=Path, default=DEFAULT_JOIN)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("load join…", flush=True)
    join = pd.read_parquet(args.join)
    lived = pd.read_parquet(args.lived)
    join["entry_ts"] = pd.to_datetime(join["entry_ts"], utc=True)
    join["exit_ts"] = pd.to_datetime(join["exit_ts"], utc=True)
    lived["entry_ts"] = pd.to_datetime(lived["entry_ts"], utc=True)
    lived["exit_ts"] = pd.to_datetime(lived["exit_ts"], utc=True)

    # Ensure side on join from lived if missing
    if "side" not in join.columns or join["side"].isna().all():
        join = join.merge(lived[["trade_id", "side"]], on="trade_id", how="left")

    scenario_defs = _overlay_scenarios(join)
    scenarios: list[dict[str, Any]] = []
    period_all: list[dict[str, Any]] = []
    daily_all: list[dict[str, Any]] = []

    for sid, label, mode, mask_fn in scenario_defs:
        mask = mask_fn(join)
        sub = join.loc[mask].copy()
        print(f"  metrics {sid} n={len(sub)}", flush=True)
        pkg = _metrics_package(sub, scenario_id=sid, label=label)
        pkg["mode"] = mode
        scenarios.append(pkg)
        for row in pkg["period_max_drawdowns"]:
            row = dict(row)
            row["scenario_id"] = sid
            period_all.append(row)
        rec = pkg["recovery_daily"]
        daily_all.append(
            {
                "scenario_id": sid,
                "max_drawdown_pct_daily": pkg["max_drawdown_pct_daily"],
                "max_drawdown_usd_daily": pkg["max_drawdown_usd_daily"],
                **{k: rec.get(k) for k in rec},
            }
        )

    baseline = next(s for s in scenarios if s["scenario_id"] == "baseline_all")
    b_n = baseline["n_trades"]
    compares: dict[str, dict[str, Any]] = {}
    for s in scenarios:
        s["pct_of_baseline"] = round(s["n_trades"] / b_n * 100.0, 2) if b_n else 0.0
        compares[s["scenario_id"]] = _compare_to_baseline(baseline, s)

    wiring = _wiring_verdict(scenarios, compares)

    # Strip heavy equity curves from summary JSON (save separately for baseline)
    baseline_full = dict(baseline)
    for s in scenarios:
        s.pop("equity_curve_trade_close", None)

    payload = {
        "generated_at": _utc_now(),
        "stage": "ETLL_D_AUCTION_FOOTPRINT_VERDICT",
        "fidelity": "PACK_TIP_FOOTPRINT_VOLUME_RESPONSE_V1",
        "n_baseline": b_n,
        "scenarios": scenarios,
        "compare_vs_baseline": compares,
    }

    (args.out_dir / "D_OVERLAY_SCENARIOS.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    baseline_export = {k: v for k, v in baseline_full.items() if k != "period_max_drawdowns"}
    (args.out_dir / "D_BASELINE_METRICS.json").write_text(
        json.dumps(baseline_export, indent=2, default=str) + "\n", encoding="utf-8"
    )
    wiring["generated_at"] = _utc_now()
    (args.out_dir / "D_WIRING_VERDICT.json").write_text(
        json.dumps(wiring, indent=2, default=str) + "\n", encoding="utf-8"
    )

    pd.DataFrame(period_all).to_parquet(args.out_dir / "period_drawdowns.parquet", index=False)
    pd.DataFrame(daily_all).to_parquet(args.out_dir / "daily_drawdowns.parquet", index=False)

    if baseline_full.get("equity_curve_trade_close"):
        eq_dir = args.out_dir / "equity_curves"
        eq_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(baseline_full["equity_curve_trade_close"]).to_parquet(
            eq_dir / "baseline_trade_close.parquet",
            index=False,
        )

    _write_md(args.out_dir, scenarios, compares, wiring)

    print(
        json.dumps(
            {
                "overall_verdict": wiring["overall_verdict"],
                "go_gates": wiring["go_entry_gates"],
                "out_dir": str(args.out_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
