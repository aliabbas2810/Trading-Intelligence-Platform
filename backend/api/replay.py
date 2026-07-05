from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.replay_runtime import ReplaySourceType, ReplayStatusSnapshot


class ReplayStartRequest(BaseModel):
    """Replay start request for FR-801 and FR-802."""

    source_type: ReplaySourceType = ReplaySourceType.TRADES
    speed_multiplier: float = Field(default=1.0, gt=0)


class ReplayStatusResponse(BaseModel):
    """Replay API status response for FR-801 through FR-805."""

    source_type: ReplaySourceType | None
    status: str
    processed_events: int
    total_events: int
    current_timestamp_ms: int | None
    speed_multiplier: float
    progress: float
    running: bool
    paused: bool
    stopped: bool

    @classmethod
    def from_snapshot(cls, snapshot: ReplayStatusSnapshot) -> ReplayStatusResponse:
        return cls(
            source_type=snapshot.source_type,
            status=snapshot.status.value,
            processed_events=snapshot.processed_events,
            total_events=snapshot.total_events,
            current_timestamp_ms=snapshot.current_timestamp_ms,
            speed_multiplier=snapshot.speed_multiplier,
            progress=snapshot.progress,
            running=snapshot.status.value == "running",
            paused=snapshot.status.value == "paused",
            stopped=snapshot.status.value in {"stopped", "completed"},
        )
