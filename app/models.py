"""Shared document shapes. See docs/contracts.md; change these only with the team."""
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["finance_lead", "analyst", "store_manager"]
ROLES: list[str] = ["finance_lead", "analyst", "store_manager"]

MemoryType = Literal["metric", "definition", "decision", "fact"]
MemoryStatus = Literal["pending", "active", "rejected", "superseded", "expired", "forgotten"]
SkillStatus = Literal["draft", "published", "stale", "retired"]
Outcome = Literal["answered", "failed", "rejected", "user_confirmed"]


class UserContext(BaseModel):
    user_id: str
    display_name: str
    role: Role
    rows: dict[str, Any] = Field(default_factory=dict)
    hidden_fields: list[str] = Field(default_factory=list)
    can_review: bool = False


class ProposedMemory(BaseModel):
    type: MemoryType
    title: str
    content: str


class SkillCall(BaseModel):
    name: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    interpretation: str
    collection: str = "sales"
    pipeline: list[dict[str, Any]] = Field(default_factory=list)
    metrics_used: list[str] = Field(default_factory=list)
    skill: SkillCall | None = None
    proposed_memory: ProposedMemory | None = None
    assumptions: list[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None
    use_memory: bool = True


class ReasonBody(BaseModel):
    reason: str = ""


class ApproveBody(BaseModel):
    # Reviewer may set the final visibility at approval time
    visibility: list[Role] | None = None
    expires_at: str | None = None  # ISO datetime


class GenerateSkillBody(BaseModel):
    cluster_id: str | None = None  # None = first ready cluster
