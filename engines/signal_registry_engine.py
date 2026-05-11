import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE SIGNAL REGISTRY ENGINE"
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

        df = pd.read_parquet(
            "divergence_aftermath.parquet"
        )

        # =================================
        # SIGNAL DEFINITIONS
        # =================================

        signal_map = {

            'SYNC_BULLISH':

                df[
                    df[
                        'sync_bullish'
                    ]
                ],

            'SYNC_BEARISH':

                df[
                    df[
                        'sync_bearish'
                    ]
                ],

            'HYPER_AGGRESSION':

                df[
                    df[
                        'hyper_aggr'
                    ]
                    >
                    0.8
                ],

            'HIGH_DIVERGENCE':

                df[
                    df[
                        'binance_bybit_div'
                    ]
                    >
                    df[
                        'binance_bybit_div'
                    ]
                    .quantile(0.9)
                ]
        }

        # =================================
        # RESULTS
        # =================================

        results = []

        # =================================
        # LOOP
        # =================================

        for signal_name, subset in signal_map.items():

            if len(subset) < 5:

                continue

            # =================================
            # RETURNS
            # =================================

            r = subset[
                'future_return_5'
            ]

            avg_return = (
                r.mean()
            )

            volatility = (
                r.std()
            )

            win_rate = (
                (r > 0)
                .mean()
            )

            downside_rate = (
                (r < 0)
                .mean()
            )

            expectancy = (

                avg_return

                *

                win_rate
            )

            sharpe_like = (

                avg_return

                /

                (
                    volatility
                    +
                    1e-9
                )
            )

            # =================================
            # SCORE
            # =================================

            score = (

                sharpe_like

                *

                np.log(
                    len(subset)
                    +
                    1
                )
            )

            results.append({

                'signal':
                    signal_name,

                'observations':
                    len(subset),

                'avg_return':
                    avg_return,

                'volatility':
                    volatility,

                'win_rate':
                    win_rate,

                'downside_rate':
                    downside_rate,

                'expectancy':
                    expectancy,

                'sharpe_like':
                    sharpe_like,

                'score':
                    score
            })

        # =================================
        # REGISTRY
        # =================================

        registry = pd.DataFrame(
            results
        )

        registry = registry.sort_values(

            'score',

            ascending=False
        )

        # =================================
        # SAVE
        # =================================

        registry.to_parquet(
            "signal_registry.parquet"
        )

        # =================================
        # OUTPUT
        # =================================

        print("================================")
        print("SIGNAL RANKINGS")
        print("================================")
        print()

        print(

            registry[
                [

                    'signal',

                    'observations',

                    'avg_return',

                    'win_rate',

                    'score'
                ]
            ]
        )

        print()

        print(
            "REGISTRY UPDATED"
        )

        print()

        # =================================
        # WAIT
        # =================================

        time.sleep(60)

    except Exception as e:

        print()
        print("ERROR")
        print(type(e).__name__)
        print(e)
        print()

        time.sleep(10)
