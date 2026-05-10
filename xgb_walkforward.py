import numpy as np
import pandas as pd

from xgboost import XGBClassifier

# ---------------------------------
# LOAD DATA
# ---------------------------------

X = np.load('X.npy')
y = np.load('y.npy')

df = pd.read_parquet('btc_15m.parquet')

print("Loaded dataset")

# ---------------------------------
# LABEL MAPPING
# ---------------------------------

y_mapped = np.zeros_like(y)

y_mapped[y == -1] = 0
y_mapped[y == 0] = 1
y_mapped[y == 1] = 2

y = y_mapped

print("Unique classes:", np.unique(y))

# ---------------------------------
# FLATTEN
# ---------------------------------

X = X.reshape(X.shape[0], -1)

# ---------------------------------
# PARAMETERS
# ---------------------------------

TRAIN_SIZE = 50000
TEST_SIZE = 10000

TP = 0.015
SL = 0.01

FEE = 0.0008

# LOWER THRESHOLD

threshold = 0.30

# ---------------------------------
# RESULTS
# ---------------------------------

total_pnl = 0

total_wins = 0
total_losses = 0

window_results = []

# ---------------------------------
# WALK FORWARD
# ---------------------------------

start = 0

while True:

    train_start = start
    train_end = train_start + TRAIN_SIZE

    test_start = train_end
    test_end = test_start + TEST_SIZE

    if test_end >= len(X):
        break

    print()
    print("----------------------------")
    print(f"TRAIN: {train_start} -> {train_end}")
    print(f"TEST : {test_start} -> {test_end}")

    # ---------------------------------
    # SPLIT
    # ---------------------------------

    X_train = X[train_start:train_end]
    y_train = y[train_start:train_end]

    X_test = X[test_start:test_end]
    y_test = y[test_start:test_end]

    # ---------------------------------
    # MODEL
    # ---------------------------------

    model = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective='multi:softprob',
        num_class=3,
        tree_method='hist',
        eval_metric='mlogloss'
    )

    print("Training XGBoost...")

    model.fit(X_train, y_train)

    probs = model.predict_proba(X_test)

    short_idx = 0
    long_idx = 2

    # ---------------------------------
    # WINDOW RESULTS
    # ---------------------------------

    pnl = 0

    wins = 0
    losses = 0

    # ---------------------------------
    # LOOP
    # ---------------------------------

    for i in range(len(probs)):

        short_prob = probs[i][short_idx]
        long_prob = probs[i][long_idx]

        signal = 0

        if short_prob >= threshold:
            signal = -1

        elif long_prob >= threshold:
            signal = 1

        if signal == 0:
            continue

        market_idx = test_start + i + 64

        if market_idx + 12 >= len(df):
            break

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

                if high_move >= TP:

                    pnl += TP - FEE

                    wins += 1

                    break

                if low_move <= -SL:

                    pnl -= SL + FEE

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

                if low_move <= -TP:

                    pnl += TP - FEE

                    wins += 1

                    break

                if high_move >= SL:

                    pnl -= SL + FEE

                    losses += 1

                    break

    # ---------------------------------
    # WINDOW SUMMARY
    # ---------------------------------

    trades = wins + losses

    if trades > 0:
        winrate = wins / trades
    else:
        winrate = 0

    print("Trades :", trades)
    print("Winrate:", round(winrate, 4))
    print("PnL    :", round(pnl, 4))

    total_pnl += pnl

    total_wins += wins
    total_losses += losses

    window_results.append(pnl)

    start += TEST_SIZE

# ---------------------------------
# FINAL RESULTS
# ---------------------------------

print()
print("================================")
print("FINAL RESULTS")
print("================================")

total_trades = total_wins + total_losses

if total_trades > 0:
    total_winrate = total_wins / total_trades
else:
    total_winrate = 0

print("Total Trades :", total_trades)
print("Total Winrate:", round(total_winrate, 4))
print("Total PnL    :", round(total_pnl, 4))

print()
print("Window PnLs:")
print(window_results)
