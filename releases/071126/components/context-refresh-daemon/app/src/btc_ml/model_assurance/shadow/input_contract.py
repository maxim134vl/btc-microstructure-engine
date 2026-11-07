"""Shadow input contract — same causal slice as active LIVE1A provisional state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from btc_ml.model_assurance.toxic_box.common import (
    canonical_json,
    load_json,
    sha256_text,
    utc_now_iso,
)

TIMEFRAMES = ("M15", "M30", "H1", "H4")


def cognition_health_path(repo_root: Path) -> Path:
    return repo_root / "data" / "runtime" / "intrabar_cognition_health.json"


def external_data_summary_path(repo_root: Path) -> Path:
    return (
        repo_root
        / "data"
        / "model_assurance"
        / "toxic_box"
        / "external_data"
        / "snapshots"
        / "latest_summary.json"
    )


def build_feature_payload_from_cognition(
    cognition: dict[str, Any] | None,
    *,
    external_status: str | None = None,
) -> list[dict[str, Any]]:
    """Narrow reader over LIVE1A provisional health/state — does not modify LIVE1A."""
    if not cognition:
        return []
    provisional = cognition.get("last_provisional_eval") or {}
    partial = cognition.get("partial_bars") or {}
    out: list[dict[str, Any]] = []
    for tf in TIMEFRAMES:
        bar = partial.get(tf) if isinstance(partial, dict) else None
        prov = provisional.get(tf) if isinstance(provisional, dict) else None
        if not isinstance(bar, dict):
            continue
        mono = bar.get("causal_cutoff_monotonic_ns")
        if mono is None:
            continue
        payload = {
            "timeframe": tf,
            "causal_cutoff_timestamp": bar.get("causal_cutoff_timestamp"),
            "causal_cutoff_monotonic_ns": mono,
            "partial_bar": {
                k: bar.get(k)
                for k in (
                    "open",
                    "high",
                    "low",
                    "close",
                    "last",
                    "volume",
                    "delta",
                    "trade_count_so_far",
                    "evaluation_mode",
                    "is_closed",
                    "bar_open_timestamp",
                )
                if k in bar
            },
            "provisional": dict(prov) if isinstance(prov, dict) else {},
            "external_data_availability": external_status,
        }
        out.append(payload)
    return out


def shadow_input_id(
    *,
    candidate_registry_record_id: str,
    timeframe: str,
    causal_cutoff_monotonic_ns: Any,
    feature_payload_hash: str,
) -> str:
    return "SHIN_" + sha256_text(
        canonical_json(
            {
                "candidate_registry_record_id": candidate_registry_record_id,
                "timeframe": timeframe,
                "causal_cutoff_monotonic_ns": causal_cutoff_monotonic_ns,
                "feature_payload_hash": feature_payload_hash,
            }
        )
    )[:32]


def build_shadow_input(
    *,
    active: dict[str, Any],
    candidate: dict[str, Any],
    timeframe: str,
    causal_cutoff_timestamp: str | None,
    causal_cutoff_monotonic_ns: Any,
    feature_payload: dict[str, Any],
    feature_schema_version: str | None = None,
    data_schema_version: str | None = None,
) -> dict[str, Any]:
    payload_hash = sha256_text(canonical_json(feature_payload))
    return {
        "shadow_input_id": shadow_input_id(
            candidate_registry_record_id=str(candidate.get("registry_record_id")),
            timeframe=timeframe,
            causal_cutoff_monotonic_ns=causal_cutoff_monotonic_ns,
            feature_payload_hash=payload_hash,
        ),
        "candidate_registry_record_id": candidate.get("registry_record_id"),
        "active_registry_record_id": active.get("registry_record_id"),
        "timeframe": timeframe,
        "causal_cutoff_timestamp": causal_cutoff_timestamp,
        "causal_cutoff_monotonic_ns": causal_cutoff_monotonic_ns,
        "feature_schema_version": feature_schema_version
        or candidate.get("feature_schema_version")
        or active.get("feature_schema_version"),
        "data_schema_version": data_schema_version
        or candidate.get("data_schema_version")
        or active.get("data_schema_version"),
        "feature_payload_hash": payload_hash,
        "feature_payload": feature_payload,
        "created_at": utc_now_iso(),
    }


def collect_shadow_inputs(
    *,
    repo_root: Path,
    active: dict[str, Any],
    candidate: dict[str, Any],
    seen_ids: set[str],
) -> list[dict[str, Any]]:
    cognition = load_json(cognition_health_path(repo_root))
    ext = load_json(external_data_summary_path(repo_root)) or {}
    external_status = str(ext.get("status") or "")
    rows = build_feature_payload_from_cognition(cognition, external_status=external_status)
    out: list[dict[str, Any]] = []
    for row in rows:
        shadow_in = build_shadow_input(
            active=active,
            candidate=candidate,
            timeframe=str(row["timeframe"]),
            causal_cutoff_timestamp=row.get("causal_cutoff_timestamp"),
            causal_cutoff_monotonic_ns=row.get("causal_cutoff_monotonic_ns"),
            feature_payload=row,
        )
        sid = str(shadow_in["shadow_input_id"])
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        out.append(shadow_in)
    return out
