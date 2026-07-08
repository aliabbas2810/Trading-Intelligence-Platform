from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from backend.engines.entry import DecisionTrace
from backend.engines.entry.models import MetadataValue
from backend.engines.risk import RiskPlan
from backend.engines.trend import MultiTimeframeTrendResult
from backend.models import Timeframe


class ChecklistItemStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    WARNING = "WARNING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ChecklistCategory(str, Enum):
    TREND_ALIGNMENT = "TREND_ALIGNMENT"
    STRUCTURE_CONFIRMATION = "STRUCTURE_CONFIRMATION"
    ENTRY_CONFIRMATION = "ENTRY_CONFIRMATION"
    RISK_VALIDATION = "RISK_VALIDATION"
    INVALIDATION = "INVALIDATION"
    DATA_QUALITY = "DATA_QUALITY"


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """Evidence-driven checklist item for CHECKLIST-001 through CHECKLIST-004."""

    id: str
    category: ChecklistCategory
    status: ChecklistItemStatus
    label: str
    description: str
    timeframe: Timeframe | None
    evidence_codes: tuple[str, ...]
    severity: str
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ChecklistItem id is required")
        if not self.label:
            raise ValueError("ChecklistItem label is required")
        if not self.description:
            raise ValueError("ChecklistItem description is required")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ChecklistResult:
    """Deterministic checklist result for CHECKLIST-001 through CHECKLIST-006."""

    symbol: str
    overall_status: ChecklistItemStatus
    pass_count: int
    fail_count: int
    warning_count: int
    missing_count: int
    items: tuple[ChecklistItem, ...]
    summary: str
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("ChecklistResult symbol is required")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ChecklistInput:
    """Structured checklist input that consumes deterministic engine evidence only."""

    symbol: str
    entry_trace: DecisionTrace | None = None
    risk_plan: RiskPlan | None = None
    alignment: MultiTimeframeTrendResult | None = None
    runtime_metadata: Mapping[str, MetadataValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("ChecklistInput symbol is required")
        object.__setattr__(self, "runtime_metadata", MappingProxyType(dict(self.runtime_metadata)))
