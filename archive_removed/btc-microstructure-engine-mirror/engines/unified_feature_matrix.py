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

oi = pd.read_parquet(
    "oi_history.parquet"
)

book = pd.read_parquet(
    "orderbook.parquet"
)

labels = pd.read_parquet(
    "transition_labels.parquet"
)

# =================================
# ALIGN LENGTHS
# =================================

min_len = min(

    len(flow),

    len(oi),

    len(book),

    len(labels)
)

flow = flow.tail(min_len)
oi = oi.tail(min_len)
book = book.tail(min_len)
labels = labels.tail(min_len)

# =================================
# FLOW FEATURES
# =================================

print(
    "BUILDING FEATURES"
)

print()

features = pd.DataFrame()

# TIMESTAMP

features['timestamp'] = (

    flow['timestamp']
    .values
)

# PRICE

features['price'] = (

    flow['avg_price']
    .values
)

# DELTA PRESSURE

features['delta_pressure'] = (

    flow['delta']
    .rolling(20)
    .mean()
    .values
)

# VOLUME

features['volume'] = (

    (
        flow['buy_volume']

        +

        flow['sell_volume']
    )
    .values
)

# VOLATILITY

returns = (

    flow['avg_price']
    .pct_change()
)

features['volatility'] = (

    returns
    .rolling(50)
    .std()
    .values
)

# =================================
# OI FEATURES
# =================================

features['oi'] = (

    oi['open_interest']
    .values
)

features['oi_change'] = (

    oi['open_interest']
    .pct_change()
    .values
)

# =================================
# ORDERBOOK FEATURES
# =================================

features['imbalance'] = (

    book['imbalance']
    .values
)

# =================================
# FUTURE LABELS
# =================================

features['expansion'] = (

    labels['expansion']
    .values
)

features['breakout_up'] = (

    labels['breakout_up']
    .values
)

features['breakout_down'] = (

    labels['breakout_down']
    .values
)

features['squeeze'] = (

    labels['squeeze']
    .values
)

# =================================
# CLEAN
# =================================

features = features.dropna()

# =================================
# SAVE
# =================================

features.to_parquet(
    "unified_features.parquet"
)

# =================================
# SUMMARY
# =================================

print("================================")
print("UNIFIED FEATURE MATRIX")
print("================================")
print()

print(
    "ROWS:",
    len(features)
)

print()

print(
    "COLUMNS:"
)

print()

print(
    features.columns
)

print()

print(
    "LABEL DISTRIBUTION"
)

print()

for col in [

    'expansion',

    'breakout_up',

    'breakout_down',

    'squeeze'
]:

    print(
        col,
        ":",
        int(
            features[col]
            .sum()
        )
    )

print()

print(
    "FEATURE MATRIX COMPLETE"
)
