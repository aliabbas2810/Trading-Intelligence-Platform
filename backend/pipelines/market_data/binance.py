from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol, SupportsFloat, SupportsIndex, cast

from backend.config.settings import PlatformSettings
from backend.core import EventBus, get_logger
from backend.models.domain import Trade
from backend.pipelines.market_data.events import (
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
    TradeReceivedEvent,
)


BINANCE_SPOT_STREAM_BASE_URL = "wss://stream.binance.com:9443/ws"
BINANCE_SOURCE = "binance_spot"


class BinanceTradeMessageError(ValueError):
    """Raised when Binance trade messages fail FR-103 validation."""


class WebSocketConnection(Protocol):
    def __aiter__(self) -> AsyncIterator[str]:
        """Yield raw websocket text messages."""


class WebSocketConnector(Protocol):
    def __call__(self, uri: str) -> AbstractAsyncContextManager[WebSocketConnection]:
        """Open a websocket connection for FR-101."""


def default_websocket_connector(uri: str) -> AbstractAsyncContextManager[WebSocketConnection]:
    from websockets.asyncio.client import connect

    return cast(AbstractAsyncContextManager[WebSocketConnection], connect(uri))


class EventBusMarketDataPipeline:
    """Publishes normalized trades to the synchronous event bus for user-specified FR-109."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def publish_trade(self, trade: Trade) -> None:
        self._event_bus.publish(TradeReceivedEvent(trade=trade))


class BinanceTradeMessageParser:
    """Normalize Binance Spot trade messages into canonical Trade objects."""

    def parse(self, message: object) -> Trade:
        """Validate and normalize Binance trade payloads for FR-103 and user FR-104/FR-105."""

        payload = self._coerce_payload(message)
        self._require_trade_event(payload)

        symbol = self._read_str(payload, "s")
        price = self._read_positive_float(payload, "p")
        quantity = self._read_positive_float(payload, "q")
        timestamp_ms = self._read_timestamp_ms(payload)

        try:
            return Trade(
                symbol=symbol,
                price=price,
                quantity=quantity,
                timestamp_ms=timestamp_ms,
                source=BINANCE_SOURCE,
            )
        except ValueError as exc:
            raise BinanceTradeMessageError(str(exc)) from exc

    def _coerce_payload(self, message: object) -> Mapping[str, object]:
        if isinstance(message, str):
            try:
                decoded = json.loads(message)
            except json.JSONDecodeError as exc:
                raise BinanceTradeMessageError("Binance message is not valid JSON") from exc
            if not isinstance(decoded, Mapping):
                raise BinanceTradeMessageError("Binance message must decode to an object")
            return cast(Mapping[str, object], decoded)

        if isinstance(message, Mapping):
            return cast(Mapping[str, object], message)

        raise BinanceTradeMessageError("Binance message must be a mapping or JSON string")

    def _require_trade_event(self, payload: Mapping[str, object]) -> None:
        event_type = payload.get("e")
        if event_type != "trade":
            raise BinanceTradeMessageError("Binance message is not a trade event")

    def _read_str(self, payload: Mapping[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise BinanceTradeMessageError(f"Binance field {key!r} must be a non-empty string")
        return value

    def _read_positive_float(self, payload: Mapping[str, object], key: str) -> float:
        value = payload.get(key)
        if not isinstance(value, str | bytes | SupportsFloat | SupportsIndex):
            raise BinanceTradeMessageError(f"Binance field {key!r} must be numeric")
        try:
            number = float(value)
        except ValueError as exc:
            raise BinanceTradeMessageError(f"Binance field {key!r} must be numeric") from exc
        if number <= 0:
            raise BinanceTradeMessageError(f"Binance field {key!r} must be positive")
        return number

    def _read_timestamp_ms(self, payload: Mapping[str, object]) -> int:
        value = payload.get("T")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BinanceTradeMessageError("Binance field 'T' must be a non-negative UTC ms integer")
        return value


@dataclass(frozen=True, slots=True)
class BinanceTradeStreamClientConfig:
    symbol: str
    reconnect_delay_seconds: float = 1.0
    max_reconnect_attempts: int | None = None


class BinanceTradeStreamClient:
    """Binance Spot trade stream client skeleton for FR-101 and FR-102."""

    def __init__(
        self,
        config: BinanceTradeStreamClientConfig,
        event_bus: EventBus,
        parser: BinanceTradeMessageParser | None = None,
        pipeline: EventBusMarketDataPipeline | None = None,
        connector: WebSocketConnector | None = None,
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._parser = parser or BinanceTradeMessageParser()
        self._pipeline = pipeline or EventBusMarketDataPipeline(event_bus)
        self._connector = connector or default_websocket_connector
        self._logger = get_logger(__name__)
        self._stop_requested = False

    @classmethod
    def from_settings(
        cls,
        settings: PlatformSettings,
        event_bus: EventBus,
        *,
        connector: WebSocketConnector | None = None,
    ) -> BinanceTradeStreamClient:
        symbol = settings.market_data.symbols[0]
        return cls(
            config=BinanceTradeStreamClientConfig(symbol=symbol),
            event_bus=event_bus,
            connector=connector,
        )

    @property
    def stream_uri(self) -> str:
        symbol = self._config.symbol.lower()
        return f"{BINANCE_SPOT_STREAM_BASE_URL}/{symbol}@trade"

    def stop(self) -> None:
        self._stop_requested = True

    async def run(self) -> None:
        """Connect and reconnect around stream interruptions for FR-101 and FR-102."""

        attempt = 0
        while not self._stop_requested:
            attempt += 1
            self._publish_status(MarketDataConnectionStatus.CONNECTING, "connecting", attempt)
            try:
                async with self._connector(self.stream_uri) as websocket:
                    self._publish_status(MarketDataConnectionStatus.CONNECTED, "connected", attempt)
                    async for raw_message in websocket:
                        if self._stop_requested:
                            break
                        self.handle_message(raw_message)
            except Exception as exc:
                self._logger.exception("Binance trade stream error")
                self._publish_status(
                    MarketDataConnectionStatus.ERROR,
                    str(exc),
                    attempt,
                )

            if self._stop_requested:
                break
            if self._config.max_reconnect_attempts is not None:
                if attempt >= self._config.max_reconnect_attempts:
                    break

            self._publish_status(MarketDataConnectionStatus.RECONNECTING, "reconnecting", attempt)
            await asyncio.sleep(self._config.reconnect_delay_seconds)

        self._publish_status(MarketDataConnectionStatus.STOPPED, "stopped", attempt)

    def handle_message(self, raw_message: object) -> None:
        """Parse and publish one raw stream message for FR-109."""

        try:
            trade = self._parser.parse(raw_message)
        except BinanceTradeMessageError:
            self._logger.exception("Invalid Binance trade message")
            return

        self._pipeline.publish_trade(trade)

    def _publish_status(
        self,
        status: MarketDataConnectionStatus,
        message: str,
        attempt: int,
    ) -> None:
        self._event_bus.publish(
            MarketDataStatusEvent(
                source=BINANCE_SOURCE,
                symbol=self._config.symbol,
                status=status,
                message=message,
                attempt=attempt,
            ),
        )
