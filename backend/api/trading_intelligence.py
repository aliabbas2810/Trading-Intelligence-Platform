from __future__ import annotations

from pydantic import BaseModel, Field

from backend.api.ai import AiDecisionResponse
from backend.api.checklist import ChecklistResultResponse
from backend.api.entry import EntryDecisionResponse
from backend.api.readiness import AnalysisReadinessResponse
from backend.api.risk import RiskPlanResponse
from backend.api.scoring import SetupScoreResponse
from backend.engines.entry.models import MetadataValue
from backend.engines.intelligence import TradingIntelligenceResult
from backend.models import Timeframe


class TradingIntelligenceRequest(BaseModel):
    """Trading intelligence chain request for INTEL-001 through INTEL-006."""

    symbol: str
    timeframe: Timeframe = Timeframe.FOUR_HOUR
    minimum_risk_reward: float | None = Field(default=2.0, gt=0)


class TradingIntelligenceResponse(BaseModel):
    """Consolidated trading intelligence response for INTEL-001 through INTEL-006."""

    symbol: str
    timeframe: Timeframe
    entry_decision: EntryDecisionResponse
    risk_plan: RiskPlanResponse
    checklist: ChecklistResultResponse
    setup_score: SetupScoreResponse
    ai_decision: AiDecisionResponse
    readiness: AnalysisReadinessResponse | None = None
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_result(cls, result: TradingIntelligenceResult) -> TradingIntelligenceResponse:
        return cls(
            symbol=result.symbol,
            timeframe=result.timeframe,
            entry_decision=EntryDecisionResponse.from_trace(result.entry_decision),
            risk_plan=RiskPlanResponse.from_plan(result.risk_plan),
            checklist=ChecklistResultResponse.from_result(result.checklist),
            setup_score=SetupScoreResponse.from_score(result.setup_score),
            ai_decision=AiDecisionResponse.from_output(result.ai_decision),
            readiness=(
                AnalysisReadinessResponse.from_readiness(result.readiness)
                if result.readiness is not None
                else None
            ),
            metadata=dict(result.metadata),
        )
