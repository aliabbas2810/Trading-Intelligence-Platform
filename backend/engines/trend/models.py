from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.engines.structure import BreakDirection
from backend.models.domain import Timeframe


class TrendState(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    TRANSITION = "transition"


class TrendFlipMode(str, Enum):
    IMMEDIATE = "immediate"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class TrendStrength:
    """Simple deterministic trend strength placeholder for M6."""

    confirming_structure_count: int


@dataclass(frozen=True, slots=True)
class TrendUpdate:
    """Trend classification update for FR-501, FR-502, FR-503, and FR-505."""

    symbol: str
    timeframe: Timeframe
    state: TrendState
    previous_state: TrendState | None
    strength: TrendStrength
    reason: str
    event_time_ms: int


@dataclass(frozen=True, slots=True)
class PendingTrendFlip:
    direction: BreakDirection
    target_state: TrendState
