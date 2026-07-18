from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.models.domain import Candle, Timeframe


class SwingKind(str, Enum):
    HIGH = "high"
    LOW = "low"


class StructureLabel(str, Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"


class BreakDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(frozen=True, slots=True)
class BodyRange:
    """Body-only candle values for FR-401 and FR-402."""

    high: float
    low: float

    @classmethod
    def from_candle(cls, candle: Candle) -> BodyRange:
        return cls(high=candle.body_high, low=candle.body_low)


@dataclass(frozen=True, slots=True)
class StructureSwing:
    """Confirmed body-based elbow swing for FR-404 through FR-408."""

    symbol: str
    timeframe: Timeframe
    kind: SwingKind
    label: StructureLabel
    level: float
    candle_open_time_ms: int
    candle_close_time_ms: int
    display_label: str | None = None
    source_timeframe: Timeframe | None = None


@dataclass(frozen=True, slots=True)
class BreakOfStructure:
    """Body-close break of structure event for FR-409."""

    symbol: str
    timeframe: Timeframe
    direction: BreakDirection
    broken_label: StructureLabel
    broken_level: float
    candle_close: float
    candle_open_time_ms: int
    candle_close_time_ms: int
    display_label: str | None = None
    source_timeframe: Timeframe | None = None


@dataclass(frozen=True, slots=True)
class StructureEvent:
    """One market-structure update emitted by the engine."""

    swing: StructureSwing | None = None
    break_of_structure: BreakOfStructure | None = None

    def __post_init__(self) -> None:
        if self.swing is None and self.break_of_structure is None:
            raise ValueError("StructureEvent must contain a swing or break_of_structure")
