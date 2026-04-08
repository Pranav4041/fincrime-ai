"""
services/fraud_detection.py — Core inference service.

Flow:
  1. Accept 4 user fields (TransactionRequest)
  2. Build a full feature row (100 columns) by:
       - Deriving features from the 4 inputs
       - Filling the remaining ~96 columns with training medians
  3. Run XGBoost model  → fraud_score (0-1)
  4. Run rules engine   → rules_score (0-100) + triggered rules
  5. Blend scores       → final action (BLOCK/ESCALATE/MONITOR/ALLOW)
  6. Return FraudDetectionResponse
"""
import math
import uuid
import numpy as np
import pandas as pd
import joblib
import os
from pathlib import Path

from schemas.transaction import TransactionRequest, FraudDetectionResponse
from app.models.rules import detect_fraud
# ── Model artifact paths ──────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).resolve().parent.parent   # backend/app/
MODEL_DIR       = BASE_DIR / "models"
USER_IP_HISTORY = {}
_model           = None
_feature_columns = None
_label_encoders  = None
_feature_medians = None


def _load_artifacts():
    """Lazy-load model artifacts once on first request."""
    global _model, _feature_columns, _label_encoders, _feature_medians
    if _model is None:
        _model           = joblib.load(MODEL_DIR / "fraud_model.pkl")
        _feature_columns = joblib.load(MODEL_DIR / "feature_columns.pkl")
        _label_encoders  = joblib.load(MODEL_DIR / "label_encoders.pkl")
        _feature_medians = joblib.load(MODEL_DIR / "feature_medians.pkl")


# ── Risk level bands (mirror test_model.py) ───────────────────────────────────
def _risk_level(score: float) -> str:
    if score >= 0.80:
        return "CRITICAL"
    elif score >= 0.60:
        return "HIGH"
    elif score >= 0.30:
        return "MEDIUM"
    return "LOW"


# ── Feature builder ───────────────────────────────────────────────────────────

def _build_feature_row(req: TransactionRequest) -> dict:
    """
    Convert 4 user inputs into the full feature dict expected by the model.
    Every field not derivable from user input is set to its training median.

    Derived mappings
    ────────────────
    TransactionAmt  →  TransactionAmt, amt_log, amt_round, amt_cents_zero
    time (HH:MM)    →  TransactionDT (synthetic), hour, day_of_week, is_night
    state           →  addr1 (region code), high_risk_state signal via C1
    is_new_device   →  card_null_count, D1 (days since first seen), D4
    """
    _load_artifacts()

    hour   = req.parsed_hour()
    minute = req.parsed_minute()
    amt    = req.amount

    # Synthetic TransactionDT — seconds from midnight for the given time
    # (the model cares about hour/day features, not the raw DT value)
    txn_dt = hour * 3600 + minute * 60

    # Engineered amount features
    amt_round      = int(amt % 1 == 0)
    amt_cents_zero = int((amt * 100) % 100 == 0)
    amt_log        = float(np.log1p(amt))

    # Device-derived features
    # New device → we have no card history → simulate high null count + fresh D1
    card_null_count = 4 if req.is_new_device else 0
    d1_value        = 1.0 if req.is_new_device else 30.0   # 1 day vs 30 days
    d4_value        = 0.1 if req.is_new_device else 5.0    # rapid reuse signal

    # State → addr1 code; high-risk state → bump C1 (linked addresses signal)
    addr1_code = req.addr1_code()
    c1_value   = 12 if req.is_high_risk_state() else 2

    # Start from medians so every column the model expects has a value
    row = dict(_feature_medians)

    # Override with derived values
    row.update({
        "TransactionAmt":  amt,
        "TransactionDT":   txn_dt,
        "amt_log":         amt_log,
        "amt_round":       amt_round,
        "amt_cents_zero":  amt_cents_zero,
        "hour":            hour,
        "day_of_week":     0,               # unknown — use Monday as default
        "is_night":        int(0 <= hour <= 5),
        "card_null_count": card_null_count,
        "addr1":           addr1_code,
        "D1":              d1_value,
        "D4":              d4_value,
        "C1":              c1_value,
        # Email features — unknown input → use least-risky defaults
        "P_email_risky":   0,
        "R_email_risky":   0,
        "email_match":     1,
        "C_sum":           row.get("C_sum", c1_value),
    })

    return row


def _row_to_dataframe(row: dict) -> pd.DataFrame:
    """Align a feature dict to the exact columns the model was trained on."""
    _load_artifacts()

    df = pd.DataFrame([row])

    # Encode any categorical columns using saved LabelEncoders
    for col, le in _label_encoders.items():
        if col in df.columns:
            df[col] = df[col].fillna("missing").astype(str)
            known   = set(le.classes_)
            df[col] = df[col].apply(lambda x: x if x in known else le.classes_[0])
            df[col] = le.transform(df[col])

    # Add any missing columns the model needs
    for col in _feature_columns:
        if col not in df.columns:
            df[col] = _feature_medians.get(col, 0)

    # Keep only training columns in training order
    df = df[_feature_columns]

    # Final null fill
    for col in df.columns:
        if df[col].isnull().any():
            df[col] = df[col].fillna(_feature_medians.get(col, 0))

    return df


# ── Public entry point ────────────────────────────────────────────────────────

def predict_transaction(req: TransactionRequest) -> FraudDetectionResponse:
    """
    Full inference pipeline for a single user transaction.

    Args:
        req: TransactionRequest with 4 user-provided fields.

    Returns:
        FraudDetectionResponse with score, risk level, rules, and explanation.
    """
    transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
    # ── IP Tracking ─────────────────────────────────────────────
    user_id = f"{req.state}_{req.ip_address}"

    if user_id not in USER_IP_HISTORY:
        USER_IP_HISTORY[user_id] = []

    USER_IP_HISTORY[user_id].append(req.ip_address)

# Check last 3 IPs
    recent_ips = USER_IP_HISTORY[user_id][-3:]

    ip_changed_fast = len(set(recent_ips)) > 1
    # ── 1. Build feature row ─────────────────────────────────────────────────
    feature_row = _build_feature_row(req)
    df          = _row_to_dataframe(feature_row)

    # ── 2. ML model prediction ───────────────────────────────────────────────
    fraud_prob = float(_model.predict_proba(df)[0, 1])
    if math.isnan(fraud_prob) or math.isinf(fraud_prob):
        fraud_prob = 0.0
    ml_score_100 = fraud_prob * 100
    risk_lvl   = _risk_level(fraud_prob)

    
    # ── 3. Rules engine ──────────────────────────────────────────────────────
    # Build the txn dict the rules engine understands
    txn_for_rules = {
    "TransactionAmt":  req.amount,
    "TransactionDT":   feature_row["TransactionDT"],
    "hour":            req.parsed_hour(),
    "is_night":        int(0 <= req.parsed_hour() <= 5),
    "amt_round":       feature_row["amt_round"],
    "amt_cents_zero":  feature_row["amt_cents_zero"],
    "card_null_count": feature_row["card_null_count"],
    "D1":              feature_row["D1"],
    "D4":              feature_row["D4"],
    "C1":              feature_row["C1"],
    "C_sum":           feature_row["C_sum"],

    # ✅ ADD THESE PROPERLY
    "ml_score": ml_score_100,
    "ip_changed_fast": ip_changed_fast,
    "is_new_device": req.is_new_device,
    # defaults
    "P_emaildomain":   "unknown",
    "R_emaildomain":   "unknown",
    "M1": "T", "M2": "T", "M3": "T", "M4": "M2",
    "ProductCD": "W",
}

    rules_out = detect_fraud(txn_for_rules)


    # ── 4. Blend ─────────────────────────────────────────────────────────────
    

    # Get rules score safely
    rules_score = rules_out.get("score", 0)

# Weights (you can tweak later if needed)
    ml_weight = 0.65
    rules_weight = 0.35

# Final blended score
    blended_score = (ml_weight * ml_score_100) + (rules_weight * rules_score)

# Decision logic
    if blended_score >= 80:
        action = "BLOCK"
    elif blended_score >= 60:
        action = "ESCALATE"
    elif blended_score >= 30:
        action = "MONITOR"
    else:
        action = "ALLOW"

# Final blended output
    blended = {
        "blended_score": round(blended_score, 2),
        "final_action": action
    }

    # ── 5. Assemble response ─────────────────────────────────────────────────
    explanation = (
        f"ML score: {ml_score_100:.1f}/100 ({fraud_prob:.2%}). "
        f"Rules engine scored {rules_out.get('score', 0):.1f}/100. "
        f"Blended score: {blended['blended_score']:.1f}/100. "
        f"Recommended action: {blended['final_action']}. "
        + rules_out.get("explanation", "")
    )
    if math.isnan(fraud_prob) or math.isinf(fraud_prob):
            fraud_prob = 0.0

    if math.isnan(blended_score) or math.isinf(blended_score):
        blended_score = 0.0
    return {
    "transaction_id": transaction_id,
    "ml_probability": round(fraud_prob, 4),
    "risk_level": risk_lvl,
    "blended_score": blended["blended_score"],
    "action": blended["final_action"],
    "triggered_rules": rules_out.get("triggered_rules", []),
    "aml_flags": rules_out.get("aml_flags", []),
    "explanation": explanation,
    "input_summary": {
        "amount": req.amount,
        "time": req.time,
        "state": req.state,
        "is_new_device": req.is_new_device,
    }
}