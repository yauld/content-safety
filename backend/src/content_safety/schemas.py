from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Decision = Literal["approved", "rejected", "needs_review"]
ModerationStatus = Literal["completed", "interrupted"]
RiskLevel = Literal["low", "medium", "high"]
DecisionStage = Literal["workflow", "agent", "human"]


class ModerateRequest(BaseModel):
    request_id: str | None = None
    scene: str = "default"
    user_id: str | None = None
    content: str = Field(min_length=1, max_length=8000)


class ModerateResponse(BaseModel):
    request_id: str | None
    moderation_id: str
    thread_id: str
    status: ModerationStatus
    decision: Decision
    reason: str
    risk_level: RiskLevel
    decision_stage: DecisionStage
    evidence: list[str] = Field(default_factory=list)
    rule_hits: list[str] = Field(default_factory=list)
    confidence: float | None = None
    interrupt: dict | None = None


class ResumeRequest(BaseModel):
    decision: Decision
    reason: str = Field(min_length=1, max_length=1000)


class ModerationRecord(BaseModel):
    request_id: str | None
    moderation_id: str
    thread_id: str
    scene: str
    user_id: str | None
    content: str
    status: ModerationStatus
    decision: Decision
    reason: str
    risk_level: RiskLevel
    decision_stage: DecisionStage
    evidence: list[str] = Field(default_factory=list)
    rule_hits: list[str] = Field(default_factory=list)
    confidence: float | None = None
    created_at: datetime
    updated_at: datetime


class ReviewSummary(BaseModel):
    pending_total: int
    pending_max_wait_seconds: int
    pending_agent: int
    completed_today: int


class DashboardMetricGroup(BaseModel):
    total: int = 0
    approved: int = 0
    rejected: int = 0
    needs_review: int = 0


class DashboardSummary(BaseModel):
    total_requests: int
    completed_total: int
    interrupted_total: int
    auto_completed_total: int
    human_involved_total: int
    workflow: DashboardMetricGroup
    agent: DashboardMetricGroup
    human: DashboardMetricGroup
    pending_total: int
    pending_max_wait_seconds: int
    completed_today: int
    rule_hits: dict[str, int] = Field(default_factory=dict)
    risk_levels: dict[str, int] = Field(default_factory=dict)
    decision_stages: dict[str, int] = Field(default_factory=dict)
    confidence_buckets: dict[str, int] = Field(default_factory=dict)
    waiting_buckets: dict[str, int] = Field(default_factory=dict)
