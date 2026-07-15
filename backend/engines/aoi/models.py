from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite

from backend.engines.structure import StructureLabel, StructureSwing
from backend.engines.trend import TrendState
from backend.models import Candle, Timeframe


class AoiTimeframe(str, Enum):
    DAILY = "1d"
    WEEKLY = "1w"

    def to_timeframe(self) -> Timeframe:
        return Timeframe(self.value)

    @classmethod
    def from_timeframe(cls, timeframe: Timeframe) -> AoiTimeframe:
        return cls(timeframe.value)


class AoiDirection(str, Enum):
    SUPPORT = "support"
    RESISTANCE = "resistance"


class AoiState(str, Enum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    BROKEN = "broken"
    RETEST_PENDING = "retest_pending"
    STRUCTURALLY_INVALIDATED = "structurally_invalidated"
    ARCHIVED = "archived"


class AoiSizingMode(str, Enum):
    FIXED_TICKS = "fixed_ticks"
    PERCENTAGE = "percentage"
    ATR_NORMALIZED = "atr_normalized"
    HYBRID = "hybrid"


class AoiLocationState(str, Enum):
    OUTSIDE = "outside"
    APPROACHING = "approaching"
    INSIDE = "inside"
    REACTING = "reacting"
    ENTRY_WINDOW = "entry_window"
    MOVED_AWAY = "moved_away"


@dataclass(frozen=True, slots=True)
class AoiBounds:
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if not isfinite(self.lower) or not isfinite(self.upper):
            raise ValueError("AOI bounds must be finite")
        if self.lower <= 0 or self.upper <= self.lower:
            raise ValueError("AOI bounds require 0 < lower < upper")

    @property
    def width(self) -> float:
        return self.upper - self.lower

    def overlaps(self, low: float, high: float) -> bool:
        return high >= self.lower and low <= self.upper

    def intersection(self, other: AoiBounds) -> AoiBounds | None:
        lower = max(self.lower, other.lower)
        upper = min(self.upper, other.upper)
        return AoiBounds(lower=lower, upper=upper) if upper > lower else None


@dataclass(frozen=True, slots=True)
class AoiSizingConfig:
    """Explicit, instrument-aware sizing inputs; no crypto pip values are implied."""

    mode: AoiSizingMode
    minimum_ticks: float | None = None
    maximum_ticks: float | None = None
    minimum_percentage: float | None = None
    maximum_percentage: float | None = None
    minimum_atr_multiple: float | None = None
    maximum_atr_multiple: float | None = None

    def resolve(
        self,
        *,
        reference_price: float,
        tick_size: float | None = None,
        atr: float | None = None,
    ) -> tuple[float, float]:
        tick_range = self._tick_range(tick_size)
        percentage_range = self._percentage_range(reference_price)
        atr_range = self._atr_range(atr)
        if self.mode is AoiSizingMode.FIXED_TICKS:
            return self._required(tick_range, "tick_size and tick limits")
        if self.mode is AoiSizingMode.PERCENTAGE:
            return self._required(percentage_range, "percentage limits")
        if self.mode is AoiSizingMode.ATR_NORMALIZED:
            return self._required(atr_range, "ATR and ATR limits")
        ranges = tuple(item for item in (tick_range, percentage_range, atr_range) if item)
        if not ranges:
            raise ValueError("HYBRID sizing requires at least one complete sizing input")
        minimum = max(item[0] for item in ranges)
        maximum = min(item[1] for item in ranges)
        if maximum < minimum:
            raise ValueError("HYBRID sizing inputs have no common valid width")
        return minimum, maximum

    def _tick_range(self, tick_size: float | None) -> tuple[float, float] | None:
        if tick_size is None or self.minimum_ticks is None or self.maximum_ticks is None:
            return None
        return tick_size * self.minimum_ticks, tick_size * self.maximum_ticks

    def _percentage_range(self, price: float) -> tuple[float, float] | None:
        if self.minimum_percentage is None or self.maximum_percentage is None:
            return None
        return price * self.minimum_percentage, price * self.maximum_percentage

    def _atr_range(self, atr: float | None) -> tuple[float, float] | None:
        if atr is None or self.minimum_atr_multiple is None or self.maximum_atr_multiple is None:
            return None
        return atr * self.minimum_atr_multiple, atr * self.maximum_atr_multiple

    def _required(
        self,
        value: tuple[float, float] | None,
        description: str,
    ) -> tuple[float, float]:
        if value is None:
            raise ValueError(f"AOI sizing requires {description}")
        if value[0] <= 0 or value[1] < value[0]:
            raise ValueError("AOI sizing limits must be positive and ordered")
        return value


@dataclass(frozen=True, slots=True)
class AoiRankingWeights:
    body_close: float = 4.0
    body_touch: float = 2.0
    reaction: float = 2.0
    recency: float = 1.0
    width_penalty: float = 1.0


@dataclass(frozen=True, slots=True)
class ActiveStructureLeg:
    symbol: str
    timeframe: AoiTimeframe
    trend_state: TrendState
    start_swing: StructureSwing
    end_swing: StructureSwing
    leg_id: str
    trend_id: str

    def __post_init__(self) -> None:
        expected = (
            (StructureLabel.HL, StructureLabel.HH)
            if self.trend_state is TrendState.BULLISH
            else (StructureLabel.LH, StructureLabel.LL)
        )
        if self.trend_state not in {TrendState.BULLISH, TrendState.BEARISH}:
            raise ValueError("AOI active legs require a bullish or bearish trend")
        if (self.start_swing.label, self.end_swing.label) != expected:
            raise ValueError(f"Active leg requires {expected[0].value}->{expected[1].value}")
        timeframe = self.timeframe.to_timeframe()
        if any(
            swing.symbol != self.symbol or swing.timeframe is not timeframe
            for swing in (self.start_swing, self.end_swing)
        ):
            raise ValueError("Active leg swings must match its symbol and timeframe")

    @property
    def direction(self) -> AoiDirection:
        return (
            AoiDirection.SUPPORT
            if self.trend_state is TrendState.BULLISH
            else AoiDirection.RESISTANCE
        )

    @property
    def price_bounds(self) -> AoiBounds:
        return AoiBounds(
            lower=min(self.start_swing.level, self.end_swing.level),
            upper=max(self.start_swing.level, self.end_swing.level),
        )

    @property
    def start_time_ms(self) -> int:
        return min(self.start_swing.candle_open_time_ms, self.end_swing.candle_open_time_ms)

    @property
    def end_time_ms(self) -> int:
        return max(self.start_swing.candle_close_time_ms, self.end_swing.candle_close_time_ms)


@dataclass(frozen=True, slots=True)
class AoiTouch:
    candle_open_time_ms: int
    candle_close_time_ms: int
    body_low: float
    body_high: float
    close: float
    close_inside: bool


@dataclass(frozen=True, slots=True)
class AoiRankingMetadata:
    score: float
    body_close_count: int
    body_touch_count: int
    reaction_count: int
    recency_time_ms: int
    normalized_width: float


@dataclass(frozen=True, slots=True)
class AoiCandidate:
    candidate_id: str
    symbol: str
    timeframe: AoiTimeframe
    direction: AoiDirection
    bounds: AoiBounds
    state: AoiState
    origin_structure_leg_id: str
    origin_trend_id: str
    origin_timeframe: AoiTimeframe
    touches: tuple[AoiTouch, ...]
    first_touch_time_ms: int
    confirmation_time_ms: int | None
    ranking: AoiRankingMetadata

    @property
    def touch_count(self) -> int:
        return len(self.touches)

    @property
    def contributing_candle_timestamps(self) -> tuple[int, ...]:
        return tuple(touch.candle_open_time_ms for touch in self.touches)

    @property
    def is_tradable(self) -> bool:
        return self.confirmation_time_ms is not None and self.state in {
            AoiState.CONFIRMED,
            AoiState.ACTIVE,
        }


@dataclass(frozen=True, slots=True)
class AreaOfInterest:
    aoi_id: str
    symbol: str
    timeframe: AoiTimeframe
    direction: AoiDirection
    bounds: AoiBounds
    state: AoiState
    origin_structure_leg_id: str
    origin_trend_id: str
    origin_timeframe: AoiTimeframe
    contributing_candle_timestamps: tuple[int, ...]
    first_touch_time_ms: int
    confirmation_time_ms: int
    touch_count: int
    close_count: int
    reaction_count: int
    ranking: AoiRankingMetadata
    state_changed_time_ms: int

    @property
    def width(self) -> float:
        return self.bounds.width


@dataclass(frozen=True, slots=True)
class AoiOverlap:
    weekly_aoi_id: str
    daily_aoi_id: str
    intersection_bounds: AoiBounds
    overlap_ratio: float
    is_full_intersection: bool
    confluence_weight: float


@dataclass(frozen=True, slots=True)
class AoiLocationConfig:
    proximity_tolerance: float
    maximum_post_reaction_excursion: float

    def __post_init__(self) -> None:
        if self.proximity_tolerance < 0 or self.maximum_post_reaction_excursion < 0:
            raise ValueError("AOI location distances must be non-negative")


@dataclass(frozen=True, slots=True)
class AoiLocationResult:
    aoi_id: str
    state: AoiLocationState
    distance: float
    current_touch: bool
    gate_open: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AoiEvaluation:
    leg: ActiveStructureLeg
    candidates: tuple[AoiCandidate, ...] = field(default_factory=tuple)
    areas: tuple[AreaOfInterest, ...] = field(default_factory=tuple)


def candle_body_overlaps(candle: Candle, bounds: AoiBounds) -> bool:
    return bounds.overlaps(candle.body_low, candle.body_high)
