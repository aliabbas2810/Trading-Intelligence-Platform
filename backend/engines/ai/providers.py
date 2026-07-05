from __future__ import annotations

from typing import Protocol

from backend.engines.ai.context import AiDecisionContextBuilder
from backend.engines.ai.models import (
    AiDecisionInput,
    AiDecisionOutput,
    AiReason,
    AiRecommendation,
    AiRiskAssessment,
    AiRiskSeverity,
)
from backend.engines.trend import DirectionalBias


class AiDecisionProvider(Protocol):
    """Provider interface for FR-1006; real LLM integrations are future work."""

    def generate_decision(self, decision_input: AiDecisionInput) -> AiDecisionOutput:
        """Generate a structured decision from deterministic input only."""


class RuleBasedMockAiDecisionProvider:
    """Deterministic local provider for FR-1002 through FR-1005 and TEST-001."""

    provider_name = "rule_based_mock"

    def __init__(self, context_builder: AiDecisionContextBuilder | None = None) -> None:
        self._context_builder = context_builder or AiDecisionContextBuilder()

    def generate_decision(self, decision_input: AiDecisionInput) -> AiDecisionOutput:
        context = self._context_builder.build(decision_input)
        recommendation = self._recommendation(decision_input)
        confidence = self._confidence(decision_input)
        risks = self._risks(decision_input)
        return AiDecisionOutput(
            symbol=decision_input.symbol,
            recommendation=recommendation,
            confidence=confidence,
            explanation=f"Structured analysis for {decision_input.symbol}: {context.facts[0]}.",
            risk_assessment=AiRiskAssessment(
                severity=self._risk_severity(risks),
                risks=risks,
            ),
            reasons=self._reasons(decision_input),
            provider=self.provider_name,
        )

    def _recommendation(self, decision_input: AiDecisionInput) -> AiRecommendation:
        bias = decision_input.setup_candidate.bias if decision_input.setup_candidate is not None else None
        score = decision_input.setup_candidate.score if decision_input.setup_candidate is not None else 0.0
        if bias is DirectionalBias.BULLISH and score >= 30.0:
            return AiRecommendation.CONSIDER_LONG
        if bias is DirectionalBias.BEARISH and score >= 30.0:
            return AiRecommendation.CONSIDER_SHORT
        if decision_input.alignment is None and decision_input.setup_candidate is None:
            return AiRecommendation.AVOID
        return AiRecommendation.WATCH

    def _confidence(self, decision_input: AiDecisionInput) -> float:
        if decision_input.setup_candidate is None:
            return 0.1
        confidence = min(0.95, 0.2 + (decision_input.setup_candidate.score / 100.0))
        if decision_input.latest_structure is None:
            confidence -= 0.05
        if decision_input.latest_trend is None or decision_input.latest_trend.update is None:
            confidence -= 0.05
        return max(0.0, round(confidence, 2))

    def _risks(self, decision_input: AiDecisionInput) -> tuple[str, ...]:
        risks: list[str] = []
        if decision_input.alignment is None:
            risks.append("Missing multi-timeframe alignment.")
        elif decision_input.alignment.alignment_score < 2:
            risks.append("Alignment score is below a strong consensus threshold.")
        if decision_input.latest_structure is None:
            risks.append("Latest structure snapshot is missing.")
        if decision_input.entry_signal is None:
            risks.append("Entry signal is not supplied.")
        if decision_input.risk_reward is None:
            risks.append("Risk/reward context is not supplied.")
        if not risks:
            risks.append("No additional deterministic risk context was supplied.")
        return tuple(risks)

    def _risk_severity(self, risks: tuple[str, ...]) -> AiRiskSeverity:
        if len(risks) >= 3:
            return AiRiskSeverity.HIGH
        if len(risks) == 2:
            return AiRiskSeverity.MEDIUM
        return AiRiskSeverity.LOW

    def _reasons(self, decision_input: AiDecisionInput) -> tuple[AiReason, ...]:
        reasons: list[AiReason] = []
        if decision_input.alignment is not None:
            reasons.append(
                AiReason(
                    category="alignment",
                    message="Multi-timeframe alignment was supplied.",
                    evidence=f"{decision_input.alignment.bias.value}/{decision_input.alignment.alignment_score}",
                ),
            )
        if decision_input.setup_candidate is not None:
            reasons.append(
                AiReason(
                    category="scanner",
                    message="Scanner candidate score was supplied.",
                    evidence=f"{decision_input.setup_candidate.score:.2f}",
                ),
            )
        if decision_input.latest_trend is not None and decision_input.latest_trend.update is not None:
            reasons.append(
                AiReason(
                    category="trend",
                    message="Latest trend state was supplied.",
                    evidence=decision_input.latest_trend.update.state.value,
                ),
            )
        if not reasons:
            reasons.append(
                AiReason(
                    category="missing_data",
                    message="Decision input contains limited deterministic context.",
                    evidence="alignment/setup/trend unavailable",
                ),
            )
        return tuple(reasons)
