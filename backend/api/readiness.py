from __future__ import annotations

from pydantic import BaseModel

from backend.engines.readiness import (
    AlignmentReadiness,
    AnalysisReadiness,
    AnalysisReadinessState,
    CandleTimeframeReadiness,
    StructureTimeframeReadiness,
    TrendTimeframeReadiness,
)
from backend.models import Timeframe


class CandleTimeframeReadinessResponse(BaseModel):
    timeframe: Timeframe
    candle_count: int
    available: bool

    @classmethod
    def from_readiness(cls, readiness: CandleTimeframeReadiness) -> CandleTimeframeReadinessResponse:
        return cls(
            timeframe=readiness.timeframe,
            candle_count=readiness.candle_count,
            available=readiness.available,
        )


class StructureTimeframeReadinessResponse(BaseModel):
    timeframe: Timeframe
    ready: bool
    swing_count: int
    bos_count: int

    @classmethod
    def from_readiness(
        cls,
        readiness: StructureTimeframeReadiness,
    ) -> StructureTimeframeReadinessResponse:
        return cls(
            timeframe=readiness.timeframe,
            ready=readiness.ready,
            swing_count=readiness.swing_count,
            bos_count=readiness.bos_count,
        )


class TrendTimeframeReadinessResponse(BaseModel):
    timeframe: Timeframe
    ready: bool
    state: str | None

    @classmethod
    def from_readiness(cls, readiness: TrendTimeframeReadiness) -> TrendTimeframeReadinessResponse:
        return cls(timeframe=readiness.timeframe, ready=readiness.ready, state=readiness.state)


class AlignmentReadinessResponse(BaseModel):
    ready: bool
    alignment_score: int | None
    missing_timeframes: tuple[Timeframe, ...]

    @classmethod
    def from_readiness(cls, readiness: AlignmentReadiness) -> AlignmentReadinessResponse:
        return cls(
            ready=readiness.ready,
            alignment_score=readiness.alignment_score,
            missing_timeframes=readiness.missing_timeframes,
        )


class AnalysisReadinessResponse(BaseModel):
    """Typed API response for M28.1 historical warm-up diagnostics."""

    symbol: str
    required_timeframes: tuple[Timeframe, ...]
    available_timeframes: tuple[Timeframe, ...]
    missing_timeframes: tuple[Timeframe, ...]
    candle_counts_by_timeframe: tuple[CandleTimeframeReadinessResponse, ...]
    structure_readiness_by_timeframe: tuple[StructureTimeframeReadinessResponse, ...]
    trend_readiness_by_timeframe: tuple[TrendTimeframeReadinessResponse, ...]
    alignment_readiness: AlignmentReadinessResponse
    entry_readiness: bool
    overall_state: AnalysisReadinessState
    reason: str
    missing_reasons: tuple[str, ...]

    @classmethod
    def from_readiness(cls, readiness: AnalysisReadiness) -> AnalysisReadinessResponse:
        return cls(
            symbol=readiness.symbol,
            required_timeframes=readiness.required_timeframes,
            available_timeframes=readiness.available_timeframes,
            missing_timeframes=readiness.missing_timeframes,
            candle_counts_by_timeframe=tuple(
                CandleTimeframeReadinessResponse.from_readiness(item)
                for item in readiness.candle_counts_by_timeframe
            ),
            structure_readiness_by_timeframe=tuple(
                StructureTimeframeReadinessResponse.from_readiness(item)
                for item in readiness.structure_readiness_by_timeframe
            ),
            trend_readiness_by_timeframe=tuple(
                TrendTimeframeReadinessResponse.from_readiness(item)
                for item in readiness.trend_readiness_by_timeframe
            ),
            alignment_readiness=AlignmentReadinessResponse.from_readiness(
                readiness.alignment_readiness,
            ),
            entry_readiness=readiness.entry_readiness,
            overall_state=readiness.overall_state,
            reason=readiness.reason,
            missing_reasons=readiness.missing_reasons,
        )
