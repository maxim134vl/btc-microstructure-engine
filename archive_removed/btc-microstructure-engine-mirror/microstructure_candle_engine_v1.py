import pandas as pd
from datetime import datetime

print()
print("MICROSTRUCTURE CANDLE ENGINE")
print()

# =====================================
# LOAD DATA
# =====================================

df = pd.read_parquet(
    "btc_15m.parquet"
)

latest = df.iloc[-1]

# =====================================
# EXTRACT
# =====================================

open_price = latest["open"]
high_price = latest["high"]
low_price = latest["low"]
close_price = latest["close"]
volume = latest["volume"]

# =====================================
# GEOMETRY
# =====================================

spread = (
    high_price - low_price
)

body = abs(
    close_price - open_price
)

upper_wick = (
    high_price - max(
        open_price,
        close_price
    )
)

lower_wick = (
    min(
        open_price,
        close_price
    ) - low_price
)

# =====================================
# CLOSE LOCATION
# =====================================

if spread > 0:

    close_position = (

        (
            close_price - low_price
        )

        / spread

    )

else:

    close_position = 0.5

# =====================================
# VOLUME LOCALIZATION
# =====================================

volume_location = (
    "MID"
)

if close_position >= 0.7:

    volume_location = (
        "UPPER_AUCTION"
    )

elif close_position <= 0.3:

    volume_location = (
        "LOWER_AUCTION"
    )

# =====================================
# BEHAVIOR
# =====================================

behavior = (
    "NEUTRAL"
)

# -------------------------------------

if (

    upper_wick > body * 1.5

    and

    close_position < 0.5

):

    behavior = (
        "UPPER_REJECTION"
    )

# -------------------------------------

elif (

    lower_wick > body * 1.5

    and

    close_position > 0.5

):

    behavior = (
        "LOWER_REJECTION"
    )

# -------------------------------------

elif (

    body > (
        spread * 0.7
    )

):

    behavior = (
        "DIRECTIONAL_ACCEPTANCE"
    )

# -------------------------------------

elif (

    body < (
        spread * 0.3
    )

):

    behavior = (
        "ROTATIONAL_AUCTION"
    )

# =====================================
# OUTPUT
# =====================================

print(
    "BEHAVIOR:"
)

print(
    behavior
)

print()

print(
    "VOLUME LOCATION:"
)

print(
    volume_location
)

print()

print(
    "CLOSE POSITION:"
)

print(
    round(
        close_position,
        2
    )
)

print()

# =====================================
# SAVE
# =====================================

row = pd.DataFrame([{

    "timestamp":
        datetime.utcnow(),

    "behavior":
        behavior,

    "volume_location":
        volume_location,

    "close_position":
        close_position,

    "spread":
        spread,

    "body":
        body,

    "upper_wick":
        upper_wick,

    "lower_wick":
        lower_wick,

    "volume":
        volume

}])

row.to_parquet(
    "microstructure_candle_memory.parquet"
)
