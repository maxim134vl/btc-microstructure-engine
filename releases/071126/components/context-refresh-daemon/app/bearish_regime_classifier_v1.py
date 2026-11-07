import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ========================================
# LOAD DATA
# ========================================

df = pd.read_parquet("bearish_context_master.parquet")

df = df.sort_values("timestamp").reset_index(drop=True)

# ========================================
# NORMALIZATION
# ========================================

metrics = [
    "progression_efficiency",
    "rotation",
    "retention_failure",
    "directional_flips",
    "deterioration_acceleration"
]

for col in metrics:
    rolling_mean = df[col].rolling(100).mean()
    rolling_std = df[col].rolling(100).std()

    df[f"{col}_z"] = (
        (df[col] - rolling_mean) / rolling_std
    )

# ========================================
# REGIME SCORE
# ========================================

df["bearish_regime_score"] = (
    - df["progression_efficiency_z"] * 2.0
    + df["rotation_z"] * 1.5
    + df["retention_failure_z"] * 2.0
    + df["directional_flips_z"] * 1.0
    + df["deterioration_acceleration_z"] * 1.5
)

# ========================================
# REGIME CLASSIFICATION
# ========================================

conditions = [
    df["bearish_regime_score"] <= -1.5,

    (df["bearish_regime_score"] > -1.5) &
    (df["bearish_regime_score"] <= 0.5),

    (df["bearish_regime_score"] > 0.5) &
    (df["bearish_regime_score"] <= 2.0),

    df["bearish_regime_score"] > 2.0
]

choices = [
    "HEALTHY_BEARISH",
    "TRANSITION",
    "ROTATIONAL_INSTABILITY",
    "EXHAUSTION_COLLAPSE"
]

df["regime"] = np.select(
    conditions,
    choices,
    default="NEUTRAL"
)

# ========================================
# COLORS
# ========================================

color_map = {
    "HEALTHY_BEARISH": "#8B0000",
    "TRANSITION": "#1E90FF",
    "ROTATIONAL_INSTABILITY": "#FFD700",
    "EXHAUSTION_COLLAPSE": "#808080",
    "NEUTRAL": "#D3D3D3"
}

# ========================================
# PLOT
# ========================================

fig, ax = plt.subplots(figsize=(18, 8))

ax.plot(
    df["timestamp"],
    df["close"],
    color="black",
    linewidth=1.2,
    label="BTC Price"
)

for i in range(len(df)-1):

    regime = df["regime"].iloc[i]

    ax.axvspan(
        df["timestamp"].iloc[i],
        df["timestamp"].iloc[i+1],
        color=color_map[regime],
        alpha=0.18
    )

ax.set_title(
    "Bearish Behavioral Regime Overlay",
    fontsize=18
)

ax.set_xlabel("Time")
ax.set_ylabel("Price")

plt.tight_layout()

plt.savefig(
    "bearish_regime_overlay.png",
    dpi=300
)

plt.show()

print("\nREGIME OVERLAY SAVED")
print("bearish_regime_overlay.png")
