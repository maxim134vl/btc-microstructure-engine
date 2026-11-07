import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from xgboost import XGBClassifier

# ---------------------------------
# LOAD DATA
# ---------------------------------

X = np.load('X.npy')
y = np.load('y.npy')

print("Loaded dataset")

# ---------------------------------
# LABEL MAPPING
# ---------------------------------

y_mapped = np.zeros_like(y)

y_mapped[y == -1] = 0
y_mapped[y == 0] = 1
y_mapped[y == 1] = 2

y = y_mapped

# ---------------------------------
# FEATURE NAMES
# ---------------------------------

feature_names = [
    'open',
    'high',
    'low',
    'close',
    'volume',

    'return',
    'volatility',
    'body',
    'upper_wick',
    'lower_wick',
    'volume_zscore',
    'range',

    'fundingRate',
    'funding_zscore'
]

# ---------------------------------
# USE LAST CANDLE ONLY
# ---------------------------------

X_last = X[:, -1, :]

print("Shape:", X_last.shape)

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

print("Training model...")

model.fit(X_last, y)

# ---------------------------------
# IMPORTANCE
# ---------------------------------

importance = model.feature_importances_

importance_df = pd.DataFrame({
    'feature': feature_names,
    'importance': importance
})

importance_df = (
    importance_df
    .sort_values(
        'importance',
        ascending=False
    )
)

print()
print("FEATURE IMPORTANCE")
print("------------------")

print(importance_df)

# ---------------------------------
# PLOT
# ---------------------------------

plt.figure(figsize=(10, 6))

plt.barh(
    importance_df['feature'],
    importance_df['importance']
)

plt.gca().invert_yaxis()

plt.title("Feature Importance")

plt.xlabel("Importance")

plt.tight_layout()

plt.show()
