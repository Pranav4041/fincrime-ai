"""
fraudster_ai.py — Adversarial Fraud Simulation Engine
Place in: backend/app/services/fraudster_ai.py

How it works:
  1. Start with a realistic normal user profile
  2. Generate a suspicious transaction based on attack type
  3. Send to analyzer.py → get risk score
  4. Evasion loop: tweak transaction to reduce risk score
  5. Repeat until LOW risk (fraud passed) or max attempts hit
  6. Log every attempt + detect system weaknesses

Attack types:
  - LOW_AND_SLOW   : many small txns over time, avoid thresholds
  - BURST          : sudden spike in short time window
  - GEO_SPOOF      : impossible travel (Delhi → Mumbai in 10 min)
  - IP_ROTATION    : new device + location on every attempt
  - STEALTH        : mimic normal user almost perfectly, one big txn
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
# ONLY minimal upgrades added: adaptive evasion + memory


import random
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.services.analyzer import analyze_transaction

MAX_EVASION_ATTEMPTS = 6
EVASION_SUCCESS_THRESHOLD = 40
# ── Import your existing analyzer ────────────────────────────────────────────
# analyzer.analyze() is the target system Fraudster AI attacks
from app.services.analyzer import analyze_transaction


# =============================================================================
# 0.  Config
# =============================================================================

# How many evasion attempts before giving up
MAX_EVASION_ATTEMPTS = 6

# Risk score below this = fraud "passed" (evaded detection)
EVASION_SUCCESS_THRESHOLD = 40   # blended_score < 40 = ALLOW

# Evasion tweak parameters
AMOUNT_REDUCTION_STEP  = 0.15   # reduce amount by 15% per attempt
TIME_SHIFT_MINUTES     = 90     # shift time closer to normal hours
LOCATION_FALLBACK      = "Delhi"  # retreat to safer location after flag

# Indian states ordered from highest→lowest fraud signal
# (matches your identity_engine HIGH_RISK_STATES)
STATES_BY_RISK = [
    "Maharashtra", "Delhi", "West Bengal", "Telangana", "Karnataka",
    "Gujarat", "Rajasthan", "Tamil Nadu", "Kerala", "Punjab",
    "Himachal Pradesh", "Uttarakhand", "Goa",
]

# Normal spending profiles (realistic baselines fraudster imitates)
USER_PROFILES = [
    {"user_id": "U001", "avg_amount": 800,  "peak_hour": 20, "state": "Delhi",       "device": "known"},
    {"user_id": "U002", "avg_amount": 1500, "peak_hour": 14, "state": "Maharashtra", "device": "known"},
    {"user_id": "U003", "avg_amount": 500,  "peak_hour": 18, "state": "Karnataka",   "device": "known"},
    {"user_id": "U004", "avg_amount": 2000, "peak_hour": 12, "state": "Gujarat",     "device": "known"},
    {"user_id": "U005", "avg_amount": 300,  "peak_hour": 19, "state": "Tamil Nadu",  "device": "known"},
]


# =============================================================================
# 1.  Data classes
# =============================================================================

@dataclass
class Attempt:
    """A single attack attempt with its result."""
    attempt_number:  int
    transaction:     dict
    blended_score:   float
    risk_level:      str
    action:          str
    passed:          bool          # True = evaded detection
    evasion_applied: str           # what tweak was applied


@dataclass
class BattleResult:
    """Full result of a Fraudster AI vs Detection System battle."""
    attack_type:     str
    user_profile:    dict
    attempts:        list[Attempt]
    final_outcome:   str           # EVADED / BLOCKED
    weaknesses:      list[str]
    battle_id:       str = field(default_factory=lambda: str(uuid.uuid4())[:8].upper())

    @property
    def passed(self) -> bool:
        return self.final_outcome == "EVADED"

    @property
    def attempts_to_evade(self) -> Optional[int]:
        for a in self.attempts:
            if a.passed:
                return a.attempt_number
        return None

    def summary(self) -> dict:
        return {
            "battle_id":       self.battle_id,
            "attack_type":     self.attack_type,
            "final_outcome":   self.final_outcome,
            "total_attempts":  len(self.attempts),
            "attempts_to_evade": self.attempts_to_evade,
            "weaknesses":      self.weaknesses,
            "attempt_log": [
                {
                    "attempt":        a.attempt_number,
                    "blended_score":  a.blended_score,
                    "risk_level":     a.risk_level,
                    "action":         a.action,
                    "passed":         a.passed,
                    "evasion":        a.evasion_applied,
                    "amount":         a.transaction.get("amount"),
                    "time":           a.transaction.get("time"),
                    "state":          a.transaction.get("state"),
                    "is_new_device":  a.transaction.get("is_new_device"),
                }
                for a in self.attempts
            ],
        }


# =============================================================================
# 2.  Fraudster AI Engine
# =============================================================================

class FraudsterAI:
    """
    Adversarial simulation engine.

    Mimics how real fraudsters:
      - Study normal patterns before striking
      - Adapt when flagged (evasion loop)
      - Use different attack strategies
      - Find weaknesses in detection systems

    Usage:
        ai = FraudsterAI()
        result = ai.simulate_attack(attack_type="GEO_SPOOF")
        print(result.summary())
    """

    def __init__(self):
        self._weakness_log: list[str] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def simulate_attack(
        self,
        attack_type: str = "LOW_AND_SLOW",
        profile: Optional[dict] = None,
    ) -> BattleResult:
        """
        Run a full Fraudster AI vs Detection System battle.

        Args:
            attack_type: one of LOW_AND_SLOW / BURST / GEO_SPOOF /
                         IP_ROTATION / STEALTH
            profile:     user profile to impersonate (random if None)

        Returns:
            BattleResult with full attempt log + weaknesses found
        """
        profile  = profile or random.choice(USER_PROFILES)
        attempts = []

        # Step 1 — Generate initial transaction based on attack type
        txn = self._generate_transaction(attack_type, profile)

        for i in range(1, MAX_EVASION_ATTEMPTS + 1):

            # Step 2 — Send to detection system
            score, risk, action = self._score_transaction(txn)

            passed = score < EVASION_SUCCESS_THRESHOLD

            attempts.append(Attempt(
                attempt_number  = i,
                transaction     = dict(txn),
                blended_score   = score,
                risk_level      = risk,
                action          = action,
                passed          = passed,
                evasion_applied = "Initial attempt" if i == 1 else txn.get("_evasion_note", ""),
            ))

            if passed:
                # Fraud evaded — log weakness
                weakness = self._detect_weakness(txn, score, attack_type)
                self._weakness_log.append(weakness)
                return BattleResult(
                    attack_type   = attack_type,
                    user_profile  = profile,
                    attempts      = attempts,
                    final_outcome = "EVADED",
                    weaknesses    = [weakness],
                )

            # Step 3 — Apply evasion strategy and try again
            txn = self._evade(txn, score, attack_type, profile, attempt=i)

        # All attempts failed — system held
        return BattleResult(
            attack_type   = attack_type,
            user_profile  = profile,
            attempts      = attempts,
            final_outcome = "BLOCKED",
            weaknesses    = [],
        )

    def run_all_attacks(self) -> dict:
        """
        Run all 5 attack types and return a combined weakness report.
        Good for the demo's 'stress test' button.
        """
        attack_types = ["LOW_AND_SLOW", "BURST", "GEO_SPOOF", "IP_ROTATION", "STEALTH"]
        results      = {}
        all_weaknesses = []

        for attack in attack_types:
            result = self.simulate_attack(attack_type=attack)
            results[attack] = result.summary()
            all_weaknesses.extend(result.weaknesses)

        passed_count  = sum(1 for r in results.values() if r["final_outcome"] == "EVADED")
        blocked_count = len(attack_types) - passed_count

        return {
            "summary": {
                "attacks_run":    len(attack_types),
                "evaded":         passed_count,
                "blocked":        blocked_count,
                "system_rating":  self._system_rating(blocked_count, len(attack_types)),
            },
            "weaknesses_found": list(set(all_weaknesses)),
            "battle_results":   results,
        }

    # ── Step 1: Transaction Generator ────────────────────────────────────────

    def _generate_transaction(self, attack_type: str, profile: dict) -> dict:
        """
        Generate a realistic suspicious transaction for the given attack type.
        Always starts from the user's normal profile, then deviates.
        """
        base_amount = profile["avg_amount"]
        peak_hour   = profile["peak_hour"]
        home_state  = profile["state"]

        if attack_type == "LOW_AND_SLOW":
            # Many small txns just under threshold — first one looks almost normal
            return {
                "amount":        round(base_amount * 2.5, 2),
                "time":          self._fmt_hour(peak_hour + 2),
                "state":         home_state,
                "is_new_device": False,
            }

        elif attack_type == "BURST":
            # Sudden large spike at odd hour
            return {
                "amount":        round(base_amount * 20, 2),
                "time":          "02:30",
                "state":         home_state,
                "is_new_device": False,
            }

        elif attack_type == "GEO_SPOOF":
            # Impossible travel — home state → very different state immediately
            far_state = "Maharashtra" if home_state != "Maharashtra" else "West Bengal"
            return {
                "amount":        round(base_amount * 10, 2),
                "time":          "03:15",
                "state":         far_state,
                "is_new_device": False,
            }

        elif attack_type == "IP_ROTATION":
            # New device + new location on every attempt (handled in _evade too)
            return {
                "amount":        round(base_amount * 8, 2),
                "time":          "01:45",
                "state":         "Jharkhand",
                "is_new_device": True,
            }

        elif attack_type == "STEALTH":
            # Almost perfectly normal — only one deviation (amount is 15x)
            return {
                "amount":        round(base_amount * 15, 2),
                "time":          self._fmt_hour(peak_hour),
                "state":         home_state,
                "is_new_device": False,
            }

        # Default fallback
        return {
            "amount":        round(base_amount * 5, 2),
            "time":          "23:00",
            "state":         home_state,
            "is_new_device": True,
        }

    # ── Step 2: Score via your real analyzer ──────────────────────────────────

    def _score_transaction(self, txn: dict) -> tuple[float, str, str]:
        """
        Send the transaction to your real detection pipeline.
        Returns (blended_score, risk_level, action).
        """
        try:
            # Build a minimal TransactionRequest-like object
            req = _DictRequest(txn)
            result = analyze_transaction(req)
            score  = result.get("blended_score", 50)
            risk   = result.get("risk_level", "MEDIUM")
            action = result.get("action", "MONITOR")
            return float(score), risk, action
        except Exception as e:
            # Fallback: rule-based scoring if analyzer fails
            return self._fallback_score(txn), "MEDIUM", "MONITOR"

    def _fallback_score(self, txn: dict) -> float:
        """Simple rule score used only if analyzer.py is unavailable."""
        score = 0.0
        amt   = txn.get("amount", 0)
        hour  = int(txn.get("time", "12:00").split(":")[0])
        if amt > 20000: score += 35
        if amt > 50000: score += 20
        if hour < 6:    score += 20
        if txn.get("is_new_device"): score += 25
        return min(score, 100)

    # ── Step 3: Evasion Engine ────────────────────────────────────────────────

    def _evade(
        self,
        txn: dict,
        score: float,
        attack_type: str,
        profile: dict,
        attempt: int,
    ) -> dict:
        """
        Core intelligence: study the risk score and tweak the transaction
        to reduce it. Each attempt applies a more aggressive evasion.
        """
        txn = dict(txn)   # don't mutate original

        # --- General evasion tactics (applied every attempt) ---

        # Tactic 1: Reduce amount gradually
        current_amt = txn.get("amount", 1000)
        reduction   = AMOUNT_REDUCTION_STEP * attempt
        txn["amount"] = round(current_amt * (1 - reduction), 2)
        txn["amount"] = max(txn["amount"], 100)   # floor at ₹100

        # Tactic 2: Shift time toward user's normal peak hour
        current_hour = int(txn.get("time", "02:00").split(":")[0])
        peak_hour    = profile.get("peak_hour", 18)
        # Move 1.5 hrs closer to peak per attempt
        new_hour = current_hour + int((peak_hour - current_hour) * 0.4)
        new_hour = max(0, min(23, new_hour))
        txn["time"] = self._fmt_hour(new_hour)

        # Tactic 3: Retreat to safer location
        if score > 70 and attempt >= 2:
            txn["state"] = profile.get("state", LOCATION_FALLBACK)

        # Tactic 4: Claim known device after initial detection
        if score > 60 and attempt >= 3:
            txn["is_new_device"] = False

        # --- Attack-specific evasion ---

        if attack_type == "LOW_AND_SLOW":
            # Keep amount very small (just above median) to stay under radar
            txn["amount"] = min(txn["amount"], profile["avg_amount"] * 1.5)
            txn["_evasion_note"] = "Reduced to just above avg — low & slow"

        elif attack_type == "BURST":
            # After first block, split into smaller amounts
            txn["amount"] = round(txn["amount"] / (attempt + 1), 2)
            txn["_evasion_note"] = f"Burst split: amount ÷ {attempt+1}"

        elif attack_type == "GEO_SPOOF":
            # Retreat toward home state location progressively
            state_idx = min(attempt - 1, len(STATES_BY_RISK) - 1)
            txn["state"] = STATES_BY_RISK[-(state_idx + 1)]  # safer states
            txn["_evasion_note"] = f"Geo retreat to {txn['state']}"

        elif attack_type == "IP_ROTATION":
            # Keep rotating device/location — the defining feature of this attack
            txn["is_new_device"] = attempt % 2 == 0  # alternate
            states = STATES_BY_RISK[attempt % len(STATES_BY_RISK):]
            txn["state"] = states[0] if states else LOCATION_FALLBACK
            txn["_evasion_note"] = f"IP rotated: new_device={txn['is_new_device']}, state={txn['state']}"

        elif attack_type == "STEALTH":
            # Already close to normal — micro-adjustments only
            txn["amount"] = round(txn["amount"] * 0.92, 2)
            txn["_evasion_note"] = "Stealth micro-reduction"

        return txn

    # ── Weakness Detection ────────────────────────────────────────────────────

    def _detect_weakness(self, txn: dict, score: float, attack_type: str) -> str:
        """
        When fraud evades detection, analyze WHY and generate a weakness report.
        """
        amt  = txn.get("amount", 0)
        hour = int(txn.get("time", "12:00").split(":")[0])

        if attack_type == "LOW_AND_SLOW" and amt < 2000:
            return (
                f"WEAKNESS: Low-value transactions (< ₹{amt:.0f}) not flagged — "
                f"system misses cumulative low-and-slow attacks"
            )
        if attack_type == "BURST" and score < 40:
            return (
                "WEAKNESS: Burst attack evaded after amount reduction — "
                "system lacks rolling-window velocity check"
            )
        if attack_type == "GEO_SPOOF":
            return (
                f"WEAKNESS: Geo-spoofing evaded by retreating to '{txn.get('state')}' — "
                f"intermediate-risk states not flagged strongly enough"
            )
        if attack_type == "IP_ROTATION":
            return (
                "WEAKNESS: IP/device rotation evaded detection — "
                "identity engine needs stronger multi-device penalty"
            )
        if attack_type == "STEALTH" and 18 <= hour <= 22:
            return (
                f"WEAKNESS: Stealth attack during normal hours (₹{amt:.0f}) evaded — "
                f"high-amount detection threshold too lenient for peak hours"
            )
        return (
            f"WEAKNESS: {attack_type} attack evaded with score {score:.1f} — "
            f"review blending weights for this pattern"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fmt_hour(self, hour: int) -> str:
        hour = max(0, min(23, int(hour)))
        return f"{hour:02d}:00"

    def _system_rating(self, blocked: int, total: int) -> str:
        ratio = blocked / total
        if ratio == 1.0: return "EXCELLENT — blocked all attacks"
        if ratio >= 0.8: return "STRONG — minor gaps found"
        if ratio >= 0.6: return "MODERATE — some attack types evaded"
        if ratio >= 0.4: return "WEAK — significant vulnerabilities"
        return "CRITICAL — most attacks evaded"


# =============================================================================
# 3.  Duck-typed request wrapper
#     analyzer.analyze() expects an object with .dict() method
# =============================================================================

class _DictRequest:
    """
    Wraps a plain transaction dict so it behaves like TransactionRequest.
    Lets FraudsterAI call analyzer.analyze() without importing Pydantic models.
    """
    def __init__(self, data: dict):
        self._data = data

    def dict(self) -> dict:
        return {
            "TransactionAmt": self._data.get("amount", 1000),
            "amount":         self._data.get("amount", 1000),
            "time":           self._data.get("time", "12:00"),
            "state":          self._data.get("state", "Delhi"),
            "is_new_device":  self._data.get("is_new_device", False),
            "hour":           int(self._data.get("time", "12:00").split(":")[0]),
            "card_null_count": 4 if self._data.get("is_new_device") else 0,
            "card1":          self._data.get("card1", 9999),
        }

    def parsed_hour(self) -> int:
        return int(self._data.get("time", "12:00").split(":")[0])

    def parsed_minute(self) -> int:
        return int(self._data.get("time", "12:00").split(":")[1])

    def addr1_code(self) -> int:
        from schemas.transaction import STATE_TO_ADDR1
        return STATE_TO_ADDR1.get(self._data.get("state", "").lower(), 999)

    def is_high_risk_state(self) -> bool:
        HIGH_RISK = {"maharashtra", "delhi", "karnataka", "west bengal", "telangana"}
        return self._data.get("state", "").lower() in HIGH_RISK

    @property
    def amount(self):     return self._data.get("amount", 1000)
    @property
    def time(self):       return self._data.get("time", "12:00")
    @property
    def state(self):      return self._data.get("state", "Delhi")
    @property
    def is_new_device(self): return self._data.get("is_new_device", False)


# =============================================================================
# 4.  Module-level singleton
# =============================================================================

fraudster_ai = FraudsterAI()


# =============================================================================
# 5.  Smoke test  —  python fraudster_ai.py
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  FRAUDSTER AI — BATTLE MODE SMOKE TEST")
    print("=" * 65)

    AI = FraudsterAI()

    for attack in ["LOW_AND_SLOW", "GEO_SPOOF", "IP_ROTATION"]:
        print(f"\n  Attack: {attack}")
        print(f"  {'-' * 50}")

        result = AI.simulate_attack(attack_type=attack)

        for a in result.attempts:
            bar    = "█" * int(a.blended_score / 5)
            status = "PASSED" if a.passed else "BLOCKED"
            print(
                f"  Attempt {a.attempt_number}: "
                f"score={a.blended_score:5.1f}  "
                f"[{a.risk_level:8s}]  "
                f"{status}  "
                f"amt=₹{a.transaction.get('amount', 0):>8,.0f}  "
                f"time={a.transaction.get('time')}  "
                f"{a.evasion_applied}"
            )

        print(f"\n  OUTCOME: {result.final_outcome}")
        if result.weaknesses:
            for w in result.weaknesses:
                print(f"  {w}")

    print("\n" + "=" * 65)
    print("  FULL STRESS TEST (all 5 attacks)")
    print("=" * 65)
    full = AI.run_all_attacks()
    s    = full["summary"]
    print(f"  Attacks run : {s['attacks_run']}")
    print(f"  Evaded      : {s['evaded']}")
    print(f"  Blocked     : {s['blocked']}")
    print(f"  Rating      : {s['system_rating']}")
    if full["weaknesses_found"]:
        print(f"\n  Weaknesses found:")
        for w in full["weaknesses_found"]:
            print(f"    {w}")
    print("=" * 65)