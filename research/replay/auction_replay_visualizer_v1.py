import pandas as pd
import mplfinance as mpf

print("\nAUCTION REPLAY VISUALIZER STARTED\n")

# =====================================
# LOAD DATA
# =====================================

flow = pd.read_parquet(
    "multi_exchange_flow.parquet"
)

flow["timestamp"] = pd.to_datetime(
    flow["timestamp"]
)

flow = flow.sort_values("timestamp")

# =====================================
# BUILD OHLC
# =====================================

ohlc = flow.resample(
    "1h",
    on="timestamp"
).agg({
    "avg_price": [
        "first",
        "max",
        "min",
        "last"
    ],
    "delta": "sum",
    "buy_volume": "sum",
    "sell_volume": "sum"
})

ohlc.columns = [
    "Open",
    "High",
    "Low",
    "Close",
    "Delta",
    "BuyVolume",
    "SellVolume"
]

ohlc = ohlc.dropna()

# =====================================
# DETECT INITIATIVES
# =====================================

buy_signals = []

sell_signals = []

for i in range(len(ohlc)):

    row = ohlc.iloc[i]

    delta = row["Delta"]

    close = row["Close"]

    timestamp = ohlc.index[i]

    # BUY INITIATIVE

    if delta > 70:

        buy_signals.append(
            (timestamp, close)
        )

    # SELL INITIATIVE

    elif delta < -70:

        sell_signals.append(
            (timestamp, close)
        )

# =====================================
# BUILD SIGNAL SERIES
# =====================================

buy_series = pd.Series(
    index=ohlc.index,
    dtype=float
)

sell_series = pd.Series(
    index=ohlc.index,
    dtype=float
)

for ts, price in buy_signals:

    buy_series.loc[ts] = price

for ts, price in sell_signals:

    sell_series.loc[ts] = price

# =====================================
# BUILD PLOTS
# =====================================

apds = [

    mpf.make_addplot(
        buy_series,
        type='scatter',
        marker='^',
        markersize=120
    ),

    mpf.make_addplot(
        sell_series,
        type='scatter',
        marker='v',
        markersize=120
    )

]

# =====================================
# SHOW CHART
# =====================================

mpf.plot(
    ohlc,
    type='candle',
    style='charles',
    title='Behavioral Initiative Replay',
    volume=False,
    addplot=apds,
    figsize=(18, 10),
    tight_layout=True
)

# =====================================
# SUMMARY
# =====================================

print("\n================================")
print("INITIATIVE SUMMARY")
print("================================\n")

print(
    f"BUY INITIATIVES: {len(buy_signals)}"
)

print(
    f"SELL INITIATIVES: {len(sell_signals)}"
)

print(
    f"TOTAL INITIATIVES: {len(buy_signals) + len(sell_signals)}"
)
