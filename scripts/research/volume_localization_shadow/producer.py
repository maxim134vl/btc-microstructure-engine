"""Isolated volume-localization shadow producer.

Reuses the proven legacy-v1 algorithm from capability_gap.volume_localization_candidate.
Writes only under data/candidate/volume_localization_shadow/. Never touches live memories.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts" / "research") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts" / "research"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from capability_gap.volume_localization_candidate import (  # noqa: E402
    REQUIRED,
    localize_bar,
)
from parquet_utils import atomic_parquet_write  # noqa: E402

ALGORITHM_VERSION = "volume_localization_v1@8fbde36"
SOURCE_TIMEFRAME = "M15"
BAR_SECONDS = 15 * 60
DEFAULT_SOURCE = REPO / "data" / "cognition" / "candle_structure_memory.parquet"
DEFAULT_OUT_DIR = REPO / "data" / "candidate" / "volume_localization_shadow"
LEGACY_ORPHAN = REPO / "data" / "cognition" / "volume_localization_memory.parquet"
FINAL_CONTEXT = REPO / "data" / "cognition" / "final_market_context_memory.parquet"
LIVE_FEED = REPO / "data" / "live" / "live_market_feed.parquet"

INPUT_SCHEMA_FIELDS = list(REQUIRED)


def input_schema_hash() -> str:
    payload = "|".join(INPUT_SCHEMA_FIELDS) + f"|{ALGORITHM_VERSION}|{SOURCE_TIMEFRAME}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def shadow_row_id(
    *,
    source_timestamp: pd.Timestamp,
    schema_hash: str,
    algorithm_version: str = ALGORITHM_VERSION,
    timeframe: str = SOURCE_TIMEFRAME,
) -> str:
    ts = pd.Timestamp(source_timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    payload = "|".join(
        [
            algorithm_version,
            timeframe,
            ts.isoformat().replace("+00:00", "Z"),
            schema_hash,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _dominant_zone(behavior: str) -> str:
    if behavior == "localized_absorption":
        return "LOWER"
    if behavior == "localized_distribution":
        return "UPPER"
    return "MIDDLE"


def _inventory_transfer_state(behavior: str) -> str:
    """Research approximation — not a legacy v1 column (absent in orphan schema)."""
    if behavior == "localized_absorption":
        return "ABSORPTION_TRANSFER_APPROX"
    if behavior == "localized_distribution":
        return "DISTRIBUTION_TRANSFER_APPROX"
    return "NEUTRAL_BODY_NO_TRANSFER"


def _effort_result_support(behavior: str, concentration: float) -> str:
    """Research support flag derived from localization intensity."""
    if behavior == "body_participation":
        return "BODY_EFFORT_ONLY"
    if concentration >= 0.69:  # RATIO_WICK / 1.0 ≈ wick path
        return "WICK_LOCALIZATION_SUPPORT"
    return "LOCALIZATION_SUPPORT_WEAK"


def _latest_completed_tip(structure: pd.DataFrame, now: pd.Timestamp) -> pd.Timestamp | None:
    if len(structure) == 0:
        return None
    # candle_structure timestamps are bar opens; completed when open+15m <= now.
    opens = pd.to_datetime(structure["timestamp"], utc=True)
    closes = opens + pd.Timedelta(seconds=BAR_SECONDS)
    eligible = structure.loc[closes <= now]
    if len(eligible) == 0:
        return None
    return pd.Timestamp(pd.to_datetime(eligible["timestamp"], utc=True).max())


def build_shadow_frame(
    source: Path = DEFAULT_SOURCE,
    *,
    limit: int | None = None,
    now: pd.Timestamp | datetime | None = None,
    exclude_forming: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not source.exists():
        return pd.DataFrame(), {"status": "SOURCE_MISSING", "source": str(source)}

    structure = pd.read_parquet(source)
    if len(structure) == 0:
        return pd.DataFrame(), {"status": "SOURCE_EMPTY", "source": str(source)}

    structure = structure.copy()
    structure["timestamp"] = pd.to_datetime(structure["timestamp"], utc=True, errors="coerce")
    structure = structure.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    calc_now = pd.Timestamp(now or datetime.now(timezone.utc))
    if calc_now.tzinfo is None:
        calc_now = calc_now.tz_localize("UTC")
    else:
        calc_now = calc_now.tz_convert("UTC")

    tip = _latest_completed_tip(structure, calc_now)
    if tip is None:
        return pd.DataFrame(), {
            "status": "NO_COMPLETED_CANDLES",
            "source": str(source),
            "calculation_timestamp": calc_now.isoformat().replace("+00:00", "Z"),
        }

    if exclude_forming:
        structure = structure[structure["timestamp"] <= tip].copy()

    if limit is not None and limit > 0:
        structure = structure.iloc[-int(limit) :].copy()

    schema_hash = input_schema_hash()
    rows: list[dict[str, Any]] = []
    skipped = 0
    future = 0
    for _, row in structure.iterrows():
        if any(field not in row.index or pd.isna(row[field]) for field in REQUIRED):
            skipped += 1
            continue
        open_ts = pd.Timestamp(row["timestamp"])
        if open_ts.tzinfo is None:
            open_ts = open_ts.tz_localize("UTC")
        else:
            open_ts = open_ts.tz_convert("UTC")
        close_ts = open_ts + pd.Timedelta(seconds=BAR_SECONDS)
        if close_ts > calc_now:
            future += 1
            continue

        base = localize_bar(row)
        behavior = str(base["behavior"])
        zone_low = float(base["zone_low"])
        zone_high = float(base["zone_high"])
        concentration = float(base["volume_concentration"])
        sid = shadow_row_id(source_timestamp=open_ts, schema_hash=schema_hash)
        candle_hash = hashlib.sha256(
            "|".join(
                str(row[c])
                for c in ("timestamp", "open", "high", "low", "close", "volume", "spread")
            ).encode("utf-8")
        ).hexdigest()[:16]

        rows.append(
            {
                "shadow_row_id": sid,
                "source_timestamp": open_ts,
                "source_timeframe": SOURCE_TIMEFRAME,
                "source_candle_open": open_ts,
                "source_candle_close": close_ts,
                # Legacy field names preserved
                "estimated_local_volume": float(base["estimated_local_volume"]),
                "total_volume": float(base["total_volume"]),
                "localized_volume_ratio": float(base["localized_volume_ratio"]),
                "volume_concentration": concentration,
                "behavior": behavior,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "zone_width": float(base["zone_width"]),
                "lower_rejection": bool(base["lower_rejection"]),
                "upper_rejection": bool(base["upper_rejection"]),
                # Additive aliases / research fields
                "localized_behavior": behavior,
                "zone_lower": zone_low,
                "zone_middle": (zone_low + zone_high) / 2.0,
                "zone_upper": zone_high,
                "dominant_zone": _dominant_zone(behavior),
                "inventory_transfer_state": _inventory_transfer_state(behavior),
                "effort_result_localization_support": _effort_result_support(
                    behavior, concentration
                ),
                "algorithm_version": ALGORITHM_VERSION,
                "input_schema_hash": schema_hash,
                "input_tip_at_run": tip,
                "calculation_timestamp": calc_now,
                "created_at": calc_now,
                "input_candle_hash": candle_hash,
                "source_lineage": "candle_structure_memory|volume_localization_shadow_v1",
            }
        )

    frame = pd.DataFrame(rows)
    duplicates = 0
    if len(frame):
        before = len(frame)
        frame = frame.drop_duplicates(subset=["shadow_row_id"], keep="last").reset_index(drop=True)
        frame = frame.sort_values("source_timestamp").reset_index(drop=True)
        duplicates = before - len(frame)

    meta = {
        "status": "OK",
        "source": str(source),
        "input_rows": int(len(structure)),
        "output_rows": int(len(frame)),
        "skipped_invalid": int(skipped),
        "future_timestamps": int(future),
        "duplicates": int(duplicates),
        "latest_completed_candle": tip.isoformat().replace("+00:00", "Z"),
        "latest_shadow_row": (
            None
            if not len(frame)
            else pd.Timestamp(frame["source_timestamp"].iloc[-1])
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "algorithm_version": ALGORITHM_VERSION,
        "input_schema_hash": schema_hash,
        "source_timeframe": SOURCE_TIMEFRAME,
        "no_lookahead": True,
        "completed_candles_only": True,
        "calculation_timestamp": calc_now.isoformat().replace("+00:00", "Z"),
    }
    if len(frame):
        tip_ts = tip
        shadow_tip = pd.Timestamp(frame["source_timestamp"].iloc[-1])
        lag_bars = int(round((tip_ts - shadow_tip).total_seconds() / BAR_SECONDS))
        meta["lag_bars"] = lag_bars
        meta["lag_seconds"] = float((tip_ts - shadow_tip).total_seconds())
        meta["shadow_tip_not_ahead"] = bool(shadow_tip <= tip_ts)
    return frame, meta


def historical_parity(
    shadow: pd.DataFrame,
    legacy_path: Path = LEGACY_ORPHAN,
) -> dict[str, Any]:
    out: dict[str, Any] = {"legacy_available": legacy_path.exists()}
    if not legacy_path.exists() or not len(shadow):
        out["status"] = "UNAVAILABLE"
        return out
    leg = pd.read_parquet(legacy_path)
    leg["timestamp"] = pd.to_datetime(leg["timestamp"], utc=True)
    sh = shadow.copy()
    sh["timestamp"] = pd.to_datetime(sh["source_timestamp"], utc=True)
    merged = sh.merge(
        leg[
            [
                "timestamp",
                "estimated_local_volume",
                "volume_concentration",
                "behavior",
                "zone_low",
                "zone_high",
                "zone_width",
                "lower_rejection",
                "upper_rejection",
            ]
        ],
        on="timestamp",
        how="inner",
        suffixes=("_shadow", "_legacy"),
    )
    out["legacy_rows_compared"] = int(len(merged))
    if not len(merged):
        out["status"] = "NO_OVERLAP"
        return out

    def _num(col: str) -> dict[str, float | int]:
        err = (merged[f"{col}_shadow"] - merged[f"{col}_legacy"]).abs()
        exact = int((err < 1e-9).sum())
        return {
            "exact_match_count": exact,
            "exact_match_share": exact / len(merged),
            "max_abs_error": float(err.max()),
            "p50_abs_error": float(err.quantile(0.50)),
            "p95_abs_error": float(err.quantile(0.95)),
            "mean_abs_error": float(err.mean()),
            "mean_rel_error": float(
                (err / (merged[f"{col}_legacy"].abs() + 1e-12)).mean()
            ),
        }

    out["estimated_local_volume"] = _num("estimated_local_volume")
    out["volume_concentration"] = _num("volume_concentration")
    out["zone_low"] = _num("zone_low")
    out["zone_high"] = _num("zone_high")
    out["zone_width"] = _num("zone_width")
    beh_exact = int((merged["behavior_shadow"] == merged["behavior_legacy"]).sum())
    out["behavior"] = {
        "exact_match_count": beh_exact,
        "exact_match_share": beh_exact / len(merged),
        "confusion": {
            str(a): {str(b): int(v) for b, v in row.items()}
            for a, row in pd.crosstab(
                merged["behavior_shadow"], merged["behavior_legacy"]
            )
            .to_dict(orient="index")
            .items()
        },
    }
    out["categorical_parity"] = out["behavior"]["exact_match_share"]
    out["zone_parity"] = min(
        out["zone_low"]["exact_match_share"], out["zone_high"]["exact_match_share"]
    )
    out["status"] = "OK"
    out["parity_ok"] = (
        out["legacy_rows_compared"] >= 5000
        and out["estimated_local_volume"]["exact_match_share"] == 1.0
        and out["volume_concentration"]["exact_match_share"] == 1.0
        and out["zone_parity"] == 1.0
        and out["categorical_parity"] == 1.0
    )
    return out


def build_comparison(
    shadow: pd.DataFrame,
    context_path: Path = FINAL_CONTEXT,
) -> pd.DataFrame:
    if not len(shadow) or not context_path.exists():
        return pd.DataFrame()
    ctx = pd.read_parquet(context_path)
    ctx["timestamp"] = pd.to_datetime(ctx["timestamp"], utc=True)
    sh = shadow[
        [
            "source_timestamp",
            "behavior",
            "dominant_zone",
            "estimated_local_volume",
            "volume_concentration",
        ]
    ].copy()
    sh["timestamp"] = pd.to_datetime(sh["source_timestamp"], utc=True)
    sh = sh.rename(columns={"behavior": "shadow_localized_behavior"})

    want = [
        "timestamp",
        "market_context",
        "location_bias",
        "localized_behavior",
        "effort_result_state",
        "trigger_event",
    ]
    ctx_cols = [c for c in want if c in ctx.columns]
    joined = sh.merge(ctx[ctx_cols], on="timestamp", how="left")

    live_tip = None
    if LEGACY_ORPHAN.exists():
        loc = pd.read_parquet(LEGACY_ORPHAN, columns=["timestamp"])
        if len(loc):
            live_tip = pd.to_datetime(loc["timestamp"], utc=True).max()

    rows = []
    for _, r in joined.iterrows():
        live_lb = r["localized_behavior"] if "localized_behavior" in r.index else None
        live_bias = r["location_bias"] if "location_bias" in r.index else None
        live_effort = r["effort_result_state"] if "effort_result_state" in r.index else None
        shadow_beh = r["shadow_localized_behavior"]
        final_ctx = r["market_context"] if "market_context" in r.index else None
        ts = pd.Timestamp(r["timestamp"])

        live_beh_present = live_lb is not None and pd.notna(live_lb)
        live_bias_present = live_bias is not None and pd.notna(live_bias)

        if live_tip is not None and ts > live_tip and not live_beh_present:
            classification = "LIVE_FIELD_STALE"
            agreement = False
            conflict = False
        elif not live_beh_present and not live_bias_present:
            classification = "LIVE_FIELD_MISSING"
            agreement = False
            conflict = False
        elif live_beh_present and str(live_lb) == str(shadow_beh):
            classification = "EXACT_SEMANTIC_AGREEMENT"
            agreement = True
            conflict = False
        elif live_beh_present and str(live_lb) != str(shadow_beh):
            classification = "SEMANTIC_CONFLICT"
            agreement = False
            conflict = True
        elif live_bias_present:
            classification = "PARTIAL_SEMANTIC_AGREEMENT"
            agreement = False
            conflict = False
        else:
            classification = "NOT_COMPARABLE"
            agreement = False
            conflict = False

        rows.append(
            {
                "source_timestamp": r["source_timestamp"],
                "shadow_dominant_zone": r.get("dominant_zone"),
                "shadow_localized_behavior": shadow_beh,
                "current_location_bias": live_bias,
                "current_localized_behavior": live_lb,
                "current_effort_result_state": live_effort,
                "final_context": final_ctx,
                "semantic_agreement": bool(agreement),
                "semantic_conflict": bool(conflict),
                "missing_live_capability": classification
                in {"LIVE_FIELD_MISSING", "LIVE_FIELD_STALE"},
                "classification": classification,
            }
        )
    return pd.DataFrame(rows)


def run_shadow_once(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    source: Path = DEFAULT_SOURCE,
    limit: int | None = 256,
    include_full_parity: bool = True,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frame, meta = build_shadow_frame(source, limit=limit)
    status: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "component": "volume_localization_shadow",
        "meta": meta,
        "writes_cognition_memories": False,
        "writes_live_memories": False,
        "persistent_daemon": False,
    }

    if include_full_parity:
        full, _ = build_shadow_frame(source, limit=None)
        status["historical_parity"] = historical_parity(full)
    else:
        status["historical_parity"] = historical_parity(frame)

    comparison = build_comparison(frame)
    shadow_path = out_dir / "volume_localization_shadow.parquet"
    comparison_path = out_dir / "volume_localization_shadow_comparison.parquet"
    status_path = out_dir / "volume_localization_shadow_status.json"
    cycles_path = out_dir / "volume_localization_shadow_cycles.jsonl"

    if len(frame):
        # Idempotent rerun check before write
        frame2, _ = build_shadow_frame(source, limit=limit, now=meta.get("calculation_timestamp"))
        status["invariants"] = {
            "deterministic_ids": True,
            "idempotent_rerun": (
                frame["shadow_row_id"].tolist() == frame2["shadow_row_id"].tolist()
                if len(frame2) == len(frame)
                else False
            ),
            "duplicates": meta.get("duplicates", 0),
            "future_timestamps": meta.get("future_timestamps", 0),
            "completed_candles_only": True,
            "no_lookahead": True,
        }
        atomic_parquet_write(frame, str(shadow_path), validate=True, timestamp_col=None)
    else:
        status["invariants"] = {
            "deterministic_ids": True,
            "idempotent_rerun": True,
            "duplicates": 0,
            "future_timestamps": meta.get("future_timestamps", 0),
            "completed_candles_only": True,
            "no_lookahead": True,
        }

    if len(comparison):
        atomic_parquet_write(
            comparison, str(comparison_path), validate=True, timestamp_col=None
        )

    status["output_parquet"] = str(shadow_path)
    status["output_comparison"] = str(comparison_path)
    status["rows"] = int(len(frame))
    status_path.write_text(json.dumps(status, indent=2, default=str) + "\n", encoding="utf-8")

    cycle = {
        "ts": status["generated_at"],
        "event": "SHADOW_ONESHOT",
        "rows": int(len(frame)),
        "latest_shadow_row": meta.get("latest_shadow_row"),
        "latest_completed_candle": meta.get("latest_completed_candle"),
        "lag_bars": meta.get("lag_bars"),
        "parity_ok": status.get("historical_parity", {}).get("parity_ok"),
    }
    with cycles_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(cycle, default=str) + "\n")
    status["output_status"] = str(status_path)
    status["output_cycles"] = str(cycles_path)
    return status


def watch_natural_bars(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    source: Path = DEFAULT_SOURCE,
    target_bars: int = 3,
    timeout_s: float = 1200.0,
    poll_s: float = 15.0,
    limit: int = 256,
) -> dict[str, Any]:
    """Bounded watcher — terminates automatically; not a persistent daemon."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cycles_path = out_dir / "volume_localization_shadow_cycles.jsonl"
    started = time.monotonic()
    baseline_tip = None
    if source.exists():
        s = pd.read_parquet(source, columns=["timestamp"])
        if len(s):
            baseline_tip = pd.to_datetime(s["timestamp"], utc=True).max()

    observed: list[dict[str, Any]] = []
    while time.monotonic() - started < timeout_s and len(observed) < target_bars:
        frame, meta = build_shadow_frame(source, limit=limit)
        tip = meta.get("latest_completed_candle")
        tip_ts = pd.Timestamp(tip) if tip else None
        if tip_ts is not None and (baseline_tip is None or tip_ts > baseline_tip):
            # new completed tip(s)
            new_rows = frame[pd.to_datetime(frame["source_timestamp"], utc=True) > baseline_tip] if baseline_tip is not None else frame.tail(1)
            for _, r in new_rows.iterrows():
                observed.append(
                    {
                        "source_timestamp": str(r["source_timestamp"]),
                        "input_candle_hash": r.get("input_candle_hash"),
                        "estimated_local_volume": float(r["estimated_local_volume"]),
                        "volume_concentration": float(r["volume_concentration"]),
                        "dominant_zone": r.get("dominant_zone"),
                        "localized_behavior": r.get("behavior"),
                        "inventory_transfer_state": r.get("inventory_transfer_state"),
                        "write_timestamp": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "duplicate_status": "unique",
                    }
                )
                if len(observed) >= target_bars:
                    break
            baseline_tip = tip_ts
            # Persist latest bounded shadow
            run_shadow_once(
                out_dir=out_dir, source=source, limit=limit, include_full_parity=False
            )
            with cycles_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ts": datetime.now(timezone.utc)
                            .isoformat()
                            .replace("+00:00", "Z"),
                            "event": "NATURAL_BAR",
                            "tip": tip,
                            "observed_count": len(observed),
                        },
                        default=str,
                    )
                    + "\n"
                )
        time.sleep(poll_s)

    result = {
        "status": (
            "VOLUME_LOCALIZATION_SHADOW_VERIFIED"
            if len(observed) >= target_bars
            else "VOLUME_LOCALIZATION_SHADOW_READY_PENDING_MORE_NATURAL_BARS"
        ),
        "natural_completed_bars_observed": len(observed),
        "target_bars": target_bars,
        "observed": observed,
        "watcher_terminated": True,
        "persistent_daemon": False,
    }
    (out_dir / "volume_localization_shadow_natural.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return result
