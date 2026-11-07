"""Causal Stage-2 cognition feature enrichment for SHADOW-EQCORR1.1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import EXPECTED_ACTIVE_FP, EXPECTED_EPOCH, FIELD_NOT_AVAILABLE, POLICY_IDS
from .features import parse_ts, utc_now

# Feature statuses
STATUS_VALID = "VALID"
STATUS_STALE = "STALE"
STATUS_MISSING = "MISSING"
STATUS_NOT_CANONICALLY_AVAILABLE = "NOT_CANONICALLY_AVAILABLE"
STATUS_AMBIGUOUS_TIMESTAMP = "AMBIGUOUS_TIMESTAMP"
STATUS_WRONG_TIMEFRAME = "WRONG_TIMEFRAME"
STATUS_FUTURE_ROW_REJECTED = "FUTURE_ROW_REJECTED"
STATUS_NOT_AVAILABLE_AT_DECISION_TIME = "NOT_AVAILABLE_AT_DECISION_TIME"
STATUS_HISTORICAL_NOT_RECOVERABLE = "HISTORICAL_CAUSAL_FEATURE_NOT_RECOVERABLE"

RESEARCH_FIELDS = (
    "synthesis_state",
    "trigger_event",
    "persistence",
    "persistence_score",
    "structural_rank",
    "alignment_score",
    "alignment_status",
    "location_bias",
    "auction_state",
    "reinforcement_state",
    "conviction_strength",
    "auction_regime",
    "absorption_probability",
    "distribution_probability",
    "conviction_probability",
    "unfinished_auction",
    "localized_behavior",
    "effort_result_state",
    "volume_event",
    "validation_state",
    "validation_reason",
)


@dataclass(frozen=True)
class SourceSpec:
    artifact_id: str
    relative_path: str
    producer: str
    timestamp_field: str
    timeframe_field: str | None
    timeframe_semantics: str  # GLOBAL_NO_TF_COLUMN | PER_TIMEFRAME_SOURCE_COLUMN
    write_mode: str
    freshness_budget_seconds: float | None
    columns: tuple[str, ...]
    causal_asof_possible: bool


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        artifact_id="runtime_cognition_memory",
        relative_path="data/cognition/runtime_cognition_memory.parquet",
        producer="runtime_cognition_engine_v1.py / canonical_pipeline_loop",
        timestamp_field="timestamp",
        timeframe_field=None,
        timeframe_semantics="GLOBAL_NO_TF_COLUMN",
        write_mode="append_event_log",
        freshness_budget_seconds=86400.0,
        columns=(
            "synthesis_state",
            "trigger_event",
            "persistence",
            "persistence_score",
            "structural_rank",
            "alignment_score",
            "location_bias",
            "auction_state",
        ),
        causal_asof_possible=True,
    ),
    SourceSpec(
        artifact_id="multi_timeframe_synthesis",
        relative_path="data/cognition/multi_timeframe_synthesis.parquet",
        producer="stage2_cognition_runtime_v1.py / canonical_pipeline_loop",
        timestamp_field="timestamp",
        timeframe_field=None,
        timeframe_semantics="GLOBAL_NO_TF_COLUMN",
        write_mode="append_event_log",
        freshness_budget_seconds=86400.0,
        columns=(
            "synthesis_state",
            "trigger_event",
            "persistence",
            "persistence_score",
            "structural_rank",
            "alignment_score",
            "location_bias",
        ),
        causal_asof_possible=True,
    ),
    SourceSpec(
        artifact_id="auction_reinforcement_memory",
        relative_path="data/reinforcement/auction_reinforcement_memory.parquet",
        producer="auction_reinforcement_engine_v1.py / canonical_pipeline_loop",
        timestamp_field="timestamp",
        timeframe_field=None,
        timeframe_semantics="GLOBAL_NO_TF_COLUMN",
        write_mode="append",
        freshness_budget_seconds=1800.0,
        columns=(
            "alignment_status",
            "auction_state",
            "localized_behavior",
            "effort_result_state",
        ),
        causal_asof_possible=True,
    ),
    SourceSpec(
        artifact_id="probabilistic_auction_memory",
        relative_path="data/probabilistic/probabilistic_auction_memory.parquet",
        producer="probabilistic_auction_engine_v1.py / canonical_pipeline_loop",
        timestamp_field="timestamp",
        timeframe_field=None,
        timeframe_semantics="GLOBAL_NO_TF_COLUMN",
        write_mode="append",
        freshness_budget_seconds=1800.0,
        columns=(
            "auction_regime",
            "absorption_probability",
            "distribution_probability",
            "conviction_probability",
            "alignment_status",
            "trigger_event",
        ),
        causal_asof_possible=True,
    ),
    SourceSpec(
        artifact_id="auction_synthesis_memory",
        relative_path="data/reinforcement/auction_synthesis_memory.parquet",
        producer="auction_synthesis_engine_v1.py / canonical_pipeline_loop",
        timestamp_field="timestamp",
        timeframe_field=None,
        timeframe_semantics="GLOBAL_NO_TF_COLUMN",
        write_mode="append",
        freshness_budget_seconds=3600.0,
        columns=("auction_state",),
        causal_asof_possible=True,
    ),
    SourceSpec(
        artifact_id="volume_response_state",
        relative_path="data/cognition/volume_response_state.parquet",
        producer="volume_response_engine_v1.py / canonical_pipeline_loop",
        timestamp_field="timestamp",
        timeframe_field="source_timeframe",
        timeframe_semantics="PER_TIMEFRAME_SOURCE_COLUMN",
        write_mode="append",
        freshness_budget_seconds=1800.0,
        columns=(
            "unfinished_auction",
            "localized_behavior",
            "effort_result_state",
            "volume_event",
        ),
        causal_asof_possible=True,
    ),
)

# Preferred source per research field (exact canonical column names only).
FIELD_SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {
    "synthesis_state": ("runtime_cognition_memory", "multi_timeframe_synthesis"),
    "trigger_event": ("runtime_cognition_memory", "multi_timeframe_synthesis", "probabilistic_auction_memory"),
    "persistence": ("runtime_cognition_memory", "multi_timeframe_synthesis"),
    "persistence_score": ("runtime_cognition_memory", "multi_timeframe_synthesis"),
    "structural_rank": ("runtime_cognition_memory", "multi_timeframe_synthesis"),
    "alignment_score": ("runtime_cognition_memory", "multi_timeframe_synthesis"),
    "alignment_status": ("auction_reinforcement_memory", "probabilistic_auction_memory"),
    "location_bias": ("runtime_cognition_memory", "multi_timeframe_synthesis"),
    "auction_state": ("runtime_cognition_memory", "auction_reinforcement_memory", "auction_synthesis_memory"),
    "reinforcement_state": (),  # column does not exist under this name
    "conviction_strength": (),  # column does not exist under this name
    "auction_regime": ("probabilistic_auction_memory",),
    "absorption_probability": ("probabilistic_auction_memory",),
    "distribution_probability": ("probabilistic_auction_memory",),
    "conviction_probability": ("probabilistic_auction_memory",),
    "unfinished_auction": ("volume_response_state",),
    "localized_behavior": ("volume_response_state", "auction_reinforcement_memory"),
    "effort_result_state": ("volume_response_state", "auction_reinforcement_memory"),
    "volume_event": ("volume_response_state",),
    "validation_state": (),
    "validation_reason": (),
}


def policy_manifest_fingerprint(manifest: dict[str, Any] | None = None) -> str:
    payload = manifest or {
        "mode": "OBSERVE_ONLY",
        "enforcement_enabled": False,
        "quality_scoring_enabled": False,
        "policy_ids": list(POLICY_IDS),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _iso(dt: datetime | pd.Timestamp | None) -> str | None:
    if dt is None or (isinstance(dt, float) and pd.isna(dt)):
        return None
    if isinstance(dt, pd.Timestamp):
        if pd.isna(dt):
            return None
        dt = dt.to_pydatetime()
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat().replace("+00:00", "Z")


def _to_python(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, pd.Timestamp):
        return _iso(value)
    return value


def audit_cognition_sources(*, repo: Path) -> list[dict[str, Any]]:
    """Fact-based source audit from live parquet + meta (not docs)."""
    out: list[dict[str, Any]] = []
    for spec in SOURCE_SPECS:
        path = repo / spec.relative_path
        meta_path = Path(str(path) + ".meta.json")
        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        row: dict[str, Any] = {
            "path": str(path.relative_to(repo)) if path.exists() else spec.relative_path,
            "producer": meta.get("writer_entrypoint") or spec.producer,
            "write_mode": meta.get("write_mode") or spec.write_mode,
            "append_only": str(meta.get("write_mode") or spec.write_mode).startswith("append"),
            "rewritten": False,
            "timeframe_semantics": spec.timeframe_semantics,
            "row_timestamp_field": spec.timestamp_field,
            "freshness_budget_seconds": spec.freshness_budget_seconds,
            "causal_asof_join_possible": spec.causal_asof_possible,
            "exists": path.exists(),
        }
        if not path.exists():
            row["available_columns"] = []
            row["latest_timestamp"] = None
            row["freshness"] = "FILE_MISSING"
            out.append(row)
            continue
        df = pd.read_parquet(path)
        row["available_columns"] = list(df.columns)
        row["row_count"] = int(len(df))
        ts = pd.to_datetime(df[spec.timestamp_field], utc=True, errors="coerce")
        latest = ts.max()
        row["latest_timestamp"] = _iso(latest)
        if pd.notna(latest):
            age = (pd.Timestamp.now(tz="UTC") - latest).total_seconds()
            row["freshness_age_seconds"] = float(age)
            budget = spec.freshness_budget_seconds
            if budget is None:
                row["freshness"] = f"AGE_ONLY:{age:.1f}s"
            elif age <= budget:
                row["freshness"] = "WITHIN_BUDGET"
            else:
                row["freshness"] = "BEYOND_BUDGET"
        else:
            row["freshness"] = "AMBIGUOUS_TIMESTAMP"
        if spec.timeframe_field and spec.timeframe_field in df.columns:
            row["timeframe_values"] = {
                str(k): int(v) for k, v in df[spec.timeframe_field].fillna("NULL").astype(str).value_counts().items()
            }
        out.append(row)
    return out


class CausalFeatureEnricher:
    """Read-only backward as-of enrichment against cognition parquets."""

    def __init__(self, *, repo: Path) -> None:
        self.repo = repo
        self._frames: dict[str, pd.DataFrame] = {}
        self.future_row_rejected_count = 0
        self.wrong_timeframe_rejected_count = 0
        self.ambiguous_timestamp_count = 0

    def _load(self, spec: SourceSpec) -> pd.DataFrame | None:
        if spec.artifact_id in self._frames:
            return self._frames[spec.artifact_id]
        path = self.repo / spec.relative_path
        if not path.exists():
            self._frames[spec.artifact_id] = pd.DataFrame()
            return self._frames[spec.artifact_id]
        df = pd.read_parquet(path)
        if spec.timestamp_field not in df.columns:
            self.ambiguous_timestamp_count += 1
            self._frames[spec.artifact_id] = pd.DataFrame()
            return self._frames[spec.artifact_id]
        out = df.copy()
        out["_asof_ts"] = pd.to_datetime(out[spec.timestamp_field], utc=True, errors="coerce")
        if spec.timeframe_field and spec.timeframe_field in out.columns:
            out["_tf"] = out[spec.timeframe_field].astype(str).str.upper()
        self._frames[spec.artifact_id] = out
        return out

    def backward_asof(
        self,
        *,
        spec: SourceSpec,
        decision_timestamp: str,
        timeframe: str,
    ) -> dict[str, Any]:
        """Select last same-TF (when available) row with source_ts <= decision_ts."""
        decision_dt = parse_ts(decision_timestamp)
        base = {
            "source_artifact": spec.artifact_id,
            "source_path": spec.relative_path,
            "decision_timestamp": decision_timestamp,
            "join_method": "BACKWARD_ASOF",
            "timeframe_semantics": spec.timeframe_semantics,
            "same_timeframe_match": False,
            "source_row_timestamp": None,
            "age_seconds_at_decision": None,
            "max_input_timestamp": None,
            "row": None,
            "status": STATUS_MISSING,
        }
        if decision_dt is None:
            self.ambiguous_timestamp_count += 1
            base["status"] = STATUS_AMBIGUOUS_TIMESTAMP
            return base

        df = self._load(spec)
        if df is None or df.empty:
            base["status"] = STATUS_MISSING
            return base

        eligible = df[df["_asof_ts"].notna()].copy()
        # Explicit future rejection accounting: count rows that would have been selected by nearest-forward.
        future_mask = eligible["_asof_ts"] > pd.Timestamp(decision_dt)
        future_n = int(future_mask.sum())
        if future_n:
            # Count only if a future tip exists (diagnostic); do not select it.
            self.future_row_rejected_count += 1

        eligible = eligible[eligible["_asof_ts"] <= pd.Timestamp(decision_dt)]
        if spec.timeframe_field:
            tf = str(timeframe).upper()
            if "_tf" not in eligible.columns:
                self.ambiguous_timestamp_count += 1
                base["status"] = STATUS_AMBIGUOUS_TIMESTAMP
                return base
            # Reject wrong TF / null TF rows from consideration
            wrong = eligible[eligible["_tf"] != tf]
            if len(wrong):
                self.wrong_timeframe_rejected_count += int(len(wrong) > 0)
            eligible = eligible[eligible["_tf"] == tf]
            base["same_timeframe_match"] = True
            if eligible.empty:
                base["status"] = STATUS_MISSING
                base["same_timeframe_match"] = False
                # If only other TF rows existed at/before decision, surface WRONG_TIMEFRAME for join attempt
                prior_any = df[(df["_asof_ts"].notna()) & (df["_asof_ts"] <= pd.Timestamp(decision_dt))]
                if not prior_any.empty and "_tf" in prior_any.columns and (prior_any["_tf"] == tf).sum() == 0:
                    if prior_any["_tf"].notna().any():
                        base["status"] = STATUS_WRONG_TIMEFRAME
                return base
        else:
            base["same_timeframe_match"] = False  # no TF column — global series

        if eligible.empty:
            base["status"] = STATUS_MISSING
            return base

        # Last row by timestamp (stable: sort then take last)
        eligible = eligible.sort_values("_asof_ts")
        chosen = eligible.iloc[-1]
        src_ts = chosen["_asof_ts"]
        # Safety: never allow future
        if src_ts > pd.Timestamp(decision_dt):
            self.future_row_rejected_count += 1
            base["status"] = STATUS_FUTURE_ROW_REJECTED
            return base

        age = (pd.Timestamp(decision_dt) - src_ts).total_seconds()
        row_dict = {c: _to_python(chosen[c]) for c in chosen.index if not str(c).startswith("_")}
        base.update(
            {
                "source_row_timestamp": _iso(src_ts),
                "age_seconds_at_decision": float(age),
                "max_input_timestamp": _iso(src_ts),
                "row": row_dict,
                "status": STATUS_VALID,
            }
        )
        return base

    def _feature_from_join(
        self,
        *,
        field: str,
        join: dict[str, Any],
        spec: SourceSpec,
    ) -> dict[str, Any]:
        value = None
        status = join.get("status") or STATUS_MISSING
        age = join.get("age_seconds_at_decision")
        if status == STATUS_VALID and isinstance(join.get("row"), dict):
            raw = join["row"].get(field)
            if raw is None or raw is FIELD_NOT_AVAILABLE or (isinstance(raw, float) and pd.isna(raw)):
                value = None
                status = STATUS_MISSING
            else:
                value = raw
                budget = spec.freshness_budget_seconds
                if budget is not None and age is not None and float(age) > float(budget):
                    status = STATUS_STALE
                else:
                    status = STATUS_VALID
        return {
            f"{field}_value": value,
            f"{field}_status": status,
            f"{field}_age_seconds_at_decision": age,
            f"{field}_source_artifact": join.get("source_artifact"),
            f"{field}_source_row_timestamp": join.get("source_row_timestamp"),
            f"{field}_join_method": "BACKWARD_ASOF",
            f"{field}_same_timeframe_match": join.get("same_timeframe_match"),
        }

    def enrich_candidate(
        self,
        *,
        candidate: dict[str, Any],
        decision_timestamp: str,
        source_epoch_id: str,
        source_contract_fingerprint: str,
        shadow_policy_manifest_fingerprint: str,
        historical: bool = False,
    ) -> dict[str, Any]:
        timeframe = str(candidate.get("timeframe") or "").upper()
        joins: dict[str, dict[str, Any]] = {}
        features: dict[str, Any] = {}
        max_input: str | None = None

        for spec in SOURCE_SPECS:
            joins[spec.artifact_id] = self.backward_asof(
                spec=spec,
                decision_timestamp=decision_timestamp,
                timeframe=timeframe,
            )
            ts = joins[spec.artifact_id].get("max_input_timestamp")
            if ts and (max_input is None or str(ts) > str(max_input)):
                max_input = str(ts)

        for field in RESEARCH_FIELDS:
            priorities = FIELD_SOURCE_PRIORITY.get(field, ())
            if field in ("validation_state", "validation_reason"):
                features[f"{field}_value"] = None
                features[f"{field}_status"] = STATUS_NOT_AVAILABLE_AT_DECISION_TIME
                features[f"{field}_age_seconds_at_decision"] = None
                features[f"{field}_source_artifact"] = None
                features[f"{field}_source_row_timestamp"] = None
                features[f"{field}_join_method"] = None
                features[f"{field}_same_timeframe_match"] = None
                continue
            if not priorities:
                features[f"{field}_value"] = None
                features[f"{field}_status"] = STATUS_NOT_CANONICALLY_AVAILABLE
                features[f"{field}_age_seconds_at_decision"] = None
                features[f"{field}_source_artifact"] = None
                features[f"{field}_source_row_timestamp"] = None
                features[f"{field}_join_method"] = None
                features[f"{field}_same_timeframe_match"] = None
                continue

            chosen_feat = None
            for artifact_id in priorities:
                join = joins[artifact_id]
                spec = next(s for s in SOURCE_SPECS if s.artifact_id == artifact_id)
                feat = self._feature_from_join(field=field, join=join, spec=spec)
                # Prefer VALID, then STALE (keep value), else keep searching
                st = feat[f"{field}_status"]
                if st in (STATUS_VALID, STATUS_STALE):
                    chosen_feat = feat
                    break
                if chosen_feat is None:
                    chosen_feat = feat
                elif st == STATUS_MISSING and chosen_feat[f"{field}_status"] not in (
                    STATUS_WRONG_TIMEFRAME,
                    STATUS_FUTURE_ROW_REJECTED,
                    STATUS_AMBIGUOUS_TIMESTAMP,
                ):
                    # keep more informative prior status if any
                    pass
            assert chosen_feat is not None
            if historical and chosen_feat[f"{field}_status"] == STATUS_MISSING:
                # Distinguish unrecovered historical vs ordinary missing only when no asof row at all
                # for the preferred artifact.
                pref = priorities[0]
                if joins[pref].get("status") in (STATUS_MISSING, STATUS_WRONG_TIMEFRAME):
                    # If preferred source tip exists but no causal row, mark historical not recoverable
                    # only when file has rows after decision (rewritten tip) — else ordinary MISSING.
                    df = self._load(next(s for s in SOURCE_SPECS if s.artifact_id == pref))
                    decision_dt = parse_ts(decision_timestamp)
                    if df is not None and not df.empty and decision_dt is not None:
                        after = df[df["_asof_ts"] > pd.Timestamp(decision_dt)]
                        before = df[df["_asof_ts"] <= pd.Timestamp(decision_dt)]
                        if before.empty and not after.empty:
                            chosen_feat[f"{field}_status"] = STATUS_HISTORICAL_NOT_RECOVERABLE
                            chosen_feat[f"{field}_value"] = None
            features.update(chosen_feat)

        # Lookahead guard on enrichment inputs
        lookahead = False
        d_dt = parse_ts(decision_timestamp)
        m_dt = parse_ts(max_input)
        if d_dt and m_dt and m_dt > d_dt:
            lookahead = True

        status_counts = {
            STATUS_VALID: 0,
            STATUS_STALE: 0,
            STATUS_MISSING: 0,
            STATUS_NOT_CANONICALLY_AVAILABLE: 0,
            STATUS_NOT_AVAILABLE_AT_DECISION_TIME: 0,
            STATUS_AMBIGUOUS_TIMESTAMP: 0,
            STATUS_WRONG_TIMEFRAME: 0,
            STATUS_FUTURE_ROW_REJECTED: 0,
            STATUS_HISTORICAL_NOT_RECOVERABLE: 0,
        }
        for field in RESEARCH_FIELDS:
            st = str(features.get(f"{field}_status"))
            if st in status_counts:
                status_counts[st] += 1

        enrichment = {
            "candidate_id": candidate.get("candidate_id"),
            "decision_timestamp": decision_timestamp,
            "timeframe": timeframe,
            "side": candidate.get("side"),
            "source_epoch_id": source_epoch_id,
            "source_contract_fingerprint": source_contract_fingerprint,
            "shadow_policy_manifest_fingerprint": shadow_policy_manifest_fingerprint,
            "economic_quality_mode": "DATA_COLLECTION",
            "enforcement_enabled": False,
            "join_method": "BACKWARD_ASOF",
            "max_input_timestamp": max_input,
            "lookahead_detected": lookahead,
            "outcome_fields_present": False,
            "source_joins": {
                aid: {
                    k: v
                    for k, v in j.items()
                    if k != "row"
                }
                for aid, j in joins.items()
            },
            "features": features,
            "status_counts": status_counts,
            "enriched_at": utc_now(),
            "historical_backfill": historical,
        }
        return enrichment


def summarize_enrichment_health(rows: list[dict[str, Any]]) -> dict[str, Any]:
    enriched = len(rows)
    fully = 0
    partial = 0
    valid = stale = missing = future = wrong = amb = 0
    last_ts = None
    for row in rows:
        counts = row.get("status_counts") or {}
        valid += int(counts.get(STATUS_VALID) or 0)
        stale += int(counts.get(STATUS_STALE) or 0)
        missing += int(counts.get(STATUS_MISSING) or 0) + int(
            counts.get(STATUS_NOT_CANONICALLY_AVAILABLE) or 0
        ) + int(counts.get(STATUS_NOT_AVAILABLE_AT_DECISION_TIME) or 0) + int(
            counts.get(STATUS_HISTORICAL_NOT_RECOVERABLE) or 0
        )
        future += int(counts.get(STATUS_FUTURE_ROW_REJECTED) or 0)
        wrong += int(counts.get(STATUS_WRONG_TIMEFRAME) or 0)
        amb += int(counts.get(STATUS_AMBIGUOUS_TIMESTAMP) or 0)
        v = int(counts.get(STATUS_VALID) or 0)
        s = int(counts.get(STATUS_STALE) or 0)
        if v + s == len(RESEARCH_FIELDS):
            fully += 1
        elif v + s > 0:
            partial += 1
        ts = row.get("enriched_at") or row.get("decision_timestamp")
        if ts and (last_ts is None or str(ts) > str(last_ts)):
            last_ts = ts
    return {
        "feature_enrichment_enabled": True,
        "enriched_candidate_count": enriched,
        "fully_enriched_candidate_count": fully,
        "partially_enriched_candidate_count": partial,
        "valid_feature_count": valid,
        "stale_feature_count": stale,
        "missing_feature_count": missing,
        "future_row_rejected_count": future,
        "wrong_timeframe_rejected_count": wrong,
        "ambiguous_timestamp_count": amb,
        "last_enrichment_timestamp": last_ts,
    }
