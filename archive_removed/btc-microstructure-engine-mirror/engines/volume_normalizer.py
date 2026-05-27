import pandas as pd
import numpy as np

# =================================
# LOAD DATA
# =================================

print()
print(
    "LOADING MULTI EXCHANGE DATA"
)
print()

df = pd.read_parquet(
    "multi_exchange_flow.parquet"
)

# =================================
# CLEAN
# =================================

df = df.copy()

# =================================
# RAW VOLUME
# =================================

df['raw_volume'] = (

    df['buy_volume']

    +

    df['sell_volume']
)

# =================================
# NORMALIZATION
# =================================

print(
    "NORMALIZING EXCHANGE DATA"
)

print()

normalized = []

# =================================
# EXCHANGE LOOP
# =================================

for exchange in df[
    'exchange'
].unique():

    sub = df[
        df['exchange']
        ==
        exchange
    ].copy()

    # =================================
    # VOLUME NORMALIZATION
    # =================================

    volume_mean = (

        sub[
            'raw_volume'
        ]
        .mean()
    )

    volume_std = (

        sub[
            'raw_volume'
        ]
        .std()
    )

    delta_std = (

        sub[
            'delta'
        ]
        .std()
    )

    # =================================
    # Z-SCORE FEATURES
    # =================================

    sub['volume_z'] = (

        (
            sub[
                'raw_volume'
            ]

            -

            volume_mean
        )

        /

        (
            volume_std
            +
            1e-9
        )
    )

    sub['delta_z'] = (

        sub[
            'delta'
        ]

        /

        (
            delta_std
            +
            1e-9
        )
    )

    # =================================
    # RELATIVE PRESSURE
    # =================================

    sub['relative_pressure'] = (

        sub[
            'delta'
        ]

        /

        (
            sub[
                'raw_volume'
            ]
            +
            1e-9
        )
    )

    # =================================
    # ABS AGGRESSION
    # =================================

    sub['aggression'] = (

        abs(
            sub[
                'relative_pressure'
            ]
        )
    )

    normalized.append(
        sub
    )

# =================================
# COMBINE
# =================================

normalized = pd.concat(
    normalized
)

# =================================
# SAVE
# =================================

normalized.to_parquet(
    "normalized_multi_exchange.parquet"
)

# =================================
# SUMMARY
# =================================

print("================================")
print("NORMALIZATION SUMMARY")
print("================================")
print()

for exchange in normalized[
    'exchange'
].unique():

    sub = normalized[
        normalized[
            'exchange'
        ]
        ==
        exchange
    ]

    print(
        exchange
    )

    print(
        "ROWS:",
        len(sub)
    )

    print(
        "AVG VOLUME Z:",
        round(
            sub[
                'volume_z'
            ]
            .mean(),
            4
        )
    )

    print(
        "AVG DELTA Z:",
        round(
            sub[
                'delta_z'
            ]
            .mean(),
            4
        )
    )

    print(
        "AVG AGGRESSION:",
        round(
            sub[
                'aggression'
            ]
            .mean(),
            4
        )
    )

    print()

print(
    "NORMALIZATION COMPLETE"
)
