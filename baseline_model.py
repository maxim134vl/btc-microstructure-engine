import numpy as np

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

# LOAD DATA

X = np.load('X.npy')
y = np.load('y.npy')

print("Loaded dataset")

# FLATTEN

X = X.reshape(X.shape[0], -1)

print("Flattened shape:", X.shape)

# SPLIT

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    shuffle=False
)

print("Training model...")

model = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    n_jobs=-1,
    class_weight='balanced'
)

model.fit(X_train, y_train)

print("Predicting...")

preds = model.predict(X_test)

print(classification_report(y_test, preds))

# ---------------------------------
# PROBABILITIES
# ---------------------------------

probs = model.predict_proba(X_test)

classes = model.classes_

short_idx = list(classes).index(-1)
neutral_idx = list(classes).index(0)
long_idx = list(classes).index(1)

# LOWER THRESHOLD

threshold = 0.45

signals = []

for i in range(len(probs)):

    short_prob = probs[i][short_idx]
    long_prob = probs[i][long_idx]

    # SHORT SIGNAL

    if short_prob >= threshold:

        signals.append((-1, y_test[i]))

    # LONG SIGNAL

    elif long_prob >= threshold:

        signals.append((1, y_test[i]))

# ---------------------------------
# EVALUATE SIGNALS
# ---------------------------------

if len(signals) == 0:

    print()
    print("No high-confidence signals found.")

else:

    correct = 0

    for pred, actual in signals:

        if pred == actual:
            correct += 1

    accuracy = correct / len(signals)

    print()
    print("HIGH CONFIDENCE SIGNALS")
    print("-----------------------")
    print("Signals:", len(signals))
    print("Accuracy:", accuracy)
