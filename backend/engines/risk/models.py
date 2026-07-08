from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from backend.engines.entry import DecisionTrace
from backend.engines.entry.models import MetadataValue
from backend.engines.structure import BreakOfStructure, StructureSwing
from backend.models import Candle, Timeframe


class RiskDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class RiskAssessmentState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    VALID = "VALID"
    INVALID = "INVALID"
    INCOMPLETE = "INCOMPLETE"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskEvidenceCode(str, Enum):
    ENTRY_STATE_NOT_APPLICABLE = "entry_state_not_applicable"
    ENTRY_STATE_INVALIDATED = "entry_state_invalidated"
    ENTRY_PRICE_FROM_LATEST_CLOSE = "entry_price_from_latest_close"
    STOP_FROM_STRUCTURE_LEVEL = "stop_from_structure_level"
    TAKE_PROFIT_FROM_RR_TARGET = "take_profit_from_rr_target"
    MISSING_ENTRY_PRICE = "missing_entry_price"
    MISSING_INVALIDATION_LEVEL = "missing_invalidation_level"
    INVALID_STOP_PLACEMENT = "invalid_stop_placement"
    RISK_REWARD_CALCULATED = "risk_reward_calculated"


class RiskEvidenceCategory(str, Enum):
    ENTRY = "entry"
    CANDLE = "candle"
    STRUCTURE = "structure"
    TARGET = "target"
    VALIDATION = "validation"
    WARNING = "warning"


class RiskEvidenceSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


@dataclass(frozen=True, slots=True)
class RiskEvidence:
    """Machine-readable risk evidence for RISK-005."""

    code: RiskEvidenceCode
    category: RiskEvidenceCategory
    severity: RiskEvidenceSeverity
    description: str
    timeframe: Timeframe | None = None
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.description:
            raise ValueError("RiskEvidence description is required")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class RiskPlan:
    """Deterministic risk plan output for RISK-001 through RISK-006."""

    direction: RiskDirection
    state: RiskAssessmentState
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward_ratio: float | None
    invalidation_level: float | None
    risk_level: RiskLevel | None
    evidence: tuple[RiskEvidence, ...]
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("RiskPlan requires at least one evidence item")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(item.description for item in self.evidence)


@dataclass(frozen=True, slots=True)
class RiskInput:
    """Structured deterministic risk input for RISK-001 through RISK-004."""

    entry_trace: DecisionTrace
    latest_candle: Candle | None = None
    structure_levels: tuple[StructureSwing, ...] = ()
    bos_events: tuple[BreakOfStructure, ...] = ()
    minimum_risk_reward: float | None = 2.0
    target_mode: str | None = "rr"
