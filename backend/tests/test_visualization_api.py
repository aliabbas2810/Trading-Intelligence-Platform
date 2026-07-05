from __future__ import annotations

from backend.api import (
    InMemoryAlignmentReadStore,
    InMemoryStructureReadStore,
    InMemoryTrendReadStore,
    VisualizationReadApi,
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
from backend.storage import InMemoryCandleStore


def make_api() -> tuple[
    VisualizationReadApi,
    InMemoryCandleStore,
    InMemoryStructureReadStore,
    InMemoryTrendReadStore,
    InMemoryAlignmentReadStore,
]:
    candle_store = InMemoryCandleStore()
    structure_store = InMemoryStructureReadStore()
    trend_store = InMemoryTrendReadStore()
    alignment_store = InMemoryAlignmentReadStore()
    api = VisualizationReadApi(
        candle_store=candle_store,
        structure_store=structure_store,
        trend_store=trend_store,
        alignment_store=alignment_store,
    )
    return api, candle_store, structure_store, trend_store, alignment_store


def test_visualization_api_returns_stored_candles_with_wicks() -> None:
    """Covers FR-601 and TEST-001."""

    api, candle_store, _, _, _ = make_api()
    candle = Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=0,
        close_time_ms=60_000,
        open=100.0,
        high=120.0,
        low=90.0,
        close=110.0,
        volume=2.0,
    )
    candle_store.save(candle)

    assert api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE) == (candle,)


def test_visualization_api_returns_stored_market_structure() -> None:
    """Covers FR-602, FR-604, and TEST-001."""

    api, _, structure_store, _, _ = make_api()
    swing = StructureSwing(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        kind=SwingKind.HIGH,
        label=StructureLabel.HH,
        level=120.0,
        candle_open_time_ms=0,
        candle_close_time_ms=60_000,
    )
    bos = BreakOfStructure(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        direction=BreakDirection.BULLISH,
        broken_label=StructureLabel.HH,
        broken_level=120.0,
        candle_close=125.0,
        candle_open_time_ms=60_000,
        candle_close_time_ms=120_000,
    )
    structure_store.add_swing(swing)
    structure_store.add_break_of_structure(bos)

    snapshot = api.get_market_structure("BTCUSDT", Timeframe.FOUR_HOUR)

    assert snapshot.swings == (swing,)
    assert snapshot.breaks_of_structure == (bos,)


def test_visualization_api_returns_stored_trend_and_alignment() -> None:
    """Covers FR-603 and TEST-001."""

    api, _, _, trend_store, alignment_store = make_api()
    trend = TrendUpdate(
        symbol="BTCUSDT",
        timeframe=Timeframe.DAILY,
        state=TrendState.BULLISH,
        previous_state=None,
        strength=TrendStrength(confirming_structure_count=3),
        reason="test",
        event_time_ms=1_000,
    )
    alignment = MultiTimeframeTrendResult(
        symbol="BTCUSDT",
        mode=MultiTimeframeMode.VOTING,
        bias=DirectionalBias.BULLISH,
        alignment_score=3,
        required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        present_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        missing_timeframes=(),
        snapshots=(
            TimeframeTrendSnapshot(
                symbol="BTCUSDT",
                timeframe=Timeframe.DAILY,
                state=TrendState.BULLISH,
                strength=TrendStrength(confirming_structure_count=3),
                event_time_ms=1_000,
            ),
        ),
        reason="test",
    )
    trend_store.set(trend)
    alignment_store.set(alignment)

    assert api.get_trend_state("BTCUSDT", Timeframe.DAILY).update == trend
    assert api.get_multi_timeframe_alignment("BTCUSDT") == alignment
