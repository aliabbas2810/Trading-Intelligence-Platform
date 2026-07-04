from __future__ import annotations

from backend.engines.structure import BreakDirection, StructureEvent, StructureLabel
from backend.engines.trend.models import (
    PendingTrendFlip,
    TrendFlipMode,
    TrendState,
    TrendStrength,
    TrendUpdate,
)
from backend.models.domain import Timeframe


class TrendEngineError(ValueError):
    """Raised when trend input is inconsistent for deterministic replay."""


class TrendEngine:
    """Classify timeframe-independent trend from structure events for FR-501 through FR-508."""

    def __init__(self, flip_mode: TrendFlipMode = TrendFlipMode.IMMEDIATE) -> None:
        self._flip_mode = flip_mode
        self._state: TrendState | None = None
        self._symbol: str | None = None
        self._timeframe: Timeframe | None = None
        self._bullish_confirmations = 0
        self._bearish_confirmations = 0
        self._pending_flip: PendingTrendFlip | None = None

    @property
    def state(self) -> TrendState | None:
        return self._state

    def add_event(self, event: StructureEvent) -> TrendUpdate | None:
        """Consume one structure event and return a trend update when state changes."""

        self._validate_event(event)

        if event.break_of_structure is not None:
            return self._handle_bos(event)
        if event.swing is not None:
            return self._handle_swing(event)
        return None

    def _validate_event(self, event: StructureEvent) -> None:
        symbol, timeframe = structure_event_identity(event)
        if self._symbol is None:
            self._symbol = symbol
            self._timeframe = timeframe
            return
        if symbol != self._symbol or timeframe is not self._timeframe:
            raise TrendEngineError("TrendEngine only accepts one symbol/timeframe per instance")

    def _handle_swing(self, event: StructureEvent) -> TrendUpdate | None:
        if event.swing is None:
            raise RuntimeError("Missing swing")

        label = event.swing.label
        if label in {StructureLabel.HH, StructureLabel.HL}:
            self._bullish_confirmations += 1
        if label in {StructureLabel.LH, StructureLabel.LL}:
            self._bearish_confirmations += 1

        if self._pending_flip is not None:
            if self._pending_flip.direction is BreakDirection.BULLISH and label is StructureLabel.HH:
                return self._set_state(
                    TrendState.BULLISH,
                    reason="confirmed_bullish_flip",
                    event_time_ms=event.swing.candle_close_time_ms,
                )
            if self._pending_flip.direction is BreakDirection.BEARISH and label is StructureLabel.LL:
                return self._set_state(
                    TrendState.BEARISH,
                    reason="confirmed_bearish_flip",
                    event_time_ms=event.swing.candle_close_time_ms,
                )

        inferred_state = self._infer_state_from_structure()
        if inferred_state is not None and self._state is None:
            return self._set_state(
                inferred_state,
                reason="structure_sequence",
                event_time_ms=event.swing.candle_close_time_ms,
            )

        return None

    def _handle_bos(self, event: StructureEvent) -> TrendUpdate:
        if event.break_of_structure is None:
            raise RuntimeError("Missing BOS")

        direction = event.break_of_structure.direction
        if self._flip_mode is TrendFlipMode.IMMEDIATE:
            target_state = trend_state_for_break(direction)
            return self._set_state(
                target_state,
                reason="bos_immediate_flip",
                event_time_ms=event.break_of_structure.candle_close_time_ms,
            )

        target_state = trend_state_for_break(direction)
        self._pending_flip = PendingTrendFlip(direction=direction, target_state=target_state)
        return self._set_state(
            TrendState.TRANSITION,
            reason="bos_pending_confirmation",
            event_time_ms=event.break_of_structure.candle_close_time_ms,
        )

    def _infer_state_from_structure(self) -> TrendState | None:
        if self._bullish_confirmations >= 2 and self._bullish_confirmations > self._bearish_confirmations:
            return TrendState.BULLISH
        if self._bearish_confirmations >= 2 and self._bearish_confirmations > self._bullish_confirmations:
            return TrendState.BEARISH
        return None

    def _set_state(
        self,
        state: TrendState,
        *,
        reason: str,
        event_time_ms: int,
    ) -> TrendUpdate:
        previous_state = self._state
        self._state = state
        if state is not TrendState.TRANSITION:
            self._pending_flip = None

        if self._symbol is None or self._timeframe is None:
            raise RuntimeError("Trend identity is not initialized")

        return TrendUpdate(
            symbol=self._symbol,
            timeframe=self._timeframe,
            state=state,
            previous_state=previous_state,
            strength=self._strength_for_state(state),
            reason=reason,
            event_time_ms=event_time_ms,
        )

    def _strength_for_state(self, state: TrendState) -> TrendStrength:
        if state is TrendState.BULLISH:
            return TrendStrength(confirming_structure_count=self._bullish_confirmations)
        if state is TrendState.BEARISH:
            return TrendStrength(confirming_structure_count=self._bearish_confirmations)
        return TrendStrength(confirming_structure_count=0)


def trend_state_for_break(direction: BreakDirection) -> TrendState:
    if direction is BreakDirection.BULLISH:
        return TrendState.BULLISH
    return TrendState.BEARISH


def structure_event_identity(event: StructureEvent) -> tuple[str, Timeframe]:
    if event.swing is not None:
        return event.swing.symbol, event.swing.timeframe
    if event.break_of_structure is not None:
        return event.break_of_structure.symbol, event.break_of_structure.timeframe
    raise TrendEngineError("StructureEvent must contain structure data")
