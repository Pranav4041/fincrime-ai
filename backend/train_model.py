"""
train_model.py — Fraud Detection Engine
Place in: backend/train_model.py
Run from backend/: python train_model.py

Strategy:
- Drop V columns with >50% nulls (most of them)
- Keep meaningful columns: TransactionAmt, ProductCD, card*, addr*, C*, D*, M*
- Keep only the best V columns based on correlation with isFraud
- Train lightweight XGBoost (100 trees, not 500)
- Output: fraud_score (0-1) per transaction
- Save model to app/models/
"""

import pandas as pd
import numpy as np
import joblib
import os
import warnings
warnings.filterwarnings('ignore')

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, roc_auc_score
import xgboost as xgb

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
DATA_PATH  = "../data/train_transaction.csv"
MODEL_DIR  = "app/models"
os.makedirs(MODEL_DIR, exist_ok=True)

# These are the human-meaningful columns in your dataset
CORE_COLS = [
    'TransactionAmt',   # transaction amount
    'TransactionDT',    # transaction time delta
    'ProductCD',        # product code (W, H, C, S, R)
    'card1', 'card2', 'card3', 'card4', 'card5', 'card6',  # card info
    'addr1', 'addr2',   # billing address
    'dist1',            # distance (billing to mailing)
    'P_emaildomain',    # purchaser email domain
    'R_emaildomain',    # recipient email domain
    # C columns = counting features (how many addresses, cards, etc linked)
    'C1','C2','C3','C4','C5','C6','C7','C8','C9','C10','C11','C12','C13','C14',
    # D columns = timedelta features
    'D1','D2','D3','D4','D5','D10','D11','D15',
    # M columns = match flags (name, address, etc.)
    'M1','M2','M3','M4','M5','M6','M7','M8','M9',
]

# Top V columns — selected based on known Kaggle analysis of this dataset
# These are the V columns with lowest null rate AND highest fraud signal
TOP_V_COLS = [
    'V1','V2','V3','V4','V5','V6','V7','V8','V9','V10',
    'V11','V12','V13','V14','V15','V16','V17','V18','V19','V20',
    'V53','V54','V55','V56','V57','V58','V59','V60','V61','V62',
    'V70','V71','V72','V73','V74','V75','V76','V77','V78','V79',
    'V95','V96','V97','V98','V99','V100',
    'V126','V127','V128','V129','V130',
    'V307','V308','V309','V310','V311','V312',
    'V317',
]

USE_COLS = ['isFraud'] + CORE_COLS + TOP_V_COLS


# ─────────────────────────────────────────────
# 1. LOAD — only the columns we need
# ─────────────────────────────────────────────
def load_data():
    print("\n📂 Loading data (selected columns only)...")

    # Only load columns that exist in file
    all_cols = pd.read_csv(DATA_PATH, nrows=0).columns.tolist()
    cols_to_load = [c for c in USE_COLS if c in all_cols]

    df = pd.read_csv(DATA_PATH, usecols=cols_to_load)
    print(f"   Loaded {df.shape[0]:,} rows × {df.shape[1]} columns")
    print(f"   Fraud rate: {df['isFraud'].mean()*100:.2f}%")
    return df


# ─────────────────────────────────────────────
# 2. FEATURE ENGINEERING (from real columns)
# ─────────────────────────────────────────────
def engineer_features(df):
    print("\n⚙️  Engineering features...")

    # Time features — TransactionDT is seconds from a reference point
    df['hour']        = (df['TransactionDT'] // 3600) % 24
    df['day_of_week'] = (df['TransactionDT'] // (3600 * 24)) % 7
    df['is_night']    = df['hour'].between(0, 5).astype(int)  # 12AM-5AM

    # Amount features
    df['amt_log']        = np.log1p(df['TransactionAmt'])
    df['amt_round']      = (df['TransactionAmt'] % 1 == 0).astype(int)  # is whole number
    df['amt_cents_zero'] = ((df['TransactionAmt'] * 100) % 100 == 0).astype(int)

    # Card features
    df['card_null_count'] = df[['card1','card2','card3','card4','card5','card6']].isnull().sum(axis=1)

    # Email domain risk (based on known patterns in this dataset)
    risky_domains = {'gmail.com', 'yahoo.com', 'hotmail.com', 'anonymous.com', 'protonmail.com'}
    df['P_email_risky'] = df['P_emaildomain'].isin(risky_domains).astype(int)
    df['R_email_risky'] = df['R_emaildomain'].isin(risky_domains).astype(int)
    df['email_match']   = (df['P_emaildomain'] == df['R_emaildomain']).astype(int)

    # C columns sum (total count features — higher = more linked accounts)
    c_cols = [c for c in df.columns if c.startswith('C') and c[1:].isdigit()]
    df['C_sum'] = df[c_cols].sum(axis=1)

    print(f"   Added engineered features. Shape: {df.shape}")
    return df


# ─────────────────────────────────────────────
# 3. PREPROCESS
# ─────────────────────────────────────────────
def preprocess(df):
    print("\n🔧 Preprocessing...")

    # Drop original DT (we extracted what we need)
    df.drop(columns=['TransactionDT'], inplace=True, errors='ignore')

    # Encode categoricals
    cat_cols = df.select_dtypes(include='object').columns.tolist()
    label_encoders = {}
    for col in cat_cols:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col].fillna('missing').astype(str))
        label_encoders[col] = le

    # Fill numeric nulls with median per column
    num_cols = df.select_dtypes(include='number').columns.tolist()
    medians = {}
    for col in num_cols:
        if col == 'isFraud':
            continue
        med = df[col].median()
        medians[col] = med
        df[col].fillna(med, inplace=True)

    # Save encoders + medians for backend inference
    joblib.dump(label_encoders, f"{MODEL_DIR}/label_encoders.pkl")
    joblib.dump(medians,        f"{MODEL_DIR}/feature_medians.pkl")

    print(f"   Encoded {len(cat_cols)} categorical cols")
    print(f"   Filled nulls with column medians")
    return df


# ─────────────────────────────────────────────
# 4. TRAIN
# ─────────────────────────────────────────────
def train(df):
    print("\n🚀 Training...")

    X = df.drop('isFraud', axis=1)
    y = df['isFraud']

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Save feature list for backend
    joblib.dump(X.columns.tolist(), f"{MODEL_DIR}/feature_columns.pkl")

    scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
    print(f"   Class imbalance ratio: {scale_pos_weight:.1f}x")

    model = xgb.XGBClassifier(
        n_estimators=100,       # lean — enough for good AUC, fast to train
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        eval_metric='auc',
        random_state=42,
        n_jobs=-1
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=25
    )

    return model, X_test, y_test


# ─────────────────────────────────────────────
# 5. EVALUATE
# ─────────────────────────────────────────────
def evaluate(model, X_test, y_test):
    print("\n📊 Evaluation:")

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    auc    = roc_auc_score(y_test, y_prob)

    print(f"\n   ROC-AUC: {auc:.4f}  ← aim for > 0.88")
    print("\n" + classification_report(y_test, y_pred, target_names=['Not Fraud', 'Fraud']))

    # Top 10 most important features (interpretable ones)
    feat_imp = pd.Series(
        model.feature_importances_,
        index=model.feature_names_in_
    ).sort_values(ascending=False).head(10)

    print("\n   Top 10 most important features:")
    for feat, score in feat_imp.items():
        print(f"   {feat:25s}  {score:.4f}")


# ─────────────────────────────────────────────
# 6. SAVE
# ─────────────────────────────────────────────
def save(model):
    path = f"{MODEL_DIR}/fraud_model.pkl"
    joblib.dump(model, path)
    print(f"\n💾 Saved:")
    print(f"   ✅ {MODEL_DIR}/fraud_model.pkl")
    print(f"   ✅ {MODEL_DIR}/feature_columns.pkl")
    print(f"   ✅ {MODEL_DIR}/label_encoders.pkl")
    print(f"   ✅ {MODEL_DIR}/feature_medians.pkl")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  FRAUD DETECTION MODEL TRAINING")
    print("=" * 50)

    df              = load_data()
    df              = engineer_features(df)
    df              = preprocess(df)
    model, X_t, y_t = train(df)
    evaluate(model, X_t, y_t)
    save(model)

    print("\n" + "=" * 50)
    print("  ✅ DONE — next: wire up app/services/fraud_detection.py")
    print("=" * 50)