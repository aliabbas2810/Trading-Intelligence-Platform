from __future__ import annotations

from pydantic import BaseModel

from backend.exchange.models import HistoricalDataGap, HistoricalIntegrityReport
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


class HistoricalDataGapResponse(BaseModel):
    symbol: str
    timeframe: Timeframe
    start_open_time_ms: int
    end_open_time_ms: int
    missing_candle_count: int
    missing_open_times_ms: tuple[int, ...]
    retry_count: int
    exchange: str
    recovery_status: str
    detected_at_ms: int

    @classmethod
    def from_gap(cls, gap: HistoricalDataGap) -> HistoricalDataGapResponse:
        return cls(
            symbol=gap.symbol,
            timeframe=gap.timeframe,
            start_open_time_ms=gap.start_open_time_ms,
            end_open_time_ms=gap.end_open_time_ms,
            missing_candle_count=gap.missing_candle_count,
            missing_open_times_ms=gap.missing_open_times_ms,
            retry_count=gap.retry_count,
            exchange=gap.exchange.value,
            recovery_status=gap.recovery_status.value,
            detected_at_ms=gap.detected_at_ms,
        )


class HistoricalIntegrityReportResponse(BaseModel):
    policy: str
    status: str
    gap_count: int
    total_missing_candles: int
    gaps: tuple[HistoricalDataGapResponse, ...]
    requested_candle_count: int
    loaded_candle_count: int
    complete: bool
    exchange: str
    market_type: str
    symbol: str
    timeframe: Timeframe
    start_time_ms: int
    end_time_ms: int

    @classmethod
    def from_report(cls, report: HistoricalIntegrityReport) -> HistoricalIntegrityReportResponse:
        return cls(
            policy=report.policy.value,
            status=report.status.value,
            gap_count=report.gap_count,
            total_missing_candles=report.total_missing_candles,
            gaps=tuple(HistoricalDataGapResponse.from_gap(gap) for gap in report.gaps),
            requested_candle_count=report.requested_candle_count,
            loaded_candle_count=report.loaded_candle_count,
            complete=report.complete,
            exchange=report.exchange.value,
            market_type=report.market_type.value,
            symbol=report.symbol,
            timeframe=report.timeframe,
            start_time_ms=report.start_time_ms,
            end_time_ms=report.end_time_ms,
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
    historical_integrity: HistoricalIntegrityReportResponse | None = None

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
            historical_integrity=(
                HistoricalIntegrityReportResponse.from_report(readiness.historical_integrity)
                if readiness.historical_integrity is not None
                else None
            ),
        )
