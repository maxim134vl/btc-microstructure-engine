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


SOURCE_PATH = ROOT / "data/cognition/candle_structure_memory.parquet"

OUTPUT_DIR = ROOT / "data/research/volume_event_replay_mtf_v1"
ALL_BARS_PATH = OUTPUT_DIR / "all_bars.parquet"
EVENTS_PATH = OUTPUT_DIR / "events.parquet"
EVENT_COUNTS_PATH = OUTPUT_DIR / "event_counts.csv"
VOLUME_COUNTS_PATH = OUTPUT_DIR / "volume_class_counts.csv"
COVERAGE_PATH = OUTPUT_DIR / "coverage.csv"
REPORT_PATH = OUTPUT_DIR / "replay_report.json"


TIMEFRAMES = {
    "M15": {
        "rule": "15min",
        "source_bars": 1,
    },
    "M30": {
        "rule": "30min",
        "source_bars": 2,
    },
    "H1": {
        "rule": "1h",
        "source_bars": 4,
    },
    "H4": {
        "rule": "4h",
        "source_bars": 16,
    },
    "D1": {
        "rule": "1D",
        "source_bars": 96,
    },
}


TARGET_EVENTS = {
    "BUYING_CLIMAX",
    "SELLING_CLIMAX",
    "STOPPING_VOLUME",
}


EVENT_PRIORITY = {
    "STOPPING_VOLUME": 3,
    "SELLING_CLIMAX": 2,
    "HIGH_AVERAGE_VOLUME": 1,
}


TRACKED_SELL_SIDE_EVENTS = {
    "STOPPING_VOLUME",
    "SELLING_CLIMAX",
    "HIGH_AVERAGE_VOLUME",
}


def git_head() -> str:
    try:
        return subprocess.check_output(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            cwd=ROOT,
            text=True,
        ).strip()
    except Exception:
        return "UNKNOWN"


def load_base() -> pd.DataFrame:
    if not SOURCE_PATH.exists():
        raise RuntimeError(
            f"Missing source: {SOURCE_PATH}"
        )

    frame = pd.read_parquet(
        SOURCE_PATH
    ).copy()

    required = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    missing = [
        column
        for column in required
        if column not in frame.columns
    ]

    if missing:
        raise RuntimeError(
            f"Missing columns: {missing}"
        )

    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
    )

    frame = (
        frame
        .dropna(
            subset=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )
        .sort_values("timestamp")
        .drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    numeric = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for column in numeric:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

    if "taker_buy_volume" in frame.columns:
        frame["taker_buy_volume"] = pd.to_numeric(
            frame["taker_buy_volume"],
            errors="coerce",
        ).fillna(0.0)
    else:
        spread = (
            frame["high"]
            - frame["low"]
        )

        body_share = (
            (
                frame["close"]
                - frame["open"]
            ).abs()
            /
            (
                spread
                + 0.000001
            )
        ).clip(
            0.0,
            1.0,
        )

        bullish = (
            frame["close"]
            >= frame["open"]
        )

        frame["taker_buy_volume"] = np.where(
            bullish,
            frame["volume"]
            * (
                0.5
                + 0.5 * body_share
            ),
            frame["volume"]
            * (
                0.5
                - 0.5 * body_share
            ),
        )

    return frame[
        [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "taker_buy_volume",
        ]
    ].copy()


def aggregate_timeframe(
    base: pd.DataFrame,
    timeframe: str,
    rule: str,
    expected_source_bars: int,
) -> tuple[pd.DataFrame, dict]:
    if timeframe == "M15":
        frame = base.copy()
        frame["source_bar_count"] = 1

        coverage = {
            "timeframe": timeframe,
            "candidate_windows": int(
                len(frame)
            ),
            "complete_windows": int(
                len(frame)
            ),
            "dropped_incomplete_windows": 0,
        }

        return (
            frame.reset_index(drop=True),
            coverage,
        )

    indexed = (
        base
        .set_index("timestamp")
        .sort_index()
    )

    grouped = indexed.resample(
        rule,
        label="left",
        closed="left",
        origin="epoch",
    )

    frame = grouped.agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "taker_buy_volume": "sum",
        }
    )

    counts = grouped.size().rename(
        "source_bar_count"
    )

    frame = frame.join(
        counts,
        how="left",
    )

    candidate_windows = len(frame)

    frame = frame[
        frame["source_bar_count"]
        == expected_source_bars
    ].copy()

    frame = frame.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    )

    frame = (
        frame
        .reset_index()
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    coverage = {
        "timeframe": timeframe,
        "candidate_windows": int(
            candidate_windows
        ),
        "complete_windows": int(
            len(frame)
        ),
        "dropped_incomplete_windows": int(
            candidate_windows
            - len(frame)
        ),
    }

    return frame, coverage


def add_candle_structure(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    work = frame.copy()

    work["buy_volume"] = (
        work["taker_buy_volume"]
        .fillna(0.0)
    )

    work["sell_volume"] = (
        work["volume"]
        - work["buy_volume"]
    ).clip(
        lower=0.0
    )

    work["delta"] = (
        work["buy_volume"]
        - work["sell_volume"]
    )

    work["candle_type"] = np.where(
        work["close"]
        >= work["open"],
        "bullish",
        "bearish",
    )

    work["body"] = (
        work["close"]
        - work["open"]
    ).abs()

    work["spread"] = (
        work["high"]
        - work["low"]
    )

    work["upper_wick"] = (
        work["high"]
        - work[
            [
                "open",
                "close",
            ]
        ].max(axis=1)
    )

    work["lower_wick"] = (
        work[
            [
                "open",
                "close",
            ]
        ].min(axis=1)
        - work["low"]
    )

    work["close_position"] = (
        (
            work["close"]
            - work["low"]
        )
        /
        (
            work["spread"]
            + 0.000001
        )
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


def add_volume_class(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    work = frame.copy()

    work["volume_class"] = (
        "high_average"
    )

    low_volume = (
        work["volume_zscore"]
        < -0.7
    )

    work.loc[
        low_volume,
        "volume_class",
    ] = "low_small"

    buying_climax = (
        (
            work["candle_type"]
            == "bullish"
        )
        &
        (
            work["spread_zscore"]
            > 1.5
        )
        &
        (
            work["volume_zscore"]
            > 1.5
        )
    )

    selling_climax = (
        (
            work["candle_type"]
            == "bearish"
        )
        &
        (
            work["spread_zscore"]
            > 1.5
        )
        &
        (
            work["volume_zscore"]
            > 1.5
        )
    )

    work.loc[
        buying_climax,
        "volume_class",
    ] = "climax"

    work.loc[
        selling_climax,
        "volume_class",
    ] = "climax"

    stopping = (
        (
            work["candle_type"]
            == "bearish"
        )
        &
        (
            work["volume_zscore"]
            > 0.7
        )
        &
        (
            work["lower_wick"]
            > work["body"]
        )
        &
        (
            work["close_position"]
            > 0.5
        )
    )

    work.loc[
        stopping,
        "volume_class",
    ] = "stopping"

    return work


def add_auction_candidates(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    settings = get_ontology_settings()

    if not ontology_refinement_active(
        settings
    ):
        raise RuntimeError(
            "Causal replay requires refined ontology"
        )

    work = frame.copy()

    work["volume_percentile_50"] = (
        work["volume"]
        .rolling(
            50,
            min_periods=1,
        )
        .rank(
            pct=True
        )
    )

    work["spread_percentile_50"] = (
        work["spread"]
        .rolling(
            50,
            min_periods=1,
        )
        .rank(
            pct=True
        )
    )

    work["directional_efficiency"] = (
        work["spread"]
        / work["volume"]
    )

    work["efficiency_mean_20"] = (
        work[
            "directional_efficiency"
        ]
        .rolling(
            20,
            min_periods=1,
        )
        .mean()
    )

    work["efficiency_decay"] = (
        work[
            "directional_efficiency"
        ]
        /
        work[
            "efficiency_mean_20"
        ]
    )

    spread_nonzero = (
        work["spread"]
        .replace(
            0.0,
            np.nan,
        )
    )

    work["close_position_ratio"] = (
        (
            work["close"]
            - work["low"]
        )
        /
        spread_nonzero
    )

    work["lower_wick_ratio"] = (
        work["lower_wick"]
        /
        spread_nonzero
    )

    work["upper_wick_ratio"] = (
        work["upper_wick"]
        /
        spread_nonzero
    )

    work["rolling_high_50"] = (
        work["high"]
        .rolling(
            50,
            min_periods=1,
        )
        .max()
    )

    work["rolling_low_50"] = (
        work["low"]
        .rolling(
            50,
            min_periods=1,
        )
        .min()
    )

    rolling_range = (
        work["rolling_high_50"]
        - work["rolling_low_50"]
    ).replace(
        0.0,
        np.nan,
    )

    work["range_position"] = (
        (
            work["close"]
            - work["rolling_low_50"]
        )
        /
        rolling_range
    )

    work["event_strength"] = (
        (
            work["volume_percentile_50"]
            + work["spread_percentile_50"]
        )
        / 2.0
    )

    work["candidate_event_type"] = (
        "NORMAL"
    )

    work["location_bias"] = (
        "NEUTRAL"
    )

    buying_climax = (
        (
            work["volume_percentile_50"]
            >= 0.90
        )
        &
        (
            work["delta"]
            > 0
        )
        &
        (
            work["spread_percentile_50"]
            >= 0.60
        )
        &
        (
            (
                work["efficiency_decay"]
                < 0.80
            )
            |
            (
                work["efficiency_decay"]
                > 1.20
            )
        )
        &
        (
            work["range_position"]
            > 0.80
        )
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
        (
            work["volume_percentile_50"]
            >= 0.70
        )
        &
        (
            work["spread_percentile_50"]
            >= 0.30
        )
        &
        (
            work["spread_percentile_50"]
            < 0.50
        )
        &
        (
            work["efficiency_decay"]
            >= 0.90
        )
        &
        (
            work["range_position"]
            > 0.35
        )
        &
        (
            work["range_position"]
            < 0.65
        )
        &
        (
            work["candidate_event_type"]
            == "NORMAL"
        )
    )

    work.loc[
        high_average,
        "candidate_event_type",
    ] = "HIGH_AVERAGE_VOLUME"

    work.loc[
        high_average,
        "location_bias",
    ] = "MID_AUCTION_TRANSFER"

    previous_delta = (
        work["delta"]
        .shift(1)
    )

    work["delta_behavior_shift"] = (
        (
            work["delta"]
            - previous_delta
        )
        /
        (
            previous_delta.abs()
            + 1e-9
        )
    ).clip(
        -1.0,
        1.0,
    ).fillna(
        0.0
    )

    work[
        "recovery_structure_score"
    ] = (
        work[
            "close_position_ratio"
        ].fillna(0.5)
        * 0.65
        +
        work[
            "lower_wick_ratio"
        ].fillna(0.0)
        * 0.35
    ).clip(
        0.0,
        1.0,
    )

    work["effort_result_zone"] = (
        "AMBIGUOUS"
    )

    work.loc[
        work["efficiency_decay"]
        > settings.selling_climax_min_decay,
        "effort_result_zone",
    ] = "CAPITULATION"

    work.loc[
        work["efficiency_decay"]
        < settings.stopping_volume_max_decay,
        "effort_result_zone",
    ] = "ABSORPTION"

    delta_threshold = (
        work["delta"]
        .rolling(
            20,
            min_periods=5,
        )
        .quantile(
            0.35
        )
    )

    base_sell_side = (
        (
            work["volume_percentile_50"]
            >= 0.80
        )
        &
        (
            work["spread_percentile_50"]
            >= 0.45
        )
        &
        (
            work["delta"]
            < delta_threshold
        )
        &
        (
            work["range_position"]
            < 0.45
        )
        &
        (
            work["delta"]
            < 0
        )
    )

    stopping = (
        base_sell_side
        &
        (
            work["candidate_event_type"]
            == "NORMAL"
        )
        &
        (
            work["efficiency_decay"]
            < settings.stopping_volume_max_decay
        )
        &
        (
            (
                work["close_position_ratio"]
                >
                settings.stopping_min_close_position_ratio
            )
            |
            (
                work["recovery_structure_score"]
                >=
                settings.stopping_recovery_score_alt
            )
        )
        &
        (
            work["lower_wick_ratio"]
            >
            settings.stopping_min_lower_wick_ratio
        )
        &
        (
            (
                work["delta_behavior_shift"]
                >
                settings.stopping_min_delta_shift
            )
            |
            (
                work["recovery_structure_score"]
                >=
                settings.stopping_recovery_score_alt
            )
        )
        &
        (
            work["effort_result_zone"]
            == "ABSORPTION"
        )
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
        &
        (
            work["candidate_event_type"]
            == "NORMAL"
        )
        &
        (
            work["efficiency_decay"]
            >
            settings.selling_climax_min_decay
        )
        &
        (
            work["close_position_ratio"]
            < 0.25
        )
        &
        (
            work["lower_wick_ratio"]
            <
            settings.selling_max_lower_wick_ratio
        )
        &
        (
            work["delta_behavior_shift"]
            <=
            settings.selling_max_delta_shift
        )
        &
        (
            work["effort_result_zone"]
            == "CAPITULATION"
        )
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


def apply_causal_cluster_filter(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    settings = get_ontology_settings()

    work = frame.copy().reset_index(
        drop=True
    )

    emitted = []
    cluster_ids = []

    cluster_id = -1
    last_tracked_position = None
    best_score = None

    for position, row in work.iterrows():
        event = row[
            "candidate_event_type"
        ]

        range_position = row.get(
            "range_position",
            np.nan,
        )

        if (
            event
            not in TRACKED_SELL_SIDE_EVENTS
            or pd.isna(range_position)
            or float(range_position) >= 0.45
        ):
            emitted.append(event)
            cluster_ids.append(-1)
            continue

        new_cluster = (
            last_tracked_position is None
            or
            (
                position
                - last_tracked_position
            )
            >
            settings.swing_cluster_window
        )

        score = (
            EVENT_PRIORITY.get(
                event,
                0,
            ),
            float(
                row.get(
                    "event_strength",
                    0.0,
                )
                or 0.0
            ),
            position,
        )

        if new_cluster:
            cluster_id += 1
            best_score = score
            emitted_event = event
        else:
            if (
                best_score is None
                or score > best_score
            ):
                best_score = score
                emitted_event = event
            else:
                emitted_event = "NORMAL"

        emitted.append(
            emitted_event
        )

        cluster_ids.append(
            cluster_id
        )

        last_tracked_position = (
            position
        )

    work["auction_event_type"] = (
        emitted
    )

    work["causal_cluster_id"] = (
        cluster_ids
    )

    return work


def add_gate_match(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    work = frame.copy()

    work["volume_gate_match"] = (
        pd.NA
    )

    climax_mask = (
        work["auction_event_type"]
        .isin(
            [
                "BUYING_CLIMAX",
                "SELLING_CLIMAX",
            ]
        )
    )

    stopping_mask = (
        work["auction_event_type"]
        == "STOPPING_VOLUME"
    )

    work.loc[
        climax_mask,
        "volume_gate_match",
    ] = (
        work.loc[
            climax_mask,
            "volume_class",
        ]
        .eq("climax")
    )

    work.loc[
        stopping_mask,
        "volume_gate_match",
    ] = (
        work.loc[
            stopping_mask,
            "volume_class",
        ]
        .eq("stopping")
    )

    return work


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    settings = get_ontology_settings()

    print(
        "GIT_HEAD",
        git_head(),
    )

    print(
        "ONTOLOGY_REFINEMENT_ACTIVE",
        ontology_refinement_active(
            settings
        ),
    )

    print(
        "SWING_CLUSTER_WINDOW",
        settings.swing_cluster_window,
    )

    base = load_base()

    print(
        "BASE_ROWS",
        len(base),
    )

    print(
        "BASE_RANGE",
        base["timestamp"].min(),
        base["timestamp"].max(),
    )

    all_frames = []
    coverage_rows = []

    for timeframe, config in TIMEFRAMES.items():
        aggregated, coverage = (
            aggregate_timeframe(
                base=base,
                timeframe=timeframe,
                rule=config["rule"],
                expected_source_bars=config[
                    "source_bars"
                ],
            )
        )

        structured = (
            add_candle_structure(
                aggregated
            )
        )

        classified = (
            add_volume_class(
                structured
            )
        )

        candidates = (
            add_auction_candidates(
                classified
            )
        )

        replayed = (
            apply_causal_cluster_filter(
                candidates
            )
        )

        replayed = (
            add_gate_match(
                replayed
            )
        )

        replayed["timeframe"] = (
            timeframe
        )

        replayed["timeframe_minutes"] = {
            "M15": 15,
            "M30": 30,
            "H1": 60,
            "H4": 240,
            "D1": 1440,
        }[timeframe]

        coverage[
            "start_timestamp"
        ] = (
            replayed["timestamp"].min()
            if len(replayed)
            else None
        )

        coverage[
            "end_timestamp"
        ] = (
            replayed["timestamp"].max()
            if len(replayed)
            else None
        )

        coverage_rows.append(
            coverage
        )

        all_frames.append(
            replayed
        )

    all_bars = pd.concat(
        all_frames,
        ignore_index=True,
    )

    events = all_bars[
        all_bars[
            "auction_event_type"
        ].isin(
            TARGET_EVENTS
        )
    ].copy()

    event_counts = (
        events
        .groupby(
            [
                "timeframe",
                "auction_event_type",
            ],
            dropna=False,
        )
        .size()
        .reset_index(
            name="cases"
        )
    )

    volume_counts = (
        all_bars
        .groupby(
            [
                "timeframe",
                "volume_class",
            ],
            dropna=False,
        )
        .size()
        .reset_index(
            name="bars"
        )
    )

    coverage = pd.DataFrame(
        coverage_rows
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

    volume_counts.to_csv(
        VOLUME_COUNTS_PATH,
        index=False,
    )

    coverage.to_csv(
        COVERAGE_PATH,
        index=False,
    )

    gate = (
        events
        .groupby(
            [
                "timeframe",
                "auction_event_type",
            ],
            dropna=False,
        )["volume_gate_match"]
        .agg(
            cases="size",
            gate_matches=lambda x: int(
                x.fillna(False)
                .astype(bool)
                .sum()
            ),
        )
        .reset_index()
    )

    gate["gate_match_pct"] = (
        gate["gate_matches"]
        / gate["cases"]
        * 100.0
    )

    report = {
        "git_head": git_head(),
        "source": str(
            SOURCE_PATH
        ),
        "base_rows": int(
            len(base)
        ),
        "base_start": str(
            base["timestamp"].min()
        ),
        "base_end": str(
            base["timestamp"].max()
        ),
        "total_replay_bars": int(
            len(all_bars)
        ),
        "target_event_rows": int(
            len(events)
        ),
        "ontology_refinement_active": bool(
            ontology_refinement_active(
                settings
            )
        ),
        "swing_cluster_window": int(
            settings.swing_cluster_window
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
    print("COVERAGE")
    print(
        coverage.to_string(
            index=False
        )
    )

    print()
    print("VOLUME_CLASS_COUNTS")
    print(
        volume_counts.to_string(
            index=False
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
    print("VOLUME_GATE_MATCH")
    print(
        gate.to_string(
            index=False
        )
    )

    print()
    print(
        "ALL_BARS",
        ALL_BARS_PATH,
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
    raise SystemExit(
        main()
    )
