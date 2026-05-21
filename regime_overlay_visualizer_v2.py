import matplotlib
matplotlib.use("Agg")

import pandas as pd
import matplotlib.pyplot as plt

# ========================================
# LOAD BTC DATA
# ========================================

btc = pd.read_parquet("btc_15m.parquet")

btc["timestamp"] = pd.to_datetime(btc["timestamp"])

btc = btc.sort_values("timestamp")

# ========================================
# LOAD REGIME DATA
# ========================================

regime = pd.read_parquet("regime_history.parquet")

regime["timestamp"] = pd.to_datetime(regime["timestamp"])

regime = regime.sort_values("timestamp")

# ========================================
# FILTER TO REAL OVERLAP
# ========================================

start_time = regime["timestamp"].min()
end_time = regime["timestamp"].max()

btc = btc[
    (btc["timestamp"] >= start_time) &
    (btc["timestamp"] <= end_time)
].copy()

print("BTC ROWS:", len(btc))

# ========================================
# MERGE
# ========================================

merged = pd.merge_asof(
    btc,
    regime,
    on="timestamp",
    direction="nearest",
    tolerance=pd.Timedelta("30m")
)

merged = merged.dropna(subset=["regime"])

print("MERGED ROWS:", len(merged))

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

    color = color_map.get(regime_name, "gray")

    ax.axvspan(
        merged["timestamp"].iloc[i],
        merged["timestamp"].iloc[i + 1],
        color=color,
        alpha=0.18
    )

ax.set_title("BTC Behavioral Regime Overlay")

ax.set_xlabel("Time")

ax.set_ylabel("BTC Price")

plt.tight_layout()

plt.savefig(
    "btc_regime_overlay_v2.png",
    dpi=300
)

plt.close()

print("DONE")
print("btc_regime_overlay_v2.png")
