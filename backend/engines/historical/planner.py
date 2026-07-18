from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from backend.models import Candle, Timeframe
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms


HistoricalSyncWindowReason = Literal["prefix", "internal_gap", "tail"]


@dataclass(frozen=True, slots=True)
class HistoricalSyncWindow:
    """Missing historical cache window planned for M31.6.2 deterministic synchronization."""

    start_time_ms: int
    end_time_ms: int
    reason: HistoricalSyncWindowReason

    def __post_init__(self) -> None:
        if self.start_time_ms < 0:
            raise ValueError("start_time_ms must be non-negative")
        if self.end_time_ms <= self.start_time_ms:
            raise ValueError("end_time_ms must be after start_time_ms")


@dataclass(frozen=True, slots=True)
class HistoricalSyncPlan:
    """One-year startup cache/replay plan for M31.6.2."""

    required_start_time_ms: int
    required_end_time_ms: int
    download_windows: tuple[HistoricalSyncWindow, ...]
    replay_start_time_ms: int
    replay_end_time_ms: int
    requested_candle_count: int
    cache_complete: bool

    def select_replay_candles(self, candles: Iterable[Candle]) -> tuple[Candle, ...]:
        """Return only candles inside the planner-owned replay window."""

        return tuple(
            sorted(
                (
                    candle
                    for candle in candles
                    if self.replay_start_time_ms <= candle.open_time_ms < self.replay_end_time_ms
                ),
                key=lambda candle: candle.open_time_ms,
            )
        )


@dataclass(frozen=True, slots=True)
class HistoricalHorizon:
    """Calendar-aware lookback horizon; Feb 29 subtracts to Feb 28 when needed."""

    years: int = 1
    months: int = 0
    days: int = 0


class HistoricalSyncPlanner:
    """Plan missing cache windows without touching disk or network for M31.6.2."""

    def create_plan(
        self,
        *,
        latest_closed_open_time_ms: int,
        timeframe: Timeframe,
        horizon: HistoricalHorizon,
        cached_open_times_ms: tuple[int, ...],
        legacy_horizon_days: int | None = None,
    ) -> HistoricalSyncPlan:
        """Create a complete calendar-aware startup synchronization plan."""

        duration_ms = timeframe_duration_ms(timeframe)
        latest_aligned_ms = align_down_ms(latest_closed_open_time_ms, duration_ms)
        required_start_time_ms = required_start_for_configured_horizon(
            latest_aligned_ms,
            timeframe=timeframe,
            horizon=horizon,
            legacy_horizon_days=legacy_horizon_days,
        )
        return self.plan(
            required_start_time_ms=required_start_time_ms,
            required_end_time_ms=latest_aligned_ms + duration_ms,
            cached_open_times_ms=cached_open_times_ms,
            timeframe=timeframe,
        )

    def plan(
        self,
        *,
        required_start_time_ms: int,
        required_end_time_ms: int,
        cached_open_times_ms: tuple[int, ...],
        timeframe: Timeframe,
    ) -> HistoricalSyncPlan:
        duration_ms = timeframe_duration_ms(timeframe)
        start_ms = align_down_ms(required_start_time_ms, duration_ms)
        end_ms = align_down_ms(required_end_time_ms, duration_ms)
        if end_ms <= start_ms:
            raise ValueError("required_end_time_ms must be after required_start_time_ms")

        present = {
            align_down_ms(open_time_ms, duration_ms)
            for open_time_ms in cached_open_times_ms
            if start_ms <= open_time_ms < end_ms
        }
        windows = tuple(self._missing_windows(start_ms, end_ms, present, duration_ms))
        return HistoricalSyncPlan(
            required_start_time_ms=start_ms,
            required_end_time_ms=end_ms,
            download_windows=windows,
            replay_start_time_ms=start_ms,
            replay_end_time_ms=end_ms,
            requested_candle_count=sum(
                (window.end_time_ms - window.start_time_ms) // duration_ms for window in windows
            ),
            cache_complete=not windows,
        )

    def _missing_windows(
        self,
        start_ms: int,
        end_ms: int,
        present: set[int],
        duration_ms: int,
    ) -> tuple[HistoricalSyncWindow, ...]:
        windows: list[HistoricalSyncWindow] = []
        missing_start_ms: int | None = None
        for open_time_ms in range(start_ms, end_ms, duration_ms):
            if open_time_ms not in present:
                if missing_start_ms is None:
                    missing_start_ms = open_time_ms
                continue
            if missing_start_ms is not None:
                windows.append(
                    HistoricalSyncWindow(
                        start_time_ms=missing_start_ms,
                        end_time_ms=open_time_ms,
                        reason=window_reason(missing_start_ms, open_time_ms, start_ms, end_ms),
                    )
                )
                missing_start_ms = None
        if missing_start_ms is not None:
            windows.append(
                HistoricalSyncWindow(
                    start_time_ms=missing_start_ms,
                    end_time_ms=end_ms,
                    reason=window_reason(missing_start_ms, end_ms, start_ms, end_ms),
                )
            )
        return merge_adjacent_windows(tuple(windows))


def required_start_for_horizon(
    latest_closed_open_time_ms: int,
    *,
    timeframe: Timeframe,
    horizon: HistoricalHorizon,
) -> int:
    """Subtract a calendar horizon from the latest closed candle open for M31.6.2."""

    duration_ms = timeframe_duration_ms(timeframe)
    latest_aligned_ms = align_down_ms(latest_closed_open_time_ms, duration_ms)
    latest_dt = datetime.fromtimestamp(latest_aligned_ms / 1000, tz=UTC)
    shifted = subtract_calendar_horizon(latest_dt, horizon)
    return max(0, align_down_ms(int(shifted.timestamp() * 1000), duration_ms))


def required_start_for_configured_horizon(
    latest_closed_open_time_ms: int,
    *,
    timeframe: Timeframe,
    horizon: HistoricalHorizon,
    legacy_horizon_days: int | None = None,
) -> int:
    """Resolve legacy day override or structured calendar horizon outside Runtime."""

    duration_ms = timeframe_duration_ms(timeframe)
    latest_aligned_ms = align_down_ms(latest_closed_open_time_ms, duration_ms)
    if legacy_horizon_days is not None:
        day_ms = 24 * 60 * 60 * 1000
        return max(0, align_down_ms(latest_aligned_ms - legacy_horizon_days * day_ms, duration_ms))
    return required_start_for_horizon(latest_aligned_ms, timeframe=timeframe, horizon=horizon)


def subtract_calendar_horizon(value: datetime, horizon: HistoricalHorizon) -> datetime:
    """Subtract calendar years/months/days with deterministic leap-day clamping."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    total_month = value.year * 12 + (value.month - 1) - horizon.years * 12 - horizon.months
    target_year = total_month // 12
    target_month = total_month % 12 + 1
    target_day = min(value.day, calendar.monthrange(target_year, target_month)[1])
    shifted = value.replace(year=target_year, month=target_month, day=target_day)
    if horizon.days:
        shifted -= timedelta(days=horizon.days)
    return shifted


def align_down_ms(timestamp_ms: int, duration_ms: int) -> int:
    return timestamp_ms - (timestamp_ms % duration_ms)


def window_reason(
    missing_start_ms: int,
    missing_end_ms: int,
    required_start_ms: int,
    required_end_ms: int,
) -> HistoricalSyncWindowReason:
    if missing_start_ms == required_start_ms:
        return "prefix"
    if missing_end_ms == required_end_ms:
        return "tail"
    return "internal_gap"


def merge_adjacent_windows(windows: tuple[HistoricalSyncWindow, ...]) -> tuple[HistoricalSyncWindow, ...]:
    if not windows:
        return ()
    merged: list[HistoricalSyncWindow] = []
    for window in sorted(windows, key=lambda item: (item.start_time_ms, item.end_time_ms)):
        if not merged:
            merged.append(window)
            continue
        previous = merged[-1]
        if previous.end_time_ms == window.start_time_ms and previous.reason == window.reason:
            merged[-1] = HistoricalSyncWindow(
                start_time_ms=previous.start_time_ms,
                end_time_ms=window.end_time_ms,
                reason=previous.reason,
            )
            continue
        merged.append(window)
    return tuple(merged)
