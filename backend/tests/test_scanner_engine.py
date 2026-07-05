from __future__ import annotations

from pathlib import Path

from backend.core import EventBus
from backend.engines.scanner import (
    ScannerCompletedEvent,
    ScannerEngine,
    SetupCandidateFoundEvent,
    SymbolScanInput,
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


def trend(symbol: str, state: TrendState, strength: int) -> TrendUpdate:
    return TrendUpdate(
        symbol=symbol,
        timeframe=Timeframe.FOUR_HOUR,
        state=state,
        previous_state=None,
        strength=TrendStrength(confirming_structure_count=strength),
        reason="test",
        event_time_ms=1_000,
    )


def alignment(symbol: str, bias: DirectionalBias, score: int) -> MultiTimeframeTrendResult:
    snapshot = TimeframeTrendSnapshot(
        symbol=symbol,
        timeframe=Timeframe.FOUR_HOUR,
        state=trend_state_for_bias(bias),
        strength=TrendStrength(confirming_structure_count=score),
        event_time_ms=1_000,
    )
    return MultiTimeframeTrendResult(
        symbol=symbol,
        mode=MultiTimeframeMode.VOTING,
        bias=bias,
        alignment_score=score,
        required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        present_timeframes=(Timeframe.FOUR_HOUR,),
        missing_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY),
        snapshots=(snapshot,),
        reason="test",
    )


def swing(symbol: str) -> StructureSwing:
    return StructureSwing(
        symbol=symbol,
        timeframe=Timeframe.FOUR_HOUR,
        kind=SwingKind.HIGH,
        label=StructureLabel.HH,
        level=100.0,
        candle_open_time_ms=0,
        candle_close_time_ms=1_000,
    )


def bos(symbol: str) -> BreakOfStructure:
    return BreakOfStructure(
        symbol=symbol,
        timeframe=Timeframe.FOUR_HOUR,
        direction=BreakDirection.BULLISH,
        broken_label=StructureLabel.HH,
        broken_level=100.0,
        candle_close=101.0,
        candle_open_time_ms=1_000,
        candle_close_time_ms=2_000,
    )


def candle(symbol: str, close: float) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=Timeframe.FOUR_HOUR,
        open_time_ms=0,
        close_time_ms=1_000,
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        volume=10.0,
    )


def test_scanner_ranks_multiple_symbols_by_score() -> None:
    """Covers FR-901, FR-903, and TEST-001."""

    summary = ScannerEngine().scan(
        [
            SymbolScanInput(
                symbol="ETHUSDT",
                trend=trend("ETHUSDT", TrendState.BULLISH, 1),
                alignment=alignment("ETHUSDT", DirectionalBias.BULLISH, 2),
            ),
            SymbolScanInput(
                symbol="BTCUSDT",
                trend=trend("BTCUSDT", TrendState.BULLISH, 3),
                alignment=alignment("BTCUSDT", DirectionalBias.BULLISH, 3),
                structure_swings=(swing("BTCUSDT"),),
                breaks_of_structure=(bos("BTCUSDT"),),
                latest_candle=candle("BTCUSDT", 101.0),
            ),
        ],
    )

    assert [candidate.symbol for candidate in summary.candidates] == ["BTCUSDT", "ETHUSDT"]
    assert summary.candidates[0].score == 44.0
    assert summary.candidates[0].latest_price == 101.0


def test_scanner_filters_by_bias_alignment_and_score() -> None:
    """Covers FR-904, FR-905, and TEST-001."""

    summary = ScannerEngine().scan(
        [
            SymbolScanInput(
                symbol="BTCUSDT",
                trend=trend("BTCUSDT", TrendState.BULLISH, 3),
                alignment=alignment("BTCUSDT", DirectionalBias.BULLISH, 3),
            ),
            SymbolScanInput(
                symbol="ETHUSDT",
                trend=trend("ETHUSDT", TrendState.BEARISH, 5),
                alignment=alignment("ETHUSDT", DirectionalBias.BEARISH, 3),
            ),
            SymbolScanInput(
                symbol="SOLUSDT",
                trend=trend("SOLUSDT", TrendState.BULLISH, 0),
                alignment=alignment("SOLUSDT", DirectionalBias.BULLISH, 1),
            ),
        ],
        bias=DirectionalBias.BULLISH,
        minimum_alignment_score=2,
        minimum_setup_score=30.0,
    )

    assert [candidate.symbol for candidate in summary.candidates] == ["BTCUSDT"]
    excluded = {result.symbol: result.excluded_reasons for result in summary.results}
    assert excluded["ETHUSDT"] == ("bias_filter",)
    assert excluded["SOLUSDT"] == ("alignment_filter", "score_filter")


def test_scanner_tie_breaks_by_symbol() -> None:
    """Covers deterministic ranking for FR-903 and TEST-001."""

    summary = ScannerEngine().scan(
        [
            SymbolScanInput(
                symbol="SOLUSDT",
                trend=trend("SOLUSDT", TrendState.BULLISH, 1),
                alignment=alignment("SOLUSDT", DirectionalBias.BULLISH, 2),
            ),
            SymbolScanInput(
                symbol="ADAUSDT",
                trend=trend("ADAUSDT", TrendState.BULLISH, 1),
                alignment=alignment("ADAUSDT", DirectionalBias.BULLISH, 2),
            ),
        ],
    )

    assert [candidate.symbol for candidate in summary.candidates] == ["ADAUSDT", "SOLUSDT"]


def test_scanner_handles_missing_data_without_crashing() -> None:
    """Covers missing data handling and TEST-001."""

    summary = ScannerEngine().scan([SymbolScanInput(symbol="BTCUSDT")])

    candidate = summary.candidates[0]
    assert candidate.symbol == "BTCUSDT"
    assert candidate.bias is DirectionalBias.NEUTRAL
    assert candidate.score == 0.0
    assert candidate.reasons == ("insufficient_data",)


def test_scanner_events_wrap_candidates_and_summary() -> None:
    """Covers scanner events for FR-902, FR-903, and TEST-001."""

    event_bus = EventBus()
    candidate_events: list[SetupCandidateFoundEvent] = []
    completed_events: list[ScannerCompletedEvent] = []
    event_bus.subscribe(SetupCandidateFoundEvent, candidate_events.append)
    event_bus.subscribe(ScannerCompletedEvent, completed_events.append)

    summary = ScannerEngine(event_bus).scan(
        [
            SymbolScanInput(
                symbol="BTCUSDT",
                trend=trend("BTCUSDT", TrendState.BULLISH, 1),
                alignment=alignment("BTCUSDT", DirectionalBias.BULLISH, 2),
            ),
        ],
    )

    assert candidate_events[0].candidate.symbol == "BTCUSDT"
    assert completed_events[0].summary == summary


def test_scanner_does_not_recalculate_structure_or_trend_logic() -> None:
    """Covers no-recalculation scanner constraint and TEST-001."""

    scanner_source = Path("backend/engines/scanner/engine.py").read_text(encoding="utf-8")

    assert "MarketStructureEngine" not in scanner_source
    assert "TrendEngine" not in scanner_source
    assert ".add_candle(" not in scanner_source
    assert ".add_event(" not in scanner_source


def trend_state_for_bias(bias: DirectionalBias) -> TrendState:
    if bias is DirectionalBias.BULLISH:
        return TrendState.BULLISH
    if bias is DirectionalBias.BEARISH:
        return TrendState.BEARISH
    return TrendState.TRANSITION
