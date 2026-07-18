from __future__ import annotations

import logging

import pytest

from backend.core import EventBus
from backend.models import Trade
from backend.pipelines.market_data import (
    BITMART_SOURCE,
    BitMartTradeMessageParser,
    BitMartTradeStreamClient,
    BitMartTradeStreamClientConfig,
    EventBusMarketDataPipeline,
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
    TradeReceivedEvent,
    parse_bitmart_created_at_ms,
    subscription_channel,
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


def test_bitmart_trade_parser_uses_official_futures_trade_channel() -> None:
    """Covers FR-101, FR-103, and TEST-001."""

    parser = BitMartTradeMessageParser(symbol="BTCUSDT")

    assert subscription_channel("BTCUSDT") == "futures/trade:BTCUSDT"
    assert parser.subscribe_payload() == '{"action":"subscribe","args":["futures/trade:BTCUSDT"]}'


def test_bitmart_trade_parser_normalizes_trade_timestamp() -> None:
    """Covers FR-103 timestamp normalization and TEST-001."""

    parser = BitMartTradeMessageParser(symbol="BTCUSDT")
    trades = parser.parse(
        """
        {
          "group":"futures/trade:BTCUSDT",
          "data":[{
            "trade_id":1409495322,
            "symbol":"BTCUSDT",
            "deal_price":"117387.58",
            "deal_vol":"1445",
            "m":true,
            "created_at":"2023-02-24T07:54:11.124940968Z"
          }]
        }
        """,
    )

    assert len(trades) == 1
    assert trades[0].symbol == "BTCUSDT"
    assert trades[0].price == 117_387.58
    assert trades[0].quantity == 1445.0
    assert trades[0].timestamp_ms == parse_bitmart_created_at_ms("2023-02-24T07:54:11.124940968Z")
    assert trades[0].source == BITMART_SOURCE


def test_bitmart_client_ack_malformed_and_duplicate_trade_handling() -> None:
    """Covers subscription ack, malformed messages, duplicate suppression, and TEST-001."""

    event_bus = EventBus()
    trades: list[TradeReceivedEvent] = []
    statuses: list[MarketDataStatusEvent] = []
    event_bus.subscribe(TradeReceivedEvent, trades.append)
    event_bus.subscribe(MarketDataStatusEvent, statuses.append)
    client = BitMartTradeStreamClient(
        config=BitMartTradeStreamClientConfig(symbol="BTCUSDT"),
        event_bus=event_bus,
        clock_ms=lambda: 123,
    )
    ack = (
        '{"action":"subscribe","group":"futures/trade:BTCUSDT","success":true,'
        '"request":{"action":"subscribe","args":["futures/trade:BTCUSDT"]}}'
    )
    message = (
        '{"group":"futures/trade:BTCUSDT","data":[{"trade_id":1,"symbol":"BTCUSDT",'
        '"deal_price":"100","deal_vol":"2","m":true,"created_at":"2023-02-24T07:54:11.124Z"}]}'
    )

    assert client.handle_text_message(ack) == ()
    client.handle_text_message(message)
    client.handle_text_message(message)
    client.handle_text_message('{"group":"futures/trade:BTCUSDT","data":[null]}')

    assert statuses[-1].status is MarketDataConnectionStatus.CONNECTED
    assert len(trades) == 1
    assert client.diagnostics.subscription_acknowledged is True
    assert client.diagnostics.duplicate_trade_count == 1
    assert client.diagnostics.malformed_trade_count == 1


@pytest.mark.asyncio
async def test_bitmart_websocket_failure_logs_diagnostics_and_reconnects(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event_bus = EventBus()
    statuses: list[MarketDataStatusEvent] = []
    event_bus.subscribe(MarketDataStatusEvent, statuses.append)

    class FailingConnector:
        def __init__(self) -> None:
            self.uris: list[str] = []

        def __call__(self, uri: str) -> object:
            self.uris.append(uri)
            return self

        async def __aenter__(self) -> object:
            raise OSError("websocket dns failure")

        async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

    connector = FailingConnector()
    client = BitMartTradeStreamClient(
        config=BitMartTradeStreamClientConfig(
            symbol="BTCUSDT",
            reconnect_delay_seconds=0.0,
            max_reconnect_attempts=2,
        ),
        event_bus=event_bus,
        connector=connector,
    )

    with caplog.at_level(logging.ERROR, logger="backend.pipelines.market_data.bitmart"):
        await client.run_forever()

    assert len(connector.uris) == 2
    assert [status.status for status in statuses].count(MarketDataConnectionStatus.ERROR) == 2
    assert any(status.status is MarketDataConnectionStatus.RECONNECTING for status in statuses)
    assert any(
        getattr(record, "operation", None) == "bitmart_websocket_connect"
        and getattr(record, "parsed_hostname", None) == "openapi-ws-v2.bitmart.com"
        and record.exc_info is not None
        for record in caplog.records
    )
