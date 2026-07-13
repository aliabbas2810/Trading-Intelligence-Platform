from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.models import Timeframe


class AnalysisReadinessState(str, Enum):
    """Overall data-readiness state for M28.1 historical warm-up diagnostics."""

    READY = "READY"
    WARMING_UP = "WARMING_UP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class CandleTimeframeReadiness:
    timeframe: Timeframe
    candle_count: int
    available: bool


@dataclass(frozen=True, slots=True)
class StructureTimeframeReadiness:
    timeframe: Timeframe
    ready: bool
    swing_count: int
    bos_count: int


@dataclass(frozen=True, slots=True)
class TrendTimeframeReadiness:
    timeframe: Timeframe
    ready: bool
    state: str | None


@dataclass(frozen=True, slots=True)
class AlignmentReadiness:
    ready: bool
    alignment_score: int | None
    missing_timeframes: tuple[Timeframe, ...]


@dataclass(frozen=True, slots=True)
class AnalysisReadiness:
    """Typed readiness snapshot for M28.1 without recalculating analysis outputs."""

    symbol: str
    required_timeframes: tuple[Timeframe, ...]
    available_timeframes: tuple[Timeframe, ...]
    missing_timeframes: tuple[Timeframe, ...]
    candle_counts_by_timeframe: tuple[CandleTimeframeReadiness, ...]
    structure_readiness_by_timeframe: tuple[StructureTimeframeReadiness, ...]
    trend_readiness_by_timeframe: tuple[TrendTimeframeReadiness, ...]
    alignment_readiness: AlignmentReadiness
    entry_readiness: bool
    overall_state: AnalysisReadinessState
    reason: str
    missing_reasons: tuple[str, ...]
