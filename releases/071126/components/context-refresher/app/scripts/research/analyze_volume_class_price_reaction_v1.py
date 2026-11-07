from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

VOLUME_PATH = ROOT / "data/cognition/volume_response_state.parquet"
PRICE_PATH = ROOT / "data/cognition/candle_structure_memory.parquet"

OUTPUT_DIR = ROOT / "data/research/volume_class_price_reaction_v1"
EVENTS_PATH = OUTPUT_DIR / "volume_class_price_reactions.parquet"
SUMMARY_PATH = OUTPUT_DIR / "volume_class_price_reaction_summary.csv"

HORIZONS = {
    "M15": 1,
    "M30": 2,
    "H1": 4,
    "H2": 8,
    "H4": 16,
}


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    volume = pd.read_parquet(VOLUME_PATH)
    price = pd.read_parquet(PRICE_PATH)

    price["timestamp"] = pd.to_datetime(
        price["timestamp"],
        utc=True,
        errors="coerce",
    )

    price = (
        price.dropna(subset=["timestamp"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )

    return volume, price


def prepare_volume_events(volume: pd.DataFrame) -> pd.DataFrame:
    work = volume.copy()

    work["timestamp"] = pd.to_datetime(
        work["timestamp"],
        utc=True,
        errors="coerce",
    )

    if "source_candle_timestamp" in work.columns:
        explicit = pd.to_datetime(
            work["source_candle_timestamp"],
            utc=True,
            errors="coerce",
        )
    else:
        explicit = pd.Series(
            pd.NaT,
            index=work.index,
            dtype="datetime64[ns, UTC]",
        )

    legacy = work["timestamp"].dt.floor("15min")

    work["source_bar_timestamp"] = explicit.fillna(legacy)

    work["identity_mode"] = np.where(
        explicit.notna(),
        "EXPLICIT_M15",
        "LEGACY_TIMESTAMP_FLOOR",
    )

    if "source_timeframe" in work.columns:
        source_tf = (
            work["source_timeframe"]
            .fillna("")
            .astype(str)
            .str.upper()
        )

        valid_tf = source_tf.isin(
            [
                "",
                "M15",
            ]
        )

        work = work[valid_tf].copy()

    work["volume_class"] = (
        work["volume_class"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    work = work[
        work["volume_class"].ne("")
    ].copy()

    evaluated = pd.to_datetime(
        work.get(
            "evaluated_at",
            work["timestamp"],
        ),
        utc=True,
        errors="coerce",
    )

    work["_evaluated"] = evaluated

    work = (
        work.dropna(subset=["source_bar_timestamp"])
        .sort_values(
            [
                "source_bar_timestamp",
                "_evaluated",
            ]
        )
        .drop_duplicates(
            subset=["source_bar_timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return work


def add_price_reactions(
    events: pd.DataFrame,
    price: pd.DataFrame,
) -> pd.DataFrame:
    price = price.copy()

    index_by_timestamp = {
        ts: idx
        for idx, ts in enumerate(price["timestamp"])
    }

    rows = []

    for _, event in events.iterrows():
        ts = event["source_bar_timestamp"]

        if ts not in index_by_timestamp:
            continue

        i = index_by_timestamp[ts]

        entry_close = float(price.iloc[i]["close"])

        row = {
            "source_bar_timestamp": ts,
            "identity_mode": event["identity_mode"],
            "volume_class": event["volume_class"],
            "volume_event": event.get("volume_event"),
            "climax_state": event.get("climax_state"),
            "entry_close": entry_close,
        }

        for label, horizon in HORIZONS.items():
            end_i = i + horizon

            if end_i >= len(price):
                row[f"ret_{label}_bps"] = np.nan
                row[f"mfe_{label}_bps"] = np.nan
                row[f"mae_{label}_bps"] = np.nan
                continue

            future = price.iloc[
                i + 1:
                end_i + 1
            ]

            end_close = float(
                price.iloc[end_i]["close"]
            )

            max_high = float(
                future["high"].max()
            )

            min_low = float(
                future["low"].min()
            )

            row[f"ret_{label}_bps"] = (
                end_close / entry_close - 1.0
            ) * 10000.0

            row[f"mfe_{label}_bps"] = (
                max_high / entry_close - 1.0
            ) * 10000.0

            row[f"mae_{label}_bps"] = (
                min_low / entry_close - 1.0
            ) * 10000.0

        rows.append(row)

    return pd.DataFrame(rows)


def summarize(
    reactions: pd.DataFrame,
    cohort_name: str,
) -> pd.DataFrame:
    rows = []

    for volume_class, group in reactions.groupby(
        "volume_class",
        dropna=False,
    ):
        for label in HORIZONS:
            ret_col = f"ret_{label}_bps"
            mfe_col = f"mfe_{label}_bps"
            mae_col = f"mae_{label}_bps"

            valid = group[
                group[ret_col].notna()
            ].copy()

            if valid.empty:
                continue

            ret = valid[ret_col].astype(float)
            mfe = valid[mfe_col].astype(float)
            mae = valid[mae_col].astype(float)

            rows.append(
                {
                    "cohort": cohort_name,
                    "volume_class": volume_class,
                    "horizon": label,
                    "cases": int(len(valid)),
                    "mean_return_bps": float(ret.mean()),
                    "median_return_bps": float(ret.median()),
                    "mean_mfe_bps": float(mfe.mean()),
                    "median_mfe_bps": float(mfe.median()),
                    "mean_mae_bps": float(mae.mean()),
                    "median_mae_bps": float(mae.median()),
                    "pct_close_up": float((ret > 0).mean() * 100.0),
                    "pct_close_down": float((ret < 0).mean() * 100.0),
                    "pct_close_flat": float((ret == 0).mean() * 100.0),
                }
            )

    return pd.DataFrame(rows)


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    volume, price = load_data()

    events = prepare_volume_events(
        volume
    )

    reactions = add_price_reactions(
        events,
        price,
    )

    reactions.to_parquet(
        EVENTS_PATH,
        index=False,
    )

    summary_all = summarize(
        reactions,
        "ALL_USABLE",
    )

    explicit = reactions[
        reactions["identity_mode"].eq(
            "EXPLICIT_M15"
        )
    ].copy()

    summary_explicit = summarize(
        explicit,
        "EXPLICIT_M15",
    )

    summary = pd.concat(
        [
            summary_all,
            summary_explicit,
        ],
        ignore_index=True,
    )

    summary.to_csv(
        SUMMARY_PATH,
        index=False,
    )

    print("EVENT_ROWS", len(reactions))

    print()
    print("IDENTITY_MODE")
    print(
        reactions["identity_mode"]
        .value_counts()
        .to_string()
    )

    print()
    print("VOLUME_CLASSES")
    print(
        reactions["volume_class"]
        .value_counts()
        .to_string()
    )

    print()
    print("ALL_USABLE_H1")
    print(
        summary[
            (summary["cohort"] == "ALL_USABLE")
            & (summary["horizon"] == "H1")
        ][
            [
                "volume_class",
                "cases",
                "median_return_bps",
                "median_mfe_bps",
                "median_mae_bps",
                "pct_close_up",
                "pct_close_down",
            ]
        ]
        .sort_values(
            "cases",
            ascending=False,
        )
        .to_string(index=False)
    )

    print()
    print("ALL_USABLE_H4")
    print(
        summary[
            (summary["cohort"] == "ALL_USABLE")
            & (summary["horizon"] == "H4")
        ][
            [
                "volume_class",
                "cases",
                "median_return_bps",
                "median_mfe_bps",
                "median_mae_bps",
                "pct_close_up",
                "pct_close_down",
            ]
        ]
        .sort_values(
            "cases",
            ascending=False,
        )
        .to_string(index=False)
    )

    print()
    print("EXPLICIT_M15_H1")
    print(
        summary[
            (summary["cohort"] == "EXPLICIT_M15")
            & (summary["horizon"] == "H1")
        ][
            [
                "volume_class",
                "cases",
                "median_return_bps",
                "median_mfe_bps",
                "median_mae_bps",
                "pct_close_up",
                "pct_close_down",
            ]
        ]
        .sort_values(
            "cases",
            ascending=False,
        )
        .to_string(index=False)
    )

    print()
    print("EXPLICIT_M15_H4")
    print(
        summary[
            (summary["cohort"] == "EXPLICIT_M15")
            & (summary["horizon"] == "H4")
        ][
            [
                "volume_class",
                "cases",
                "median_return_bps",
                "median_mfe_bps",
                "median_mae_bps",
                "pct_close_up",
                "pct_close_down",
            ]
        ]
        .sort_values(
            "cases",
            ascending=False,
        )
        .to_string(index=False)
    )

    print()
    print("EVENTS", EVENTS_PATH)
    print("SUMMARY", SUMMARY_PATH)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
