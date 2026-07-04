from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import TracebackType

import pytest

from backend.core import EventBus
from backend.pipelines.market_data import (
    BINANCE_SOURCE,
    BinanceTradeMessageError,
    BinanceTradeMessageParser,
    BinanceTradeStreamClient,
    BinanceTradeStreamClientConfig,
    EventBusMarketDataPipeline,
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
    TradeReceivedEvent,
)


VALID_BINANCE_TRADE = {
    "e": "trade",
    "E": 1_725_000_000_125,
    "s": "BTCUSDT",
    "t": 12345,
    "p": "100000.25",
    "q": "0.0105",
    "T": 1_725_000_000_123,
    "m": True,
    "M": True,
}


class FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self._messages = messages

    async def __aiter__(self) -> AsyncIterator[str]:
        for message in self._messages:
            yield message


class FakeConnectionContext(AbstractAsyncContextManager[FakeWebSocket]):
    def __init__(self, websocket: FakeWebSocket) -> None:
        self._websocket = websocket

    async def __aenter__(self) -> FakeWebSocket:
        return self._websocket

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class FailingConnectionContext(AbstractAsyncContextManager[FakeWebSocket]):
    async def __aenter__(self) -> FakeWebSocket:
        raise ConnectionError("socket closed")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class RecordingConnector:
    def __init__(self, context: AbstractAsyncContextManager[FakeWebSocket]) -> None:
        self.context = context
        self.uris: list[str] = []

    def __call__(self, uri: str) -> AbstractAsyncContextManager[FakeWebSocket]:
        self.uris.append(uri)
        return self.context


def test_binance_parser_normalizes_trade_message() -> None:
    """Covers FR-103, user-specified FR-104/FR-105, and TEST-001."""

    parser = BinanceTradeMessageParser()

    trade = parser.parse(VALID_BINANCE_TRADE)

    assert trade.symbol == "BTCUSDT"
    assert trade.price == 100000.25
    assert trade.quantity == 0.0105
    assert trade.timestamp_ms == 1_725_000_000_123
    assert trade.source == BINANCE_SOURCE


def test_binance_parser_accepts_json_string() -> None:
    """Covers FR-103 and TEST-001."""

    parser = BinanceTradeMessageParser()
    raw_message = (
        '{"e":"trade","s":"BTCUSDT","t":12345,'
        '"p":"100000.25","q":"0.0105","T":1725000000123}'
    )

    trade = parser.parse(raw_message)

    assert trade.timestamp_ms == 1_725_000_000_123


@pytest.mark.parametrize(
    "payload",
    [
        {"e": "aggTrade", "s": "BTCUSDT", "p": "1", "q": "1", "T": 1},
        {"e": "trade", "s": "", "p": "1", "q": "1", "T": 1},
        {"e": "trade", "s": "BTCUSDT", "p": "0", "q": "1", "T": 1},
        {"e": "trade", "s": "BTCUSDT", "p": "1", "q": "-1", "T": 1},
        {"e": "trade", "s": "BTCUSDT", "p": "1", "q": "1", "T": -1},
        {"e": "trade", "s": "BTCUSDT", "p": "1", "q": "1", "T": True},
    ],
)
def test_binance_parser_rejects_invalid_messages(payload: dict[str, object]) -> None:
    """Covers FR-103 and TEST-001 invalid external message handling."""

    parser = BinanceTradeMessageParser()

    with pytest.raises(BinanceTradeMessageError):
        parser.parse(payload)


def test_event_bus_market_data_pipeline_publishes_trade_event() -> None:
    """Covers user-specified FR-109 and TEST-001."""

    event_bus = EventBus()
    events: list[TradeReceivedEvent] = []
    parser = BinanceTradeMessageParser()
    pipeline = EventBusMarketDataPipeline(event_bus)
    event_bus.subscribe(TradeReceivedEvent, events.append)

    pipeline.publish_trade(parser.parse(VALID_BINANCE_TRADE))

    assert len(events) == 1
    assert events[0].trade.symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_binance_client_publishes_stream_trade_events() -> None:
    """Covers FR-101, user-specified FR-109, and TEST-001."""

    event_bus = EventBus()
    trades: list[TradeReceivedEvent] = []
    statuses: list[MarketDataStatusEvent] = []
    event_bus.subscribe(TradeReceivedEvent, trades.append)
    event_bus.subscribe(MarketDataStatusEvent, statuses.append)

    connector = RecordingConnector(
        FakeConnectionContext(FakeWebSocket([json.dumps(VALID_BINANCE_TRADE)])),
    )
    client = BinanceTradeStreamClient(
        config=BinanceTradeStreamClientConfig(
            symbol="BTCUSDT",
            reconnect_delay_seconds=0,
            max_reconnect_attempts=1,
        ),
        event_bus=event_bus,
        connector=connector,
    )

    await client.run()

    assert connector.uris == ["wss://stream.binance.com:9443/ws/btcusdt@trade"]
    assert [status.status for status in statuses] == [
        MarketDataConnectionStatus.CONNECTING,
        MarketDataConnectionStatus.CONNECTED,
        MarketDataConnectionStatus.STOPPED,
    ]
    assert len(trades) == 1
    assert trades[0].trade.symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_binance_client_publishes_reconnect_status_after_disconnect() -> None:
    """Covers FR-102 and TEST-001 reconnect/error handling design."""

    event_bus = EventBus()
    statuses: list[MarketDataStatusEvent] = []
    event_bus.subscribe(MarketDataStatusEvent, statuses.append)

    connector = RecordingConnector(FailingConnectionContext())
    client = BinanceTradeStreamClient(
        config=BinanceTradeStreamClientConfig(
            symbol="BTCUSDT",
            reconnect_delay_seconds=0,
            max_reconnect_attempts=2,
        ),
        event_bus=event_bus,
        connector=connector,
    )

    await client.run()

    assert len(connector.uris) == 2
    assert [status.status for status in statuses] == [
        MarketDataConnectionStatus.CONNECTING,
        MarketDataConnectionStatus.ERROR,
        MarketDataConnectionStatus.RECONNECTING,
        MarketDataConnectionStatus.CONNECTING,
        MarketDataConnectionStatus.ERROR,
        MarketDataConnectionStatus.STOPPED,
    ]
