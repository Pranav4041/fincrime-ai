"""
analyzer.py — Main Transaction Analyzer
Place in: backend/app/services/analyzer.py
"""
import math
import joblib
import numpy as np
from pathlib import Path
import uuid
import json
from .signals import extract_signals
from .llm import generate_llm_explanation
from .context_engine import ContextEngine
from .compliance import ComplianceEngine
from .fraud_detection import _build_feature_row, _row_to_dataframe

# ── Load model artifacts ──────────────────────────────────────────────────────
BASE          = Path(__file__).resolve().parent.parent
MODEL_PATH    = BASE / "models" / "fraud_model.pkl"
FEATURES_PATH = BASE / "models" / "feature_columns.pkl"
MEDIANS_PATH  = BASE / "models" / "feature_medians.pkl"

model           = joblib.load(MODEL_PATH)
feature_columns = joblib.load(FEATURES_PATH)
medians         = joblib.load(MEDIANS_PATH)

# ── Engine instances ──────────────────────────────────────────────────────────
context_engine    = ContextEngine()
compliance_engine = ComplianceEngine()

def clean_response(obj):
    if isinstance(obj, dict):
        return {k: clean_response(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_response(v) for v in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    return obj
def get_risk_level(score: float) -> str:
    if score >= 75:   return "CRITICAL"
    elif score >= 60: return "HIGH"
    elif score >= 40: return "MEDIUM"
    return "LOW"


# ── Main analyzer ─────────────────────────────────────────────────────────────
def analyze_transaction(transaction, history: list = []) -> dict:

    # 🔥 FIX: convert to dict for engines
    if isinstance(transaction, dict):
        txn_dict = transaction
    else:
        txn_dict = transaction.dict()
    history_dict = [
    {
        "user_id": tx.user_id,
        "amount": tx.amount,
        "time": tx.time,
        "state": tx.state,
        "ip_address": tx.ip_address,
        "is_new_device": tx.is_new_device,
    }
    for tx in history
]
    # ── Step 1: ML Score ──────────────────────────────────────────────────────
    feature_row = _build_feature_row(transaction)
    df = _row_to_dataframe(feature_row)
    features = df.values

    ml_prob  = float(model.predict_proba(features)[0][1])
    ml_score = round(ml_prob * 100, 2)

    # ── Step 2: Context Engine ───────────────────────────────────────────────
    context = context_engine.gather(txn_dict, history_dict)

    # ── Step 3: Compliance Engine ────────────────────────────────────────────
    compliance = compliance_engine.assess(txn_dict, context)

    # ── Step 4: Signal extraction ────────────────────────────────────────────
    signals = extract_signals(txn_dict, features)
    # ── Step 4.5: Behavior Scoring (NEW) ────────────────────────────────
    behavior_score = 0
    behavior_reasons = []

    if history:
        avg_amount = sum(tx.amount for tx in history) / len(history)

        if transaction.amount > 2 * avg_amount:
            behavior_score += 20
            behavior_reasons.append("Amount significantly higher than user's usual pattern")

        states = [tx.state for tx in history]
        if transaction.state not in states:
            behavior_score += 10
            behavior_reasons.append("Transaction from a new location")

        ips = [tx.ip_address for tx in history if tx.ip_address]
        if transaction.ip_address not in ips:
            behavior_score += 10
            behavior_reasons.append("New IP address detected")  

    # ── Step 5: Blended score ────────────────────────────────────────────────
    context_score    = context["context_risk_score"] * 100
    compliance_score = compliance["compliance_score"]

    blended_score = round(
    (ml_score * 0.40) +
    (context_score * 0.20) +
    (compliance_score * 0.20) +
    (behavior_score * 0.20),
    2
)
    blended_score = min(blended_score, 100)
    risk_level    = get_risk_level(blended_score)

    # ── Step 6: LLM explanation ──────────────────────────────────────────────
    enriched_signals = signals + behavior_reasons + [
    e.replace("🔍 HISTORY: ", "")
     .replace("📱 DEVICE: ", "")
     .replace("📍 GEO: ", "")
     .replace("👥 PEER: ", "")
    for e in context["evidence_summary"]
    if "normal" not in e.lower()
]

    llm_output = generate_llm_explanation(blended_score, enriched_signals)

    # ── Step 7: Final response ───────────────────────────────────────────────
    transaction_id = str(uuid.uuid4())
    print(f"[DEBUG] User: {txn_dict.get('user_id')}")
    print(f"[DEBUG] ML Score: {ml_score}")
    print(f"[DEBUG] Final Score: {blended_score}")
    response = {
        "transaction_id": transaction_id,

        "transaction": txn_dict,

        "ml_score": ml_score,
        "blended_score": blended_score,
        "risk_level": risk_level,
        "action": _action(blended_score),

        "behavior": {
            "behavior_score": behavior_score if 'behavior_score' in locals() else 0,
            "reasons": behavior_reasons if 'behavior_reasons' in locals() else []
        },

        "context": context if context else {},
        "compliance": compliance if compliance else {},

        "signals": enriched_signals if enriched_signals else [],
        "explanation": llm_output.get("explanation", ""),

        "user_actions": llm_output.get("user_actions", []),
        "bank_actions": llm_output.get("bank_actions", [])
    }
    return clean_nan(response)
def clean_nan(obj):
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan(v) for v in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    return obj   

def _action(score: float) -> str:
    if score >= 80:   return "BLOCK"
    elif score >= 60: return "ESCALATE"
    elif score >= 40: return "MONITOR"
    return "ALLOW"
