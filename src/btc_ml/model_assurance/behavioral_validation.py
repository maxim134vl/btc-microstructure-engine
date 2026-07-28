"""Observational behavioral validation for CONTEXT_* events (MODEL-1).

NON-BLOCKING / OBSERVATIONAL ONLY.
Does not affect cognition, paper trading, or System Health.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import pyarrow.parquet as pq

from btc_ml.model_assurance.registry import read_active_runtime

TF_SECONDS: dict[str, int] = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}
HORIZON_MULTS: tuple[tuple[str, int], ...] = (("1x", 1), ("2x", 2), ("3x", 3))
DIRECTIONAL_CONTEXTS = {"LONG_CONTEXT": "LONG", "SHORT_CONTEXT": "SHORT"}
SOURCE_FRESH_SECONDS = 120.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _iso(stamp: datetime | None) -> str | None:
    if stamp is None:
        return None
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "behavioral_validation"
    return {
        "root": base,
        "predictions": base / "events" / "context_predictions.jsonl",
        "outcomes": base / "outcomes" / "context_outcomes.jsonl",
        "summary": base / "snapshots" / "latest_summary.json",
        "health": base / "runtime" / "health.json",
        "checkpoint": base / "runtime" / "checkpoint.json",
        "active_model": root / "data" / "model_assurance" / "registry" / "active" / "active_model.json",
        "context_events": root / "data" / "cognition" / "intrabar_context_events" / "events.jsonl",
        "raw_root": root / "data" / "raw_market_events_v2",
    }


def prediction_id_for(*, registry_record_id: str, context_event_id: str, direction: str) -> str:
    return "PRED_" + _sha256_text(
        _canonical_json(
            {
                "registry_record_id": registry_record_id,
                "context_event_id": context_event_id,
                "direction": direction,
            }
        )
    )[:32]


def outcome_id_for(*, prediction_id: str, horizon_type: str) -> str:
    return "OUT_" + _sha256_text(
        _canonical_json({"prediction_id": prediction_id, "horizon_type": horizon_type})
    )[:32]


def direction_from_context(context: str | None) -> str | None:
    return DIRECTIONAL_CONTEXTS.get(str(context or "").strip().upper())


def horizon_seconds(timeframe: str, mult: int) -> int:
    base = TF_SECONDS.get(str(timeframe).upper())
    if base is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return int(base) * int(mult)


def compute_signed_metrics(
    *,
    direction: str,
    start_price: float,
    end_price: float,
    prices: Iterable[float],
) -> dict[str, float]:
    """Objective LONG/SHORT metrics; SHORT is the inverse of LONG."""
    side = str(direction).upper()
    if start_price <= 0 or end_price <= 0:
        raise ValueError("prices must be positive")
    path = [float(p) for p in prices if p is not None and float(p) > 0]
    if not path:
        path = [float(end_price)]
    if side == "LONG":
        signed = (end_price / start_price - 1.0) * 10_000.0
        rets = [(p / start_price - 1.0) * 10_000.0 for p in path]
    elif side == "SHORT":
        signed = (start_price / end_price - 1.0) * 10_000.0
        rets = [(start_price / p - 1.0) * 10_000.0 for p in path]
    else:
        raise ValueError(f"unsupported direction: {direction}")
    return {
        "signed_return_bps": float(signed),
        "mfe_bps": float(max(rets)),
        "mae_bps": float(min(rets)),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _append_jsonl_unique(path: Path, row: dict[str, Any], *, id_key: str, existing: set[str]) -> bool:
    rid = str(row.get(id_key) or "")
    if not rid or rid in existing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_canonical_json(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    existing.add(rid)
    return True


def _hour_partitions(start: datetime, end: datetime) -> list[tuple[str, str]]:
    """Inclusive UTC hour dirs covering [start, end]."""
    if end < start:
        start, end = end, start
    cur = start.replace(minute=0, second=0, microsecond=0)
    last = end.replace(minute=0, second=0, microsecond=0)
    out: list[tuple[str, str]] = []
    while cur <= last:
        out.append((cur.strftime("%Y-%m-%d"), f"{cur.hour:02d}"))
        cur += timedelta(hours=1)
    return out


def iter_agg_trades(
    raw_root: Path,
    *,
    start_ts: datetime,
    cutoff_ts: datetime,
) -> Iterator[dict[str, Any]]:
    """Yield BTCUSDT aggTrades with start_ts < trade_ts <= cutoff_ts."""
    base = raw_root / "agg_trade"
    if not base.exists():
        return
    for date_part, hour_part in _hour_partitions(start_ts, cutoff_ts):
        hour_int = int(hour_part)
        candidates = [
            base / f"date={date_part}" / f"hour={hour_int}",
            base / f"date={date_part}" / f"hour={hour_part}",
        ]
        part_dirs = [d for d in candidates if d.exists()]
        seen: set[Path] = set()
        for part_dir in part_dirs:
            if part_dir in seen:
                continue
            seen.add(part_dir)
            files = sorted(
                p
                for p in part_dir.iterdir()
                if p.is_file() and p.suffix == ".parquet" and not p.name.endswith(".tmp")
            )
            for path in files:
                try:
                    table = pq.read_table(path)
                except Exception:
                    continue
                names = [n for n in table.column_names if n not in {"date", "hour"}]
                table = table.select(names) if names else table
                for batch in table.to_batches(max_chunksize=4096):
                    rows = batch.to_pydict()
                    n = len(next(iter(rows.values()), []))
                    for i in range(n):
                        if str(rows.get("symbol", [None] * n)[i] or "BTCUSDT").upper() != "BTCUSDT":
                            continue
                        trade_ts = _parse_ts(
                            rows.get("exchange_trade_timestamp", [None] * n)[i]
                            or rows.get("exchange_event_timestamp", [None] * n)[i]
                        )
                        if trade_ts is None:
                            continue
                        if not (start_ts < trade_ts <= cutoff_ts):
                            continue
                        price_raw = rows.get("price", [None] * n)[i]
                        try:
                            price = float(price_raw)
                        except (TypeError, ValueError):
                            continue
                        if price <= 0 or math.isnan(price):
                            continue
                        yield {
                            "trade_timestamp": trade_ts,
                            "trade_id": rows.get("aggregate_trade_id", [None] * n)[i],
                            "price": price,
                        }


def evaluate_horizon_window(
    *,
    direction: str,
    start_price: float,
    start_ts: datetime,
    cutoff_ts: datetime,
    raw_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utc_now()
    if now < cutoff_ts:
        return {"outcome_status": "PENDING"}
    trades = list(iter_agg_trades(raw_root, start_ts=start_ts, cutoff_ts=cutoff_ts))
    if not trades:
        return {
            "outcome_status": "INSUFFICIENT_MARKET_DATA",
            "observation_count": 0,
            "cutoff_timestamp": _iso(cutoff_ts),
            "evaluated_at": _utc_now_iso(),
            "end_trade_timestamp": None,
            "end_trade_id": None,
            "end_price": None,
            "price_lag_ms": None,
            "signed_return_bps": None,
            "mfe_bps": None,
            "mae_bps": None,
        }
    end = trades[-1]
    metrics = compute_signed_metrics(
        direction=direction,
        start_price=float(start_price),
        end_price=float(end["price"]),
        prices=[t["price"] for t in trades],
    )
    lag_ms = max(0.0, (cutoff_ts - end["trade_timestamp"]).total_seconds() * 1000.0)
    return {
        "outcome_status": "EVALUATED",
        "observation_count": len(trades),
        "cutoff_timestamp": _iso(cutoff_ts),
        "evaluated_at": _utc_now_iso(),
        "end_trade_timestamp": _iso(end["trade_timestamp"]),
        "end_trade_id": end.get("trade_id"),
        "end_price": float(end["price"]),
        "price_lag_ms": lag_ms,
        **metrics,
    }


def latest_agg_trade_ts(raw_root: Path) -> datetime | None:
    base = raw_root / "agg_trade"
    if not base.exists():
        return None
    dates = sorted([p for p in base.glob("date=*") if p.is_dir()], reverse=True)
    for date_dir in dates[:2]:
        hours = sorted([p for p in date_dir.glob("hour=*") if p.is_dir()], reverse=True)
        for hour_dir in hours[:2]:
            files = sorted(
                [p for p in hour_dir.glob("*.parquet") if p.is_file()],
                reverse=True,
            )
            for path in files[:3]:
                try:
                    table = pq.read_table(path, columns=["exchange_trade_timestamp"])
                except Exception:
                    continue
                col = table.column(0).to_pylist()
                for value in reversed(col):
                    stamp = _parse_ts(value)
                    if stamp is not None:
                        return stamp
    return None


@dataclass
class ValidationState:
    predictions: dict[str, dict[str, Any]]
    outcomes: dict[str, dict[str, Any]]
    open_by_tf: dict[str, str]
    processed_event_ids: set[str]


def load_state(p: dict[str, Path]) -> ValidationState:
    preds = {str(r["prediction_id"]): r for r in _read_jsonl(p["predictions"]) if r.get("prediction_id")}
    outs = {str(r["outcome_id"]): r for r in _read_jsonl(p["outcomes"]) if r.get("outcome_id")}
    open_by_tf: dict[str, str] = {}
    for pred in preds.values():
        if str(pred.get("prediction_status") or "") == "OPEN":
            open_by_tf[str(pred.get("timeframe") or "")] = str(pred["prediction_id"])
    processed = {str(r.get("context_event_id") or "") for r in preds.values() if r.get("context_event_id")}
    # Also mark FLIP/END close events from checkpoint if present
    ck = {}
    if p["checkpoint"].exists():
        try:
            ck = json.loads(p["checkpoint"].read_text(encoding="utf-8"))
        except Exception:
            ck = {}
    processed |= set(ck.get("processed_event_ids") or [])
    return ValidationState(preds, outs, open_by_tf, {x for x in processed if x})


def _close_prediction(
    state: ValidationState,
    *,
    prediction_id: str,
    closed_at: str,
    close_reason: str,
    close_event_id: str | None,
) -> None:
    pred = state.predictions.get(prediction_id)
    if not pred:
        return
    if str(pred.get("prediction_status")) != "OPEN":
        return
    pred["prediction_status"] = "CLOSED"
    pred["closed_at"] = closed_at
    pred["close_reason"] = close_reason
    pred["close_context_event_id"] = close_event_id
    tf = str(pred.get("timeframe") or "")
    if state.open_by_tf.get(tf) == prediction_id:
        state.open_by_tf.pop(tf, None)


def _open_prediction(
    state: ValidationState,
    *,
    active: dict[str, Any],
    event: dict[str, Any],
    direction: str,
) -> dict[str, Any] | None:
    context_event_id = str(event.get("context_event_id") or "")
    if not context_event_id:
        return None
    pid = prediction_id_for(
        registry_record_id=str(active["registry_record_id"]),
        context_event_id=context_event_id,
        direction=direction,
    )
    if pid in state.predictions:
        state.open_by_tf[str(event.get("timeframe") or "")] = pid
        return state.predictions[pid]
    start_price = event.get("context_event_price")
    try:
        start_price_f = float(start_price)
    except (TypeError, ValueError):
        return None
    if start_price_f <= 0:
        return None
    row = {
        "prediction_id": pid,
        "registry_record_id": active.get("registry_record_id"),
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "runtime_fingerprint": active.get("runtime_fingerprint"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "model_binding_method": "ACTIVE_REGISTRY_BY_EPOCH_TIME",
        "context_event_id": context_event_id,
        "lifecycle_episode_id": event.get("lifecycle_episode_id"),
        "timeframe": str(event.get("timeframe") or "").upper(),
        "direction": direction,
        "start_timestamp": event.get("event_timestamp"),
        "start_monotonic_ns": event.get("event_monotonic_ns"),
        "start_price": start_price_f,
        "last_trade_id": event.get("last_trade_id"),
        "prediction_status": "OPEN",
        "created_at": _utc_now_iso(),
        "runtime_impact": "NON_BLOCKING",
    }
    state.predictions[pid] = row
    state.open_by_tf[row["timeframe"]] = pid
    return row


def process_context_event(
    state: ValidationState,
    *,
    active: dict[str, Any],
    event: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply one CONTEXT_* event; return newly created prediction rows."""
    event_id = str(event.get("context_event_id") or "")
    if not event_id or event_id in state.processed_event_ids:
        return []
    event_type = str(event.get("event_type") or "").upper()
    tf = str(event.get("timeframe") or "").upper()
    created: list[dict[str, Any]] = []
    if event_type == "CONTEXT_START":
        direction = direction_from_context(event.get("new_context"))
        if direction:
            row = _open_prediction(state, active=active, event=event, direction=direction)
            if row and row["prediction_id"] not in {c["prediction_id"] for c in created}:
                # only brand-new if created_at just set and not previously persisted — caller dedupes
                created.append(row)
    elif event_type == "CONTEXT_FLIP":
        open_id = state.open_by_tf.get(tf)
        if open_id:
            _close_prediction(
                state,
                prediction_id=open_id,
                closed_at=str(event.get("event_timestamp") or _utc_now_iso()),
                close_reason="CONTEXT_FLIP",
                close_event_id=event_id,
            )
        direction = direction_from_context(event.get("new_context"))
        if direction:
            row = _open_prediction(state, active=active, event=event, direction=direction)
            if row:
                created.append(row)
    elif event_type == "CONTEXT_END":
        open_id = state.open_by_tf.get(tf)
        if open_id:
            _close_prediction(
                state,
                prediction_id=open_id,
                closed_at=str(event.get("event_timestamp") or _utc_now_iso()),
                close_reason="CONTEXT_END",
                close_event_id=event_id,
            )
    state.processed_event_ids.add(event_id)
    return created


def due_horizons_for_prediction(pred: dict[str, Any], *, now: datetime) -> list[tuple[str, datetime]]:
    start = _parse_ts(pred.get("start_timestamp"))
    if start is None:
        return []
    tf = str(pred.get("timeframe") or "").upper()
    due: list[tuple[str, datetime]] = []
    try:
        for _name, mult in HORIZON_MULTS:
            cutoff = start + timedelta(seconds=horizon_seconds(tf, mult))
            if now >= cutoff:
                due.append((f"{mult}xTF", cutoff))
    except ValueError:
        return []
    if str(pred.get("prediction_status")) == "CLOSED":
        closed_at = _parse_ts(pred.get("closed_at"))
        if closed_at is not None and now >= closed_at:
            due.append(("LIFECYCLE_END", closed_at))
    return due


def build_outcome_row(
    *,
    pred: dict[str, Any],
    horizon_type: str,
    cutoff: datetime,
    raw_root: Path,
    now: datetime,
) -> dict[str, Any]:
    start = _parse_ts(pred["start_timestamp"])
    assert start is not None
    evaluated = evaluate_horizon_window(
        direction=str(pred["direction"]),
        start_price=float(pred["start_price"]),
        start_ts=start,
        cutoff_ts=cutoff,
        raw_root=raw_root,
        now=now,
    )
    oid = outcome_id_for(prediction_id=str(pred["prediction_id"]), horizon_type=horizon_type)
    if horizon_type == "LIFECYCLE_END":
        seconds = int((cutoff - start).total_seconds())
    else:
        mult = int(str(horizon_type).split("x", 1)[0])
        seconds = horizon_seconds(str(pred["timeframe"]), mult)
    return {
        "outcome_id": oid,
        "prediction_id": pred["prediction_id"],
        "horizon_type": horizon_type,
        "horizon_seconds": seconds,
        "registry_record_id": pred.get("registry_record_id"),
        "model_id": pred.get("model_id"),
        "model_version": pred.get("model_version"),
        "paper_epoch_id": pred.get("paper_epoch_id"),
        "timeframe": pred.get("timeframe"),
        "direction": pred.get("direction"),
        **evaluated,
    }


def iter_eligible_context_events(
    events_path: Path,
    *,
    activated_at: datetime,
) -> Iterator[dict[str, Any]]:
    if not events_path.exists():
        return
    for row in _read_jsonl(events_path):
        et = str(row.get("event_type") or "").upper()
        if et not in {"CONTEXT_START", "CONTEXT_END", "CONTEXT_FLIP"}:
            continue
        ts = _parse_ts(row.get("event_timestamp"))
        if ts is None or ts < activated_at:
            continue
        yield row


def build_summary(
    *,
    active: dict[str, Any],
    state: ValidationState,
    source_tip: datetime | None,
    last_context_event_at: str | None,
    last_outcome_at: str | None,
) -> dict[str, Any]:
    now = _utc_now()
    preds = list(state.predictions.values())
    outs = list(state.outcomes.values())
    open_n = sum(1 for p in preds if str(p.get("prediction_status")) == "OPEN")
    closed_n = sum(1 for p in preds if str(p.get("prediction_status")) == "CLOSED")
    evaluated = [o for o in outs if o.get("outcome_status") == "EVALUATED"]
    pending = [o for o in outs if o.get("outcome_status") == "PENDING"]
    # Also count due-but-not-yet-written as pending conceptually via predictions
    due_missing = 0
    for pred in preds:
        for htype, _cutoff in due_horizons_for_prediction(pred, now=now):
            oid = outcome_id_for(prediction_id=str(pred["prediction_id"]), horizon_type=htype)
            if oid not in state.outcomes:
                due_missing += 1
    insuff = sum(1 for o in outs if o.get("outcome_status") == "INSUFFICIENT_MARKET_DATA")
    counts_tf: dict[str, int] = {}
    counts_dir: dict[str, int] = {}
    for p in preds:
        counts_tf[str(p.get("timeframe"))] = counts_tf.get(str(p.get("timeframe")), 0) + 1
        counts_dir[str(p.get("direction"))] = counts_dir.get(str(p.get("direction")), 0) + 1

    def _median(xs: list[float]) -> float | None:
        return float(statistics.median(xs)) if xs else None

    def _mean(xs: list[float]) -> float | None:
        return float(statistics.fmean(xs)) if xs else None

    by_h_signed: dict[str, list[float]] = {}
    by_h_mfe: dict[str, list[float]] = {}
    by_h_mae: dict[str, list[float]] = {}
    for o in evaluated:
        h = str(o.get("horizon_type"))
        if o.get("signed_return_bps") is not None:
            by_h_signed.setdefault(h, []).append(float(o["signed_return_bps"]))
        if o.get("mfe_bps") is not None:
            by_h_mfe.setdefault(h, []).append(float(o["mfe_bps"]))
        if o.get("mae_bps") is not None:
            by_h_mae.setdefault(h, []).append(float(o["mae_bps"]))

    source_age = None
    if source_tip is not None:
        source_age = max(0.0, (now - source_tip).total_seconds())

    eligible = len(preds)
    if eligible == 0:
        status = "NO_ELIGIBLE_CONTEXTS_YET"
    elif due_missing > 0:
        status = "COLLECTING_OUTCOMES"
    elif open_n > 0 and len(evaluated) == 0:
        status = "COLLECTING_OUTCOMES"
    elif source_age is not None and source_age > SOURCE_FRESH_SECONDS:
        status = "STALE_VALIDATION"
    else:
        status = "CURRENT"

    return {
        "status": status,
        "runtime_impact": "NON_BLOCKING",
        "registry_record_id": active.get("registry_record_id"),
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "eligible_contexts": eligible,
        "open_predictions": open_n,
        "closed_predictions": closed_n,
        "evaluated_outcomes": len(evaluated),
        "pending_outcomes": len(pending) + due_missing,
        "insufficient_market_data": insuff,
        "counts_by_timeframe": counts_tf,
        "counts_by_direction": counts_dir,
        "mean_signed_return_bps_by_horizon": {k: _mean(v) for k, v in by_h_signed.items()},
        "median_mfe_bps_by_horizon": {k: _median(v) for k, v in by_h_mfe.items()},
        "median_mae_bps_by_horizon": {k: _median(v) for k, v in by_h_mae.items()},
        "last_context_event_at": last_context_event_at,
        "last_outcome_at": last_outcome_at,
        "source_data_age_seconds": source_age,
        "updated_at": _utc_now_iso(),
    }


def run_once(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    p = paths(root)
    active = read_active_runtime(repo_root=root)
    if not active:
        summary = {
            "status": "NO_ACTIVE_MODEL",
            "runtime_impact": "NON_BLOCKING",
            "eligible_contexts": 0,
            "open_predictions": 0,
            "closed_predictions": 0,
            "evaluated_outcomes": 0,
            "pending_outcomes": 0,
            "insufficient_market_data": 0,
            "updated_at": _utc_now_iso(),
        }
        _atomic_write_json(p["summary"], summary)
        _atomic_write_json(
            p["health"],
            {"status": "NO_ACTIVE_MODEL", "alive": True, "updated_at": _utc_now_iso(), "runtime_impact": "NON_BLOCKING"},
        )
        return summary

    activated = _parse_ts(active.get("paper_epoch_activated_at"))
    if activated is None:
        activated = _parse_ts("1970-01-01T00:00:00Z")
        assert activated is not None

    state = load_state(p)
    existing_pred_ids = set(state.predictions.keys())
    existing_out_ids = set(state.outcomes.keys())

    last_context_at = None
    new_preds: list[dict[str, Any]] = []
    for event in iter_eligible_context_events(p["context_events"], activated_at=activated):
        last_context_at = str(event.get("event_timestamp") or last_context_at)
        created = process_context_event(state, active=active, event=event)
        for row in created:
            if row["prediction_id"] not in existing_pred_ids:
                new_preds.append(row)

    # Persist predictions (including status updates): rewrite file atomically from state for simplicity
    # while remaining append-only for brand-new ids; updates to CLOSED are patched via rewrite of jsonl.
    _rewrite_predictions(p["predictions"], list(state.predictions.values()))
    existing_pred_ids = set(state.predictions.keys())

    now = _utc_now()
    last_outcome_at = None
    for pred in list(state.predictions.values()):
        for htype, cutoff in due_horizons_for_prediction(pred, now=now):
            oid = outcome_id_for(prediction_id=str(pred["prediction_id"]), horizon_type=htype)
            if oid in existing_out_ids:
                continue
            row = build_outcome_row(pred=pred, horizon_type=htype, cutoff=cutoff, raw_root=p["raw_root"], now=now)
            if row.get("outcome_status") == "PENDING":
                continue
            if _append_jsonl_unique(p["outcomes"], row, id_key="outcome_id", existing=existing_out_ids):
                state.outcomes[oid] = row
                last_outcome_at = row.get("evaluated_at")

    source_tip = latest_agg_trade_ts(p["raw_root"])
    summary = build_summary(
        active=active,
        state=state,
        source_tip=source_tip,
        last_context_event_at=last_context_at,
        last_outcome_at=last_outcome_at,
    )
    _atomic_write_json(p["summary"], summary)
    _atomic_write_json(
        p["checkpoint"],
        {
            "processed_event_ids": sorted(state.processed_event_ids),
            "open_by_tf": state.open_by_tf,
            "updated_at": _utc_now_iso(),
        },
    )
    _atomic_write_json(
        p["health"],
        {
            "status": summary["status"],
            "alive": True,
            "runtime_impact": "NON_BLOCKING",
            "pid": os.getpid(),
            "eligible_contexts": summary["eligible_contexts"],
            "open_predictions": summary["open_predictions"],
            "closed_predictions": summary["closed_predictions"],
            "evaluated_outcomes": summary["evaluated_outcomes"],
            "pending_outcomes": summary["pending_outcomes"],
            "source_data_age_seconds": summary.get("source_data_age_seconds"),
            "paper_only": active.get("paper_only", True),
            "real_execution": active.get("real_execution", False),
            "updated_at": _utc_now_iso(),
        },
    )
    return summary


def _rewrite_predictions(path: Path, rows: list[dict[str, Any]]) -> None:
    """Atomic rewrite of predictions jsonl (status updates require rewrite)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for row in sorted(rows, key=lambda r: str(r.get("created_at") or "")):
                fh.write(_canonical_json(row) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def read_summary(*, repo_root: Path | None = None) -> dict[str, Any]:
    path = paths(repo_root)["summary"]
    if not path.exists():
        return {"status": "NOT_STARTED"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "CORRUPT", "error": str(exc)}


def read_health(*, repo_root: Path | None = None) -> dict[str, Any]:
    path = paths(repo_root)["health"]
    if not path.exists():
        return {"status": "NOT_STARTED", "alive": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "CORRUPT", "alive": False, "error": str(exc)}
