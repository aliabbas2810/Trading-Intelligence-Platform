from __future__ import annotations

from pydantic import BaseModel, Field

from backend.engines.checklist import (
    ChecklistCategory,
    ChecklistItem,
    ChecklistItemStatus,
    ChecklistResult,
)
from backend.engines.entry.models import MetadataValue
from backend.models import Timeframe


class ChecklistEvaluateRequest(BaseModel):
    """Checklist evaluation request for CHECKLIST-001 through CHECKLIST-006."""

    symbol: str
    minimum_risk_reward: float | None = Field(default=2.0, gt=0)


class ChecklistItemResponse(BaseModel):
    """Checklist item transport payload for CHECKLIST-001."""

    id: str
    category: ChecklistCategory
    status: ChecklistItemStatus
    label: str
    description: str
    timeframe: Timeframe | None
    evidence_codes: tuple[str, ...]
    severity: str
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_item(cls, item: ChecklistItem) -> ChecklistItemResponse:
        return cls(
            id=item.id,
            category=item.category,
            status=item.status,
            label=item.label,
            description=item.description,
            timeframe=item.timeframe,
            evidence_codes=item.evidence_codes,
            severity=item.severity,
            metadata=dict(item.metadata),
        )


class ChecklistResultResponse(BaseModel):
    """ChecklistResult transport response for CHECKLIST-001 through CHECKLIST-006."""

    symbol: str
    overall_status: ChecklistItemStatus
    pass_count: int
    fail_count: int
    warning_count: int
    missing_count: int
    items: tuple[ChecklistItemResponse, ...]
    summary: str
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_result(cls, result: ChecklistResult) -> ChecklistResultResponse:
        return cls(
            symbol=result.symbol,
            overall_status=result.overall_status,
            pass_count=result.pass_count,
            fail_count=result.fail_count,
            warning_count=result.warning_count,
            missing_count=result.missing_count,
            items=tuple(ChecklistItemResponse.from_item(item) for item in result.items),
            summary=result.summary,
            metadata=dict(result.metadata),
        )
