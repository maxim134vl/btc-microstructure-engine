from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

BASE_URL = "https://data-api.binance.vision"
ENDPOINT = "/api/v3/klines"

SYMBOL = "BTCUSDT"

WARMUP_START = pd.Timestamp(
    "2026-03-01T00:00:00Z"
)

ANALYSIS_START = pd.Timestamp(
    "2026-05-02T00:00:00Z"
)

OUTPUT_DIR = (
    ROOT
    / "data/research/binance_native_ohlcv_v1"
)

REPORT_PATH = (
    OUTPUT_DIR
    / "download_report.json"
)

INTERVALS = {
    "M15": {
        "binance": "15m",
        "minutes": 15,
    },
    "M30": {
        "binance": "30m",
        "minutes": 30,
    },
    "H1": {
        "binance": "1h",
        "minutes": 60,
    },
    "H4": {
        "binance": "4h",
        "minutes": 240,
    },
    "D1": {
        "binance": "1d",
        "minutes": 1440,
    },
}

COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def to_ms(timestamp: pd.Timestamp) -> int:
    return int(
        timestamp.timestamp()
        * 1000
    )


def request_json(
    params: dict,
    retries: int = 8,
):
    query = urllib.parse.urlencode(
        params
    )

    url = (
        BASE_URL
        + ENDPOINT
        + "?"
        + query
    )

    last_error = None

    for attempt in range(
        1,
        retries + 1,
    ):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "btc-ml-research/1.0"
                ),
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                body = response.read()

            return json.loads(
                body.decode("utf-8")
            )

        except urllib.error.HTTPError as exc:
            last_error = exc

            if exc.code in {
                418,
                429,
            }:
                retry_after = (
                    exc.headers.get(
                        "Retry-After"
                    )
                )

                delay = (
                    float(retry_after)
                    if retry_after
                    else 5.0 * attempt
                )

                print(
                    "RATE_LIMIT",
                    exc.code,
                    "SLEEP",
                    delay,
                )

                time.sleep(delay)
                continue

            if 500 <= exc.code < 600:
                delay = min(
                    2.0 * attempt,
                    15.0,
                )

                print(
                    "SERVER_ERROR",
                    exc.code,
                    "SLEEP",
                    delay,
                )

                time.sleep(delay)
                continue

            raise

        except Exception as exc:
            last_error = exc

            delay = min(
                2.0 * attempt,
                15.0,
            )

            print(
                "REQUEST_ERROR",
                type(exc).__name__,
                "SLEEP",
                delay,
            )

            time.sleep(delay)

    raise RuntimeError(
        f"Request failed: {last_error}"
    )


def download_interval(
    interval: str,
    minutes: int,
    now_utc: pd.Timestamp,
) -> pd.DataFrame:
    interval_ms = (
        minutes
        * 60
        * 1000
    )

    cursor = to_ms(
        WARMUP_START
    )

    end_ms = to_ms(
        now_utc
    )

    rows = []

    request_count = 0

    while cursor <= end_ms:
        payload = request_json(
            {
                "symbol": SYMBOL,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )

        request_count += 1

        if not payload:
            break

        rows.extend(payload)

        last_open_time = int(
            payload[-1][0]
        )

        next_cursor = (
            last_open_time
            + interval_ms
        )

        if next_cursor <= cursor:
            raise RuntimeError(
                "Pagination did not advance"
            )

        cursor = next_cursor

        if len(payload) < 1000:
            break

        time.sleep(0.05)

    if not rows:
        raise RuntimeError(
            f"No rows for {interval}"
        )

    frame = pd.DataFrame(
        rows,
        columns=COLUMNS,
    )

    frame["open_time"] = (
        pd.to_datetime(
            frame["open_time"],
            unit="ms",
            utc=True,
        )
    )

    frame["close_time"] = (
        pd.to_datetime(
            frame["close_time"],
            unit="ms",
            utc=True,
        )
    )

    numeric_float = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]

    for column in numeric_float:
        frame[column] = (
            pd.to_numeric(
                frame[column],
                errors="coerce",
            )
        )

    frame[
        "number_of_trades"
    ] = pd.to_numeric(
        frame[
            "number_of_trades"
        ],
        errors="coerce",
    ).astype(
        "Int64"
    )

    frame = (
        frame
        .sort_values(
            "open_time"
        )
        .drop_duplicates(
            subset=["open_time"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    frame = frame[
        frame["close_time"]
        < now_utc
    ].copy()

    frame = frame[
        frame["open_time"]
        >= WARMUP_START
    ].copy()

    frame["timestamp"] = (
        frame["open_time"]
    )

    frame["taker_buy_volume"] = (
        frame[
            "taker_buy_base_volume"
        ]
    )

    frame["buy_volume"] = (
        frame[
            "taker_buy_base_volume"
        ]
    )

    frame["sell_volume"] = (
        frame["volume"]
        - frame["buy_volume"]
    ).clip(
        lower=0.0
    )

    frame["delta"] = (
        frame["buy_volume"]
        - frame["sell_volume"]
    )

    frame["symbol"] = SYMBOL
    frame["binance_interval"] = (
        interval
    )
    frame["timeframe_minutes"] = (
        minutes
    )

    frame["analysis_eligible"] = (
        frame["timestamp"]
        >= ANALYSIS_START
    )

    frame.attrs[
        "request_count"
    ] = request_count

    return frame


def continuity_report(
    frame: pd.DataFrame,
    timeframe: str,
    minutes: int,
) -> dict:
    expected_delta = pd.Timedelta(
        minutes=minutes
    )

    timestamps = (
        frame["timestamp"]
        .sort_values()
        .reset_index(drop=True)
    )

    diffs = (
        timestamps
        .diff()
        .dropna()
    )

    gaps = diffs[
        diffs
        != expected_delta
    ]

    missing_bars = 0

    gap_details = []

    for index, gap in gaps.items():
        previous_timestamp = (
            timestamps.iloc[
                index - 1
            ]
        )

        current_timestamp = (
            timestamps.iloc[
                index
            ]
        )

        ratio = (
            gap
            / expected_delta
        )

        missing = max(
            int(round(ratio)) - 1,
            0,
        )

        missing_bars += missing

        gap_details.append(
            {
                "previous": str(
                    previous_timestamp
                ),
                "current": str(
                    current_timestamp
                ),
                "gap_minutes": (
                    gap.total_seconds()
                    / 60.0
                ),
                "missing_bars": missing,
            }
        )

    duplicate_count = int(
        frame["timestamp"]
        .duplicated()
        .sum()
    )

    analysis_frame = frame[
        frame["analysis_eligible"]
    ]

    return {
        "timeframe": timeframe,
        "interval_minutes": minutes,
        "total_rows": int(
            len(frame)
        ),
        "analysis_rows": int(
            len(analysis_frame)
        ),
        "start": str(
            frame["timestamp"].min()
        ),
        "end": str(
            frame["timestamp"].max()
        ),
        "analysis_start": str(
            analysis_frame[
                "timestamp"
            ].min()
        )
        if len(analysis_frame)
        else None,
        "analysis_end": str(
            analysis_frame[
                "timestamp"
            ].max()
        )
        if len(analysis_frame)
        else None,
        "gap_count": int(
            len(gaps)
        ),
        "missing_bars": int(
            missing_bars
        ),
        "duplicate_count": (
            duplicate_count
        ),
        "gap_details": (
            gap_details[:20]
        ),
    }


def main() -> int:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now_utc = pd.Timestamp.now(
        tz="UTC"
    )

    print(
        "SOURCE",
        BASE_URL + ENDPOINT,
    )

    print(
        "SYMBOL",
        SYMBOL,
    )

    print(
        "WARMUP_START",
        WARMUP_START,
    )

    print(
        "ANALYSIS_START",
        ANALYSIS_START,
    )

    print(
        "DOWNLOAD_CUTOFF",
        now_utc,
    )

    reports = []

    for timeframe, config in (
        INTERVALS.items()
    ):
        print()
        print(
            "DOWNLOADING",
            timeframe,
            config["binance"],
        )

        frame = download_interval(
            interval=config[
                "binance"
            ],
            minutes=config[
                "minutes"
            ],
            now_utc=now_utc,
        )

        report = continuity_report(
            frame=frame,
            timeframe=timeframe,
            minutes=config[
                "minutes"
            ],
        )

        reports.append(report)

        full_path = (
            OUTPUT_DIR
            / f"{timeframe}_native.parquet"
        )

        analysis_path = (
            OUTPUT_DIR
            / f"{timeframe}_analysis.parquet"
        )

        frame.to_parquet(
            full_path,
            index=False,
        )

        frame[
            frame[
                "analysis_eligible"
            ]
        ].to_parquet(
            analysis_path,
            index=False,
        )

        print(
            "ROWS",
            report["total_rows"],
        )

        print(
            "ANALYSIS_ROWS",
            report["analysis_rows"],
        )

        print(
            "RANGE",
            report["start"],
            report["end"],
        )

        print(
            "GAPS",
            report["gap_count"],
        )

        print(
            "MISSING_BARS",
            report[
                "missing_bars"
            ],
        )

        print(
            "DUPLICATES",
            report[
                "duplicate_count"
            ],
        )

        print(
            "FULL_PATH",
            full_path,
        )

        print(
            "ANALYSIS_PATH",
            analysis_path,
        )

    payload = {
        "source": (
            BASE_URL
            + ENDPOINT
        ),
        "symbol": SYMBOL,
        "warmup_start": str(
            WARMUP_START
        ),
        "analysis_start": str(
            ANALYSIS_START
        ),
        "download_cutoff": str(
            now_utc
        ),
        "timeframes": reports,
    }

    REPORT_PATH.write_text(
        json.dumps(
            payload,
            indent=2,
            default=str,
        )
    )

    print()
    print("CONTINUITY_SUMMARY")

    summary = pd.DataFrame(
        [
            {
                "timeframe": row[
                    "timeframe"
                ],
                "total_rows": row[
                    "total_rows"
                ],
                "analysis_rows": row[
                    "analysis_rows"
                ],
                "gap_count": row[
                    "gap_count"
                ],
                "missing_bars": row[
                    "missing_bars"
                ],
                "duplicate_count": row[
                    "duplicate_count"
                ],
                "start": row[
                    "start"
                ],
                "end": row[
                    "end"
                ],
            }
            for row in reports
        ]
    )

    print(
        summary.to_string(
            index=False
        )
    )

    print()
    print(
        "REPORT",
        REPORT_PATH,
    )

    bad = [
        row
        for row in reports
        if (
            row["gap_count"] > 0
            or
            row[
                "duplicate_count"
            ] > 0
        )
    ]

    if bad:
        print()
        print(
            "CONTINUITY_STATUS FAIL"
        )

        return 2

    print()
    print(
        "CONTINUITY_STATUS PASS"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
