from __future__ import annotations

from dataclasses import dataclass

from backend.models.domain import Candle


@dataclass(frozen=True, slots=True)
class TimeframeCandleClosedEvent:
    """Published when a 4H, daily, or weekly candle closes for FR-306."""

    candle: Candle
