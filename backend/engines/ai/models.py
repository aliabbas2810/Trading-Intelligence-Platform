from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.api import StructureSnapshot, TrendSnapshot
from backend.engines.scanner import SetupCandidate
from backend.engines.trend import MultiTimeframeTrendResult, TimeframeTrendSnapshot


class AiRecommendation(str, Enum):
    CONSIDER_LONG = "consider_long"
    CONSIDER_SHORT = "consider_short"
    WATCH = "watch"
    AVOID = "avoid"


class AiRiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class AiReason:
    """Explainable reason emitted by the AI layer for FR-1002."""

    category: str
    message: str
    evidence: str

    def __post_init__(self) -> None:
        if not self.category:
            raise ValueError("AiReason category is required")
        if not self.message:
            raise ValueError("AiReason message is required")
        if not self.evidence:
            raise ValueError("AiReason evidence is required")


@dataclass(frozen=True, slots=True)
class AiRiskAssessment:
    """Risk highlight model for FR-1004; risk values are supplied as explanation, not orders."""

    severity: AiRiskSeverity
    risks: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.risks:
            raise ValueError("AiRiskAssessment requires at least one risk")


@dataclass(frozen=True, slots=True)
class AiDecisionInput:
    """Structured analytical input consumed by the AI engine for FR-1001."""

    symbol: str
    timeframe_states: tuple[TimeframeTrendSnapshot, ...] = ()
    alignment: MultiTimeframeTrendResult | None = None
    setup_candidate: SetupCandidate | None = None
    latest_structure: StructureSnapshot | None = None
    latest_trend: TrendSnapshot | None = None
    entry_signal: str | None = None
    risk_reward: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("AiDecisionInput symbol is required")


@dataclass(frozen=True, slots=True)
class AiDecisionOutput:
    """Structured AI decision response for FR-1002 through FR-1005."""

    symbol: str
    recommendation: AiRecommendation
    confidence: float
    explanation: str
    risk_assessment: AiRiskAssessment
    reasons: tuple[AiReason, ...]
    provider: str

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("AiDecisionOutput symbol is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("AiDecisionOutput confidence must be between 0.0 and 1.0")
        if not self.explanation:
            raise ValueError("AiDecisionOutput explanation is required")
        if not self.reasons:
            raise ValueError("AiDecisionOutput requires at least one reason")
        if not self.provider:
            raise ValueError("AiDecisionOutput provider is required")


@dataclass(frozen=True, slots=True)
class AiDecisionContext:
    """Structured prompt/context payload for FR-1001 and FR-1006 provider boundaries."""

    symbol: str
    facts: tuple[str, ...]
    prompt: str
