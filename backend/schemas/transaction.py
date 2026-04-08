"""
schemas/transaction.py — Pydantic models for the fraud detection API.

User only needs to send 4 fields:
  - amount        : transaction amount (INR)
  - time          : "HH:MM" string  e.g. "02:30"
  - state         : Indian state name  e.g. "Maharashtra"
  - is_new_device : true / false
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from typing import List, Dict

class BehaviorAnalysis(BaseModel):
    behavior_score: float
    reasons: List[str]

# ── Indian state → addr1 region code mapping ─────────────────────────────────
# addr1 in the IEEE-CIS dataset is a numeric billing-region code (100-540 range).
# We map Indian states to plausible codes so the trained model gets a numeric value.

STATE_TO_ADDR1: dict[str, int] = {
    # North
    "delhi": 110,       "haryana": 120,     "punjab": 130,
    "himachal pradesh": 140, "uttarakhand": 150, "uttar pradesh": 160,
    "rajasthan": 170,   "jammu and kashmir": 180, "ladakh": 185,
    # East
    "west bengal": 200, "odisha": 210,      "bihar": 220,
    "jharkhand": 230,   "assam": 240,       "sikkim": 245,
    "nagaland": 250,    "manipur": 255,     "meghalaya": 260,
    "mizoram": 265,     "tripura": 270,     "arunachal pradesh": 275,
    # West
    "maharashtra": 300, "gujarat": 310,     "goa": 320,
    "madhya pradesh": 330, "chhattisgarh": 340,
    # South
    "karnataka": 400,   "tamil nadu": 410,  "kerala": 420,
    "andhra pradesh": 430, "telangana": 440,
    "puducherry": 450,
    # Union Territories / others
    "chandigarh": 500,  "dadra and nagar haveli": 510,
    "lakshadweep": 520, "andaman and nicobar": 530,
    "other": 999,
}

# High-risk states (higher fraud incidence used as a risk signal)
HIGH_RISK_STATES = {"delhi", "maharashtra", "karnataka", "west bengal", "telangana"}


class TransactionRequest(BaseModel):
    """
    The only 4 fields a user needs to submit.
    All other model features are filled with training medians automatically.
    """
    amount: float = Field(
        ...,
        gt=0,
        description="Transaction amount in INR (e.g. 5000.0)",
        example=25000.0,
    )
    time: str = Field(
        ...,
        description="Time of transaction in HH:MM format (24-hour)",
        example="02:30",
    )
    state: str = Field(
        ...,
        description="Indian state where transaction originated",
        example="Maharashtra",
    )
    is_new_device: bool = Field(
        ...,
        description="True if the transaction comes from a device not seen before",
        example=True,
    )
    ip_address: str = Field(
    ...,
    description="User IP address",
    example="192.168.1.1"
    )
    user_id: str = Field(
    ...,
    description="Unique identifier for the user making the transaction",
    example="U001"
    )   

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        parts = v.strip().split(":")
        if len(parts) != 2:
            raise ValueError("time must be in HH:MM format")
        h, m = parts
        if not (h.isdigit() and m.isdigit()):
            raise ValueError("time must contain numeric hours and minutes")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError("time out of range — use 00:00 to 23:59")
        return v.strip()

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        normalised = v.strip().lower()
        if normalised not in STATE_TO_ADDR1:
            # Accept unknown states — will fall back to "other" code
            return v.strip()
        return v.strip()

    def parsed_hour(self) -> int:
        return int(self.time.split(":")[0])

    def parsed_minute(self) -> int:
        return int(self.time.split(":")[1])

    def addr1_code(self) -> int:
        return STATE_TO_ADDR1.get(self.state.strip().lower(), 999)

    def is_high_risk_state(self) -> bool:
        return self.state.strip().lower() in HIGH_RISK_STATES


class FraudDetectionResponse(BaseModel):
    transaction: Dict

    ml_score: float
    blended_score: float
    risk_level: str
    action: str

    behavior: BehaviorAnalysis

    context: Dict
    compliance: Dict

    signals: List[str]
    explanation: str

    user_actions: List[str]
    bank_actions: List[str]