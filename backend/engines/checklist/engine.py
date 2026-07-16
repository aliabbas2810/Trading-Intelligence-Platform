from __future__ import annotations

from backend.engines.checklist.models import (
    ChecklistCategory,
    ChecklistInput,
    ChecklistItem,
    ChecklistItemStatus,
    ChecklistResult,
)
from backend.engines.entry import (
    DecisionEvidence,
    DecisionEvidenceCategory,
    DecisionEvidenceCode,
    DecisionEvidencePolarity,
    DecisionEvidenceSeverity,
)
from backend.engines.risk import (
    RiskAssessmentState,
    RiskEvidence,
    RiskEvidenceSeverity,
)
from backend.engines.trend import DirectionalBias
from backend.models import Timeframe


class ChecklistEngine:
    """Convert deterministic entry/risk evidence into a checklist without recalculation."""

    def evaluate(self, checklist_input: ChecklistInput) -> ChecklistResult:
        """Build an evidence-driven checklist for CHECKLIST-001 through CHECKLIST-006."""

        items = (
            *self._alignment_items(checklist_input),
            *self._entry_items(checklist_input),
            *self._aoi_items(checklist_input),
            *self._risk_items(checklist_input),
            *self._data_quality_items(checklist_input),
        )
        pass_count = sum(item.status is ChecklistItemStatus.PASS for item in items)
        fail_count = sum(item.status is ChecklistItemStatus.FAIL for item in items)
        warning_count = sum(item.status is ChecklistItemStatus.WARNING for item in items)
        missing_count = sum(item.status is ChecklistItemStatus.MISSING for item in items)
        overall_status = self._overall_status(items)
        return ChecklistResult(
            symbol=checklist_input.symbol,
            overall_status=overall_status,
            pass_count=pass_count,
            fail_count=fail_count,
            warning_count=warning_count,
            missing_count=missing_count,
            items=items,
            summary=self._summary(overall_status, pass_count, fail_count, warning_count, missing_count),
            metadata={
                "entry_state": (
                    checklist_input.entry_trace.state.value
                    if checklist_input.entry_trace is not None
                    else None
                ),
                "risk_state": (
                    checklist_input.risk_plan.state.value
                    if checklist_input.risk_plan is not None
                    else None
                ),
                "alignment_score": (
                    checklist_input.alignment.alignment_score
                    if checklist_input.alignment is not None
                    else None
                ),
                **dict(checklist_input.runtime_metadata),
            },
        )

    def _alignment_items(self, checklist_input: ChecklistInput) -> tuple[ChecklistItem, ...]:
        alignment = checklist_input.alignment
        if alignment is None:
            return (
                self._item(
                    item_id="alignment.missing",
                    category=ChecklistCategory.TREND_ALIGNMENT,
                    status=ChecklistItemStatus.MISSING,
                    label="Trend alignment unavailable",
                    description="multi_timeframe_alignment_missing",
                    evidence_codes=(),
                    severity="warning",
                ),
            )

        status = (
            ChecklistItemStatus.PASS
            if alignment.alignment_score >= 2 and alignment.bias is not DirectionalBias.NEUTRAL
            else ChecklistItemStatus.WARNING
        )
        return (
            self._item(
                item_id="alignment.snapshot",
                category=ChecklistCategory.TREND_ALIGNMENT,
                status=status,
                label="Trend alignment",
                description=alignment.reason,
                evidence_codes=(),
                severity="info" if status is ChecklistItemStatus.PASS else "warning",
                metadata={
                    "bias": alignment.bias.value,
                    "alignment_score": alignment.alignment_score,
                    "present_timeframes": len(alignment.present_timeframes),
                    "missing_timeframes": len(alignment.missing_timeframes),
                },
            ),
        )

    def _entry_items(self, checklist_input: ChecklistInput) -> tuple[ChecklistItem, ...]:
        trace = checklist_input.entry_trace
        if trace is None:
            return (
                self._item(
                    item_id="entry.missing",
                    category=ChecklistCategory.DATA_QUALITY,
                    status=ChecklistItemStatus.MISSING,
                    label="Entry trace unavailable",
                    description="entry_trace_missing",
                    evidence_codes=(),
                    severity="blocking",
                ),
            )

        return tuple(self._entry_item(index, evidence) for index, evidence in enumerate(trace.evidence, start=1))

    def _entry_item(self, index: int, evidence: DecisionEvidence) -> ChecklistItem:
        return self._item(
            item_id=f"entry.{index}.{evidence.code.value}",
            category=self._entry_category(evidence),
            status=self._entry_status(evidence),
            label=evidence.description,
            description=evidence.description,
            timeframe=evidence.timeframe,
            evidence_codes=(evidence.code.value,),
            severity=evidence.severity.value,
            metadata={
                "polarity": evidence.polarity.value,
                "entry_category": evidence.category.value,
                **dict(evidence.metadata),
            },
        )

    def _aoi_items(self, checklist_input: ChecklistInput) -> tuple[ChecklistItem, ...]:
        trace = checklist_input.entry_trace
        if trace is None:
            return (
                self._aoi_item(
                    item_id="aoi.location_gate",
                    status=ChecklistItemStatus.MISSING,
                    label="AOI location gate",
                    description="entry_trace_missing",
                    evidence_codes=(),
                    severity="blocking",
                ),
            )

        codes = {evidence.code for evidence in trace.evidence if evidence.category is DecisionEvidenceCategory.AOI}
        missing = DecisionEvidenceCode.AOI_DATA_MISSING in codes
        location_failed = bool(
            codes.intersection(
                {
                    DecisionEvidenceCode.AOI_LOCATION_NOT_ELIGIBLE,
                    DecisionEvidenceCode.AOI_MOVED_AWAY,
                },
            ),
        )
        location_passed = bool(
            codes.intersection(
                {
                    DecisionEvidenceCode.AOI_LOCATION_INSIDE,
                    DecisionEvidenceCode.AOI_LOCATION_REACTING,
                    DecisionEvidenceCode.AOI_LOCATION_ENTRY_WINDOW,
                },
            ),
        )
        return (
            self._aoi_presence_item(
                item_id="aoi.weekly",
                label="Weekly AOI",
                timeframe=Timeframe.WEEKLY,
                active_code=DecisionEvidenceCode.WEEKLY_AOI_ACTIVE,
                codes=codes,
                missing=missing,
            ),
            self._aoi_presence_item(
                item_id="aoi.daily",
                label="Daily AOI",
                timeframe=Timeframe.DAILY,
                active_code=DecisionEvidenceCode.DAILY_AOI_ACTIVE,
                codes=codes,
                missing=missing,
            ),
            self._aoi_item(
                item_id="aoi.weekly_daily_overlap",
                status=(
                    ChecklistItemStatus.PASS
                    if DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP in codes
                    else ChecklistItemStatus.MISSING
                    if missing
                    else ChecklistItemStatus.WARNING
                ),
                label="Weekly/Daily AOI confluence",
                description=(
                    "weekly_daily_aoi_overlap"
                    if DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP in codes
                    else "weekly_daily_aoi_overlap_missing"
                ),
                evidence_codes=(
                    (DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP.value,)
                    if DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP in codes
                    else ()
                ),
                severity=(
                    "info"
                    if DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP in codes
                    else "warning"
                ),
            ),
            self._aoi_item(
                item_id="aoi.location_gate",
                status=(
                    ChecklistItemStatus.PASS
                    if location_passed
                    else ChecklistItemStatus.MISSING
                    if missing
                    else ChecklistItemStatus.FAIL
                    if location_failed
                    else ChecklistItemStatus.WARNING
                ),
                label="AOI location gate",
                description=(
                    "aoi_location_gate_open"
                    if location_passed
                    else "aoi_data_missing"
                    if missing
                    else "aoi_location_not_eligible"
                    if location_failed
                    else "aoi_location_gate_unconfirmed"
                ),
                evidence_codes=tuple(
                    code.value
                    for code in (
                        DecisionEvidenceCode.AOI_LOCATION_INSIDE,
                        DecisionEvidenceCode.AOI_LOCATION_REACTING,
                        DecisionEvidenceCode.AOI_LOCATION_ENTRY_WINDOW,
                        DecisionEvidenceCode.AOI_LOCATION_NOT_ELIGIBLE,
                        DecisionEvidenceCode.AOI_MOVED_AWAY,
                        DecisionEvidenceCode.AOI_DATA_MISSING,
                    )
                    if code in codes
                ),
                severity="info" if location_passed else "blocking" if location_failed or missing else "warning",
            ),
        )

    def _aoi_presence_item(
        self,
        *,
        item_id: str,
        label: str,
        timeframe: Timeframe,
        active_code: DecisionEvidenceCode,
        codes: set[DecisionEvidenceCode],
        missing: bool,
    ) -> ChecklistItem:
        active = active_code in codes
        return self._aoi_item(
            item_id=item_id,
            status=ChecklistItemStatus.PASS if active else ChecklistItemStatus.MISSING if missing else ChecklistItemStatus.WARNING,
            label=label,
            description=active_code.value if active else f"{active_code.value}_missing",
            evidence_codes=(active_code.value,) if active else (),
            severity="info" if active else "warning",
            timeframe=timeframe,
        )

    def _risk_items(self, checklist_input: ChecklistInput) -> tuple[ChecklistItem, ...]:
        plan = checklist_input.risk_plan
        if plan is None:
            return (
                self._item(
                    item_id="risk.missing",
                    category=ChecklistCategory.DATA_QUALITY,
                    status=ChecklistItemStatus.MISSING,
                    label="Risk plan unavailable",
                    description="risk_plan_missing",
                    evidence_codes=(),
                    severity="blocking",
                ),
            )

        state_item = self._item(
            item_id="risk.state",
            category=ChecklistCategory.RISK_VALIDATION,
            status=self._risk_state_status(plan.state),
            label="Risk assessment state",
            description=f"risk_state_{plan.state.value.lower()}",
            evidence_codes=(),
            severity=self._risk_state_severity(plan.state),
            metadata={
                "direction": plan.direction.value,
                "risk_reward_ratio": plan.risk_reward_ratio,
                "risk_level": plan.risk_level.value if plan.risk_level is not None else None,
            },
        )
        evidence_items = tuple(self._risk_evidence_item(index, evidence) for index, evidence in enumerate(plan.evidence, start=1))
        warning_items = tuple(
            self._item(
                item_id=f"risk.warning.{index}",
                category=ChecklistCategory.RISK_VALIDATION,
                status=ChecklistItemStatus.WARNING,
                label=warning,
                description=warning,
                evidence_codes=(),
                severity="warning",
            )
            for index, warning in enumerate(plan.warnings, start=1)
        )
        return (state_item, *evidence_items, *warning_items)

    def _risk_evidence_item(self, index: int, evidence: RiskEvidence) -> ChecklistItem:
        return self._item(
            item_id=f"risk.{index}.{evidence.code.value}",
            category=ChecklistCategory.RISK_VALIDATION,
            status=self._risk_evidence_status(evidence),
            label=evidence.description,
            description=evidence.description,
            timeframe=evidence.timeframe,
            evidence_codes=(evidence.code.value,),
            severity=evidence.severity.value,
            metadata={
                "risk_category": evidence.category.value,
                **dict(evidence.metadata),
            },
        )

    def _data_quality_items(self, checklist_input: ChecklistInput) -> tuple[ChecklistItem, ...]:
        if not checklist_input.runtime_metadata:
            return ()
        return (
            self._item(
                item_id="runtime.metadata",
                category=ChecklistCategory.DATA_QUALITY,
                status=ChecklistItemStatus.PASS,
                label="Runtime metadata available",
                description="runtime_metadata_available",
                evidence_codes=(),
                severity="info",
                metadata=dict(checklist_input.runtime_metadata),
            ),
        )

    def _entry_category(self, evidence: DecisionEvidence) -> ChecklistCategory:
        if evidence.category is DecisionEvidenceCategory.ALIGNMENT or evidence.category is DecisionEvidenceCategory.TREND:
            return ChecklistCategory.TREND_ALIGNMENT
        if evidence.category is DecisionEvidenceCategory.STRUCTURE or evidence.category is DecisionEvidenceCategory.BOS:
            return ChecklistCategory.STRUCTURE_CONFIRMATION
        if evidence.category is DecisionEvidenceCategory.CANDLE:
            return ChecklistCategory.ENTRY_CONFIRMATION
        if evidence.category is DecisionEvidenceCategory.AOI:
            return ChecklistCategory.AOI_LOCATION
        if evidence.category is DecisionEvidenceCategory.INVALIDATION:
            return ChecklistCategory.INVALIDATION
        if evidence.category is DecisionEvidenceCategory.MISSING_CONFIRMATION:
            return ChecklistCategory.ENTRY_CONFIRMATION
        return ChecklistCategory.DATA_QUALITY

    def _entry_status(self, evidence: DecisionEvidence) -> ChecklistItemStatus:
        if evidence.category is DecisionEvidenceCategory.MISSING_CONFIRMATION:
            return ChecklistItemStatus.MISSING
        if evidence.category is DecisionEvidenceCategory.INVALIDATION:
            return ChecklistItemStatus.FAIL if evidence.severity is DecisionEvidenceSeverity.BLOCKING else ChecklistItemStatus.WARNING
        if evidence.polarity is DecisionEvidencePolarity.OPPOSES:
            return ChecklistItemStatus.FAIL
        if evidence.polarity is DecisionEvidencePolarity.MISSING:
            return ChecklistItemStatus.MISSING
        if evidence.severity is DecisionEvidenceSeverity.WARNING:
            return ChecklistItemStatus.WARNING
        if evidence.severity is DecisionEvidenceSeverity.BLOCKING:
            return ChecklistItemStatus.FAIL
        return ChecklistItemStatus.PASS

    def _risk_state_status(self, state: RiskAssessmentState) -> ChecklistItemStatus:
        if state is RiskAssessmentState.VALID:
            return ChecklistItemStatus.PASS
        if state is RiskAssessmentState.INVALID:
            return ChecklistItemStatus.FAIL
        if state is RiskAssessmentState.INCOMPLETE:
            return ChecklistItemStatus.MISSING
        return ChecklistItemStatus.NOT_APPLICABLE

    def _risk_state_severity(self, state: RiskAssessmentState) -> str:
        if state is RiskAssessmentState.INVALID:
            return "blocking"
        if state is RiskAssessmentState.INCOMPLETE:
            return "warning"
        return "info"

    def _risk_evidence_status(self, evidence: RiskEvidence) -> ChecklistItemStatus:
        if evidence.severity is RiskEvidenceSeverity.BLOCKING:
            return ChecklistItemStatus.FAIL
        if evidence.severity is RiskEvidenceSeverity.WARNING:
            return ChecklistItemStatus.WARNING
        return ChecklistItemStatus.PASS

    def _overall_status(self, items: tuple[ChecklistItem, ...]) -> ChecklistItemStatus:
        if any(item.status is ChecklistItemStatus.FAIL for item in items):
            return ChecklistItemStatus.FAIL
        if any(item.status is ChecklistItemStatus.MISSING for item in items):
            return ChecklistItemStatus.MISSING
        if any(item.status is ChecklistItemStatus.WARNING for item in items):
            return ChecklistItemStatus.WARNING
        if any(item.status is ChecklistItemStatus.PASS for item in items):
            return ChecklistItemStatus.PASS
        return ChecklistItemStatus.NOT_APPLICABLE

    def _summary(
        self,
        overall_status: ChecklistItemStatus,
        pass_count: int,
        fail_count: int,
        warning_count: int,
        missing_count: int,
    ) -> str:
        return (
            f"{overall_status.value}: "
            f"{pass_count} pass, {fail_count} fail, {warning_count} warning, {missing_count} missing"
        )

    def _item(
        self,
        *,
        item_id: str,
        category: ChecklistCategory,
        status: ChecklistItemStatus,
        label: str,
        description: str,
        evidence_codes: tuple[str, ...],
        severity: str,
        timeframe: Timeframe | None = None,
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> ChecklistItem:
        return ChecklistItem(
            id=item_id,
            category=category,
            status=status,
            label=label,
            description=description,
            timeframe=timeframe,
            evidence_codes=evidence_codes,
            severity=severity,
            metadata=metadata or {},
        )

    def _aoi_item(
        self,
        *,
        item_id: str,
        status: ChecklistItemStatus,
        label: str,
        description: str,
        evidence_codes: tuple[str, ...],
        severity: str,
        timeframe: Timeframe | None = None,
    ) -> ChecklistItem:
        return self._item(
            item_id=item_id,
            category=ChecklistCategory.AOI_LOCATION,
            status=status,
            label=label,
            description=description,
            timeframe=timeframe,
            evidence_codes=evidence_codes,
            severity=severity,
        )
