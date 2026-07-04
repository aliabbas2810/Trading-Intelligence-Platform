from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.models.domain import Trade


class MarketDataConnectionStatus(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class MarketDataStatusEvent:
    """Lifecycle event for FR-101, FR-102, and LOG-002."""

    source: str
    symbol: str
    status: MarketDataConnectionStatus
    message: str
    attempt: int = 0


@dataclass(frozen=True, slots=True)
class TradeReceivedEvent:
    """Published when a trade is normalized for user-specified FR-109."""

    trade: Trade
