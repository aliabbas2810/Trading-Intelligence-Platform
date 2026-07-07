from __future__ import annotations

from collections.abc import Iterable

from backend.core import EventBus, get_logger
from backend.models.domain import Trade
from backend.pipelines.candle.builder import ClosedCandle, OneMinuteCandleBuilder
from backend.pipelines.candle.events import CandleClosedEvent
from backend.pipelines.market_data import TradeReceivedEvent
from backend.storage.candles import CandleStore


class OneMinuteCandlePipeline:
    """Event-driven 1m candle pipeline for FR-201 through FR-209."""

    def __init__(
        self,
        event_bus: EventBus,
        store: CandleStore,
        builder: OneMinuteCandleBuilder | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._store = store
        self._builder = builder or OneMinuteCandleBuilder()
        self._logger = get_logger(__name__)

    def subscribe(self) -> None:
        self._event_bus.subscribe(TradeReceivedEvent, self._handle_trade_event)

    def reset(self, store: CandleStore) -> None:
        """Reset stateful candle construction for a fresh replay/runtime session."""

        self._store = store
        self._builder = OneMinuteCandleBuilder()

    def handle_trade(self, trade: Trade) -> None:
        closed = self._builder.add_trade(trade)
        self._publish_closed_candles(closed)

    def advance_time(self, timestamp_ms: int, symbol: str) -> None:
        closed = self._builder.advance_time(timestamp_ms, symbol)
        self._publish_closed_candles(closed)

    def _handle_trade_event(self, event: TradeReceivedEvent) -> None:
        self.handle_trade(event.trade)

    def _publish_closed_candles(self, closed_candles: Iterable[ClosedCandle]) -> None:
        for closed in closed_candles:
            self._store.save(closed.candle)
            self._logger.info("Closed 1m candle")
            self._event_bus.publish(
                CandleClosedEvent(
                    candle=closed.candle,
                    is_synthetic=closed.is_synthetic,
                ),
            )
