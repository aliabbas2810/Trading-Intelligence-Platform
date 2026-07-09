from __future__ import annotations

from pathlib import Path

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
from backend.engines.risk import (
    RiskAssessmentState,
    RiskDirection,
    RiskEngine,
    RiskEvidenceCode,
    RiskInput,
    RiskLevel,
)
from backend.engines.structure import (
    StructureLabel,
    StructureSwing,
    SwingKind,
)
from backend.models import Candle, Timeframe


def test_long_valid_risk_plan() -> None:
    """Covers RISK-001, RISK-002, RISK-003, and TEST-001."""

    plan = RiskEngine().evaluate(
        RiskInput(
            entry_trace=entry_trace(EntryState.ENTRY_READY, EntryDirection.LONG),
            latest_candle=candle(open_price=104.0, close=105.0),
            structure_levels=(swing(StructureLabel.HL, 95.0),),
            minimum_risk_reward=2.0,
        ),
    )

    assert plan.direction is RiskDirection.LONG
    assert plan.state is RiskAssessmentState.VALID
    assert plan.entry_price == 105.0
    assert plan.stop_loss == 95.0
    assert plan.take_profit == 125.0
    assert plan.risk_reward_ratio == 2.0
    assert plan.risk_level is RiskLevel.MEDIUM


def test_short_valid_risk_plan() -> None:
    """Covers bearish RISK-001, RISK-002, RISK-003, and TEST-001."""

    plan = RiskEngine().evaluate(
        RiskInput(
            entry_trace=entry_trace(EntryState.ENTRY_READY, EntryDirection.SHORT),
            latest_candle=candle(open_price=101.0, close=100.0),
            structure_levels=(swing(StructureLabel.LH, 110.0),),
            minimum_risk_reward=3.0,
        ),
    )

    assert plan.direction is RiskDirection.SHORT
    assert plan.state is RiskAssessmentState.VALID
    assert plan.entry_price == 100.0
    assert plan.stop_loss == 110.0
    assert plan.take_profit == 70.0
    assert plan.risk_reward_ratio == 3.0
    assert plan.risk_level is RiskLevel.LOW


def test_wait_and_watch_are_not_applicable() -> None:
    """Covers RISK-004 and TEST-001."""

    engine = RiskEngine()

    wait_plan = engine.evaluate(RiskInput(entry_trace=entry_trace(EntryState.WAIT, EntryDirection.NONE)))
    watch_plan = engine.evaluate(RiskInput(entry_trace=entry_trace(EntryState.WATCH, EntryDirection.LONG)))

    assert wait_plan.state is RiskAssessmentState.NOT_APPLICABLE
    assert watch_plan.state is RiskAssessmentState.NOT_APPLICABLE
    assert wait_plan.direction is RiskDirection.NONE


def test_invalidated_entry_returns_invalid() -> None:
    """Covers RISK-004 and RISK-006."""

    plan = RiskEngine().evaluate(
        RiskInput(entry_trace=entry_trace(EntryState.INVALIDATED, EntryDirection.LONG)),
    )

    assert plan.state is RiskAssessmentState.INVALID
    assert plan.risk_level is RiskLevel.HIGH
    assert plan.warnings == ("entry_invalidated",)


def test_missing_stop_returns_incomplete() -> None:
    """Covers RISK-004 graceful missing-data handling."""

    plan = RiskEngine().evaluate(
        RiskInput(
            entry_trace=entry_trace(EntryState.ENTRY_READY, EntryDirection.LONG),
            latest_candle=candle(open_price=104.0, close=105.0),
            structure_levels=(),
        ),
    )

    assert plan.state is RiskAssessmentState.INCOMPLETE
    assert plan.entry_price == 105.0
    assert plan.stop_loss is None
    assert plan.warnings == ("missing_invalidation_level",)


def test_rr_calculation_is_deterministic() -> None:
    """Covers deterministic RISK-002 target and R:R calculation."""

    plan = RiskEngine().evaluate(
        RiskInput(
            entry_trace=entry_trace(EntryState.LONG_SETUP, EntryDirection.LONG),
            latest_candle=candle(open_price=100.0, close=100.0),
            structure_levels=(swing(StructureLabel.HL, 90.0),),
            minimum_risk_reward=2.5,
        ),
    )

    assert plan.take_profit == 125.0
    assert plan.risk_reward_ratio == 2.5
    assert RiskEvidenceCode.RISK_REWARD_CALCULATED in tuple(item.code for item in plan.evidence)


def test_long_uses_latest_relevant_hl_below_entry() -> None:
    """Regression: LONG stops must prefer the latest HL below entry."""

    plan = RiskEngine().evaluate(
        RiskInput(
            entry_trace=entry_trace(EntryState.ENTRY_READY, EntryDirection.LONG),
            latest_candle=candle(open_price=104.0, close=105.0),
            structure_levels=(
                swing(StructureLabel.HL, 90.0, close_time_ms=60_000),
                swing(StructureLabel.HL, 95.0, close_time_ms=120_000),
                swing(StructureLabel.HL, 110.0, close_time_ms=180_000),
            ),
            minimum_risk_reward=2.0,
        ),
    )

    assert plan.state is RiskAssessmentState.VALID
    assert plan.stop_loss == 95.0


def test_short_uses_latest_relevant_lh_above_entry() -> None:
    """Regression: SHORT stops must prefer the latest LH above entry."""

    plan = RiskEngine().evaluate(
        RiskInput(
            entry_trace=entry_trace(EntryState.ENTRY_READY, EntryDirection.SHORT),
            latest_candle=candle(open_price=101.0, close=100.0),
            structure_levels=(
                swing(StructureLabel.LH, 112.0, close_time_ms=60_000),
                swing(StructureLabel.LH, 108.0, close_time_ms=120_000),
                swing(StructureLabel.LH, 95.0, close_time_ms=180_000),
            ),
            minimum_risk_reward=2.0,
        ),
    )

    assert plan.state is RiskAssessmentState.VALID
    assert plan.stop_loss == 108.0


def test_risk_engine_does_not_recalculate_structure_trend_entry_scanner_or_ai_logic() -> None:
    """Covers RISK-006 no-recalculation constraint."""

    source = "\n".join(
        (
            Path("backend/engines/risk/engine.py").read_text(encoding="utf-8"),
            Path("backend/engines/risk/models.py").read_text(encoding="utf-8"),
        ),
    )

    forbidden_fragments = (
        "MarketStructureEngine",
        "TrendEngine",
        "EntrySignalEngine",
        "ScannerEngine",
        "AiDecisionEngine",
        ".add_candle(",
        ".add_event(",
        "score_candidate",
        "body_high =",
        "body_low =",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source


def entry_trace(state: EntryState, direction: EntryDirection) -> DecisionTrace:
    return DecisionTrace(
        state=state,
        direction=direction,
        confidence=0.8,
        evidence=(
            DecisionEvidence(
                code=DecisionEvidenceCode.SETUP_CONFIRMED,
                category=DecisionEvidenceCategory.STRUCTURE,
                timeframe=Timeframe.FIVE_MINUTE,
                polarity=DecisionEvidencePolarity.SUPPORTS,
                severity=DecisionEvidenceSeverity.INFO,
                description="test_entry_trace",
            ),
        ),
    )


def swing(label: StructureLabel, level: float, *, close_time_ms: int = 60_000) -> StructureSwing:
    return StructureSwing(
        symbol="BTCUSDT",
        timeframe=Timeframe.FIVE_MINUTE,
        kind=SwingKind.LOW if label in {StructureLabel.HL, StructureLabel.LL} else SwingKind.HIGH,
        label=label,
        level=level,
        candle_open_time_ms=0,
        candle_close_time_ms=close_time_ms,
    )


def candle(*, open_price: float, close: float) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=60_000,
        close_time_ms=120_000,
        open=open_price,
        high=max(open_price, close) + 1.0,
        low=min(open_price, close) - 1.0,
        close=close,
        volume=1.0,
    )
