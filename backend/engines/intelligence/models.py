from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from backend.engines.ai import AiDecisionOutput
from backend.engines.checklist import ChecklistResult
from backend.engines.entry import DecisionTrace
from backend.engines.entry.models import MetadataValue
from backend.engines.readiness import AnalysisReadiness
from backend.engines.risk import RiskPlan
from backend.engines.scoring import SetupScore
from backend.models import Timeframe


@dataclass(frozen=True, slots=True)
class TradingIntelligenceResult:
    """Consolidated trading intelligence output for INTEL-001 through INTEL-006."""

    symbol: str
    timeframe: Timeframe
    entry_decision: DecisionTrace
    risk_plan: RiskPlan
    checklist: ChecklistResult
    setup_score: SetupScore
    ai_decision: AiDecisionOutput
    readiness: AnalysisReadiness | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("TradingIntelligenceResult symbol is required")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
