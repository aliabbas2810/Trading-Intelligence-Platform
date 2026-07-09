from __future__ import annotations

from backend.engines.ai.models import AiDecisionContext, AiDecisionInput


class AiDecisionContextBuilder:
    """Build a structured prompt from deterministic outputs without recalculation."""

    def build(self, decision_input: AiDecisionInput) -> AiDecisionContext:
        """Construct provider context for FR-1001 and FR-1002."""

        facts = tuple(self._facts(decision_input))
        prompt = "\n".join(
            (
                "Use only the structured facts below.",
                "Do not calculate candles, structure, trend, scanner score, or risk metrics.",
                *facts,
            ),
        )
        return AiDecisionContext(symbol=decision_input.symbol, facts=facts, prompt=prompt)

    def _facts(self, decision_input: AiDecisionInput) -> list[str]:
        facts = [f"symbol={decision_input.symbol}"]

        if decision_input.timeframe_states:
            states = ", ".join(
                f"{snapshot.timeframe.value}:{snapshot.state.value}"
                for snapshot in decision_input.timeframe_states
            )
            facts.append(f"timeframe_states={states}")
        else:
            facts.append("timeframe_states=missing")

        if decision_input.alignment is not None:
            facts.append(f"alignment_bias={decision_input.alignment.bias.value}")
            facts.append(f"alignment_score={decision_input.alignment.alignment_score}")
        else:
            facts.append("alignment=missing")

        if decision_input.setup_candidate is not None:
            facts.append(f"setup_score={decision_input.setup_candidate.score:.2f}")
            facts.append(f"setup_bias={decision_input.setup_candidate.bias.value}")
        else:
            facts.append("setup_candidate=missing")

        if decision_input.latest_structure is not None:
            facts.append(f"structure_swings={len(decision_input.latest_structure.swings)}")
            facts.append(f"bos_events={len(decision_input.latest_structure.breaks_of_structure)}")
        else:
            facts.append("structure=missing")

        if decision_input.latest_trend is not None and decision_input.latest_trend.update is not None:
            facts.append(f"latest_trend={decision_input.latest_trend.update.state.value}")
        else:
            facts.append("latest_trend=missing")

        if decision_input.entry_signal is not None:
            facts.append(f"entry_signal={decision_input.entry_signal}")
        else:
            facts.append("entry_signal=missing")

        if decision_input.entry_state is not None:
            facts.append(f"entry_state={decision_input.entry_state.value}")
        if decision_input.entry_direction is not None:
            facts.append(f"entry_direction={decision_input.entry_direction.value}")
        if decision_input.risk_state is not None:
            facts.append(f"risk_state={decision_input.risk_state.value}")
        if decision_input.checklist_status is not None:
            facts.append(f"checklist_status={decision_input.checklist_status.value}")
        if decision_input.setup_grade is not None:
            facts.append(f"setup_grade={decision_input.setup_grade.value}")
        if decision_input.setup_score_percentage is not None:
            facts.append(f"setup_score_percentage={decision_input.setup_score_percentage:.2f}")
        if decision_input.risk_reward_ratio is not None:
            facts.append(f"risk_reward_ratio={decision_input.risk_reward_ratio:.4f}")

        if decision_input.risk_reward is not None:
            facts.append(f"risk_reward={decision_input.risk_reward}")
        else:
            facts.append("risk_reward=missing")

        return facts
