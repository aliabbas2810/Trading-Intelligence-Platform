from __future__ import annotations

from typing import Protocol

from backend.models.domain import Trade


class TradeMessageParser(Protocol):
    """Parser boundary for FR-103 normalized market data."""

    def parse(self, message: object) -> Trade:
        """Convert one exchange-specific message into a canonical Trade."""


class MarketDataPipeline(Protocol):
    """Market data pipeline interface for FR-101 and user-specified FR-109."""

    def publish_trade(self, trade: Trade) -> None:
        """Publish a normalized trade into the shared processing path."""
