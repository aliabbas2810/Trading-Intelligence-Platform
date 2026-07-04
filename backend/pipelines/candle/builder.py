from __future__ import annotations

from dataclasses import dataclass

from backend.models.domain import Candle, Timeframe, Trade


ONE_MINUTE_MS = 60_000


@dataclass(slots=True)
class _WorkingCandle:
    symbol: str
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_trade(cls, trade: Trade, open_time_ms: int) -> _WorkingCandle:
        return cls(
            symbol=trade.symbol,
            open_time_ms=open_time_ms,
            open=trade.price,
            high=trade.price,
            low=trade.price,
            close=trade.price,
            volume=trade.quantity,
        )

    def add_trade(self, trade: Trade) -> None:
        self.high = max(self.high, trade.price)
        self.low = min(self.low, trade.price)
        self.close = trade.price
        self.volume += trade.quantity

    def finalize(self) -> Candle:
        return Candle(
            symbol=self.symbol,
            timeframe=Timeframe.ONE_MINUTE,
            open_time_ms=self.open_time_ms,
            close_time_ms=self.open_time_ms + ONE_MINUTE_MS,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
        )


@dataclass(frozen=True, slots=True)
class ClosedCandle:
    candle: Candle
    is_synthetic: bool = False


class LateTradeError(ValueError):
    """Raised when a trade would mutate an already completed candle."""


class OneMinuteCandleBuilder:
    """Deterministic UTC-aligned 1m candle builder for FR-201 through FR-209."""

    def __init__(self) -> None:
        self._current: _WorkingCandle | None = None
        self._previous_close: float | None = None
        self._next_expected_open_time_ms: int | None = None

    def add_trade(self, trade: Trade) -> list[ClosedCandle]:
        """Apply a trade and close/fill earlier UTC minutes when needed."""

        trade_open_time_ms = floor_to_minute_ms(trade.timestamp_ms)
        closed = self._close_before(trade.symbol, trade_open_time_ms)

        if self._next_expected_open_time_ms is not None:
            if trade_open_time_ms < self._next_expected_open_time_ms:
                raise LateTradeError("Trade belongs to an already completed candle")

        if self._current is None:
            self._current = _WorkingCandle.from_trade(trade, trade_open_time_ms)
            return closed

        if trade.symbol != self._current.symbol:
            raise LateTradeError("Trade symbol does not match the active candle")
        if trade_open_time_ms != self._current.open_time_ms:
            raise LateTradeError("Trade timestamp is not in the active candle minute")

        self._current.add_trade(trade)
        return closed

    def advance_time(self, timestamp_ms: int, symbol: str) -> list[ClosedCandle]:
        """Close all completed UTC minutes at or before timestamp_ms for FR-205."""

        if timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")

        cutoff_open_time_ms = floor_to_minute_ms(timestamp_ms)
        if timestamp_ms % ONE_MINUTE_MS == 0:
            cutoff_open_time_ms = timestamp_ms

        closed: list[ClosedCandle] = []
        if self._current is not None:
            current_close_time_ms = self._current.open_time_ms + ONE_MINUTE_MS
            if current_close_time_ms <= timestamp_ms:
                closed.append(self._finalize_current())

        closed.extend(self._fill_synthetic_until(symbol, cutoff_open_time_ms, inclusive=False))
        return closed

    def _close_before(self, symbol: str, open_time_ms: int) -> list[ClosedCandle]:
        closed: list[ClosedCandle] = []
        if self._current is not None and self._current.open_time_ms < open_time_ms:
            closed.append(self._finalize_current())

        closed.extend(self._fill_synthetic_until(symbol, open_time_ms, inclusive=False))
        return closed

    def _finalize_current(self) -> ClosedCandle:
        if self._current is None:
            raise RuntimeError("No active candle to finalize")

        candle = self._current.finalize()
        self._previous_close = candle.close
        self._next_expected_open_time_ms = candle.close_time_ms
        self._current = None
        return ClosedCandle(candle=candle)

    def _fill_synthetic_until(
        self,
        symbol: str,
        open_time_ms: int,
        *,
        inclusive: bool,
    ) -> list[ClosedCandle]:
        closed: list[ClosedCandle] = []

        while self._should_fill_synthetic(open_time_ms, inclusive):
            if self._previous_close is None or self._next_expected_open_time_ms is None:
                break
            candle = self._make_synthetic_candle(symbol, self._next_expected_open_time_ms)
            closed.append(ClosedCandle(candle=candle, is_synthetic=True))
            self._previous_close = candle.close
            self._next_expected_open_time_ms = candle.close_time_ms

        return closed

    def _should_fill_synthetic(self, open_time_ms: int, inclusive: bool) -> bool:
        if self._next_expected_open_time_ms is None:
            return False
        if inclusive:
            return self._next_expected_open_time_ms <= open_time_ms
        return self._next_expected_open_time_ms < open_time_ms

    def _make_synthetic_candle(self, symbol: str, open_time_ms: int) -> Candle:
        if self._previous_close is None:
            raise RuntimeError("Cannot synthesize candle without previous close")
        return Candle(
            symbol=symbol,
            timeframe=Timeframe.ONE_MINUTE,
            open_time_ms=open_time_ms,
            close_time_ms=open_time_ms + ONE_MINUTE_MS,
            open=self._previous_close,
            high=self._previous_close,
            low=self._previous_close,
            close=self._previous_close,
            volume=0.0,
        )


def floor_to_minute_ms(timestamp_ms: int) -> int:
    """Normalize timestamps to UTC minute boundaries for FR-205."""

    if timestamp_ms < 0:
        raise ValueError("timestamp_ms must be non-negative")
    return timestamp_ms - (timestamp_ms % ONE_MINUTE_MS)
