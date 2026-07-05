from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class Timeframe(str, Enum):
    ONE_MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    THIRTY_MINUTE = "30m"
    ONE_HOUR = "1h"
    TWO_HOUR = "2h"
    FOUR_HOUR = "4h"
    DAILY = "1d"
    WEEKLY = "1w"


@dataclass(frozen=True, slots=True)
class Trade:
    """Canonical normalized trade model for DATA-001 and FR-103."""

    symbol: str
    price: float
    quantity: float
    timestamp_ms: int
    source: str = "binance"

    def __post_init__(self) -> None:
        """Validate normalized trade data for FR-103 and TEST-001."""

        if not self.symbol:
            raise ValueError("Trade symbol is required")
        if not isfinite(self.price) or self.price <= 0:
            raise ValueError("Trade price must be positive and finite")
        if not isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("Trade quantity must be positive and finite")
        if self.timestamp_ms < 0:
            raise ValueError("Trade timestamp_ms must be non-negative")
        if not self.source:
            raise ValueError("Trade source is required")


@dataclass(frozen=True, slots=True)
class Candle:
    """Canonical OHLCV candle model for DATA-002 and FR-201 through FR-204."""

    symbol: str
    timeframe: Timeframe
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        """Validate completed candle integrity for FR-201 through FR-204."""

        if not self.symbol:
            raise ValueError("Candle symbol is required")
        if self.close_time_ms <= self.open_time_ms:
            raise ValueError("Candle close_time_ms must be after open_time_ms")
        for field_name, value in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
        ):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"Candle {field_name} must be positive and finite")
        if not isfinite(self.volume) or self.volume < 0:
            raise ValueError("Candle volume must be non-negative and finite")
        if self.high < max(self.open, self.close):
            raise ValueError("Candle high must be at least open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("Candle low must be at most open and close")

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)
