from __future__ import annotations

from dataclasses import dataclass

from backend.app import BackendRuntime, RuntimeMode
from backend.config import PlatformSettings, load_settings
from backend.engines.checklist import ChecklistItemStatus
from backend.engines.entry import EntryState
from backend.engines.risk import RiskAssessmentState
from backend.engines.scoring import ScoreGrade
from backend.engines.trend import TrendState
from backend.models import Candle, Timeframe
from backend.pipelines.candle import CandleClosedEvent
from backend.pipelines.timeframe import TimeframeCandleClosedEvent


@dataclass(frozen=True, slots=True)
class HistoricalValidationSummary:
    """M27 validation output summary over existing runtime/engine results."""

    symbol: str
    timeframe: Timeframe
    candle_count: int
    structure_count: int
    bos_count: int
    trend_state: TrendState | None
    entry_state: EntryState
    risk_state: RiskAssessmentState
    checklist_status: ChecklistItemStatus
    setup_score: float
    setup_grade: ScoreGrade


class HistoricalValidationRunner:
    """Feed historical candles through existing runtime event paths for M27."""

    def __init__(self, settings: PlatformSettings | None = None) -> None:
        self._settings = settings or demo_disabled_settings()

    def run(
        self,
        candles: tuple[Candle, ...],
        *,
        symbol: str,
        timeframe: Timeframe,
    ) -> HistoricalValidationSummary:
        runtime = BackendRuntime(settings=self._settings, mode=RuntimeMode.DRY_RUN)
        runtime.start()
        try:
            for candle in sorted(candles, key=lambda item: item.open_time_ms):
                publish_candle(runtime, candle)
            entry = runtime.evaluate_entry_signal(symbol=symbol)
            risk = runtime.evaluate_risk(symbol=symbol, entry_trace=entry)
            checklist = runtime.evaluate_checklist(symbol=symbol, entry_trace=entry, risk_plan=risk)
            score = runtime.evaluate_setup_score(
                symbol=symbol,
                entry_trace=entry,
                risk_plan=risk,
                checklist_result=checklist,
            )
            structure = runtime.structure_store.list(symbol, timeframe)
            trend = runtime.trend_store.get(symbol, timeframe)
            return HistoricalValidationSummary(
                symbol=symbol,
                timeframe=timeframe,
                candle_count=len(runtime.candle_store.list(symbol, timeframe)),
                structure_count=len(structure.swings),
                bos_count=len(structure.breaks_of_structure),
                trend_state=trend.update.state if trend.update is not None else None,
                entry_state=entry.state,
                risk_state=risk.state,
                checklist_status=checklist.overall_status,
                setup_score=score.percentage,
                setup_grade=score.grade,
            )
        finally:
            runtime.stop()


def publish_candle(runtime: BackendRuntime, candle: Candle) -> None:
    if candle.timeframe is Timeframe.ONE_MINUTE:
        runtime.event_bus.publish(CandleClosedEvent(candle=candle))
        return
    runtime.candle_store.save(candle)
    runtime.event_bus.publish(TimeframeCandleClosedEvent(candle=candle))


def demo_disabled_settings() -> PlatformSettings:
    settings = load_settings()
    return settings.model_copy(update={"demo": settings.demo.model_copy(update={"enabled": False})})
