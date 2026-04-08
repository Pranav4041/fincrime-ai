import joblib
import numpy as np

MODEL_PATH = "app/models/fraud_model.pkl"
FEATURES_PATH = "app/models/feature_columns.pkl"
MEDIANS_PATH = "app/models/feature_medians.pkl"

# Load everything once
model = joblib.load(MODEL_PATH)
feature_columns = joblib.load(FEATURES_PATH)
medians = joblib.load(MEDIANS_PATH)


def build_features(txn):
    features = {}

    # ✅ Map dict input → model features
    amount = txn["TransactionAmt"]
    hour = txn["hour"]

    features["TransactionAmt"] = amount
    features["hour"] = hour
    features["is_night"] = int(hour < 6 or hour > 22)

    # ✅ Simulated values (important for ML compatibility)
    features["card1"] = 1000
    features["addr1"] = 300

    # Fill missing features with medians
    for col in feature_columns:
        if col not in features:
            features[col] = medians.get(col, 0)

    # Convert to array in correct order
    X = np.array([features[col] for col in feature_columns]).reshape(1, -1)

    return X


def predict_ml(txn):
    X = build_features(txn)
    prob = model.predict_proba(X)[0][1]
    return float(prob)