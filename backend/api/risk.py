from __future__ import annotations

from pydantic import BaseModel, Field

from backend.engines.entry.models import MetadataValue
from backend.engines.risk import (
    RiskAssessmentState,
    RiskDirection,
    RiskEvidence,
    RiskEvidenceCategory,
    RiskEvidenceCode,
    RiskEvidenceSeverity,
    RiskLevel,
    RiskPlan,
)
from backend.models import Timeframe


class RiskEvaluateRequest(BaseModel):
    """Risk evaluation request for RISK-001 through RISK-006."""

    symbol: str
    minimum_risk_reward: float | None = Field(default=2.0, gt=0)
    target_mode: str | None = "rr"


class RiskEvidenceResponse(BaseModel):
    """Structured RiskEvidence API payload for RISK-005."""

    code: RiskEvidenceCode
    category: RiskEvidenceCategory
    severity: RiskEvidenceSeverity
    description: str
    timeframe: Timeframe | None
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_evidence(cls, evidence: RiskEvidence) -> RiskEvidenceResponse:
        return cls(
            code=evidence.code,
            category=evidence.category,
            severity=evidence.severity,
            description=evidence.description,
            timeframe=evidence.timeframe,
            metadata=dict(evidence.metadata),
        )


class RiskPlanResponse(BaseModel):
    """RiskPlan transport response for RISK-001 through RISK-006."""

    direction: RiskDirection
    state: RiskAssessmentState
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward_ratio: float | None
    invalidation_level: float | None
    risk_level: RiskLevel | None
    reasons: tuple[str, ...]
    evidence: tuple[RiskEvidenceResponse, ...]
    warnings: tuple[str, ...]
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_plan(cls, plan: RiskPlan) -> RiskPlanResponse:
        return cls(
            direction=plan.direction,
            state=plan.state,
            entry_price=plan.entry_price,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            risk_reward_ratio=plan.risk_reward_ratio,
            invalidation_level=plan.invalidation_level,
            risk_level=plan.risk_level,
            reasons=plan.reasons,
            evidence=tuple(RiskEvidenceResponse.from_evidence(item) for item in plan.evidence),
            warnings=plan.warnings,
            metadata=dict(plan.metadata),
        )
