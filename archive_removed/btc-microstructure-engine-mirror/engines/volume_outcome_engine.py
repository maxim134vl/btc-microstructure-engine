import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE VOLUME OUTCOME ENGINE"
)
print()

while True:

    try:

        print("================================")
        print(datetime.utcnow())
        print("================================")
        print()

        # =================================
        # LOAD SIGNALS
        # =================================

        reactions = pd.read_parquet(
            "volume_reactions.parquet"
        )

        inventory = pd.read_parquet(
            "inventory_states.parquet"
        )

        acceptance = pd.read_parquet(
            "acceptance_states.parquet"
        )

        vacuums = pd.read_parquet(
            "liquidity_vacuums.parquet"
        )

        flow = pd.read_parquet(
            "multi_exchange_flow.parquet"
        )

        # =================================
        # MARKET
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

            len(reactions),

            len(inventory),

            len(acceptance),

            len(vacuums),

            len(market)
        )

        reactions = reactions.tail(
            min_len
        ).reset_index(
            drop=True
        )

        inventory = inventory.tail(
            min_len
        ).reset_index(
            drop=True
        )

        acceptance = acceptance.tail(
            min_len
        ).reset_index(
            drop=True
        )

        vacuums = vacuums.tail(
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
        # SIGNAL TABLE
        # =================================

        signals = pd.DataFrame({

            'reaction':
                reactions[
                    'reaction'
                ],

            'inventory':
                inventory[
                    'inventory_state'
                ],

            'acceptance':
                acceptance[
                    'state'
                ],

            'vacuum':
                vacuums[
                    'vacuum_state'
                ],

            'future_return_5':
                market[
                    'future_return_5'
                ]
        })

        # =================================
        # RESULT STORAGE
        # =================================

        rows = []

        # =================================
        # ANALYSIS FUNCTION
        # =================================

        def analyze_signal(
            column
        ):

            unique_states = (

                signals[
                    column
                ]
                .unique()
            )

            for state in unique_states:

                subset = signals[

                    signals[
                        column
                    ]
                    ==
                    state
                ]

                if len(subset) < 5:

                    continue

                returns = subset[
                    'future_return_5'
                ]

                avg_return = (
                    returns.mean()
                )

                win_rate = (
                    (returns > 0)
                    .mean()
                )

                volatility = (
                    returns.std()
                )

                score = (

                    avg_return

                    /

                    (
                        volatility
                        +
                        1e-9
                    )
                )

                rows.append({

                    'signal_type':
                        column,

                    'state':
                        state,

                    'observations':
                        len(subset),

                    'avg_return':
                        avg_return,

                    'win_rate':
                        win_rate,

                    'score':
                        score
                })

        # =================================
        # RUN ANALYSIS
        # =================================

        analyze_signal(
            'reaction'
        )

        analyze_signal(
            'inventory'
        )

        analyze_signal(
            'acceptance'
        )

        analyze_signal(
            'vacuum'
        )

        # =================================
        # EMPTY
        # =================================

        if len(rows) == 0:

            print(
                "NO VALIDATED VOLUME SIGNALS YET"
            )

            print()

            time.sleep(30)

            continue

        # =================================
        # DATAFRAME
        # =================================

        results = pd.DataFrame(
            rows
        )

        results = results.sort_values(

            'score',

            ascending=False
        )

        # =================================
        # SAVE
        # =================================

        results.to_parquet(
            "volume_signal_validation.parquet"
        )

        # =================================
        # OUTPUT
        # =================================

        print("================================")
        print("VOLUME SIGNAL VALIDATION")
        print("================================")
        print()

        print(

            results[
                [

                    'signal_type',

                    'state',

                    'observations',

                    'avg_return',

                    'win_rate',

                    'score'
                ]
            ]
        )

        print()

        print(
            "VALIDATION UPDATED"
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
