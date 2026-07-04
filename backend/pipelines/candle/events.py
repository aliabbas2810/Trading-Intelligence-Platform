from __future__ import annotations

from dataclasses import dataclass

from backend.models.domain import Candle


@dataclass(frozen=True, slots=True)
class CandleClosedEvent:
    """Published after a completed one-minute candle for FR-209."""

    candle: Candle
    is_synthetic: bool = False
