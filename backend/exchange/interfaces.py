from __future__ import annotations

from typing import Protocol

from backend.exchange.models import (
    CandlePage,
    ContractMetadata,
    ExchangeHistoricalCandleRequest,
    HistoricalCandleResult,
    RateLimitMetadata,
)


class ExchangeMarketDataAdapter(Protocol):
    """Exchange-agnostic public market-data boundary for EXCHANGE-001."""

    def discover_contracts(self) -> tuple[ContractMetadata, ...]:
        """Return normalized contract metadata."""

    def fetch_historical_candles(
        self,
        request: ExchangeHistoricalCandleRequest,
    ) -> HistoricalCandleResult:
        """Fetch completed historical 1m candles with adapter-level pagination."""

    def fetch_historical_candle_page(
        self,
        request: ExchangeHistoricalCandleRequest,
    ) -> CandlePage:
        """Fetch one deterministic page of completed candles."""

    def fetch_latest_completed_candle_time(self, symbol: str) -> int:
        """Return latest fully completed canonical 1m candle open time."""

    def normalize_symbol(self, exchange_symbol: str) -> str:
        """Normalize exchange-specific symbols into canonical symbols."""

    def get_contract_metadata(self, symbol: str) -> ContractMetadata | None:
        """Return known contract metadata for a canonical or exchange symbol."""

    def get_rate_limit_metadata(self) -> RateLimitMetadata:
        """Return adapter rate-limit metadata where known."""
