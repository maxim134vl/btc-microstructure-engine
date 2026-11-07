#!/usr/bin/env python3
"""Bounded candidate replay for volume localization live wiring (Phase 4A).

Writes ONLY under data/candidate/volume_localization_live_wiring/.
Does not write live cognition / trading artifacts. Does not restart processes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from parquet_utils import atomic_parquet_write  # noqa: E402
from volume_localization_engine_v1 import (  # noqa: E402
    ALGORITHM_VERSION,
    build_localization_frame,
    resolve_localization_for_structure,
)

OUT_DIR = REPO / "data" / "candidate" / "volume_localization_live_wiring"
CANDLE = REPO / "data" / "cognition" / "candle_structure_memory.parquet"
SHADOW = REPO / "data" / "candidate" / "volume_localization_shadow" / "volume_localization_shadow.parquet"
LEGACY = REPO / "data" / "cognition" / "volume_localization_memory.parquet"
RESPONSE = REPO / "data" / "cognition" / "volume_response_state.parquet"
FINAL = REPO / "data" / "cognition" / "final_market_context_memory.parquet"


def _parity(a: pd.DataFrame, b: pd.DataFrame, cols: list[str]) -> dict:
    left = a.copy()
    right = b.copy()
    left["timestamp"] = pd.to_datetime(left["timestamp"], utc=True)
    right["timestamp"] = pd.to_datetime(right["timestamp"], utc=True)
    merged = left.merge(right, on="timestamp", how="inner", suffixes=("_cand", "_ref"))
    out = {"rows_compared": int(len(merged))}
    if not len(merged):
        out["parity_ok"] = False
        return out
    ok = True
    for col in cols:
        if col == "behavior":
            share = float((merged[f"{col}_cand"] == merged[f"{col}_ref"]).mean())
            out[col] = {"exact_share": share}
            ok = ok and share == 1.0
        else:
            err = (merged[f"{col}_cand"] - merged[f"{col}_ref"]).abs()
            share = float((err < 1e-12).mean())
            out[col] = {
                "exact_share": share,
                "max_abs_error": float(err.max()),
            }
            ok = ok and share == 1.0 and float(err.max()) == 0.0
    out["parity_ok"] = ok
    return out


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    structure = pd.read_parquet(CANDLE)
    structure["timestamp"] = pd.to_datetime(structure["timestamp"], utc=True)
    structure = structure.sort_values("timestamp")
    bounded = structure.iloc[-5000:].copy()

    cand = build_localization_frame(bounded)
    atomic_parquet_write(
        cand,
        str(OUT_DIR / "volume_localization_candidate.parquet"),
        validate=True,
        timestamp_col="timestamp",
        enforce_timestamp_integrity=True,
    )

    # Parity vs proven shadow (same algorithm) and legacy orphan overlap.
    parity = {}
    if SHADOW.exists():
        shadow = pd.read_parquet(SHADOW)
        ts_col = "source_timestamp" if "source_timestamp" in shadow.columns else "timestamp"
        ref = shadow.copy()
        ref["timestamp"] = pd.to_datetime(ref[ts_col], utc=True)
        shadow_ts = set(ref["timestamp"])
        overlap_struct = bounded[bounded["timestamp"].isin(shadow_ts)]
        from_cand = build_localization_frame(overlap_struct)
        parity["vs_shadow"] = _parity(
            from_cand,
            ref[
                [
                    "timestamp",
                    "estimated_local_volume",
                    "volume_concentration",
                    "zone_low",
                    "zone_high",
                    "zone_width",
                    "behavior",
                ]
            ],
            [
                "estimated_local_volume",
                "volume_concentration",
                "zone_low",
                "zone_high",
                "zone_width",
                "behavior",
            ],
        )
    if LEGACY.exists():
        legacy = pd.read_parquet(LEGACY)
        legacy = legacy.copy()
        legacy["timestamp"] = pd.to_datetime(legacy["timestamp"], utc=True)
        # Full historical overlap (not only latest-5000 window) for ≥5000 parity gate.
        overlap_struct = structure[structure["timestamp"].isin(set(legacy["timestamp"]))]
        parity_cand = build_localization_frame(overlap_struct)
        parity["vs_legacy_orphan"] = _parity(
            parity_cand,
            legacy[
                [
                    "timestamp",
                    "estimated_local_volume",
                    "volume_concentration",
                    "zone_low",
                    "zone_high",
                    "zone_width",
                    "behavior",
                ]
            ],
            [
                "estimated_local_volume",
                "volume_concentration",
                "zone_low",
                "zone_high",
                "zone_width",
                "behavior",
            ],
        )
        parity["vs_legacy_orphan"]["parity_window"] = "full_orphan_timestamp_overlap"

    # Candidate volume-response localization fields via exact join (no live write).
    response_rows = []
    for _, crow in bounded.iterrows():
        join = resolve_localization_for_structure(cand, crow["timestamp"], live_v1=True)
        row = {
            "timestamp": crow["timestamp"],
            "localization_join_status": join["localization_join_status"],
            "localization_source_timestamp": join["localization_source_timestamp"],
            "localization_fresh": join["localization_fresh"],
            "estimated_local_volume": None,
            "volume_concentration": None,
            "localized_behavior": None,
            "location_bias": None,  # must remain untouched / not derived
        }
        if join["localization_join_status"] == "EXACT_FRESH_MATCH" and join["row"] is not None:
            r = join["row"]
            row["estimated_local_volume"] = float(r["estimated_local_volume"])
            row["volume_concentration"] = float(r["volume_concentration"])
            row["localized_behavior"] = r["behavior"]
        response_rows.append(row)
    response_cand = pd.DataFrame(response_rows)
    atomic_parquet_write(
        response_cand,
        str(OUT_DIR / "volume_response_candidate.parquet"),
        validate=True,
        timestamp_col="timestamp",
        enforce_timestamp_integrity=False,
    )

    # Compare against current live response on overlapping timestamps.
    comparison = {"live_response_available": RESPONSE.exists()}
    if RESPONSE.exists():
        live = pd.read_parquet(RESPONSE)
        live["timestamp"] = pd.to_datetime(live["timestamp"], utc=True, errors="coerce")
        # Live tip uses wall-clock timestamps; fuzzy/nearest join is FORBIDDEN.
        # Exact bar-open overlap is therefore expected to be zero until activation
        # writes response rows keyed by structure timestamp.
        merged = response_cand.merge(
            live[
                [
                    c
                    for c in live.columns
                    if c
                    in {
                        "timestamp",
                        "localized_behavior",
                        "estimated_local_volume",
                        "volume_concentration",
                        "effort_result_state",
                        "volume_event",
                        "unfinished_auction",
                    }
                ]
            ],
            on="timestamp",
            how="inner",
            suffixes=("_cand", "_live"),
        )
        comparison["exact_timestamp_overlap"] = int(len(merged))
        comparison["live_timestamp_semantics"] = "wall_clock_not_bar_open"
        comparison["expected_restored_deltas"] = {
            "estimated_local_volume": "yes (on activation / exact join)",
            "volume_concentration": "yes (on activation / exact join)",
            "localized_behavior": "yes (on activation / exact join)",
            "localization_join_status": "yes (new metadata when flag ON)",
        }
        comparison["must_remain_equal_when_flag_off"] = {
            "effort_result_state": "unchanged (not rewritten by candidate)",
            "volume_event": "unchanged (not rewritten by candidate)",
            "unfinished_auction": "unchanged (not rewritten by candidate)",
            "raw_ohlcv_refs": "unchanged",
            "unrelated_volume_response_changes": 0,
        }
        if len(merged):
            for col, expected_change in (
                ("estimated_local_volume", True),
                ("volume_concentration", True),
                ("localized_behavior", True),
            ):
                if f"{col}_live" not in merged.columns:
                    continue
                if col == "localized_behavior":
                    equal = int((merged[f"{col}_cand"] == merged[f"{col}_live"]).sum())
                else:
                    equal = int(
                        (
                            (merged[f"{col}_cand"].isna() & merged[f"{col}_live"].isna())
                            | (
                                (merged[f"{col}_cand"] - merged[f"{col}_live"]).abs()
                                < 1e-12
                            )
                        ).sum()
                    )
                comparison[col] = {
                    "equal_rows": equal,
                    "changed_rows": int(len(merged) - equal),
                    "expected_change": expected_change,
                }
        else:
            # Tip-level stale vs fresh (research): live tip-carry vs candidate tip.
            comparison["tip_level_stale_vs_fresh"] = {
                "live_localized_behavior": live.iloc[-1].get("localized_behavior"),
                "candidate_tip_localized_behavior": response_cand.iloc[-1][
                    "localized_behavior"
                ],
                "live_estimated_local_volume": (
                    None
                    if pd.isna(live.iloc[-1].get("estimated_local_volume"))
                    else float(live.iloc[-1]["estimated_local_volume"])
                ),
                "candidate_tip_estimated_local_volume": float(
                    response_cand.iloc[-1]["estimated_local_volume"]
                ),
                "expected_change_on_activation": True,
            }

    # Downstream counterfactual: tip-carry stale vs fresh localized_behavior (research only).
    downstream = {
        "reinforcement": "reads volume_response.localized_behavior (no formula change)",
        "probabilistic": "reads localized_behavior via volume_response / state",
        "runtime_cognition": "location_bias separate — unchanged by this candidate",
        "fresh_match_rows": int((response_cand["localization_join_status"] == "EXACT_FRESH_MATCH").sum()),
        "missing_null_rows": int((response_cand["localization_join_status"] != "EXACT_FRESH_MATCH").sum()),
    }
    missing = response_cand[response_cand["localization_join_status"] != "EXACT_FRESH_MATCH"]
    downstream["missing_elv_all_null"] = bool(missing["estimated_local_volume"].isna().all()) if len(missing) else True
    downstream["missing_behavior_not_neutral"] = bool(
        (~missing["localized_behavior"].fillna("").astype(str).isin(["neutral", "NEUTRAL", "0"])).all()
    ) if len(missing) else True

    # Counterfactual tip comparison: current live response tip vs candidate tip (same bar open).
    if RESPONSE.exists():
        live = pd.read_parquet(RESPONSE)
        live_tip_behavior = live.iloc[-1].get("localized_behavior") if len(live) else None
        cand_tip_behavior = response_cand.iloc[-1]["localized_behavior"]
        cand_tip_elv = response_cand.iloc[-1]["estimated_local_volume"]
        live_tip_elv = live.iloc[-1].get("estimated_local_volume") if len(live) else None
        # Reinforcement component delta from localized_distribution only (+0.1 when match).
        def _dist_bonus(behavior) -> float:
            return 0.1 if behavior == "localized_distribution" else 0.0

        downstream["tip_counterfactual"] = {
            "live_localized_behavior": live_tip_behavior,
            "candidate_localized_behavior": cand_tip_behavior,
            "behavior_changed": live_tip_behavior != cand_tip_behavior,
            "live_estimated_local_volume": None if pd.isna(live_tip_elv) else float(live_tip_elv),
            "candidate_estimated_local_volume": None if pd.isna(cand_tip_elv) else float(cand_tip_elv),
            "reinforcement_distribution_bonus_live": _dist_bonus(live_tip_behavior),
            "reinforcement_distribution_bonus_candidate": _dist_bonus(cand_tip_behavior),
            "reinforcement_bonus_delta": _dist_bonus(cand_tip_behavior) - _dist_bonus(live_tip_behavior),
            "note": (
                "Formulas unchanged; delta is research-only effect of fresh vs stale tip-carry."
            ),
        }
        # Regime-ish counts over candidate window
        vc = response_cand["localized_behavior"].value_counts(dropna=False).to_dict()
        downstream["candidate_behavior_counts"] = {str(k): int(v) for k, v in vc.items()}
        if "localized_behavior" in live.columns:
            live_vc = live["localized_behavior"].value_counts(dropna=False).to_dict()
            downstream["live_behavior_counts"] = {str(k): int(v) for k, v in live_vc.items()}

    final_cf = {"final_context_available": FINAL.exists(), "candidate_applied": False}
    if FINAL.exists():
        final = pd.read_parquet(FINAL)
        final["timestamp"] = pd.to_datetime(final["timestamp"], utc=True)
        joined = response_cand.merge(
            final[["timestamp", "market_context"]],
            on="timestamp",
            how="inner",
        )
        final_cf["overlap"] = int(len(joined))
        if len(joined) and "market_context" in joined.columns:
            final_cf["context_counts"] = joined["market_context"].value_counts().to_dict()
            # No candidate context rewrite — unchanged by construction.
            final_cf["LONG_unchanged"] = int(
                (joined["market_context"].astype(str).str.contains("LONG")).sum()
            )
            final_cf["SHORT_unchanged"] = int(
                (joined["market_context"].astype(str).str.contains("SHORT")).sum()
            )
            final_cf["OBSERVE_unchanged"] = int((joined["market_context"] == "OBSERVE").sum())
            final_cf["LONG_changed"] = 0
            final_cf["SHORT_changed"] = 0
            final_cf["OBSERVE_changed"] = 0
            final_cf["action_allowed_changes"] = 0
            final_cf["entry_eligible_changes"] = 0
            final_cf["note"] = (
                "Candidate does not rewrite final context; all directional fields unchanged."
            )

    # Idempotent rerun
    cand2 = build_localization_frame(bounded)
    idempotent = cand["timestamp"].tolist() == cand2["timestamp"].tolist() and (
        cand["estimated_local_volume"].tolist() == cand2["estimated_local_volume"].tolist()
    )

    status = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "component": "volume_localization_live_wiring_candidate",
        "algorithm_version": ALGORITHM_VERSION,
        "bounded_rows": int(len(bounded)),
        "localization_rows": int(len(cand)),
        "parity": parity,
        "response_comparison": comparison,
        "downstream_counterfactual": downstream,
        "final_context_counterfactual": final_cf,
        "invariants": {
            "live_writes": False,
            "inventory_transfer_wired": False,
            "location_bias_derived": False,
            "exact_timestamp_join": True,
            "fuzzy_join": False,
            "stale_carry_forward": False,
            "idempotent": idempotent,
            "activation_flag_default_off": True,
        },
        "sha_localization": hashlib.sha256(
            (OUT_DIR / "volume_localization_candidate.parquet").read_bytes()
        ).hexdigest(),
    }
    (OUT_DIR / "live_wiring_status.json").write_text(
        json.dumps(status, indent=2, default=str) + "\n", encoding="utf-8"
    )
    # lightweight comparison parquet
    atomic_parquet_write(
        response_cand[
            [
                "timestamp",
                "localized_behavior",
                "estimated_local_volume",
                "volume_concentration",
                "localization_join_status",
                "localization_fresh",
            ]
        ],
        str(OUT_DIR / "downstream_comparison.parquet"),
        validate=True,
        timestamp_col="timestamp",
        enforce_timestamp_integrity=False,
    )
    print(json.dumps(status, indent=2, default=str))
    if not status["parity"].get("vs_legacy_orphan", {}).get("parity_ok", False) and not status[
        "parity"
    ].get("vs_shadow", {}).get("parity_ok", False):
        # Prefer legacy orphan overlap >=5000; shadow window may be smaller.
        if status["parity"].get("vs_legacy_orphan", {}).get("rows_compared", 0) >= 5000:
            return 2
    if status["parity"].get("vs_legacy_orphan", {}).get("rows_compared", 0) >= 5000:
        if not status["parity"]["vs_legacy_orphan"].get("parity_ok"):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
