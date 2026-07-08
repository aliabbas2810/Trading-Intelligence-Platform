from __future__ import annotations

from pydantic import BaseModel, Field

from backend.engines.entry.models import MetadataValue
from backend.engines.scoring import ScoreComponent, ScoreGrade, SetupScore


class SetupScoreEvaluateRequest(BaseModel):
    """Setup score evaluation request for SCORE-001 through SCORE-006."""

    symbol: str
    minimum_risk_reward: float | None = Field(default=2.0, gt=0)


class ScoreComponentResponse(BaseModel):
    """ScoreComponent transport payload for SCORE-002 and SCORE-004."""

    name: str
    category: str
    raw_score: float
    weight: float
    weighted_score: float
    max_score: float
    evidence_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_component(cls, component: ScoreComponent) -> ScoreComponentResponse:
        return cls(
            name=component.name,
            category=component.category,
            raw_score=component.raw_score,
            weight=component.weight,
            weighted_score=component.weighted_score,
            max_score=component.max_score,
            evidence_codes=component.evidence_codes,
            reasons=component.reasons,
            metadata=dict(component.metadata),
        )


class SetupScoreResponse(BaseModel):
    """SetupScore transport response for SCORE-001 through SCORE-006."""

    symbol: str
    total_score: float
    max_score: float
    percentage: float
    grade: ScoreGrade
    components: tuple[ScoreComponentResponse, ...]
    summary: str
    warnings: tuple[str, ...]
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_score(cls, score: SetupScore) -> SetupScoreResponse:
        return cls(
            symbol=score.symbol,
            total_score=score.total_score,
            max_score=score.max_score,
            percentage=score.percentage,
            grade=score.grade,
            components=tuple(ScoreComponentResponse.from_component(item) for item in score.components),
            summary=score.summary,
            warnings=score.warnings,
            metadata=dict(score.metadata),
        )
