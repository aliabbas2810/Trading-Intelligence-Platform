from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.core import EventBus
from backend.engines.replay import HistoricalCandleReplaySource, HistoricalTradeReplaySource, ReplayController
from backend.engines.replay.models import ReplayProgressEvent, ReplayStatus
from backend.models import Candle, Timeframe, Trade
from backend.pipelines.candle import ONE_MINUTE_MS


class ReplaySourceType(str, Enum):
    TRADES = "trades"
    CANDLES = "candles"


@dataclass(frozen=True, slots=True)
class ReplayStatusSnapshot:
    """Runtime replay status for FR-801 through FR-805 and RUNTIME-004."""

    source_type: ReplaySourceType | None
    status: ReplayStatus
    processed_events: int
    total_events: int
    current_timestamp_ms: int | None
    speed_multiplier: float

    @property
    def progress(self) -> float:
        if self.total_events == 0:
            return 0.0
        return self.processed_events / self.total_events


class RuntimeReplayService:
    """Replay API/runtime control layer that reuses the live event bus path."""

    def __init__(self, event_bus: EventBus, *, symbol: str) -> None:
        self._event_bus = event_bus
        self._symbol = symbol
        self._controller = ReplayController(event_bus, HistoricalTradeReplaySource(()))
        self._source_type: ReplaySourceType | None = None
        self._stopped_snapshot = ReplayStatusSnapshot(
            source_type=None,
            status=ReplayStatus.STOPPED,
            processed_events=0,
            total_events=0,
            current_timestamp_ms=None,
            speed_multiplier=1.0,
        )

    def start(
        self,
        *,
        source_type: ReplaySourceType,
        speed_multiplier: float = 1.0,
    ) -> ReplayStatusSnapshot:
        """Start deterministic demo replay using the shared event bus for FR-801 and FR-802."""

        self._source_type = source_type
        self._controller = ReplayController(
            self._event_bus,
            self._demo_source(source_type),
            speed_multiplier=speed_multiplier,
        )
        self._controller.step()
        return self.status()

    def pause(self) -> ReplayStatusSnapshot:
        """Pause replay controls for FR-803."""

        self._controller.pause()
        return self.status()

    def resume(self) -> ReplayStatusSnapshot:
        """Resume replay controls for FR-804 without blocking the API request."""

        if self._controller.status is ReplayStatus.PAUSED:
            self._controller.step()
        return self.status()

    def stop(self) -> ReplayStatusSnapshot:
        """Stop replay controls for FR-801."""

        self._controller.stop()
        self._stopped_snapshot = self.status()
        return self._stopped_snapshot

    def step(self) -> ReplayStatusSnapshot:
        """Publish one replay event through the live event bus for FR-805 and FR-806."""

        self._controller.step()
        return self.status()

    def status(self) -> ReplayStatusSnapshot:
        progress = self._controller.progress
        return ReplayStatusSnapshot(
            source_type=self._source_type,
            status=progress.status,
            processed_events=progress.processed_events,
            total_events=progress.total_events,
            current_timestamp_ms=progress.current_timestamp_ms,
            speed_multiplier=progress.speed_multiplier,
        )

    def _demo_source(self, source_type: ReplaySourceType) -> HistoricalTradeReplaySource | HistoricalCandleReplaySource:
        if source_type is ReplaySourceType.TRADES:
            return HistoricalTradeReplaySource(demo_replay_trades(self._symbol))
        return HistoricalCandleReplaySource(demo_replay_candles(self._symbol))


def demo_replay_trades(symbol: str) -> tuple[Trade, ...]:
    """Create deterministic in-memory replay trades; no network or files required."""

    start_ms = 2_000_000_000_000
    return (
        Trade(symbol=symbol, price=50_000.0, quantity=1.0, timestamp_ms=start_ms, source="demo-replay"),
        Trade(
            symbol=symbol,
            price=50_120.0,
            quantity=1.2,
            timestamp_ms=start_ms + ONE_MINUTE_MS,
            source="demo-replay",
        ),
        Trade(
            symbol=symbol,
            price=50_240.0,
            quantity=1.1,
            timestamp_ms=start_ms + 2 * ONE_MINUTE_MS,
            source="demo-replay",
        ),
    )


def demo_replay_candles(symbol: str) -> tuple[Candle, ...]:
    """Create deterministic completed candles for the candle replay source."""

    start_ms = 2_100_000_000_000
    return tuple(
        Candle(
            symbol=symbol,
            timeframe=Timeframe.ONE_MINUTE,
            open_time_ms=start_ms + index * ONE_MINUTE_MS,
            close_time_ms=start_ms + (index + 1) * ONE_MINUTE_MS,
            open=51_000.0 + index * 100.0,
            high=51_140.0 + index * 100.0,
            low=50_940.0 + index * 100.0,
            close=51_080.0 + index * 100.0,
            volume=10.0 + index,
        )
        for index in range(3)
    )


def snapshot_from_progress(
    progress: ReplayProgressEvent,
    *,
    source_type: ReplaySourceType | None,
) -> ReplayStatusSnapshot:
    return ReplayStatusSnapshot(
        source_type=source_type,
        status=progress.status,
        processed_events=progress.processed_events,
        total_events=progress.total_events,
        current_timestamp_ms=progress.current_timestamp_ms,
        speed_multiplier=progress.speed_multiplier,
    )
