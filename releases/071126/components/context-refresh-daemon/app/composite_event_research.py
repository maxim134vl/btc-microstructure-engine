import pandas as pd
import numpy as np

# ---------------------------------
# CONFIG
# ---------------------------------

FUTURE_WINDOW = 50

# ---------------------------------
# LOAD DATA
# ---------------------------------

flow = pd.read_parquet(
    "intraday_flow.parquet"
)

bybit = pd.read_parquet(
    "bybit_flow.parquet"
)

oi = pd.read_parquet(
    "oi_history.parquet"
)

book = pd.read_parquet(
    "orderbook.parquet"
)

# ---------------------------------
# ALIGN
# ---------------------------------

min_len = min(

    len(flow),

    len(bybit),

    len(oi),

    len(book)
)

flow = flow.iloc[:min_len]

bybit = bybit.iloc[:min_len]

oi = oi.iloc[:min_len]

book = book.iloc[:min_len]

# ---------------------------------
# RESULTS
# ---------------------------------

results = []

print()
print("COMPOSITE EVENT RESEARCH")
print()

# ---------------------------------
# MAIN LOOP
# ---------------------------------

for i in range(

    100,

    min_len - FUTURE_WINDOW
):

    try:

        # ---------------------------------
        # FEATURES
        # ---------------------------------

        flow_row = flow.iloc[i]

        bybit_row = bybit.iloc[i]

        oi_window = oi.iloc[
            i - 20 : i
        ]

        book_row = book.iloc[i]

        # ---------------------------------
        # METRICS
        # ---------------------------------

        binance_delta = (
            flow_row['delta']
        )

        bybit_delta = (
            bybit_row['delta']
        )

        efficiency = (
            flow_row['efficiency']
        )

        imbalance = (
            book_row['imbalance']
        )

        oi_change = (

            oi_window[
                'open_interest'
            ].iloc[-1]

            -

            oi_window[
                'open_interest'
            ].iloc[0]
        )

        # ---------------------------------
        # VOL
        # ---------------------------------

        returns = (

            flow.iloc[
                i - 50 : i
            ][
                'avg_price'
            ]
            .pct_change()
            .dropna()
        )

        realized_vol = (
            returns.std()
        )

        # ---------------------------------
        # COMPOSITE EVENT
        # ---------------------------------

        event = None

        # ---------------------------------
        # BULL PRESSURE + IMBALANCE
        # ---------------------------------

        if (

            binance_delta > 100

            and

            bybit_delta > 100

            and

            imbalance > 0.3

            and

            oi_change > 5
        ):

            event = (
                "BULL_PRESSURE_IMBALANCE"
            )

        # ---------------------------------
        # BEAR PRESSURE + IMBALANCE
        # ---------------------------------

        elif (

            binance_delta < -100

            and

            bybit_delta < -100

            and

            imbalance < -0.3

            and

            oi_change > 5
        ):

            event = (
                "BEAR_PRESSURE_IMBALANCE"
            )

        # ---------------------------------
        # ABSORPTION
        # ---------------------------------

        elif (

            abs(efficiency)
            <
            0.03

            and

            abs(binance_delta)
            >
            100

            and

            oi_change > 5
        ):

            event = (
                "ABSORPTION_SETUP"
            )

        # ---------------------------------
        # VOL EXPANSION
        # ---------------------------------

        elif (

            realized_vol
            >
            0.001

            and

            abs(binance_delta)
            >
            100
        ):

            event = (
                "VOLATILITY_EXPANSION"
            )

        # ---------------------------------
        # FILTER
        # ---------------------------------

        if event is None:

            continue

        # ---------------------------------
        # FUTURE
        # ---------------------------------

        current_price = (
            flow_row['avg_price']
        )

        future = flow.iloc[

            i :
            i + FUTURE_WINDOW
        ]

        future_last = (
            future.iloc[-1][
                'avg_price'
            ]
        )

        future_max = (
            future['avg_price'].max()
        )

        future_min = (
            future['avg_price'].min()
        )

        # ---------------------------------
        # RETURNS
        # ---------------------------------

        future_return = (

            (
                future_last
                -
                current_price
            )

            /

            current_price
        )

        max_upside = (

            (
                future_max
                -
                current_price
            )

            /

            current_price
        )

        max_drawdown = (

            (
                future_min
                -
                current_price
            )

            /

            current_price
        )

        # ---------------------------------
        # STORE
        # ---------------------------------

        results.append({

            'event':
                event,

            'future_return':
                future_return,

            'max_upside':
                max_upside,

            'max_drawdown':
                max_drawdown
        })

    except:

        continue

# ---------------------------------
# DATAFRAME
# ---------------------------------

results = pd.DataFrame(
    results
)

# ---------------------------------
# EMPTY
# ---------------------------------

if len(results) == 0:

    print()
    print("NO COMPOSITE EVENTS FOUND")

    exit()

# ---------------------------------
# SUMMARY
# ---------------------------------

print()
print("================================")
print("COMPOSITE EXPECTANCY")
print("================================")
print()

for event in (

    results['event']
    .unique()
):

    subset = results[

        results['event']
        ==
        event
    ]

    avg_return = (

        subset[
            'future_return'
        ].mean()
    )

    avg_upside = (

        subset[
            'max_upside'
        ].mean()
    )

    avg_drawdown = (

        subset[
            'max_drawdown'
        ].mean()
    )

    print(
        "EVENT:",
        event
    )

    print(
        "COUNT:",
        len(subset)
    )

    print(
        "AVG RETURN:",
        round(
            avg_return,
            5
        )
    )

    print(
        "AVG UPSIDE:",
        round(
            avg_upside,
            5
        )
    )

    print(
        "AVG DRAWDOWN:",
        round(
            avg_drawdown,
            5
        )
    )

    print()

print("RESEARCH COMPLETE")
