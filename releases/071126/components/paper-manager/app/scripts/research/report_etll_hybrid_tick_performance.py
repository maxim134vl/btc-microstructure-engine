#!/usr/bin/env python3
"""Hybrid tick performance report: DD / Sharpe / Sortino / Calmar + period × TF.

Uses market occurrence timestamps (not wall-clock exit_ts) when available.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "live"))

from paper_pnl_engine import INITIAL_CAPITAL, summarize_trades  # noqa: E402

SANDBOX = ROOT / "data" / "research" / "external_traders" / "etll_hybrid_tick"
TIMEFRAMES = ("M15", "M30", "H1", "H4")


def _load_trades(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
        frame = pd.DataFrame(rows)
    else:
        raise ValueError(f"unsupported trades path: {path}")
    if not len(frame):
        return frame
    return frame


def _market_ts(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    """Parse the first available market-clock column, in preference order.

    format="ISO8601" is required, not cosmetic: manager closes are stamped on the
    bar boundary ("...T03:15:00Z") while protective exits carry the exchange tick
    time ("...T17:13:13.064000Z"). Letting pandas infer one format off the first
    row coerces the whole fractional-second group to NaT, which silently drops
    every TP and SL exit — 70% of trades and 93% of the PnL.

    Wall-clock fields (execution_timestamp / exit_ts / materialized_timestamp) are
    deliberately NOT in the fallback chain: they record when the replay ran, so
    using them here stacks every affected trade onto the run date instead of the
    date it traded.
    """
    out = pd.Series([pd.NaT] * len(frame), index=frame.index, dtype="datetime64[ns, UTC]")
    for col in columns:
        if col not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[col], utc=True, errors="coerce", format="ISO8601")
        out = out.fillna(parsed)
    return out


def _occurrence_ts(frame: pd.DataFrame) -> pd.Series:
    return _market_ts(frame, ("context_occurrence_timestamp",))


def _entry_ts(frame: pd.DataFrame) -> pd.Series:
    return _market_ts(frame, ("decision_available_at", "context_occurrence_timestamp"))


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["timeframe"] = out.get("timeframe", "UNK").astype(str).str.upper()
    out["net_pnl"] = pd.to_numeric(out.get("net_pnl_usd", out.get("net_pnl")), errors="coerce").fillna(0.0)
    out["gross_pnl"] = pd.to_numeric(out.get("gross_pnl_usd", out.get("gross_pnl")), errors="coerce")
    if out["gross_pnl"].isna().all():
        out["gross_pnl"] = out["net_pnl"]
    out["fees"] = pd.to_numeric(out.get("fees_usd", out.get("fees")), errors="coerce").fillna(0.0)
    out["slippage"] = pd.to_numeric(out.get("slippage_usd", out.get("slippage")), errors="coerce").fillna(0.0)
    out["exit_ts"] = _occurrence_ts(out)
    out["entry_ts"] = _entry_ts(out)
    # if entry missing, use exit
    out["entry_ts"] = out["entry_ts"].fillna(out["exit_ts"])
    out = out.dropna(subset=["exit_ts"]).sort_values("exit_ts").reset_index(drop=True)
    exit_naive = out["exit_ts"].dt.tz_convert("UTC").dt.tz_localize(None)
    out["month"] = exit_naive.dt.strftime("%Y-%m")
    out["quarter"] = exit_naive.dt.to_period("Q").astype(str)
    out["year"] = exit_naive.dt.strftime("%Y")
    if "exit_reason" not in out.columns:
        out["exit_reason"] = out.get("trigger_type", "UNKNOWN")
    return out


def _records_for_summarize(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, r in frame.iterrows():
        rows.append(
            {
                "trade_id": r.get("trade_id") or r.get("position_id"),
                "net_pnl": float(r["net_pnl"]),
                "gross_pnl": float(r["gross_pnl"]) if pd.notna(r["gross_pnl"]) else float(r["net_pnl"]),
                "fees": float(r["fees"]),
                "slippage": float(r["slippage"]),
                "entry_ts": r["entry_ts"].isoformat() if pd.notna(r["entry_ts"]) else None,
                "exit_ts": r["exit_ts"].isoformat() if pd.notna(r["exit_ts"]) else None,
                "r_multiple": r.get("realized_r"),
            }
        )
    return rows


def _safe_summarize(records: list[dict[str, Any]], *, initial_equity: float) -> dict[str, Any]:
    try:
        return summarize_trades(records, initial_capital=initial_equity)
    except OverflowError:
        # Extreme short windows / huge equity jumps can blow annualisation.
        return {"model_evaluation_metrics": {}, "detailed_pnl": {}}


def _local_dd_sharpe(frame: pd.DataFrame, *, initial_equity: float) -> dict[str, Any]:
    """Fallback risk metrics when paper_pnl_engine annualisation overflows."""
    equity = float(initial_equity)
    peak = equity
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    returns: list[float] = []
    for pnl in frame["net_pnl"].astype(float).tolist():
        prev = equity
        equity += float(pnl)
        if prev > 0:
            returns.append((equity / prev) - 1.0)
        if equity > peak:
            peak = equity
        dd_usd = equity - peak
        dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0
        if dd_pct < max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd_usd
    sharpe = sortino = calmar = None
    if len(returns) >= 2:
        mean_r = sum(returns) / len(returns)
        var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        downside = [min(0.0, r) for r in returns]
        dvar = sum(r * r for r in downside) / len(returns)
        dstd = math.sqrt(dvar) if dvar > 0 else 0.0
        start = frame["exit_ts"].iloc[0]
        end = frame["exit_ts"].iloc[-1]
        elapsed_days = max((end - start).total_seconds() / 86400.0, 1e-9)
        periods_per_year = len(returns) / (elapsed_days / 365.25)
        scale = math.sqrt(periods_per_year) if periods_per_year > 0 else 1.0
        if std > 0:
            sharpe = mean_r / std * scale
        if dstd > 0:
            sortino = mean_r / dstd * scale
        total_return = equity / float(initial_equity) - 1.0 if initial_equity else 0.0
        try:
            ann = (equity / float(initial_equity)) ** (365.25 / elapsed_days) - 1.0
            if math.isfinite(ann) and max_dd_pct < 0:
                calmar = ann * 100.0 / abs(max_dd_pct)
        except OverflowError:
            ann = None
            calmar = None
        else:
            if not math.isfinite(ann) if ann is not None else True:
                pass
    return {
        "max_drawdown_pct": round(max_dd_pct, 6),
        "max_drawdown_usd": round(max_dd_usd, 6),
        "sharpe_ratio": None if sharpe is None else round(sharpe, 6),
        "sortino_ratio": None if sortino is None else round(sortino, 6),
        "calmar_ratio": None if calmar is None else round(calmar, 6),
    }


def _slice_metrics(frame: pd.DataFrame, *, initial_equity: float) -> dict[str, Any]:
    if not len(frame):
        return {
            "n": 0,
            "wr": None,
            "pf": None,
            "net_pnl_usd": 0.0,
            "avg_win": None,
            "avg_loss": None,
            "max_drawdown_pct": None,
            "max_drawdown_usd": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "calmar_ratio": None,
            "exit_reasons": {},
        }
    net = frame["net_pnl"]
    wins = net[net > 0]
    losses = net[net < 0]
    gp = float(wins.sum())
    gl = float(abs(losses.sum()))
    summary = _safe_summarize(_records_for_summarize(frame), initial_equity=initial_equity)
    metrics = summary.get("model_evaluation_metrics") or {}
    detailed = summary.get("detailed_pnl") or {}
    if not metrics.get("sharpe_ratio") and not metrics.get("max_drawdown_pct"):
        metrics = {**metrics, **_local_dd_sharpe(frame, initial_equity=initial_equity)}
    exit_reasons = (
        frame["exit_reason"].astype(str).value_counts().to_dict() if "exit_reason" in frame.columns else {}
    )
    return {
        "n": int(len(frame)),
        "wr": float((net > 0).mean()),
        "pf": (gp / gl) if gl > 0 else None,
        "net_pnl_usd": float(net.sum()),
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "max_drawdown_usd": metrics.get("max_drawdown_usd"),
        "max_drawdown_duration": metrics.get("max_drawdown_duration"),
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "sortino_ratio": metrics.get("sortino_ratio"),
        "calmar_ratio": metrics.get("calmar_ratio"),
        "annualized_return_pct": detailed.get("annualized_return_pct"),
        "total_return_pct": detailed.get("total_return_pct"),
        "expectancy_per_trade": metrics.get("expectancy_per_trade"),
        "exit_reasons": {str(k): int(v) for k, v in exit_reasons.items()},
        "from_ts": frame["exit_ts"].iloc[0].isoformat(),
        "to_ts": frame["exit_ts"].iloc[-1].isoformat(),
    }


def _period_table(frame: pd.DataFrame, *, period_col: str, initial_equity: float) -> dict[str, Any]:
    out: dict[str, Any] = {"overall": {}, "by_timeframe": {}}
    for period, part in frame.groupby(period_col, sort=True):
        out["overall"][str(period)] = _slice_metrics(part, initial_equity=initial_equity)
    for tf in TIMEFRAMES:
        tf_frame = frame[frame["timeframe"] == tf]
        out["by_timeframe"][tf] = {}
        if not len(tf_frame):
            continue
        for period, part in tf_frame.groupby(period_col, sort=True):
            out["by_timeframe"][tf][str(period)] = _slice_metrics(part, initial_equity=initial_equity)
    return out


def build_report(
    trades: pd.DataFrame,
    *,
    initial_equity: float,
    source: str,
    paper_epoch_id: str | None = None,
) -> dict[str, Any]:
    prepared = _prepare(trades)
    by_tf = {
        tf: _slice_metrics(prepared[prepared["timeframe"] == tf], initial_equity=initial_equity)
        for tf in TIMEFRAMES
    }
    return {
        "stage": "ETLL_HYBRID_TICK_PERFORMANCE_REPORT",
        "source": source,
        "paper_epoch_id": paper_epoch_id,
        "initial_equity_usd": initial_equity,
        "timestamp_basis": "context_occurrence_timestamp_prefer_market",
        "closed_trades": int(len(prepared)),
        "overall": _slice_metrics(prepared, initial_equity=initial_equity),
        "by_timeframe": by_tf,
        "monthly": _period_table(prepared, period_col="month", initial_equity=initial_equity),
        "quarterly": _period_table(prepared, period_col="quarter", initial_equity=initial_equity),
        "yearly": _period_table(prepared, period_col="year", initial_equity=initial_equity),
    }


def _fmt(v: Any, digits: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if math.isinf(v):
            return "inf"
        return f"{v:.{digits}f}"
    return str(v)


def _md_metrics_table(title: str, rows: dict[str, dict[str, Any]]) -> str:
    lines = [
        f"### {title}",
        "",
        "| Slice | n | WR | PF | Net $ | MaxDD % | MaxDD $ | Sharpe | Sortino | Calmar |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, m in rows.items():
        lines.append(
            "| {name} | {n} | {wr} | {pf} | {net} | {dd_pct} | {dd_usd} | {sh} | {so} | {ca} |".format(
                name=name,
                n=m.get("n", 0),
                wr=_fmt(m.get("wr"), 3),
                pf=_fmt(m.get("pf"), 3),
                net=_fmt(m.get("net_pnl_usd"), 2),
                dd_pct=_fmt(m.get("max_drawdown_pct"), 3),
                dd_usd=_fmt(m.get("max_drawdown_usd"), 2),
                sh=_fmt(m.get("sharpe_ratio"), 3),
                so=_fmt(m.get("sortino_ratio"), 3),
                ca=_fmt(m.get("calmar_ratio"), 3),
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_markdown(report: dict[str, Any]) -> str:
    parts = [
        "# Hybrid Tick Performance Report",
        "",
        f"- epoch: `{report.get('paper_epoch_id')}`",
        f"- source: `{report.get('source')}`",
        f"- closed_trades: **{report.get('closed_trades')}**",
        f"- initial_equity_usd: {report.get('initial_equity_usd')}",
        f"- timestamp_basis: `{report.get('timestamp_basis')}`",
        "",
    ]
    overall_rows = {"OVERALL": report["overall"]}
    overall_rows.update({tf: report["by_timeframe"][tf] for tf in TIMEFRAMES})
    parts.append(_md_metrics_table("Overall + by timeframe", overall_rows))

    for period_name in ("yearly", "quarterly", "monthly"):
        block = report[period_name]["overall"]
        if not block:
            continue
        parts.append(_md_metrics_table(f"{period_name.title()} (all TF)", block))
        for tf in TIMEFRAMES:
            tf_block = report[period_name]["by_timeframe"].get(tf) or {}
            if tf_block:
                parts.append(_md_metrics_table(f"{period_name.title()} — {tf}", tf_block))
    return "\n".join(parts) + "\n"


def _resolve_trades_path(explicit: Path | None) -> tuple[Path, str | None]:
    if explicit is not None:
        return explicit, None
    # Prefer durable MaksTiger archive (survives local wipe)
    tiger = Path("/Volumes/MaksTiger/btc-ml/research/etll_hybrid_tick/archive")
    for root in (tiger, SANDBOX / "archive"):
        if not root.exists():
            continue
        epochs = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)
        for ep in epochs:
            for cand in (ep / "lived_trades.parquet", ep / "books" / "trades.jsonl"):
                if cand.exists() and cand.stat().st_size > 0:
                    return cand, ep.name
    lived = SANDBOX / "lived_replay" / "lived_trades.parquet"
    if lived.exists():
        return lived, None
    # live books
    books_root = SANDBOX / "data" / "trading" / "intrabar_paper"
    if books_root.exists():
        for ep in sorted(books_root.glob("ETLL_HYBRID_TICK_V1_*"), reverse=True):
            tj = ep / "books" / "trades.jsonl"
            if tj.exists() and tj.stat().st_size > 0:
                return tj, ep.name
    raise FileNotFoundError("no Hybrid tick trades found under Tiger/local archive or sandbox")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trades", type=Path, default=None)
    ap.add_argument("--initial-equity", type=float, default=None)
    ap.add_argument("--out-dir", type=Path, default=SANDBOX / "reports")
    ap.add_argument("--paper-epoch-id", type=str, default=None)
    args = ap.parse_args()

    trades_path, epoch_guess = _resolve_trades_path(args.trades)
    initial = args.initial_equity
    if initial is None:
        cfg_path = ROOT / "config" / "intrabar_paper_execution.json"
        initial = float(json.loads(cfg_path.read_text(encoding="utf-8")).get("initial_equity_usd", INITIAL_CAPITAL))

    trades = _load_trades(trades_path)
    report = build_report(
        trades,
        initial_equity=float(initial),
        source=str(trades_path),
        paper_epoch_id=args.paper_epoch_id or epoch_guess,
    )
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "performance_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    md = render_markdown(report)
    (out_dir / "PERFORMANCE_REPORT.md").write_text(md, encoding="utf-8")
    print(json.dumps({"wrote": str(out_dir), "closed_trades": report["closed_trades"], "overall": report["overall"]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
