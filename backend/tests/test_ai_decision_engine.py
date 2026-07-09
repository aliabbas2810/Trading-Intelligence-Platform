from __future__ import annotations

from pathlib import Path

import pytest

from backend.api import StructureSnapshot, TrendSnapshot
from backend.engines.ai import (
    AiDecisionContextBuilder,
    AiDecisionEngine,
    AiDecisionInput,
    AiDecisionOutput,
    AiRecommendation,
    AiRiskAssessment,
    AiRiskSeverity,
    RuleBasedMockAiDecisionProvider,
)
from backend.engines.checklist import ChecklistItemStatus
from backend.engines.entry import EntryDirection, EntryState
from backend.engines.risk import RiskAssessmentState
from backend.engines.scanner import SetupCandidate
from backend.engines.scoring import ScoreGrade
from backend.engines.structure import (
    BreakDirection,
    BreakOfStructure,
    StructureLabel,
    StructureSwing,
    SwingKind,
)
from backend.engines.trend import (
    DirectionalBias,
    MultiTimeframeMode,
    MultiTimeframeTrendResult,
    TimeframeTrendSnapshot,
    TrendState,
    TrendStrength,
    TrendUpdate,
)
from backend.models import Timeframe


def trend_update(symbol: str = "BTCUSDT", state: TrendState = TrendState.BULLISH) -> TrendUpdate:
    return TrendUpdate(
        symbol=symbol,
        timeframe=Timeframe.FOUR_HOUR,
        state=state,
        previous_state=None,
        strength=TrendStrength(confirming_structure_count=3),
        reason="test",
        event_time_ms=1_000,
    )


def timeframe_snapshot(timeframe: Timeframe, state: TrendState) -> TimeframeTrendSnapshot:
    return TimeframeTrendSnapshot(
        symbol="BTCUSDT",
        timeframe=timeframe,
        state=state,
        strength=TrendStrength(confirming_structure_count=2),
        event_time_ms=1_000,
    )


def alignment(
    bias: DirectionalBias = DirectionalBias.BULLISH,
    score: int = 3,
) -> MultiTimeframeTrendResult:
    snapshots = (
        timeframe_snapshot(Timeframe.WEEKLY, TrendState.BULLISH),
        timeframe_snapshot(Timeframe.DAILY, TrendState.BULLISH),
        timeframe_snapshot(Timeframe.FOUR_HOUR, TrendState.BULLISH),
    )
    return MultiTimeframeTrendResult(
        symbol="BTCUSDT",
        mode=MultiTimeframeMode.VOTING,
        bias=bias,
        alignment_score=score,
        required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        present_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        missing_timeframes=(),
        snapshots=snapshots,
        reason="test",
    )


def setup_candidate(
    bias: DirectionalBias = DirectionalBias.BULLISH,
    score: float = 44.0,
) -> SetupCandidate:
    return SetupCandidate(
        symbol="BTCUSDT",
        bias=bias,
        score=score,
        alignment_score=3,
        trend_state=TrendState.BULLISH,
        trend_strength=3,
        has_structure=True,
        has_bos=True,
        latest_price=101.0,
        reasons=("alignment", "trend_strength", "structure", "bos"),
    )


def structure_snapshot() -> StructureSnapshot:
    swing = StructureSwing(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        kind=SwingKind.HIGH,
        label=StructureLabel.HH,
        level=100.0,
        candle_open_time_ms=0,
        candle_close_time_ms=1_000,
    )
    bos = BreakOfStructure(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        direction=BreakDirection.BULLISH,
        broken_label=StructureLabel.HH,
        broken_level=100.0,
        candle_close=101.0,
        candle_open_time_ms=1_000,
        candle_close_time_ms=2_000,
    )
    return StructureSnapshot(swings=(swing,), breaks_of_structure=(bos,))


def decision_input() -> AiDecisionInput:
    return AiDecisionInput(
        symbol="BTCUSDT",
        timeframe_states=alignment().snapshots,
        alignment=alignment(),
        setup_candidate=setup_candidate(),
        latest_structure=structure_snapshot(),
        latest_trend=TrendSnapshot(update=trend_update()),
        entry_signal="pullback-confirmation-placeholder",
        risk_reward="2R-placeholder",
    )


def intelligence_decision_input(
    *,
    entry_state: EntryState = EntryState.ENTRY_READY,
    entry_direction: EntryDirection = EntryDirection.LONG,
    risk_state: RiskAssessmentState = RiskAssessmentState.VALID,
    checklist_status: ChecklistItemStatus = ChecklistItemStatus.PASS,
    setup_grade: ScoreGrade = ScoreGrade.A,
    setup_score_percentage: float = 100.0,
) -> AiDecisionInput:
    return AiDecisionInput(
        symbol="BTCUSDT",
        timeframe_states=alignment().snapshots,
        alignment=alignment(),
        latest_structure=structure_snapshot(),
        latest_trend=TrendSnapshot(update=trend_update()),
        entry_signal=f"{entry_state.value}:{entry_direction.value}",
        risk_reward=f"risk_state={risk_state.value};rr=2.0;score={setup_grade.value}:{setup_score_percentage:.2f}",
        entry_state=entry_state,
        entry_direction=entry_direction,
        risk_state=risk_state,
        checklist_status=checklist_status,
        setup_grade=setup_grade,
        setup_score_percentage=setup_score_percentage,
        risk_reward_ratio=2.0,
    )


def test_context_builder_uses_structured_facts_only() -> None:
    """Covers FR-1001, FR-1002, and TEST-001."""

    context = AiDecisionContextBuilder().build(decision_input())

    assert context.symbol == "BTCUSDT"
    assert "alignment_bias=bullish" in context.facts
    assert "setup_score=44.00" in context.facts
    assert "structure_swings=1" in context.facts
    assert "Do not calculate candles, structure, trend, scanner score, or risk metrics." in context.prompt


def test_context_builder_includes_trading_intelligence_facts() -> None:
    """Covers INTEL-004 structured AI context."""

    context = AiDecisionContextBuilder().build(intelligence_decision_input())

    assert "entry_state=ENTRY_READY" in context.facts
    assert "entry_direction=LONG" in context.facts
    assert "risk_state=VALID" in context.facts
    assert "checklist_status=PASS" in context.facts
    assert "setup_grade=A" in context.facts
    assert "setup_score_percentage=100.00" in context.facts
    assert "risk_reward_ratio=2.0000" in context.facts


def test_mock_provider_generates_structured_long_decision() -> None:
    """Covers FR-1002, FR-1003, FR-1004, FR-1005, and TEST-001."""

    output = RuleBasedMockAiDecisionProvider().generate_decision(decision_input())

    assert output.recommendation is AiRecommendation.CONSIDER_LONG
    assert output.confidence == 0.64
    assert output.risk_assessment.severity is AiRiskSeverity.LOW
    assert output.provider == "rule_based_mock"
    assert [reason.category for reason in output.reasons] == ["alignment", "scanner", "trend"]


def test_mock_provider_generates_high_confidence_for_valid_long_intelligence() -> None:
    """Covers INTEL-004 consistency for ENTRY_READY + VALID + PASS + A/B."""

    output = RuleBasedMockAiDecisionProvider().generate_decision(intelligence_decision_input())

    assert output.recommendation is AiRecommendation.CONSIDER_LONG
    assert 0.8 <= output.confidence <= 0.95
    assert output.risk_assessment.severity is AiRiskSeverity.LOW
    assert {reason.category for reason in output.reasons} >= {
        "entry",
        "risk",
        "checklist",
        "setup_score",
    }


def test_mock_provider_avoids_invalid_intelligence_setup() -> None:
    """Invalid risk/checklist failures should not produce a long recommendation."""

    output = RuleBasedMockAiDecisionProvider().generate_decision(
        intelligence_decision_input(
            risk_state=RiskAssessmentState.INVALID,
            checklist_status=ChecklistItemStatus.FAIL,
            setup_grade=ScoreGrade.F,
            setup_score_percentage=20.0,
        ),
    )

    assert output.recommendation is AiRecommendation.AVOID
    assert output.confidence == 0.2
    assert output.risk_assessment.severity is AiRiskSeverity.HIGH


def test_mock_provider_keeps_watch_state_as_watch() -> None:
    """WATCH setup should stay watch even with partial context supplied."""

    output = RuleBasedMockAiDecisionProvider().generate_decision(
        intelligence_decision_input(
            entry_state=EntryState.WATCH,
            entry_direction=EntryDirection.NONE,
            risk_state=RiskAssessmentState.NOT_APPLICABLE,
            checklist_status=ChecklistItemStatus.MISSING,
            setup_grade=ScoreGrade.D,
            setup_score_percentage=45.0,
        ),
    )

    assert output.recommendation is AiRecommendation.WATCH
    assert output.confidence == 0.45


def test_engine_calls_provider_and_validates_symbol_consistency() -> None:
    """Covers FR-1006 provider interface and TEST-001."""

    engine = AiDecisionEngine(RuleBasedMockAiDecisionProvider())

    output = engine.generate_decision(decision_input())

    assert output.symbol == "BTCUSDT"
    assert output.recommendation is AiRecommendation.CONSIDER_LONG

    with pytest.raises(ValueError, match="alignment symbol"):
        engine.generate_decision(
            AiDecisionInput(
                symbol="ETHUSDT",
                alignment=alignment(),
            ),
        )


def test_structured_output_validation_rejects_invalid_confidence() -> None:
    """Covers FR-1003 output validation and TEST-001."""

    with pytest.raises(ValueError, match="confidence"):
        AiDecisionOutput(
            symbol="BTCUSDT",
            recommendation=AiRecommendation.WATCH,
            confidence=1.2,
            explanation="invalid",
            risk_assessment=AiRiskAssessment(
                severity=AiRiskSeverity.LOW,
                risks=("test risk",),
            ),
            reasons=RuleBasedMockAiDecisionProvider().generate_decision(decision_input()).reasons,
            provider="test",
        )


def test_missing_data_returns_avoid_with_high_risk() -> None:
    """Covers missing data handling, FR-1004, FR-1005, and TEST-001."""

    output = AiDecisionEngine(RuleBasedMockAiDecisionProvider()).generate_decision(
        AiDecisionInput(symbol="BTCUSDT"),
    )

    assert output.recommendation is AiRecommendation.AVOID
    assert output.confidence == 0.1
    assert output.risk_assessment.severity is AiRiskSeverity.HIGH
    assert output.reasons[0].category == "missing_data"


def test_ai_engine_does_not_recalculate_deterministic_logic() -> None:
    """Covers no-recalculation constraint and TEST-001."""

    ai_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("backend/engines/ai").glob("*.py")
        if path.name != "__init__.py"
    )

    assert "MarketStructureEngine" not in ai_sources
    assert "TrendEngine" not in ai_sources
    assert "ScannerEngine" not in ai_sources
    assert "score_candidate" not in ai_sources
    assert ".add_candle(" not in ai_sources
    assert ".add_event(" not in ai_sources
