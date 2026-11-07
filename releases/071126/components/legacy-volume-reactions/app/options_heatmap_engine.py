import pandas as pd

# =================================
# LOAD DATA
# =================================

print()
print(
    "LOADING OPTIONS DATA"
)
print()

df = pd.read_parquet(
    "binance_options.parquet"
)

# =================================
# LATEST SNAPSHOT
# =================================

latest_time = df[
    'timestamp'
].max()

latest = df[
    df['timestamp']
    ==
    latest_time
]

# =================================
# CLEAN
# =================================

latest = latest.copy()

latest['strike'] = pd.to_numeric(

    latest['strike'],

    errors='coerce'
)

latest['volume'] = pd.to_numeric(

    latest['volume'],

    errors='coerce'
)

latest = latest.dropna()

# =================================
# CALLS / PUTS
# =================================

calls = latest[
    latest['type']
    ==
    'CALL'
]

puts = latest[
    latest['type']
    ==
    'PUT'
]

# =================================
# STRIKE ANALYSIS
# =================================

call_heatmap = (

    calls
    .groupby('strike')
    ['volume']
    .sum()
)

put_heatmap = (

    puts
    .groupby('strike')
    ['volume']
    .sum()
)

# =================================
# OUTPUT
# =================================

print("================================")
print("OPTIONS HEATMAP")
print("================================")
print()

print(
    "TOTAL CONTRACTS:",
    len(latest)
)

print()

# =================================
# TOP CALL STRIKES
# =================================

print("================================")
print("TOP CALL STRIKES")
print("================================")
print()

if len(call_heatmap) > 0:

    print(

        call_heatmap
        .sort_values(
            ascending=False
        )
        .head(20)
    )

else:

    print(
        "NO CALL DATA"
    )

print()

# =================================
# TOP PUT STRIKES
# =================================

print("================================")
print("TOP PUT STRIKES")
print("================================")
print()

if len(put_heatmap) > 0:

    print(

        put_heatmap
        .sort_values(
            ascending=False
        )
        .head(20)
    )

else:

    print(
        "NO PUT DATA"
    )

print()

# =================================
# TOTAL STRUCTURE
# =================================

total = (

    latest
    .groupby(
        [
            'strike',
            'type'
        ]
    )
    ['volume']
    .sum()
    .reset_index()
)

total = total.sort_values(

    'volume',

    ascending=False
)

print("================================")
print("HIGHEST ACTIVITY OPTIONS")
print("================================")
print()

print(
    total.head(30)
)

print()

# =================================
# EXPIRATION CLUSTERS
# =================================

expiration = (

    latest
    .groupby('expiration')
    ['volume']
    .sum()
    .sort_values(
        ascending=False
    )
)

print("================================")
print("EXPIRATION CLUSTERS")
print("================================")
print()

print(
    expiration.head(20)
)

print()

print(
    "HEATMAP ANALYSIS COMPLETE"
)
