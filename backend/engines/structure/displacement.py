from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from backend.models.domain import Candle


class DisplacementMode(str, Enum):
    PERCENT = "percent"
    ATR = "atr"
    HYBRID = "hybrid"


class DisplacementThreshold(Protocol):
    """Dynamic displacement threshold interface for FR-403."""

    def threshold(self, candle: Candle) -> float:
        """Return the minimum body displacement required to confirm a swing."""


@dataclass(frozen=True, slots=True)
class PercentDisplacementThreshold:
    """Percent-based dynamic displacement for FR-403."""

    percent: float

    def __post_init__(self) -> None:
        if self.percent < 0:
            raise ValueError("percent must be non-negative")

    def threshold(self, candle: Candle) -> float:
        return candle.body_high * self.percent


@dataclass(frozen=True, slots=True)
class AtrDisplacementThreshold:
    """ATR displacement placeholder interface for FR-403."""

    multiplier: float

    def threshold(self, candle: Candle) -> float:
        raise NotImplementedError("ATR displacement requires an ATR provider in a later milestone")


@dataclass(frozen=True, slots=True)
class HybridDisplacementThreshold:
    """Hybrid displacement placeholder interface for FR-403."""

    percent: PercentDisplacementThreshold
    atr: AtrDisplacementThreshold

    def threshold(self, candle: Candle) -> float:
        raise NotImplementedError("Hybrid displacement requires ATR support in a later milestone")
