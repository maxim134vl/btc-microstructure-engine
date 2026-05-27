import pandas as pd
import numpy as np

# =================================
# LOAD DATA
# =================================

print()
print(
    "LOADING NORMALIZED DATA"
)
print()

df = pd.read_parquet(
    "normalized_multi_exchange.parquet"
)

# =================================
# BUILD EXCHANGE TABLES
# =================================

binance = df[
    df['exchange']
    ==
    'BINANCE'
].copy()

bybit = df[
    df['exchange']
    ==
    'BYBIT'
].copy()

hyper = df[
    df['exchange']
    ==
    'HYPERLIQUID'
].copy()

# =================================
# ALIGN LENGTHS
# =================================

min_len = min(

    len(binance),

    len(bybit),

    len(hyper)
)

binance = binance.tail(min_len)
bybit = bybit.tail(min_len)
hyper = hyper.tail(min_len)

# =================================
# BUILD MATRIX
# =================================

signals = pd.DataFrame()

signals['timestamp'] = (
    binance['timestamp']
    .values
)

# =================================
# DELTA DIVERGENCE
# =================================

signals['binance_delta'] = (
    binance['delta_z']
    .values
)

signals['bybit_delta'] = (
    bybit['delta_z']
    .values
)

signals['hyper_delta'] = (
    hyper['delta_z']
    .values
)

# =================================
# AGGRESSION
# =================================

signals['binance_aggr'] = (
    binance['aggression']
    .values
)

signals['bybit_aggr'] = (
    bybit['aggression']
    .values
)

signals['hyper_aggr'] = (
    hyper['aggression']
    .values
)

# =================================
# DIVERGENCE SCORES
# =================================

signals['binance_bybit_div'] = (

    abs(

        signals['binance_delta']

        -

        signals['bybit_delta']
    )
)

signals['hyper_vs_market'] = (

    abs(

        signals['hyper_delta']

        -

        (
            signals['binance_delta']

            +

            signals['bybit_delta']
        )
        / 2
    )
)

# =================================
# COMPOSITE PRESSURE
# =================================

signals['market_pressure'] = (

    signals['binance_delta']

    +

    signals['bybit_delta']

    +

    signals['hyper_delta']
)

# =================================
# SPECULATIVE BURST
# =================================

signals['speculative_burst'] = (

    signals['hyper_aggr']

    >

    (
        signals['hyper_aggr']
        .rolling(20)
        .mean()

        +

        signals['hyper_aggr']
        .rolling(20)
        .std()
    )
)

# =================================
# SYNCHRONIZED BUYING
# =================================

signals['sync_bullish'] = (

    (
        signals['binance_delta']
        > 1
    )

    &

    (
        signals['bybit_delta']
        > 1
    )
)

# =================================
# SYNCHRONIZED SELLING
# =================================

signals['sync_bearish'] = (

    (
        signals['binance_delta']
        < -1
    )

    &

    (
        signals['bybit_delta']
        < -1
    )
)

# =================================
# SAVE
# =================================

signals.to_parquet(
    "divergence_signals.parquet"
)

# =================================
# SUMMARY
# =================================

print("================================")
print("DIVERGENCE SUMMARY")
print("================================")
print()

print(
    "TOTAL STATES:",
    len(signals)
)

print()

print(
    "SYNC BULLISH:",
    int(
        signals[
            'sync_bullish'
        ]
        .sum()
    )
)

print()

print(
    "SYNC BEARISH:",
    int(
        signals[
            'sync_bearish'
        ]
        .sum()
    )
)

print()

print(
    "SPECULATIVE BURSTS:",
    int(
        signals[
            'speculative_burst'
        ]
        .sum()
    )
)

print()

print(
    "AVG BINANCE/BYBIT DIV:",
    round(
        signals[
            'binance_bybit_div'
        ]
        .mean(),
        4
    )
)

print()

# =================================
# RECENT SIGNALS
# =================================

print("================================")
print("RECENT STATES")
print("================================")
print()

print(

    signals.tail(10)
)

print()

print(
    "DIVERGENCE ENGINE COMPLETE"
)
