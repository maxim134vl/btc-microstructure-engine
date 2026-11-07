from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ontology_config import get_ontology_settings, ontology_refinement_active


INPUT_DIR = ROOT / "data/research/binance_native_ohlcv_v1"
OUTPUT_DIR = ROOT / "data/research/binance_native_volume_events_v1"

ALL_BARS_PATH = OUTPUT_DIR / "all_timeframes.parquet"
EVENTS_PATH = OUTPUT_DIR / "events.parquet"
EVENT_COUNTS_PATH = OUTPUT_DIR / "event_counts.csv"
MONTHLY_COUNTS_PATH = OUTPUT_DIR / "monthly_event_counts.csv"
REPORT_PATH = OUTPUT_DIR / "replay_report.json"

ANALYSIS_START = pd.Timestamp("2026-05-02T00:00:00Z")

TIMEFRAMES = {
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

TARGET_EVENTS = {
    "BUYING_CLIMAX",
    "SELLING_CLIMAX",
    "STOPPING_VOLUME",
}

TRACKED_SELL_SIDE_EVENTS = {
    "STOPPING_VOLUME",
    "SELLING_CLIMAX",
    "HIGH_AVERAGE_VOLUME",
}

EVENT_PRIORITY = {
    "STOPPING_VOLUME": 3,
    "SELLING_CLIMAX": 2,
    "HIGH_AVERAGE_VOLUME": 1,
}


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except Exception:
        return "UNKNOWN"


def load_native(timeframe: str) -> pd.DataFrame:
    path = INPUT_DIR / f"{timeframe}_native.parquet"

    if not path.exists():
        raise RuntimeError(f"Missing file: {path}")

    frame = pd.read_parquet(path).copy()

    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
    )

    required = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "taker_buy_volume",
    ]

    missing = [
        column
        for column in required
        if column not in frame.columns
    ]

    if missing:
        raise RuntimeError(
            f"{timeframe} missing columns: {missing}"
        )

    frame = (
        frame
        .dropna(subset=required)
        .sort_values("timestamp")
        .drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return frame


def add_candle_structure(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()

    work["buy_volume"] = pd.to_numeric(
        work["taker_buy_volume"],
        errors="coerce",
    ).fillna(0.0)

    work["volume"] = pd.to_numeric(
        work["volume"],
        errors="coerce",
    )

    work["sell_volume"] = (
        work["volume"] - work["buy_volume"]
    ).clip(lower=0.0)

    work["delta"] = (
        work["buy_volume"] - work["sell_volume"]
    )

    work["candle_type"] = np.where(
        work["close"] >= work["open"],
        "bullish",
        "bearish",
    )

    work["body"] = (
        work["close"] - work["open"]
    ).abs()

    work["spread"] = (
        work["high"] - work["low"]
    )

    work["upper_wick"] = (
        work["high"]
        - work[["open", "close"]].max(axis=1)
    )

    work["lower_wick"] = (
        work[["open", "close"]].min(axis=1)
        - work["low"]
    )

    spread_safe = work["spread"].replace(
        0.0,
        np.nan,
    )

    work["close_position"] = (
        (work["close"] - work["low"])
        / (work["spread"] + 0.000001)
    )

    work["close_position_ratio"] = (
        (work["close"] - work["low"])
        / spread_safe
    )

    work["lower_wick_ratio"] = (
        work["lower_wick"] / spread_safe
    )

    work["upper_wick_ratio"] = (
        work["upper_wick"] / spread_safe
    )

    work["spread_mean_20"] = (
        work["spread"]
        .rolling(20)
        .mean()
    )

    work["spread_std_20"] = (
        work["spread"]
        .rolling(20)
        .std()
    )

    work["volume_mean_20"] = (
        work["volume"]
        .rolling(10)
        .mean()
    )

    work["volume_std_20"] = (
        work["volume"]
        .rolling(10)
        .std()
    )

    work["spread_zscore"] = (
        (
            work["spread"]
            - work["spread_mean_20"]
        )
        /
        (
            work["spread_std_20"]
            + 0.000001
        )
    )

    work["volume_zscore"] = (
        (
            work["volume"]
            - work["volume_mean_20"]
        )
        /
        (
            work["volume_std_20"]
            + 0.000001
        )
    )

    return work


def add_coarse_volume_class(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()

    work["volume_class"] = "high_average"

    work.loc[
        work["volume_zscore"] < -0.7,
        "volume_class",
    ] = "low_small"

    climax = (
        work["spread_zscore"].gt(1.5)
        & work["volume_zscore"].gt(1.5)
    )

    work.loc[
        climax,
        "volume_class",
    ] = "climax"

    stopping = (
        work["candle_type"].eq("bearish")
        & work["volume_zscore"].gt(0.7)
        & work["lower_wick"].gt(work["body"])
        & work["close_position"].gt(0.5)
    )

    work.loc[
        stopping,
        "volume_class",
    ] = "stopping"

    return work


def add_auction_features(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()

    work["volume_percentile_50"] = (
        work["volume"]
        .rolling(50, min_periods=1)
        .rank(pct=True)
    )

    work["spread_percentile_50"] = (
        work["spread"]
        .rolling(50, min_periods=1)
        .rank(pct=True)
    )

    work["directional_efficiency"] = (
        work["spread"]
        / work["volume"].replace(0.0, np.nan)
    )

    work["efficiency_mean_20"] = (
        work["directional_efficiency"]
        .rolling(20, min_periods=1)
        .mean()
    )

    work["efficiency_decay"] = (
        work["directional_efficiency"]
        /
        work["efficiency_mean_20"].replace(
            0.0,
            np.nan,
        )
    )

    work["rolling_high_50"] = (
        work["high"]
        .rolling(50, min_periods=1)
        .max()
    )

    work["rolling_low_50"] = (
        work["low"]
        .rolling(50, min_periods=1)
        .min()
    )

    rolling_range = (
        work["rolling_high_50"]
        - work["rolling_low_50"]
    ).replace(0.0, np.nan)

    work["range_position"] = (
        (
            work["close"]
            - work["rolling_low_50"]
        )
        / rolling_range
    )

    work["event_strength"] = (
        work["volume_percentile_50"]
        + work["spread_percentile_50"]
    ) / 2.0

    previous_delta = work["delta"].shift(1)

    work["delta_behavior_shift"] = (
        (
            work["delta"] - previous_delta
        )
        /
        (
            previous_delta.abs() + 1e-9
        )
    ).clip(
        -1.0,
        1.0,
    ).fillna(0.0)

    work["recovery_structure_score"] = (
        work["close_position_ratio"]
        .fillna(0.5)
        * 0.65
        +
        work["lower_wick_ratio"]
        .fillna(0.0)
        * 0.35
    ).clip(
        0.0,
        1.0,
    )

    return work


def classify_events(frame: pd.DataFrame) -> pd.DataFrame:
    settings = get_ontology_settings()

    if not ontology_refinement_active(settings):
        raise RuntimeError(
            "Refined ontology must be active"
        )

    work = frame.copy()

    work["candidate_event_type"] = "NORMAL"
    work["location_bias"] = "NEUTRAL"

    buying_climax = (
        work["volume_percentile_50"].ge(0.90)
        & work["delta"].gt(0)
        & work["spread_percentile_50"].ge(0.60)
        & (
            work["efficiency_decay"].lt(0.80)
            | work["efficiency_decay"].gt(1.20)
        )
        & work["range_position"].gt(0.80)
    )

    work.loc[
        buying_climax,
        "candidate_event_type",
    ] = "BUYING_CLIMAX"

    work.loc[
        buying_climax,
        "location_bias",
    ] = "UPPER_DISTRIBUTION"

    high_average = (
        work["volume_percentile_50"].ge(0.70)
        & work["spread_percentile_50"].ge(0.30)
        & work["spread_percentile_50"].lt(0.50)
        & work["efficiency_decay"].ge(0.90)
        & work["range_position"].gt(0.35)
        & work["range_position"].lt(0.65)
        & work["candidate_event_type"].eq("NORMAL")
    )

    work.loc[
        high_average,
        "candidate_event_type",
    ] = "HIGH_AVERAGE_VOLUME"

    work.loc[
        high_average,
        "location_bias",
    ] = "MID_AUCTION_TRANSFER"

    work["effort_result_zone"] = "AMBIGUOUS"

    work.loc[
        work["efficiency_decay"].gt(
            settings.selling_climax_min_decay
        ),
        "effort_result_zone",
    ] = "CAPITULATION"

    work.loc[
        work["efficiency_decay"].lt(
            settings.stopping_volume_max_decay
        ),
        "effort_result_zone",
    ] = "ABSORPTION"

    delta_threshold = (
        work["delta"]
        .rolling(
            20,
            min_periods=5,
        )
        .quantile(0.35)
    )

    base_sell_side = (
        work["volume_percentile_50"].ge(0.80)
        & work["spread_percentile_50"].ge(0.45)
        & work["delta"].lt(delta_threshold)
        & work["range_position"].lt(0.45)
        & work["delta"].lt(0)
    )

    stopping = (
        base_sell_side
        & work["candidate_event_type"].eq("NORMAL")
        & work["efficiency_decay"].lt(
            settings.stopping_volume_max_decay
        )
        & (
            work["close_position_ratio"].gt(
                settings.stopping_min_close_position_ratio
            )
            |
            work["recovery_structure_score"].ge(
                settings.stopping_recovery_score_alt
            )
        )
        & work["lower_wick_ratio"].gt(
            settings.stopping_min_lower_wick_ratio
        )
        & (
            work["delta_behavior_shift"].gt(
                settings.stopping_min_delta_shift
            )
            |
            work["recovery_structure_score"].ge(
                settings.stopping_recovery_score_alt
            )
        )
        & work["effort_result_zone"].eq("ABSORPTION")
    )

    work.loc[
        stopping,
        "candidate_event_type",
    ] = "STOPPING_VOLUME"

    work.loc[
        stopping,
        "location_bias",
    ] = "LOWER_ABSORPTION"

    selling_climax = (
        base_sell_side
        & work["candidate_event_type"].eq("NORMAL")
        & work["efficiency_decay"].gt(
            settings.selling_climax_min_decay
        )
        & work["close_position_ratio"].lt(0.25)
        & work["lower_wick_ratio"].lt(
            settings.selling_max_lower_wick_ratio
        )
        & work["delta_behavior_shift"].le(
            settings.selling_max_delta_shift
        )
        & work["effort_result_zone"].eq("CAPITULATION")
    )

    work.loc[
        selling_climax,
        "candidate_event_type",
    ] = "SELLING_CLIMAX"

    work.loc[
        selling_climax,
        "location_bias",
    ] = "LOWER_CAPITULATION"

    return work


def apply_online_cluster_filter(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    settings = get_ontology_settings()

    work = frame.copy().reset_index(drop=True)

    emitted_events = []
    cluster_ids = []
    suppressed_flags = []

    cluster_id = -1
    last_sell_side_position = None
    current_best_score = None

    for position, row in work.iterrows():
        event = row["candidate_event_type"]

        range_position = row.get(
            "range_position",
            np.nan,
        )

        eligible_cluster_event = (
            event in TRACKED_SELL_SIDE_EVENTS
            and pd.notna(range_position)
            and float(range_position) < 0.45
        )

        if not eligible_cluster_event:
            emitted_events.append(event)
            cluster_ids.append(-1)
            suppressed_flags.append(False)
            continue

        new_cluster = (
            last_sell_side_position is None
            or
            (
                position - last_sell_side_position
            )
            > settings.swing_cluster_window
        )

        score = (
            EVENT_PRIORITY.get(event, 0),
            float(
                row.get(
                    "event_strength",
                    0.0,
                )
                or 0.0
            ),
        )

        if new_cluster:
            cluster_id += 1
            current_best_score = score
            emitted_event = event
            suppressed = False

        else:
            if (
                current_best_score is None
                or score > current_best_score
            ):
                current_best_score = score
                emitted_event = event
                suppressed = False
            else:
                emitted_event = "NORMAL"
                suppressed = True

        emitted_events.append(
            emitted_event
        )

        cluster_ids.append(
            cluster_id
        )

        suppressed_flags.append(
            suppressed
        )

        last_sell_side_position = position

    work["auction_event_type"] = emitted_events
    work["causal_cluster_id"] = cluster_ids
    work["cluster_suppressed"] = suppressed_flags

    return work


def add_gate_diagnostic(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()

    work["coarse_volume_gate_match"] = pd.NA

    climax = work["auction_event_type"].isin(
        [
            "BUYING_CLIMAX",
            "SELLING_CLIMAX",
        ]
    )

    stopping = work["auction_event_type"].eq(
        "STOPPING_VOLUME"
    )

    work.loc[
        climax,
        "coarse_volume_gate_match",
    ] = (
        work.loc[
            climax,
            "volume_class",
        ].eq("climax")
    )

    work.loc[
        stopping,
        "coarse_volume_gate_match",
    ] = (
        work.loc[
            stopping,
            "volume_class",
        ].eq("stopping")
    )

    return work


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    settings = get_ontology_settings()

    print("GIT_HEAD", git_head())
    print(
        "ONTOLOGY_REFINEMENT_ACTIVE",
        ontology_refinement_active(settings),
    )
    print(
        "ANALYSIS_START",
        ANALYSIS_START,
    )

    all_frames = []

    for timeframe, minutes in TIMEFRAMES.items():
        frame = load_native(timeframe)

        frame = add_candle_structure(frame)
        frame = add_coarse_volume_class(frame)
        frame = add_auction_features(frame)
        frame = classify_events(frame)
        frame = apply_online_cluster_filter(frame)
        frame = add_gate_diagnostic(frame)

        frame["timeframe"] = timeframe
        frame["timeframe_minutes"] = minutes

        frame["analysis_eligible"] = (
            frame["timestamp"] >= ANALYSIS_START
        )

        all_frames.append(frame)

    all_bars = pd.concat(
        all_frames,
        ignore_index=True,
    )

    events = all_bars[
        all_bars["analysis_eligible"]
        & all_bars[
            "auction_event_type"
        ].isin(TARGET_EVENTS)
    ].copy()

    events["month"] = (
        events["timestamp"]
        .dt.strftime("%Y-%m")
    )

    event_counts = (
        events
        .groupby(
            [
                "timeframe",
                "auction_event_type",
            ]
        )
        .size()
        .reset_index(name="cases")
    )

    monthly_counts = (
        events
        .groupby(
            [
                "timeframe",
                "month",
                "auction_event_type",
            ]
        )
        .size()
        .reset_index(name="cases")
    )

    all_bars.to_parquet(
        ALL_BARS_PATH,
        index=False,
    )

    events.to_parquet(
        EVENTS_PATH,
        index=False,
    )

    event_counts.to_csv(
        EVENT_COUNTS_PATH,
        index=False,
    )

    monthly_counts.to_csv(
        MONTHLY_COUNTS_PATH,
        index=False,
    )

    gate = (
        events
        .groupby(
            [
                "timeframe",
                "auction_event_type",
            ]
        )["coarse_volume_gate_match"]
        .agg(
            cases="size",
            matches=lambda series: int(
                series.fillna(False)
                .astype(bool)
                .sum()
            ),
        )
        .reset_index()
    )

    gate["match_pct"] = (
        gate["matches"]
        / gate["cases"]
        * 100.0
    )

    report = {
        "git_head": git_head(),
        "analysis_start": str(
            ANALYSIS_START
        ),
        "event_rows": int(
            len(events)
        ),
        "ontology_refinement_active": bool(
            ontology_refinement_active(settings)
        ),
        "timeframes": list(
            TIMEFRAMES.keys()
        ),
    }

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    print()
    print("EVENT_COUNTS")
    print(
        event_counts.to_string(
            index=False
        )
    )

    print()
    print("MONTHLY_EVENT_COUNTS")
    print(
        monthly_counts.to_string(
            index=False
        )
    )

    print()
    print("COARSE_VOLUME_GATE_DIAGNOSTIC")
    print(
        gate.to_string(
            index=False
        )
    )

    print()
    print(
        "TOTAL_EVENTS",
        len(events),
    )

    print(
        "EVENTS",
        EVENTS_PATH,
    )

    print(
        "REPORT",
        REPORT_PATH,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
