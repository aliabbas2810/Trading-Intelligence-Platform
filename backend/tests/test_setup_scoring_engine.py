from __future__ import annotations

from pathlib import Path

from backend.engines.checklist import ChecklistEngine, ChecklistInput, ChecklistItemStatus
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
from backend.engines.risk import RiskEngine, RiskInput, RiskPlan
from backend.engines.scoring import ScoreComponent, ScoreGrade, ScoringInput, SetupScore, SetupScoringEngine
from backend.engines.structure import StructureLabel, StructureSwing, SwingKind
from backend.engines.trend import (
    DirectionalBias,
    MultiTimeframeMode,
    MultiTimeframeTrendResult,
    TimeframeTrendSnapshot,
    TrendState,
    TrendStrength,
)
from backend.models import Candle, Timeframe


def test_a_grade_setup_from_entry_ready_valid_risk_and_passing_checklist() -> None:
    """Covers SCORE-001, SCORE-002, SCORE-004, and TEST-001."""

    score = SetupScoringEngine().evaluate(scoring_input(entry_ready_trace()))

    assert score.grade is ScoreGrade.A
    assert score.percentage >= 85.0
    assert score.total_score <= score.max_score
    assert {component.name for component in score.components} == {
        "trend_alignment",
        "aoi_location_gate",
        "entry_confirmation",
        "risk_validity",
        "checklist_health",
    }


def test_watch_setup_scores_lower_due_to_missing_confirmation() -> None:
    """Covers SCORE-003 missing confirmation penalty."""

    score = SetupScoringEngine().evaluate(scoring_input(watch_trace(), include_stop=False))

    assert score.grade in {ScoreGrade.D, ScoreGrade.F}
    assert "entry_missing_confirmations" in score.warnings
    assert "risk_incomplete" not in score.warnings


def test_invalidated_setup_scores_very_low() -> None:
    """Covers SCORE-003 invalidated setup penalty."""

    score = SetupScoringEngine().evaluate(scoring_input(invalidated_trace(), include_stop=False))

    assert score.grade is ScoreGrade.F
    assert score.percentage < 40.0
    assert "entry_invalidated" in score.warnings


def test_incomplete_risk_is_penalized() -> None:
    """Covers SCORE-003 incomplete risk penalty."""

    score = SetupScoringEngine().evaluate(scoring_input(entry_ready_trace(), include_stop=False))

    assert score.grade in {ScoreGrade.C, ScoreGrade.D}
    assert "risk_incomplete" in score.warnings
    risk_component = component_by_name(score, "risk_validity")
    assert risk_component.raw_score < 0.5


def test_checklist_failures_are_penalized() -> None:
    """Covers SCORE-003 checklist failure penalty."""

    checklist = ChecklistEngine().evaluate(
        ChecklistInput(
            symbol="BTCUSDT",
            entry_trace=invalidated_trace(),
            risk_plan=RiskEngine().evaluate(RiskInput(entry_trace=invalidated_trace())),
            alignment=bullish_alignment(),
        ),
    )
    score = SetupScoringEngine().evaluate(
        ScoringInput(
            symbol="BTCUSDT",
            entry_trace=entry_ready_trace(),
            risk_plan=valid_risk_plan(entry_ready_trace()),
            checklist_result=checklist,
            alignment=bullish_alignment(),
        ),
    )

    assert checklist.overall_status is ChecklistItemStatus.FAIL
    assert "checklist_not_passing" in score.warnings
    assert component_by_name(score, "checklist_health").raw_score < 0.8


def test_component_scores_are_deterministic() -> None:
    """Covers deterministic SCORE-004 component scoring."""

    engine = SetupScoringEngine()
    setup_input = scoring_input(entry_ready_trace())

    first = engine.evaluate(setup_input)
    second = engine.evaluate(setup_input)

    assert first.total_score == second.total_score
    assert first.percentage == second.percentage
    assert first.grade is second.grade
    assert tuple(component.weighted_score for component in first.components) == tuple(
        component.weighted_score for component in second.components
    )


def test_setup_scoring_engine_does_not_recalculate_structure_trend_entry_risk_checklist_or_ai_logic() -> None:
    """Covers SCORE-006 no-recalculation constraint."""

    source = "\n".join(
        (
            Path("backend/engines/scoring/engine.py").read_text(encoding="utf-8"),
            Path("backend/engines/scoring/models.py").read_text(encoding="utf-8"),
        ),
    )

    forbidden_fragments = (
        "MarketStructureEngine",
        "TrendEngine",
        "EntrySignalEngine",
        "RiskEngine",
        "ChecklistEngine",
        "ScannerEngine",
        "AiDecisionEngine",
        ".add_candle(",
        ".add_event(",
        "checklist_engine.evaluate",
        "risk_engine.evaluate",
        "body_high =",
        "body_low =",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source


def scoring_input(trace: DecisionTrace, *, include_stop: bool = True) -> ScoringInput:
    risk_plan = valid_risk_plan(trace) if include_stop else RiskEngine().evaluate(
        RiskInput(entry_trace=trace, latest_candle=candle(), structure_levels=()),
    )
    checklist = ChecklistEngine().evaluate(
        ChecklistInput(
            symbol="BTCUSDT",
            entry_trace=trace,
            risk_plan=risk_plan,
            alignment=bullish_alignment(),
        ),
    )
    return ScoringInput(
        symbol="BTCUSDT",
        entry_trace=trace,
        risk_plan=risk_plan,
        checklist_result=checklist,
        alignment=bullish_alignment(),
    )


def valid_risk_plan(trace: DecisionTrace) -> RiskPlan:
    return RiskEngine().evaluate(
        RiskInput(
            entry_trace=trace,
            latest_candle=candle(),
            structure_levels=(swing(),),
            minimum_risk_reward=3.0,
        ),
    )


def component_by_name(score: SetupScore, name: str) -> ScoreComponent:
    for component in score.components:
        if component.name == name:
            return component
    raise AssertionError(f"missing component {name}")


def entry_ready_trace() -> DecisionTrace:
    return DecisionTrace(
        state=EntryState.ENTRY_READY,
        direction=EntryDirection.LONG,
        confidence=0.85,
        evidence=(
            evidence(
                DecisionEvidenceCode.HIGHER_TIMEFRAMES_ALIGNED,
                DecisionEvidenceCategory.ALIGNMENT,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "higher_timeframes_aligned",
            ),
            *aoi_support_evidence(),
            evidence(
                DecisionEvidenceCode.FIFTEEN_MINUTE_STRUCTURE_CONFIRMATION,
                DecisionEvidenceCategory.STRUCTURE,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "15m_structure_confirmation",
                timeframe=Timeframe.FIFTEEN_MINUTE,
            ),
            evidence(
                DecisionEvidenceCode.FIVE_MINUTE_STRUCTURE_CONFIRMATION,
                DecisionEvidenceCategory.STRUCTURE,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "5m_structure_confirmation",
                timeframe=Timeframe.FIVE_MINUTE,
            ),
            evidence(
                DecisionEvidenceCode.ONE_MINUTE_ENTRY_CONFIRMATION,
                DecisionEvidenceCategory.CANDLE,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "one_minute_trigger",
                timeframe=Timeframe.ONE_MINUTE,
            ),
        ),
        trigger_timeframe=Timeframe.ONE_MINUTE,
    )


def watch_trace() -> DecisionTrace:
    return DecisionTrace(
        state=EntryState.WATCH,
        direction=EntryDirection.LONG,
        confidence=0.35,
        evidence=(
            evidence(
                DecisionEvidenceCode.HIGHER_TIMEFRAMES_ALIGNED,
                DecisionEvidenceCategory.ALIGNMENT,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "higher_timeframes_aligned",
            ),
            *aoi_support_evidence(),
            evidence(
                DecisionEvidenceCode.MISSING_CONFIRMATION,
                DecisionEvidenceCategory.MISSING_CONFIRMATION,
                DecisionEvidencePolarity.MISSING,
                DecisionEvidenceSeverity.WARNING,
                "1m_confirmation",
                metadata={"missing_key": "1m_confirmation"},
            ),
        ),
    )


def invalidated_trace() -> DecisionTrace:
    return DecisionTrace(
        state=EntryState.INVALIDATED,
        direction=EntryDirection.LONG,
        confidence=0.0,
        evidence=(
            evidence(
                DecisionEvidenceCode.HIGHER_TIMEFRAMES_ALIGNED,
                DecisionEvidenceCategory.ALIGNMENT,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "higher_timeframes_aligned",
            ),
            *aoi_support_evidence(),
            evidence(
                DecisionEvidenceCode.OPPOSING_BOS_INVALIDATION,
                DecisionEvidenceCategory.INVALIDATION,
                DecisionEvidencePolarity.OPPOSES,
                DecisionEvidenceSeverity.BLOCKING,
                "lower_timeframe_invalidation",
            ),
        ),
    )


def aoi_support_evidence() -> tuple[DecisionEvidence, ...]:
    return (
        evidence(
            DecisionEvidenceCode.WEEKLY_AOI_ACTIVE,
            DecisionEvidenceCategory.AOI,
            DecisionEvidencePolarity.SUPPORTS,
            DecisionEvidenceSeverity.INFO,
            "weekly_aoi_active",
            timeframe=Timeframe.WEEKLY,
        ),
        evidence(
            DecisionEvidenceCode.AOI_LOCATION_INSIDE,
            DecisionEvidenceCategory.AOI,
            DecisionEvidencePolarity.SUPPORTS,
            DecisionEvidenceSeverity.INFO,
            "aoi_location_inside",
            timeframe=Timeframe.WEEKLY,
        ),
    )


def evidence(
    code: DecisionEvidenceCode,
    category: DecisionEvidenceCategory,
    polarity: DecisionEvidencePolarity,
    severity: DecisionEvidenceSeverity,
    description: str,
    *,
    timeframe: Timeframe | None = None,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> DecisionEvidence:
    return DecisionEvidence(
        code=code,
        category=category,
        timeframe=timeframe,
        polarity=polarity,
        severity=severity,
        description=description,
        metadata=metadata or {},
    )


def bullish_alignment() -> MultiTimeframeTrendResult:
    snapshot = TimeframeTrendSnapshot(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        state=TrendState.BULLISH,
        strength=TrendStrength(confirming_structure_count=3),
        event_time_ms=120_000,
    )
    return MultiTimeframeTrendResult(
        symbol="BTCUSDT",
        mode=MultiTimeframeMode.VOTING,
        bias=DirectionalBias.BULLISH,
        alignment_score=3,
        required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        present_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        missing_timeframes=(),
        snapshots=(snapshot,),
        reason="alignment-test",
    )


def swing() -> StructureSwing:
    return StructureSwing(
        symbol="BTCUSDT",
        timeframe=Timeframe.FIVE_MINUTE,
        kind=SwingKind.LOW,
        label=StructureLabel.HL,
        level=95.0,
        candle_open_time_ms=0,
        candle_close_time_ms=120_000,
    )


def candle() -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=120_000,
        close_time_ms=180_000,
        open=104.0,
        high=106.0,
        low=94.0,
        close=105.0,
        volume=1.0,
    )
