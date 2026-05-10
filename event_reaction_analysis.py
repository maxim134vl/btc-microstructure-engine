import pandas as pd
import numpy as np

# ---------------------------------
# CONFIG
# ---------------------------------

FUTURE_WINDOW = 50

# ---------------------------------
# LOAD
# ---------------------------------

events = pd.read_parquet(
    "market_events.parquet"
)

flow = pd.read_parquet(
    "intraday_flow.parquet"
)

print()
print("EVENT REACTION ANALYSIS")
print()

# ---------------------------------
# EMPTY
# ---------------------------------

if len(events) == 0:

    print("NO EVENTS FOUND")

    exit()

# ---------------------------------
# RESULTS
# ---------------------------------

results = []

# ---------------------------------
# LOOP EVENTS
# ---------------------------------

for _, event_row in events.iterrows():

    try:

        event_time = (
            event_row['timestamp']
        )

        event_type = (
            event_row['event']
        )

        # ---------------------------------
        # FIND FLOW INDEX
        # ---------------------------------

        matches = flow[
            flow['timestamp']
            >=
            event_time
        ]

        if len(matches) == 0:

            continue

        start_idx = matches.index[0]

        if (

            start_idx + FUTURE_WINDOW
            >=
            len(flow)
        ):

            continue

        # ---------------------------------
        # WINDOW
        # ---------------------------------

        current_price = (

            flow.iloc[
                start_idx
            ]['avg_price']
        )

        future = flow.iloc[

            start_idx :
            start_idx + FUTURE_WINDOW
        ]

        # ---------------------------------
        # FUTURE STATS
        # ---------------------------------

        future_max = (
            future['avg_price'].max()
        )

        future_min = (
            future['avg_price'].min()
        )

        future_last = (
            future.iloc[-1][
                'avg_price'
            ]
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
                event_type,

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
    print("NO MATCHED EVENTS")

    exit()

# ---------------------------------
# EVENT TYPES
# ---------------------------------

event_types = results[
    'event'
].unique()

# ---------------------------------
# SUMMARY
# ---------------------------------

print()
print("================================")
print("EVENT EXPECTANCY")
print("================================")
print()

for event in event_types:

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

print("ANALYSIS COMPLETE")
