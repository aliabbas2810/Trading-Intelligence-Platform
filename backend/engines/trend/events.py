from __future__ import annotations

from dataclasses import dataclass

from backend.engines.trend.aggregation import MultiTimeframeTrendResult
from backend.engines.trend.models import TrendUpdate


@dataclass(frozen=True, slots=True)
class TrendChangedEvent:
    """Published trend state update model for FR-508."""

    update: TrendUpdate


@dataclass(frozen=True, slots=True)
class MultiTimeframeTrendAggregatedEvent:
    """Published multi-timeframe aggregation event for FR-508."""

    result: MultiTimeframeTrendResult
