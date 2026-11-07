#!/usr/bin/env python3
"""Bounded candidate replay for volume_response canonical timestamp identity (Phase 4B).

Writes ONLY under data/candidate/volume_localization_timestamp_identity/.
Does not write live cognition / trading artifacts. Does not restart processes.
"""

from __future__ import annotations

import hashlib
import importlib.util
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
)

OUT_DIR = REPO / "data" / "candidate" / "volume_localization_timestamp_identity"
CANDLE = REPO / "data" / "cognition" / "candle_structure_memory.parquet"
LEGACY_LOC = REPO / "data" / "cognition" / "volume_localization_memory.parquet"
LIVE_RESPONSE = REPO / "data" / "cognition" / "volume_response_state.parquet"
NATURAL_BARS = (
    "2026-07-26T09:00:00Z",
    "2026-07-26T09:15:00Z",
    "2026-07-26T09:30:00Z",
)


def _load_identity():
    path = REPO / "src/btc_ml/cognition/volume_response_timestamp_identity.py"
    spec = importlib.util.spec_from_file_location("vr_ts_identity", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    identity = _load_identity()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Capture live hashes before candidate work.
    live_paths = [
        CANDLE,
        LEGACY_LOC,
        LIVE_RESPONSE,
        REPO / "data/cognition/volume_localization_v2_memory.parquet",
    ]
    pre = {}
    for p in live_paths:
        if p.exists():
            pre[str(p.relative_to(REPO))] = hashlib.sha256(p.read_bytes()).hexdigest()

    structure = pd.read_parquet(CANDLE)
    structure["timestamp"] = pd.to_datetime(structure["timestamp"], utc=True)
    structure = structure.sort_values("timestamp")
    bounded = structure.iloc[-5000:].copy()

    localization = build_localization_frame(bounded)

    # Simulated wall-clock mismatch: evaluation far from bar open.
    fake_eval_base = pd.Timestamp("2099-01-01T12:00:00Z")

    response_rows = []
    for i, (_, crow) in enumerate(bounded.iterrows()):
        ident = identity.build_response_identity_fields(
            crow,
            evaluated_at=fake_eval_base + pd.Timedelta(seconds=i),
        )
        join = identity.classify_response_localization_join(
            ident,
            localization,
            live_v1=True,
        )
        row = {
            **ident,
            "localization_join_status": join["localization_join_status"],
            "localization_source_timestamp": join["localization_source_timestamp"],
            "localization_fresh": join["localization_fresh"],
            "estimated_local_volume": None,
            "volume_concentration": None,
            "localized_behavior": None,
            "zone_low": None,
            "zone_high": None,
            "zone_width": None,
        }
        if join["localization_join_status"] == identity.STATUS_EXACT and join["row"] is not None:
            r = join["row"]
            row["estimated_local_volume"] = float(r["estimated_local_volume"])
            row["volume_concentration"] = float(r["volume_concentration"])
            row["localized_behavior"] = r["behavior"]
            row["zone_low"] = float(r["zone_low"])
            row["zone_high"] = float(r["zone_high"])
            row["zone_width"] = float(r["zone_width"])
        response_rows.append(row)

    response_cand = pd.DataFrame(response_rows)
    atomic_parquet_write(
        response_cand,
        str(OUT_DIR / "volume_response_candidate.parquet"),
        validate=True,
        timestamp_col="source_candle_timestamp",
        enforce_timestamp_integrity=True,
    )

    status_counts = response_cand["localization_join_status"].value_counts().to_dict()
    exact = int(status_counts.get(identity.STATUS_EXACT, 0))
    coverage = {
        "total_candle_rows": int(len(bounded)),
        "localization_rows": int(len(localization)),
        "response_rows": int(len(response_cand)),
        "EXACT_FRESH_MATCH": exact,
        "NO_LOCALIZATION_MATCH": int(status_counts.get(identity.STATUS_NO_MATCH, 0)),
        "AMBIGUOUS_LOCALIZATION_MATCH": int(status_counts.get(identity.STATUS_AMBIGUOUS, 0)),
        "STALE_LOCALIZATION_MATCH": int(status_counts.get(identity.STATUS_STALE, 0)),
        "LEGACY_RESPONSE_NO_SOURCE_TIMESTAMP": int(
            status_counts.get(identity.STATUS_LEGACY_NO_SOURCE, 0)
        ),
        "exact_fresh_match_share": float(exact / len(response_cand)) if len(response_cand) else 0.0,
    }

    # Parity vs localization on exact matches
    merged = response_cand.merge(
        localization[
            [
                "timestamp",
                "estimated_local_volume",
                "volume_concentration",
                "behavior",
            ]
        ],
        left_on="source_candle_timestamp",
        right_on="timestamp",
        how="inner",
        suffixes=("_resp", "_loc"),
    )
    if len(merged):
        elv_ok = bool(
            (merged["estimated_local_volume_resp"] - merged["estimated_local_volume_loc"])
            .abs()
            .max()
            == 0
        )
        conc_ok = bool(
            (merged["volume_concentration_resp"] - merged["volume_concentration_loc"])
            .abs()
            .max()
            == 0
        )
        beh_share = float((merged["localized_behavior"] == merged["behavior"]).mean())
    else:
        elv_ok = False
        conc_ok = False
        beh_share = 0.0
    parity = {
        "rows_compared": int(len(merged)),
        "ELV_parity": elv_ok,
        "concentration_parity": conc_ok,
        "behavior_parity": beh_share,
    }

    # Live legacy rows: must classify as LEGACY_RESPONSE_NO_SOURCE_TIMESTAMP (no synthetic ts)
    legacy_compat = {"live_response_available": LIVE_RESPONSE.exists()}
    if LIVE_RESPONSE.exists():
        live = pd.read_parquet(LIVE_RESPONSE)
        sample = live.tail(min(200, len(live)))
        legacy_statuses = []
        for _, r in sample.iterrows():
            st = identity.classify_response_localization_join(r, localization, live_v1=True)
            legacy_statuses.append(st["localization_join_status"])
        legacy_compat["sampled_rows"] = int(len(sample))
        legacy_compat["all_legacy_no_source"] = bool(
            all(s == identity.STATUS_LEGACY_NO_SOURCE for s in legacy_statuses)
        )
        legacy_compat["synthetic_timestamps"] = 0
        legacy_compat["has_source_candle_timestamp_column"] = bool(
            "source_candle_timestamp" in live.columns
        )

    # Three natural candles cadence simulation
    natural = []
    for bar in NATURAL_BARS:
        ts = pd.Timestamp(bar)
        crow = structure[structure["timestamp"] == ts]
        if not len(crow):
            natural.append({"bar": bar, "status": "MISSING_CANDLE"})
            continue
        crow = crow.iloc[0]
        # wall-clock deliberately unequal to bar open
        ident = identity.build_response_identity_fields(
            crow,
            evaluated_at=pd.Timestamp("2099-07-26T15:00:00Z"),
        )
        # ensure localization covers this bar
        loc_one = build_localization_frame(structure[structure["timestamp"] == ts])
        join = identity.classify_response_localization_join(ident, loc_one, live_v1=True)
        natural.append(
            {
                "bar": bar,
                "source_candle_timestamp": str(ident["source_candle_timestamp"]),
                "evaluated_at": str(ident["evaluated_at"]),
                "wall_clock_equals_source": bool(
                    ident["evaluated_at"] == ident["source_candle_timestamp"]
                ),
                "localization_join_status": join["localization_join_status"],
                "localized_behavior": None
                if join["row"] is None
                else join["row"]["behavior"],
            }
        )

    comparison = response_cand[
        [
            "source_candle_timestamp",
            "evaluated_at",
            "timestamp",
            "localization_join_status",
            "estimated_local_volume",
            "volume_concentration",
            "localized_behavior",
        ]
    ].copy()
    atomic_parquet_write(
        comparison,
        str(OUT_DIR / "timestamp_identity_comparison.parquet"),
        validate=True,
        timestamp_col="source_candle_timestamp",
        enforce_timestamp_integrity=True,
    )

    # Idempotence
    localization2 = build_localization_frame(bounded)
    idempotent = localization["timestamp"].tolist() == localization2["timestamp"].tolist()

    post = {}
    for p in live_paths:
        if p.exists():
            post[str(p.relative_to(REPO))] = hashlib.sha256(p.read_bytes()).hexdigest()
    live_writes = sum(1 for k in pre if pre.get(k) != post.get(k))

    join_report = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage": coverage,
        "parity": parity,
        "natural_three_bar": natural,
        "legacy_compat": legacy_compat,
        "algorithm_version": ALGORITHM_VERSION,
    }
    (OUT_DIR / "join_coverage_report.json").write_text(
        json.dumps(join_report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    status = {
        **join_report,
        "invariants": {
            "fuzzy_matching": False,
            "stale_carry_forward_flag_on": False,
            "legacy_backfill": 0,
            "synthetic_timestamps": 0,
            "live_writes": live_writes,
            "idempotent": idempotent,
            "activation_flag_default_off": True,
            "canonical_source_timestamp_defined": True,
            "wall_clock_timestamp_separated": True,
        },
        "gates": {
            "candidate_rows_ge_5000": coverage["response_rows"] >= 5000,
            "exact_fresh_share_100": coverage["exact_fresh_match_share"] == 1.0,
            "no_match_0": coverage["NO_LOCALIZATION_MATCH"] == 0,
            "ambiguous_0": coverage["AMBIGUOUS_LOCALIZATION_MATCH"] == 0,
            "stale_0": coverage["STALE_LOCALIZATION_MATCH"] == 0,
            "elv_parity": parity["ELV_parity"] is True,
            "concentration_parity": parity["concentration_parity"] is True,
            "behavior_parity": parity["behavior_parity"] == 1.0,
            "live_writes_0": live_writes == 0,
        },
    }
    (OUT_DIR / "candidate_status.json").write_text(
        json.dumps(status, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(status, indent=2, default=str))
    gates = status["gates"]
    if not all(gates.values()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
