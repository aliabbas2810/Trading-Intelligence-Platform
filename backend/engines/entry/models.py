from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from backend.api import StructureSnapshot
from backend.engines.aoi import AoiGateResult
from backend.engines.structure import BreakOfStructure
from backend.engines.trend import MultiTimeframeTrendResult, TrendUpdate
from backend.models import Candle, Timeframe


class EntryState(str, Enum):
    WAIT = "WAIT"
    WATCH = "WATCH"
    LONG_SETUP = "LONG_SETUP"
    SHORT_SETUP = "SHORT_SETUP"
    ENTRY_READY = "ENTRY_READY"
    INVALIDATED = "INVALIDATED"


class EntryDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class DecisionEvidenceCode(str, Enum):
    ALIGNMENT_DATA_MISSING = "alignment_data_missing"
    ALIGNMENT_WEAK_OR_NEUTRAL = "alignment_weak_or_neutral"
    HIGHER_TIMEFRAMES_ALIGNED = "higher_timeframes_aligned"
    HIGHER_TIMEFRAME_CONFLICT = "higher_timeframe_conflict"
    WAITING_FOR_LOWER_TIMEFRAME_DATA = "waiting_for_lower_timeframe_data"
    WAITING_FOR_15M_5M_STRUCTURE = "waiting_for_15m_5m_structure"
    FIFTEEN_MINUTE_STRUCTURE_CONFIRMATION = "15m_structure_confirmation"
    FIVE_MINUTE_STRUCTURE_CONFIRMATION = "5m_structure_confirmation"
    SETUP_CONFIRMED = "setup_confirmed"
    ONE_MINUTE_ENTRY_CONFIRMATION = "one_minute_trigger"
    MISSING_CONFIRMATION = "missing_confirmation"
    OPPOSING_BOS_INVALIDATION = "opposing_bos_invalidation"
    WEEKLY_AOI_ACTIVE = "weekly_aoi_active"
    DAILY_AOI_ACTIVE = "daily_aoi_active"
    WEEKLY_DAILY_AOI_OVERLAP = "weekly_daily_aoi_overlap"
    AOI_LOCATION_INSIDE = "aoi_location_inside"
    AOI_LOCATION_REACTING = "aoi_location_reacting"
    AOI_LOCATION_ENTRY_WINDOW = "aoi_location_entry_window"
    AOI_LOCATION_NOT_ELIGIBLE = "aoi_location_not_eligible"
    AOI_MOVED_AWAY = "aoi_moved_away"
    AOI_DATA_MISSING = "aoi_data_missing"
    NO_ACTIVE_AOI = "no_active_aoi"


class DecisionEvidenceCategory(str, Enum):
    ALIGNMENT = "alignment"
    TREND = "trend"
    STRUCTURE = "structure"
    BOS = "bos"
    CANDLE = "candle"
    MISSING_CONFIRMATION = "missing_confirmation"
    INVALIDATION = "invalidation"
    AOI = "aoi"


class DecisionEvidenceSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class DecisionEvidencePolarity(str, Enum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    NEUTRAL = "neutral"
    MISSING = "missing"


MetadataValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """Machine-readable entry evidence for ENTRY-005 and future engines."""

    code: DecisionEvidenceCode
    category: DecisionEvidenceCategory
    timeframe: Timeframe | None
    polarity: DecisionEvidencePolarity
    severity: DecisionEvidenceSeverity
    description: str
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.description:
            raise ValueError("DecisionEvidence description is required")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """Deterministic entry decision output for ENTRY-001 and ENTRY-005."""

    state: EntryState
    direction: EntryDirection
    confidence: float
    evidence: tuple[DecisionEvidence, ...]
    trigger_timeframe: Timeframe | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("DecisionTrace confidence must be between 0.0 and 1.0")
        if not self.evidence:
            raise ValueError("DecisionTrace requires at least one evidence item")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(item.description for item in self.evidence if item.category is not DecisionEvidenceCategory.MISSING_CONFIRMATION)

    @property
    def missing_confirmations(self) -> tuple[str, ...]:
        return tuple(
            str(item.metadata["missing_key"])
            for item in self.evidence
            if item.category is DecisionEvidenceCategory.MISSING_CONFIRMATION
            and isinstance(item.metadata.get("missing_key"), str)
        )

    @property
    def invalidation_conditions(self) -> tuple[str, ...]:
        return tuple(
            str(item.metadata["condition"])
            for item in self.evidence
            if item.category is DecisionEvidenceCategory.INVALIDATION
            and isinstance(item.metadata.get("condition"), str)
        )


@dataclass(frozen=True, slots=True)
class EntrySignalInput:
    """Structured deterministic entry input for ENTRY-002 through ENTRY-004."""

    symbol: str
    trend_1w: TrendUpdate | None = None
    trend_1d: TrendUpdate | None = None
    trend_4h: TrendUpdate | None = None
    trend_2h: TrendUpdate | None = None
    trend_1h: TrendUpdate | None = None
    trend_30m: TrendUpdate | None = None
    structure_15m: StructureSnapshot | None = None
    structure_5m: StructureSnapshot | None = None
    structure_1m: StructureSnapshot | None = None
    bos_events: tuple[BreakOfStructure, ...] = ()
    latest_candle: Candle | None = None
    alignment: MultiTimeframeTrendResult | None = None
    aoi_gate: AoiGateResult | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("EntrySignalInput symbol is required")

    @property
    def trend_by_timeframe(self) -> Mapping[Timeframe, TrendUpdate | None]:
        return {
            Timeframe.WEEKLY: self.trend_1w,
            Timeframe.DAILY: self.trend_1d,
            Timeframe.FOUR_HOUR: self.trend_4h,
            Timeframe.TWO_HOUR: self.trend_2h,
            Timeframe.ONE_HOUR: self.trend_1h,
            Timeframe.THIRTY_MINUTE: self.trend_30m,
        }

    @property
    def structure_by_timeframe(self) -> Mapping[Timeframe, StructureSnapshot | None]:
        return {
            Timeframe.FIFTEEN_MINUTE: self.structure_15m,
            Timeframe.FIVE_MINUTE: self.structure_5m,
            Timeframe.ONE_MINUTE: self.structure_1m,
        }
