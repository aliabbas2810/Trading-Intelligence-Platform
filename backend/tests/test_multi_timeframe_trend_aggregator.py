from __future__ import annotations

from backend.engines.trend import (
    DirectionalBias,
    MultiTimeframeMode,
    MultiTimeframeTrendAggregatedEvent,
    MultiTimeframeTrendAggregator,
    TimeframeTrendSnapshot,
    TrendState,
    TrendStrength,
)
from backend.models import Timeframe


def snapshot(timeframe: Timeframe, state: TrendState, strength: int = 1) -> TimeframeTrendSnapshot:
    return TimeframeTrendSnapshot(
        symbol="BTCUSDT",
        timeframe=timeframe,
        state=state,
        strength=TrendStrength(confirming_structure_count=strength),
        event_time_ms=1_000,
    )


def test_voting_mode_two_of_three_bullish_creates_bullish_bias() -> None:
    """Covers FR-501, FR-502, FR-503, FR-504, FR-507, and TEST-001."""

    result = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.VOTING).aggregate(
        [
            snapshot(Timeframe.WEEKLY, TrendState.BULLISH),
            snapshot(Timeframe.DAILY, TrendState.BULLISH),
            snapshot(Timeframe.FOUR_HOUR, TrendState.BEARISH),
        ],
    )

    assert result.bias is DirectionalBias.BULLISH
    assert result.alignment_score == 2
    assert result.reason == "voting_bullish"


def test_voting_mode_two_of_three_bearish_creates_bearish_bias() -> None:
    """Covers FR-501, FR-502, FR-503, FR-504, FR-507, and TEST-001."""

    result = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.VOTING).aggregate(
        [
            snapshot(Timeframe.WEEKLY, TrendState.BEARISH),
            snapshot(Timeframe.DAILY, TrendState.TRANSITION),
            snapshot(Timeframe.FOUR_HOUR, TrendState.BEARISH),
        ],
    )

    assert result.bias is DirectionalBias.BEARISH
    assert result.alignment_score == 2
    assert result.reason == "voting_bearish"


def test_voting_mode_conflicting_trends_without_majority_are_neutral() -> None:
    """Covers conflicting trends, FR-507, and TEST-001."""

    result = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.VOTING).aggregate(
        [
            snapshot(Timeframe.WEEKLY, TrendState.BULLISH),
            snapshot(Timeframe.DAILY, TrendState.BEARISH),
            snapshot(Timeframe.FOUR_HOUR, TrendState.TRANSITION),
        ],
    )

    assert result.bias is DirectionalBias.NEUTRAL
    assert result.alignment_score == 1
    assert result.reason == "voting_no_majority"


def test_all_aligned_trends_have_three_of_three_alignment() -> None:
    """Covers all-aligned trends, FR-504, FR-507, and TEST-001."""

    result = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.VOTING).aggregate(
        [
            snapshot(Timeframe.WEEKLY, TrendState.BULLISH),
            snapshot(Timeframe.DAILY, TrendState.BULLISH),
            snapshot(Timeframe.FOUR_HOUR, TrendState.BULLISH),
        ],
    )

    assert result.bias is DirectionalBias.BULLISH
    assert result.alignment_score == 3
    assert result.present_timeframes == (
        Timeframe.WEEKLY,
        Timeframe.DAILY,
        Timeframe.FOUR_HOUR,
    )


def test_hierarchical_mode_requires_weekly_daily_and_4h_alignment() -> None:
    """Covers hierarchical mode, FR-504, FR-507, and TEST-001."""

    result = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.HIERARCHICAL).aggregate(
        [
            snapshot(Timeframe.WEEKLY, TrendState.BULLISH),
            snapshot(Timeframe.DAILY, TrendState.BULLISH),
            snapshot(Timeframe.FOUR_HOUR, TrendState.BULLISH),
        ],
    )

    assert result.bias is DirectionalBias.BULLISH
    assert result.alignment_score == 3
    assert result.reason == "hierarchical_bullish"


def test_hierarchical_mode_uses_weekly_as_hard_filter() -> None:
    """Covers hierarchical mode conflicting trends and TEST-001."""

    result = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.HIERARCHICAL).aggregate(
        [
            snapshot(Timeframe.WEEKLY, TrendState.BULLISH),
            snapshot(Timeframe.DAILY, TrendState.BEARISH),
            snapshot(Timeframe.FOUR_HOUR, TrendState.BULLISH),
        ],
    )

    assert result.bias is DirectionalBias.NEUTRAL
    assert result.alignment_score == 2
    assert result.reason == "weekly_bullish_filter"


def test_missing_timeframe_handling_is_neutral_and_lists_missing() -> None:
    """Covers missing timeframe handling and TEST-001."""

    result = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.VOTING).aggregate(
        [
            snapshot(Timeframe.WEEKLY, TrendState.BULLISH),
            snapshot(Timeframe.DAILY, TrendState.BULLISH),
        ],
    )

    assert result.bias is DirectionalBias.NEUTRAL
    assert result.alignment_score == 0
    assert result.missing_timeframes == (Timeframe.FOUR_HOUR,)
    assert result.reason == "missing_timeframes"


def test_aggregation_event_wraps_result() -> None:
    """Covers FR-508 and TEST-001."""

    result = MultiTimeframeTrendAggregator().aggregate(
        [
            snapshot(Timeframe.WEEKLY, TrendState.BEARISH),
            snapshot(Timeframe.DAILY, TrendState.BEARISH),
            snapshot(Timeframe.FOUR_HOUR, TrendState.BEARISH),
        ],
    )

    event = MultiTimeframeTrendAggregatedEvent(result=result)

    assert event.result.bias is DirectionalBias.BEARISH
    assert event.result.alignment_score == 3


def test_replay_consistency_for_same_snapshot_sequence() -> None:
    """Covers replay consistency and TEST-001."""

    snapshots = [
        snapshot(Timeframe.WEEKLY, TrendState.BULLISH, strength=3),
        snapshot(Timeframe.DAILY, TrendState.BEARISH, strength=2),
        snapshot(Timeframe.FOUR_HOUR, TrendState.BULLISH, strength=1),
    ]

    first = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.VOTING).aggregate(snapshots)
    second = MultiTimeframeTrendAggregator(mode=MultiTimeframeMode.VOTING).aggregate(snapshots)

    assert first == second
