"""
context_engine.py — Autonomous Contextual Evidence Gatherer
Place in: backend/app/services/context_engine.py

Gathers 4 types of evidence autonomously:
  1. Transaction History    — spending patterns, velocity, frequency
  2. Device Fingerprint     — device risk based on card/device signals
  3. Geo Data               — location risk, impossible travel
  4. Peer Comparison        — how this txn compares to similar users
"""

import numpy as np
from typing import Optional


# ── Known high-risk states (higher fraud incidence in IEEE-CIS data) ──────────
HIGH_RISK_STATES = {
    "unknown", "foreign", "overseas", "proxy",
    # Indian states with higher digital fraud rates
    "jharkhand", "bihar", "uttar pradesh", "assam"
}

# ── High-risk email domains (from training data patterns) ────────────────────
HIGH_RISK_EMAILS = {
    "anonymous.com", "protonmail.com", "guerrillamail.com",
    "mailinator.com", "tempmail.com", "throwam.com"
}

# ── Peer buckets — avg spend by product type (from IEEE-CIS medians) ─────────
PEER_BENCHMARKS = {
    "W": {"avg": 68.5,  "p75": 120.0,  "p95": 350.0},   # general purchase
    "H": {"avg": 112.0, "p75": 200.0,  "p95": 600.0},   # hotel/travel
    "C": {"avg": 45.0,  "p75": 85.0,   "p95": 250.0},   # cashback
    "S": {"avg": 25.0,  "p75": 50.0,   "p95": 150.0},   # subscription
    "R": {"avg": 90.0,  "p75": 175.0,  "p95": 500.0},   # retail
}

def sanitize(data):
    if isinstance(data, dict):
        return {k: sanitize(v) for k, v in data.items()}

    elif isinstance(data, list):
        return [sanitize(v) for v in data]

    elif isinstance(data, (float, int, np.floating)):
        if np.isnan(data) or np.isinf(data):
            return 0.0
        return float(data)

    return data
class ContextEngine:
    """
    Autonomously gathers contextual evidence for a transaction.
    Returns a structured context dict used by the compliance engine
    and the LLM explainer.
    """

    def gather(self, txn: dict, history: list = []) -> dict:
        """
        Args:
            txn:     current transaction dict
            history: past transactions for this account (list of dicts)

        Returns:
            context: {
                transaction_history: {...},
                device_fingerprint:  {...},
                geo_data:            {...},
                peer_comparison:     {...},
                evidence_summary:    [list of strings for LLM/report],
                context_risk_score:  0.0 - 1.0
            }
        """
        tx_history   = self._analyze_history(txn, history)
        device_fp    = self._device_fingerprint(txn, history)
        geo          = self._geo_data(txn, history)
        peer         = self._peer_comparison(txn)

        # Aggregate context risk score
        context_risk = min(
            tx_history["risk_contribution"]  +
            device_fp["risk_contribution"]   +
            geo["risk_contribution"]         +
            peer["risk_contribution"],
            1.0
        )

        evidence = self._build_evidence_summary(tx_history, device_fp, geo, peer)

        return sanitize({
            "transaction_history": tx_history,
            "device_fingerprint":  device_fp,
            "geo_data":            geo,
            "peer_comparison":     peer,
            "evidence_summary":    evidence,
            "context_risk_score":  round(context_risk, 3),
        })

    # ── 1. TRANSACTION HISTORY ────────────────────────────────────────────────
    def _analyze_history(self, txn: dict, history: list) -> dict:
        amount = txn.get("TransactionAmt", 0)

        if not history:
            return {
                "total_transactions":    0,
                "avg_amount":            0,
                "max_amount":            0,
                "velocity_1h":           0,
                "velocity_24h":          0,
                "prior_fraud_flags":     0,
                "is_first_transaction":  True,
                "amount_vs_avg":         None,
                "risk_contribution":     0.15,  # slight risk — no history
                "note": "No transaction history available — new account signal"
            }

        amounts = [
            float(h.get("TransactionAmt", 0) or 0)
            for h in history
            if h.get("TransactionAmt") is not None
        ]
       
        if not amounts:
            avg_amount = 0.0
            max_amount = 0.0
        else:
            avg_amount = float(np.mean(amounts))
            max_amount = float(np.max(amounts))

            if np.isnan(avg_amount) or np.isinf(avg_amount):
                avg_amount = 0.0
            if np.isnan(max_amount) or np.isinf(max_amount):
                max_amount = 0.0
        
        prior_frauds = int(sum(1 for h in history if h.get("isFraud", 0) == 1
                           or h.get("fraud_score", 0) > 0.6))

        # Velocity — count of txns in last 1h and 24h using TransactionDT
        curr_dt    = txn.get("TransactionDT", 0)
        velocity_1h = int(sum(
            1 for h in history
            if 0 <= (curr_dt - h.get("TransactionDT", 0)) <= 3600
        ))

        velocity_24h = int(sum(
            1 for h in history
            if 0 <= (curr_dt - h.get("TransactionDT", 0)) <= 86400
        ))

        if avg_amount > 0:
            ratio = amount / avg_amount
            if np.isnan(ratio) or np.isinf(ratio):
                amount_vs_avg = None
            else:
                amount_vs_avg = round(ratio, 2)
        else:
            amount_vs_avg = None

        # Risk contribution
        risk = 0.0
        if prior_frauds > 0:          risk += 0.30
        if velocity_1h >= 3:          risk += 0.25
        if amount_vs_avg and amount_vs_avg > 5:  risk += 0.20

        return {
            "total_transactions":   len(history),
            "avg_amount":           round(avg_amount, 2),
            "max_amount":           round(max_amount, 2),
            "velocity_1h":          velocity_1h,
            "velocity_24h":         velocity_24h,
            "prior_fraud_flags":    prior_frauds,
            "is_first_transaction": False,
            "amount_vs_avg":        amount_vs_avg,
            "risk_contribution":    round(min(risk, 0.5), 3),
            "note": self._history_note(velocity_1h, prior_frauds, amount_vs_avg)
        }

    def _history_note(self, vel, frauds, ratio) -> str:
        notes = []
        if frauds > 0:
            notes.append(f"{frauds} prior fraud flag(s) on this account")
        if vel >= 3:
            notes.append(f"{vel} transactions in last hour — velocity spike")
        if ratio and ratio > 5:
            notes.append(f"Current amount is {ratio}x account average")
        return "; ".join(notes) if notes else "Transaction history appears normal"

    # ── 2. DEVICE FINGERPRINT ─────────────────────────────────────────────────
    def _device_fingerprint(self, txn: dict, history: list) -> dict:
        card_null_count = txn.get("card_null_count", 0)
        card1           = txn.get("card1", None)
        card4           = txn.get("card4", "")   # visa/mastercard/discover
        card6           = txn.get("card6", "")   # credit/debit
        d1              = txn.get("D1", None)     # days since first seen
        d4              = txn.get("D4", None)     # days since last seen

        # Device freshness
        is_new_device    = card_null_count > 2 or (d1 is not None and d1 <= 1)
        is_prepaid       = str(card4).lower() in {"prepaid", "unknown", ""}
        is_credit        = str(card6).lower() == "credit"

        # Check if card changed vs history
        card_changed = False
        if history and card1:
            prev_cards = {h.get("card1") for h in history[-5:] if h.get("card1")}
            card_changed = bool(prev_cards) and card1 not in prev_cards

        risk = 0.0
        if is_new_device:   risk += 0.25
        if is_prepaid:      risk += 0.15
        if card_changed:    risk += 0.20
        if card_null_count >= 4: risk += 0.15

        signals = []
        if is_new_device:   signals.append("New/unrecognized device")
        if is_prepaid:      signals.append("Prepaid card — harder to trace")
        if card_changed:    signals.append("Card changed from recent history")
        if card_null_count >= 4: signals.append("Multiple card fields missing")

        return {
            "is_new_device":       is_new_device,
            "is_prepaid_card":     is_prepaid,
            "is_credit_card":      is_credit,
            "card_changed":        card_changed,
            "missing_card_fields": card_null_count,
            "days_since_first":    d1,
            "days_since_last":     d4,
            "device_signals":      signals,
            "risk_contribution":   round(min(risk, 0.4), 3),
            "note": "; ".join(signals) if signals else "Device fingerprint appears normal"
        }

    # ── 3. GEO DATA ───────────────────────────────────────────────────────────
    def _geo_data(self, txn: dict, history: list) -> dict:
        addr1    = txn.get("addr1", None)    # billing region code
        addr2    = txn.get("addr2", None)    # billing country code
        dist1    = txn.get("dist1", None)    # distance billing to mailing
        state    = txn.get("state", "unknown").lower()

        is_high_risk_state  = state in HIGH_RISK_STATES
        is_overseas         = addr2 not in (None, 87.0, 87)  # 87 = US in IEEE-CIS
        large_distance      = dist1 is not None and dist1 > 500

        # Impossible travel — location changed drastically in short time
        impossible_travel = False
        if history and addr1:
            last_addr = history[-1].get("addr1")
            last_dt   = history[-1].get("TransactionDT", 0)
            curr_dt   = txn.get("TransactionDT", 0)
            time_gap  = abs(curr_dt - last_dt)
            if last_addr and last_addr != addr1 and time_gap < 3600:
                impossible_travel = True

        risk = 0.0
        if is_high_risk_state:  risk += 0.20
        if is_overseas:         risk += 0.15
        if large_distance:      risk += 0.15
        if impossible_travel:   risk += 0.35

        signals = []
        if is_high_risk_state:  signals.append(f"High-risk location: {state}")
        if is_overseas:         signals.append("Overseas transaction detected")
        if large_distance:      signals.append(f"Large billing-to-mailing distance: {dist1}km")
        if impossible_travel:   signals.append("Impossible travel — location changed within 1 hour")

        return {
            "state":               state,
            "addr1_code":          addr1,
            "addr2_code":          addr2,
            "billing_distance_km": dist1,
            "is_high_risk_state":  is_high_risk_state,
            "is_overseas":         is_overseas,
            "impossible_travel":   impossible_travel,
            "geo_signals":         signals,
            "risk_contribution":   round(min(risk, 0.5), 3),
            "note": "; ".join(signals) if signals else "Geo data appears normal"
        }

    # ── 4. PEER COMPARISON ────────────────────────────────────────────────────
    def _peer_comparison(self, txn: dict) -> dict:
        amount      = txn.get("TransactionAmt", 0)
        product_cd  = txn.get("ProductCD", "W")
        benchmark   = PEER_BENCHMARKS.get(str(product_cd), PEER_BENCHMARKS["W"])

        avg  = benchmark["avg"]
        p75  = benchmark["p75"]
        p95  = benchmark["p95"]

        vs_avg = round(amount / avg, 2) if avg > 0 else 1.0

        if amount > p95:
            peer_band = "TOP_5_PERCENT"
            risk      = 0.25
            note      = f"Amount ₹{amount:.0f} is in top 5% for {product_cd} transactions (peer p95=₹{p95})"
        elif amount > p75:
            peer_band = "TOP_25_PERCENT"
            risk      = 0.10
            note      = f"Amount ₹{amount:.0f} is above 75th percentile for {product_cd} transactions"
        else:
            peer_band  = "NORMAL"
            risk       = 0.0
            note       = f"Amount ₹{amount:.0f} is within normal range for {product_cd} transactions"

        return {
            "product_type":      product_cd,
            "peer_avg":          avg,
            "peer_p75":          p75,
            "peer_p95":          p95,
            "amount_vs_avg":     vs_avg,
            "peer_band":         peer_band,
            "risk_contribution": round(risk, 3),
            "note":              note
        }

    # ── EVIDENCE SUMMARY (for LLM + case report) ─────────────────────────────
    def _build_evidence_summary(self, history, device, geo, peer) -> list:
        evidence = []

        # History evidence
        if history["is_first_transaction"]:
            evidence.append("🔍 HISTORY: First transaction on this account — no baseline available")
        elif history["note"] != "Transaction history appears normal":
            evidence.append(f"🔍 HISTORY: {history['note']}")

        # Device evidence
        if device["note"] != "Device fingerprint appears normal":
            evidence.append(f"📱 DEVICE: {device['note']}")

        # Geo evidence
        if geo["note"] != "Geo data appears normal":
            evidence.append(f"📍 GEO: {geo['note']}")

        # Peer evidence
        if peer["peer_band"] != "NORMAL":
            evidence.append(f"👥 PEER: {peer['note']}")

        if not evidence:
            evidence.append("✅ All contextual signals appear normal")
        return evidence
    
    
        