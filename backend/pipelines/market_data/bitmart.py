from __future__ import annotations

from dataclasses import dataclass

from backend.core import EventBus
from backend.models.domain import Trade
from backend.pipelines.market_data.events import (
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
    TradeReceivedEvent,
)


BITMART_SOURCE = "bitmart_usdt_m_perpetual"


class EventBusMarketDataPipeline:
    """Publishes normalized exchange trades to the synchronous event bus for FR-109."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def publish_trade(self, trade: Trade) -> None:
        self._event_bus.publish(TradeReceivedEvent(trade=trade))


@dataclass(frozen=True, slots=True)
class BitMartTradeStreamClientConfig:
    symbol: str


class BitMartTradeStreamClient:
    """BitMart USDT-M live stream boundary; WebSocket ingestion is not implemented yet."""

    def __init__(
        self,
        *,
        config: BitMartTradeStreamClientConfig,
        event_bus: EventBus,
        pipeline: EventBusMarketDataPipeline | None = None,
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._pipeline = pipeline or EventBusMarketDataPipeline(event_bus)
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True
        self._publish_status(MarketDataConnectionStatus.STOPPED, "stopped", 0)

    def start_unavailable(self) -> None:
        """Report BitMart live streaming honestly until WebSocket ingestion is implemented."""

        self._publish_status(
            MarketDataConnectionStatus.ERROR,
            "bitmart_live_stream_unavailable",
            0,
        )

    def publish_trade(self, trade: Trade) -> None:
        """Publish an injected canonical BitMart trade without parsing exchange DTOs."""

        self._pipeline.publish_trade(trade)

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
