import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE REGIME SIGNAL REGISTRY"
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
            "divergence_aftermath.parquet"
        )

        regimes = pd.read_parquet(
            "regime_history.parquet"
        )

        # =================================
        # ALIGN
        # =================================

        min_len = min(
            len(signals),
            len(regimes)
        )

        signals = signals.tail(
            min_len
        ).reset_index(
            drop=True
        )

        regimes = regimes.tail(
            min_len
        ).reset_index(
            drop=True
        )

        # =================================
        # MERGE REGIME
        # =================================

        signals['regime'] = (
            regimes['regime']
        )

        # =================================
        # SIGNAL DEFINITIONS
        # =================================

        signal_map = {

            'SYNC_BULLISH':

                signals[
                    signals[
                        'sync_bullish'
                    ]
                ],

            'SYNC_BEARISH':

                signals[
                    signals[
                        'sync_bearish'
                    ]
                ],

            'HYPER_AGGRESSION':

                signals[
                    signals[
                        'hyper_aggr'
                    ]
                    >
                    0.8
                ],

            'HIGH_DIVERGENCE':

                signals[
                    signals[
                        'binance_bybit_div'
                    ]
                    >
                    signals[
                        'binance_bybit_div'
                    ]
                    .quantile(0.9)
                ]
        }

        # =================================
        # RESULTS
        # =================================

        rows = []

        # =================================
        # LOOP
        # =================================

        for signal_name, subset in signal_map.items():

            if len(subset) == 0:

                continue

            unique_regimes = (
                subset[
                    'regime'
                ]
                .dropna()
                .unique()
            )

            for regime_name in unique_regimes:

                regime_subset = subset[

                    subset[
                        'regime'
                    ]
                    ==
                    regime_name
                ]

                if len(regime_subset) < 5:

                    continue

                returns = regime_subset[
                    'future_return_5'
                ]

                avg_return = (
                    returns.mean()
                )

                volatility = (
                    returns.std()
                )

                win_rate = (
                    (returns > 0)
                    .mean()
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

                score = (

                    sharpe_like

                    *

                    np.log(
                        len(regime_subset)
                        +
                        1
                    )
                )

                rows.append({

                    'signal':
                        signal_name,

                    'regime':
                        regime_name,

                    'observations':
                        len(regime_subset),

                    'avg_return':
                        avg_return,

                    'volatility':
                        volatility,

                    'win_rate':
                        win_rate,

                    'score':
                        score
                })

        # =================================
        # EMPTY CHECK
        # =================================

        if len(rows) == 0:

            print(
                "NO REGIME SIGNALS YET"
            )

            print()

            time.sleep(30)

            continue

        # =================================
        # DATAFRAME
        # =================================

        registry = pd.DataFrame(
            rows
        )

        registry = registry.sort_values(

            'score',

            ascending=False
        )

        # =================================
        # SAVE
        # =================================

        registry.to_parquet(
            "regime_signal_registry.parquet"
        )

        # =================================
        # OUTPUT
        # =================================

        print("================================")
        print("REGIME SIGNAL RANKINGS")
        print("================================")
        print()

        print(

            registry[
                [

                    'signal',

                    'regime',

                    'observations',

                    'avg_return',

                    'win_rate',

                    'score'
                ]
            ]
        )

        print()

        print(
            "REGIME REGISTRY UPDATED"
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
