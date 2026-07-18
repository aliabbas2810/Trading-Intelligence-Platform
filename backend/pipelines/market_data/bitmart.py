from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from backend.core import EventBus
from backend.models.domain import Trade
from backend.pipelines.market_data.events import (
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
    TradeReceivedEvent,
)


BITMART_SOURCE = "bitmart_usdt_m_perpetual"
BITMART_FUTURES_PUBLIC_WS_URL = "wss://openapi-ws-v2.bitmart.com/api?protocol=1.1"
BITMART_FUTURES_TRADE_CHANNEL = "futures/trade"


class EventBusMarketDataPipeline:
    """Publishes normalized exchange trades to the synchronous event bus for FR-109."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def publish_trade(self, trade: Trade) -> None:
        self._event_bus.publish(TradeReceivedEvent(trade=trade))


@dataclass(frozen=True, slots=True)
class BitMartTradeStreamClientConfig:
    symbol: str
    websocket_url: str = BITMART_FUTURES_PUBLIC_WS_URL
    heartbeat_seconds: float = 15.0
    reconnect_delay_seconds: float = 1.0
    max_reconnect_attempts: int | None = None


@dataclass(frozen=True, slots=True)
class BitMartTradeStreamDiagnostics:
    websocket_endpoint: str
    subscription_channel: str
    subscription_acknowledged: bool = False
    connected: bool = False
    connected_at_ms: int | None = None
    last_message_time_ms: int | None = None
    last_trade_time_ms: int | None = None
    duplicate_trade_count: int = 0
    malformed_trade_count: int = 0
    reconnect_attempt_count: int = 0
    last_stream_error: str | None = None


class WebSocketConnection(Protocol):
    async def send(self, message: str) -> None:
        """Send one text frame."""

    async def recv(self) -> str:
        """Receive one text frame."""

    async def close(self) -> None:
        """Close the connection."""


class WebSocketConnector(Protocol):
    def __call__(self, uri: str) -> Any:
        """Return an async context manager yielding a websocket connection."""


class BitMartTradeMessageParser:
    """Parse BitMart futures public trade messages into canonical Trade objects for FR-103."""

    def __init__(self, *, symbol: str) -> None:
        self.symbol = symbol
        self.group = subscription_channel(symbol)

    def subscribe_payload(self) -> str:
        return json.dumps({"action": "subscribe", "args": [self.group]}, separators=(",", ":"))

    def parse(self, message: str) -> tuple[Trade, ...]:
        if message == "pong":
            return ()
        payload = json.loads(message)
        if not isinstance(payload, dict):
            raise ValueError("BitMart message must be an object")
        if payload.get("success") is False:
            raise ValueError(f"BitMart stream error: {payload.get('error', 'unknown')}")
        if payload.get("action") == "subscribe":
            return ()
        if payload.get("group") != self.group:
            return ()
        data = payload.get("data")
        rows = data if isinstance(data, list) else [data]
        trades: list[Trade] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("BitMart trade row must be an object")
            trades.append(self._parse_trade_row(cast(dict[str, object], row)))
        return tuple(trades)

    def is_subscription_ack(self, message: str) -> bool:
        payload = json.loads(message)
        return (
            isinstance(payload, dict)
            and payload.get("action") == "subscribe"
            and payload.get("group") == self.group
            and payload.get("success") is True
        )

    def trade_identity(self, message_trade: Trade, raw_row: dict[str, object] | None = None) -> tuple[object, ...]:
        if raw_row is not None and raw_row.get("trade_id") is not None:
            return (BITMART_SOURCE, self.symbol, raw_row["trade_id"])
        return (
            BITMART_SOURCE,
            message_trade.symbol,
            message_trade.timestamp_ms,
            message_trade.price,
            message_trade.quantity,
        )

    def _parse_trade_row(self, row: dict[str, object]) -> Trade:
        symbol = str(row["symbol"])
        if symbol != self.symbol:
            raise ValueError(f"Unexpected BitMart trade symbol: {symbol}")
        return Trade(
            symbol=symbol,
            price=float(str(row["deal_price"])),
            quantity=float(str(row["deal_vol"])),
            timestamp_ms=parse_bitmart_created_at_ms(str(row["created_at"])),
            source=BITMART_SOURCE,
        )


class BitMartTradeStreamClient:
    """BitMart USDT-M public trade WebSocket client for FR-101/FR-102/FR-103."""

    def __init__(
        self,
        *,
        config: BitMartTradeStreamClientConfig,
        event_bus: EventBus,
        pipeline: EventBusMarketDataPipeline | None = None,
        connector: WebSocketConnector | None = None,
        clock_ms: Any | None = None,
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._pipeline = pipeline or EventBusMarketDataPipeline(event_bus)
        self._parser = BitMartTradeMessageParser(symbol=config.symbol)
        self._connector = connector
        self._clock_ms = clock_ms or current_time_ms
        self._stop_requested = False
        self._thread: threading.Thread | None = None
        self._seen_trade_keys: set[tuple[object, ...]] = set()
        self._diagnostics = BitMartTradeStreamDiagnostics(
            websocket_endpoint=config.websocket_url,
            subscription_channel=subscription_channel(config.symbol),
        )

    @property
    def diagnostics(self) -> BitMartTradeStreamDiagnostics:
        return self._diagnostics

    @property
    def subscription_acknowledged(self) -> bool:
        return self._diagnostics.subscription_acknowledged

    def start_background(self) -> None:
        """Start the real websocket loop on a daemon thread for local runtime live mode."""

        self._stop_requested = False
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=lambda: asyncio.run(self.run_forever()), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested = True
        self._publish_status(MarketDataConnectionStatus.STOPPED, "stopped", 0)

    def start_unavailable(self) -> None:
        """Legacy diagnostic hook for tests/configurations that intentionally disable live WebSocket."""

        self._publish_status(MarketDataConnectionStatus.ERROR, "bitmart_live_stream_unavailable", 0)

    async def run_forever(self) -> None:
        """Connect, subscribe, parse trades, and reconnect on disconnect for FR-101/FR-102."""

        attempt = 0
        while not self._stop_requested:
            attempt += 1
            self._diagnostics = replace_diagnostics(
                self._diagnostics,
                reconnect_attempt_count=max(0, attempt - 1),
                last_stream_error=None,
            )
            self._publish_status(MarketDataConnectionStatus.CONNECTING, "connecting", attempt)
            try:
                await self._run_once()
                if not self._stop_requested:
                    self._publish_status(MarketDataConnectionStatus.DISCONNECTED, "disconnected", attempt)
            except Exception as exc:  # pragma: no cover - exercised through deterministic fakes
                self._diagnostics = replace_diagnostics(
                    self._diagnostics,
                    connected=False,
                    last_stream_error=str(exc),
                )
                self._publish_status(MarketDataConnectionStatus.ERROR, str(exc), attempt)
            if self._stop_requested:
                break
            if self._config.max_reconnect_attempts is not None and attempt >= self._config.max_reconnect_attempts:
                break
            self._publish_status(MarketDataConnectionStatus.RECONNECTING, "reconnecting", attempt)
            await asyncio.sleep(self._config.reconnect_delay_seconds)

    async def _run_once(self) -> None:
        connector = self._connector
        if connector is None:
            import websockets

            connector = websockets.connect
        async with connector(self._config.websocket_url) as websocket:
            self._diagnostics = replace_diagnostics(
                self._diagnostics,
                connected=True,
                connected_at_ms=self._clock_ms(),
            )
            await websocket.send(self._parser.subscribe_payload())
            while not self._stop_requested:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=self._config.heartbeat_seconds)
                except TimeoutError:
                    await websocket.send('{"action":"ping"}')
                    continue
                self.handle_text_message(message)

    def publish_trade(self, trade: Trade) -> None:
        """Publish an injected canonical BitMart trade without parsing exchange DTOs."""

        self._pipeline.publish_trade(trade)

    def handle_text_message(self, message: str) -> tuple[Trade, ...]:
        """Handle one BitMart websocket text message for deterministic tests and live mode."""

        self._diagnostics = replace_diagnostics(
            self._diagnostics,
            last_message_time_ms=self._clock_ms(),
        )
        try:
            if self._parser.is_subscription_ack(message):
                self._diagnostics = replace_diagnostics(self._diagnostics, subscription_acknowledged=True)
                self._publish_status(MarketDataConnectionStatus.CONNECTED, "subscribed", 0)
                return ()
            trades = self._parse_trades_with_identity(message)
        except Exception as exc:
            self._diagnostics = replace_diagnostics(
                self._diagnostics,
                malformed_trade_count=self._diagnostics.malformed_trade_count + 1,
                last_stream_error=str(exc),
            )
            return ()
        published: list[Trade] = []
        for trade, identity in trades:
            if identity in self._seen_trade_keys:
                self._diagnostics = replace_diagnostics(
                    self._diagnostics,
                    duplicate_trade_count=self._diagnostics.duplicate_trade_count + 1,
                )
                continue
            self._seen_trade_keys.add(identity)
            self._diagnostics = replace_diagnostics(
                self._diagnostics,
                last_trade_time_ms=trade.timestamp_ms,
            )
            self.publish_trade(trade)
            published.append(trade)
        return tuple(published)

    def _parse_trades_with_identity(self, message: str) -> tuple[tuple[Trade, tuple[object, ...]], ...]:
        payload = json.loads(message)
        if not isinstance(payload, dict):
            raise ValueError("BitMart message must be an object")
        if payload.get("success") is False:
            raise ValueError(f"BitMart stream error: {payload.get('error', 'unknown')}")
        if payload.get("group") != self._parser.group:
            return ()
        data = payload.get("data")
        rows = data if isinstance(data, list) else [data]
        parsed: list[tuple[Trade, tuple[object, ...]]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("BitMart trade row must be an object")
            raw = cast(dict[str, object], row)
            trade = self._parser._parse_trade_row(raw)
            parsed.append((trade, self._parser.trade_identity(trade, raw)))
        return tuple(parsed)

    def _publish_status(
        self,
        status: MarketDataConnectionStatus,
        message: str,
        attempt: int,
    ) -> None:
        self._event_bus.publish(
            MarketDataStatusEvent(
                source=BITMART_SOURCE,
                symbol=self._config.symbol,
                status=status,
                message=message,
                attempt=attempt,
            ),
        )


class BitMartWebSocketLiveStreamRunner:
    """Synchronous runtime adapter around the asynchronous BitMart WebSocket client."""

    def __init__(self, client: BitMartTradeStreamClient) -> None:
        self._client = client

    def start(self) -> None:
        self._client.start_background()

    def stop(self) -> None:
        self._client.stop()


def subscription_channel(symbol: str) -> str:
    return f"{BITMART_FUTURES_TRADE_CHANNEL}:{symbol}"


def parse_bitmart_created_at_ms(value: str) -> int:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    if "." in value:
        prefix, suffix = value.split(".", 1)
        fraction, timezone = suffix[:6], suffix[6:]
        value = f"{prefix}.{fraction.ljust(6, '0')}{timezone}"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def current_time_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def replace_diagnostics(
    diagnostics: BitMartTradeStreamDiagnostics,
    **updates: Any,
) -> BitMartTradeStreamDiagnostics:
    return replace(diagnostics, **updates)
