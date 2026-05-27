import pandas as pd
import numpy as np
import time

from datetime import datetime

print()
print(
    "LIVE MARKET NARRATIVE ENGINE"
)
print()

while True:

    try:

        print("================================")
        print(datetime.utcnow())
        print("================================")
        print()

        # =================================
        # LOAD ENGINES
        # =================================

        structure = pd.read_parquet(
            "market_structure.parquet"
        )

        classifications = pd.read_parquet(
            "volume_classifications.parquet"
        )

        divergence = pd.read_parquet(
            "divergence_signals.parquet"
        )

        regimes = pd.read_parquet(
            "regime_history.parquet"
        )

        # =================================
        # LATEST STATES
        # =================================

        latest_structure = (
            structure.iloc[-1]
        )

        latest_classification = (
            classifications.iloc[-1]
        )

        latest_divergence = (
            divergence.iloc[-1]
        )

        latest_regime = (
            regimes.iloc[-1]
        )

        # =================================
        # EXTRACT
        # =================================

        structure_state = (
            latest_structure[
                'structure'
            ]
        )

        volume_state = (
            latest_classification[
                'classification'
            ]
        )

        regime_state = (
            latest_regime[
                'regime'
            ]
        )

        sync_bullish = (
            latest_divergence[
                'sync_bullish'
            ]
        )

        sync_bearish = (
            latest_divergence[
                'sync_bearish'
            ]
        )

        hyper_aggr = (
            latest_divergence[
                'hyper_aggr'
            ]
        )

        # =================================
        # DEFAULT
        # =================================

        narrative = (
            "NEUTRAL_MARKET"
        )

        confidence = 0.0

        # =================================
        # ABSORPTION
        # =================================

        if (

            structure_state
            ==
            "NEAR_SUPPORT"

            and

            volume_state
            ==
            "ABSORPTION_BUYING"
        ):

            narrative = (
                "SELLER_EXHAUSTION"
            )

            confidence = 0.75

        # =================================
        # DISTRIBUTION
        # =================================

        if (

            structure_state
            ==
            "NEAR_RESISTANCE"

            and

            volume_state
            ==
            "DISTRIBUTION_SELLING"
        ):

            narrative = (
                "DISTRIBUTION"
            )

            confidence = 0.75

        # =================================
        # BREAKOUT
        # =================================

        if (

            "BREAKOUT"
            in
            structure_state

            and

            volume_state
            ==
            "BREAKOUT_PRESSURE"
        ):

            narrative = (
                "ACTIVE_BREAKOUT"
            )

            confidence = 0.9

        # =================================
        # TRAP
        # =================================

        if (

            structure_state
            ==
            "NEAR_RESISTANCE"

            and

            sync_bullish
            ==
            True
        ):

            narrative = (
                "BULL_TRAP_RISK"
            )

            confidence = 0.7

        # =================================
        # SHORT SQUEEZE
        # =================================

        if (

            structure_state
            ==
            "NEAR_SUPPORT"

            and

            sync_bearish
            ==
            True
        ):

            narrative = (
                "SHORT_SQUEEZE_RISK"
            )

            confidence = 0.8

        # =================================
        # HYPER AGGRESSION
        # =================================

        if hyper_aggr > 0.9:

            narrative = (
                "AGGRESSIVE_POSITIONING"
            )

            confidence = 0.6

        # =================================
        # REGIME BOOST
        # =================================

        if (

            regime_state
            ==
            "EXPANSION"
        ):

            confidence += 0.1

        confidence = min(
            confidence,
            1.0
        )

        # =================================
        # OUTPUT
        # =================================

        print(
            "STRUCTURE:",
            structure_state
        )

        print()

        print(
            "VOLUME:",
            volume_state
        )

        print()

        print(
            "REGIME:",
            regime_state
        )

        print()

        print(
            "SYNC BULLISH:",
            sync_bullish
        )

        print()

        print(
            "SYNC BEARISH:",
            sync_bearish
        )

        print()

        print(
            "HYPER AGGRESSION:",
            round(
                hyper_aggr,
                4
            )
        )

        print()

        print(
            "MARKET NARRATIVE:",
            narrative
        )

        print()

        print(
            "CONFIDENCE:",
            round(
                confidence,
                2
            )
        )

        print()

        # =================================
        # SAVE
        # =================================

        snapshot = pd.DataFrame([{

            'timestamp':
                datetime.utcnow(),

            'narrative':
                narrative,

            'confidence':
                confidence
        }])

        try:

            old = pd.read_parquet(
                "market_narratives.parquet"
            )

            combined = pd.concat([

                old,

                snapshot
            ])

        except:

            combined = snapshot

        combined.to_parquet(
            "market_narratives.parquet"
        )

        print(
            "NARRATIVE UPDATED"
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
