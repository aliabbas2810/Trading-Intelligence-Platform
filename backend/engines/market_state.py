from __future__ import annotations

from dataclasses import replace

from backend.api.visualization import StructureSnapshot
from backend.engines.structure import BreakOfStructure, BreakDirection, StructureLabel, StructureSwing
from backend.engines.trend import TrendState, TrendUpdate
from backend.models import Timeframe


MARKET_STRUCTURE_TIMEFRAMES = (Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR)
PROJECTED_STRUCTURE_TIMEFRAMES = (
    Timeframe.FOUR_HOUR,
    Timeframe.TWO_HOUR,
    Timeframe.ONE_HOUR,
    Timeframe.THIRTY_MINUTE,
    Timeframe.FIFTEEN_MINUTE,
    Timeframe.FIVE_MINUTE,
    Timeframe.ONE_MINUTE,
)


class MarketStateService:
    """Authoritative current market-state service for Weekly, Daily, and 4H only."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, Timeframe], TrendState] = {}
        self._swings: dict[tuple[str, Timeframe, StructureLabel], StructureSwing] = {}
        self._breaks: dict[tuple[str, Timeframe], BreakOfStructure] = {}

    def update_trend(self, update: TrendUpdate) -> None:
        if update.timeframe not in MARKET_STRUCTURE_TIMEFRAMES:
            return
        self._states[(update.symbol, update.timeframe)] = (
            TrendState.BEARISH if update.state is TrendState.BEARISH else TrendState.BULLISH
        )
        self._discard_inactive_pair(update.symbol, update.timeframe)

    def update_swing(self, swing: StructureSwing) -> None:
        if swing.timeframe not in MARKET_STRUCTURE_TIMEFRAMES:
            return
        self._states.setdefault((swing.symbol, swing.timeframe), self._state_from_label(swing.label))
        self._swings[(swing.symbol, swing.timeframe, swing.label)] = self._with_public_label(swing)
        self._discard_inactive_pair(swing.symbol, swing.timeframe)

    def update_break_of_structure(self, break_of_structure: BreakOfStructure) -> None:
        if break_of_structure.timeframe not in MARKET_STRUCTURE_TIMEFRAMES:
            return
        self._states[(break_of_structure.symbol, break_of_structure.timeframe)] = (
            TrendState.BULLISH
            if break_of_structure.direction is BreakDirection.BULLISH
            else TrendState.BEARISH
        )
        self._breaks[(break_of_structure.symbol, break_of_structure.timeframe)] = self._with_public_bos_label(
            break_of_structure
        )
        self._discard_inactive_pair(break_of_structure.symbol, break_of_structure.timeframe)

    def structure_snapshot(self, symbol: str, chart_timeframe: Timeframe) -> StructureSnapshot:
        source_timeframes = self._source_timeframes_for_chart(chart_timeframe)
        swings = tuple(
            swing
            for timeframe in source_timeframes
            for swing in self._active_swings(symbol, timeframe)
        )
        breaks = tuple(
            item
            for timeframe in source_timeframes
            for item in (self._breaks.get((symbol, timeframe)),)
            if item is not None
        )
        return StructureSnapshot(swings=swings, breaks_of_structure=breaks)

    def state(self, symbol: str) -> dict[str, dict[str, object]]:
        return {
            timeframe.value: {
                "state": self._states.get((symbol, timeframe), TrendState.BULLISH).value,
                "swings": tuple(
                    {
                        "label": swing.display_label or swing.label.value,
                        "level": swing.level,
                        "timeframe": timeframe.value,
                        "candle_close_time_ms": swing.candle_close_time_ms,
                    }
                    for swing in self._active_swings(symbol, timeframe)
                ),
                "break_of_structure": self._breaks.get((symbol, timeframe)),
            }
            for timeframe in MARKET_STRUCTURE_TIMEFRAMES
        }

    def reset(self) -> None:
        self._states.clear()
        self._swings.clear()
        self._breaks.clear()

    def _active_swings(self, symbol: str, timeframe: Timeframe) -> tuple[StructureSwing, ...]:
        state = self._states.get((symbol, timeframe), TrendState.BULLISH)
        labels = (
            (StructureLabel.HH, StructureLabel.HL)
            if state is TrendState.BULLISH
            else (StructureLabel.LH, StructureLabel.LL)
        )
        return tuple(
            swing
            for label in labels
            for swing in (self._swings.get((symbol, timeframe, label)),)
            if swing is not None
        )

    def _discard_inactive_pair(self, symbol: str, timeframe: Timeframe) -> None:
        state = self._states.get((symbol, timeframe), TrendState.BULLISH)
        inactive = (
            (StructureLabel.LH, StructureLabel.LL)
            if state is TrendState.BULLISH
            else (StructureLabel.HH, StructureLabel.HL)
        )
        for label in inactive:
            self._swings.pop((symbol, timeframe, label), None)

    def _source_timeframes_for_chart(self, chart_timeframe: Timeframe) -> tuple[Timeframe, ...]:
        if chart_timeframe is Timeframe.WEEKLY:
            return (Timeframe.WEEKLY,)
        if chart_timeframe is Timeframe.DAILY:
            return (Timeframe.WEEKLY, Timeframe.DAILY)
        return MARKET_STRUCTURE_TIMEFRAMES

    def _with_public_label(self, swing: StructureSwing) -> StructureSwing:
        return replace(
            swing,
            display_label=self._public_label(swing.timeframe, swing.label),
            source_timeframe=swing.timeframe,
        )

    def _with_public_bos_label(self, break_of_structure: BreakOfStructure) -> BreakOfStructure:
        return replace(
            break_of_structure,
            display_label=self._public_label(
                break_of_structure.timeframe,
                break_of_structure.broken_label,
            ),
            source_timeframe=break_of_structure.timeframe,
        )

    def _public_label(self, timeframe: Timeframe, label: StructureLabel) -> str:
        prefix = {
            Timeframe.WEEKLY: "W",
            Timeframe.DAILY: "D",
            Timeframe.FOUR_HOUR: "4",
        }[timeframe]
        return f"{prefix}{label.value}"

    def _state_from_label(self, label: StructureLabel) -> TrendState:
        return TrendState.BEARISH if label in {StructureLabel.LH, StructureLabel.LL} else TrendState.BULLISH
