from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.engines.structure import BreakOfStructure, StructureDiagnostics, StructureLabel, StructureSwing
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
        self._swing_keys: set[tuple[object, ...]] = set()
        self._break_keys: set[tuple[object, ...]] = set()
        self._duplicate_swings = 0
        self._duplicate_breaks = 0

    def add_swing(self, swing: StructureSwing) -> None:
        key = (
            swing.symbol,
            swing.timeframe,
            swing.kind,
            swing.label,
            swing.level,
            swing.candle_close_time_ms,
        )
        if key in self._swing_keys:
            self._duplicate_swings += 1
            return
        self._swing_keys.add(key)
        self._swings.setdefault((swing.symbol, swing.timeframe), []).append(swing)

    def add_break_of_structure(self, break_of_structure: BreakOfStructure) -> None:
        key = (
            break_of_structure.symbol,
            break_of_structure.timeframe,
            break_of_structure.direction,
            break_of_structure.broken_level,
            break_of_structure.candle_close_time_ms,
        )
        if key in self._break_keys:
            self._duplicate_breaks += 1
            return
        self._break_keys.add(key)
        self._breaks.setdefault(
            (break_of_structure.symbol, break_of_structure.timeframe),
            [],
        ).append(break_of_structure)

    def list(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int | None = None,
    ) -> StructureSnapshot:
        swings = tuple(
            item
            for item in self._swings.get((symbol, timeframe), ())
            if _in_time_range(item.candle_close_time_ms, start_time_ms, end_time_ms)
        )
        breaks = tuple(
            item
            for item in self._breaks.get((symbol, timeframe), ())
            if _in_time_range(item.candle_close_time_ms, start_time_ms, end_time_ms)
        )
        if limit is not None:
            swings = swings[-limit:]
            breaks = breaks[-limit:]
        return StructureSnapshot(
            swings=swings,
            breaks_of_structure=breaks,
        )

    def diagnostics(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        candle_count: int,
        density_anomaly_ratio: float,
        bos_anomaly_ratio: float,
    ) -> StructureDiagnostics:
        snapshot = self.list(symbol, timeframe)
        label_counts = {label: 0 for label in StructureLabel}
        max_same_role_run = 0
        current_run = 0
        last_kind = None
        alternation_violations = 0
        for swing in snapshot.swings:
            label_counts[swing.label] += 1
            if swing.kind is last_kind:
                current_run += 1
                alternation_violations += 1
            else:
                current_run = 1
                last_kind = swing.kind
            max_same_role_run = max(max_same_role_run, current_run)
        confirmed = len(snapshot.swings)
        bos = len(snapshot.breaks_of_structure)
        structure_ratio = confirmed / candle_count if candle_count else 0.0
        bos_ratio = bos / confirmed if confirmed else 0.0
        return StructureDiagnostics(
            candidate_swings=0,
            provisional_swings=0,
            confirmed_swings=confirmed,
            hh=label_counts[StructureLabel.HH],
            hl=label_counts[StructureLabel.HL],
            lh=label_counts[StructureLabel.LH],
            ll=label_counts[StructureLabel.LL],
            bos=bos,
            duplicate_structures=self._duplicate_swings,
            duplicate_bos=self._duplicate_breaks,
            alternation_violation_count=alternation_violations,
            same_role_run_length=max_same_role_run,
            candle_count=candle_count,
            structure_candle_ratio=structure_ratio,
            bos_swing_ratio=bos_ratio,
            structure_density_anomaly=structure_ratio >= density_anomaly_ratio or bos_ratio >= bos_anomaly_ratio,
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

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int | None = None,
    ) -> tuple[Candle, ...]:
        """GET /api/candles: completed OHLCV candles with wicks for FR-601."""

        candles = tuple(
            candle
            for candle in self._candle_store.list(symbol, timeframe)
            if _in_time_range(candle.close_time_ms, start_time_ms, end_time_ms)
        )
        if limit is not None:
            return candles[-limit:]
        return candles

    def get_market_structure(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int | None = None,
    ) -> StructureSnapshot:
        """GET /api/market-structure: precomputed HH/HL/LH/LL and BOS for FR-602/FR-604."""

        if isinstance(self._structure_store, InMemoryStructureReadStore):
            return self._structure_store.list(
                symbol,
                timeframe,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                limit=limit,
            )
        return self._structure_store.list(symbol, timeframe)

    def get_trend_state(self, symbol: str, timeframe: Timeframe) -> TrendSnapshot:
        """GET /api/trend-state: precomputed trend state for FR-603."""

        return self._trend_store.get(symbol, timeframe)

    def get_multi_timeframe_alignment(self, symbol: str) -> MultiTimeframeTrendResult | None:
        """GET /api/multi-timeframe-alignment: precomputed alignment for FR-603."""

        return self._alignment_store.get(symbol)


def _in_time_range(value_ms: int, start_time_ms: int | None, end_time_ms: int | None) -> bool:
    if start_time_ms is not None and value_ms < start_time_ms:
        return False
    if end_time_ms is not None and value_ms >= end_time_ms:
        return False
    return True
