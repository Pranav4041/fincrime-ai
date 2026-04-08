"""
compliance.py — Regulatory Risk Assessment Engine
Place in: backend/app/services/compliance.py

Assesses transactions against 3 frameworks:
  1. RBI  — Reserve Bank of India AML/KYC guidelines
  2. FATF — Financial Action Task Force recommendations
  3. PMLA — Prevention of Money Laundering Act 2002
"""


# ── Regulatory framework definitions ─────────────────────────────────────────
FRAMEWORKS = {
    "RBI": {
        "name":      "Reserve Bank of India",
        "full_name": "RBI AML/KYC Master Directions 2016",
        "url":       "https://www.rbi.org.in/scripts/BS_ViewMasCirculardetails.aspx?id=12228"
    },
    "FATF": {
        "name":      "Financial Action Task Force",
        "full_name": "FATF 40 Recommendations on AML/CFT",
        "url":       "https://www.fatf-gafi.org/en/topics/fatf-recommendations.html"
    },
    "PMLA": {
        "name":      "Prevention of Money Laundering Act",
        "full_name": "PMLA 2002 — as amended 2023",
        "url":       "https://enforcementdirectorate.gov.in/pmla"
    }
}


class ComplianceEngine:
    """
    Runs a transaction through RBI, FATF, and PMLA rule sets.
    Returns compliance flags, risk level, and regulatory citations.
    """

    def assess(self, txn: dict, context: dict) -> dict:
        """
        Args:
            txn:     transaction dict
            context: output from ContextEngine.gather()

        Returns:
            {
                rbi_assessment:   {...},
                fatf_assessment:  {...},
                pmla_assessment:  {...},
                overall_compliance_risk: LOW/MEDIUM/HIGH/CRITICAL,
                total_flags:      int,
                regulatory_report: [list of strings],
                compliance_score:  0-100 (higher = more risky)
            }
        """
        rbi  = self._assess_rbi(txn, context)
        fatf = self._assess_fatf(txn, context)
        pmla = self._assess_pmla(txn, context)

        total_flags    = len(rbi["flags"]) + len(fatf["flags"]) + len(pmla["flags"])
        compliance_score = min(
            rbi["risk_score"] + fatf["risk_score"] + pmla["risk_score"],
            100
        )

        overall = self._overall_risk(compliance_score)
        report  = self._build_report(rbi, fatf, pmla, overall)

        return {
            "rbi_assessment":        rbi,
            "fatf_assessment":       fatf,
            "pmla_assessment":       pmla,
            "overall_compliance_risk": overall,
            "total_flags":           total_flags,
            "compliance_score":      round(compliance_score, 1),
            "regulatory_report":     report,
            "frameworks_checked":    list(FRAMEWORKS.keys()),
        }

    # ── RBI ASSESSMENT ────────────────────────────────────────────────────────
    def _assess_rbi(self, txn: dict, context: dict) -> dict:
        flags      = []
        risk_score = 0

        amount  = txn.get("TransactionAmt", 0)
        history = context.get("transaction_history", {})
        device  = context.get("device_fingerprint", {})
        geo     = context.get("geo_data", {})

        # RBI Rule 1: High-value transaction monitoring
        # Master Direction: Transactions > ₹50,000 require enhanced monitoring
        if amount > 50000:
            flags.append({
                "flag":      "RBI_HIGH_VALUE",
                "severity":  "HIGH",
                "detail":    f"Transaction ₹{amount:,.0f} exceeds ₹50,000 enhanced monitoring threshold",
                "citation":  "RBI KYC Master Direction 2016 — Rule 38: Enhanced Due Diligence",
                "action":    "Mandatory enhanced due diligence required"
            })
            risk_score += 30

        # RBI Rule 2: KYC verification — missing identity signals
        if device.get("missing_card_fields", 0) >= 3:
            flags.append({
                "flag":      "RBI_KYC_INCOMPLETE",
                "severity":  "MEDIUM",
                "detail":    "Multiple identity fields missing — KYC completeness check failed",
                "citation":  "RBI KYC Master Direction 2016 — Rule 6: Customer Identification",
                "action":    "Re-verify customer identity before processing"
            })
            risk_score += 20

        # RBI Rule 3: Velocity monitoring — system-based detection mandate
        if history.get("velocity_1h", 0) >= 3:
            flags.append({
                "flag":      "RBI_VELOCITY_BREACH",
                "severity":  "HIGH",
                "detail":    f"{history['velocity_1h']} transactions in 1 hour — exceeds RBI velocity norm",
                "citation":  "RBI Cyber Security Framework 2016 — Annex 1: Fraud Monitoring",
                "action":    "Temporarily hold account pending investigation"
            })
            risk_score += 25

        # RBI Rule 4: New device with high amount
        if device.get("is_new_device") and amount > 10000:
            flags.append({
                "flag":      "RBI_NEW_DEVICE_HIGH_VALUE",
                "severity":  "MEDIUM",
                "detail":    f"New device used for high-value transaction ₹{amount:,.0f}",
                "citation":  "RBI Guidelines on Digital Payment Security 2021 — Section 4",
                "action":    "Trigger additional authentication (OTP/biometric)"
            })
            risk_score += 15

        # RBI Rule 5: Overseas transaction monitoring
        if geo.get("is_overseas"):
            flags.append({
                "flag":      "RBI_OVERSEAS_TXN",
                "severity":  "MEDIUM",
                "detail":    "Overseas transaction detected — FEMA reporting may apply",
                "citation":  "RBI FEMA Guidelines — Foreign Transaction Reporting",
                "action":    "Check FEMA compliance; report if above threshold"
            })
            risk_score += 15

        return {
            "framework":   FRAMEWORKS["RBI"],
            "flags":       flags,
            "risk_score":  min(risk_score, 40),
            "compliant":   len(flags) == 0,
            "flag_count":  len(flags)
        }

    # ── FATF ASSESSMENT ───────────────────────────────────────────────────────
    def _assess_fatf(self, txn: dict, context: dict) -> dict:
        flags      = []
        risk_score = 0

        amount  = txn.get("TransactionAmt", 0)
        history = context.get("transaction_history", {})
        peer    = context.get("peer_comparison", {})
        device  = context.get("device_fingerprint", {})

        # FATF Rec 1: Structuring / Smurfing detection
        # Multiple transactions just below reporting threshold
        if history.get("velocity_24h", 0) >= 5 and amount < 50000:
            flags.append({
                "flag":      "FATF_STRUCTURING",
                "severity":  "HIGH",
                "detail":    f"{history['velocity_24h']} transactions in 24h, all below ₹50K — possible structuring",
                "citation":  "FATF Recommendation 3 — Money Laundering Offences: Structuring",
                "action":    "File Suspicious Transaction Report (STR) with FIU-IND"
            })
            risk_score += 30

        # FATF Rec 2: Unusual transaction patterns (Rec 20 — STR)
        if peer.get("peer_band") == "TOP_5_PERCENT":
            flags.append({
                "flag":      "FATF_UNUSUAL_AMOUNT",
                "severity":  "MEDIUM",
                "detail":    f"Amount in top 5% for this transaction type — unusual pattern",
                "citation":  "FATF Recommendation 20 — Reporting of Suspicious Transactions",
                "action":    "Consider filing STR with Financial Intelligence Unit India"
            })
            risk_score += 20

        # FATF Rec 3: Anonymous/prepaid instrument risk
        if device.get("is_prepaid_card"):
            flags.append({
                "flag":      "FATF_ANONYMOUS_INSTRUMENT",
                "severity":  "MEDIUM",
                "detail":    "Prepaid/anonymous payment instrument detected",
                "citation":  "FATF Recommendation 15 — New Technologies & Prepaid Cards",
                "action":    "Apply enhanced due diligence for prepaid instrument transactions"
            })
            risk_score += 15

        # FATF Rec 4: Prior fraud history = PEP/high risk customer signal
        if history.get("prior_fraud_flags", 0) >= 2:
            flags.append({
                "flag":      "FATF_HIGH_RISK_CUSTOMER",
                "severity":  "CRITICAL",
                "detail":    f"{history['prior_fraud_flags']} prior fraud flags — customer classified as high-risk",
                "citation":  "FATF Recommendation 12 — Politically Exposed Persons & High-Risk Customers",
                "action":    "Apply Enhanced Due Diligence (EDD); consider account restriction"
            })
            risk_score += 35

        return {
            "framework":   FRAMEWORKS["FATF"],
            "flags":       flags,
            "risk_score":  min(risk_score, 40),
            "compliant":   len(flags) == 0,
            "flag_count":  len(flags)
        }

    # ── PMLA ASSESSMENT ───────────────────────────────────────────────────────
    def _assess_pmla(self, txn: dict, context: dict) -> dict:
        flags      = []
        risk_score = 0

        amount  = txn.get("TransactionAmt", 0)
        history = context.get("transaction_history", {})
        geo     = context.get("geo_data", {})

        # PMLA Section 12: Cash Transaction Report (CTR)
        # Transactions above ₹10 lakh must be reported
        if amount >= 1000000:
            flags.append({
                "flag":      "PMLA_CTR_REQUIRED",
                "severity":  "CRITICAL",
                "detail":    f"Transaction ₹{amount:,.0f} exceeds ₹10,00,000 — CTR filing mandatory",
                "citation":  "PMLA 2002 Section 12 — Obligation to Maintain Records & File CTR",
                "action":    "File Cash Transaction Report with FIU-IND within 15 days"
            })
            risk_score += 40

        # PMLA Section 12A: Suspicious Transaction Report (STR)
        elif amount >= 500000:
            flags.append({
                "flag":      "PMLA_STR_THRESHOLD",
                "severity":  "HIGH",
                "detail":    f"Transaction ₹{amount:,.0f} near STR threshold — enhanced scrutiny required",
                "citation":  "PMLA 2002 Section 12A — Suspicious Transaction Reporting",
                "action":    "Enhanced monitoring; file STR if suspicious indicators confirmed"
            })
            risk_score += 25

        # PMLA Section 3: Money laundering — layering signal
        # Rapid movement of funds across accounts
        if history.get("velocity_24h", 0) >= 10:
            flags.append({
                "flag":      "PMLA_LAYERING_SIGNAL",
                "severity":  "CRITICAL",
                "detail":    f"{history['velocity_24h']} transactions in 24h — possible fund layering",
                "citation":  "PMLA 2002 Section 3 — Offence of Money Laundering: Layering",
                "action":    "Freeze account; report to Enforcement Directorate"
            })
            risk_score += 35

        # PMLA — Geographic risk (cross-border = higher PMLA scrutiny)
        if geo.get("impossible_travel"):
            flags.append({
                "flag":      "PMLA_GEO_ANOMALY",
                "severity":  "HIGH",
                "detail":    "Impossible travel detected — potential identity fraud or account takeover",
                "citation":  "PMLA 2002 — KYC/AML Guidelines: Geographic Risk Assessment",
                "action":    "Verify customer location; consider temporary account hold"
            })
            risk_score += 25

        return {
            "framework":   FRAMEWORKS["PMLA"],
            "flags":       flags,
            "risk_score":  min(risk_score, 40),
            "compliant":   len(flags) == 0,
            "flag_count":  len(flags)
        }

    # ── HELPERS ───────────────────────────────────────────────────────────────
    def _overall_risk(self, score: float) -> str:
        if score >= 70:   return "CRITICAL"
        elif score >= 45: return "HIGH"
        elif score >= 20: return "MEDIUM"
        return "LOW"

    def _build_report(self, rbi, fatf, pmla, overall) -> list:
        report = [
            f"COMPLIANCE ASSESSMENT — Overall Risk: {overall}",
            f"Frameworks checked: RBI, FATF, PMLA",
            f"RBI flags: {rbi['flag_count']} | FATF flags: {fatf['flag_count']} | PMLA flags: {pmla['flag_count']}",
        ]

        all_flags = rbi["flags"] + fatf["flags"] + pmla["flags"]
        for f in all_flags:
            report.append(
                f"[{f['severity']}] {f['flag']}: {f['detail']} "
                f"→ Action: {f['action']} "
                f"(Ref: {f['citation']})"
            )

        if not all_flags:
            report.append("No compliance violations detected.")

        return report