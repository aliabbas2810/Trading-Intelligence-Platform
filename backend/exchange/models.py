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


class HistoricalIntegrityPolicy(str, Enum):
    STRICT = "strict"
    WARN = "warn"
    ALLOW = "allow"


class HistoricalIntegrityStatus(str, Enum):
    VALID = "valid"
    DEGRADED = "degraded"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class HistoricalGapRecoveryStatus(str, Enum):
    RECOVERED = "recovered"
    UNRECOVERABLE = "unrecoverable"


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
    integrity_policy: HistoricalIntegrityPolicy = HistoricalIntegrityPolicy.STRICT

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("Historical request symbol is required")
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
    integrity_report: HistoricalIntegrityReport | None = None


@dataclass(frozen=True, slots=True)
class HistoricalDataGap:
    symbol: str
    timeframe: Timeframe
    start_open_time_ms: int
    end_open_time_ms: int
    missing_candle_count: int
    missing_open_times_ms: tuple[int, ...]
    retry_count: int
    exchange: ExchangeName
    recovery_status: HistoricalGapRecoveryStatus
    detected_at_ms: int


@dataclass(frozen=True, slots=True)
class HistoricalIntegrityReport:
    policy: HistoricalIntegrityPolicy
    status: HistoricalIntegrityStatus
    gap_count: int
    total_missing_candles: int
    gaps: tuple[HistoricalDataGap, ...]
    requested_candle_count: int
    loaded_candle_count: int
    complete: bool
    exchange: ExchangeName
    market_type: MarketType
    symbol: str
    timeframe: Timeframe
    start_time_ms: int
    end_time_ms: int
    exchange_candle_count: int = 0
    synthetic_candle_count: int = 0
    canonical_candle_count: int = 0

    @classmethod
    def valid(
        cls,
        request: ExchangeHistoricalCandleRequest,
        *,
        requested_candle_count: int,
        loaded_candle_count: int,
        exchange_candle_count: int | None = None,
        synthetic_candle_count: int = 0,
        canonical_candle_count: int | None = None,
    ) -> HistoricalIntegrityReport:
        final_exchange_count = loaded_candle_count if exchange_candle_count is None else exchange_candle_count
        final_canonical_count = loaded_candle_count if canonical_candle_count is None else canonical_candle_count
        return cls(
            policy=request.integrity_policy,
            status=HistoricalIntegrityStatus.VALID,
            gap_count=0,
            total_missing_candles=0,
            gaps=(),
            requested_candle_count=requested_candle_count,
            loaded_candle_count=loaded_candle_count,
            complete=True,
            exchange=request.exchange,
            market_type=request.market_type,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_time_ms=request.start_time_ms,
            end_time_ms=request.end_time_ms,
            exchange_candle_count=final_exchange_count,
            synthetic_candle_count=synthetic_candle_count,
            canonical_candle_count=final_canonical_count,
        )

    @classmethod
    def from_gaps(
        cls,
        request: ExchangeHistoricalCandleRequest,
        *,
        status: HistoricalIntegrityStatus,
        gaps: tuple[HistoricalDataGap, ...],
        requested_candle_count: int,
        loaded_candle_count: int,
        exchange_candle_count: int | None = None,
        synthetic_candle_count: int = 0,
        canonical_candle_count: int | None = None,
    ) -> HistoricalIntegrityReport:
        final_exchange_count = loaded_candle_count if exchange_candle_count is None else exchange_candle_count
        final_canonical_count = loaded_candle_count if canonical_candle_count is None else canonical_candle_count
        return cls(
            policy=request.integrity_policy,
            status=status,
            gap_count=len(gaps),
            total_missing_candles=sum(gap.missing_candle_count for gap in gaps),
            gaps=gaps,
            requested_candle_count=requested_candle_count,
            loaded_candle_count=loaded_candle_count,
            complete=False,
            exchange=request.exchange,
            market_type=request.market_type,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_time_ms=request.start_time_ms,
            end_time_ms=request.end_time_ms,
            exchange_candle_count=final_exchange_count,
            synthetic_candle_count=synthetic_candle_count,
            canonical_candle_count=final_canonical_count,
        )


@dataclass(frozen=True, slots=True)
class RateLimitMetadata:
    requests_per_second: float | None = None
    page_size: int | None = None
