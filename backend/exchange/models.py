from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from backend.models import Candle, Timeframe


class ExchangeName(str, Enum):
    BITMART = "bitmart"


class MarketType(str, Enum):
    USDT_M_PERPETUAL = "usdt_m_perpetual"


class ContractStatus(str, Enum):
    TRADING = "trading"
    PAUSED = "paused"
    DELISTED = "delisted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ContractMetadata:
    """Exchange-independent contract metadata for EXCHANGE-001..004."""

    exchange: ExchangeName
    exchange_symbol: str
    canonical_symbol: str
    base_asset: str
    quote_asset: str
    market_type: MarketType
    status: ContractStatus
    price_tick_size: float | None = None
    quantity_step_size: float | None = None
    listing_time_ms: int | None = None
    is_perpetual: bool = False
    is_active: bool = False
    metadata_time_ms: int | None = None
    raw_metadata: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.exchange_symbol or not self.canonical_symbol:
            raise ValueError("contract symbols are required")
        if not self.base_asset or not self.quote_asset:
            raise ValueError("contract assets are required")
        object.__setattr__(self, "raw_metadata", MappingProxyType(dict(self.raw_metadata)))


@dataclass(frozen=True, slots=True)
class ExchangeHistoricalCandleRequest:
    """Generic completed-candle request for EXCHANGE-005 and SYNC-003."""

    exchange: ExchangeName
    market_type: MarketType
    symbol: str
    timeframe: Timeframe
    start_time_ms: int
    end_time_ms: int
    limit: int = 500

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("Historical request symbol is required")
        if self.timeframe is not Timeframe.ONE_MINUTE:
            raise ValueError("M31 synchronization uses 1m as canonical history")
        if self.start_time_ms < 0 or self.end_time_ms <= self.start_time_ms:
            raise ValueError("Historical request time range is invalid")
        if self.limit <= 0:
            raise ValueError("Historical request limit must be positive")


@dataclass(frozen=True, slots=True)
class CandlePage:
    candles: tuple[Candle, ...]
    next_start_time_ms: int | None
    complete: bool


@dataclass(frozen=True, slots=True)
class HistoricalCandleResult:
    request: ExchangeHistoricalCandleRequest
    candles: tuple[Candle, ...]
    pages: int
    latest_completed_time_ms: int


@dataclass(frozen=True, slots=True)
class RateLimitMetadata:
    requests_per_second: float | None = None
    page_size: int | None = None
