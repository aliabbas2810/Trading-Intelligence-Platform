from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.engines.replay.models import ReplayStatus
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
    """TradingView-style replay cursor for FR-801 through FR-805.

    The runtime/API replay controls intentionally do not mutate candle stores or
    publish events. They expose a cursor over already-loaded chart history so the
    frontend can hide future candles without destroying the full dataset.
    """

    def __init__(self, *, symbol: str) -> None:
        self._symbol = symbol
        self._source_type: ReplaySourceType | None = None
        self._status = ReplayStatus.READY
        self._processed_events = 0
        self._total_events = 0
        self._current_timestamp_ms: int | None = None
        self._speed_multiplier = 1.0
        self._timestamps: tuple[int, ...] = ()

    def start(
        self,
        *,
        source_type: ReplaySourceType,
        speed_multiplier: float = 1.0,
        start_index: int = 0,
    ) -> ReplayStatusSnapshot:
        """Start a non-destructive chart replay cursor from a selected candle."""

        self._speed_multiplier = validate_speed_multiplier(speed_multiplier)
        self._source_type = source_type
        self._timestamps = self._demo_timestamps(source_type)
        self._total_events = len(self._timestamps)
        if self._total_events == 0:
            self._processed_events = 0
            self._current_timestamp_ms = None
            self._status = ReplayStatus.COMPLETED
            return self.status()

        selected_index = min(max(start_index, 0), self._total_events - 1)
        self._processed_events = selected_index + 1
        self._current_timestamp_ms = self._timestamps[selected_index]
        self._status = ReplayStatus.RUNNING
        return self.status()

    def pause(self) -> ReplayStatusSnapshot:
        """Pause replay controls for FR-803."""

        if self._status is ReplayStatus.RUNNING:
            self._status = ReplayStatus.PAUSED
        return self.status()

    def resume(self) -> ReplayStatusSnapshot:
        """Resume chart replay without draining the remaining cursor range."""

        if self._status is ReplayStatus.PAUSED:
            self._status = ReplayStatus.RUNNING
        return self.status()

    def stop(self) -> ReplayStatusSnapshot:
        """Stop replay controls and let the frontend restore the full chart."""

        self._status = ReplayStatus.STOPPED
        return self.status()

    def step(self) -> ReplayStatusSnapshot:
        """Advance the chart replay cursor by one event for FR-805."""

        if self._status in {ReplayStatus.READY, ReplayStatus.STOPPED, ReplayStatus.COMPLETED}:
            return self.status()
        if self._processed_events >= self._total_events:
            self._status = ReplayStatus.COMPLETED
            return self.status()

        previous_status = self._status
        self._processed_events += 1
        self._current_timestamp_ms = self._timestamps[self._processed_events - 1]
        if self._processed_events >= self._total_events:
            self._status = ReplayStatus.COMPLETED
        else:
            self._status = ReplayStatus.PAUSED if previous_status is ReplayStatus.PAUSED else ReplayStatus.RUNNING
        return self.status()

    def status(self) -> ReplayStatusSnapshot:
        return ReplayStatusSnapshot(
            source_type=self._source_type,
            status=self._status,
            processed_events=self._processed_events,
            total_events=self._total_events,
            current_timestamp_ms=self._current_timestamp_ms,
            speed_multiplier=self._speed_multiplier,
        )

    def _demo_timestamps(self, source_type: ReplaySourceType) -> tuple[int, ...]:
        if source_type is ReplaySourceType.TRADES:
            return tuple(trade.timestamp_ms for trade in demo_replay_trades(self._symbol))
        return tuple(candle.close_time_ms for candle in demo_replay_candles(self._symbol))


def demo_replay_trades(symbol: str) -> tuple[Trade, ...]:
    """Create deterministic in-memory replay trades; no network or files required."""

    start_ms = 2_000_000_000_000
    return tuple(
        Trade(
            symbol=symbol,
            price=50_000.0 + index * 60.0,
            quantity=1.0 + index * 0.05,
            timestamp_ms=start_ms + index * ONE_MINUTE_MS,
            source="demo-replay",
        )
        for index in range(12)
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
            open=51_000.0 + index * 45.0,
            high=51_120.0 + index * 45.0,
            low=50_940.0 + index * 45.0,
            close=51_070.0 + index * 45.0 if index % 2 == 0 else 51_010.0 + index * 45.0,
            volume=10.0 + index,
        )
        for index in range(12)
    )


def validate_speed_multiplier(speed_multiplier: float) -> float:
    if speed_multiplier <= 0:
        raise ValueError("Replay speed_multiplier must be positive")
    return speed_multiplier
