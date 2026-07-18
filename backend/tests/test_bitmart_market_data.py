from __future__ import annotations

from backend.core import EventBus
from backend.models import Trade
from backend.pipelines.market_data import (
    BITMART_SOURCE,
    BitMartTradeStreamClient,
    BitMartTradeStreamClientConfig,
    EventBusMarketDataPipeline,
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
    TradeReceivedEvent,
)


def test_event_bus_market_data_pipeline_publishes_bitmart_trade_event() -> None:
    """Covers FR-109 and TEST-001 with exchange-neutral canonical trades."""

    event_bus = EventBus()
    events: list[TradeReceivedEvent] = []
    pipeline = EventBusMarketDataPipeline(event_bus)
    event_bus.subscribe(TradeReceivedEvent, events.append)

    pipeline.publish_trade(
        Trade(
            symbol="BTCUSDT",
            price=100.0,
            quantity=1.0,
            timestamp_ms=1_000,
            source=BITMART_SOURCE,
        ),
    )

    assert len(events) == 1
    assert events[0].trade.source == BITMART_SOURCE


def test_bitmart_live_stream_client_reports_unavailable_without_network() -> None:
    """M31.1 exposes live BitMart as foundation-only and makes no network calls."""

    event_bus = EventBus()
    statuses: list[MarketDataStatusEvent] = []
    event_bus.subscribe(MarketDataStatusEvent, statuses.append)
    client = BitMartTradeStreamClient(
        config=BitMartTradeStreamClientConfig(symbol="BTCUSDT"),
        event_bus=event_bus,
    )

    client.start_unavailable()

    assert statuses[0].source == BITMART_SOURCE
    assert statuses[0].status is MarketDataConnectionStatus.ERROR
    assert statuses[0].message == "bitmart_live_stream_unavailable"
