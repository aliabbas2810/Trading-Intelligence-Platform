from __future__ import annotations

from collections.abc import Iterable

from backend.core import EventBus
from backend.engines.scanner.events import ScannerCompletedEvent, SetupCandidateFoundEvent
from backend.engines.scanner.models import (
    ScannerSummary,
    SetupCandidate,
    SymbolScanInput,
    SymbolScanResult,
)
from backend.engines.trend import DirectionalBias, TrendState


class ScannerEngine:
    """Batch multi-symbol scanner consuming existing engine outputs only."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus

    def scan(
        self,
        inputs: Iterable[SymbolScanInput],
        *,
        bias: DirectionalBias | None = None,
        minimum_alignment_score: int = 0,
        minimum_setup_score: float = 0.0,
    ) -> ScannerSummary:
        """Scan symbols in batch for FR-901 through FR-905 and TEST-001."""

        if minimum_alignment_score < 0:
            raise ValueError("minimum_alignment_score must be non-negative")
        if minimum_setup_score < 0:
            raise ValueError("minimum_setup_score must be non-negative")

        ordered_inputs = tuple(sorted(inputs, key=lambda item: item.symbol))
        results = tuple(
            self._scan_symbol(
                item,
                bias=bias,
                minimum_alignment_score=minimum_alignment_score,
                minimum_setup_score=minimum_setup_score,
            )
            for item in ordered_inputs
        )
        candidates = tuple(
            sorted(
                (result.candidate for result in results if result.candidate is not None),
                key=lambda candidate: (-candidate.score, candidate.symbol),
            ),
        )
        summary = ScannerSummary(
            scanned_symbols=tuple(item.symbol for item in ordered_inputs),
            candidates=candidates,
            results=results,
        )
        self._publish_summary(summary)
        return summary

    def _scan_symbol(
        self,
        item: SymbolScanInput,
        *,
        bias: DirectionalBias | None,
        minimum_alignment_score: int,
        minimum_setup_score: float,
    ) -> SymbolScanResult:
        candidate = self._build_candidate(item)
        excluded_reasons: list[str] = []

        if bias is not None and candidate.bias is not bias:
            excluded_reasons.append("bias_filter")
        if candidate.alignment_score < minimum_alignment_score:
            excluded_reasons.append("alignment_filter")
        if candidate.score < minimum_setup_score:
            excluded_reasons.append("score_filter")

        if excluded_reasons:
            return SymbolScanResult(
                symbol=item.symbol,
                candidate=None,
                excluded_reasons=tuple(excluded_reasons),
            )

        self._publish_candidate(candidate)
        return SymbolScanResult(symbol=item.symbol, candidate=candidate)

    def _build_candidate(self, item: SymbolScanInput) -> SetupCandidate:
        bias = resolve_bias(item)
        alignment_score = item.alignment.alignment_score if item.alignment is not None else 0
        trend_state = item.trend.state if item.trend is not None else None
        trend_strength = (
            item.trend.strength.confirming_structure_count if item.trend is not None else 0
        )
        has_structure = bool(item.structure_swings)
        has_bos = bool(item.breaks_of_structure)
        latest_price = item.latest_candle.close if item.latest_candle is not None else None

        score = score_candidate(
            alignment_score=alignment_score,
            trend_strength=trend_strength,
            has_structure=has_structure,
            has_bos=has_bos,
        )
        return SetupCandidate(
            symbol=item.symbol,
            bias=bias,
            score=score,
            alignment_score=alignment_score,
            trend_state=trend_state,
            trend_strength=trend_strength,
            has_structure=has_structure,
            has_bos=has_bos,
            latest_price=latest_price,
            reasons=reasons_for_candidate(
                alignment_score=alignment_score,
                trend_strength=trend_strength,
                has_structure=has_structure,
                has_bos=has_bos,
            ),
        )

    def _publish_candidate(self, candidate: SetupCandidate) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(SetupCandidateFoundEvent(candidate=candidate))

    def _publish_summary(self, summary: ScannerSummary) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(ScannerCompletedEvent(summary=summary))


def resolve_bias(item: SymbolScanInput) -> DirectionalBias:
    """Resolve scan bias from existing alignment/trend outputs for FR-904."""

    if item.alignment is not None:
        return item.alignment.bias
    if item.trend is not None:
        if item.trend.state is TrendState.BULLISH:
            return DirectionalBias.BULLISH
        if item.trend.state is TrendState.BEARISH:
            return DirectionalBias.BEARISH
    return DirectionalBias.NEUTRAL


def score_candidate(
    *,
    alignment_score: int,
    trend_strength: int,
    has_structure: bool,
    has_bos: bool,
) -> float:
    """Simple deterministic setup score for FR-903 and FR-905."""

    score = float(alignment_score * 10)
    score += min(trend_strength, 5) * 2
    if has_structure:
        score += 3
    if has_bos:
        score += 5
    return score


def reasons_for_candidate(
    *,
    alignment_score: int,
    trend_strength: int,
    has_structure: bool,
    has_bos: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if alignment_score:
        reasons.append("alignment")
    if trend_strength:
        reasons.append("trend_strength")
    if has_structure:
        reasons.append("structure")
    if has_bos:
        reasons.append("bos")
    if not reasons:
        reasons.append("insufficient_data")
    return tuple(reasons)
