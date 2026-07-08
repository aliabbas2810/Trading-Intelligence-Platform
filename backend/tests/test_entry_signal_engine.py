from __future__ import annotations

from pathlib import Path

from backend.api import StructureSnapshot
from backend.engines.entry import (
    DecisionEvidenceCategory,
    DecisionEvidenceCode,
    DecisionEvidencePolarity,
    DecisionEvidenceSeverity,
    DecisionTrace,
    EntryDirection,
    EntrySignalEngine,
    EntrySignalInput,
    EntryState,
)
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
from backend.models import Candle, Timeframe


def test_wait_on_weak_alignment() -> None:
    """Covers ENTRY-001, ENTRY-002, and TEST-001."""

    trace = EntrySignalEngine().evaluate(
        base_input(alignment=alignment(DirectionalBias.NEUTRAL, score=1)),
    )

    assert trace.state is EntryState.WAIT
    assert trace.direction is EntryDirection.NONE
    assert "alignment_weak_or_neutral" in trace.reasons
    assert trace.evidence[0].code is DecisionEvidenceCode.ALIGNMENT_WEAK_OR_NEUTRAL
    assert trace.evidence[0].polarity is DecisionEvidencePolarity.NEUTRAL


def test_watch_on_higher_timeframe_alignment_without_lower_confirmation() -> None:
    """Covers ENTRY-001 through ENTRY-003 and TEST-001."""

    trace = EntrySignalEngine().evaluate(
        base_input(
            alignment=alignment(DirectionalBias.BULLISH, score=3),
            trends=trend_set(TrendState.BULLISH),
            latest_candle=bullish_candle(),
        ),
    )

    assert trace.state is EntryState.WATCH
    assert trace.direction is EntryDirection.LONG
    assert "15m_structure" in trace.missing_confirmations
    assert "5m_structure" in trace.missing_confirmations
    assert any(
        item.code is DecisionEvidenceCode.MISSING_CONFIRMATION
        and item.category is DecisionEvidenceCategory.MISSING_CONFIRMATION
        for item in trace.evidence
    )


def test_long_setup_requires_15m_and_5m_bullish_structure() -> None:
    """Covers ENTRY-001, ENTRY-003, ENTRY-004, and TEST-001."""

    trace = EntrySignalEngine().evaluate(
        base_input(
            alignment=alignment(DirectionalBias.BULLISH, score=3),
            trends=trend_set(TrendState.BULLISH),
            structure_15m=bullish_structure(Timeframe.FIFTEEN_MINUTE),
            structure_5m=bullish_structure(Timeframe.FIVE_MINUTE),
            structure_1m=neutral_structure(Timeframe.ONE_MINUTE),
            latest_candle=bullish_candle(),
        ),
    )

    assert trace.state is EntryState.LONG_SETUP
    assert trace.direction is EntryDirection.LONG
    assert trace.missing_confirmations == ("1m_confirmation",)
    assert trace.trigger_timeframe is Timeframe.FIVE_MINUTE
    assert evidence_codes(trace) == (
        DecisionEvidenceCode.HIGHER_TIMEFRAMES_ALIGNED,
        DecisionEvidenceCode.FIFTEEN_MINUTE_STRUCTURE_CONFIRMATION,
        DecisionEvidenceCode.FIVE_MINUTE_STRUCTURE_CONFIRMATION,
        DecisionEvidenceCode.MISSING_CONFIRMATION,
    )


def test_short_setup_requires_15m_and_5m_bearish_structure() -> None:
    """Covers bearish ENTRY-001, ENTRY-003, ENTRY-004, and TEST-001."""

    trace = EntrySignalEngine().evaluate(
        base_input(
            alignment=alignment(DirectionalBias.BEARISH, score=3),
            trends=trend_set(TrendState.BEARISH),
            structure_15m=bearish_structure(Timeframe.FIFTEEN_MINUTE),
            structure_5m=bearish_structure(Timeframe.FIVE_MINUTE),
            structure_1m=neutral_structure(Timeframe.ONE_MINUTE),
            latest_candle=bearish_candle(),
        ),
    )

    assert trace.state is EntryState.SHORT_SETUP
    assert trace.direction is EntryDirection.SHORT
    assert trace.missing_confirmations == ("1m_confirmation",)


def test_entry_ready_requires_one_minute_confirmation() -> None:
    """Covers ENTRY-001, ENTRY-004, ENTRY-005, and TEST-001."""

    trace = EntrySignalEngine().evaluate(
        base_input(
            alignment=alignment(DirectionalBias.BULLISH, score=3),
            trends=trend_set(TrendState.BULLISH),
            structure_15m=bullish_structure(Timeframe.FIFTEEN_MINUTE),
            structure_5m=bullish_structure(Timeframe.FIVE_MINUTE),
            structure_1m=bullish_structure(Timeframe.ONE_MINUTE),
            latest_candle=bullish_candle(),
        ),
    )

    assert trace.state is EntryState.ENTRY_READY
    assert trace.direction is EntryDirection.LONG
    assert trace.confidence == 0.85
    assert trace.trigger_timeframe is Timeframe.ONE_MINUTE
    assert DecisionEvidenceCode.ONE_MINUTE_ENTRY_CONFIRMATION in evidence_codes(trace)
    assert "one_minute_trigger" in trace.reasons


def test_invalidated_on_opposing_bos() -> None:
    """Covers ENTRY-001, ENTRY-003, ENTRY-006, and TEST-001."""

    bearish_bos = bos(Timeframe.FIVE_MINUTE, BreakDirection.BEARISH)
    trace = EntrySignalEngine().evaluate(
        base_input(
            alignment=alignment(DirectionalBias.BULLISH, score=3),
            trends=trend_set(TrendState.BULLISH),
            structure_15m=bullish_structure(Timeframe.FIFTEEN_MINUTE),
            structure_5m=StructureSnapshot(swings=(), breaks_of_structure=(bearish_bos,)),
            structure_1m=bullish_structure(Timeframe.ONE_MINUTE),
            bos_events=(bearish_bos,),
            latest_candle=bullish_candle(),
        ),
    )

    assert trace.state is EntryState.INVALIDATED
    assert trace.direction is EntryDirection.LONG
    assert trace.invalidation_conditions == ("5m_bearish_bos",)
    invalidation = trace.evidence[-1]
    assert invalidation.code is DecisionEvidenceCode.OPPOSING_BOS_INVALIDATION
    assert invalidation.category is DecisionEvidenceCategory.INVALIDATION
    assert invalidation.severity is DecisionEvidenceSeverity.BLOCKING


def test_missing_data_handled_gracefully() -> None:
    """Covers missing-data behavior for ENTRY-001 through ENTRY-006."""

    trace = EntrySignalEngine().evaluate(EntrySignalInput(symbol="BTCUSDT"))

    assert trace.state is EntryState.WAIT
    assert trace.direction is EntryDirection.NONE
    assert "alignment" in trace.missing_confirmations
    assert "latest_candle" in trace.missing_confirmations
    assert all(item.metadata for item in trace.evidence if item.code is DecisionEvidenceCode.MISSING_CONFIRMATION)


def test_entry_engine_does_not_recalculate_structure_trend_scanner_or_ai_logic() -> None:
    """Covers ENTRY-006 no-recalculation constraint."""

    source = "\n".join(
        (
            Path("backend/engines/entry/engine.py").read_text(encoding="utf-8"),
            Path("backend/engines/entry/models.py").read_text(encoding="utf-8"),
        ),
    )

    forbidden_fragments = (
        "MarketStructureEngine",
        "TrendEngine",
        "ScannerEngine",
        "AiDecisionEngine",
        ".add_candle(",
        ".add_event(",
        "score_candidate",
        "detect",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source


def base_input(
    *,
    alignment: MultiTimeframeTrendResult | None = None,
    trends: dict[Timeframe, TrendUpdate] | None = None,
    structure_15m: StructureSnapshot | None = None,
    structure_5m: StructureSnapshot | None = None,
    structure_1m: StructureSnapshot | None = None,
    bos_events: tuple[BreakOfStructure, ...] = (),
    latest_candle: Candle | None = None,
) -> EntrySignalInput:
    trends = trends or {}
    return EntrySignalInput(
        symbol="BTCUSDT",
        trend_1w=trends.get(Timeframe.WEEKLY),
        trend_1d=trends.get(Timeframe.DAILY),
        trend_4h=trends.get(Timeframe.FOUR_HOUR),
        trend_2h=trends.get(Timeframe.TWO_HOUR),
        trend_1h=trends.get(Timeframe.ONE_HOUR),
        trend_30m=trends.get(Timeframe.THIRTY_MINUTE),
        structure_15m=structure_15m,
        structure_5m=structure_5m,
        structure_1m=structure_1m,
        bos_events=bos_events,
        latest_candle=latest_candle,
        alignment=alignment,
    )


def evidence_codes(trace: DecisionTrace) -> tuple[DecisionEvidenceCode, ...]:
    return tuple(item.code for item in trace.evidence)


def trend_set(state: TrendState) -> dict[Timeframe, TrendUpdate]:
    return {
        timeframe: trend(timeframe, state)
        for timeframe in (
            Timeframe.WEEKLY,
            Timeframe.DAILY,
            Timeframe.FOUR_HOUR,
            Timeframe.TWO_HOUR,
            Timeframe.ONE_HOUR,
            Timeframe.THIRTY_MINUTE,
        )
    }


def trend(timeframe: Timeframe, state: TrendState) -> TrendUpdate:
    return TrendUpdate(
        symbol="BTCUSDT",
        timeframe=timeframe,
        state=state,
        previous_state=None,
        strength=TrendStrength(confirming_structure_count=3),
        reason="test",
        event_time_ms=60_000,
    )


def alignment(bias: DirectionalBias, *, score: int) -> MultiTimeframeTrendResult:
    snapshots = tuple(
        TimeframeTrendSnapshot(
            symbol="BTCUSDT",
            timeframe=timeframe,
            state=TrendState.BULLISH if bias is DirectionalBias.BULLISH else TrendState.BEARISH,
            strength=TrendStrength(confirming_structure_count=3),
            event_time_ms=60_000,
        )
        for timeframe in (Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR)
        if bias is not DirectionalBias.NEUTRAL
    )
    return MultiTimeframeTrendResult(
        symbol="BTCUSDT",
        mode=MultiTimeframeMode.VOTING,
        bias=bias,
        alignment_score=score,
        required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        present_timeframes=tuple(snapshot.timeframe for snapshot in snapshots),
        missing_timeframes=(),
        snapshots=snapshots,
        reason="test",
    )


def bullish_structure(timeframe: Timeframe) -> StructureSnapshot:
    return StructureSnapshot(
        swings=(
            swing(timeframe, SwingKind.HIGH, StructureLabel.HH),
            swing(timeframe, SwingKind.LOW, StructureLabel.HL),
        ),
        breaks_of_structure=(bos(timeframe, BreakDirection.BULLISH),),
    )


def bearish_structure(timeframe: Timeframe) -> StructureSnapshot:
    return StructureSnapshot(
        swings=(
            swing(timeframe, SwingKind.HIGH, StructureLabel.LH),
            swing(timeframe, SwingKind.LOW, StructureLabel.LL),
        ),
        breaks_of_structure=(bos(timeframe, BreakDirection.BEARISH),),
    )


def neutral_structure(timeframe: Timeframe) -> StructureSnapshot:
    return StructureSnapshot(
        swings=(swing(timeframe, SwingKind.HIGH, StructureLabel.HH),),
        breaks_of_structure=(),
    )


def swing(timeframe: Timeframe, kind: SwingKind, label: StructureLabel) -> StructureSwing:
    return StructureSwing(
        symbol="BTCUSDT",
        timeframe=timeframe,
        kind=kind,
        label=label,
        level=100.0,
        candle_open_time_ms=0,
        candle_close_time_ms=60_000,
    )


def bos(timeframe: Timeframe, direction: BreakDirection) -> BreakOfStructure:
    return BreakOfStructure(
        symbol="BTCUSDT",
        timeframe=timeframe,
        direction=direction,
        broken_label=StructureLabel.HH if direction is BreakDirection.BULLISH else StructureLabel.LL,
        broken_level=100.0,
        candle_close=105.0 if direction is BreakDirection.BULLISH else 95.0,
        candle_open_time_ms=60_000,
        candle_close_time_ms=120_000,
    )


def bullish_candle() -> Candle:
    return candle(open_price=100.0, close=105.0)


def bearish_candle() -> Candle:
    return candle(open_price=105.0, close=100.0)


def candle(*, open_price: float, close: float) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=120_000,
        close_time_ms=180_000,
        open=open_price,
        high=max(open_price, close) + 1.0,
        low=min(open_price, close) - 1.0,
        close=close,
        volume=1.0,
    )
