"""Candidate volume localization producer — legacy v1 algorithm, isolated outputs.

Reads completed candle_structure rows only. Does not write cognition memories.
No lookahead: each observation uses only that bar's completed structure fields.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Frozen constants from config/volume_localization.py @ git 8fbde36
EPS = 1e-6
WICK_REJECTION_RATIO = 0.40
WICK_DOMINANCE_SPREAD = 0.35
CLOSE_LOWER = 0.40
CLOSE_UPPER = 0.60
RATIO_BODY = 0.5
RATIO_WICK = 0.7
ZONE_LOWER_WICK_LOW = 0.25
ZONE_LOWER_WICK_HIGH = 0.45
ZONE_UPPER_WICK_LOW = 0.55
ZONE_UPPER_WICK_HIGH = 0.80

REQUIRED = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "spread",
    "upper_wick",
    "lower_wick",
    "close_position",
)

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = REPO / "data" / "cognition" / "candle_structure_memory.parquet"
DEFAULT_OUT_DIR = REPO / "data" / "candidate" / "capability_gap"
LEGACY_ORPHAN = REPO / "data" / "cognition" / "volume_localization_memory.parquet"
FINAL_CONTEXT = REPO / "data" / "cognition" / "final_market_context_memory.parquet"


def deterministic_id(*parts: object) -> str:
    payload = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def derive_rejection_flags(row: pd.Series) -> tuple[bool, bool]:
    spread = float(row["spread"])
    if spread <= 0:
        return False, False
    upper_wick = float(row["upper_wick"])
    lower_wick = float(row["lower_wick"])
    close_position = float(row["close_position"])
    uwr = upper_wick / (spread + EPS)
    lwr = lower_wick / (spread + EPS)
    lower_rej = lwr > WICK_REJECTION_RATIO and close_position > CLOSE_LOWER
    upper_rej = uwr > WICK_REJECTION_RATIO and close_position < CLOSE_UPPER
    return lower_rej, upper_rej


def localize_bar(row: pd.Series) -> dict[str, Any]:
    lower_rej, upper_rej = derive_rejection_flags(row)
    spread = float(row["spread"])
    low = float(row["low"])
    high = float(row["high"])
    open_price = float(row["open"])
    close_price = float(row["close"])
    volume = float(row["volume"])
    lower_wick = float(row["lower_wick"])
    upper_wick = float(row["upper_wick"])

    if lower_rej and lower_wick > spread * WICK_DOMINANCE_SPREAD:
        ratio = RATIO_WICK
        behavior = "localized_absorption"
        zone_low = low + lower_wick * ZONE_LOWER_WICK_LOW
        zone_high = low + lower_wick * ZONE_LOWER_WICK_HIGH
    elif upper_rej and upper_wick > spread * WICK_DOMINANCE_SPREAD:
        ratio = RATIO_WICK
        behavior = "localized_distribution"
        zone_low = high - upper_wick * (1.0 - ZONE_UPPER_WICK_LOW)
        zone_high = high - upper_wick * (1.0 - ZONE_UPPER_WICK_HIGH)
    else:
        ratio = RATIO_BODY
        behavior = "body_participation"
        zone_low = min(open_price, close_price)
        zone_high = max(open_price, close_price)

    elv = volume * ratio
    ts = pd.Timestamp(row["timestamp"])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return {
        "observation_id": deterministic_id("vol_loc_cand", ts.isoformat()),
        "timestamp": ts,
        "estimated_local_volume": elv,
        "total_volume": volume,
        "localized_volume_ratio": ratio,
        "volume_concentration": elv / (volume + EPS),
        "behavior": behavior,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "zone_width": zone_high - zone_low,
        "lower_rejection": bool(lower_rej),
        "upper_rejection": bool(upper_rej),
        "source_lineage": "candle_structure_memory|volume_localization_candidate_v1",
        "algorithm_version": "volume_localization_v1@8fbde36",
    }


def _required_ok(row: pd.Series) -> bool:
    return all(field in row.index and pd.notna(row[field]) for field in REQUIRED)


def build_volume_localization_candidate(
    source: Path = DEFAULT_SOURCE,
    *,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> tuple[pd.DataFrame, dict]:
    if not source.exists():
        return pd.DataFrame(), {"status": "SOURCE_MISSING", "source": str(source)}
    structure = pd.read_parquet(source)
    if len(structure) == 0:
        return pd.DataFrame(), {"status": "SOURCE_EMPTY", "source": str(source)}
    structure = structure.copy()
    structure["timestamp"] = pd.to_datetime(structure["timestamp"], utc=True, errors="coerce")
    structure = structure.dropna(subset=["timestamp"]).sort_values("timestamp")
    if start is not None:
        start_ts = pd.Timestamp(start)
        start_ts = start_ts.tz_localize("UTC") if start_ts.tzinfo is None else start_ts.tz_convert("UTC")
        structure = structure[structure["timestamp"] >= start_ts]
    if end is not None:
        end_ts = pd.Timestamp(end)
        end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
        structure = structure[structure["timestamp"] <= end_ts]

    rows: list[dict[str, Any]] = []
    skipped = 0
    for _, row in structure.iterrows():
        if not _required_ok(row):
            skipped += 1
            continue
        rows.append(localize_bar(row))
    frame = pd.DataFrame(rows)
    if len(frame):
        before = len(frame)
        frame = frame.drop_duplicates(subset=["observation_id"], keep="last").reset_index(drop=True)
        duplicates = before - len(frame)
    else:
        duplicates = 0
    meta = {
        "status": "OK",
        "source": str(source),
        "input_rows": int(len(structure)),
        "output_rows": int(len(frame)),
        "skipped_invalid": int(skipped),
        "duplicates": int(duplicates),
        "no_lookahead": True,
        "idempotent": True,
        "algorithm_version": "volume_localization_v1@8fbde36",
    }
    return frame, meta


def compare_with_legacy_and_context(
    candidate: pd.DataFrame,
    legacy_path: Path = LEGACY_ORPHAN,
    context_path: Path = FINAL_CONTEXT,
) -> dict:
    """Historical comparison on overlapping timestamps (exact timestamp join)."""
    out: dict[str, Any] = {
        "legacy_available": legacy_path.exists(),
        "context_available": context_path.exists(),
    }
    if not len(candidate):
        out["status"] = "NO_CANDIDATE_ROWS"
        return out
    cand = candidate.copy()
    cand["timestamp"] = pd.to_datetime(cand["timestamp"], utc=True)

    exact = partial = missing = 0
    if legacy_path.exists():
        legacy = pd.read_parquet(legacy_path)
        legacy["timestamp"] = pd.to_datetime(legacy["timestamp"], utc=True)
        merged = cand.merge(
            legacy[
                [
                    "timestamp",
                    "behavior",
                    "estimated_local_volume",
                    "volume_concentration",
                    "zone_low",
                    "zone_high",
                ]
            ],
            on="timestamp",
            how="inner",
            suffixes=("_cand", "_leg"),
        )
        out["overlap_with_legacy"] = int(len(merged))
        if len(merged):
            for _, row in merged.iterrows():
                same_behavior = row["behavior_cand"] == row["behavior_leg"]
                same_elv = abs(float(row["estimated_local_volume_cand"]) - float(row["estimated_local_volume_leg"])) < 1e-9
                same_zone = (
                    abs(float(row["zone_low_cand"]) - float(row["zone_low_leg"])) < 1e-9
                    and abs(float(row["zone_high_cand"]) - float(row["zone_high_leg"])) < 1e-9
                )
                if same_behavior and same_elv and same_zone:
                    exact += 1
                elif same_behavior:
                    partial += 1
                else:
                    missing += 1
            out["exact_equivalent_share"] = exact / len(merged)
            out["partial_equivalent_share"] = partial / len(merged)
            out["lost_feature_share"] = missing / len(merged)
            # sample disagreements
            disagree = merged[merged["behavior_cand"] != merged["behavior_leg"]].head(5)
            out["disagreement_examples"] = [
                {
                    "timestamp": str(r["timestamp"]),
                    "candidate_behavior": r["behavior_cand"],
                    "legacy_behavior": r["behavior_leg"],
                    "candidate_elv": float(r["estimated_local_volume_cand"]),
                    "legacy_elv": float(r["estimated_local_volume_leg"]),
                }
                for _, r in disagree.iterrows()
            ]
        else:
            out["exact_equivalent_share"] = None
            out["note"] = "No timestamp overlap between candidate window and orphan legacy tip"

    if context_path.exists():
        ctx = pd.read_parquet(context_path)
        ctx["timestamp"] = pd.to_datetime(ctx["timestamp"], utc=True)
        joined = cand.merge(ctx[["timestamp", "market_context"]], on="timestamp", how="inner")
        out["overlap_with_final_context"] = int(len(joined))
        if len(joined):
            ct = pd.crosstab(joined["behavior"], joined["market_context"])
            out["behavior_vs_context"] = {str(i): {str(c): int(ct.loc[i, c]) for c in ct.columns} for i in ct.index}
            # Does behavior alone determine context? No if same behavior maps to multiple contexts.
            multi = {b: int((ct.loc[b] > 0).sum()) for b in ct.index}
            out["contexts_per_behavior"] = multi
            out["behavior_does_not_uniquely_determine_context"] = any(v > 1 for v in multi.values())
            # examples where absorption coincides with SHORT (counter-intuitive) etc.
            samples = []
            for behavior in ("localized_absorption", "localized_distribution"):
                sub = joined[joined["behavior"] == behavior]
                for ctx_name in ("LONG_CONTEXT", "SHORT_CONTEXT", "OBSERVE"):
                    hit = sub[sub["market_context"] == ctx_name].head(1)
                    if len(hit):
                        r = hit.iloc[0]
                        samples.append(
                            {
                                "timestamp": str(r["timestamp"]),
                                "behavior": behavior,
                                "market_context": ctx_name,
                                "elv": float(r["estimated_local_volume"]),
                            }
                        )
            out["context_divergence_examples"] = samples
    return out


def write_volume_candidate(
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    source: Path = DEFAULT_SOURCE,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> dict:
    frame, meta = build_volume_localization_candidate(source, start=start, end=end)
    # Historical comparison uses full available structure∩legacy overlap (not only bounded window)
    full_frame, _ = build_volume_localization_candidate(source, start=None, end=None)
    comparison = compare_with_legacy_and_context(full_frame)
    comparison["bounded_window_rows"] = int(len(frame))
    comparison["full_candidate_rows"] = int(len(full_frame))
    # idempotency check
    frame2, _ = build_volume_localization_candidate(source, start=start, end=end)
    idempotent = (
        frame["observation_id"].tolist() if len(frame) else []
    ) == (frame2["observation_id"].tolist() if len(frame2) else [])
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "component": "volume_localization_candidate",
        "meta": meta,
        "comparison": comparison,
        "invariants": {
            "no_lookahead": True,
            "deterministic_ids": True,
            "idempotent": idempotent,
            "duplicates": meta.get("duplicates", 0),
            "writes_cognition_memories": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".gitkeep").write_text("", encoding="utf-8")
    parquet_path = out_dir / "volume_localization_candidate.parquet"
    tmp = parquet_path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(parquet_path)
    status_path = out_dir / "volume_localization_candidate_status.json"
    status_path.write_text(json.dumps(status, indent=2, default=str) + "\n", encoding="utf-8")
    status["output_parquet"] = str(parquet_path)
    status["output_status"] = str(status_path)
    status["rows"] = int(len(frame))
    return status
