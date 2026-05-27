import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE DIVERGENCE AFTERMATH ENGINE"
)
print()

while True:

    try:

        print("================================")
        print(datetime.utcnow())
        print("================================")
        print()

        # =================================
        # LOAD
        # =================================

        signals = pd.read_parquet(
            "divergence_signals.parquet"
        )

        flow = pd.read_parquet(
            "multi_exchange_flow.parquet"
        )

        # =================================
        # BINANCE MARKET
        # =================================

        market = flow[
            flow['exchange']
            ==
            'BINANCE'
        ].copy()

        market = market.sort_values(
            'timestamp'
        )

        market = market.reset_index(
            drop=True
        )

        # =================================
        # FUTURE RETURNS
        # =================================

        for horizon in [1, 5, 15]:

            market[
                f'future_return_{horizon}'
            ] = (

                market[
                    'avg_price'
                ]
                .shift(-horizon)

                /

                market[
                    'avg_price'
                ]

                - 1
            )

        # =================================
        # ALIGN
        # =================================

        min_len = min(
            len(signals),
            len(market)
        )

        signals = signals.tail(
            min_len
        ).reset_index(
            drop=True
        )

        market = market.tail(
            min_len
        ).reset_index(
            drop=True
        )

        # =================================
        # MERGE
        # =================================

        for horizon in [1, 5, 15]:

            signals[
                f'future_return_{horizon}'
            ] = market[
                f'future_return_{horizon}'
            ]

        # =================================
        # SIGNAL GROUPS
        # =================================

        sync_bullish = signals[
            signals[
                'sync_bullish'
            ]
        ]

        sync_bearish = signals[
            signals[
                'sync_bearish'
            ]
        ]

        hyper_aggr = signals[
            signals[
                'hyper_aggr'
            ]
            >
            0.8
        ]

        # =================================
        # ANALYSIS FUNCTION
        # =================================

        def analyze(
            name,
            subset
        ):

            if len(subset) == 0:

                return

            print("================================")
            print(name)
            print("================================")
            print()

            print(
                "OBSERVATIONS:",
                len(subset)
            )

            print()

            for horizon in [1, 5, 15]:

                col = (
                    f'future_return_{horizon}'
                )

                avg_return = (
                    subset[col]
                    .mean()
                )

                win_rate = (

                    (
                        subset[col]
                        > 0
                    )
                    .mean()
                )

                print(
                    f"HORIZON {horizon}"
                )

                print(
                    "AVG RETURN:",
                    round(
                        avg_return,
                        6
                    )
                )

                print(
                    "WIN RATE:",
                    round(
                        win_rate,
                        4
                    )
                )

                print()

        # =================================
        # RUN ANALYSIS
        # =================================

        analyze(
            "SYNC BULLISH",
            sync_bullish
        )

        analyze(
            "SYNC BEARISH",
            sync_bearish
        )

        analyze(
            "HYPER AGGRESSION",
            hyper_aggr
        )

        # =================================
        # SAVE
        # =================================

        signals.to_parquet(
            "divergence_aftermath.parquet"
        )

        print(
            "AFTERMATH UPDATED"
        )

        print()

        # =================================
        # WAIT
        # =================================

        time.sleep(30)

    except Exception as e:

        print()
        print("ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(10)
