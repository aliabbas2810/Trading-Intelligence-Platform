from __future__ import annotations

from backend.core import EventBus
from backend.models import Candle, Timeframe
from backend.pipelines.candle import ONE_MINUTE_MS, CandleClosedEvent
from backend.pipelines.timeframe import (
    AGGREGATED_TIMEFRAMES,
    DAILY_MS,
    FOUR_HOUR_MS,
    ONE_HOUR_MS,
    WEEKLY_MS,
    TimeframeAggregationError,
    TimeframeAggregator,
    TimeframeCandleClosedEvent,
    TimeframePipeline,
    timeframe_close_time_ms,
    timeframe_open_time_ms,
)
from backend.storage import InMemoryCandleStore


MONDAY_2024_01_01_UTC_MS = 1_704_067_200_000


def make_one_minute_candle(open_time_ms: int, index: int = 0, volume: float = 1.0) -> Candle:
    price = 100.0 + index
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + ONE_MINUTE_MS,
        open=price,
        high=price + 10.0,
        low=price - 10.0,
        close=price + 1.0,
        volume=volume,
    )


def feed_minutes(
    aggregator: TimeframeAggregator,
    start_ms: int,
    count: int,
) -> Candle:
    completed: Candle | None = None
    for index in range(count):
        result = aggregator.add_candle(
            make_one_minute_candle(
                open_time_ms=start_ms + index * ONE_MINUTE_MS,
                index=index,
                volume=float(index + 1),
            ),
        )
        if result is not None:
            completed = result

    if completed is None:
        raise AssertionError("Expected completed higher-timeframe candle")
    return completed


def test_four_hour_aggregation_preserves_ohlcv_and_wicks() -> None:
    """Covers FR-301, FR-305, and TEST-001."""

    aggregator = TimeframeAggregator(Timeframe.FOUR_HOUR)

    candle = feed_minutes(aggregator, start_ms=0, count=240)

    assert candle.timeframe is Timeframe.FOUR_HOUR
    assert candle.open_time_ms == 0
    assert candle.close_time_ms == FOUR_HOUR_MS
    assert candle.open == 100.0
    assert candle.high == 349.0
    assert candle.low == 90.0
    assert candle.close == 340.0
    assert candle.volume == sum(float(index + 1) for index in range(240))


def test_one_hour_aggregation_supports_entry_timeframe() -> None:
    """Covers expanded lower-timeframe aggregation support and TEST-001."""

    aggregator = TimeframeAggregator(Timeframe.ONE_HOUR)

    candle = feed_minutes(aggregator, start_ms=0, count=60)

    assert candle.timeframe is Timeframe.ONE_HOUR
    assert candle.open_time_ms == 0
    assert candle.close_time_ms == ONE_HOUR_MS
    assert timeframe_open_time_ms(ONE_HOUR_MS + 123_456, Timeframe.ONE_HOUR) == ONE_HOUR_MS
    assert timeframe_close_time_ms(ONE_HOUR_MS, Timeframe.ONE_HOUR) == 2 * ONE_HOUR_MS


def test_default_timeframe_pipeline_supports_required_derived_timeframes() -> None:
    """Covers expanded timeframe pipeline defaults and TEST-001."""

    assert AGGREGATED_TIMEFRAMES == (
        Timeframe.FIVE_MINUTE,
        Timeframe.FIFTEEN_MINUTE,
        Timeframe.THIRTY_MINUTE,
        Timeframe.ONE_HOUR,
        Timeframe.TWO_HOUR,
        Timeframe.FOUR_HOUR,
        Timeframe.DAILY,
        Timeframe.WEEKLY,
    )


def test_daily_aggregation_uses_utc_midnight_boundaries() -> None:
    """Covers FR-302, FR-304, FR-305, and TEST-001."""

    aggregator = TimeframeAggregator(Timeframe.DAILY)

    candle = feed_minutes(aggregator, start_ms=DAILY_MS, count=1_440)

    assert candle.timeframe is Timeframe.DAILY
    assert candle.open_time_ms == DAILY_MS
    assert candle.close_time_ms == 2 * DAILY_MS
    assert timeframe_open_time_ms(DAILY_MS + 123_456, Timeframe.DAILY) == DAILY_MS
    assert timeframe_close_time_ms(DAILY_MS, Timeframe.DAILY) == 2 * DAILY_MS


def test_weekly_aggregation_uses_monday_utc_boundaries() -> None:
    """Covers FR-303, FR-304, FR-305, and TEST-001."""

    aggregator = TimeframeAggregator(Timeframe.WEEKLY)

    candle = feed_minutes(aggregator, start_ms=MONDAY_2024_01_01_UTC_MS, count=10_080)

    assert candle.timeframe is Timeframe.WEEKLY
    assert candle.open_time_ms == MONDAY_2024_01_01_UTC_MS
    assert candle.close_time_ms == MONDAY_2024_01_01_UTC_MS + WEEKLY_MS
    assert (
        timeframe_open_time_ms(MONDAY_2024_01_01_UTC_MS + 3 * DAILY_MS, Timeframe.WEEKLY)
        == MONDAY_2024_01_01_UTC_MS
    )


def test_aggregator_rejects_non_one_minute_or_missing_input() -> None:
    """Covers FR-305 and TEST-001."""

    aggregator = TimeframeAggregator(Timeframe.FOUR_HOUR)
    aggregator.add_candle(make_one_minute_candle(0))

    try:
        aggregator.add_candle(make_one_minute_candle(2 * ONE_MINUTE_MS))
    except TimeframeAggregationError as exc:
        assert "contiguous" in str(exc)
    else:
        raise AssertionError("Expected missing one-minute candle to be rejected")

    bad_candle = Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        open_time_ms=0,
        close_time_ms=FOUR_HOUR_MS,
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=10.0,
    )

    try:
        TimeframeAggregator(Timeframe.DAILY).add_candle(bad_candle)
    except TimeframeAggregationError as exc:
        assert "1m candles only" in str(exc)
    else:
        raise AssertionError("Expected non-1m candle to be rejected")


def test_timeframe_pipeline_publishes_events_and_stores_completed_candles() -> None:
    """Covers FR-306 and TEST-001."""

    event_bus = EventBus()
    store = InMemoryCandleStore()
    events: list[TimeframeCandleClosedEvent] = []
    event_bus.subscribe(TimeframeCandleClosedEvent, events.append)
    pipeline = TimeframePipeline(
        event_bus=event_bus,
        store=store,
        timeframes=(Timeframe.FOUR_HOUR,),
    )
    pipeline.subscribe()

    for index in range(240):
        event_bus.publish(
            CandleClosedEvent(
                candle=make_one_minute_candle(
                    open_time_ms=index * ONE_MINUTE_MS,
                    index=index,
                    volume=1.0,
                ),
            ),
        )

    assert len(events) == 1
    assert events[0].candle.timeframe is Timeframe.FOUR_HOUR
    assert store.list("BTCUSDT", Timeframe.FOUR_HOUR) == (events[0].candle,)
