import matplotlib
matplotlib.use("Agg")

import pandas as pd
import matplotlib.pyplot as plt

# ========================================
# LOAD BTC
# ========================================

btc = pd.read_parquet("btc_15m.parquet")

btc["timestamp"] = pd.to_datetime(
    btc["timestamp"]
).astype("datetime64[ns]")

btc = btc.sort_values("timestamp")

# ========================================
# LOAD REGIME
# ========================================

regime = pd.read_parquet("regime_history.parquet")

regime["timestamp"] = pd.to_datetime(
    regime["timestamp"]
).astype("datetime64[ns]")

regime = regime.sort_values("timestamp")

# ========================================
# PRINT RANGES
# ========================================

print("\nBTC RANGE:")
print(btc["timestamp"].min())
print(btc["timestamp"].max())

print("\nREGIME RANGE:")
print(regime["timestamp"].min())
print(regime["timestamp"].max())

# ========================================
# FILTER BTC TO REGIME PERIOD
# ========================================

start = regime["timestamp"].min()
end = regime["timestamp"].max()

btc_filtered = btc[
    (btc["timestamp"] >= start) &
    (btc["timestamp"] <= end)
].copy()

print("\nFILTERED BTC ROWS:")
print(len(btc_filtered))

# ========================================
# IF EMPTY -> EXIT
# ========================================

if len(btc_filtered) == 0:

    print("\nNO TIME OVERLAP FOUND")
    print("btc_15m.parquet does not overlap with regime_history.parquet")

    exit()

# ========================================
# MERGE
# ========================================

merged = pd.merge_asof(
    btc_filtered,
    regime,
    on="timestamp",
    direction="nearest",
    tolerance=pd.Timedelta("30m")
)

merged = merged.dropna(subset=["regime"])

print("\nMERGED ROWS:")
print(len(merged))

# ========================================
# COLORS
# ========================================

color_map = {
    "BULLISH_PRESSURE": "green",
    "BEARISH_PRESSURE": "red",
    "NEUTRAL": "gray"
}

# ========================================
# PLOT
# ========================================

fig, ax = plt.subplots(figsize=(18, 8))

ax.plot(
    merged["timestamp"],
    merged["close"],
    color="black",
    linewidth=1.5
)

for i in range(len(merged) - 1):

    regime_name = merged["regime"].iloc[i]

    color = color_map.get(
        regime_name,
        "gray"
    )

    ax.axvspan(
        merged["timestamp"].iloc[i],
        merged["timestamp"].iloc[i + 1],
        color=color,
        alpha=0.18
    )

ax.set_title(
    "BTC Behavioral Regime Overlay"
)

ax.set_xlabel("Time")

ax.set_ylabel("BTC Price")

plt.tight_layout()

# ========================================
# SAVE
# ========================================

plt.savefig(
    "btc_regime_overlay_v3.png",
    dpi=300
)

plt.close()

print("\nDONE")
print("btc_regime_overlay_v3.png")
