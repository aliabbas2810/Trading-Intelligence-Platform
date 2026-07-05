from __future__ import annotations

from dataclasses import dataclass

from backend.engines.structure import BreakOfStructure, StructureSwing
from backend.engines.trend import DirectionalBias, MultiTimeframeTrendResult, TrendState, TrendUpdate
from backend.models import Candle


@dataclass(frozen=True, slots=True)
class SymbolScanInput:
    """Read-side scanner input for FR-901 without recalculating existing engines."""

    symbol: str
    trend: TrendUpdate | None = None
    alignment: MultiTimeframeTrendResult | None = None
    structure_swings: tuple[StructureSwing, ...] = ()
    breaks_of_structure: tuple[BreakOfStructure, ...] = ()
    latest_candle: Candle | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("SymbolScanInput symbol is required")


@dataclass(frozen=True, slots=True)
class SetupCandidate:
    """Ranked setup candidate generated from existing outputs for FR-903."""

    symbol: str
    bias: DirectionalBias
    score: float
    alignment_score: int
    trend_state: TrendState | None
    trend_strength: int
    has_structure: bool
    has_bos: bool
    latest_price: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SymbolScanResult:
    """Per-symbol scanner result for FR-901 and FR-905."""

    symbol: str
    candidate: SetupCandidate | None
    excluded_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScannerSummary:
    """Deterministic multi-symbol scanner summary for FR-901 through FR-905."""

    scanned_symbols: tuple[str, ...]
    candidates: tuple[SetupCandidate, ...]
    results: tuple[SymbolScanResult, ...]

    @property
    def total_symbols(self) -> int:
        return len(self.scanned_symbols)

    @property
    def filtered_symbols(self) -> int:
        return sum(1 for result in self.results if result.candidate is None)
