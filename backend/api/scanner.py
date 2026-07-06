from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from backend.engines.scanner import ScannerSummary, SetupCandidate, SymbolScanResult
from backend.engines.trend import DirectionalBias, TrendState
from backend.models import Timeframe


class ScannerBiasFilter(str, Enum):
    ANY = "any"
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

    def to_directional_bias(self) -> DirectionalBias | None:
        if self is ScannerBiasFilter.ANY:
            return None
        return DirectionalBias(self.value)


class ScannerRunRequest(BaseModel):
    """Scanner run request for FR-901 through FR-905."""

    symbols: tuple[str, ...] | None = None
    timeframe: Timeframe = Timeframe.FOUR_HOUR
    bias: ScannerBiasFilter = ScannerBiasFilter.ANY
    minimum_alignment_score: int = Field(default=0, ge=0)
    minimum_setup_score: float = Field(default=0.0, ge=0)
    limit: int | None = Field(default=None, ge=1)


class SetupCandidateResponse(BaseModel):
    """Transport model for scanner setup candidates under FR-903."""

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

    @classmethod
    def from_candidate(cls, candidate: SetupCandidate) -> SetupCandidateResponse:
        return cls(
            symbol=candidate.symbol,
            bias=candidate.bias,
            score=candidate.score,
            alignment_score=candidate.alignment_score,
            trend_state=candidate.trend_state,
            trend_strength=candidate.trend_strength,
            has_structure=candidate.has_structure,
            has_bos=candidate.has_bos,
            latest_price=candidate.latest_price,
            reasons=candidate.reasons,
        )


class SymbolScanResultResponse(BaseModel):
    """Per-symbol scanner result response for FR-901 and FR-905."""

    symbol: str
    candidate: SetupCandidateResponse | None
    excluded_reasons: tuple[str, ...]

    @classmethod
    def from_result(cls, result: SymbolScanResult) -> SymbolScanResultResponse:
        return cls(
            symbol=result.symbol,
            candidate=(
                SetupCandidateResponse.from_candidate(result.candidate)
                if result.candidate is not None
                else None
            ),
            excluded_reasons=result.excluded_reasons,
        )


class ScannerSummaryResponse(BaseModel):
    """Scanner summary response for FR-901 through FR-905."""

    scanned_symbols: tuple[str, ...]
    total_symbols: int
    filtered_symbols: int
    candidates: tuple[SetupCandidateResponse, ...]
    results: tuple[SymbolScanResultResponse, ...]

    @classmethod
    def from_summary(
        cls,
        summary: ScannerSummary,
        *,
        limit: int | None = None,
    ) -> ScannerSummaryResponse:
        candidates = summary.candidates[:limit] if limit is not None else summary.candidates
        return cls(
            scanned_symbols=summary.scanned_symbols,
            total_symbols=summary.total_symbols,
            filtered_symbols=summary.filtered_symbols,
            candidates=tuple(SetupCandidateResponse.from_candidate(candidate) for candidate in candidates),
            results=tuple(SymbolScanResultResponse.from_result(result) for result in summary.results),
        )
