from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import EventBus
from backend.models import Candle, Timeframe, Trade
from backend.pipelines.candle import (
    ONE_MINUTE_MS,
    CandleClosedEvent,
    LateTradeError,
    OneMinuteCandleBuilder,
    OneMinuteCandlePipeline,
    floor_to_minute_ms,
)
from backend.pipelines.market_data import TradeReceivedEvent
from backend.storage import CandleAlreadyExistsError, InMemoryCandleStore, JsonlCandleStore


def make_trade(timestamp_ms: int, price: float, quantity: float = 1.0) -> Trade:
    return Trade(
        symbol="BTCUSDT",
        price=price,
        quantity=quantity,
        timestamp_ms=timestamp_ms,
        source="test",
    )


def test_one_minute_builder_constructs_correct_ohlcv_and_preserves_wicks() -> None:
    """Covers FR-201, FR-202, FR-203, FR-204, and TEST-001."""

    builder = OneMinuteCandleBuilder()

    assert builder.add_trade(make_trade(1_000, 100.0, 0.5)) == []
    assert builder.add_trade(make_trade(10_000, 105.0, 0.25)) == []
    assert builder.add_trade(make_trade(20_000, 95.0, 0.75)) == []
    closed = builder.advance_time(ONE_MINUTE_MS, "BTCUSDT")

    assert len(closed) == 1
    candle = closed[0].candle
    assert candle.open_time_ms == 0
    assert candle.close_time_ms == ONE_MINUTE_MS
    assert candle.open == 100.0
    assert candle.high == 105.0
    assert candle.low == 95.0
    assert candle.close == 95.0
    assert candle.volume == 1.5
    assert candle.body_high == 100.0
    assert candle.body_low == 95.0
    assert not closed[0].is_synthetic


def test_candle_closure_uses_utc_minute_boundaries() -> None:
    """Covers FR-205 and TEST-001."""

    builder = OneMinuteCandleBuilder()

    builder.add_trade(make_trade(125_123, 100.0))
    assert builder.advance_time(179_999, "BTCUSDT") == []
    closed = builder.advance_time(180_000, "BTCUSDT")

    assert len(closed) == 1
    assert closed[0].candle.open_time_ms == 120_000
    assert closed[0].candle.close_time_ms == 180_000
    assert floor_to_minute_ms(125_123) == 120_000


def test_builder_generates_synthetic_candles_for_missing_minutes() -> None:
    """Covers FR-206, FR-208, and TEST-001."""

    builder = OneMinuteCandleBuilder()

    builder.add_trade(make_trade(1_000, 100.0))
    closed = builder.add_trade(make_trade(3 * ONE_MINUTE_MS + 1_000, 110.0))

    assert [item.candle.open_time_ms for item in closed] == [
        0,
        ONE_MINUTE_MS,
        2 * ONE_MINUTE_MS,
    ]
    assert [item.is_synthetic for item in closed] == [False, True, True]
    assert closed[1].candle.open == 100.0
    assert closed[1].candle.high == 100.0
    assert closed[1].candle.low == 100.0
    assert closed[1].candle.close == 100.0
    assert closed[1].candle.volume == 0.0


def test_builder_rejects_late_trades_for_completed_candles() -> None:
    """Covers FR-207 and TEST-001 duplicate prevention at the builder boundary."""

    builder = OneMinuteCandleBuilder()

    builder.add_trade(make_trade(1_000, 100.0))
    builder.advance_time(ONE_MINUTE_MS, "BTCUSDT")

    with pytest.raises(LateTradeError):
        builder.add_trade(make_trade(2_000, 101.0))


def test_pipeline_publishes_candle_close_events_from_trade_events() -> None:
    """Covers FR-209 and TEST-001."""

    event_bus = EventBus()
    store = InMemoryCandleStore()
    events: list[CandleClosedEvent] = []
    event_bus.subscribe(CandleClosedEvent, events.append)
    pipeline = OneMinuteCandlePipeline(event_bus=event_bus, store=store)
    pipeline.subscribe()

    event_bus.publish(TradeReceivedEvent(trade=make_trade(1_000, 100.0)))
    event_bus.publish(TradeReceivedEvent(trade=make_trade(ONE_MINUTE_MS + 1_000, 101.0)))

    assert len(events) == 1
    assert events[0].candle.open_time_ms == 0
    assert store.list("BTCUSDT", Timeframe.ONE_MINUTE) == (events[0].candle,)


def test_pipeline_advance_time_does_not_publish_duplicate_candles() -> None:
    """Covers FR-207, FR-209, and TEST-001."""

    event_bus = EventBus()
    store = InMemoryCandleStore()
    events: list[CandleClosedEvent] = []
    event_bus.subscribe(CandleClosedEvent, events.append)
    pipeline = OneMinuteCandlePipeline(event_bus=event_bus, store=store)

    pipeline.handle_trade(make_trade(1_000, 100.0))
    pipeline.advance_time(ONE_MINUTE_MS, "BTCUSDT")
    pipeline.advance_time(ONE_MINUTE_MS, "BTCUSDT")

    assert len(events) == 1
    assert len(store.list("BTCUSDT", Timeframe.ONE_MINUTE)) == 1


def test_in_memory_store_rejects_duplicate_candle_keys() -> None:
    """Covers FR-207 and TEST-001."""

    store = InMemoryCandleStore()
    candle = Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=0,
        close_time_ms=ONE_MINUTE_MS,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=2.0,
    )

    store.save(candle)
    with pytest.raises(CandleAlreadyExistsError):
        store.save(candle)


def test_jsonl_candle_store_persists_and_reloads(tmp_path: Path) -> None:
    """Covers basic disk persistence for M3 and TEST-001."""

    path = tmp_path / "candles.jsonl"
    candle = Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=0,
        close_time_ms=ONE_MINUTE_MS,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=2.0,
    )

    store = JsonlCandleStore(path)
    store.save(candle)
    reloaded = JsonlCandleStore(path)

    assert reloaded.list("BTCUSDT", Timeframe.ONE_MINUTE) == (candle,)
