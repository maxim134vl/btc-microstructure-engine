import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

from xgboost import XGBClassifier

# ---------------------------------
# LOAD
# ---------------------------------

X = np.load('X_adv.npy')
y = np.load('y_adv.npy')

print("Loaded advanced dataset")

# ---------------------------------
# LABEL MAPPING
# ---------------------------------

y_mapped = np.zeros_like(y)

y_mapped[y == -1] = 0
y_mapped[y == 0] = 1
y_mapped[y == 1] = 2

y = y_mapped

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
# MODEL
# ---------------------------------

model = XGBClassifier(
    n_estimators=300,
    max_depth=6,
    learning_rate=0.03,
    subsample=0.8,
    colsample_bytree=0.8,
    tree_method='hist',
    eval_metric='mlogloss',
    objective='multi:softprob',
    num_class=3
)

print()
print("Training advanced XGBoost...")

model.fit(X_train, y_train)

# ---------------------------------
# PREDICT
# ---------------------------------

probs = model.predict_proba(X_test)

preds = np.argmax(
    probs,
    axis=1
)

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

max_probs = probs.max(axis=1)

high_conf = max_probs >= 0.7

if np.sum(high_conf) > 0:

    high_acc = (
        y_test[high_conf]
        ==
        preds[high_conf]
    ).mean()

    print()
    print("HIGH CONFIDENCE")
    print("----------------")

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
