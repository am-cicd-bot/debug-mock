from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class CanonicalReasonCode(str, Enum):
    VISA_10_4 = "VISA_10_4"
    VISA_12_6 = "VISA_12_6"
    VISA_13_1 = "VISA_13_1"
    VISA_13_2 = "VISA_13_2"
    MC_4837 = "MC_4837"
    MC_4834 = "MC_4834"
    ACH_R29 = "ACH_R29"
    ACH_R10 = "ACH_R10"


class ProvisionalCreditRequest(BaseModel):
    account_id: str = Field(..., min_length=4)
    transaction_id: str = Field(..., min_length=4)
    ticket_id: str = Field(..., min_length=4)
    amount_cents: int = Field(..., gt=0, description="Credit amount in minor currency units (integer cents)")
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    memo: str = Field(default="Automated provisional dispute credit")


class ChargebackFilingRequest(BaseModel):
    account_id: str
    transaction_id: str
    ticket_id: str
    reason_code: CanonicalReasonCode
    disputed_amount_cents: int = Field(..., gt=0)
    settlement_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    evidence_summary: Optional[str] = None
    merchant_contact_date: Optional[str] = None
