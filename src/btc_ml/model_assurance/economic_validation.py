"""Observational economic validation for the active LIVE1B paper epoch (MODEL-3).

NON-BLOCKING — does not affect trading, cognition, or System Health.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from btc_ml.model_assurance.registry import (
    load_active_trading_contract,
    read_active_runtime,
)
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.economics import closed_trade_economics
from btc_ml.trading.intrabar_paper.books import EpochBooks

VOID_STATUS = "VOID_PRE_INTRABAR_RULE_CONTRACT"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)
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
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n"
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


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "economic_validation"
    return {
        "root": base,
        "evaluations": base / "trades" / "trade_evaluations.jsonl",
        "summary": base / "snapshots" / "latest_summary.json",
        "checkpoint": base / "runtime" / "checkpoint.json",
        "health": base / "runtime" / "health.json",
        "config": root / "config" / "model_assurance_economic_validation.json",
        "active_epoch": root / "data" / "trading" / "paper_epochs" / "active.json",
        "books_root": root / "data" / "trading" / "intrabar_paper",
    }


def load_config(repo_root: Path | None = None) -> dict[str, Any]:
    path = paths(repo_root)["config"]
    return json.loads(path.read_text(encoding="utf-8"))


def economic_evaluation_id(*, registry_record_id: str, paper_epoch_id: str, trade_id: str) -> str:
    return "ECON_" + _sha256_text(
        _canonical_json(
            {
                "registry_record_id": registry_record_id,
                "paper_epoch_id": paper_epoch_id,
                "trade_id": trade_id,
            }
        )
    )[:32]


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


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_canonical_json(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_active_epoch(repo_root: Path | None = None) -> dict[str, Any] | None:
    path = paths(repo_root)["active_epoch"]
    payload = _read_json(path)
    if not payload:
        return None
    if str(payload.get("epoch_status") or "").upper() != "ACTIVE":
        return None
    if not str(payload.get("paper_epoch_id") or "").strip():
        return None
    return payload


def books_for_epoch(paper_epoch_id: str, *, repo_root: Path | None = None) -> EpochBooks:
    root = repo_root or _repo_root()
    return EpochBooks(paths(root)["books_root"] / paper_epoch_id / "books", paper_epoch_id=paper_epoch_id)


def is_eligible_closed_trade(
    trade: dict[str, Any],
    *,
    paper_epoch_id: str,
    activated_at: datetime,
) -> bool:
    if str(trade.get("paper_epoch_id") or "") and str(trade.get("paper_epoch_id")) != paper_epoch_id:
        return False
    # EpochBooks always stamps paper_epoch_id on append; missing ⇒ exclude.
    if not str(trade.get("paper_epoch_id") or "").strip():
        return False
    status = str(trade.get("status") or trade.get("void_status") or "").upper()
    if status == VOID_STATUS or status.startswith("VOID_"):
        return False
    if status and status not in {"CLOSED", "CLOSE", ""}:
        # require closed
        if status != "CLOSED":
            return False
    exit_ts = _parse_ts(trade.get("exit_ts") or trade.get("exit_timestamp") or trade.get("closed_at"))
    if exit_ts is None:
        return False
    if exit_ts < activated_at:
        return False
    entry = _f(trade.get("entry_price"))
    exit_ = _f(trade.get("exit_price"))
    qty = _f(trade.get("quantity"))
    if entry is None or exit_ is None or qty is None or qty <= 0:
        return False
    return True


def compute_trade_economics(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    risk_amount_usd: float,
    exit_reason: str | None,
    cfg: Any,
) -> dict[str, Any]:
    """Delegate to LIVE1B closed_trade_economics (no new formula)."""
    return closed_trade_economics(
        cfg=cfg,
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        risk_amount_usd=risk_amount_usd,
        exit_reason=exit_reason,
    )


def reconcile_net_pnl(
    *,
    computed_net: float,
    canonical_net: float | None,
    tolerance_usd: float,
) -> tuple[str, float | None]:
    if canonical_net is None:
        return "CANONICAL_PNL_UNAVAILABLE", None
    diff = float(computed_net) - float(canonical_net)
    if abs(diff) <= float(tolerance_usd):
        return "MATCHED", diff
    return "MISMATCH", diff


def build_evaluation_record(
    *,
    active: dict[str, Any],
    trade: dict[str, Any],
    econ: dict[str, Any],
    reconciliation_status: str,
    pnl_difference_usd: float | None,
    entry_ts: str | None,
    exit_ts: str | None,
    holding_seconds: float | None,
) -> dict[str, Any]:
    risk = _f(trade.get("risk_amount_usd")) or _f(econ.get("risk_amount_usd")) or 0.0
    net = float(econ["net_pnl_usd"])
    r_mult = (net / risk) if risk > 0 else None
    mfe = _f(trade.get("mfe_bps"))
    mae = _f(trade.get("mae_bps"))
    if mfe is None and mae is None:
        mfe_mae_source = "NOT_RECORDED"
    else:
        mfe_mae_source = "LIVE1B_RECORDED"
    eid = economic_evaluation_id(
        registry_record_id=str(active["registry_record_id"]),
        paper_epoch_id=str(active["paper_epoch_id"]),
        trade_id=str(trade["trade_id"]),
    )
    return {
        "economic_evaluation_id": eid,
        "registry_record_id": active.get("registry_record_id"),
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "runtime_fingerprint":
            active.get(
                "runtime_fingerprint"
            ),
        "trading_contract_fingerprint":
            active.get(
                "trading_contract_fingerprint"
            ),
        "paper_epoch_id":
            active.get(
                "paper_epoch_id"
            ),
        "trade_id": trade.get("trade_id"),
        "position_id": trade.get("position_id"),
        "timeframe": str(trade.get("timeframe") or "").upper(),
        "direction": str(trade.get("side") or trade.get("direction") or "").upper(),
        "context_event_id": trade.get("context_event_id"),
        "lifecycle_episode_id": trade.get("lifecycle_episode_id"),
        "entry_timestamp": entry_ts,
        "exit_timestamp": exit_ts,
        "holding_seconds": holding_seconds,
        "exit_reason": trade.get("exit_reason"),
        "quantity": _f(trade.get("quantity")),
        "entry_fill_price": float(econ["gross_entry_price"]),
        "exit_fill_price": float(econ["gross_exit_price"]),
        "gross_pnl_usd": float(econ["gross_pnl_usd"]),
        "entry_fee_usd": float(econ["entry_fee_usd"]),
        "exit_fee_usd": float(econ["exit_fee_usd"]),
        "total_fee_usd": float(econ["fees_usd"]),
        "entry_slippage_usd": float(econ["entry_slippage_usd"]),
        "exit_slippage_usd": float(econ["exit_slippage_usd"]),
        "total_slippage_usd": float(econ["slippage_usd"]),
        "net_pnl_usd": net,
        "initial_risk_budget_usd": float(risk) if risk > 0 else 0.0,
        "realized_r_multiple": r_mult,
        "mfe_bps": mfe,
        "mae_bps": mae,
        "mfe_mae_source": mfe_mae_source,
        "canonical_net_pnl_usd": _f(trade.get("net_pnl_usd")),
        "pnl_difference_usd": pnl_difference_usd,
        "pnl_reconciliation_status": reconciliation_status,
        "evaluated_at": _utc_now_iso(),
        "runtime_impact": "NON_BLOCKING",
    }


def _position_opened_at(books: EpochBooks, position_id: str | None) -> str | None:
    if not position_id:
        return None
    for row in books.read_all("positions"):
        if str(row.get("position_id") or "") != str(position_id):
            continue
        if str(row.get("status") or "").upper() == "OPEN":
            return row.get("opened_at") or row.get("ts")
    # fallback any row
    for row in books.read_all("positions"):
        if str(row.get("position_id") or "") == str(position_id):
            return row.get("opened_at") or row.get("ts")
    return None


def equity_metrics(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    equities: list[float] = []
    for row in snapshots:
        eq = _f(row.get("equity_usd"))
        if eq is not None:
            equities.append(eq)
    if len(equities) < 2:
        return {
            "current_equity": equities[-1] if equities else None,
            "max_drawdown_pct": None,
            "sharpe": None,
            "calmar": None,
            "reason": "INSUFFICIENT_OBSERVATIONS",
        }
    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    rets = []
    for i in range(1, len(equities)):
        if equities[i - 1] > 0:
            rets.append((equities[i] - equities[i - 1]) / equities[i - 1])
    sharpe = None
    if len(rets) >= 2 and statistics.pstdev(rets) > 0:
        sharpe = statistics.fmean(rets) / statistics.pstdev(rets)
    calmar = None
    total_ret = (equities[-1] / equities[0] - 1.0) if equities[0] > 0 else None
    if total_ret is not None and max_dd > 0:
        calmar = total_ret / max_dd
    return {
        "current_equity": equities[-1],
        "max_drawdown_pct": max_dd * 100.0,
        "sharpe": sharpe,
        "calmar": calmar,
        "reason": None,
    }


def build_summary(
    *,
    active: dict[str, Any],
    evaluations: list[dict[str, Any]],
    open_positions: int,
    closed_trade_count: int,
    equity_snaps: list[dict[str, Any]],
    config: dict[str, Any],
    source_age_seconds: float | None,
) -> dict[str, Any]:
    nets = [float(e["net_pnl_usd"]) for e in evaluations]
    gross = sum(float(e["gross_pnl_usd"]) for e in evaluations)
    fees = sum(float(e["total_fee_usd"]) for e in evaluations)
    slip = sum(float(e["total_slippage_usd"]) for e in evaluations)
    net = sum(nets)
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n < 0]
    rs = [float(e["realized_r_multiple"]) for e in evaluations if e.get("realized_r_multiple") is not None]
    avg_r = statistics.fmean(rs) if rs else None
    med_r = statistics.median(rs) if rs else None
    expectancy_r = avg_r
    profit_factor = None
    if losses:
        denom = abs(sum(losses))
        if denom > 0:
            profit_factor = sum(wins) / denom
    elif wins:
        profit_factor = None  # undefined / infinite — leave null

    by_tf: dict[str, int] = {}
    by_dir: dict[str, int] = {}
    pnl_tf: dict[str, float] = {}
    pnl_dir: dict[str, float] = {}
    for e in evaluations:
        tf = str(e.get("timeframe") or "")
        d = str(e.get("direction") or "")
        by_tf[tf] = by_tf.get(tf, 0) + 1
        by_dir[d] = by_dir.get(d, 0) + 1
        pnl_tf[tf] = pnl_tf.get(tf, 0.0) + float(e["net_pnl_usd"])
        pnl_dir[d] = pnl_dir.get(d, 0.0) + float(e["net_pnl_usd"])

    matched = sum(1 for e in evaluations if e.get("pnl_reconciliation_status") == "MATCHED")
    mismatched = sum(1 for e in evaluations if e.get("pnl_reconciliation_status") == "MISMATCH")
    missing = sum(1 for e in evaluations if e.get("pnl_reconciliation_status") == "CANONICAL_PNL_UNAVAILABLE")

    eqm = equity_metrics(equity_snaps)
    last_closed = None
    last_eval = None
    for e in evaluations:
        if e.get("exit_timestamp"):
            last_closed = e.get("exit_timestamp")
        if e.get("evaluated_at"):
            last_eval = e.get("evaluated_at")

    min_for_current = int(config.get("min_closed_trades_for_current", 5))
    stale_s = float(config.get("source_stale_seconds", 120))
    if closed_trade_count == 0:
        status = "NO_ELIGIBLE_TRADES_YET"
    elif mismatched > 0:
        status = "RECONCILIATION_WARNING"
    elif source_age_seconds is not None and source_age_seconds > stale_s and closed_trade_count > 0:
        status = "STALE_VALIDATION"
    elif closed_trade_count < min_for_current:
        status = "COLLECTING_TRADES"
    else:
        status = "CURRENT"

    return {
        "status": status,
        "runtime_impact": "NON_BLOCKING",
        "monitoring_mode": "LIVE_CURRENT",
        "registry_record_id": active.get("registry_record_id"),
        "model_id": active.get("model_id"),
        "model_version":
            active.get(
                "model_version"
            ),
        "runtime_fingerprint":
            active.get(
                "runtime_fingerprint"
            ),
        "trading_contract_fingerprint":
            active.get(
                "trading_contract_fingerprint"
            ),
        "paper_epoch_id":
            active.get(
                "paper_epoch_id"
            ),
        "closed_trades":
            closed_trade_count,
        "open_positions": open_positions,
        "evaluated_trades": len(evaluations),
        "pending_trades": max(0, closed_trade_count - len(evaluations)),
        "gross_pnl_usd": gross,
        "net_pnl_usd": net,
        "fees_usd": fees,
        "slippage_usd": slip,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": (len(wins) / len(nets)) if nets else None,
        "average_r": avg_r,
        "median_r": med_r,
        "expectancy_r": expectancy_r,
        "profit_factor": profit_factor,
        "current_equity": eqm.get("current_equity"),
        "max_drawdown_pct": eqm.get("max_drawdown_pct"),
        "sharpe": eqm.get("sharpe"),
        "calmar": eqm.get("calmar"),
        "equity_metrics_reason": eqm.get("reason"),
        "counts_by_timeframe": by_tf,
        "counts_by_direction": by_dir,
        "pnl_by_timeframe": pnl_tf,
        "pnl_by_direction": pnl_dir,
        "matched_reconciliations": matched,
        "mismatched_reconciliations": mismatched,
        "missing_canonical_pnl": missing,
        "last_trade_closed_at": last_closed,
        "last_evaluated_at": last_eval,
        "source_age_seconds": source_age_seconds,
        "updated_at": _utc_now_iso(),
    }


def load_epoch_execution_config(
    *,
    repo_root: Path,
    epoch: dict[str, Any],
):
    """Load only immutable fields used by closed-trade economics."""
    contract = load_active_trading_contract(
        repo_root,
        epoch=epoch,
    )

    if contract is None:
        # Legacy epochs predate immutable trading contracts.
        return (
            load_intrabar_paper_config(
                repo_root=repo_root
            ),
            None,
        )

    manifest = contract.get(
        "trading_contract_manifest"
    )

    if not isinstance(
        manifest,
        dict,
    ):
        raise RuntimeError(
            "ECONOMIC_CONTRACT_MANIFEST_INVALID"
        )

    snapshot = manifest.get(
        "execution_config_snapshot"
    )

    if not isinstance(
        snapshot,
        dict,
    ):
        raise RuntimeError(
            "ECONOMIC_EXECUTION_SNAPSHOT_MISSING"
        )

    required = (
        "entry_fee_bps",
        "exit_fee_bps",
        "entry_slippage_bps",
        "exit_slippage_bps",
        "stop_exit_slippage_bps",
    )

    missing = [
        key
        for key in required
        if key not in snapshot
    ]

    if missing:
        raise RuntimeError(
            "ECONOMIC_EXECUTION_"
            "SNAPSHOT_INCOMPLETE:"
            + ",".join(
                sorted(missing)
            )
        )

    paper_only = bool(
        snapshot.get(
            "paper_only",
            True,
        )
    )
    real_execution = bool(
        snapshot.get(
            "real_execution_enabled",
            False,
        )
    )

    if (
        paper_only is not True
        or real_execution is not False
    ):
        raise RuntimeError(
            "ECONOMIC_EXECUTION_"
            "SNAPSHOT_UNSAFE"
        )

    config = SimpleNamespace(
        entry_fee_bps=float(
            snapshot[
                "entry_fee_bps"
            ]
        ),
        exit_fee_bps=float(
            snapshot[
                "exit_fee_bps"
            ]
        ),
        entry_slippage_bps=float(
            snapshot[
                "entry_slippage_bps"
            ]
        ),
        exit_slippage_bps=float(
            snapshot[
                "exit_slippage_bps"
            ]
        ),
        stop_exit_slippage_bps=float(
            snapshot[
                "stop_exit_slippage_bps"
            ]
        ),
        economics_source=str(
            snapshot.get(
                "economics_source",
                "canonical_paper_"
                "trade_economics_v1",
            )
        ),
        paper_only=paper_only,
        real_execution_enabled=
            real_execution,
        raw=dict(snapshot),
    )

    return config, contract


def active_binding_mismatch(
    *,
    active: dict[str, Any],
    epoch: dict[str, Any],
) -> str | None:
    registry_epoch = str(
        active.get(
            "paper_epoch_id"
        )
        or ""
    )
    paper_epoch = str(
        epoch.get(
            "paper_epoch_id"
        )
        or ""
    )

    if registry_epoch != paper_epoch:
        return (
            "PAPER_EPOCH_ID_MISMATCH"
        )

    paper_fingerprint = str(
        epoch.get(
            "trading_contract_fingerprint"
        )
        or ""
    )
    registry_fingerprint = str(
        active.get(
            "trading_contract_fingerprint"
        )
        or ""
    )

    if (
        paper_fingerprint
        and registry_fingerprint
        != paper_fingerprint
    ):
        return (
            "TRADING_CONTRACT_"
            "FINGERPRINT_MISMATCH"
        )

    return None


def mark_health_stopped(
    *,
    repo_root: Path | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    """Persist that the economic validation process is no longer alive."""
    p = paths(repo_root)
    payload = (
        _read_json(
            p["health"]
        )
        or {}
    )

    payload.update(
        {
            "alive":
                False,
            "pid": (
                pid
                if pid is not None
                else payload.get(
                    "pid"
                )
            ),
            "stopped_at":
                _utc_now_iso(),
            "updated_at":
                _utc_now_iso(),
            "runtime_impact":
                "NON_BLOCKING",
        }
    )

    _atomic_write_json(
        p["health"],
        payload,
    )

    return payload


def run_once(
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    p = paths(root)
    config = load_config(root)
    active = read_active_runtime(
        repo_root=root
    )
    epoch = load_active_epoch(
        repo_root=root
    )

    if not active or not epoch:
        status = (
            "NO_ACTIVE_MODEL"
            if not active
            else "NO_ACTIVE_PAPER_EPOCH"
        )

        summary = {
            "status":
                status,
            "runtime_impact":
                "NON_BLOCKING",
            "monitoring_mode":
                "LIVE_CURRENT",
            "registry_record_id": (
                (active or {}).get(
                    "registry_record_id"
                )
            ),
            "registry_paper_epoch_id": (
                (active or {}).get(
                    "paper_epoch_id"
                )
            ),
            "paper_epoch_id": (
                (epoch or {}).get(
                    "paper_epoch_id"
                )
            ),
            "closed_trades":
                0,
            "open_positions":
                0,
            "evaluated_trades":
                0,
            "pending_trades":
                0,
            "updated_at":
                _utc_now_iso(),
        }

        _atomic_write_json(
            p["summary"],
            summary,
        )
        _atomic_write_json(
            p["health"],
            {
                **summary,
                "alive":
                    True,
                "pid":
                    os.getpid(),
                "paper_only": (
                    (active or {}).get(
                        "paper_only",
                        True,
                    )
                ),
                "real_execution": (
                    (active or {}).get(
                        "real_execution",
                        False,
                    )
                ),
            },
        )

        return summary

    mismatch = active_binding_mismatch(
        active=active,
        epoch=epoch,
    )

    if mismatch:
        summary = {
            "status":
                "ACTIVE_BINDING_MISMATCH",
            "binding_mismatch_reason":
                mismatch,
            "runtime_impact":
                "NON_BLOCKING",
            "monitoring_mode":
                "LIVE_CURRENT",
            "registry_record_id":
                active.get(
                    "registry_record_id"
                ),
            "model_id":
                active.get(
                    "model_id"
                ),
            "model_version":
                active.get(
                    "model_version"
                ),
            "runtime_fingerprint":
                active.get(
                    "runtime_fingerprint"
                ),
            "registry_paper_epoch_id":
                active.get(
                    "paper_epoch_id"
                ),
            "paper_epoch_id":
                epoch.get(
                    "paper_epoch_id"
                ),
            "registry_trading_contract_fingerprint":
                active.get(
                    "trading_contract_fingerprint"
                ),
            "trading_contract_fingerprint":
                epoch.get(
                    "trading_contract_fingerprint"
                ),
            "closed_trades":
                0,
            "open_positions":
                0,
            "evaluated_trades":
                0,
            "pending_trades":
                0,
            "updated_at":
                _utc_now_iso(),
        }

        _atomic_write_json(
            p["summary"],
            summary,
        )
        _atomic_write_json(
            p["checkpoint"],
            {
                "status":
                    summary["status"],
                "binding_mismatch_reason":
                    mismatch,
                "registry_record_id":
                    active.get(
                        "registry_record_id"
                    ),
                "registry_paper_epoch_id":
                    active.get(
                        "paper_epoch_id"
                    ),
                "paper_epoch_id":
                    epoch.get(
                        "paper_epoch_id"
                    ),
                "trading_contract_fingerprint":
                    epoch.get(
                        "trading_contract_fingerprint"
                    ),
                "evaluated_trade_ids":
                    [],
                "updated_at":
                    _utc_now_iso(),
            },
        )
        _atomic_write_json(
            p["health"],
            {
                **summary,
                "alive":
                    True,
                "pid":
                    os.getpid(),
                "paper_only":
                    active.get(
                        "paper_only",
                        True,
                    ),
                "real_execution":
                    active.get(
                        "real_execution",
                        False,
                    ),
            },
        )

        return summary

    paper_epoch_id = str(
        epoch[
            "paper_epoch_id"
        ]
    )
    paper_fingerprint = str(
        epoch.get(
            "trading_contract_fingerprint"
        )
        or active.get(
            "trading_contract_fingerprint"
        )
        or ""
    )

    binding = {
        **active,
        "paper_epoch_id":
            paper_epoch_id,
        "paper_epoch_activated_at":
            epoch.get(
                "activated_at"
            ),
        "trading_contract_fingerprint":
            paper_fingerprint,
    }

    try:
        cfg, _contract = (
            load_epoch_execution_config(
                repo_root=root,
                epoch=epoch,
            )
        )
    except RuntimeError as exc:
        summary = {
            "status":
                "ACTIVE_CONTRACT_INVALID",
            "contract_error":
                str(exc),
            "runtime_impact":
                "NON_BLOCKING",
            "monitoring_mode":
                "LIVE_CURRENT",
            "registry_record_id":
                binding.get(
                    "registry_record_id"
                ),
            "runtime_fingerprint":
                binding.get(
                    "runtime_fingerprint"
                ),
            "trading_contract_fingerprint":
                paper_fingerprint,
            "paper_epoch_id":
                paper_epoch_id,
            "closed_trades":
                0,
            "open_positions":
                0,
            "evaluated_trades":
                0,
            "pending_trades":
                0,
            "updated_at":
                _utc_now_iso(),
        }

        _atomic_write_json(
            p["summary"],
            summary,
        )
        _atomic_write_json(
            p["health"],
            {
                **summary,
                "alive":
                    True,
                "pid":
                    os.getpid(),
                "paper_only":
                    binding.get(
                        "paper_only",
                        True,
                    ),
                "real_execution":
                    binding.get(
                        "real_execution",
                        False,
                    ),
            },
        )

        return summary

    activated = _parse_ts(
        epoch.get(
            "activated_at"
        )
    )

    if activated is None:
        activated = datetime(
            1970,
            1,
            1,
            tzinfo=timezone.utc,
        )

    books = books_for_epoch(
        paper_epoch_id,
        repo_root=root,
    )
    trades = books.read_all(
        "trades"
    )
    eligible = [
        trade
        for trade in trades
        if is_eligible_closed_trade(
            trade,
            paper_epoch_id=
                paper_epoch_id,
            activated_at=
                activated,
        )
    ]
    open_positions = len(
        books.open_positions()
    )

    existing = {
        str(
            row.get(
                "economic_evaluation_id"
            )
        ): row
        for row in _read_jsonl(
            p["evaluations"]
        )
    }
    existing_ids = set(
        existing.keys()
    )
    tolerance = float(
        config.get(
            "pnl_reconciliation_tolerance_usd",
            0.01,
        )
    )

    for trade in eligible:
        evaluation_id = (
            economic_evaluation_id(
                registry_record_id=str(
                    binding[
                        "registry_record_id"
                    ]
                ),
                paper_epoch_id=
                    paper_epoch_id,
                trade_id=str(
                    trade[
                        "trade_id"
                    ]
                ),
            )
        )

        if evaluation_id in existing_ids:
            continue

        side = str(
            trade.get("side")
            or trade.get(
                "direction"
            )
            or "LONG"
        )
        risk = (
            _f(
                trade.get(
                    "risk_amount_usd"
                )
            )
            or 0.0
        )
        economics = (
            compute_trade_economics(
                side=side,
                entry_price=float(
                    trade[
                        "entry_price"
                    ]
                ),
                exit_price=float(
                    trade[
                        "exit_price"
                    ]
                ),
                quantity=float(
                    trade[
                        "quantity"
                    ]
                ),
                risk_amount_usd=
                    risk,
                exit_reason=trade.get(
                    "exit_reason"
                ),
                cfg=cfg,
            )
        )

        identity_check = (
            float(
                economics[
                    "gross_pnl_usd"
                ]
            )
            - float(
                economics[
                    "entry_fee_usd"
                ]
            )
            - float(
                economics[
                    "exit_fee_usd"
                ]
            )
            - float(
                economics[
                    "entry_slippage_usd"
                ]
            )
            - float(
                economics[
                    "exit_slippage_usd"
                ]
            )
        )

        if (
            abs(
                identity_check
                - float(
                    economics[
                        "net_pnl_usd"
                    ]
                )
            )
            > 1e-9
        ):
            raise AssertionError(
                "economic identity broken"
            )

        reconciliation, difference = (
            reconcile_net_pnl(
                computed_net=float(
                    economics[
                        "net_pnl_usd"
                    ]
                ),
                canonical_net=_f(
                    trade.get(
                        "net_pnl_usd"
                    )
                ),
                tolerance_usd=
                    tolerance,
            )
        )

        exit_ts = (
            trade.get("exit_ts")
            or trade.get(
                "exit_timestamp"
            )
            or trade.get(
                "closed_at"
            )
        )
        entry_ts = (
            trade.get("entry_ts")
            or trade.get(
                "entry_timestamp"
            )
            or _position_opened_at(
                books,
                trade.get(
                    "position_id"
                ),
            )
        )

        holding = None
        entry_stamp = _parse_ts(
            entry_ts
        )
        exit_stamp = _parse_ts(
            exit_ts
        )

        if (
            entry_stamp
            and exit_stamp
        ):
            holding = max(
                0.0,
                (
                    exit_stamp
                    - entry_stamp
                ).total_seconds(),
            )

        row = build_evaluation_record(
            active=binding,
            trade=trade,
            econ=economics,
            reconciliation_status=
                reconciliation,
            pnl_difference_usd=
                difference,
            entry_ts=entry_ts,
            exit_ts=exit_ts,
            holding_seconds=holding,
        )

        _append_jsonl(
            p["evaluations"],
            row,
        )
        existing[
            evaluation_id
        ] = row
        existing_ids.add(
            evaluation_id
        )

    evaluations = [
        evaluation
        for evaluation
        in existing.values()
        if evaluation.get(
            "paper_epoch_id"
        )
        == paper_epoch_id
        and evaluation.get(
            "registry_record_id"
        )
        == binding.get(
            "registry_record_id"
        )
        and (
            not paper_fingerprint
            or evaluation.get(
                "trading_contract_fingerprint"
            )
            == paper_fingerprint
        )
    ]

    equity_snapshots = [
        row
        for row in books.read_all(
            "equity_snapshots"
        )
        if str(
            row.get(
                "paper_epoch_id"
            )
            or ""
        )
        == paper_epoch_id
    ]

    source_age = None
    tip_candidates = []

    for row in equity_snapshots:
        tip_candidates.append(
            _parse_ts(
                row.get("ts")
            )
        )

    for evaluation in evaluations:
        tip_candidates.append(
            _parse_ts(
                evaluation.get(
                    "exit_timestamp"
                )
            )
        )

    tips = [
        stamp
        for stamp in tip_candidates
        if stamp is not None
    ]

    if tips:
        source_age = max(
            0.0,
            (
                _utc_now()
                - max(tips)
            ).total_seconds(),
        )

    summary = build_summary(
        active=binding,
        evaluations=evaluations,
        open_positions=
            open_positions,
        closed_trade_count=len(
            eligible
        ),
        equity_snaps=
            equity_snapshots,
        config=config,
        source_age_seconds=
            source_age,
    )

    _atomic_write_json(
        p["summary"],
        summary,
    )
    _atomic_write_json(
        p["checkpoint"],
        {
            "status":
                summary["status"],
            "registry_record_id":
                binding.get(
                    "registry_record_id"
                ),
            "runtime_fingerprint":
                binding.get(
                    "runtime_fingerprint"
                ),
            "trading_contract_fingerprint":
                paper_fingerprint,
            "paper_epoch_id":
                paper_epoch_id,
            "evaluated_trade_ids":
                sorted(
                    str(
                        evaluation.get(
                            "trade_id"
                        )
                    )
                    for evaluation
                    in evaluations
                ),
            "updated_at":
                _utc_now_iso(),
        },
    )
    _atomic_write_json(
        p["health"],
        {
            "status":
                summary["status"],
            "alive":
                True,
            "runtime_impact":
                "NON_BLOCKING",
            "monitoring_mode":
                "LIVE_CURRENT",
            "pid":
                os.getpid(),
            "registry_record_id":
                binding.get(
                    "registry_record_id"
                ),
            "runtime_fingerprint":
                binding.get(
                    "runtime_fingerprint"
                ),
            "trading_contract_fingerprint":
                paper_fingerprint,
            "paper_epoch_id":
                paper_epoch_id,
            "closed_trades":
                summary[
                    "closed_trades"
                ],
            "open_positions":
                summary[
                    "open_positions"
                ],
            "evaluated_trades":
                summary[
                    "evaluated_trades"
                ],
            "mismatched_reconciliations":
                summary[
                    "mismatched_reconciliations"
                ],
            "paper_only":
                binding.get(
                    "paper_only",
                    True,
                ),
            "real_execution":
                binding.get(
                    "real_execution",
                    False,
                ),
            "updated_at":
                _utc_now_iso(),
        },
    )

    return summary
