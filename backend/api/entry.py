from __future__ import annotations

from pydantic import BaseModel

from backend.engines.entry import (
    DecisionEvidence,
    DecisionEvidenceCategory,
    DecisionEvidenceCode,
    DecisionEvidencePolarity,
    DecisionEvidenceSeverity,
    DecisionTrace,
    EntryDirection,
    EntryState,
)
from backend.engines.entry.models import MetadataValue
from backend.models import Timeframe


class EntryEvaluateRequest(BaseModel):
    """Entry evaluation request for ENTRY-001 through ENTRY-006."""

    symbol: str


class DecisionEvidenceResponse(BaseModel):
    """Structured evidence API payload for M21.1."""

    code: DecisionEvidenceCode
    category: DecisionEvidenceCategory
    timeframe: Timeframe | None
    polarity: DecisionEvidencePolarity
    severity: DecisionEvidenceSeverity
    description: str
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_evidence(cls, evidence: DecisionEvidence) -> DecisionEvidenceResponse:
        return cls(
            code=evidence.code,
            category=evidence.category,
            timeframe=evidence.timeframe,
            polarity=evidence.polarity,
            severity=evidence.severity,
            description=evidence.description,
            metadata=dict(evidence.metadata),
        )


class EntryDecisionResponse(BaseModel):
    """DecisionTrace transport response for ENTRY-001 and ENTRY-005."""

    state: EntryState
    direction: EntryDirection
    confidence: float
    reasons: tuple[str, ...]
    evidence: tuple[DecisionEvidenceResponse, ...]
    missing_confirmations: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    trigger_timeframe: Timeframe | None
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_trace(cls, trace: DecisionTrace) -> EntryDecisionResponse:
        return cls(
            state=trace.state,
            direction=trace.direction,
            confidence=trace.confidence,
            reasons=trace.reasons,
            evidence=tuple(DecisionEvidenceResponse.from_evidence(item) for item in trace.evidence),
            missing_confirmations=trace.missing_confirmations,
            invalidation_conditions=trace.invalidation_conditions,
            trigger_timeframe=trace.trigger_timeframe,
            metadata=dict(trace.metadata),
        )
