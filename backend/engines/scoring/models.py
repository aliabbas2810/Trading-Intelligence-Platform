from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from backend.engines.checklist import ChecklistResult
from backend.engines.entry import DecisionTrace
from backend.engines.entry.models import MetadataValue
from backend.engines.risk import RiskPlan
from backend.engines.scanner import SetupCandidate
from backend.engines.trend import MultiTimeframeTrendResult


class ScoreGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    """Weighted component for SCORE-002 and SCORE-004."""

    name: str
    category: str
    raw_score: float
    weight: float
    weighted_score: float
    max_score: float
    evidence_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ScoreComponent name is required")
        if not self.category:
            raise ValueError("ScoreComponent category is required")
        if self.raw_score < 0.0:
            raise ValueError("ScoreComponent raw_score cannot be negative")
        if self.weight < 0.0:
            raise ValueError("ScoreComponent weight cannot be negative")
        if self.max_score <= 0.0:
            raise ValueError("ScoreComponent max_score must be positive")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SetupScore:
    """Deterministic setup score for SCORE-001 through SCORE-006."""

    symbol: str
    total_score: float
    max_score: float
    percentage: float
    grade: ScoreGrade
    components: tuple[ScoreComponent, ...]
    summary: str
    warnings: tuple[str, ...]
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("SetupScore symbol is required")
        if self.max_score <= 0.0:
            raise ValueError("SetupScore max_score must be positive")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ScoringInput:
    """Structured setup scoring input that consumes existing deterministic outputs only."""

    symbol: str
    entry_trace: DecisionTrace | None = None
    risk_plan: RiskPlan | None = None
    checklist_result: ChecklistResult | None = None
    alignment: MultiTimeframeTrendResult | None = None
    scanner_candidate: SetupCandidate | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("ScoringInput symbol is required")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
