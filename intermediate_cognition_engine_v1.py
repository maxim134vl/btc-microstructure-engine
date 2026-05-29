"""Stage 2.5 — Intermediate cognition layer (Phase 1).

Context narration only. No trading signals.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from parquet_utils import append_state_row, safe_read_parquet
from runtime_lineage import apply_lineage_metadata

MEMORY_PATH = "intermediate_cognition_memory.parquet"
ENGINE_NAME = "intermediate_cognition_engine_v1.py"

PHASE1_STATES = (
    "IC_CONTINUATION_WEAKENING",
    "IC_INITIATIVE_DETERIORATION",
    "IC_ROTATIONAL_PRESSURE",
)

COOLDOWN_BARS = 4
CONFIDENCE_MATERIAL_DELTA = 0.08
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
STATE_PRIORITY = {
    "IC_CONTINUATION_WEAKENING": 3,
    "IC_INITIATIVE_DETERIORATION": 2,
    "IC_ROTATIONAL_PRESSURE": 1,
}

CONTINUATION_DELTA_MIN = 350.0
CONTINUATION_PRICE_MIN = 150.0
INITIATIVE_MA_MIN = 180.0
INITIATIVE_SWING_MIN = 450.0
ROTATIONAL_FLIPS_MIN = 4

BASE_CONFIDENCE = {
    "IC_CONTINUATION_WEAKENING": 0.55,
    "IC_INITIATIVE_DETERIORATION": 0.52,
    "IC_ROTATIONAL_PRESSURE": 0.48,
}

MAX_MEMORY_ROWS = 520


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) == 0:
        return df
    frame = df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    return frame.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def _stage2_anchor(stage2: pd.DataFrame, ts: pd.Timestamp) -> dict[str, Any] | None:
    if len(stage2) == 0:
        return None
    prior = stage2[stage2["timestamp"] <= ts]
    if len(prior) == 0:
        return None
    row = prior.iloc[-1]
    return {
        "anchor_timestamp": row["timestamp"],
        "anchor_stage2_state": row.get("synthesis_state"),
        "trigger_event": row.get("trigger_event"),
        "persistence": row.get("persistence"),
    }


def _severity_continuation(delta5: float, price5: float) -> str:
    ratio = abs(delta5) / max(abs(price5), 1.0)
    if ratio > 15 or abs(delta5) > 2500:
        return "HIGH"
    if ratio > 8 or abs(delta5) > 1200:
        return "MEDIUM"
    return "LOW"


def _severity_initiative(prev_ma: float, cur_ma: float) -> str:
    swing = abs(cur_ma - prev_ma)
    if swing > 800:
        return "HIGH"
    if swing > 400:
        return "MEDIUM"
    return "LOW"


def _confidence(state: str, severity: str, source_count: int) -> float:
    base = BASE_CONFIDENCE[state]
    adj = {"HIGH": 0.06, "MEDIUM": 0.0, "LOW": -0.05}[severity]
    if source_count >= 2:
        adj += 0.05
    return round(min(0.75, max(0.35, base + adj)), 4)


def _collapse_bar_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep at most one intermediate event per timestamp (highest severity, then priority)."""

    by_ts: dict[pd.Timestamp, dict[str, Any]] = {}
    for candidate in candidates:
        ts = pd.Timestamp(candidate["timestamp"])
        current = by_ts.get(ts)
        if current is None:
            by_ts[ts] = candidate
            continue
        cur_rank = SEVERITY_RANK.get(str(current.get("severity")), 0)
        new_rank = SEVERITY_RANK.get(str(candidate.get("severity")), 0)
        if new_rank > cur_rank:
            by_ts[ts] = candidate
        elif new_rank == cur_rank:
            cur_pri = STATE_PRIORITY.get(str(current.get("intermediate_state")), 0)
            new_pri = STATE_PRIORITY.get(str(candidate.get("intermediate_state")), 0)
            if new_pri > cur_pri:
                by_ts[ts] = candidate
    return sorted(by_ts.values(), key=lambda row: row["timestamp"])


def detect_candidates(
    candles: pd.DataFrame,
    volume_class: pd.DataFrame | None = None,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    """Evaluate Phase 1 intermediate triggers over M15 candles."""

    candles = _prep(candles)
    if len(candles) < 6:
        return []

    if start is not None:
        candles = candles[candles["timestamp"] >= start]
    if end is not None:
        candles = candles[candles["timestamp"] <= end]
    if len(candles) < 6:
        return []

    vol_class = _prep(volume_class) if volume_class is not None else pd.DataFrame()
    vol_lookup = {}
    if len(vol_class) > 0 and "volume_class" in vol_class.columns:
        for _, row in vol_class.iterrows():
            vol_lookup[row["timestamp"]] = row.get("volume_class")

    frame = candles.copy()
    frame["dir"] = np.sign(frame["delta"].astype(float))

    candidates: list[dict[str, Any]] = []

    for i in range(5, len(frame)):
        ts = frame.iloc[i]["timestamp"]
        w5 = frame.iloc[i - 4 : i + 1]
        delta5 = float(w5["delta"].astype(float).sum())
        price5 = float(frame.iloc[i]["close"] - frame.iloc[i - 5]["close"])
        dirs = w5["dir"].values
        sign_flips = int(np.sum(dirs[1:] != dirs[:-1])) if len(dirs) == 5 else 0

        ma5 = float(w5["delta"].astype(float).mean())
        prev = frame.iloc[max(0, i - 9) : i - 4]
        ma5_prev = float(prev["delta"].astype(float).mean()) if len(prev) >= 3 else np.nan

        sources: list[str] = ["candle_structure_memory"]

        # IC_CONTINUATION_WEAKENING
        if (
            delta5 > CONTINUATION_DELTA_MIN
            and price5 < -CONTINUATION_PRICE_MIN
        ) or (
            delta5 < -CONTINUATION_DELTA_MIN
            and price5 > CONTINUATION_PRICE_MIN
        ):
            severity = _severity_continuation(delta5, price5)
            direction = "effort-up/price-down" if delta5 > 0 else "effort-down/price-up"
            candidates.append(
                {
                    "timestamp": ts,
                    "intermediate_state": "IC_CONTINUATION_WEAKENING",
                    "severity": severity,
                    "confidence": _confidence("IC_CONTINUATION_WEAKENING", severity, 1),
                    "source_layers": json.dumps(sources),
                    "reason": f"{direction}; delta5={delta5:.0f}, price5={price5:.1f}",
                }
            )

        # IC_INITIATIVE_DETERIORATION
        if pd.notna(ma5_prev) and np.sign(ma5_prev) != np.sign(ma5):
            swing = abs(ma5 - ma5_prev)
            if (
                abs(ma5) >= INITIATIVE_MA_MIN
                and abs(ma5_prev) >= INITIATIVE_MA_MIN
                and swing >= INITIATIVE_SWING_MIN
            ):
                severity = _severity_initiative(ma5_prev, ma5)
                candidates.append(
                    {
                        "timestamp": ts,
                        "intermediate_state": "IC_INITIATIVE_DETERIORATION",
                        "severity": severity,
                        "confidence": _confidence("IC_INITIATIVE_DETERIORATION", severity, 1),
                        "source_layers": json.dumps(sources),
                        "reason": f"initiative MA flip {ma5_prev:.0f} → {ma5:.0f}",
                    }
                )

        # IC_ROTATIONAL_PRESSURE
        rotational = sign_flips >= ROTATIONAL_FLIPS_MIN
        vc = vol_lookup.get(ts)
        if vc == "stopping":
            rotational = True
            sources = list(dict.fromkeys(sources + ["volume_classification_memory"]))
        if rotational:
            severity = "HIGH" if sign_flips >= ROTATIONAL_FLIPS_MIN or vc == "stopping" else "MEDIUM"
            if severity == "MEDIUM" and vc != "stopping":
                rotational = False
        if rotational:
            reason = f"sign_flips_5={sign_flips}"
            if vc == "stopping":
                reason += "; volume_class=stopping"
            candidates.append(
                {
                    "timestamp": ts,
                    "intermediate_state": "IC_ROTATIONAL_PRESSURE",
                    "severity": severity,
                    "confidence": _confidence("IC_ROTATIONAL_PRESSURE", severity, len(sources)),
                    "source_layers": json.dumps(sources),
                    "reason": reason,
                }
            )

    return _collapse_bar_candidates(candidates)


def _bars_between(ts_a: pd.Timestamp, ts_b: pd.Timestamp) -> float:
    return abs((ts_b - ts_a).total_seconds()) / (15 * 60)


def should_persist(
    existing: pd.DataFrame,
    candidate: dict[str, Any],
    *,
    cooldown_bars: int = COOLDOWN_BARS,
) -> bool:
    """Return True if candidate should be appended given cooldown rules."""

    if len(existing) == 0:
        return True

    state = candidate["intermediate_state"]
    ts = pd.Timestamp(candidate["timestamp"])
    same = existing[existing["intermediate_state"] == state]
    if len(same) == 0:
        return True

    recent = same[same["timestamp"] >= ts - pd.Timedelta(minutes=15 * cooldown_bars)]
    if len(recent) == 0:
        return True

    last = recent.iloc[-1]
    bars = _bars_between(pd.Timestamp(last["timestamp"]), ts)
    if bars >= cooldown_bars:
        same_hour = (
            pd.Timestamp(last["timestamp"]).floor("h") == ts.floor("h")
        )
        if same_hour:
            last_sev = SEVERITY_RANK.get(str(last.get("severity")), 0)
            new_sev = SEVERITY_RANK.get(str(candidate.get("severity")), 0)
            if new_sev <= last_sev:
                return False
        return True

    last_sev = SEVERITY_RANK.get(str(last.get("severity")), 0)
    new_sev = SEVERITY_RANK.get(str(candidate.get("severity")), 0)
    if new_sev > last_sev:
        return True

    last_conf = float(last.get("confidence") or 0)
    new_conf = float(candidate.get("confidence") or 0)
    if abs(new_conf - last_conf) >= CONFIDENCE_MATERIAL_DELTA:
        return True

    return False


def enrich_with_anchor(rows: list[dict[str, Any]], stage2: pd.DataFrame) -> list[dict[str, Any]]:
    stage2 = _prep(stage2)
    enriched: list[dict[str, Any]] = []
    for row in rows:
        ts = pd.Timestamp(row["timestamp"])
        anchor = _stage2_anchor(stage2, ts)
        enriched.append(
            {
                **row,
                "anchor_timestamp": anchor["anchor_timestamp"] if anchor else None,
                "anchor_stage2_state": anchor["anchor_stage2_state"] if anchor else None,
            }
        )
    return enriched


def persist_candidates(candidates: list[dict[str, Any]], *, reset: bool = False) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    existing = pd.DataFrame() if reset else _prep(safe_read_parquet(MEMORY_PATH))
    appended: list[dict[str, Any]] = []

    for candidate in sorted(candidates, key=lambda r: r["timestamp"]):
        if should_persist(existing, candidate):
            row = pd.DataFrame([candidate])
            row = apply_lineage_metadata(
                row,
                engine_name=ENGINE_NAME,
                source_parquet="candle_structure_memory.parquet",
                dependency_chain=[
                    "candle_structure_memory.parquet",
                    "runtime_cognition_memory.parquet",
                    ENGINE_NAME,
                    MEMORY_PATH,
                ],
            )
            row["lineage_timestamp"] = row["lineage_propagation_timestamp"]
            if len(existing) == 0:
                existing = row
            else:
                existing = pd.concat([existing, row], ignore_index=True)
            appended.append(candidate)

    if len(existing) > MAX_MEMORY_ROWS:
        existing = existing.iloc[-MAX_MEMORY_ROWS:].reset_index(drop=True)

    if len(existing) > 0:
        from parquet_utils import atomic_parquet_write

        atomic_parquet_write(existing, MEMORY_PATH)

    return existing, appended


def build_gap_comparison(
    *,
    start: str = "2026-05-21",
    end: str = "2026-05-28 23:59:59",
    gap_observable_signals: int = 47,
    gap_stage2_events: int = 0,
) -> dict[str, Any]:
    """Compare Stage 2.5 output against Behavioral Gap Analysis baseline."""

    memory = _prep(safe_read_parquet(MEMORY_PATH))
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    period = memory[(memory["timestamp"] >= start_ts) & (memory["timestamp"] <= end_ts)] if len(memory) else pd.DataFrame()

    stage2 = _prep(safe_read_parquet("runtime_cognition_memory.parquet"))
    stage2_in_period = stage2[(stage2["timestamp"] >= start_ts) & (stage2["timestamp"] <= end_ts)] if len(stage2) else pd.DataFrame()

    return {
        "behavioral_gap_observable_signals": gap_observable_signals,
        "behavioral_gap_stage2_events": gap_stage2_events,
        "stage2_5_events": len(period),
        "stage2_events_in_period": len(stage2_in_period),
        "narrative_continuity_restored": len(period) > 0 and gap_stage2_events == 0,
        "coverage_ratio_vs_gap": round(len(period) / max(gap_observable_signals, 1), 3),
        "note": (
            "Stage 2.5 emits deduplicated intermediate states; gap analysis counted raw observable signals."
        ),
    }


def build_cognition_chain_example(memory: pd.DataFrame, stage2: pd.DataFrame) -> list[dict[str, Any]]:
    """Build example narrative chain linking Stage 2 anchor → Tier-2 → Stage 2."""

    chain: list[dict[str, Any]] = []
    stage2 = _prep(stage2)
    memory = _prep(memory)

    if len(stage2) == 0:
        return chain

    anchor = stage2.iloc[-1]
    chain.append(
        {
            "layer": "stage1_trigger",
            "timestamp": anchor.get("timestamp"),
            "state": anchor.get("trigger_event"),
        }
    )
    chain.append(
        {
            "layer": "stage2_anchor",
            "timestamp": anchor.get("timestamp"),
            "state": anchor.get("synthesis_state"),
        }
    )

    for _, row in memory.tail(8).iterrows():
        chain.append(
            {
                "layer": "stage2_5",
                "timestamp": row["timestamp"],
                "state": row["intermediate_state"],
                "confidence": row.get("confidence"),
                "severity": row.get("severity"),
            }
        )

    reversal = stage2[stage2["synthesis_state"].astype(str).str.contains("REVERSAL", case=False, na=False)]
    if len(reversal):
        row = reversal.iloc[-1]
        chain.append(
            {
                "layer": "stage2_synthesis",
                "timestamp": row["timestamp"],
                "state": row["synthesis_state"],
            }
        )

    return chain


def run_validation_report(
    *,
    start: str = "2026-05-21",
    end: str = "2026-05-28 23:59:59",
) -> dict[str, Any]:
    """Full retrospective validation payload for acceptance criteria."""

    retrospective = run_retrospective(start=start, end=end, reset=True)
    memory = _prep(safe_read_parquet(MEMORY_PATH))
    stage2 = _prep(safe_read_parquet("runtime_cognition_memory.parquet"))
    candles = _prep(safe_read_parquet("candle_structure_memory.parquet"))
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    candle_span = candles[(candles["timestamp"] >= start_ts) & (candles["timestamp"] <= end_ts)]

    gap = build_gap_comparison(start=start, end=end)
    chain = build_cognition_chain_example(memory, stage2)

    accepted = (
        retrospective["event_count"] >= 8
        and retrospective.get("density_status") in ("OK", "INSUFFICIENT_PERIOD")
        and gap["narrative_continuity_restored"]
    )

    return {
        **retrospective,
        "gap_comparison": gap,
        "cognition_chain_example": chain,
        "data_coverage": {
            "candles_in_period": len(candle_span),
            "candle_start": str(candle_span["timestamp"].min()) if len(candle_span) else None,
            "candle_end": str(candle_span["timestamp"].max()) if len(candle_span) else None,
            "last_stage2_event": str(stage2["timestamp"].max()) if len(stage2) else None,
        },
        "acceptance": {
            "passed": accepted,
            "criteria": [
                "observable narrative continuity between Stage 2 anchor events",
                "event density 12–20/week (or INSUFFICIENT_PERIOD with ≥8 events)",
                "no trading signals emitted",
            ],
        },
    }


def run_retrospective(
    *,
    start: str = "2026-05-21",
    end: str = "2026-05-28 23:59:59",
    reset: bool = True,
) -> dict[str, Any]:
    """Replay intermediate cognition detection over a historical window."""

    candles = _prep(safe_read_parquet("candle_structure_memory.parquet"))
    vol_class = _prep(safe_read_parquet("volume_classification_memory.parquet"))
    stage2 = _prep(safe_read_parquet("runtime_cognition_memory.parquet"))

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    candidates = detect_candidates(candles, vol_class, start=start_ts, end=end_ts)
    candidates = enrich_with_anchor(candidates, stage2)

    memory, appended = persist_candidates(candidates, reset=reset)

    period_rows = memory[
        (memory["timestamp"] >= start_ts) & (memory["timestamp"] <= end_ts)
    ] if len(memory) else pd.DataFrame()

    days = max((end_ts - start_ts).total_seconds() / 86400, 1)
    weeks = days / 7
    count = len(period_rows)
    weekly_rate = count / weeks if weeks else count

    distribution = period_rows["intermediate_state"].value_counts().to_dict() if len(period_rows) else {}
    timeline = period_rows.sort_values("timestamp").to_dict(orient="records") if len(period_rows) else []

    density_ok = 12 <= weekly_rate <= 20 if days >= 6 else None

    return {
        "status": "OK",
        "period_start": start,
        "period_end": end,
        "event_count": count,
        "events_appended_this_run": len(appended),
        "weekly_rate": round(weekly_rate, 2),
        "density_target_12_20": density_ok,
        "density_status": (
            "OK" if density_ok else ("SPARSE" if weekly_rate < 12 else "NOISY")
        ) if density_ok is not None else "INSUFFICIENT_PERIOD",
        "distribution": distribution,
        "timeline": timeline,
    }


def run() -> None:
    """Live evaluation — process candles since last memory timestamp."""

    print()
    print("INTERMEDIATE COGNITION ENGINE (Stage 2.5 Phase 1)")
    print()

    candles = _prep(safe_read_parquet("candle_structure_memory.parquet"))
    vol_class = _prep(safe_read_parquet("volume_classification_memory.parquet"))
    stage2 = _prep(safe_read_parquet("runtime_cognition_memory.parquet"))
    existing = _prep(safe_read_parquet(MEMORY_PATH))

    if len(candles) == 0:
        print("NO CANDLE DATA")
        print()
        return

    start_ts = existing["timestamp"].max() - pd.Timedelta(minutes=15 * 5) if len(existing) else candles["timestamp"].min()
    candidates = detect_candidates(candles, vol_class, start=start_ts)
    candidates = enrich_with_anchor(candidates, stage2)

    _, appended = persist_candidates(candidates, reset=False)

    print("CANDIDATES EVALUATED:", len(candidates))
    print("APPENDED:", len(appended))
    print("MEMORY ROWS:", len(_prep(safe_read_parquet(MEMORY_PATH))))
    if appended:
        latest = appended[-1]
        print("LATEST:", latest["intermediate_state"], latest["timestamp"])
    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Stage 2.5 intermediate cognition")
    parser.add_argument("--retrospective", action="store_true")
    parser.add_argument("--start", default="2026-05-21")
    parser.add_argument("--end", default="2026-05-28 23:59:59")
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--validation-report", action="store_true")
    args = parser.parse_args()

    if args.validation_report:
        import json as _json

        result = run_validation_report(start=args.start, end=args.end)
        print(_json.dumps(result, indent=2, default=str))
    elif args.retrospective:
        import json as _json

        result = run_retrospective(start=args.start, end=args.end, reset=not args.no_reset)
        print(_json.dumps(result, indent=2, default=str))
    else:
        run()
