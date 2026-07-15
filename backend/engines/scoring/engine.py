from __future__ import annotations

from backend.engines.checklist import ChecklistItemStatus
from backend.engines.entry import (
    DecisionEvidenceCategory,
    DecisionEvidenceCode,
    DecisionEvidencePolarity,
    EntryState,
)
from backend.engines.risk import RiskAssessmentState
from backend.engines.scoring.models import ScoreComponent, ScoreGrade, ScoringInput, SetupScore
from backend.engines.trend import DirectionalBias


class SetupScoringEngine:
    """Deterministic setup scorer consuming existing analytical outputs only."""

    def evaluate(self, scoring_input: ScoringInput) -> SetupScore:
        """Build a weighted setup score for SCORE-001 through SCORE-006."""

        components = (
            self._trend_component(scoring_input),
            self._aoi_component(scoring_input),
            self._entry_component(scoring_input),
            self._risk_component(scoring_input),
            self._checklist_component(scoring_input),
        )
        total_score = round(sum(component.weighted_score for component in components), 4)
        max_score = round(sum(component.max_score for component in components), 4)
        if self._aoi_gate_failed(scoring_input):
            total_score = round(min(total_score, max_score * 0.54), 4)
        if scoring_input.entry_trace is not None and scoring_input.entry_trace.state is EntryState.INVALIDATED:
            total_score = round(min(total_score, max_score * 0.39), 4)
        elif scoring_input.entry_trace is not None and scoring_input.entry_trace.missing_confirmations:
            total_score = round(min(total_score, max_score * 0.54), 4)
        if scoring_input.risk_plan is not None and scoring_input.risk_plan.state is RiskAssessmentState.INCOMPLETE:
            total_score = round(min(total_score, max_score * 0.54), 4)
        percentage = round((total_score / max_score) * 100.0, 4)
        grade = grade_for_percentage(percentage)
        warnings = self._warnings(scoring_input, components)
        return SetupScore(
            symbol=scoring_input.symbol,
            total_score=total_score,
            max_score=max_score,
            percentage=percentage,
            grade=grade,
            components=components,
            summary=f"{grade.value}: {percentage:.2f}% setup score",
            warnings=warnings,
            metadata={
                "entry_state": (
                    scoring_input.entry_trace.state.value if scoring_input.entry_trace is not None else None
                ),
                "risk_state": (
                    scoring_input.risk_plan.state.value if scoring_input.risk_plan is not None else None
                ),
                "checklist_status": (
                    scoring_input.checklist_result.overall_status.value
                    if scoring_input.checklist_result is not None
                    else None
                ),
                "alignment_score": (
                    scoring_input.alignment.alignment_score if scoring_input.alignment is not None else None
                ),
                "scanner_score": (
                    scoring_input.scanner_candidate.score if scoring_input.scanner_candidate is not None else None
                ),
                **dict(scoring_input.metadata),
                "aoi_gate_failed": self._aoi_gate_failed(scoring_input),
            },
        )

    def _trend_component(self, scoring_input: ScoringInput) -> ScoreComponent:
        alignment = scoring_input.alignment
        if alignment is None:
            return self._component(
                name="trend_alignment",
                category="trend",
                raw_score=0.0,
                weight=0.2,
                evidence_codes=(),
                reasons=("alignment_missing",),
                metadata={"alignment_score": None, "bias": None},
            )

        raw_score = min(max(alignment.alignment_score, 0), 3) / 3.0
        if alignment.bias is DirectionalBias.NEUTRAL:
            raw_score *= 0.5
        return self._component(
            name="trend_alignment",
            category="trend",
            raw_score=raw_score,
            weight=0.2,
            evidence_codes=(),
            reasons=(alignment.reason,),
            metadata={
                "alignment_score": alignment.alignment_score,
                "bias": alignment.bias.value,
            },
        )

    def _entry_component(self, scoring_input: ScoringInput) -> ScoreComponent:
        trace = scoring_input.entry_trace
        if trace is None:
            return self._component(
                name="entry_confirmation",
                category="entry",
                raw_score=0.0,
                weight=0.2,
                evidence_codes=(),
                reasons=("entry_trace_missing",),
            )

        state_score = {
            EntryState.ENTRY_READY: 1.0,
            EntryState.LONG_SETUP: 0.75,
            EntryState.SHORT_SETUP: 0.75,
            EntryState.WATCH: 0.35,
            EntryState.WAIT: 0.15,
            EntryState.INVALIDATED: 0.0,
        }[trace.state]
        support_count = sum(item.polarity is DecisionEvidencePolarity.SUPPORTS for item in trace.evidence)
        missing_count = sum(item.category is DecisionEvidenceCategory.MISSING_CONFIRMATION for item in trace.evidence)
        structure_or_entry_count = sum(
            item.category
            in {
                DecisionEvidenceCategory.STRUCTURE,
                DecisionEvidenceCategory.BOS,
                DecisionEvidenceCategory.CANDLE,
            }
            for item in trace.evidence
        )
        raw_score = max(0.0, state_score + min(support_count, 4) * 0.03 + min(structure_or_entry_count, 3) * 0.03 - missing_count * 0.12)
        raw_score = min(raw_score, 1.0)
        return self._component(
            name="entry_confirmation",
            category="entry",
            raw_score=raw_score,
            weight=0.2,
            evidence_codes=tuple(item.code.value for item in trace.evidence),
            reasons=trace.reasons or tuple(item.description for item in trace.evidence),
            metadata={
                "entry_state": trace.state.value,
                "direction": trace.direction.value,
                "confidence": trace.confidence,
                "missing_confirmations": len(trace.missing_confirmations),
            },
        )

    def _risk_component(self, scoring_input: ScoringInput) -> ScoreComponent:
        plan = scoring_input.risk_plan
        if plan is None:
            return self._component(
                name="risk_validity",
                category="risk",
                raw_score=0.0,
                weight=0.2,
                evidence_codes=(),
                reasons=("risk_plan_missing",),
            )

        state_score = {
            RiskAssessmentState.VALID: 0.75,
            RiskAssessmentState.NOT_APPLICABLE: 0.2,
            RiskAssessmentState.INCOMPLETE: 0.25,
            RiskAssessmentState.INVALID: 0.0,
        }[plan.state]
        rr_score = min((plan.risk_reward_ratio or 0.0) / 3.0, 0.25)
        warning_penalty = min(len(plan.warnings) * 0.1, 0.25)
        raw_score = min(max(state_score + rr_score - warning_penalty, 0.0), 1.0)
        return self._component(
            name="risk_validity",
            category="risk",
            raw_score=raw_score,
            weight=0.2,
            evidence_codes=tuple(item.code.value for item in plan.evidence),
            reasons=plan.reasons,
            metadata={
                "risk_state": plan.state.value,
                "risk_reward_ratio": plan.risk_reward_ratio,
                "risk_level": plan.risk_level.value if plan.risk_level is not None else None,
                "warning_count": len(plan.warnings),
            },
        )

    def _checklist_component(self, scoring_input: ScoringInput) -> ScoreComponent:
        result = scoring_input.checklist_result
        if result is None:
            return self._component(
                name="checklist_health",
                category="checklist",
                raw_score=0.0,
                weight=0.2,
                evidence_codes=(),
                reasons=("checklist_missing",),
            )

        total_items = max(len(result.items), 1)
        pass_ratio = result.pass_count / total_items
        penalty = (result.fail_count * 0.25 + result.missing_count * 0.15 + result.warning_count * 0.08) / total_items
        raw_score = min(max(pass_ratio - penalty, 0.0), 1.0)
        return self._component(
            name="checklist_health",
            category="checklist",
            raw_score=raw_score,
            weight=0.2,
            evidence_codes=tuple(code for item in result.items for code in item.evidence_codes),
            reasons=(result.summary,),
            metadata={
                "overall_status": result.overall_status.value,
                "pass_count": result.pass_count,
                "fail_count": result.fail_count,
                "warning_count": result.warning_count,
                "missing_count": result.missing_count,
            },
        )

    def _aoi_component(self, scoring_input: ScoringInput) -> ScoreComponent:
        trace = scoring_input.entry_trace
        if trace is None:
            return self._component(
                name="aoi_location_gate",
                category="aoi",
                raw_score=0.0,
                weight=0.2,
                evidence_codes=(),
                reasons=("aoi_entry_trace_missing",),
            )
        codes = {item.code for item in trace.evidence}
        if self._aoi_gate_failed(scoring_input):
            return self._component(
                name="aoi_location_gate",
                category="aoi",
                raw_score=0.0,
                weight=0.2,
                evidence_codes=tuple(item.code.value for item in trace.evidence if item.category is DecisionEvidenceCategory.AOI),
                reasons=tuple(item.description for item in trace.evidence if item.category is DecisionEvidenceCategory.AOI),
                metadata={"eligible": False},
            )
        location_support = codes.intersection(
            {
                DecisionEvidenceCode.AOI_LOCATION_INSIDE,
                DecisionEvidenceCode.AOI_LOCATION_REACTING,
                DecisionEvidenceCode.AOI_LOCATION_ENTRY_WINDOW,
            },
        )
        active_support = codes.intersection(
            {
                DecisionEvidenceCode.WEEKLY_AOI_ACTIVE,
                DecisionEvidenceCode.DAILY_AOI_ACTIVE,
            },
        )
        overlap_bonus = 0.1 if DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP in codes else 0.0
        raw_score = min(1.0, (0.45 if active_support else 0.0) + (0.45 if location_support else 0.0) + overlap_bonus)
        return self._component(
            name="aoi_location_gate",
            category="aoi",
            raw_score=raw_score,
            weight=0.2,
            evidence_codes=tuple(item.code.value for item in trace.evidence if item.category is DecisionEvidenceCategory.AOI),
            reasons=tuple(item.description for item in trace.evidence if item.category is DecisionEvidenceCategory.AOI) or ("aoi_evidence_missing",),
            metadata={
                "eligible": raw_score > 0.0,
                "overlap": DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP in codes,
            },
        )

    def _warnings(self, scoring_input: ScoringInput, components: tuple[ScoreComponent, ...]) -> tuple[str, ...]:
        warnings: list[str] = []
        if scoring_input.entry_trace is None:
            warnings.append("entry_trace_missing")
        elif scoring_input.entry_trace.state is EntryState.INVALIDATED:
            warnings.append("entry_invalidated")
        elif scoring_input.entry_trace.missing_confirmations:
            warnings.append("entry_missing_confirmations")
        if self._aoi_gate_failed(scoring_input):
            warnings.append("aoi_location_gate_failed")

        if scoring_input.risk_plan is None:
            warnings.append("risk_plan_missing")
        elif scoring_input.risk_plan.state is RiskAssessmentState.INCOMPLETE:
            warnings.append("risk_incomplete")
        elif scoring_input.risk_plan.state is RiskAssessmentState.INVALID:
            warnings.append("risk_invalid")

        if scoring_input.checklist_result is None:
            warnings.append("checklist_missing")
        elif scoring_input.checklist_result.overall_status is not ChecklistItemStatus.PASS:
            warnings.append("checklist_not_passing")

        for component in components:
            if component.raw_score < 0.4:
                warnings.append(f"{component.name}_weak")
        return tuple(dict.fromkeys(warnings))

    def _aoi_gate_failed(self, scoring_input: ScoringInput) -> bool:
        trace = scoring_input.entry_trace
        if trace is None:
            return True
        codes = {item.code for item in trace.evidence}
        return bool(
            codes.intersection(
                {
                    DecisionEvidenceCode.AOI_LOCATION_NOT_ELIGIBLE,
                    DecisionEvidenceCode.AOI_MOVED_AWAY,
                    DecisionEvidenceCode.AOI_DATA_MISSING,
                },
            ),
        )

    def _component(
        self,
        *,
        name: str,
        category: str,
        raw_score: float,
        weight: float,
        evidence_codes: tuple[str, ...],
        reasons: tuple[str, ...],
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> ScoreComponent:
        bounded_raw_score = min(max(raw_score, 0.0), 1.0)
        max_score = round(weight * 100.0, 4)
        return ScoreComponent(
            name=name,
            category=category,
            raw_score=round(bounded_raw_score, 4),
            weight=weight,
            weighted_score=round(bounded_raw_score * max_score, 4),
            max_score=max_score,
            evidence_codes=evidence_codes,
            reasons=reasons,
            metadata=metadata or {},
        )


def grade_for_percentage(percentage: float) -> ScoreGrade:
    if percentage >= 85.0:
        return ScoreGrade.A
    if percentage >= 70.0:
        return ScoreGrade.B
    if percentage >= 55.0:
        return ScoreGrade.C
    if percentage >= 40.0:
        return ScoreGrade.D
    return ScoreGrade.F
