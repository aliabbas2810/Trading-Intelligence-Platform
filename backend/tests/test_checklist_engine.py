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
from backend.engines.risk import RiskAssessmentState, RiskEngine, RiskInput, RiskPlan
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


def test_checklist_from_entry_ready_and_valid_risk() -> None:
    """Covers CHECKLIST-001, CHECKLIST-002, CHECKLIST-003, CHECKLIST-004, and TEST-001."""

    result = ChecklistEngine().evaluate(
        ChecklistInput(
            symbol="BTCUSDT",
            entry_trace=entry_ready_trace(),
            risk_plan=valid_long_risk_plan(),
            alignment=bullish_alignment(),
        ),
    )

    assert result.symbol == "BTCUSDT"
    assert result.overall_status is ChecklistItemStatus.PASS
    assert result.fail_count == 0
    assert result.missing_count == 0
    assert result.pass_count > 0
    assert any(item.category.value == "RISK_VALIDATION" for item in result.items)
    assert "PASS:" in result.summary


def test_checklist_from_watch_with_missing_confirmations() -> None:
    """Covers CHECKLIST-002 missing confirmation conversion."""

    result = ChecklistEngine().evaluate(
        ChecklistInput(
            symbol="BTCUSDT",
            entry_trace=watch_trace(),
            risk_plan=RiskEngine().evaluate(RiskInput(entry_trace=watch_trace())),
            alignment=bullish_alignment(),
        ),
    )

    assert result.overall_status is ChecklistItemStatus.MISSING
    assert result.missing_count >= 1
    assert any(item.status is ChecklistItemStatus.MISSING for item in result.items)
    assert any(item.description == "1m_confirmation" for item in result.items)


def test_checklist_from_invalidated_entry() -> None:
    """Covers CHECKLIST-002 invalidation conversion."""

    trace = invalidated_trace()
    result = ChecklistEngine().evaluate(
        ChecklistInput(
            symbol="BTCUSDT",
            entry_trace=trace,
            risk_plan=RiskEngine().evaluate(RiskInput(entry_trace=trace)),
            alignment=bullish_alignment(),
        ),
    )

    assert result.overall_status is ChecklistItemStatus.FAIL
    assert result.fail_count >= 1
    assert any(item.category.value == "INVALIDATION" and item.status is ChecklistItemStatus.FAIL for item in result.items)


def test_checklist_from_incomplete_risk() -> None:
    """Covers CHECKLIST-003 incomplete risk conversion."""

    plan = RiskEngine().evaluate(
        RiskInput(
            entry_trace=entry_ready_trace(),
            latest_candle=candle(),
            structure_levels=(),
        ),
    )
    result = ChecklistEngine().evaluate(
        ChecklistInput(
            symbol="BTCUSDT",
            entry_trace=entry_ready_trace(),
            risk_plan=plan,
            alignment=bullish_alignment(),
        ),
    )

    assert plan.state is RiskAssessmentState.INCOMPLETE
    assert result.overall_status in {ChecklistItemStatus.FAIL, ChecklistItemStatus.MISSING}
    assert result.missing_count >= 1
    assert any(item.description == "risk_state_incomplete" for item in result.items)


def test_summary_counts_are_deterministic() -> None:
    """Covers CHECKLIST-004 deterministic counts and summary."""

    checklist_input = ChecklistInput(
        symbol="BTCUSDT",
        entry_trace=entry_ready_trace(),
        risk_plan=valid_long_risk_plan(),
        alignment=bullish_alignment(),
    )

    first = ChecklistEngine().evaluate(checklist_input)
    second = ChecklistEngine().evaluate(checklist_input)

    assert first.pass_count == second.pass_count
    assert first.fail_count == second.fail_count
    assert first.warning_count == second.warning_count
    assert first.missing_count == second.missing_count
    assert first.summary == second.summary


def test_missing_entry_or_risk_inputs_are_graceful() -> None:
    """Covers CHECKLIST-005 graceful missing-input handling."""

    result = ChecklistEngine().evaluate(ChecklistInput(symbol="BTCUSDT"))

    assert result.overall_status is ChecklistItemStatus.MISSING
    assert result.missing_count >= 2
    assert {"entry_trace_missing", "risk_plan_missing"}.issubset({item.description for item in result.items})


def test_checklist_engine_does_not_recalculate_structure_trend_entry_risk_scanner_or_ai_logic() -> None:
    """Covers CHECKLIST-006 no-recalculation constraint."""

    source = "\n".join(
        (
            Path("backend/engines/checklist/engine.py").read_text(encoding="utf-8"),
            Path("backend/engines/checklist/models.py").read_text(encoding="utf-8"),
        ),
    )

    forbidden_fragments = (
        "MarketStructureEngine",
        "TrendEngine",
        "EntrySignalEngine",
        "RiskEngine",
        "ScannerEngine",
        "AiDecisionEngine",
        ".add_candle(",
        ".add_event(",
        "score_candidate",
        "risk_reward =",
        "body_high =",
        "body_low =",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source


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
            evidence(
                DecisionEvidenceCode.FIFTEEN_MINUTE_STRUCTURE_CONFIRMATION,
                DecisionEvidenceCategory.STRUCTURE,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "15m_structure_confirmation",
                timeframe=Timeframe.FIFTEEN_MINUTE,
            ),
            evidence(
                DecisionEvidenceCode.WEEKLY_AOI_ACTIVE,
                DecisionEvidenceCategory.AOI,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "weekly_aoi_active",
                timeframe=Timeframe.WEEKLY,
            ),
            evidence(
                DecisionEvidenceCode.DAILY_AOI_ACTIVE,
                DecisionEvidenceCategory.AOI,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "daily_aoi_active",
                timeframe=Timeframe.DAILY,
            ),
            evidence(
                DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP,
                DecisionEvidenceCategory.AOI,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "weekly_daily_aoi_overlap",
            ),
            evidence(
                DecisionEvidenceCode.AOI_LOCATION_INSIDE,
                DecisionEvidenceCategory.AOI,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                "aoi_location_inside",
                timeframe=Timeframe.DAILY,
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
            evidence(
                DecisionEvidenceCode.OPPOSING_BOS_INVALIDATION,
                DecisionEvidenceCategory.INVALIDATION,
                DecisionEvidencePolarity.OPPOSES,
                DecisionEvidenceSeverity.BLOCKING,
                "lower_timeframe_invalidation",
                timeframe=Timeframe.FIVE_MINUTE,
            ),
        ),
    )


def valid_long_risk_plan() -> RiskPlan:
    return RiskEngine().evaluate(
        RiskInput(
            entry_trace=entry_ready_trace(),
            latest_candle=candle(),
            structure_levels=(swing(),),
            minimum_risk_reward=2.0,
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
