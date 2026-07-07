from __future__ import annotations

from pydantic import BaseModel

from backend.engines.ai import (
    AiDecisionOutput,
    AiReason,
    AiRecommendation,
    AiRiskAssessment,
    AiRiskSeverity,
)
from backend.models import Timeframe


class AiDecisionRequest(BaseModel):
    """Decision request for FR-1001 through FR-1006."""

    symbol: str
    timeframe: Timeframe = Timeframe.FOUR_HOUR
    entry_signal: str | None = None
    risk_reward: str | None = None


class AiReasonResponse(BaseModel):
    """Explainable AI reason response for FR-1002."""

    category: str
    message: str
    evidence: str

    @classmethod
    def from_reason(cls, reason: AiReason) -> AiReasonResponse:
        return cls(
            category=reason.category,
            message=reason.message,
            evidence=reason.evidence,
        )


class AiRiskAssessmentResponse(BaseModel):
    """Risk response for FR-1004."""

    severity: AiRiskSeverity
    risks: tuple[str, ...]

    @classmethod
    def from_assessment(cls, assessment: AiRiskAssessment) -> AiRiskAssessmentResponse:
        return cls(
            severity=assessment.severity,
            risks=assessment.risks,
        )


class AiDecisionResponse(BaseModel):
    """Structured decision response for FR-1002 through FR-1005."""

    symbol: str
    recommendation: AiRecommendation
    confidence: float
    explanation: str
    risk_assessment: AiRiskAssessmentResponse
    reasons: tuple[AiReasonResponse, ...]
    provider: str

    @classmethod
    def from_output(cls, output: AiDecisionOutput) -> AiDecisionResponse:
        return cls(
            symbol=output.symbol,
            recommendation=output.recommendation,
            confidence=output.confidence,
            explanation=output.explanation,
            risk_assessment=AiRiskAssessmentResponse.from_assessment(output.risk_assessment),
            reasons=tuple(AiReasonResponse.from_reason(reason) for reason in output.reasons),
            provider=output.provider,
        )
