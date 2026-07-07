from __future__ import annotations

from backend.core import EventBus, get_logger
from backend.models.domain import Candle, Timeframe
from backend.pipelines.candle import CandleClosedEvent
from backend.pipelines.timeframe.aggregation import AGGREGATED_TIMEFRAMES, TimeframeAggregator
from backend.pipelines.timeframe.events import TimeframeCandleClosedEvent
from backend.storage import CandleStore


class TimeframePipeline:
    """Event-driven higher-timeframe pipeline for FR-301 through FR-306."""

    def __init__(
        self,
        event_bus: EventBus,
        store: CandleStore,
        timeframes: tuple[Timeframe, ...] = AGGREGATED_TIMEFRAMES,
    ) -> None:
        self._event_bus = event_bus
        self._store = store
        self._aggregators = tuple(TimeframeAggregator(timeframe) for timeframe in timeframes)
        self._logger = get_logger(__name__)

    def subscribe(self) -> None:
        self._event_bus.subscribe(CandleClosedEvent, self._handle_candle_closed_event)

    def reset(self, store: CandleStore) -> None:
        """Reset stateful higher-timeframe aggregation for a fresh replay/runtime session."""

        self._store = store
        self._aggregators = tuple(
            TimeframeAggregator(aggregator.timeframe) for aggregator in self._aggregators
        )

    def handle_one_minute_candle(self, candle: Candle) -> tuple[Candle, ...]:
        completed: list[Candle] = []
        for aggregator in self._aggregators:
            higher_timeframe_candle = aggregator.add_candle(candle)
            if higher_timeframe_candle is None:
                continue

            self._store.save(higher_timeframe_candle)
            self._logger.info("Closed higher-timeframe candle")
            self._event_bus.publish(TimeframeCandleClosedEvent(candle=higher_timeframe_candle))
            completed.append(higher_timeframe_candle)

        return tuple(completed)

    def _handle_candle_closed_event(self, event: CandleClosedEvent) -> None:
        self.handle_one_minute_candle(event.candle)
