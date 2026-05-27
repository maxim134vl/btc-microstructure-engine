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

# TOTAL AGGRESSIVE VOLUME

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

# ABSOLUTE MOVE

flow['abs_move'] = (

    flow['returns']
    .abs()
)

# SMOOTH VOLUME

flow['volume_smooth'] = (

    flow['total_volume']
    .rolling(50)
    .mean()
)

# =================================
# VOLUME Z SCORE
# =================================

WINDOW = 200

flow['volume_z'] = (

    (
        flow['total_volume']

        -

        flow['total_volume']
        .rolling(WINDOW)
        .mean()
    )

    /

    flow['total_volume']
    .rolling(WINDOW)
    .std()
)

# =================================
# PRICE EFFICIENCY
# =================================

flow['price_efficiency'] = (

    flow['abs_move']

    /

    (
        flow['total_volume']

        +

        1
    )
)

# =================================
# DETECT EVENTS
# =================================

events = []

for i in range(WINDOW, len(flow)):

    row = flow.iloc[i]

    volume_z = row['volume_z']

    move = row['abs_move']

    efficiency = row[
        'price_efficiency'
    ]

    # =================================
    # VOLUME CLIMAX
    # =================================

    if (

        volume_z > 3

        and

        move > 0.0005
    ):

        events.append({

            'timestamp':
                row['timestamp'],

            'event':
                'VOLUME_CLIMAX',

            'price':
                row['avg_price'],

            'volume_z':
                round(
                    volume_z,
                    2
                ),

            'move':
                round(
                    move,
                    6
                )
        })

    # =================================
    # ABSORPTION
    # =================================

    elif (

        volume_z > 3

        and

        move < 0.00005
    ):

        events.append({

            'timestamp':
                row['timestamp'],

            'event':
                'ABSORPTION',

            'price':
                row['avg_price'],

            'volume_z':
                round(
                    volume_z,
                    2
                ),

            'move':
                round(
                    move,
                    6
                )
        })

    # =================================
    # LIQUIDITY VACUUM
    # =================================

    elif (

        volume_z < -1

        and

        move > 0.0003
    ):

        events.append({

            'timestamp':
                row['timestamp'],

            'event':
                'LIQUIDITY_VACUUM',

            'price':
                row['avg_price'],

            'volume_z':
                round(
                    volume_z,
                    2
                ),

            'move':
                round(
                    move,
                    6
                )
        })

# =================================
# DATAFRAME
# =================================

events = pd.DataFrame(events)

# =================================
# SAVE
# =================================

events.to_parquet(
    "volume_events.parquet"
)

# =================================
# SUMMARY
# =================================

print("================================")
print("VOLUME EVENT SUMMARY")
print("================================")
print()

if len(events) > 0:

    print(

        events['event']
        .value_counts()
    )

    print()

    print(
        "RECENT EVENTS"
    )

    print()

    print(
        events.tail(20)
    )

else:

    print(
        "NO EVENTS FOUND"
    )

print()

print(
    "TOTAL EVENTS:",
    len(events)
)

print()

print(
    "VOLUME ENGINE COMPLETE"
)
