from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from backend.engines.trend.models import TrendState, TrendStrength
from backend.models.domain import Timeframe


REQUIRED_TIMEFRAMES = (Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR)


class MultiTimeframeMode(str, Enum):
    VOTING = "voting"
    HIERARCHICAL = "hierarchical"


class DirectionalBias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class TimeframeTrendSnapshot:
    """Independent timeframe trend snapshot for FR-501, FR-502, and FR-503."""

    symbol: str
    timeframe: Timeframe
    state: TrendState
    strength: TrendStrength
    event_time_ms: int


@dataclass(frozen=True, slots=True)
class MultiTimeframeTrendResult:
    """Aggregated trend alignment result for FR-504 and FR-507."""

    symbol: str
    mode: MultiTimeframeMode
    bias: DirectionalBias
    alignment_score: int
    required_timeframes: tuple[Timeframe, ...]
    present_timeframes: tuple[Timeframe, ...]
    missing_timeframes: tuple[Timeframe, ...]
    snapshots: tuple[TimeframeTrendSnapshot, ...]
    reason: str


class MultiTimeframeTrendAggregator:
    """Aggregate independent trend states without recalculating structure."""

    def __init__(
        self,
        mode: MultiTimeframeMode = MultiTimeframeMode.VOTING,
        required_timeframes: tuple[Timeframe, ...] = REQUIRED_TIMEFRAMES,
    ) -> None:
        self._mode = mode
        self._required_timeframes = required_timeframes

    def aggregate(self, snapshots: Iterable[TimeframeTrendSnapshot]) -> MultiTimeframeTrendResult:
        """Aggregate Weekly, Daily, and 4H trend snapshots for FR-501 through FR-508."""

        snapshot_by_timeframe = self._deduplicate_snapshots(snapshots)
        ordered_snapshots = tuple(
            snapshot_by_timeframe[timeframe]
            for timeframe in self._required_timeframes
            if timeframe in snapshot_by_timeframe
        )
        symbol = self._resolve_symbol(ordered_snapshots)
        missing_timeframes = tuple(
            timeframe for timeframe in self._required_timeframes if timeframe not in snapshot_by_timeframe
        )
        present_timeframes = tuple(snapshot.timeframe for snapshot in ordered_snapshots)

        if missing_timeframes:
            return MultiTimeframeTrendResult(
                symbol=symbol,
                mode=self._mode,
                bias=DirectionalBias.NEUTRAL,
                alignment_score=0,
                required_timeframes=self._required_timeframes,
                present_timeframes=present_timeframes,
                missing_timeframes=missing_timeframes,
                snapshots=ordered_snapshots,
                reason="missing_timeframes",
            )

        if self._mode is MultiTimeframeMode.VOTING:
            bias, score, reason = self._aggregate_voting(ordered_snapshots)
        else:
            bias, score, reason = self._aggregate_hierarchical(ordered_snapshots)

        return MultiTimeframeTrendResult(
            symbol=symbol,
            mode=self._mode,
            bias=bias,
            alignment_score=score,
            required_timeframes=self._required_timeframes,
            present_timeframes=present_timeframes,
            missing_timeframes=(),
            snapshots=ordered_snapshots,
            reason=reason,
        )

    def _deduplicate_snapshots(
        self,
        snapshots: Iterable[TimeframeTrendSnapshot],
    ) -> dict[Timeframe, TimeframeTrendSnapshot]:
        snapshot_by_timeframe: dict[Timeframe, TimeframeTrendSnapshot] = {}
        symbol: str | None = None
        for snapshot in snapshots:
            if snapshot.timeframe not in self._required_timeframes:
                continue
            if symbol is None:
                symbol = snapshot.symbol
            elif snapshot.symbol != symbol:
                raise ValueError("Cannot aggregate trend snapshots for multiple symbols")
            snapshot_by_timeframe[snapshot.timeframe] = snapshot
        return snapshot_by_timeframe

    def _resolve_symbol(self, snapshots: tuple[TimeframeTrendSnapshot, ...]) -> str:
        if not snapshots:
            return ""
        return snapshots[0].symbol

    def _aggregate_voting(
        self,
        snapshots: tuple[TimeframeTrendSnapshot, ...],
    ) -> tuple[DirectionalBias, int, str]:
        bullish_count = count_state(snapshots, TrendState.BULLISH)
        bearish_count = count_state(snapshots, TrendState.BEARISH)

        if bullish_count >= 2:
            return DirectionalBias.BULLISH, bullish_count, "voting_bullish"
        if bearish_count >= 2:
            return DirectionalBias.BEARISH, bearish_count, "voting_bearish"
        return DirectionalBias.NEUTRAL, max(bullish_count, bearish_count), "voting_no_majority"

    def _aggregate_hierarchical(
        self,
        snapshots: tuple[TimeframeTrendSnapshot, ...],
    ) -> tuple[DirectionalBias, int, str]:
        snapshot_by_timeframe = {snapshot.timeframe: snapshot for snapshot in snapshots}
        weekly = snapshot_by_timeframe[Timeframe.WEEKLY]
        daily = snapshot_by_timeframe[Timeframe.DAILY]
        four_hour = snapshot_by_timeframe[Timeframe.FOUR_HOUR]

        if weekly.state is TrendState.BULLISH:
            if daily.state is TrendState.BULLISH and four_hour.state is TrendState.BULLISH:
                return DirectionalBias.BULLISH, 3, "hierarchical_bullish"
            return DirectionalBias.NEUTRAL, count_state(snapshots, TrendState.BULLISH), "weekly_bullish_filter"

        if weekly.state is TrendState.BEARISH:
            if daily.state is TrendState.BEARISH and four_hour.state is TrendState.BEARISH:
                return DirectionalBias.BEARISH, 3, "hierarchical_bearish"
            return DirectionalBias.NEUTRAL, count_state(snapshots, TrendState.BEARISH), "weekly_bearish_filter"

        return DirectionalBias.NEUTRAL, 0, "weekly_transition_filter"


def count_state(snapshots: tuple[TimeframeTrendSnapshot, ...], state: TrendState) -> int:
    return sum(1 for snapshot in snapshots if snapshot.state is state)
