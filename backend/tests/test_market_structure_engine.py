from __future__ import annotations

import pytest

from backend.engines.structure import (
    AtrDisplacementThreshold,
    BodyRange,
    BreakDirection,
    DisplacementMode,
    HybridDisplacementThreshold,
    MarketStructureEngine,
    PercentDisplacementThreshold,
    StructureLabel,
    SwingKind,
)
from backend.models import Candle, Timeframe


MINUTE_MS = 60_000


def make_candle(
    index: int,
    open_price: float,
    close_price: float,
    *,
    high: float | None = None,
    low: float | None = None,
    timeframe: Timeframe = Timeframe.ONE_MINUTE,
) -> Candle:
    body_high = max(open_price, close_price)
    body_low = min(open_price, close_price)
    return Candle(
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time_ms=index * MINUTE_MS,
        close_time_ms=(index + 1) * MINUTE_MS,
        open=open_price,
        high=high if high is not None else body_high,
        low=low if low is not None else body_low,
        close=close_price,
        volume=1.0,
    )


def collect_swings(candles: list[Candle]) -> list[StructureLabel]:
    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))
    labels: list[StructureLabel] = []
    for candle in candles:
        for event in engine.add_candle(candle):
            if event.swing is not None:
                labels.append(event.swing.label)
    return labels


def test_body_range_uses_open_close_only() -> None:
    """Covers FR-401, FR-402, and TEST-001."""

    candle = make_candle(0, 100.0, 105.0, high=500.0, low=1.0)

    body = BodyRange.from_candle(candle)

    assert body.high == 105.0
    assert body.low == 100.0


def test_percent_displacement_threshold_is_dynamic() -> None:
    """Covers FR-403 and TEST-001."""

    candle = make_candle(0, 100.0, 110.0)
    threshold = PercentDisplacementThreshold(percent=0.05)

    assert threshold.threshold(candle) == 5.5
    assert DisplacementMode.PERCENT.value == "percent"


def test_asymmetric_displacement_thresholds_are_supported() -> None:
    """Covers CFG-003-style bullish/bearish percentage threshold compatibility."""

    engine = MarketStructureEngine(
        bullish_displacement=PercentDisplacementThreshold(percent=0.10),
        bearish_displacement=PercentDisplacementThreshold(percent=0.05),
    )
    candles = [
        make_candle(0, 100.0, 100.0),
        make_candle(1, 120.0, 120.0),
        make_candle(2, 111.0, 111.0),
        make_candle(3, 108.0, 108.0),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))

    assert len(events) == 1
    assert events[0].swing is not None
    assert events[0].swing.level == 120.0


def test_atr_and_hybrid_thresholds_are_typed_placeholders() -> None:
    """Covers FR-403 and TEST-001 placeholder interfaces."""

    candle = make_candle(0, 100.0, 110.0)
    atr = AtrDisplacementThreshold(multiplier=2.0)
    hybrid = HybridDisplacementThreshold(
        percent=PercentDisplacementThreshold(percent=0.01),
        atr=atr,
    )

    with pytest.raises(NotImplementedError):
        atr.threshold(candle)
    with pytest.raises(NotImplementedError):
        hybrid.threshold(candle)


def test_minor_pullback_below_displacement_does_not_confirm_swing() -> None:
    """Covers FR-403, FR-404, and TEST-001."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))

    candles = [
        make_candle(0, 100.0, 100.0),
        make_candle(1, 120.0, 120.0),
        make_candle(2, 119.0, 119.0),
        make_candle(3, 118.0, 118.0),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))

    assert events == ()


def test_pullback_at_or_above_displacement_confirms_swing() -> None:
    """Covers FR-403, FR-404, FR-405, and TEST-001."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))

    candles = [
        make_candle(0, 100.0, 100.0),
        make_candle(1, 120.0, 120.0),
        make_candle(2, 108.0, 108.0),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))

    assert len(events) == 1
    assert events[0].swing is not None
    assert events[0].swing.kind is SwingKind.HIGH
    assert events[0].swing.label is StructureLabel.HH
    assert events[0].swing.level == 120.0


def test_detection_does_not_depend_on_exactly_three_candles() -> None:
    """Covers FR-404 and TEST-001."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.10))

    candles = [
        make_candle(0, 100.0, 100.0),
        make_candle(1, 110.0, 110.0),
        make_candle(2, 120.0, 120.0),
        make_candle(3, 125.0, 125.0),
        make_candle(4, 124.0, 124.0),
        make_candle(5, 112.5, 112.5),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))

    assert len(events) == 1
    assert events[0].swing is not None
    assert events[0].swing.level == 125.0
    assert events[0].swing.candle_open_time_ms == 3 * MINUTE_MS


def test_runtime_default_displacement_does_not_confirm_every_candle() -> None:
    """Regression for M31.3: provisional highs move until an opposite pullback confirms once."""

    engine = MarketStructureEngine()
    candles = [
        make_candle(index, 100.0 + index, 100.0 + index)
        for index in range(20)
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))
    diagnostics = engine.diagnostics()

    assert events == ()
    assert diagnostics.candidate_swings > 0
    assert diagnostics.confirmed_swings == 0
    assert diagnostics.structure_density_anomaly is False


def test_single_confirmed_swing_after_provisional_extreme_pullback() -> None:
    """Regression for M31.3: one moving provisional high becomes one confirmed HH."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))
    candles = [
        make_candle(0, 100.0, 100.0),
        make_candle(1, 110.0, 110.0),
        make_candle(2, 120.0, 120.0),
        make_candle(3, 130.0, 130.0),
        make_candle(4, 123.0, 123.0),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))
    swings = [event.swing for event in events if event.swing is not None]

    assert len(swings) == 1
    assert swings[0].label is StructureLabel.HH
    assert swings[0].level == 130.0


def test_new_candidate_extreme_is_not_confirmed_by_same_candle_body() -> None:
    """Regression: confirmation requires an opposite move after the provisional update."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))
    candles = [
        make_candle(0, 120.0, 120.0),
        make_candle(1, 100.0, 100.0),
        make_candle(2, 130.0, 130.0),
        make_candle(3, 90.0, 140.0),
    ]

    for candle in candles[:-1]:
        tuple(engine.add_candle(candle))
    events = tuple(engine.add_candle(candles[-1]))

    assert [event.swing for event in events if event.swing is not None] == []

    confirmation = tuple(engine.add_candle(make_candle(4, 115.0, 115.0)))
    swings = [event.swing for event in confirmation if event.swing is not None]

    assert len(swings) == 1
    assert swings[0].kind is SwingKind.HIGH
    assert swings[0].level == 140.0


def test_elbow_swing_detection_uses_bodies_and_ignores_wicks() -> None:
    """Covers FR-402, FR-404, and TEST-001."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))

    candles = [
        make_candle(0, 100.0, 100.0, high=1_000.0),
        make_candle(1, 110.0, 110.0),
        make_candle(2, 109.0, 109.0, high=2_000.0),
        make_candle(3, 99.0, 99.0, high=3_000.0),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))

    assert len(events) == 1
    assert events[0].swing is not None
    assert events[0].swing.kind is SwingKind.HIGH
    assert events[0].swing.label is StructureLabel.HH
    assert events[0].swing.level == 110.0


def test_structure_classifies_hh_hl_lh_ll() -> None:
    """Covers FR-405, FR-406, FR-407, FR-408, and TEST-001."""

    candles = [
        make_candle(0, 100.0, 100.0),
        make_candle(1, 110.0, 110.0),
        make_candle(2, 104.0, 104.0),
        make_candle(3, 106.0, 106.0),
        make_candle(4, 102.0, 102.0),
        make_candle(5, 108.0, 108.0),
        make_candle(6, 103.0, 103.0),
        make_candle(7, 112.0, 112.0),
        make_candle(8, 105.0, 105.0),
        make_candle(9, 107.0, 107.0),
        make_candle(10, 98.0, 98.0),
        make_candle(11, 101.0, 101.0),
        make_candle(12, 104.0, 104.0),
        make_candle(13, 98.0, 98.0),
    ]

    labels = collect_swings(candles)

    assert labels == [
        StructureLabel.HH,
        StructureLabel.HL,
        StructureLabel.HH,
        StructureLabel.LL,
        StructureLabel.LH,
    ]


def test_bullish_bos_uses_close_above_body_swing_high_not_wick() -> None:
    """Covers FR-402, FR-409, and TEST-001."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))
    candles = [
        make_candle(0, 100.0, 100.0),
        make_candle(1, 110.0, 110.0, high=500.0),
        make_candle(2, 104.0, 104.0),
        make_candle(3, 109.0, 109.0, high=600.0),
        make_candle(4, 111.0, 111.0),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))
    bos_events = [event.break_of_structure for event in events if event.break_of_structure]

    assert len(bos_events) == 1
    assert bos_events[0].direction is BreakDirection.BULLISH
    assert bos_events[0].broken_label is StructureLabel.HH
    assert bos_events[0].broken_level == 110.0
    assert bos_events[0].candle_close == 111.0


def test_bearish_bos_uses_close_below_body_swing_low_not_wick() -> None:
    """Covers FR-402, FR-409, and TEST-001."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))
    candles = [
        make_candle(0, 108.0, 108.0),
        make_candle(1, 100.0, 100.0, low=1.0),
        make_candle(2, 106.0, 106.0),
        make_candle(3, 101.0, 101.0, low=2.0),
        make_candle(4, 99.0, 99.0),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))
    bos_events = [event.break_of_structure for event in events if event.break_of_structure]

    assert len(bos_events) == 1
    assert bos_events[0].direction is BreakDirection.BEARISH
    assert bos_events[0].broken_label is StructureLabel.HL
    assert bos_events[0].broken_level == 100.0
    assert bos_events[0].candle_close == 99.0


def test_replay_consistency_for_same_completed_candle_sequence() -> None:
    """Covers FR-412 and TEST-001."""

    candles = [
        make_candle(0, 100.0, 100.0),
        make_candle(1, 110.0, 110.0),
        make_candle(2, 104.0, 104.0),
        make_candle(3, 109.0, 109.0),
        make_candle(4, 111.0, 111.0),
        make_candle(5, 105.0, 105.0),
    ]

    first_engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))
    second_engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))

    first_events = tuple(event for candle in candles for event in first_engine.add_candle(candle))
    second_events = tuple(event for candle in candles for event in second_engine.add_candle(candle))

    assert first_events == second_events


def test_engine_is_timeframe_independent() -> None:
    """Covers M5 timeframe independence and TEST-001."""

    engine = MarketStructureEngine(displacement=PercentDisplacementThreshold(percent=0.05))
    candles = [
        make_candle(0, 100.0, 100.0, timeframe=Timeframe.FOUR_HOUR),
        make_candle(1, 110.0, 110.0, timeframe=Timeframe.FOUR_HOUR),
        make_candle(2, 104.5, 104.5, timeframe=Timeframe.FOUR_HOUR),
    ]

    events = tuple(event for candle in candles for event in engine.add_candle(candle))

    assert events[0].swing is not None
    assert events[0].swing.timeframe is Timeframe.FOUR_HOUR
