"""Current active-model Drift Monitoring (MODEL-6).

OBSERVATIONAL / NON-BLOCKING — does not alter trading or System Health.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from btc_ml.model_assurance.registry import read_active_runtime
from btc_ml.model_assurance.toxic_box.common import (
    append_jsonl,
    atomic_write_json,
    canonical_json,
    load_json,
    parse_ts,
    read_jsonl,
    sha256_text,
    utc_now_iso,
)
from btc_ml.model_assurance.drift.statistics import (
    categorical_js_distance,
    count_categories,
    max_status,
    numeric_quantile_distance,
    severity_for_distance,
)

FEATURE_NUMERIC = (
    "persistence_score",
    "alignment_score",
    "confidence",
    "conviction",
    "structural_rank",
    "location_bias",
)
FEATURE_CATEGORICAL = (
    "market_context",
    "synthesis_state",
    "response_state",
    "lifecycle",
    "active",
)
TIMEFRAMES = ("M15", "M30", "H1", "H4")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "drift"
    return {
        "config": root / "config" / "model_assurance_drift_monitoring.json",
        "baselines": base / "baselines" / "baselines.jsonl",
        "windows": base / "windows" / "windows.jsonl",
        "events": base / "events" / "drift_events.jsonl",
        "current_metrics": base / "snapshots" / "current_metrics.json",
        "summary": base / "snapshots" / "latest_summary.json",
        "checkpoint": base / "runtime" / "checkpoint.json",
        "health": base / "runtime" / "health.json",
        "external_summary": root
        / "data"
        / "model_assurance"
        / "toxic_box"
        / "external_data"
        / "snapshots"
        / "latest_summary.json",
        "external_sources": root
        / "data"
        / "model_assurance"
        / "toxic_box"
        / "external_data"
        / "sources"
        / "current_sources.json",
        "cognition_health": root / "data" / "runtime" / "intrabar_cognition_health.json",
        "raw_root": root / "data" / "raw_market_events_v2",
        "bv_predictions": root
        / "data"
        / "model_assurance"
        / "behavioral_validation"
        / "events"
        / "context_predictions.jsonl",
        "bv_outcomes": root
        / "data"
        / "model_assurance"
        / "behavioral_validation"
        / "outcomes"
        / "context_outcomes.jsonl",
        "econ_evals": root
        / "data"
        / "model_assurance"
        / "economic_validation"
        / "trades"
        / "trade_evaluations.jsonl",
        "books_root": root / "data" / "trading" / "intrabar_paper",
    }


def load_config(repo_root: Path | None = None) -> dict[str, Any]:
    return json.loads(paths(repo_root)["config"].read_text(encoding="utf-8"))


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _identity_key(active: dict[str, Any], *, branch: str, metric: str, timeframe: str | None) -> str:
    return canonical_json(
        {
            "registry_record_id": active.get("registry_record_id"),
            "model_version": active.get("model_version"),
            "runtime_fingerprint": active.get("runtime_fingerprint"),
            "paper_epoch_id": active.get("paper_epoch_id"),
            "branch": branch,
            "timeframe": timeframe,
            "metric": metric,
        }
    )


def baseline_id_for(active: dict[str, Any], *, branch: str, metric: str, timeframe: str | None) -> str:
    return "BL6_" + sha256_text(_identity_key(active, branch=branch, metric=metric, timeframe=timeframe))[:28]


def window_id_for(
    active: dict[str, Any],
    *,
    branch: str,
    metric: str,
    timeframe: str | None,
    window_index: int,
) -> str:
    return "WIN6_" + sha256_text(
        canonical_json(
            {
                "identity": _identity_key(active, branch=branch, metric=metric, timeframe=timeframe),
                "window_index": window_index,
            }
        )
    )[:28]


def drift_event_id_for(
    *,
    baseline_id: str,
    branch: str,
    metric: str,
    timeframe: str | None,
    previous_status: str,
    new_status: str,
) -> str:
    return "DRF6_" + sha256_text(
        canonical_json(
            {
                "baseline_id": baseline_id,
                "branch": branch,
                "metric": metric,
                "timeframe": timeframe,
                "previous_status": previous_status,
                "new_status": new_status,
            }
        )
    )[:28]


class MetricTracker:
    """Collect baseline → freeze → evaluate rolling windows with consecutive gating."""

    def __init__(
        self,
        *,
        branch: str,
        metric: str,
        timeframe: str | None,
        kind: str,
        active: dict[str, Any],
        baseline_min: int,
        window_size: int,
        min_consecutive: int,
        recovery_consecutive: int,
        numeric_thr: dict[str, float],
        categorical_thr: dict[str, float],
        state: dict[str, Any] | None = None,
    ) -> None:
        self.branch = branch
        self.metric = metric
        self.timeframe = timeframe
        self.kind = kind  # numeric | categorical
        self.active = active
        self.baseline_min = baseline_min
        self.window_size = window_size
        self.min_consecutive = min_consecutive
        self.recovery_consecutive = recovery_consecutive
        self.numeric_thr = numeric_thr
        self.categorical_thr = categorical_thr
        self.baseline_id = baseline_id_for(active, branch=branch, metric=metric, timeframe=timeframe)

        st = state or {}
        self.baseline_status = str(st.get("baseline_status") or "COLLECTING")
        self.baseline_values: list[float] = [float(x) for x in (st.get("baseline_values") or [])]
        self.baseline_counts: dict[str, float] = {
            str(k): float(v) for k, v in (st.get("baseline_counts") or {}).items()
        }
        self.current_window: list[Any] = list(st.get("current_window") or [])
        self.window_index = int(st.get("window_index") or 0)
        self.status = str(st.get("status") or "COLLECTING_BASELINE")
        self.pending_severity: str | None = st.get("pending_severity")
        self.pending_count = int(st.get("pending_count") or 0)
        self.last_distance = st.get("last_distance")
        self.observations = int(st.get("observations") or 0)
        self.suppressed = bool(st.get("suppressed") or False)
        self.not_evaluable = bool(st.get("not_evaluable") or False)
        self.not_evaluable_reason = st.get("not_evaluable_reason")

    def to_state(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "metric": self.metric,
            "timeframe": self.timeframe,
            "kind": self.kind,
            "baseline_id": self.baseline_id,
            "baseline_status": self.baseline_status,
            "baseline_values": self.baseline_values[-self.baseline_min :]
            if self.kind == "numeric" and self.baseline_status != "FROZEN"
            else (self.baseline_values if self.kind == "numeric" else []),
            "baseline_counts": self.baseline_counts if self.kind == "categorical" else {},
            "current_window": self.current_window,
            "window_index": self.window_index,
            "status": self.status,
            "pending_severity": self.pending_severity,
            "pending_count": self.pending_count,
            "last_distance": self.last_distance,
            "observations": self.observations,
            "suppressed": self.suppressed,
            "not_evaluable": self.not_evaluable,
            "not_evaluable_reason": self.not_evaluable_reason,
        }

    def mark_not_evaluable(self, reason: str) -> None:
        self.not_evaluable = True
        self.not_evaluable_reason = reason
        self.status = "NOT_EVALUABLE"

    def set_suppressed(self, suppressed: bool) -> None:
        self.suppressed = suppressed
        if suppressed:
            self.status = "SUPPRESSED_DATA_QUALITY"
            self.pending_severity = None
            self.pending_count = 0

    def add_values(self, values: list[Any]) -> list[dict[str, Any]]:
        """Ingest observations; return completed window records (pre-persist)."""
        if self.not_evaluable or self.suppressed:
            return []
        completed: list[dict[str, Any]] = []
        for value in values:
            if value is None:
                continue
            self.observations += 1
            if self.baseline_status != "FROZEN":
                if self.kind == "numeric":
                    fv = _f(value)
                    if fv is None:
                        continue
                    self.baseline_values.append(fv)
                else:
                    key = str(value)
                    self.baseline_counts[key] = self.baseline_counts.get(key, 0.0) + 1.0
                n = (
                    len(self.baseline_values)
                    if self.kind == "numeric"
                    else int(sum(self.baseline_counts.values()))
                )
                if n >= self.baseline_min:
                    self.baseline_status = "FROZEN"
                    if self.status == "COLLECTING_BASELINE":
                        self.status = "STABLE"
                    # trim numeric baseline to exact freeze sample
                    if self.kind == "numeric" and len(self.baseline_values) > self.baseline_min:
                        self.baseline_values = self.baseline_values[: self.baseline_min]
                continue

            # FROZEN — fill current window
            if self.kind == "numeric":
                fv = _f(value)
                if fv is None:
                    continue
                self.current_window.append(fv)
            else:
                self.current_window.append(str(value))
            if len(self.current_window) >= self.window_size:
                completed.append(self._close_window())
        return completed

    def _close_window(self) -> dict[str, Any]:
        window_vals = self.current_window[: self.window_size]
        self.current_window = self.current_window[self.window_size :]
        self.window_index += 1
        if self.kind == "numeric":
            distance = numeric_quantile_distance(self.baseline_values, window_vals)
            thr = self.numeric_thr
            statistic_type = "NUMERIC_QUANTILE_WASSERSTEIN"
        else:
            distance = categorical_js_distance(self.baseline_counts, count_categories(window_vals))
            thr = self.categorical_thr
            statistic_type = "CATEGORICAL_JS"
        self.last_distance = distance
        window_sev = severity_for_distance(
            distance,
            watch=float(thr["watch"]),
            warning=float(thr["warning"]),
            critical=float(thr["critical"]),
        )
        previous = self.status
        transition = self._apply_consecutive(window_sev)
        return {
            "window_id": window_id_for(
                self.active,
                branch=self.branch,
                metric=self.metric,
                timeframe=self.timeframe,
                window_index=self.window_index,
            ),
            "branch": self.branch,
            "metric": self.metric,
            "timeframe": self.timeframe,
            "window_index": self.window_index,
            "statistic_type": statistic_type,
            "statistic_value": distance,
            "window_severity": window_sev,
            "tracker_status": self.status,
            "previous_status": previous,
            "transition": transition,
            "baseline_id": self.baseline_id,
            "baseline_observations": (
                len(self.baseline_values)
                if self.kind == "numeric"
                else int(sum(self.baseline_counts.values()))
            ),
            "current_window_observations": len(window_vals),
            "threshold": thr,
            "registry_record_id": self.active.get("registry_record_id"),
            "model_id": self.active.get("model_id"),
            "model_version": self.active.get("model_version"),
            "runtime_fingerprint": self.active.get("runtime_fingerprint"),
            "paper_epoch_id": self.active.get("paper_epoch_id"),
            "detected_at": utc_now_iso(),
        }

    def _apply_consecutive(self, window_sev: str) -> dict[str, Any] | None:
        """Raise/lower status only after consecutive windows; single window never flips branch."""
        if window_sev == "STABLE":
            target = "STABLE"
            need = self.recovery_consecutive if self.status in {"WATCH", "WARNING", "CRITICAL"} else 1
        else:
            target = window_sev
            need = self.min_consecutive

        if self.pending_severity == target:
            self.pending_count += 1
        else:
            self.pending_severity = target
            self.pending_count = 1

        if self.pending_count < need:
            return None
        if self.status == target:
            self.pending_count = 0
            self.pending_severity = None
            return None
        previous = self.status
        self.status = target
        self.pending_count = 0
        self.pending_severity = None
        return {"previous_status": previous, "new_status": target}


def _list_stream_parquets(stream_root: Path, *, max_files: int = 8) -> list[Path]:
    """Recent parquet chunks only — never full-tree scan of raw_market_events_v2."""
    if not stream_root.exists():
        return []
    dates = sorted([p for p in stream_root.glob("date=*") if p.is_dir()])[-2:]
    files: list[Path] = []
    for date_dir in dates:
        hours = sorted([p for p in date_dir.glob("hour=*") if p.is_dir()])[-3:]
        for hour_dir in hours:
            chunk = sorted(
                p
                for p in hour_dir.iterdir()
                if p.is_file() and p.suffix == ".parquet" and not p.name.endswith(".tmp")
            )
            files.extend(chunk)
    return files[-max_files:]


def _read_parquet_after(
    path: Path,
    *,
    after_mono: int | None,
    max_rows: int,
) -> tuple[list[dict[str, Any]], int | None]:
    try:
        table = pq.read_table(path)
    except Exception:
        return [], after_mono
    names = [n for n in table.column_names if n not in {"date", "hour"}]
    table = table.select(names) if names else table
    rows: list[dict[str, Any]] = []
    last_mono = after_mono
    data = table.to_pydict()
    n = len(next(iter(data.values()), []))
    for i in range(n):
        row = {k: data[k][i] for k in data}
        mono = row.get("local_receive_monotonic_ns")
        try:
            mono_i = int(mono) if mono is not None else None
        except (TypeError, ValueError):
            mono_i = None
        if after_mono is not None and mono_i is not None and mono_i <= after_mono:
            continue
        rows.append(row)
        if mono_i is not None:
            last_mono = mono_i if last_mono is None else max(last_mono, mono_i)
        if len(rows) >= max_rows:
            break
    return rows, last_mono


def collect_input_observations(
    *,
    raw_root: Path,
    checkpoint: dict[str, Any],
    max_rows_per_stream: int = 1500,
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    """Derive input metrics from newly seen market events only."""
    metrics: dict[str, list[float]] = defaultdict(list)
    state = dict(checkpoint.get("input_streams") or {})

    # aggTrade
    agg_state = dict(state.get("agg_trade") or {})
    after = agg_state.get("last_mono")
    last_price = _f(agg_state.get("last_price"))
    last_ts = parse_ts(agg_state.get("last_ts"))
    minute_bucket: dict[str, int] = dict(agg_state.get("minute_counts") or {})
    files = _list_stream_parquets(raw_root / "agg_trade")
    last_file = agg_state.get("last_file")
    # start from files at/after last_file
    if last_file:
        files = [f for f in files if str(f) >= str(last_file)]
    remaining = max_rows_per_stream
    for path in files:
        if remaining <= 0:
            break
        rows, after = _read_parquet_after(
            path, after_mono=agg_state.get("last_mono"), max_rows=remaining
        )
        for row in rows:
            price = _f(row.get("price"))
            qty = _f(row.get("quantity"))
            quote = _f(row.get("quote_quantity"))
            ts = parse_ts(row.get("exchange_trade_timestamp") or row.get("local_receive_timestamp"))
            if price is not None and last_price is not None and last_price > 0:
                ret = (price - last_price) / last_price * 10000.0
                metrics["trade_return_bps"].append(ret)
                metrics["absolute_trade_return_bps"].append(abs(ret))
            if qty is not None:
                metrics["quantity"].append(qty)
            if quote is not None:
                metrics["quote_notional"].append(quote)
            elif price is not None and qty is not None:
                metrics["quote_notional"].append(price * qty)
            if ts is not None and last_ts is not None:
                gap = (ts - last_ts).total_seconds() * 1000.0
                if gap >= 0:
                    metrics["trade_interarrival_ms"].append(gap)
            if ts is not None:
                bucket = ts.strftime("%Y-%m-%dT%H:%M")
                minute_bucket[bucket] = minute_bucket.get(bucket, 0) + 1
            if price is not None:
                last_price = price
            if ts is not None:
                last_ts = ts
        remaining -= len(rows)
        last_file = str(path)
        agg_state["last_file"] = last_file
        agg_state["last_mono"] = after
        agg_state["last_price"] = last_price
        agg_state["last_ts"] = last_ts.isoformat().replace("+00:00", "Z") if last_ts else None
    # flush completed minute rates except current open minute
    if minute_bucket:
        keys = sorted(minute_bucket.keys())
        for k in keys[:-1]:
            metrics["trades_per_minute"].append(float(minute_bucket[k]))
            del minute_bucket[k]
    agg_state["minute_counts"] = minute_bucket
    state["agg_trade"] = agg_state

    # bookTicker
    book_state = dict(state.get("book_ticker") or {})
    after_b = book_state.get("last_mono")
    last_mid = _f(book_state.get("last_mid"))
    last_b_ts = parse_ts(book_state.get("last_ts"))
    b_files = _list_stream_parquets(raw_root / "book_ticker")
    last_b_file = book_state.get("last_file")
    if last_b_file:
        b_files = [f for f in b_files if str(f) >= str(last_b_file)]
    remaining = max_rows_per_stream
    for path in b_files:
        if remaining <= 0:
            break
        rows, after_b = _read_parquet_after(path, after_mono=book_state.get("last_mono"), max_rows=remaining)
        for row in rows:
            bid = _f(row.get("best_bid_price"))
            ask = _f(row.get("best_ask_price"))
            mid = _f(row.get("mid_price"))
            if mid is None and bid is not None and ask is not None:
                mid = 0.5 * (bid + ask)
            spread = _f(row.get("spread"))
            if spread is None and bid is not None and ask is not None and mid and mid > 0:
                spread = (ask - bid) / mid * 10000.0
            elif spread is not None and mid and mid > 0 and spread < 1:
                # raw spread in price → bps
                spread = spread / mid * 10000.0
            if spread is not None:
                metrics["spread_bps"].append(float(spread))
            if mid is not None and last_mid is not None and last_mid > 0:
                metrics["mid_return_bps"].append((mid - last_mid) / last_mid * 10000.0)
            ts = parse_ts(row.get("local_receive_timestamp") or row.get("exchange_event_timestamp"))
            if ts is not None and last_b_ts is not None:
                gap = (ts - last_b_ts).total_seconds() * 1000.0
                if gap >= 0:
                    metrics["book_update_interarrival_ms"].append(gap)
            if mid is not None:
                last_mid = mid
            if ts is not None:
                last_b_ts = ts
        remaining -= len(rows)
        book_state["last_file"] = str(path)
        book_state["last_mono"] = after_b
        book_state["last_mid"] = last_mid
        book_state["last_ts"] = last_b_ts.isoformat().replace("+00:00", "Z") if last_b_ts else None
    state["book_ticker"] = book_state
    return dict(metrics), state


def collect_feature_observations(
    *,
    cognition: dict[str, Any] | None,
    seen_keys: set[str],
) -> tuple[dict[tuple[str, str], list[Any]], set[str], set[str]]:
    """Unique provisional observations by timeframe + causal_cutoff_monotonic_ns."""
    observations: dict[tuple[str, str], list[Any]] = defaultdict(list)
    missing_fields: set[str] = set(FEATURE_NUMERIC) | set(FEATURE_CATEGORICAL)
    present_fields: set[str] = set()
    if not cognition:
        return {}, seen_keys, missing_fields

    provisional = cognition.get("last_provisional_eval") or {}
    partial = cognition.get("partial_bars") or {}
    for tf in TIMEFRAMES:
        bar = partial.get(tf) if isinstance(partial, dict) else None
        prov = provisional.get(tf) if isinstance(provisional, dict) else None
        if not isinstance(bar, dict):
            continue
        mono = bar.get("causal_cutoff_monotonic_ns")
        if mono is None:
            continue
        key = f"{tf}|{mono}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        payload: dict[str, Any] = {}
        if isinstance(prov, dict):
            payload.update(prov)
        # optional nested scores if ever present on bar/health
        for src in (prov if isinstance(prov, dict) else {}), bar, cognition:
            if not isinstance(src, dict):
                continue
            for field in FEATURE_NUMERIC + FEATURE_CATEGORICAL:
                if field in src and src.get(field) is not None:
                    payload[field] = src[field]
        for field in FEATURE_NUMERIC + FEATURE_CATEGORICAL:
            if field in payload and payload.get(field) is not None:
                present_fields.add(field)
                observations[(tf, field)].append(payload[field])
    missing_fields -= present_fields
    # If we saw observations but some configured fields never appear, keep them missing
    if not present_fields:
        return observations, seen_keys, set(FEATURE_NUMERIC) | set(FEATURE_CATEGORICAL)
    return observations, seen_keys, missing_fields - present_fields


def collect_context_observations(
    *,
    predictions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    active: dict[str, Any],
) -> dict[tuple[str | None, str], list[Any]]:
    out: dict[tuple[str | None, str], list[Any]] = defaultdict(list)
    preds = [
        p
        for p in predictions
        if str(p.get("registry_record_id") or "") == str(active.get("registry_record_id") or "")
        and str(p.get("paper_epoch_id") or "") == str(active.get("paper_epoch_id") or "")
    ]
    by_tf: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in preds:
        tf = str(p.get("timeframe") or "")
        by_tf[tf].append(p)
        direction = str(p.get("direction") or "").upper()
        if direction in {"LONG", "SHORT"}:
            out[(tf, "direction_share")].append(direction)
        reason = str(p.get("close_reason") or p.get("event_type") or "").upper()
        if reason:
            out[(tf, "context_event_type_share")].append(reason)
        start = parse_ts(p.get("start_timestamp"))
        end = parse_ts(p.get("closed_at"))
        if start and end:
            out[(tf, "prediction_duration_seconds")].append((end - start).total_seconds())
        if reason == "CONTEXT_FLIP":
            out[(tf, "flip_indicator")].append(1.0)
        else:
            out[(tf, "flip_indicator")].append(0.0)
    for tf, rows in by_tf.items():
        out[(tf, "context_event_rate")].append(float(len(rows)))

    for o in outcomes:
        if o.get("registry_record_id") and str(o.get("registry_record_id")) != str(active.get("registry_record_id")):
            continue
        if o.get("paper_epoch_id") and str(o.get("paper_epoch_id")) != str(active.get("paper_epoch_id")):
            continue
        if str(o.get("outcome_status") or "") != "EVALUATED":
            continue
        # join timeframe via prediction_id
        pid = str(o.get("prediction_id") or "")
        tf = next((str(p.get("timeframe")) for p in preds if str(p.get("prediction_id")) == pid), None)
        horizon = str(o.get("horizon_type") or "")
        signed = _f(o.get("signed_return_bps"))
        mfe = _f(o.get("mfe_bps"))
        mae = _f(o.get("mae_bps"))
        if signed is not None:
            out[(tf, f"signed_return_bps_{horizon}")].append(signed)
        if mfe is not None:
            out[(tf, "mfe_bps")].append(mfe)
        if mae is not None:
            out[(tf, "mae_bps")].append(abs(mae))
    return out


def collect_performance_observations(
    *,
    evaluations: list[dict[str, Any]],
    equity_rows: list[dict[str, Any]],
    active: dict[str, Any],
) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = defaultdict(list)
    evals = [
        e
        for e in evaluations
        if str(e.get("registry_record_id") or "") == str(active.get("registry_record_id") or "")
        and str(e.get("paper_epoch_id") or "") == str(active.get("paper_epoch_id") or "")
    ]
    for e in evals:
        net = _f(e.get("net_pnl_usd"))
        r = _f(e.get("realized_r_multiple"))
        gross = _f(e.get("gross_pnl_usd"))
        fees = _f(e.get("total_fee_usd")) or 0.0
        slip = _f(e.get("total_slippage_usd")) or 0.0
        hold = _f(e.get("holding_seconds"))
        if net is not None:
            out["net_pnl_usd"].append(net)
            out["win_loss_share"].append("WIN" if net > 0 else "LOSS")
        if r is not None:
            out["realized_r_multiple"].append(r)
        if gross is not None and abs(gross) > 0:
            out["cost_to_gross_ratio"].append((fees + slip) / abs(gross))
        if hold is not None:
            out["holding_seconds"].append(hold)
        reason = e.get("exit_reason")
        if reason:
            out["exit_reason_share"].append(str(reason))

    equities = []
    for row in equity_rows:
        if str(row.get("paper_epoch_id") or "") != str(active.get("paper_epoch_id") or ""):
            continue
        eq = _f(row.get("equity_usd") or row.get("equity") or row.get("balance_usd"))
        if eq is not None:
            equities.append(eq)
    peak = None
    for eq in equities:
        if peak is None or eq > peak:
            peak = eq
        if peak is not None:
            out["drawdown_increments"].append(max(0.0, peak - eq))
    return out


def _ensure_tracker(
    trackers: dict[str, MetricTracker],
    *,
    key: str,
    branch: str,
    metric: str,
    timeframe: str | None,
    kind: str,
    active: dict[str, Any],
    config: dict[str, Any],
    state_blob: dict[str, Any],
) -> MetricTracker:
    if key in trackers:
        return trackers[key]
    branch_cfg = (config.get("branches") or {}).get(branch) or {}
    tracker = MetricTracker(
        branch=branch,
        metric=metric,
        timeframe=timeframe,
        kind=kind,
        active=active,
        baseline_min=int(branch_cfg.get("baseline_min_observations", 30)),
        window_size=int(branch_cfg.get("current_window_observations", 10)),
        min_consecutive=int(config.get("minimum_consecutive_windows", 3)),
        recovery_consecutive=int(config.get("recovery_consecutive_windows", 3)),
        numeric_thr=dict(config.get("numeric_drift") or {}),
        categorical_thr=dict(config.get("categorical_drift") or {}),
        state=state_blob.get(key),
    )
    trackers[key] = tracker
    return tracker


def _persist_unique(path: Path, row: dict[str, Any], *, id_field: str, existing: set[str]) -> bool:
    rid = str(row.get(id_field) or "")
    if not rid or rid in existing:
        return False
    append_jsonl(path, row)
    existing.add(rid)
    return True


def build_summary(
    *,
    active: dict[str, Any],
    trackers: dict[str, MetricTracker],
    last_drift_event_at: str | None,
    last_resolved_at: str | None,
) -> dict[str, Any]:
    by_branch: dict[str, list[str]] = defaultdict(list)
    baseline_status_by_branch: dict[str, str] = {}
    observations_by_branch: dict[str, int] = defaultdict(int)
    watch_metrics: list[str] = []
    warning_metrics: list[str] = []
    critical_metrics: list[str] = []
    not_evaluable_metrics: list[str] = []
    suppressed_metrics: list[str] = []
    counts_by_branch: dict[str, int] = defaultdict(int)
    counts_by_metric: dict[str, int] = defaultdict(int)
    counts_by_timeframe: dict[str, int] = defaultdict(int)
    frozen = 0

    for tr in trackers.values():
        by_branch[tr.branch].append(tr.status)
        observations_by_branch[tr.branch] += tr.observations
        counts_by_branch[tr.branch] += 1
        counts_by_metric[tr.metric] += 1
        if tr.timeframe:
            counts_by_timeframe[tr.timeframe] += 1
        if tr.baseline_status == "FROZEN":
            frozen += 1
        label = f"{tr.branch}:{tr.timeframe or '-'}:{tr.metric}"
        if tr.status == "WATCH":
            watch_metrics.append(label)
        elif tr.status == "WARNING":
            warning_metrics.append(label)
        elif tr.status == "CRITICAL":
            critical_metrics.append(label)
        elif tr.status == "NOT_EVALUABLE":
            not_evaluable_metrics.append(label)
        elif tr.status == "SUPPRESSED_DATA_QUALITY":
            suppressed_metrics.append(label)

    for branch, statuses in by_branch.items():
        # branch status ignores single-window (already gated in tracker.status)
        if all(s == "COLLECTING_BASELINE" for s in statuses):
            baseline_status_by_branch[branch] = "COLLECTING"
        elif any(s == "SUPPRESSED_DATA_QUALITY" for s in statuses) and all(
            s in {"SUPPRESSED_DATA_QUALITY", "COLLECTING_BASELINE", "NOT_EVALUABLE"} for s in statuses
        ):
            baseline_status_by_branch[branch] = "SUPPRESSED_DATA_QUALITY"
        elif any(s == "COLLECTING_BASELINE" for s in statuses):
            baseline_status_by_branch[branch] = "COLLECTING"
        else:
            baseline_status_by_branch[branch] = "FROZEN" if all(
                t.baseline_status == "FROZEN"
                for t in trackers.values()
                if t.branch == branch and not t.not_evaluable and not t.suppressed
            ) or not any(t.branch == branch and not t.not_evaluable and not t.suppressed for t in trackers.values()) else "PARTIAL"

    branch_status = {
        "input": max_status(by_branch.get("input") or ["COLLECTING_BASELINE"]),
        "feature": max_status(by_branch.get("feature") or ["COLLECTING_BASELINE"]),
        "context": max_status(by_branch.get("context") or ["COLLECTING_BASELINE"]),
        "performance": max_status(by_branch.get("performance") or ["COLLECTING_BASELINE"]),
    }
    # Empty branches with no trackers stay COLLECTING_BASELINE / NO eligible
    for b in ("input", "feature", "context", "performance"):
        if b not in by_branch:
            branch_status[b] = "COLLECTING_BASELINE"
            baseline_status_by_branch[b] = "COLLECTING"

    all_statuses = list(branch_status.values())
    if critical_metrics:
        overall = "CURRENT_CRITICAL"
    elif warning_metrics:
        overall = "CURRENT_WARNING"
    elif watch_metrics:
        overall = "CURRENT_WATCH"
    elif any(s == "COLLECTING_BASELINE" for s in all_statuses) or any(
        baseline_status_by_branch.get(b) == "COLLECTING" for b in baseline_status_by_branch
    ):
        overall = "COLLECTING_BASELINE"
    else:
        overall = "CURRENT_STABLE"

    return {
        "status": overall,
        "runtime_impact": "NON_BLOCKING",
        "monitoring_mode": "LIVE_CURRENT",
        "registry_record_id": active.get("registry_record_id"),
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "runtime_fingerprint": active.get("runtime_fingerprint"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "input_drift_status": branch_status["input"],
        "feature_drift_status": branch_status["feature"],
        "context_drift_status": branch_status["context"],
        "performance_drift_status": branch_status["performance"],
        "baseline_status_by_branch": baseline_status_by_branch,
        "observations_by_branch": dict(observations_by_branch),
        "frozen_baselines": frozen,
        "watch_metrics": watch_metrics,
        "warning_metrics": warning_metrics,
        "critical_metrics": critical_metrics,
        "not_evaluable_metrics": not_evaluable_metrics,
        "suppressed_metrics": suppressed_metrics,
        "counts_by_branch": dict(counts_by_branch),
        "counts_by_metric": dict(counts_by_metric),
        "counts_by_timeframe": dict(counts_by_timeframe),
        "last_drift_event_at": last_drift_event_at,
        "last_resolved_at": last_resolved_at,
        "updated_at": utc_now_iso(),
    }


def run_once(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    p = paths(root)
    config = load_config(root)
    active = read_active_runtime(repo_root=root)
    if not active:
        summary = {
            "status": "COLLECTING_BASELINE",
            "runtime_impact": "NON_BLOCKING",
            "monitoring_mode": "LIVE_CURRENT",
            "updated_at": utc_now_iso(),
        }
        atomic_write_json(p["summary"], summary)
        return summary

    checkpoint = load_json(p["checkpoint"]) or {}
    # Reset trackers if fingerprint/model_version changed
    identity = {
        "registry_record_id": active.get("registry_record_id"),
        "model_version": active.get("model_version"),
        "runtime_fingerprint": active.get("runtime_fingerprint"),
    }
    if checkpoint.get("active_identity") != identity:
        checkpoint = {
            "active_identity": identity,
            "paper_epoch_id": active.get("paper_epoch_id"),
            "trackers": {},
            "input_streams": {},
            "feature_seen_keys": [],
            "created_at": utc_now_iso(),
        }

    ext_summary = load_json(p["external_summary"]) or {}
    ext_status = str(ext_summary.get("status") or "")
    suppress_input_feature = ext_status in {"CURRENT_DEGRADED", "CURRENT_CRITICAL"}

    trackers: dict[str, MetricTracker] = {}
    state_blob = dict(checkpoint.get("trackers") or {})
    existing_windows = {str(r.get("window_id")) for r in read_jsonl(p["windows"])}
    existing_events = {str(r.get("drift_event_id")) for r in read_jsonl(p["events"])}
    existing_baselines = {str(r.get("baseline_id")) for r in read_jsonl(p["baselines"])}
    last_event_at = None
    last_resolved = None
    for r in read_jsonl(p["events"]):
        if r.get("detected_at"):
            last_event_at = r.get("detected_at")
        if r.get("resolved_at"):
            last_resolved = r.get("resolved_at")

    def handle_windows(windows: list[dict[str, Any]], tracker: MetricTracker) -> None:
        nonlocal last_event_at, last_resolved
        for w in windows:
            _persist_unique(p["windows"], w, id_field="window_id", existing=existing_windows)
            tr = w.get("transition")
            if not tr:
                continue
            prev_s, new_s = tr["previous_status"], tr["new_status"]
            event = {
                "drift_event_id": drift_event_id_for(
                    baseline_id=tracker.baseline_id,
                    branch=tracker.branch,
                    metric=tracker.metric,
                    timeframe=tracker.timeframe,
                    previous_status=prev_s,
                    new_status=new_s,
                ),
                "branch": tracker.branch,
                "metric": tracker.metric,
                "timeframe": tracker.timeframe,
                "previous_status": prev_s,
                "new_status": new_s,
                "severity": new_s if new_s in {"WATCH", "WARNING", "CRITICAL"} else "WATCH",
                "statistic_type": w.get("statistic_type"),
                "statistic_value": w.get("statistic_value"),
                "threshold": w.get("threshold"),
                "baseline_id": tracker.baseline_id,
                "baseline_observations": w.get("baseline_observations"),
                "current_window_observations": w.get("current_window_observations"),
                "registry_record_id": active.get("registry_record_id"),
                "model_id": active.get("model_id"),
                "model_version": active.get("model_version"),
                "runtime_fingerprint": active.get("runtime_fingerprint"),
                "paper_epoch_id": active.get("paper_epoch_id"),
                "detected_at": utc_now_iso(),
                "resolved_at": utc_now_iso() if new_s == "STABLE" and prev_s != "STABLE" else None,
                "evidence": {
                    "window_id": w.get("window_id"),
                    "window_index": w.get("window_index"),
                    "external_data_status": ext_status,
                },
            }
            if _persist_unique(p["events"], event, id_field="drift_event_id", existing=existing_events):
                last_event_at = event["detected_at"]
                if event.get("resolved_at"):
                    last_resolved = event["resolved_at"]

    # --- INPUT ---
    input_metrics, input_stream_state = collect_input_observations(
        raw_root=p["raw_root"], checkpoint=checkpoint
    )
    checkpoint["input_streams"] = input_stream_state
    for metric, values in input_metrics.items():
        key = f"input|{metric}"
        tr = _ensure_tracker(
            trackers,
            key=key,
            branch="input",
            metric=metric,
            timeframe=None,
            kind="numeric",
            active=active,
            config=config,
            state_blob=state_blob,
        )
        if suppress_input_feature:
            tr.set_suppressed(True)
            tr.observations += len(values)
            continue
        tr.set_suppressed(False)
        handle_windows(tr.add_values(values), tr)

    # --- FEATURE ---
    cognition = load_json(p["cognition_health"])
    seen = set(checkpoint.get("feature_seen_keys") or [])
    feat_obs, seen, missing = collect_feature_observations(cognition=cognition, seen_keys=seen)
    checkpoint["feature_seen_keys"] = sorted(seen)[-5000:]
    for (tf, field), values in feat_obs.items():
        kind = "numeric" if field in FEATURE_NUMERIC else "categorical"
        key = f"feature|{tf}|{field}"
        tr = _ensure_tracker(
            trackers,
            key=key,
            branch="feature",
            metric=field,
            timeframe=tf,
            kind=kind,
            active=active,
            config=config,
            state_blob=state_blob,
        )
        if suppress_input_feature:
            tr.set_suppressed(True)
            tr.observations += len(values)
            continue
        tr.set_suppressed(False)
        handle_windows(tr.add_values(values), tr)
    # mark configured missing fields once (no LIVE1A patch)
    for field in sorted(missing):
        for tf in TIMEFRAMES:
            key = f"feature|{tf}|{field}"
            if key in trackers:
                continue
            # only mark if field never observed globally
            if any(k.endswith(f"|{field}") and trackers[k].observations > 0 for k in trackers):
                continue
            tr = _ensure_tracker(
                trackers,
                key=key,
                branch="feature",
                metric=field,
                timeframe=tf,
                kind="numeric" if field in FEATURE_NUMERIC else "categorical",
                active=active,
                config=config,
                state_blob=state_blob,
            )
            if suppress_input_feature:
                tr.set_suppressed(True)
            else:
                tr.mark_not_evaluable("NOT_EVALUABLE_SOURCE_FIELD_MISSING")

    # --- CONTEXT ---
    ctx_obs = collect_context_observations(
        predictions=read_jsonl(p["bv_predictions"]),
        outcomes=read_jsonl(p["bv_outcomes"]),
        active=active,
    )
    for (tf, metric), values in ctx_obs.items():
        kind = "categorical" if metric in {"direction_share", "context_event_type_share"} else "numeric"
        key = f"context|{tf}|{metric}"
        tr = _ensure_tracker(
            trackers,
            key=key,
            branch="context",
            metric=metric,
            timeframe=tf,
            kind=kind,
            active=active,
            config=config,
            state_blob=state_blob,
        )
        handle_windows(tr.add_values(values), tr)

    # --- PERFORMANCE ---
    paper_epoch = str(active.get("paper_epoch_id") or "")
    equity_path = p["books_root"] / paper_epoch / "books" / "equity_snapshots.jsonl"
    perf_obs = collect_performance_observations(
        evaluations=read_jsonl(p["econ_evals"]),
        equity_rows=read_jsonl(equity_path),
        active=active,
    )
    for metric, values in perf_obs.items():
        kind = "categorical" if metric in {"win_loss_share", "exit_reason_share"} else "numeric"
        key = f"performance|{metric}"
        tr = _ensure_tracker(
            trackers,
            key=key,
            branch="performance",
            metric=metric,
            timeframe=None,
            kind=kind,
            active=active,
            config=config,
            state_blob=state_blob,
        )
        handle_windows(tr.add_values(values), tr)

    # Persist newly frozen baselines (idempotent)
    for tr in trackers.values():
        if tr.baseline_status == "FROZEN" and tr.baseline_id not in existing_baselines:
            row = {
                "baseline_id": tr.baseline_id,
                "branch": tr.branch,
                "metric": tr.metric,
                "timeframe": tr.timeframe,
                "kind": tr.kind,
                "baseline_status": "FROZEN",
                "observations": (
                    len(tr.baseline_values)
                    if tr.kind == "numeric"
                    else int(sum(tr.baseline_counts.values()))
                ),
                "registry_record_id": active.get("registry_record_id"),
                "model_id": active.get("model_id"),
                "model_version": active.get("model_version"),
                "runtime_fingerprint": active.get("runtime_fingerprint"),
                "paper_epoch_id": active.get("paper_epoch_id"),
                "frozen_at": utc_now_iso(),
            }
            if _persist_unique(p["baselines"], row, id_field="baseline_id", existing=existing_baselines):
                pass

    # Restore trackers that exist in state but got no new data this cycle
    for key, st in state_blob.items():
        if key not in trackers:
            branch = str(st.get("branch") or "")
            metric = str(st.get("metric") or "")
            timeframe = st.get("timeframe")
            kind = str(st.get("kind") or "numeric")
            tr = _ensure_tracker(
                trackers,
                key=key,
                branch=branch,
                metric=metric,
                timeframe=timeframe,
                kind=kind,
                active=active,
                config=config,
                state_blob=state_blob,
            )
            if branch in {"input", "feature"} and suppress_input_feature:
                tr.set_suppressed(True)

    checkpoint["trackers"] = {k: t.to_state() for k, t in trackers.items()}
    checkpoint["paper_epoch_id"] = active.get("paper_epoch_id")
    checkpoint["updated_at"] = utc_now_iso()
    atomic_write_json(p["checkpoint"], checkpoint)

    summary = build_summary(
        active=active,
        trackers=trackers,
        last_drift_event_at=last_event_at,
        last_resolved_at=last_resolved,
    )
    if suppress_input_feature:
        summary["external_data_status"] = ext_status
        summary["suppressed_reason"] = "DATA_QUALITY_FAILURE_NOT_DRIFT"
    atomic_write_json(p["summary"], summary)
    atomic_write_json(
        p["current_metrics"],
        {
            "metrics": {
                k: {
                    "status": t.status,
                    "baseline_status": t.baseline_status,
                    "observations": t.observations,
                    "last_distance": t.last_distance,
                    "window_index": t.window_index,
                }
                for k, t in trackers.items()
            },
            "updated_at": utc_now_iso(),
        },
    )
    atomic_write_json(
        p["health"],
        {
            "status": summary["status"],
            "alive": True,
            "runtime_impact": "NON_BLOCKING",
            "monitoring_mode": "LIVE_CURRENT",
            "pid": os.getpid(),
            "paper_epoch_id": active.get("paper_epoch_id"),
            "observations_by_branch": summary.get("observations_by_branch"),
            "frozen_baselines": summary.get("frozen_baselines"),
            "paper_only": active.get("paper_only", True),
            "real_execution": active.get("real_execution", False),
            "updated_at": utc_now_iso(),
        },
    )
    return summary
