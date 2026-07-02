from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Timeframe(str, Enum):
    ONE_MINUTE = "1m"
    FOUR_HOUR = "4h"
    DAILY = "1d"
    WEEKLY = "1w"


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    price: float
    quantity: float
    timestamp_ms: int
    source: str = "binance"


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: Timeframe
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)
