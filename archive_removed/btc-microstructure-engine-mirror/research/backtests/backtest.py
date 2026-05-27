import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

# ---------------------------------
# LOAD DATA
# ---------------------------------

X = np.load('X.npy')
y = np.load('y.npy')

df = pd.read_parquet('btc_15m.parquet')

print("Loaded dataset")

# ---------------------------------
# REGIME FEATURES
# ---------------------------------

df['range_pct'] = (
    df['high'] - df['low']
) / df['close']

df['range_ma'] = (
    df['range_pct']
    .rolling(50)
    .mean()
)

# ---------------------------------
# FLATTEN
# ---------------------------------

X_flat = X.reshape(X.shape[0], -1)

# ---------------------------------
# SPLIT
# ---------------------------------

X_train, X_test, y_train, y_test = train_test_split(
    X_flat,
    y,
    test_size=0.2,
    shuffle=False
)

# ---------------------------------
# MODEL
# ---------------------------------

model = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    n_jobs=-1,
    class_weight='balanced'
)

print("Training model...")

model.fit(X_train, y_train)

# ---------------------------------
# PROBABILITIES
# ---------------------------------

print("Predicting probabilities...")

probs = model.predict_proba(X_test)

classes = model.classes_

short_idx = list(classes).index(-1)
long_idx = list(classes).index(1)

# ---------------------------------
# PARAMETERS
# ---------------------------------

threshold = 0.45

TP = 0.015
SL = 0.01

FEE = 0.0008

wins = 0
losses = 0

pnl = 0

equity_curve = [0]

# ---------------------------------
# TEST START
# ---------------------------------

test_start = len(X_train)

# ---------------------------------
# LOOP
# ---------------------------------

for i in range(len(probs)):

    market_idx = test_start + i + 64

    if market_idx + 12 >= len(df):
        break

    # ---------------------------------
    # REGIME FILTER
    # ---------------------------------

    current_range = df.iloc[market_idx]['range_pct']
    average_range = df.iloc[market_idx]['range_ma']

    # ONLY TRADE HIGH VOLATILITY

    if current_range <= average_range:
        continue

    # ---------------------------------
    # MODEL SIGNAL
    # ---------------------------------

    short_prob = probs[i][short_idx]
    long_prob = probs[i][long_idx]

    signal = 0

    if short_prob >= threshold:
        signal = -1

    elif long_prob >= threshold:
        signal = 1

    if signal == 0:
        continue

    # ---------------------------------
    # MARKET DATA
    # ---------------------------------

    current_price = df.iloc[market_idx]['close']

    future = df.iloc[
        market_idx+1 : market_idx+13
    ]

    # ---------------------------------
    # LONG
    # ---------------------------------

    if signal == 1:

        for _, row in future.iterrows():

            high_move = (
                row['high'] - current_price
            ) / current_price

            low_move = (
                row['low'] - current_price
            ) / current_price

            # TP

            if high_move >= TP:

                trade_pnl = TP - FEE

                pnl += trade_pnl

                equity_curve.append(pnl)

                wins += 1

                break

            # SL

            if low_move <= -SL:

                trade_pnl = -SL - FEE

                pnl += trade_pnl

                equity_curve.append(pnl)

                losses += 1

                break

    # ---------------------------------
    # SHORT
    # ---------------------------------

    if signal == -1:

        for _, row in future.iterrows():

            high_move = (
                row['high'] - current_price
            ) / current_price

            low_move = (
                row['low'] - current_price
            ) / current_price

            # TP

            if low_move <= -TP:

                trade_pnl = TP - FEE

                pnl += trade_pnl

                equity_curve.append(pnl)

                wins += 1

                break

            # SL

            if high_move >= SL:

                trade_pnl = -SL - FEE

                pnl += trade_pnl

                equity_curve.append(pnl)

                losses += 1

                break

# ---------------------------------
# RESULTS
# ---------------------------------

total_trades = wins + losses

print()
print("BACKTEST RESULTS")
print("----------------")

print("Trades:", total_trades)
print("Wins:", wins)
print("Losses:", losses)

if total_trades > 0:

    winrate = wins / total_trades

    print("Winrate:", round(winrate, 4))

print("PnL:", round(pnl, 4))

# ---------------------------------
# EQUITY CURVE
# ---------------------------------

plt.figure(figsize=(12, 6))

plt.plot(equity_curve)

plt.title("Equity Curve")

plt.xlabel("Trades")

plt.ylabel("PnL")

plt.grid(True)

plt.show()
