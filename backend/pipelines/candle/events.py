from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.models.domain import Candle


class CandleEventSource(str, Enum):
    """Provenance for completed candle events crossing live/replay boundaries."""

    LIVE_STREAM = "live_stream"
    HISTORICAL_REPLAY = "historical_replay"
    HISTORICAL_SYNC = "historical_sync"


@dataclass(frozen=True, slots=True)
class CandleClosedEvent:
    """Published after a completed one-minute candle for FR-209."""

    candle: Candle
    is_synthetic: bool = False
    source: CandleEventSource = CandleEventSource.LIVE_STREAM
