from __future__ import annotations

from backend.api import StructureReadStore, TrendReadStore
from backend.engines.readiness.models import (
    AlignmentReadiness,
    AnalysisReadiness,
    AnalysisReadinessState,
    CandleTimeframeReadiness,
    StructureTimeframeReadiness,
    TrendTimeframeReadiness,
)
from backend.exchange.models import HistoricalIntegrityReport
from backend.models import Timeframe
from backend.storage import CandleStore


REQUIRED_TREND_TIMEFRAMES = (
    Timeframe.WEEKLY,
    Timeframe.DAILY,
    Timeframe.FOUR_HOUR,
    Timeframe.TWO_HOUR,
    Timeframe.ONE_HOUR,
    Timeframe.THIRTY_MINUTE,
)
REQUIRED_STRUCTURE_TIMEFRAMES = (
    Timeframe.FIFTEEN_MINUTE,
    Timeframe.FIVE_MINUTE,
    Timeframe.ONE_MINUTE,
)
REQUIRED_ALIGNMENT_TIMEFRAMES = (
    Timeframe.WEEKLY,
    Timeframe.DAILY,
    Timeframe.FOUR_HOUR,
)
REQUIRED_ANALYSIS_TIMEFRAMES = (
    Timeframe.WEEKLY,
    Timeframe.DAILY,
    Timeframe.FOUR_HOUR,
    Timeframe.TWO_HOUR,
    Timeframe.ONE_HOUR,
    Timeframe.THIRTY_MINUTE,
    Timeframe.FIFTEEN_MINUTE,
    Timeframe.FIVE_MINUTE,
    Timeframe.ONE_MINUTE,
)


class AnalysisReadinessEngine:
    """Build read-only warm-up diagnostics without recalculating market analysis."""

    def __init__(
        self,
        candle_store: CandleStore,
        structure_store: StructureReadStore,
        trend_store: TrendReadStore,
    ) -> None:
        self._candle_store = candle_store
        self._structure_store = structure_store
        self._trend_store = trend_store

    def evaluate(
        self,
        symbol: str,
        alignment_missing_timeframes: tuple[Timeframe, ...],
        alignment_score: int | None,
        historical_integrity: HistoricalIntegrityReport | None = None,
    ) -> AnalysisReadiness:
        """Inspect existing read stores for historical warm-up diagnostics."""

        candle_readiness = tuple(
            CandleTimeframeReadiness(
                timeframe=timeframe,
                candle_count=len(self._candle_store.list(symbol, timeframe)),
                available=bool(self._candle_store.list(symbol, timeframe)),
            )
            for timeframe in REQUIRED_ANALYSIS_TIMEFRAMES
        )
        available_timeframes = tuple(item.timeframe for item in candle_readiness if item.available)
        missing_timeframes = tuple(item.timeframe for item in candle_readiness if not item.available)
        structure_readiness = tuple(
            self._structure_readiness(symbol, timeframe)
            for timeframe in REQUIRED_STRUCTURE_TIMEFRAMES
        )
        trend_readiness = tuple(
            self._trend_readiness(symbol, timeframe)
            for timeframe in REQUIRED_TREND_TIMEFRAMES
        )
        alignment_readiness = AlignmentReadiness(
            ready=alignment_score is not None and not alignment_missing_timeframes,
            alignment_score=alignment_score,
            missing_timeframes=alignment_missing_timeframes,
        )
        missing_reasons = self._missing_reasons(
            missing_timeframes=missing_timeframes,
            structure_readiness=structure_readiness,
            trend_readiness=trend_readiness,
            alignment_readiness=alignment_readiness,
            historical_integrity=historical_integrity,
        )
        entry_readiness = not missing_reasons
        return AnalysisReadiness(
            symbol=symbol,
            required_timeframes=REQUIRED_ANALYSIS_TIMEFRAMES,
            available_timeframes=available_timeframes,
            missing_timeframes=missing_timeframes,
            candle_counts_by_timeframe=candle_readiness,
            structure_readiness_by_timeframe=structure_readiness,
            trend_readiness_by_timeframe=trend_readiness,
            alignment_readiness=alignment_readiness,
            entry_readiness=entry_readiness,
            overall_state=self._overall_state(
                candle_readiness=candle_readiness,
                missing_timeframes=missing_timeframes,
                missing_reasons=missing_reasons,
                historical_integrity=historical_integrity,
            ),
            reason=self._reason(missing_timeframes, missing_reasons, historical_integrity),
            missing_reasons=missing_reasons,
            historical_integrity=historical_integrity,
        )

    def _structure_readiness(self, symbol: str, timeframe: Timeframe) -> StructureTimeframeReadiness:
        snapshot = self._structure_store.list(symbol, timeframe)
        swing_count = len(snapshot.swings)
        bos_count = len(snapshot.breaks_of_structure)
        return StructureTimeframeReadiness(
            timeframe=timeframe,
            ready=swing_count > 0 or bos_count > 0,
            swing_count=swing_count,
            bos_count=bos_count,
        )

    def _trend_readiness(self, symbol: str, timeframe: Timeframe) -> TrendTimeframeReadiness:
        update = self._trend_store.get(symbol, timeframe).update
        return TrendTimeframeReadiness(
            timeframe=timeframe,
            ready=update is not None,
            state=update.state.value if update is not None else None,
        )

    def _missing_reasons(
        self,
        *,
        missing_timeframes: tuple[Timeframe, ...],
        structure_readiness: tuple[StructureTimeframeReadiness, ...],
        trend_readiness: tuple[TrendTimeframeReadiness, ...],
        alignment_readiness: AlignmentReadiness,
        historical_integrity: HistoricalIntegrityReport | None,
    ) -> tuple[str, ...]:
        reasons = [f"{timeframe.value}_candles" for timeframe in missing_timeframes]
        if historical_integrity is not None and not historical_integrity.complete:
            reasons.append("historical_data_gap")
            reasons.append(f"historical_integrity_{historical_integrity.status.value}")
        reasons.extend(
            f"{item.timeframe.value}_structure"
            for item in structure_readiness
            if not item.ready
        )
        reasons.extend(
            f"{item.timeframe.value}_trend"
            for item in trend_readiness
            if not item.ready
        )
        if not alignment_readiness.ready:
            reasons.append("multi_timeframe_alignment")
        return tuple(reasons)

    def _overall_state(
        self,
        *,
        candle_readiness: tuple[CandleTimeframeReadiness, ...],
        missing_timeframes: tuple[Timeframe, ...],
        missing_reasons: tuple[str, ...],
        historical_integrity: HistoricalIntegrityReport | None,
    ) -> AnalysisReadinessState:
        if not any(item.available for item in candle_readiness):
            return AnalysisReadinessState.INSUFFICIENT_DATA
        if historical_integrity is not None and not historical_integrity.complete:
            return AnalysisReadinessState.DEGRADED
        if missing_timeframes:
            return AnalysisReadinessState.INSUFFICIENT_DATA
        if missing_reasons:
            return AnalysisReadinessState.WARMING_UP
        return AnalysisReadinessState.READY

    def _reason(
        self,
        missing_timeframes: tuple[Timeframe, ...],
        missing_reasons: tuple[str, ...],
        historical_integrity: HistoricalIntegrityReport | None,
    ) -> str:
        if historical_integrity is not None and not historical_integrity.complete:
            return f"historical_integrity_{historical_integrity.status.value}"
        if missing_timeframes:
            return "insufficient_historical_range"
        if missing_reasons:
            return "analysis_warming_up"
        return "ready"
