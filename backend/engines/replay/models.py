from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReplayStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    """One historical event scheduled for replay through the live event bus."""

    timestamp_ms: int
    sequence: int
    event: object

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("ReplayRecord timestamp_ms must be non-negative")
        if self.sequence < 0:
            raise ValueError("ReplayRecord sequence must be non-negative")


@dataclass(frozen=True, slots=True)
class ReplayLifecycleEvent:
    """Replay lifecycle notification for FR-801, FR-803, FR-804, and FR-805."""

    status: ReplayStatus
    previous_status: ReplayStatus
    message: str


@dataclass(frozen=True, slots=True)
class ReplayProgressEvent:
    """Replay progress/status report for FR-801, FR-802, and TEST-001."""

    status: ReplayStatus
    processed_events: int
    total_events: int
    current_timestamp_ms: int | None
    speed_multiplier: float
