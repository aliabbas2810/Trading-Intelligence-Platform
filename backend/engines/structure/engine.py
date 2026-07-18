from __future__ import annotations

from backend.engines.structure.displacement import (
    DisplacementThreshold,
    PercentDisplacementThreshold,
)
from backend.engines.structure.models import (
    BreakDirection,
    BreakOfStructure,
    BodyRange,
    StructureEvent,
    StructureDiagnostics,
    StructureLabel,
    StructureSwing,
    SwingKind,
)
from backend.models.domain import Candle, Timeframe


class MarketStructureError(ValueError):
    """Raised when structure input is inconsistent for deterministic replay."""


class MarketStructureEngine:
    """Body-only market structure engine for FR-401 through FR-412."""

    def __init__(
        self,
        displacement: DisplacementThreshold | None = None,
        *,
        bullish_displacement: DisplacementThreshold | None = None,
        bearish_displacement: DisplacementThreshold | None = None,
    ) -> None:
        default_displacement = displacement or PercentDisplacementThreshold(percent=0.02)
        self._bullish_displacement = bullish_displacement or default_displacement
        self._bearish_displacement = bearish_displacement or default_displacement
        self._symbol: str | None = None
        self._timeframe: Timeframe | None = None
        self._last_close_time_ms: int | None = None
        self._candidate_high: Candle | None = None
        self._candidate_low: Candle | None = None
        self._seeking: SwingKind | None = None
        self._last_high_swing: StructureSwing | None = None
        self._last_low_swing: StructureSwing | None = None
        self._last_bullish_bos_level: float | None = None
        self._last_bearish_bos_level: float | None = None
        self._candle_count = 0
        self._candidate_updates = 0
        self._confirmed_swings = 0
        self._bos_count = 0
        self._label_counts: dict[StructureLabel, int] = {label: 0 for label in StructureLabel}
        self._same_role_run_length = 0
        self._max_same_role_run_length = 0
        self._alternation_violation_count = 0
        self._last_confirmed_kind: SwingKind | None = None

    def add_candle(self, candle: Candle) -> tuple[StructureEvent, ...]:
        """Consume one completed candle and emit deterministic structure events."""

        self._validate_candle(candle)
        self._candle_count += 1
        events: list[StructureEvent] = []

        bullish_bos = self._detect_bullish_bos(candle)
        if bullish_bos is not None:
            self._bos_count += 1
            events.append(StructureEvent(break_of_structure=bullish_bos))

        bearish_bos = self._detect_bearish_bos(candle)
        if bearish_bos is not None:
            self._bos_count += 1
            events.append(StructureEvent(break_of_structure=bearish_bos))

        swing = self._update_displacement_candidates(candle)
        if swing is not None:
            self._remember_swing(swing)
            self._confirmed_swings += 1
            self._label_counts[swing.label] += 1
            self._remember_confirmed_kind(swing.kind)
            events.append(StructureEvent(swing=swing))

        self._last_close_time_ms = candle.close_time_ms
        return tuple(events)

    def diagnostics(
        self,
        *,
        duplicate_structures: int = 0,
        duplicate_bos: int = 0,
        density_anomaly_ratio: float = 0.35,
        bos_anomaly_ratio: float = 0.75,
    ) -> StructureDiagnostics:
        """Expose lifecycle metrics without changing structure behaviour."""

        structure_ratio = self._confirmed_swings / self._candle_count if self._candle_count else 0.0
        bos_ratio = self._bos_count / self._confirmed_swings if self._confirmed_swings else 0.0
        return StructureDiagnostics(
            candidate_swings=self._candidate_updates,
            provisional_swings=1 if self._seeking is not None else 0,
            confirmed_swings=self._confirmed_swings,
            hh=self._label_counts[StructureLabel.HH],
            hl=self._label_counts[StructureLabel.HL],
            lh=self._label_counts[StructureLabel.LH],
            ll=self._label_counts[StructureLabel.LL],
            bos=self._bos_count,
            duplicate_structures=duplicate_structures,
            duplicate_bos=duplicate_bos,
            alternation_violation_count=self._alternation_violation_count,
            same_role_run_length=self._max_same_role_run_length,
            candle_count=self._candle_count,
            structure_candle_ratio=structure_ratio,
            bos_swing_ratio=bos_ratio,
            structure_density_anomaly=structure_ratio >= density_anomaly_ratio or bos_ratio >= bos_anomaly_ratio,
        )

    def _validate_candle(self, candle: Candle) -> None:
        if self._symbol is None:
            self._symbol = candle.symbol
            self._timeframe = candle.timeframe
            return

        if candle.symbol != self._symbol:
            raise MarketStructureError("MarketStructureEngine only accepts one symbol per instance")
        if candle.timeframe is not self._timeframe:
            raise MarketStructureError("MarketStructureEngine only accepts one timeframe per instance")
        if self._last_close_time_ms is not None and candle.open_time_ms < self._last_close_time_ms:
            raise MarketStructureError("Candles must be added in increasing time order")

    def _update_displacement_candidates(self, candle: Candle) -> StructureSwing | None:
        """Confirm swings by opposite body displacement, not fixed candle counts."""

        if self._candidate_high is None or self._candidate_low is None:
            self._candidate_high = candle
            self._candidate_low = candle
            return None

        if self._seeking is None:
            return self._update_initial_candidates(candle)
        if self._seeking is SwingKind.HIGH:
            return self._seek_high(candle)
        return self._seek_low(candle)

    def _update_initial_candidates(self, candle: Candle) -> StructureSwing | None:
        previous_high = self._candidate_high
        previous_low = self._candidate_low
        self._candidate_high = higher_body_high(self._candidate_high, candle)
        self._candidate_low = lower_body_low(self._candidate_low, candle)
        self._count_candidate_update(previous_high, self._candidate_high)
        self._count_candidate_update(previous_low, self._candidate_low)

        if self._candidate_high is None or self._candidate_low is None:
            raise RuntimeError("Missing initial displacement candidates")

        impulse_range = self._candidate_high.body_high - self._candidate_low.body_low
        high_threshold = self._bullish_displacement.threshold(self._candidate_high)
        low_threshold = self._bearish_displacement.threshold(self._candidate_low)

        if self._candidate_high is candle and impulse_range >= high_threshold:
            self._seeking = SwingKind.HIGH
        elif self._candidate_low is candle and impulse_range >= low_threshold:
            self._seeking = SwingKind.LOW

        return None

    def _seek_high(self, candle: Candle) -> StructureSwing | None:
        previous = self._candidate_high
        self._candidate_high = higher_body_high(self._candidate_high, candle)
        self._count_candidate_update(previous, self._candidate_high)
        if self._candidate_high is None:
            raise RuntimeError("Missing high candidate")
        if self._candidate_high is candle and previous is not candle:
            return None
        if self._high_pullback(candle) >= self._bullish_displacement.threshold(self._candidate_high):
            return self._confirm_high(candle)
        return None

    def _seek_low(self, candle: Candle) -> StructureSwing | None:
        previous = self._candidate_low
        self._candidate_low = lower_body_low(self._candidate_low, candle)
        self._count_candidate_update(previous, self._candidate_low)
        if self._candidate_low is None:
            raise RuntimeError("Missing low candidate")
        if self._candidate_low is candle and previous is not candle:
            return None
        if self._low_pullback(candle) >= self._bearish_displacement.threshold(self._candidate_low):
            return self._confirm_low(candle)
        return None

    def _high_pullback(self, candle: Candle) -> float:
        if self._candidate_high is None:
            return 0.0
        return self._candidate_high.body_high - candle.body_low

    def _low_pullback(self, candle: Candle) -> float:
        if self._candidate_low is None:
            return 0.0
        return candle.body_high - self._candidate_low.body_low

    def _confirm_high(self, pullback_candle: Candle) -> StructureSwing:
        if self._candidate_high is None:
            raise RuntimeError("Missing high candidate")
        swing = self._make_swing(self._candidate_high, SwingKind.HIGH)
        self._candidate_low = pullback_candle
        self._candidate_high = pullback_candle
        self._seeking = SwingKind.LOW
        return swing

    def _confirm_low(self, pullback_candle: Candle) -> StructureSwing:
        if self._candidate_low is None:
            raise RuntimeError("Missing low candidate")
        swing = self._make_swing(self._candidate_low, SwingKind.LOW)
        self._candidate_high = pullback_candle
        self._candidate_low = pullback_candle
        self._seeking = SwingKind.HIGH
        return swing

    def _make_swing(self, candle: Candle, kind: SwingKind) -> StructureSwing:
        body = BodyRange.from_candle(candle)
        if kind is SwingKind.HIGH:
            previous = self._last_high_swing
            level = body.high
            label = StructureLabel.HH if previous is None or level > previous.level else StructureLabel.LH
        else:
            previous = self._last_low_swing
            level = body.low
            label = StructureLabel.HL if previous is None or level > previous.level else StructureLabel.LL

        return StructureSwing(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            kind=kind,
            label=label,
            level=level,
            candle_open_time_ms=candle.open_time_ms,
            candle_close_time_ms=candle.close_time_ms,
        )

    def _remember_swing(self, swing: StructureSwing) -> None:
        if swing.kind is SwingKind.HIGH:
            self._last_high_swing = swing
        else:
            self._last_low_swing = swing

    def _remember_confirmed_kind(self, kind: SwingKind) -> None:
        if self._last_confirmed_kind is kind:
            self._same_role_run_length += 1
            self._alternation_violation_count += 1
        else:
            self._same_role_run_length = 1
            self._last_confirmed_kind = kind
        self._max_same_role_run_length = max(self._max_same_role_run_length, self._same_role_run_length)

    def _count_candidate_update(self, previous: Candle | None, current: Candle | None) -> None:
        if previous is not None and current is not None and current is not previous:
            self._candidate_updates += 1

    def _detect_bullish_bos(self, candle: Candle) -> BreakOfStructure | None:
        if self._last_high_swing is None:
            return None
        if candle.close <= self._last_high_swing.level:
            return None
        if self._last_bullish_bos_level == self._last_high_swing.level:
            return None

        self._last_bullish_bos_level = self._last_high_swing.level
        return BreakOfStructure(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            direction=BreakDirection.BULLISH,
            broken_label=self._last_high_swing.label,
            broken_level=self._last_high_swing.level,
            candle_close=candle.close,
            candle_open_time_ms=candle.open_time_ms,
            candle_close_time_ms=candle.close_time_ms,
        )

    def _detect_bearish_bos(self, candle: Candle) -> BreakOfStructure | None:
        if self._last_low_swing is None:
            return None
        if candle.close >= self._last_low_swing.level:
            return None
        if self._last_bearish_bos_level == self._last_low_swing.level:
            return None

        self._last_bearish_bos_level = self._last_low_swing.level
        return BreakOfStructure(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            direction=BreakDirection.BEARISH,
            broken_label=self._last_low_swing.label,
            broken_level=self._last_low_swing.level,
            candle_close=candle.close,
            candle_open_time_ms=candle.open_time_ms,
            candle_close_time_ms=candle.close_time_ms,
        )


def higher_body_high(current: Candle | None, candidate: Candle) -> Candle:
    if current is None or candidate.body_high >= current.body_high:
        return candidate
    return current


def lower_body_low(current: Candle | None, candidate: Candle) -> Candle:
    if current is None or candidate.body_low <= current.body_low:
        return candidate
    return current
