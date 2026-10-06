from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Action = Literal["tracking_update", "refund", "manual_review"]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(pattern=r"^ORD-\d{4}$")
    issue: str = Field(min_length=3, max_length=1000)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    rationale: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(max_length=5)


class Resolution(BaseModel):
    case_id: str
    order_id: str
    status: Literal["completed", "awaiting_approval", "manual_review", "failed", "rejected"]
    proposal: Proposal | None = None
    amount_cents: int = 0
    receipt: str | None = None
    error: str | None = None


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
