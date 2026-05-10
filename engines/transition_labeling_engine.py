import pandas as pd
import numpy as np

# =================================
# LOAD DATA
# =================================

print()
print("LOADING DATA")
print()

flow = pd.read_parquet(
    "intraday_flow.parquet"
)

# =================================
# FEATURES
# =================================

print("BUILDING FEATURES")
print()

# TOTAL VOLUME

flow['total_volume'] = (

    flow['buy_volume']

    +

    flow['sell_volume']
)

# RETURNS

flow['returns'] = (

    flow['avg_price']
    .pct_change()
)

# VOLATILITY

flow['volatility'] = (

    flow['returns']
    .rolling(50)
    .std()
)

# DELTA PRESSURE

flow['delta_pressure'] = (

    flow['delta']
    .rolling(20)
    .mean()
)

# =================================
# FUTURE WINDOWS
# =================================

FUTURE = 30

labels = []

# =================================
# LOOP
# =================================

for i in range(100, len(flow) - FUTURE):

    current = flow.iloc[i]

    future = flow.iloc[

        i :

        i + FUTURE
    ]

    # =================================
    # FUTURE MOVES
    # =================================

    current_price = (
        current['avg_price']
    )

    future_max = (

        future['avg_price']
        .max()
    )

    future_min = (

        future['avg_price']
        .min()
    )

    max_up = (

        future_max
        /
        current_price
    ) - 1

    max_down = (

        future_min
        /
        current_price
    ) - 1

    future_vol = (

        future['returns']
        .std()
    )

    current_vol = (
        current['volatility']
    )

    # =================================
    # LABELS
    # =================================

    expansion = 0
    breakout_up = 0
    breakout_down = 0
    squeeze = 0
    reversal = 0

    # VOL EXPANSION

    if (

        future_vol

        >

        current_vol * 1.5
    ):

        expansion = 1

    # BREAKOUT UP

    if max_up > 0.0015:

        breakout_up = 1

    # BREAKOUT DOWN

    if max_down < -0.0015:

        breakout_down = 1

    # SQUEEZE

    if (

        abs(
            max_up
        ) > 0.001

        and

        abs(
            max_down
        ) < 0.0005
    ):

        squeeze = 1

    # REVERSAL

    if (

        max_up > 0.001

        and

        max_down < -0.001
    ):

        reversal = 1

    # =================================
    # SAVE
    # =================================

    labels.append({

        'timestamp':
            current['timestamp'],

        'price':
            current_price,

        'delta_pressure':
            current[
                'delta_pressure'
            ],

        'volatility':
            current[
                'volatility'
            ],

        'volume':
            current[
                'total_volume'
            ],

        'expansion':
            expansion,

        'breakout_up':
            breakout_up,

        'breakout_down':
            breakout_down,

        'squeeze':
            squeeze,

        'reversal':
            reversal
    })

# =================================
# DATAFRAME
# =================================

labels = pd.DataFrame(
    labels
)

# =================================
# SAVE
# =================================

labels.to_parquet(
    "transition_labels.parquet"
)

# =================================
# SUMMARY
# =================================

print("================================")
print("TRANSITION LABEL SUMMARY")
print("================================")
print()

for col in [

    'expansion',

    'breakout_up',

    'breakout_down',

    'squeeze',

    'reversal'
]:

    print(
        col,
        ":",
        labels[col]
        .sum()
    )

print()

print(
    "TOTAL STATES:",
    len(labels)
)

print()

print(
    "LABELING COMPLETE"
)
