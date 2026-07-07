from __future__ import annotations

from collections.abc import Callable

from backend.core import EventBus, get_logger
from backend.engines.replay.models import ReplayLifecycleEvent, ReplayProgressEvent, ReplayStatus
from backend.engines.replay.sources import ReplaySource


class ReplayControllerError(ValueError):
    """Raised for invalid replay controller usage."""


class ReplayController:
    """Replay historical events through the same synchronous event bus as live mode."""

    def __init__(
        self,
        event_bus: EventBus,
        source: ReplaySource,
        *,
        speed_multiplier: float = 1.0,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._records = source.list_records()
        self._index = 0
        self._status = ReplayStatus.READY
        self._last_timestamp_ms: int | None = None
        self._sleeper = sleeper
        self._logger = get_logger(__name__)
        self._speed_multiplier = self._validate_speed(speed_multiplier)

    @property
    def status(self) -> ReplayStatus:
        return self._status

    @property
    def progress(self) -> ReplayProgressEvent:
        return self._progress_event()

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    def set_speed_multiplier(self, speed_multiplier: float) -> None:
        """Update replay speed for FR-802 without changing event order."""

        self._speed_multiplier = self._validate_speed(speed_multiplier)
        self._publish_progress()

    def start(self) -> None:
        """Start or continue replay until pause, stop, or completion."""

        if self._status is ReplayStatus.COMPLETED:
            return
        if self._status is ReplayStatus.STOPPED:
            self._index = 0
            self._last_timestamp_ms = None

        self._set_status(ReplayStatus.RUNNING, "replay_started")
        while self._status is ReplayStatus.RUNNING and self._index < len(self._records):
            self._publish_next(apply_speed_delay=True)

        if self._status is ReplayStatus.RUNNING and self._index >= len(self._records):
            self._set_status(ReplayStatus.COMPLETED, "replay_completed")
            self._publish_progress()

    def begin(self) -> None:
        """Enter running state without draining the replay source."""

        if self._status is ReplayStatus.COMPLETED:
            return
        if self._status is ReplayStatus.STOPPED:
            self._index = 0
            self._last_timestamp_ms = None
        if self._index >= len(self._records):
            self._set_status(ReplayStatus.COMPLETED, "replay_completed")
        else:
            self._set_status(ReplayStatus.RUNNING, "replay_started")
        self._publish_progress()

    def stop(self) -> None:
        """Stop replay for FR-801 status control."""

        if self._status is not ReplayStatus.STOPPED:
            self._set_status(ReplayStatus.STOPPED, "replay_stopped")

    def pause(self) -> None:
        """Pause replay for FR-803."""

        if self._status is ReplayStatus.RUNNING:
            self._set_status(ReplayStatus.PAUSED, "replay_paused")

    def resume(self) -> None:
        """Resume a paused replay for FR-804."""

        if self._status is ReplayStatus.PAUSED:
            self.start()

    def step(self) -> None:
        """Publish exactly one historical event for FR-805 step mode."""

        if self._status in {ReplayStatus.COMPLETED, ReplayStatus.STOPPED}:
            return
        if self._index >= len(self._records):
            self._set_status(ReplayStatus.COMPLETED, "replay_completed")
            self._publish_progress()
            return

        if self._status is not ReplayStatus.PAUSED:
            self._set_status(ReplayStatus.PAUSED, "replay_step_mode")
        self._publish_next(apply_speed_delay=False)
        if self._index >= len(self._records):
            self._set_status(ReplayStatus.COMPLETED, "replay_completed")
        self._publish_progress()

    def advance_running_once(self) -> None:
        """Publish one event while preserving running state for API-driven replay starts."""

        if self._status is not ReplayStatus.RUNNING:
            return
        if self._index >= len(self._records):
            self._set_status(ReplayStatus.COMPLETED, "replay_completed")
            self._publish_progress()
            return

        self._publish_next(apply_speed_delay=False)
        if self._index >= len(self._records):
            self._set_status(ReplayStatus.COMPLETED, "replay_completed")
        self._publish_progress()

    def _publish_next(self, *, apply_speed_delay: bool) -> None:
        record = self._records[self._index]
        if apply_speed_delay:
            self._sleep_until(record.timestamp_ms)

        self._event_bus.publish(record.event)
        self._last_timestamp_ms = record.timestamp_ms
        self._index += 1
        self._publish_progress()

    def _sleep_until(self, timestamp_ms: int) -> None:
        if self._sleeper is None or self._last_timestamp_ms is None:
            return
        delay_seconds = max(0.0, (timestamp_ms - self._last_timestamp_ms) / 1000.0)
        if delay_seconds > 0:
            self._sleeper(delay_seconds / self._speed_multiplier)

    def _set_status(self, status: ReplayStatus, message: str) -> None:
        previous_status = self._status
        if previous_status is status:
            return
        self._status = status
        self._logger.info("Replay status changed")
        self._event_bus.publish(
            ReplayLifecycleEvent(
                status=status,
                previous_status=previous_status,
                message=message,
            ),
        )

    def _publish_progress(self) -> None:
        self._event_bus.publish(self._progress_event())

    def _progress_event(self) -> ReplayProgressEvent:
        return ReplayProgressEvent(
            status=self._status,
            processed_events=self._index,
            total_events=len(self._records),
            current_timestamp_ms=self._last_timestamp_ms,
            speed_multiplier=self._speed_multiplier,
        )

    def _validate_speed(self, speed_multiplier: float) -> float:
        if speed_multiplier <= 0:
            raise ReplayControllerError("Replay speed_multiplier must be positive")
        return speed_multiplier
