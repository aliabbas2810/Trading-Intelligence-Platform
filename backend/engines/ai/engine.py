from __future__ import annotations

from backend.engines.ai.models import AiDecisionInput, AiDecisionOutput
from backend.engines.ai.providers import AiDecisionProvider


class AiDecisionEngine:
    """Provider-backed AI decision foundation consuming structured outputs only."""

    def __init__(self, provider: AiDecisionProvider) -> None:
        self._provider = provider

    def generate_decision(self, decision_input: AiDecisionInput) -> AiDecisionOutput:
        """Validate input, call provider, and return structured output for FR-1001 through FR-1006."""

        self._validate(decision_input)
        output = self._provider.generate_decision(decision_input)
        if output.symbol != decision_input.symbol:
            raise ValueError("AI provider output symbol must match input symbol")
        return output

    def _validate(self, decision_input: AiDecisionInput) -> None:
        if decision_input.alignment is not None and decision_input.alignment.symbol != decision_input.symbol:
            raise ValueError("AI alignment symbol must match input symbol")
        if (
            decision_input.setup_candidate is not None
            and decision_input.setup_candidate.symbol != decision_input.symbol
        ):
            raise ValueError("AI setup candidate symbol must match input symbol")
        if (
            decision_input.latest_trend is not None
            and decision_input.latest_trend.update is not None
            and decision_input.latest_trend.update.symbol != decision_input.symbol
        ):
            raise ValueError("AI trend snapshot symbol must match input symbol")
