import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from parquet_utils import atomic_parquet_write, safe_read_parquet
from runtime_lineage import parquet_mtime

ALIGNMENT_AUDIT_PATH = "runtime_cognition_alignment_audit.parquet"

ALIGNMENT_STATUS_VALID = "VALID"
ALIGNMENT_STATUS_STALE = "STALE"
ALIGNMENT_STATUS_MISSING = "MISSING"
ALIGNMENT_STATUS_INVALID = "INVALID"

DEFAULT_STALE_SECONDS = 3600


def log_runtime_warning(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[RUNTIME WARNING {timestamp}] {message}")


def log_runtime_error(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[RUNTIME ERROR {timestamp}] {message}")


def _safe_float(value) -> Optional[float]:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_alignment_score(
    alignment_score,
    event_timestamp=None,
    reference_timestamp=None,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> str:
    score = _safe_float(alignment_score)

    if score is None:
        return ALIGNMENT_STATUS_MISSING

    if score < 0.0 or score > 1.0:
        return ALIGNMENT_STATUS_INVALID

    if event_timestamp is not None and reference_timestamp is not None:
        event_ts = pd.to_datetime(event_timestamp)
        reference_ts = pd.to_datetime(reference_timestamp)
        drift_seconds = abs((event_ts - reference_ts).total_seconds())
        if drift_seconds > stale_seconds:
            return ALIGNMENT_STATUS_STALE

    return ALIGNMENT_STATUS_VALID


def enrich_alignment_status(
    cognition: pd.DataFrame,
    synthesis: Optional[pd.DataFrame] = None,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> pd.DataFrame:
    output = cognition.copy()

    if "alignment_score" not in output.columns:
        output["alignment_score"] = pd.NA

    if synthesis is not None and len(synthesis) > 0:
        if "alignment_score" not in synthesis.columns:
            synthesis = synthesis.copy()
            synthesis["alignment_score"] = pd.NA

        merged = output.merge(
            synthesis[
                [
                    "timestamp",
                    "alignment_score",
                ]
            ].rename(
                columns={
                    "alignment_score": "alignment_score_reference",
                }
            ),
            on="timestamp",
            how="left",
        )

        missing_mask = merged["alignment_score"].isna()
        merged.loc[
            missing_mask,
            "alignment_score",
        ] = merged.loc[
            missing_mask,
            "alignment_score_reference",
        ]

        reference_ts = merged["timestamp"]
        reference_alignment = merged["alignment_score_reference"]
    else:
        merged = output.copy()
        merged["alignment_score_reference"] = pd.NA
        reference_ts = merged.get("timestamp")
        reference_alignment = pd.NA

    statuses = []
    synthesis_by_ts = {}
    if synthesis is not None and len(synthesis) > 0:
        synthesis_by_ts = {
            pd.to_datetime(row["timestamp"]): row.get("alignment_score")
            for _, row in synthesis.iterrows()
        }
        synthesis_latest = max(synthesis_by_ts.keys())
    else:
        synthesis_latest = None

    for _, row in merged.iterrows():
        event_ts = pd.to_datetime(row.get("timestamp"))
        status = classify_alignment_score(row.get("alignment_score"))

        if status == ALIGNMENT_STATUS_VALID and synthesis_by_ts:
            reference_score = synthesis_by_ts.get(event_ts)
            if reference_score is not None:
                current_score = _safe_float(row.get("alignment_score"))
                reference_value = _safe_float(reference_score)
                if (
                    current_score is not None
                    and reference_value is not None
                    and abs(current_score - reference_value) > 1e-9
                ):
                    status = ALIGNMENT_STATUS_STALE
            elif event_ts not in synthesis_by_ts:
                status = ALIGNMENT_STATUS_STALE

        if (
            status == ALIGNMENT_STATUS_VALID
            and synthesis_latest is not None
            and event_ts == pd.to_datetime(merged["timestamp"]).max()
        ):
            drift_seconds = (synthesis_latest - event_ts).total_seconds()
            if drift_seconds > stale_seconds:
                status = ALIGNMENT_STATUS_STALE

        statuses.append(status)

    merged["alignment_status"] = statuses

    return merged


def export_alignment_audit(cognition: pd.DataFrame) -> pd.DataFrame:
    if "alignment_status" not in cognition.columns:
        return pd.DataFrame()

    audit = cognition[
        cognition["alignment_status"].isin(
            [
                ALIGNMENT_STATUS_MISSING,
                ALIGNMENT_STATUS_INVALID,
                ALIGNMENT_STATUS_STALE,
            ]
        )
    ].copy()

    if len(audit) == 0:
        return audit

    audit["audit_recorded_at"] = pd.Timestamp.utcnow()
    atomic_parquet_write(audit, ALIGNMENT_AUDIT_PATH)
    return audit


def compute_drift_metrics(
    cognition_path: str = "runtime_cognition_memory.parquet",
    synthesis_path: str = "multi_timeframe_synthesis.parquet",
    reinforcement_path: str = "auction_reinforcement_memory.parquet",
    candle_structure_path: str = "candle_structure_memory.parquet",
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> Tuple[Dict[str, object], List[str]]:
    warnings: List[str] = []
    metrics: Dict[str, object] = {
        "checked_at": pd.Timestamp.utcnow(),
        "stale_threshold_seconds": stale_seconds,
    }

    cognition = safe_read_parquet(cognition_path)
    synthesis = safe_read_parquet(synthesis_path)
    reinforcement = safe_read_parquet(reinforcement_path)
    candle_structure = safe_read_parquet(candle_structure_path)

    metrics["cognition_rows"] = len(cognition)
    metrics["synthesis_rows"] = len(synthesis)
    metrics["reinforcement_rows"] = len(reinforcement)

    if len(cognition) > 0:
        cognition_ts = pd.to_datetime(cognition["timestamp"])
        metrics["cognition_latest_event_timestamp"] = cognition_ts.max()
        if not cognition_ts.is_monotonic_increasing:
            warnings.append("Cognition timestamps are out of order")
            metrics["cognition_out_of_order"] = True
        else:
            metrics["cognition_out_of_order"] = False

    if len(synthesis) > 0:
        metrics["synthesis_latest_event_timestamp"] = pd.to_datetime(
            synthesis["timestamp"]
        ).max()

    if len(cognition) > 0 and len(synthesis) > 0:
        cognition_latest = pd.to_datetime(cognition["timestamp"]).max()
        synthesis_latest = pd.to_datetime(synthesis["timestamp"]).max()
        event_lag = (synthesis_latest - cognition_latest).total_seconds()
        metrics["cognition_vs_synthesis_event_lag_seconds"] = event_lag
        if abs(event_lag) > stale_seconds:
            warnings.append(
                "Cognition event timestamp diverges from synthesis latest event"
            )

    cognition_mtime = parquet_mtime(cognition_path)
    synthesis_mtime = parquet_mtime(synthesis_path)
    reinforcement_mtime = parquet_mtime(reinforcement_path)

    metrics["cognition_parquet_mtime"] = cognition_mtime
    metrics["synthesis_parquet_mtime"] = synthesis_mtime
    metrics["reinforcement_parquet_mtime"] = reinforcement_mtime

    if cognition_mtime and synthesis_mtime:
        propagation_lag = cognition_mtime - synthesis_mtime
        metrics["cognition_vs_synthesis_propagation_lag_seconds"] = propagation_lag
        if propagation_lag < -5:
            warnings.append(
                "runtime_cognition_memory.parquet is older than synthesis parquet"
            )

    if len(reinforcement) > 0 and len(cognition) > 0:
        reinforcement_latest = pd.to_datetime(reinforcement["timestamp"]).max()
        cognition_latest = pd.to_datetime(cognition["timestamp"]).max()
        metrics["reinforcement_latest_timestamp"] = reinforcement_latest
        reinforcement_lag = (
            cognition_latest - reinforcement_latest
        ).total_seconds()
        metrics["cognition_vs_reinforcement_lag_seconds"] = reinforcement_lag
        if reinforcement_lag > stale_seconds:
            warnings.append("Reinforcement memory is stale relative to cognition")

    if len(candle_structure) > 0 and len(cognition) > 0:
        candle_latest = pd.to_datetime(candle_structure["timestamp"]).max()
        cognition_latest = pd.to_datetime(cognition["timestamp"]).max()
        candle_lag = (candle_latest - cognition_latest).total_seconds()
        metrics["candle_structure_vs_cognition_lag_seconds"] = candle_lag
        if candle_lag > stale_seconds:
            warnings.append("Cognition is stale relative to candle structure")

    metrics["warning_count"] = len(warnings)
    return metrics, warnings
