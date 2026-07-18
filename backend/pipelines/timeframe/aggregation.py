from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.models.domain import Candle, Timeframe


ONE_MINUTE_MS = 60_000


FIVE_MINUTE_MS = 5 * ONE_MINUTE_MS
FIFTEEN_MINUTE_MS = 15 * ONE_MINUTE_MS
THIRTY_MINUTE_MS = 30 * ONE_MINUTE_MS
ONE_HOUR_MS = 60 * ONE_MINUTE_MS
TWO_HOUR_MS = 2 * ONE_HOUR_MS
FOUR_HOUR_MS = 4 * 60 * ONE_MINUTE_MS
DAILY_MS = 24 * 60 * ONE_MINUTE_MS
WEEKLY_MS = 7 * DAILY_MS
AGGREGATED_TIMEFRAMES = (
    Timeframe.FIVE_MINUTE,
    Timeframe.FIFTEEN_MINUTE,
    Timeframe.THIRTY_MINUTE,
    Timeframe.ONE_HOUR,
    Timeframe.TWO_HOUR,
    Timeframe.FOUR_HOUR,
    Timeframe.DAILY,
    Timeframe.WEEKLY,
)


class TimeframeAggregationError(ValueError):
    """Raised when one-minute candle input cannot be aggregated deterministically."""


@dataclass(slots=True)
class _WorkingTimeframeCandle:
    symbol: str
    timeframe: Timeframe
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    complete_from_open: bool

    @classmethod
    def from_candle(
        cls,
        candle: Candle,
        timeframe: Timeframe,
        open_time_ms: int,
        close_time_ms: int,
        *,
        require_full_bucket_from_open: bool = False,
    ) -> _WorkingTimeframeCandle:
        return cls(
            symbol=candle.symbol,
            timeframe=timeframe,
            open_time_ms=open_time_ms,
            close_time_ms=close_time_ms,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            complete_from_open=(not require_full_bucket_from_open or candle.open_time_ms == open_time_ms),
        )

    def add_candle(self, candle: Candle) -> None:
        self.high = max(self.high, candle.high)
        self.low = min(self.low, candle.low)
        self.close = candle.close
        self.volume += candle.volume

    def finalize(self) -> Candle:
        return Candle(
            symbol=self.symbol,
            timeframe=self.timeframe,
            open_time_ms=self.open_time_ms,
            close_time_ms=self.close_time_ms,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


@dataclass(frozen=True, slots=True)
class DiscardedAggregationBucket:
    """Incomplete higher-timeframe bucket discarded at a known data gap."""

    timeframe: Timeframe
    open_time_ms: int
    close_time_ms: int


class TimeframeAggregator:
    """Aggregate completed 1m candles into one higher timeframe for FR-301 through FR-305."""

    def __init__(self, timeframe: Timeframe) -> None:
        if timeframe not in AGGREGATED_TIMEFRAMES:
            raise ValueError("TimeframeAggregator only supports configured higher timeframes")

        self._timeframe = timeframe
        self._current: _WorkingTimeframeCandle | None = None
        self._last_input_close_time_ms: int | None = None
        self._require_full_bucket_from_open = False

    @property
    def timeframe(self) -> Timeframe:
        return self._timeframe

    def add_candle(self, candle: Candle) -> Candle | None:
        """Consume one completed 1m candle and emit a higher-timeframe close when complete."""

        self._validate_input_candle(candle)
        bucket_open_time_ms = timeframe_open_time_ms(candle.open_time_ms, self._timeframe)
        bucket_close_time_ms = timeframe_close_time_ms(bucket_open_time_ms, self._timeframe)

        if self._current is None:
            self._current = _WorkingTimeframeCandle.from_candle(
                candle,
                self._timeframe,
                bucket_open_time_ms,
                bucket_close_time_ms,
                require_full_bucket_from_open=self._require_full_bucket_from_open,
            )
        else:
            self._validate_continuity(candle, bucket_open_time_ms)
            self._current.add_candle(candle)

        self._last_input_close_time_ms = candle.close_time_ms
        if candle.close_time_ms == bucket_close_time_ms:
            completed = self._current.finalize() if self._current.complete_from_open else None
            self._current = None
            self._require_full_bucket_from_open = False
            return completed

        return None

    def reset_for_discontinuity(self) -> DiscardedAggregationBucket | None:
        """Discard the current incomplete bucket before starting a new replay segment."""

        if self._current is None:
            self._last_input_close_time_ms = None
            self._require_full_bucket_from_open = True
            return None
        discarded = DiscardedAggregationBucket(
            timeframe=self._current.timeframe,
            open_time_ms=self._current.open_time_ms,
            close_time_ms=self._current.close_time_ms,
        )
        self._current = None
        self._last_input_close_time_ms = None
        self._require_full_bucket_from_open = True
        return discarded

    def _validate_input_candle(self, candle: Candle) -> None:
        if candle.timeframe is not Timeframe.ONE_MINUTE:
            raise TimeframeAggregationError("Higher timeframes must be built from 1m candles only")
        if candle.close_time_ms - candle.open_time_ms != ONE_MINUTE_MS:
            raise TimeframeAggregationError("Input candle must cover exactly one minute")
        if candle.open_time_ms % ONE_MINUTE_MS != 0:
            raise TimeframeAggregationError("Input candle must be UTC minute aligned")
        if self._last_input_close_time_ms is not None:
            if candle.open_time_ms != self._last_input_close_time_ms:
                raise TimeframeAggregationError("Input 1m candles must be contiguous")

    def _validate_continuity(self, candle: Candle, bucket_open_time_ms: int) -> None:
        if self._current is None:
            raise RuntimeError("No active timeframe candle")
        if candle.symbol != self._current.symbol:
            raise TimeframeAggregationError("Input candle symbol changed during aggregation")
        if bucket_open_time_ms != self._current.open_time_ms:
            raise TimeframeAggregationError("Input candle skipped across a timeframe boundary")
        if candle.open_time_ms != self._last_input_close_time_ms:
            raise TimeframeAggregationError("Input 1m candles must be contiguous")


def timeframe_open_time_ms(timestamp_ms: int, timeframe: Timeframe) -> int:
    """Return UTC-aligned timeframe open for FR-304."""

    if timestamp_ms < 0:
        raise ValueError("timestamp_ms must be non-negative")

    if timeframe is Timeframe.WEEKLY:
        return _weekly_open_time_ms(timestamp_ms)
    duration_ms = timeframe_duration_ms(timeframe)
    return timestamp_ms - (timestamp_ms % duration_ms)

    raise ValueError(f"Unsupported timeframe: {timeframe}")


def timeframe_close_time_ms(open_time_ms: int, timeframe: Timeframe) -> int:
    """Return UTC-aligned timeframe close for FR-304."""

    return open_time_ms + timeframe_duration_ms(timeframe)


def timeframe_duration_ms(timeframe: Timeframe) -> int:
    if timeframe is Timeframe.ONE_MINUTE:
        return ONE_MINUTE_MS
    if timeframe is Timeframe.FIVE_MINUTE:
        return FIVE_MINUTE_MS
    if timeframe is Timeframe.FIFTEEN_MINUTE:
        return FIFTEEN_MINUTE_MS
    if timeframe is Timeframe.THIRTY_MINUTE:
        return THIRTY_MINUTE_MS
    if timeframe is Timeframe.ONE_HOUR:
        return ONE_HOUR_MS
    if timeframe is Timeframe.TWO_HOUR:
        return TWO_HOUR_MS
    if timeframe is Timeframe.FOUR_HOUR:
        return FOUR_HOUR_MS
    if timeframe is Timeframe.DAILY:
        return DAILY_MS
    if timeframe is Timeframe.WEEKLY:
        return WEEKLY_MS
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _weekly_open_time_ms(timestamp_ms: int) -> int:
    timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    week_open = timestamp - timedelta(
        days=timestamp.weekday(),
        hours=timestamp.hour,
        minutes=timestamp.minute,
        seconds=timestamp.second,
        microseconds=timestamp.microsecond,
    )
    return int(week_open.timestamp() * 1000)
