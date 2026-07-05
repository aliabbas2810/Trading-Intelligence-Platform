from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.engines.structure import BreakOfStructure, StructureSwing
from backend.engines.trend import MultiTimeframeTrendResult, TrendUpdate
from backend.models.domain import Candle, Timeframe
from backend.storage import CandleStore


@dataclass(frozen=True, slots=True)
class StructureSnapshot:
    """Read model for FR-602 and FR-604 visualization overlays."""

    swings: tuple[StructureSwing, ...]
    breaks_of_structure: tuple[BreakOfStructure, ...]


@dataclass(frozen=True, slots=True)
class TrendSnapshot:
    """Read model for FR-603 trend visualization."""

    update: TrendUpdate | None


class StructureReadStore(Protocol):
    def list(self, symbol: str, timeframe: Timeframe) -> StructureSnapshot:
        """Return precomputed market structure without recalculation."""


class TrendReadStore(Protocol):
    def get(self, symbol: str, timeframe: Timeframe) -> TrendSnapshot:
        """Return precomputed trend state without recalculation."""


class AlignmentReadStore(Protocol):
    def get(self, symbol: str) -> MultiTimeframeTrendResult | None:
        """Return precomputed multi-timeframe alignment without recalculation."""


class InMemoryStructureReadStore:
    def __init__(self) -> None:
        self._swings: dict[tuple[str, Timeframe], list[StructureSwing]] = {}
        self._breaks: dict[tuple[str, Timeframe], list[BreakOfStructure]] = {}

    def add_swing(self, swing: StructureSwing) -> None:
        self._swings.setdefault((swing.symbol, swing.timeframe), []).append(swing)

    def add_break_of_structure(self, break_of_structure: BreakOfStructure) -> None:
        self._breaks.setdefault(
            (break_of_structure.symbol, break_of_structure.timeframe),
            [],
        ).append(break_of_structure)

    def list(self, symbol: str, timeframe: Timeframe) -> StructureSnapshot:
        return StructureSnapshot(
            swings=tuple(self._swings.get((symbol, timeframe), ())),
            breaks_of_structure=tuple(self._breaks.get((symbol, timeframe), ())),
        )


class InMemoryTrendReadStore:
    def __init__(self) -> None:
        self._updates: dict[tuple[str, Timeframe], TrendUpdate] = {}

    def set(self, update: TrendUpdate) -> None:
        self._updates[(update.symbol, update.timeframe)] = update

    def get(self, symbol: str, timeframe: Timeframe) -> TrendSnapshot:
        return TrendSnapshot(update=self._updates.get((symbol, timeframe)))


class InMemoryAlignmentReadStore:
    def __init__(self) -> None:
        self._results: dict[str, MultiTimeframeTrendResult] = {}

    def set(self, result: MultiTimeframeTrendResult) -> None:
        self._results[result.symbol] = result

    def get(self, symbol: str) -> MultiTimeframeTrendResult | None:
        return self._results.get(symbol)


class VisualizationReadApi:
    """Read-only visualization API boundary for FR-601 through FR-605."""

    def __init__(
        self,
        candle_store: CandleStore,
        structure_store: StructureReadStore,
        trend_store: TrendReadStore,
        alignment_store: AlignmentReadStore,
    ) -> None:
        self._candle_store = candle_store
        self._structure_store = structure_store
        self._trend_store = trend_store
        self._alignment_store = alignment_store

    def get_candles(self, symbol: str, timeframe: Timeframe) -> tuple[Candle, ...]:
        """GET /api/candles: completed OHLCV candles with wicks for FR-601."""

        return self._candle_store.list(symbol, timeframe)

    def get_market_structure(self, symbol: str, timeframe: Timeframe) -> StructureSnapshot:
        """GET /api/market-structure: precomputed HH/HL/LH/LL and BOS for FR-602/FR-604."""

        return self._structure_store.list(symbol, timeframe)

    def get_trend_state(self, symbol: str, timeframe: Timeframe) -> TrendSnapshot:
        """GET /api/trend-state: precomputed trend state for FR-603."""

        return self._trend_store.get(symbol, timeframe)

    def get_multi_timeframe_alignment(self, symbol: str) -> MultiTimeframeTrendResult | None:
        """GET /api/multi-timeframe-alignment: precomputed alignment for FR-603."""

        return self._alignment_store.get(symbol)
