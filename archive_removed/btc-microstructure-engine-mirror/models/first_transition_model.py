import pandas as pd
import numpy as np

from sklearn.model_selection import (
    train_test_split
)

from sklearn.ensemble import (
    RandomForestClassifier
)

from sklearn.metrics import (
    classification_report,
    accuracy_score
)

# =================================
# LOAD DATA
# =================================

print()
print("LOADING DATA")
print()

df = pd.read_parquet(
    "transition_labels.parquet"
)

# =================================
# CLEAN
# =================================

df = df.dropna()

# =================================
# FEATURES
# =================================

features = [

    'delta_pressure',

    'volatility',

    'volume'
]

X = df[features]

# =================================
# TARGET
# =================================

y = df['expansion']

# =================================
# SPLIT
# =================================

X_train, X_test, y_train, y_test = (

    train_test_split(

        X,

        y,

        test_size=0.2,

        shuffle=False
    )
)

# =================================
# MODEL
# =================================

print(
    "TRAINING MODEL"
)

print()

model = RandomForestClassifier(

    n_estimators=200,

    max_depth=5,

    random_state=42
)

model.fit(

    X_train,

    y_train
)

# =================================
# PREDICT
# =================================

preds = model.predict(
    X_test
)

# =================================
# METRICS
# =================================

acc = accuracy_score(

    y_test,

    preds
)

print("================================")
print("MODEL RESULTS")
print("================================")
print()

print(
    "ACCURACY:",
    round(acc, 4)
)

print()

print(
    classification_report(
        y_test,
        preds
    )
)

# =================================
# FEATURE IMPORTANCE
# =================================

importance = pd.DataFrame({

    'feature':
        features,

    'importance':
        model.feature_importances_
})

importance = importance.sort_values(

    'importance',

    ascending=False
)

print("================================")
print("FEATURE IMPORTANCE")
print("================================")
print()

print(
    importance
)

print()

# =================================
# LIVE STATE
# =================================

latest = X.iloc[[-1]]

prob = model.predict_proba(
    latest
)[0][1]

print("================================")
print("CURRENT MARKET STATE")
print("================================")
print()

print(
    "P(EXPANSION):",
    round(prob, 4)
)

print()

if prob > 0.7:

    print(
        "HIGH EXPANSION RISK"
    )

elif prob > 0.5:

    print(
        "MODERATE EXPANSION RISK"
    )

else:

    print(
        "LOW EXPANSION RISK"
    )

print()

print(
    "MODEL COMPLETE"
)
