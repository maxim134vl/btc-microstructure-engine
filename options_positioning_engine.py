import pandas as pd

# =================================
# LOAD DATA
# =================================

print()
print("LOADING OPTIONS DATA")
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
# SUMMARY
# =================================

print("================================")
print("MARKET SUMMARY")
print("================================")
print()

print(
    "TOTAL OPTIONS:",
    len(latest)
)

print()

# =================================
# CALLS VS PUTS
# =================================

calls = latest[
    latest['type'] == 'C'
]

puts = latest[
    latest['type'] == 'P'
]

call_volume = (
    calls['volume']
    .sum()
)

put_volume = (
    puts['volume']
    .sum()
)

print("================================")
print("CALL / PUT STRUCTURE")
print("================================")
print()

print(
    "CALL VOLUME:",
    round(call_volume, 2)
)

print(
    "PUT VOLUME:",
    round(put_volume, 2)
)

print()

if put_volume > 0:

    ratio = (
        call_volume
        /
        put_volume
    )

    print(
        "CALL/PUT RATIO:",
        round(ratio, 2)
    )

print()

# =================================
# TOP STRIKES
# =================================

print("================================")
print("TOP STRIKES")
print("================================")
print()

strike_volume = (

    latest
    .groupby('strike')
    ['volume']
    .sum()
    .sort_values(
        ascending=False
    )
)

print(
    strike_volume
    .head(15)
)

print()

# =================================
# EXPIRATION ANALYSIS
# =================================

print("================================")
print("TOP EXPIRATIONS")
print("================================")
print()

expiration_volume = (

    latest
    .groupby('expiration')
    ['volume']
    .sum()
    .sort_values(
        ascending=False
    )
)

print(
    expiration_volume
    .head(10)
)

print()

# =================================
# NEAR PRICE OPTIONS
# =================================

underlying = (

    latest[
        'underlying'
    ]
    .median()
)

print("================================")
print("UNDERLYING")
print("================================")
print()

print(
    "BTC PRICE:",
    round(
        underlying,
        2
    )
)

print()

latest['distance'] = (

    (
        latest['strike']

        -

        underlying
    )
    .abs()
)

near = latest.sort_values(
    'distance'
)

print("================================")
print("NEAR PRICE POSITIONING")
print("================================")
print()

print(

    near[
        [
            'symbol',
            'strike',
            'type',
            'volume',
            'iv'
        ]
    ]
    .head(20)
)

print()

# =================================
# HIGH VOLUME OPTIONS
# =================================

print("================================")
print("HIGHEST VOLUME OPTIONS")
print("================================")
print()

top = latest.sort_values(

    'volume',

    ascending=False
)

print(

    top[
        [
            'symbol',
            'strike',
            'type',
            'volume',
            'iv'
        ]
    ]
    .head(20)
)

print()

print(
    "POSITIONING ANALYSIS COMPLETE"
)
