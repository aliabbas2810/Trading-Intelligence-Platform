from __future__ import annotations

from dataclasses import dataclass

from backend.engines.trend.models import TrendUpdate


@dataclass(frozen=True, slots=True)
class TrendChangedEvent:
    """Published trend state update model for FR-508."""

    update: TrendUpdate
