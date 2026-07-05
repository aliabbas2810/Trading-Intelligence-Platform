from __future__ import annotations

import pytest

from backend.core import EventBus
from backend.engines.replay import (
    HistoricalCandleReplaySource,
    HistoricalTradeReplaySource,
    ReplayController,
    ReplayControllerError,
    ReplayLifecycleEvent,
    ReplayProgressEvent,
    ReplayStatus,
)
from backend.models import Candle, Timeframe, Trade
from backend.pipelines.candle import CandleClosedEvent, OneMinuteCandlePipeline
from backend.pipelines.market_data import TradeReceivedEvent
from backend.storage import InMemoryCandleStore


def make_trade(timestamp_ms: int, price: float) -> Trade:
    return Trade(
        symbol="BTCUSDT",
        price=price,
        quantity=1.0,
        timestamp_ms=timestamp_ms,
        source="historical",
    )


def make_candle(open_time_ms: int, close_price: float) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + 60_000,
        open=close_price - 1.0,
        high=close_price + 2.0,
        low=close_price - 2.0,
        close=close_price,
        volume=10.0,
    )


def test_historical_trade_replay_source_orders_trades_deterministically() -> None:
    """Covers FR-801, FR-806, and TEST-001."""

    source = HistoricalTradeReplaySource(
        [
            make_trade(2_000, 102.0),
            make_trade(1_000, 101.0),
            make_trade(1_000, 100.0),
        ],
    )

    records = source.list_records()

    assert [record.timestamp_ms for record in records] == [1_000, 1_000, 2_000]
    assert [record.sequence for record in records] == [1, 2, 0]
    assert [record.event.trade.price for record in records if isinstance(record.event, TradeReceivedEvent)] == [
        101.0,
        100.0,
        102.0,
    ]


def test_historical_candle_replay_source_can_load_from_store() -> None:
    """Covers FR-801 and TEST-001 for stored candle replay."""

    store = InMemoryCandleStore()
    first = make_candle(60_000, 101.0)
    second = make_candle(0, 100.0)
    store.save(first)
    store.save(second)

    source = HistoricalCandleReplaySource.from_store(store, "BTCUSDT", Timeframe.ONE_MINUTE)

    records = source.list_records()
    assert [record.timestamp_ms for record in records] == [60_000, 120_000]
    assert all(isinstance(record.event, CandleClosedEvent) for record in records)


def test_replay_controller_publishes_trade_events_to_same_candle_pipeline() -> None:
    """Covers FR-801, FR-806, and TEST-002 live/replay consistency."""

    live_events = run_live_trade_sequence()
    replay_events = run_replayed_trade_sequence()

    assert replay_events == live_events


def test_replay_pause_resume_and_progress_reporting() -> None:
    """Covers FR-803, FR-804, and deterministic progress reporting."""

    bus = EventBus()
    observed_trades: list[Trade] = []
    lifecycle_events: list[ReplayLifecycleEvent] = []
    progress_events: list[ReplayProgressEvent] = []
    controller = ReplayController(
        bus,
        HistoricalTradeReplaySource(
            [
                make_trade(1_000, 100.0),
                make_trade(2_000, 101.0),
                make_trade(3_000, 102.0),
            ],
        ),
    )

    def capture_trade(event: TradeReceivedEvent) -> None:
        observed_trades.append(event.trade)
        if len(observed_trades) == 1:
            controller.pause()

    bus.subscribe(TradeReceivedEvent, capture_trade)
    bus.subscribe(ReplayLifecycleEvent, lifecycle_events.append)
    bus.subscribe(ReplayProgressEvent, progress_events.append)

    controller.start()

    assert_replay_status(controller, ReplayStatus.PAUSED)
    assert [trade.price for trade in observed_trades] == [100.0]
    assert progress_events[-1].processed_events == 1

    controller.resume()

    assert_replay_status(controller, ReplayStatus.COMPLETED)
    assert [trade.price for trade in observed_trades] == [100.0, 101.0, 102.0]
    assert lifecycle_events[-1].status is ReplayStatus.COMPLETED


def test_replay_step_mode_publishes_one_event_at_a_time() -> None:
    """Covers FR-805 and TEST-001."""

    bus = EventBus()
    trades: list[Trade] = []
    bus.subscribe(TradeReceivedEvent, lambda event: trades.append(event.trade))
    controller = ReplayController(
        bus,
        HistoricalTradeReplaySource([make_trade(1_000, 100.0), make_trade(2_000, 101.0)]),
    )

    controller.step()

    assert_replay_status(controller, ReplayStatus.PAUSED)
    assert [trade.price for trade in trades] == [100.0]

    controller.step()

    assert_replay_status(controller, ReplayStatus.COMPLETED)
    assert [trade.price for trade in trades] == [100.0, 101.0]


def test_replay_speed_multiplier_controls_delay_without_changing_order() -> None:
    """Covers FR-802 and TEST-001."""

    bus = EventBus()
    delays: list[float] = []
    trades: list[Trade] = []
    bus.subscribe(TradeReceivedEvent, lambda event: trades.append(event.trade))
    controller = ReplayController(
        bus,
        HistoricalTradeReplaySource([make_trade(1_000, 100.0), make_trade(3_000, 101.0)]),
        speed_multiplier=2.0,
        sleeper=delays.append,
    )

    controller.start()

    assert delays == [1.0]
    assert [trade.price for trade in trades] == [100.0, 101.0]


def test_replay_rejects_invalid_speed_multiplier() -> None:
    """Covers FR-802 validation and TEST-001."""

    with pytest.raises(ReplayControllerError):
        ReplayController(EventBus(), HistoricalTradeReplaySource(()), speed_multiplier=0.0)


def run_live_trade_sequence() -> tuple[CandleClosedEvent, ...]:
    bus = EventBus()
    store = InMemoryCandleStore()
    events: list[CandleClosedEvent] = []
    pipeline = OneMinuteCandlePipeline(bus, store)
    pipeline.subscribe()
    bus.subscribe(CandleClosedEvent, events.append)

    bus.publish(TradeReceivedEvent(trade=make_trade(1_000, 100.0)))
    bus.publish(TradeReceivedEvent(trade=make_trade(61_000, 101.0)))

    return tuple(events)


def run_replayed_trade_sequence() -> tuple[CandleClosedEvent, ...]:
    bus = EventBus()
    store = InMemoryCandleStore()
    events: list[CandleClosedEvent] = []
    pipeline = OneMinuteCandlePipeline(bus, store)
    pipeline.subscribe()
    bus.subscribe(CandleClosedEvent, events.append)
    controller = ReplayController(
        bus,
        HistoricalTradeReplaySource([make_trade(1_000, 100.0), make_trade(61_000, 101.0)]),
    )

    controller.start()

    return tuple(events)


def assert_replay_status(controller: ReplayController, expected: ReplayStatus) -> None:
    assert controller.status is expected
