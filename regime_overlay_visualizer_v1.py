import matplotlib
matplotlib.use("Agg")

import pandas as pd
import matplotlib.pyplot as plt

# ========================================
# LOAD BTC PRICE
# ========================================

btc = pd.read_parquet("btc_15m.parquet")

print("BTC LOADED")

btc["timestamp"] = pd.to_datetime(btc["timestamp"])

btc["timestamp"] = btc["timestamp"].astype("datetime64[ns]")

btc = btc.sort_values("timestamp")

# ========================================
# LOAD REGIME HISTORY
# ========================================

regime = pd.read_parquet("regime_history.parquet")

print("REGIME LOADED")

regime["timestamp"] = pd.to_datetime(regime["timestamp"])

regime["timestamp"] = regime["timestamp"].astype("datetime64[ns]")

regime = regime.sort_values("timestamp")

# ========================================
# FILTER BTC TO REGIME PERIOD
# ========================================

btc = btc[
    btc["timestamp"] >= regime["timestamp"].min()
].copy()

# ========================================
# MERGE
# ========================================

df = pd.merge_asof(
    btc.sort_values("timestamp"),
    regime.sort_values("timestamp"),
    on="timestamp",
    direction="backward"
)

df = df.dropna(subset=["regime"])

print("MERGE DONE")
print(df.head())
print(len(df))

# ========================================
# COLOR MAP
# ========================================

color_map = {
    "BULLISH_PRESSURE": "#00FF00",
    "BEARISH_PRESSURE": "#FF0000",
    "NEUTRAL": "#A9A9A9"
}

# ========================================
# PLOT
# ========================================

print("START PLOTTING")

fig, ax = plt.subplots(figsize=(20, 8))

# BTC PRICE
ax.plot(
    df["timestamp"],
    df["close"],
    color="black",
    linewidth=1.2
)

# REGIME OVERLAY
for i in range(len(df)-1):

    current_regime = df["regime"].iloc[i]

    color = color_map.get(
        current_regime,
        "#D3D3D3"
    )

    ax.axvspan(
        df["timestamp"].iloc[i],
        df["timestamp"].iloc[i+1],
        color=color,
        alpha=0.18
    )

# ========================================
# TITLES
# ========================================

ax.set_title(
    "BTC Behavioral Regime Overlay",
    fontsize=18
)

ax.set_xlabel("Time")

ax.set_ylabel("BTC Price")

plt.tight_layout()

# ========================================
# SAVE
# ========================================

plt.savefig(
    "btc_regime_overlay.png",
    dpi=300
)

print("\nOVERLAY SAVED")
print("btc_regime_overlay.png")

plt.close()

print("SAVE COMPLETE")
