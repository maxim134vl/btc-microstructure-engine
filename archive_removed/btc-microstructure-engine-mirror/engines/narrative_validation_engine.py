import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE NARRATIVE VALIDATION ENGINE"
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

        narratives = pd.read_parquet(
            "market_narratives.parquet"
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
            len(narratives),
            len(market)
        )

        narratives = narratives.tail(
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
        # MERGE RETURNS
        # =================================

        for horizon in [1, 5, 15]:

            narratives[
                f'future_return_{horizon}'
            ] = market[
                f'future_return_{horizon}'
            ]

        # =================================
        # UNIQUE NARRATIVES
        # =================================

        narrative_types = (

            narratives[
                'narrative'
            ]
            .unique()
        )

        # =================================
        # RESULTS
        # =================================

        rows = []

        # =================================
        # LOOP
        # =================================

        for narrative in narrative_types:

            subset = narratives[

                narratives[
                    'narrative'
                ]
                ==
                narrative
            ]

            if len(subset) < 5:

                continue

            returns = subset[
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
                    len(subset)
                    +
                    1
                )
            )

            rows.append({

                'narrative':
                    narrative,

                'observations':
                    len(subset),

                'avg_return':
                    avg_return,

                'win_rate':
                    win_rate,

                'volatility':
                    volatility,

                'score':
                    score
            })

        # =================================
        # EMPTY
        # =================================

        if len(rows) == 0:

            print(
                "NO VALIDATED NARRATIVES YET"
            )

            print()

            time.sleep(30)

            continue

        # =================================
        # DATAFRAME
        # =================================

        validation = pd.DataFrame(
            rows
        )

        validation = validation.sort_values(

            'score',

            ascending=False
        )

        # =================================
        # SAVE
        # =================================

        validation.to_parquet(
            "narrative_validation.parquet"
        )

        # =================================
        # OUTPUT
        # =================================

        print("================================")
        print("NARRATIVE VALIDATION")
        print("================================")
        print()

        print(

            validation[
                [

                    'narrative',

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
