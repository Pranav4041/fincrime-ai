import math

from app.services.ml_model import predict_ml
def enrich_transaction(txn):
    features = {}

    avg_spend = 5000

    amount = txn["TransactionAmt"]
    hour = txn["hour"]
    is_new_device = txn["card_null_count"] > 0
    location = txn.get("state", "unknown")

    # Amount logic
    features["amount_ratio"] = amount / avg_spend
    features["is_high_amount"] = amount > avg_spend * 3

    # Time logic
    features["is_night"] = hour < 6 or hour > 22

    # Device
    features["device_risk"] = 0.8 if is_new_device else 0.2

    # Location
    safe_locations = ["Delhi", "Chandigarh"]
    features["location_risk"] = 0.7 if location not in safe_locations else 0.2

    return features



def detect_fraud(txn):
    # 🔹 ML prediction
    ml_score = txn.get("ml_score", 0)

    # 🔹 Rule-based logic
    rule_score = 0
    triggers = []

    amount = txn["TransactionAmt"]
    hour = txn["hour"]
    is_new_device = txn["card_null_count"] > 0
    location = txn.get("state", "unknown")  # fallback

    if amount > 20000:
        rule_score += 0.3
        triggers.append("High transaction amount")

    if hour < 6 or hour > 22:
        rule_score += 0.2
        triggers.append("Unusual transaction time")

    if is_new_device:
        rule_score += 0.3
        triggers.append("New device used")

    if location not in ["Delhi", "Chandigarh"]:
        rule_score += 0.2
        triggers.append("Suspicious location")
    if txn.get("ip_changed_fast"):
        rule_score += 0.25
        triggers.append("Rapid IP Switching")
    # 🔹 Combine ML + Rules
    
    if math.isnan(ml_score) or math.isinf(ml_score):
        ml_score = 0

    if math.isnan(rule_score) or math.isinf(rule_score):
        rule_score = 0
    final_score = 0.7 * ml_score + 0.3 * rule_score

    return {
        "score": round(final_score * 100, 2),  # IMPORTANT: now 0–100 scale
        "fraud_score": round(final_score, 2),
        "ml_score": round(ml_score, 2),
        "rule_score": round(rule_score, 2),
        "action": "BLOCK" if final_score > 0.8 else "ESCALATE" if final_score > 0.6 else "MONITOR" if final_score > 0.3 else "ALLOW",
        "triggered_rules": [{"rule": t} for t in triggers],
        "aml_flags": triggers,
        "explanation": ", ".join(triggers) if triggers else "No major risk signals"
    }