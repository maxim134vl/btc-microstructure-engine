import pandas as pd
import numpy as np

# ---------------------------------
# LOAD DATA
# ---------------------------------

df = pd.read_parquet('btc_15m.parquet')

print("Loaded data")

# ---------------------------------
# FEATURES
# ---------------------------------

# RETURNS

df['return'] = df['close'].pct_change()

# VOLATILITY

df['volatility'] = (
    df['high'] - df['low']
) / df['close']

# TREND STRENGTH

df['trend'] = (
    df['close']
    .pct_change(20)
    .abs()
)

# MOVING AVERAGES

df['volatility_ma'] = (
    df['volatility']
    .rolling(50)
    .mean()
)

df['trend_ma'] = (
    df['trend']
    .rolling(50)
    .mean()
)

# ---------------------------------
# REGIME CLASSIFICATION
# ---------------------------------

regimes = []

for i in range(len(df)):

    row = df.iloc[i]

    # HIGH VOLATILITY

    if row['volatility'] > row['volatility_ma'] * 1.5:

        regimes.append("HIGH_VOL")

    # TREND

    elif row['trend'] > row['trend_ma'] * 1.5:

        regimes.append("TREND")

    # RANGE

    else:

        regimes.append("RANGE")

df['regime'] = regimes

# ---------------------------------
# SUMMARY
# ---------------------------------

print()
print("REGIME DISTRIBUTION")
print("-------------------")

print(df['regime'].value_counts())

# ---------------------------------
# FORWARD RETURNS
# ---------------------------------

LOOKAHEAD = 12

future_returns = []

for i in range(len(df) - LOOKAHEAD):

    current_price = df.iloc[i]['close']

    future_price = df.iloc[i + LOOKAHEAD]['close']

    future_return = (
        future_price - current_price
    ) / current_price

    future_returns.append(future_return)

future_returns += [np.nan] * LOOKAHEAD

df['future_return'] = future_returns

# ---------------------------------
# REGIME PERFORMANCE
# ---------------------------------

print()
print("REGIME FUTURE RETURNS")
print("---------------------")

summary = df.groupby('regime')[
    'future_return'
].agg([
    'mean',
    'std',
    'count'
])

print(summary)
