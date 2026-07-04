from __future__ import annotations

import pytest

from backend.engines.structure import (
    BreakDirection,
    BreakOfStructure,
    StructureEvent,
    StructureLabel,
    StructureSwing,
    SwingKind,
)
from backend.engines.trend import TrendEngine, TrendEngineError, TrendFlipMode, TrendState
from backend.models import Timeframe


def swing(
    label: StructureLabel,
    *,
    index: int,
    timeframe: Timeframe = Timeframe.FOUR_HOUR,
) -> StructureEvent:
    kind = SwingKind.HIGH if label in {StructureLabel.HH, StructureLabel.LH} else SwingKind.LOW
    return StructureEvent(
        swing=StructureSwing(
            symbol="BTCUSDT",
            timeframe=timeframe,
            kind=kind,
            label=label,
            level=100.0 + index,
            candle_open_time_ms=index * 60_000,
            candle_close_time_ms=(index + 1) * 60_000,
        ),
    )


def bos(
    direction: BreakDirection,
    *,
    index: int,
    timeframe: Timeframe = Timeframe.FOUR_HOUR,
) -> StructureEvent:
    broken_label = StructureLabel.HH if direction is BreakDirection.BULLISH else StructureLabel.HL
    return StructureEvent(
        break_of_structure=BreakOfStructure(
            symbol="BTCUSDT",
            timeframe=timeframe,
            direction=direction,
            broken_label=broken_label,
            broken_level=100.0,
            candle_close=105.0 if direction is BreakDirection.BULLISH else 95.0,
            candle_open_time_ms=index * 60_000,
            candle_close_time_ms=(index + 1) * 60_000,
        ),
    )


def collect_updates(engine: TrendEngine, events: list[StructureEvent]) -> list[TrendState]:
    states: list[TrendState] = []
    for event in events:
        update = engine.add_event(event)
        if update is not None:
            states.append(update.state)
    return states


def test_bullish_trend_from_hh_hl_structure() -> None:
    """Covers FR-501, FR-502, FR-503, and TEST-001."""

    engine = TrendEngine()

    updates = [
        engine.add_event(swing(StructureLabel.HH, index=0)),
        engine.add_event(swing(StructureLabel.HL, index=1)),
    ]

    assert updates[0] is None
    assert updates[1] is not None
    assert updates[1].state is TrendState.BULLISH
    assert updates[1].strength.confirming_structure_count == 2


def test_bearish_trend_from_lh_ll_structure() -> None:
    """Covers FR-501, FR-502, FR-503, and TEST-001."""

    engine = TrendEngine()

    updates = [
        engine.add_event(swing(StructureLabel.LH, index=0)),
        engine.add_event(swing(StructureLabel.LL, index=1)),
    ]

    assert updates[0] is None
    assert updates[1] is not None
    assert updates[1].state is TrendState.BEARISH
    assert updates[1].strength.confirming_structure_count == 2


def test_immediate_mode_flips_bullish_to_bearish_on_bos() -> None:
    """Covers FR-505, FR-508, and TEST-001."""

    engine = TrendEngine(flip_mode=TrendFlipMode.IMMEDIATE)
    engine.add_event(swing(StructureLabel.HH, index=0))
    bullish_update = engine.add_event(swing(StructureLabel.HL, index=1))

    bearish_update = engine.add_event(bos(BreakDirection.BEARISH, index=2))

    assert bullish_update is not None
    assert bullish_update.state is TrendState.BULLISH
    assert bearish_update is not None
    assert bearish_update.previous_state is TrendState.BULLISH
    assert bearish_update.state is TrendState.BEARISH
    assert bearish_update.reason == "bos_immediate_flip"


def test_immediate_mode_flips_bearish_to_bullish_on_bos() -> None:
    """Covers FR-505, FR-508, and TEST-001."""

    engine = TrendEngine(flip_mode=TrendFlipMode.IMMEDIATE)
    engine.add_event(swing(StructureLabel.LH, index=0))
    bearish_update = engine.add_event(swing(StructureLabel.LL, index=1))

    bullish_update = engine.add_event(bos(BreakDirection.BULLISH, index=2))

    assert bearish_update is not None
    assert bearish_update.state is TrendState.BEARISH
    assert bullish_update is not None
    assert bullish_update.previous_state is TrendState.BEARISH
    assert bullish_update.state is TrendState.BULLISH


def test_confirmed_mode_enters_transition_until_new_ll_confirms_bearish_flip() -> None:
    """Covers FR-505, FR-508, and TEST-001."""

    engine = TrendEngine(flip_mode=TrendFlipMode.CONFIRMED)
    engine.add_event(swing(StructureLabel.HH, index=0))
    engine.add_event(swing(StructureLabel.HL, index=1))

    transition_update = engine.add_event(bos(BreakDirection.BEARISH, index=2))
    ignored_update = engine.add_event(swing(StructureLabel.LH, index=3))
    bearish_update = engine.add_event(swing(StructureLabel.LL, index=4))

    assert transition_update is not None
    assert transition_update.state is TrendState.TRANSITION
    assert transition_update.previous_state is TrendState.BULLISH
    assert ignored_update is None
    assert bearish_update is not None
    assert bearish_update.previous_state is TrendState.TRANSITION
    assert bearish_update.state is TrendState.BEARISH
    assert bearish_update.reason == "confirmed_bearish_flip"


def test_confirmed_mode_enters_transition_until_new_hh_confirms_bullish_flip() -> None:
    """Covers FR-505, FR-508, and TEST-001."""

    engine = TrendEngine(flip_mode=TrendFlipMode.CONFIRMED)
    engine.add_event(swing(StructureLabel.LH, index=0))
    engine.add_event(swing(StructureLabel.LL, index=1))

    transition_update = engine.add_event(bos(BreakDirection.BULLISH, index=2))
    ignored_update = engine.add_event(swing(StructureLabel.HL, index=3))
    bullish_update = engine.add_event(swing(StructureLabel.HH, index=4))

    assert transition_update is not None
    assert transition_update.state is TrendState.TRANSITION
    assert transition_update.previous_state is TrendState.BEARISH
    assert ignored_update is None
    assert bullish_update is not None
    assert bullish_update.previous_state is TrendState.TRANSITION
    assert bullish_update.state is TrendState.BULLISH
    assert bullish_update.reason == "confirmed_bullish_flip"


def test_engine_is_timeframe_independent_but_single_instance_is_consistent() -> None:
    """Covers FR-501, FR-502, FR-503, and TEST-001."""

    engine = TrendEngine()

    engine.add_event(swing(StructureLabel.HH, index=0, timeframe=Timeframe.WEEKLY))
    update = engine.add_event(swing(StructureLabel.HL, index=1, timeframe=Timeframe.WEEKLY))

    assert update is not None
    assert update.timeframe is Timeframe.WEEKLY

    with pytest.raises(TrendEngineError):
        engine.add_event(swing(StructureLabel.HH, index=2, timeframe=Timeframe.DAILY))


def test_replay_consistency_for_same_structure_event_sequence() -> None:
    """Covers replay consistency and TEST-001."""

    events = [
        swing(StructureLabel.HH, index=0),
        swing(StructureLabel.HL, index=1),
        bos(BreakDirection.BEARISH, index=2),
        swing(StructureLabel.LH, index=3),
        swing(StructureLabel.LL, index=4),
    ]

    first = collect_updates(TrendEngine(flip_mode=TrendFlipMode.CONFIRMED), events)
    second = collect_updates(TrendEngine(flip_mode=TrendFlipMode.CONFIRMED), events)

    assert first == second
    assert first == [TrendState.BULLISH, TrendState.TRANSITION, TrendState.BEARISH]
