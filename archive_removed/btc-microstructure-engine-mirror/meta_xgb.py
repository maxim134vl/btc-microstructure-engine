import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

from xgboost import XGBClassifier

# ---------------------------------
# LOAD
# ---------------------------------

X = np.load('X_meta.npy')
y = np.load('y_meta.npy')

print("Loaded meta dataset")

# ---------------------------------
# FLATTEN
# ---------------------------------

X = X.reshape(X.shape[0], -1)

print("Shape:", X.shape)

# ---------------------------------
# SPLIT
# ---------------------------------

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    shuffle=False
)

# ---------------------------------
# CLASS BALANCE
# ---------------------------------

positive = np.sum(y_train == 1)
negative = np.sum(y_train == 0)

scale_pos_weight = negative / positive

print()
print("scale_pos_weight:", round(scale_pos_weight, 2))

# ---------------------------------
# MODEL
# ---------------------------------

model = XGBClassifier(
    n_estimators=300,
    max_depth=6,
    learning_rate=0.03,
    subsample=0.8,
    colsample_bytree=0.8,
    scale_pos_weight=scale_pos_weight,
    tree_method='hist',
    eval_metric='logloss'
)

print()
print("Training meta-model...")

model.fit(X_train, y_train)

# ---------------------------------
# PREDICT
# ---------------------------------

probs = model.predict_proba(X_test)[:, 1]

preds = (probs >= 0.5).astype(int)

# ---------------------------------
# REPORT
# ---------------------------------

print()
print("CLASSIFICATION REPORT")
print("---------------------")

print(
    classification_report(
        y_test,
        preds
    )
)

# ---------------------------------
# HIGH CONFIDENCE
# ---------------------------------

high_conf = probs >= 0.8

if np.sum(high_conf) > 0:

    high_acc = (
        y_test[high_conf]
        ==
        preds[high_conf]
    ).mean()

    print()
    print("HIGH CONFIDENCE SIGNALS")
    print("-----------------------")

    print(
        "Signals:",
        np.sum(high_conf)
    )

    print(
        "Accuracy:",
        round(high_acc, 4)
    )

else:

    print()
    print("No high-confidence signals")
