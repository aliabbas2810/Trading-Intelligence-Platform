from __future__ import annotations

from datetime import UTC, datetime

from backend.engines.historical import (
    HistoricalHorizon,
    HistoricalSyncPlanner,
    required_start_for_configured_horizon,
    required_start_for_horizon,
)
from backend.models import Candle, Timeframe


MINUTE = 60_000


def test_planner_empty_cache_requests_full_prefix_window() -> None:
    plan = HistoricalSyncPlanner().plan(
        required_start_time_ms=0,
        required_end_time_ms=5 * MINUTE,
        cached_open_times_ms=(),
        timeframe=Timeframe.ONE_MINUTE,
    )

    assert plan.cache_complete is False
    assert [(window.start_time_ms, window.end_time_ms, window.reason) for window in plan.download_windows] == [
        (0, 5 * MINUTE, "prefix")
    ]
    assert plan.replay_start_time_ms == 0
    assert plan.replay_end_time_ms == 5 * MINUTE
    assert plan.requested_candle_count == 5


def test_planner_complete_cache_has_no_download_windows() -> None:
    plan = HistoricalSyncPlanner().plan(
        required_start_time_ms=0,
        required_end_time_ms=4 * MINUTE,
        cached_open_times_ms=(0, MINUTE, 2 * MINUTE, 3 * MINUTE),
        timeframe=Timeframe.ONE_MINUTE,
    )

    assert plan.cache_complete is True
    assert plan.download_windows == ()
    assert plan.requested_candle_count == 0


def test_planner_detects_prefix_tail_and_internal_gaps() -> None:
    plan = HistoricalSyncPlanner().plan(
        required_start_time_ms=0,
        required_end_time_ms=8 * MINUTE,
        cached_open_times_ms=(2 * MINUTE, 3 * MINUTE, 5 * MINUTE),
        timeframe=Timeframe.ONE_MINUTE,
    )

    assert [(window.start_time_ms, window.end_time_ms, window.reason) for window in plan.download_windows] == [
        (0, 2 * MINUTE, "prefix"),
        (4 * MINUTE, 5 * MINUTE, "internal_gap"),
        (6 * MINUTE, 8 * MINUTE, "tail"),
    ]


def test_planner_ignores_outside_range_and_deduplicates_unsorted_cache() -> None:
    plan = HistoricalSyncPlanner().plan(
        required_start_time_ms=MINUTE,
        required_end_time_ms=4 * MINUTE,
        cached_open_times_ms=(3 * MINUTE, 0, MINUTE, MINUTE, 5 * MINUTE),
        timeframe=Timeframe.ONE_MINUTE,
    )

    assert [(window.start_time_ms, window.end_time_ms, window.reason) for window in plan.download_windows] == [
        (2 * MINUTE, 3 * MINUTE, "internal_gap")
    ]


def test_planner_is_timeframe_aware_for_five_minute_windows() -> None:
    duration_ms = 5 * MINUTE
    plan = HistoricalSyncPlanner().plan(
        required_start_time_ms=0,
        required_end_time_ms=4 * duration_ms,
        cached_open_times_ms=(0, duration_ms, 3 * duration_ms),
        timeframe=Timeframe.FIVE_MINUTE,
    )

    assert [(window.start_time_ms, window.end_time_ms, window.reason) for window in plan.download_windows] == [
        (2 * duration_ms, 3 * duration_ms, "internal_gap")
    ]


def test_required_start_uses_calendar_year_not_fixed_days() -> None:
    latest_ms = utc_ms(2025, 7, 19, 12, 34)

    required_start = required_start_for_horizon(
        latest_ms,
        timeframe=Timeframe.ONE_MINUTE,
        horizon=HistoricalHorizon(years=1),
    )

    assert required_start == utc_ms(2024, 7, 19, 12, 34)


def test_create_plan_derives_calendar_year_window_from_latest_closed_candle() -> None:
    latest_ms = utc_ms(2025, 1, 1, 0, 0)

    plan = HistoricalSyncPlanner().create_plan(
        latest_closed_open_time_ms=latest_ms,
        timeframe=Timeframe.ONE_MINUTE,
        horizon=HistoricalHorizon(years=1),
        cached_open_times_ms=(),
    )

    assert plan.required_start_time_ms == utc_ms(2024, 1, 1, 0, 0)
    assert plan.required_end_time_ms == utc_ms(2025, 1, 1, 0, 1)
    assert plan.replay_start_time_ms == plan.required_start_time_ms
    assert plan.replay_end_time_ms == plan.required_end_time_ms
    assert len(plan.download_windows) == 1
    assert plan.download_windows[0].reason == "prefix"
    assert plan.requested_candle_count == (
        plan.required_end_time_ms - plan.required_start_time_ms
    ) // MINUTE


def test_configured_horizon_legacy_days_override_remains_deterministic() -> None:
    latest_ms = utc_ms(2025, 1, 10, 0, 0)

    required_start = required_start_for_configured_horizon(
        latest_ms,
        timeframe=Timeframe.ONE_MINUTE,
        horizon=HistoricalHorizon(years=1),
        legacy_horizon_days=2,
    )

    assert required_start == utc_ms(2025, 1, 8, 0, 0)


def test_required_start_clamps_feb_29_to_feb_28() -> None:
    latest_ms = utc_ms(2024, 2, 29, 0, 0)

    required_start = required_start_for_horizon(
        latest_ms,
        timeframe=Timeframe.ONE_MINUTE,
        horizon=HistoricalHorizon(years=1),
    )

    assert required_start == utc_ms(2023, 2, 28, 0, 0)


def test_create_plan_legacy_days_override_bypasses_calendar_year_window() -> None:
    latest_ms = utc_ms(2025, 1, 10, 0, 0)

    plan = HistoricalSyncPlanner().create_plan(
        latest_closed_open_time_ms=latest_ms,
        timeframe=Timeframe.ONE_MINUTE,
        horizon=HistoricalHorizon(years=1),
        legacy_horizon_days=1,
        cached_open_times_ms=(),
    )

    assert plan.required_start_time_ms == utc_ms(2025, 1, 9, 0, 0)
    assert plan.required_end_time_ms == utc_ms(2025, 1, 10, 0, 1)


def test_required_start_aligns_to_timeframe_boundary() -> None:
    latest_ms = utc_ms(2025, 1, 1, 1, 2)

    required_start = required_start_for_horizon(
        latest_ms,
        timeframe=Timeframe.FIVE_MINUTE,
        horizon=HistoricalHorizon(years=1),
    )

    assert required_start == utc_ms(2024, 1, 1, 1, 0)


def test_plan_selects_replay_candles_inside_planner_window() -> None:
    plan = HistoricalSyncPlanner().plan(
        required_start_time_ms=MINUTE,
        required_end_time_ms=4 * MINUTE,
        cached_open_times_ms=(MINUTE, 2 * MINUTE, 3 * MINUTE),
        timeframe=Timeframe.ONE_MINUTE,
    )
    source = (
        candle_for_open_time(0),
        candle_for_open_time(3 * MINUTE),
        candle_for_open_time(MINUTE),
        candle_for_open_time(4 * MINUTE),
    )

    replay_candles = plan.select_replay_candles(source)

    assert [candle.open_time_ms for candle in replay_candles] == [MINUTE, 3 * MINUTE]


def utc_ms(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp() * 1000)


def candle_for_open_time(open_time_ms: int) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + MINUTE,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=1.0,
    )
