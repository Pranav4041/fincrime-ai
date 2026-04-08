"""
test_model.py — Test Fraud Detection Model on test_transaction.csv
Place in: backend/test_model.py
Run from backend/: python test_model.py
"""

import pandas as pd
import numpy as np
import joblib
import os
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TEST_DATA_PATH = "../data/test_transaction.csv"
MODEL_DIR      = "app/models"

# ─────────────────────────────────────────────
# 1. LOAD MODEL ARTIFACTS
# ─────────────────────────────────────────────
print("\n📦 Loading model artifacts...")
model           = joblib.load(f"{MODEL_DIR}/fraud_model.pkl")
feature_columns = joblib.load(f"{MODEL_DIR}/feature_columns.pkl")
label_encoders  = joblib.load(f"{MODEL_DIR}/label_encoders.pkl")
feature_medians = joblib.load(f"{MODEL_DIR}/feature_medians.pkl")
print("   ✅ All artifacts loaded")

# ─────────────────────────────────────────────
# 2. LOAD TEST DATA
# ─────────────────────────────────────────────
print("\n📂 Loading test data...")
df = pd.read_csv(TEST_DATA_PATH)
print(f"   Shape: {df.shape[0]:,} rows × {df.shape[1]} columns")

transaction_ids = df['TransactionID'].copy()

# ─────────────────────────────────────────────
# 3. ENGINEER SAME FEATURES AS TRAINING
# ─────────────────────────────────────────────
print("\n⚙️  Engineering features...")

# Time features
df['hour']        = (df['TransactionDT'] // 3600) % 24
df['day_of_week'] = (df['TransactionDT'] // (3600 * 24)) % 7
df['is_night']    = df['hour'].between(0, 5).astype(int)

# Amount features
df['amt_log']        = np.log1p(df['TransactionAmt'])
df['amt_round']      = (df['TransactionAmt'] % 1 == 0).astype(int)
df['amt_cents_zero'] = ((df['TransactionAmt'] * 100) % 100 == 0).astype(int)

# Card null count
df['card_null_count'] = df[['card1','card2','card3','card4','card5','card6']].isnull().sum(axis=1)

# Email features
risky_domains = {'gmail.com', 'yahoo.com', 'hotmail.com', 'anonymous.com', 'protonmail.com'}
df['P_email_risky'] = df['P_emaildomain'].isin(risky_domains).astype(int)
df['R_email_risky'] = df['R_emaildomain'].isin(risky_domains).astype(int)
df['email_match']   = (df['P_emaildomain'] == df['R_emaildomain']).astype(int)

# C columns sum
c_cols = [c for c in df.columns if c.startswith('C') and c[1:].isdigit()]
df['C_sum'] = df[c_cols].sum(axis=1)

df.drop(columns=['TransactionDT'], inplace=True, errors='ignore')

# ─────────────────────────────────────────────
# 4. ALIGN COLUMNS TO TRAINING FEATURES
# ─────────────────────────────────────────────
print("\n🔧 Aligning columns to training features...")

# Encode categoricals using saved encoders
for col, le in label_encoders.items():
    if col in df.columns:
        # Handle unseen labels gracefully
        df[col] = df[col].fillna('missing').astype(str)
        known_classes = set(le.classes_)
        df[col] = df[col].apply(lambda x: x if x in known_classes else 'missing')
        # If 'missing' not in classes, use most frequent class
        if 'missing' not in known_classes:
            df[col] = df[col].apply(lambda x: le.classes_[0] if x not in known_classes else x)
        df[col] = le.transform(df[col])

# Keep only training feature columns
missing_cols = [c for c in feature_columns if c not in df.columns]
if missing_cols:
    print(f"   ⚠️  {len(missing_cols)} columns missing from test data — filling with median")
    for col in missing_cols:
        df[col] = feature_medians.get(col, 0)

df = df[feature_columns]

# Fill nulls with training medians
for col in df.columns:
    if df[col].isnull().any():
        df[col].fillna(feature_medians.get(col, 0), inplace=True)

print(f"   ✅ Features aligned: {df.shape[1]} columns")

# ─────────────────────────────────────────────
# 5. PREDICT
# ─────────────────────────────────────────────
print("\n🔍 Running predictions...")

fraud_probs = model.predict_proba(df)[:, 1]
fraud_preds = (fraud_probs >= 0.5).astype(int)

# ─────────────────────────────────────────────
# 6. RESULTS
# ─────────────────────────────────────────────
results = pd.DataFrame({
    'TransactionID': transaction_ids,
    'fraud_score':   np.round(fraud_probs, 4),
    'is_fraud':      fraud_preds,
    'risk_level':    pd.cut(
        fraud_probs,
        bins=[0, 0.3, 0.6, 0.8, 1.0],
        labels=['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
    )
})

print("\n" + "=" * 50)
print("  PREDICTION SUMMARY")
print("=" * 50)
print(f"  Total transactions:   {len(results):,}")
print(f"  Flagged as fraud:     {fraud_preds.sum():,}  ({fraud_preds.mean()*100:.2f}%)")
print(f"\n  Risk Level Breakdown:")
print(results['risk_level'].value_counts().to_string())

print("\n  Sample HIGH/CRITICAL risk transactions:")
high_risk = results[results['risk_level'].isin(['HIGH', 'CRITICAL'])].head(10)
print(high_risk.to_string(index=False))

# ─────────────────────────────────────────────
# 7. SAVE RESULTS
# ─────────────────────────────────────────────
os.makedirs("../data/processed", exist_ok=True)
output_path = "../data/processed/fraud_predictions.csv"
results.to_csv(output_path, index=False)
print(f"\n💾 Full predictions saved to: {output_path}")
print("=" * 50)