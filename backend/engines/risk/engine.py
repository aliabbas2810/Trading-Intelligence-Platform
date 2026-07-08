from __future__ import annotations

from backend.engines.entry import EntryDirection, EntryState
from backend.engines.risk.models import (
    RiskAssessmentState,
    RiskDirection,
    RiskEvidence,
    RiskEvidenceCategory,
    RiskEvidenceCode,
    RiskEvidenceSeverity,
    RiskInput,
    RiskLevel,
    RiskPlan,
)
from backend.engines.structure import StructureLabel, StructureSwing
from backend.models import Timeframe


class RiskEngine:
    """Deterministic risk engine consuming existing analytical outputs only."""

    def evaluate(self, risk_input: RiskInput) -> RiskPlan:
        """Build a RiskPlan for RISK-001 through RISK-006."""

        direction = risk_direction_from_entry(risk_input.entry_trace.direction)
        if risk_input.entry_trace.state in {EntryState.WAIT, EntryState.WATCH}:
            return RiskPlan(
                direction=RiskDirection.NONE,
                state=RiskAssessmentState.NOT_APPLICABLE,
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                risk_reward_ratio=None,
                invalidation_level=None,
                risk_level=None,
                evidence=(
                    self._evidence(
                        RiskEvidenceCode.ENTRY_STATE_NOT_APPLICABLE,
                        RiskEvidenceCategory.ENTRY,
                        RiskEvidenceSeverity.INFO,
                        "entry_state_not_applicable",
                        metadata={"entry_state": risk_input.entry_trace.state.value},
                    ),
                ),
                metadata=self._metadata(risk_input),
            )

        if risk_input.entry_trace.state is EntryState.INVALIDATED:
            return RiskPlan(
                direction=direction,
                state=RiskAssessmentState.INVALID,
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                risk_reward_ratio=None,
                invalidation_level=None,
                risk_level=RiskLevel.HIGH,
                evidence=(
                    self._evidence(
                        RiskEvidenceCode.ENTRY_STATE_INVALIDATED,
                        RiskEvidenceCategory.ENTRY,
                        RiskEvidenceSeverity.BLOCKING,
                        "entry_state_invalidated",
                        metadata={"entry_state": risk_input.entry_trace.state.value},
                    ),
                ),
                warnings=("entry_invalidated",),
                metadata=self._metadata(risk_input),
            )

        if direction is RiskDirection.NONE:
            return self._incomplete_plan(
                risk_input,
                direction,
                self._blocking_evidence(
                    RiskEvidenceCode.MISSING_ENTRY_PRICE,
                    "missing_entry_direction",
                ),
            )

        entry_price = risk_input.latest_candle.close if risk_input.latest_candle is not None else None
        if entry_price is None:
            return self._incomplete_plan(
                risk_input,
                direction,
                self._blocking_evidence(RiskEvidenceCode.MISSING_ENTRY_PRICE, "missing_entry_price"),
            )

        stop_level = self._stop_level(risk_input.structure_levels, direction)
        if stop_level is None:
            return RiskPlan(
                direction=direction,
                state=RiskAssessmentState.INCOMPLETE,
                entry_price=entry_price,
                stop_loss=None,
                take_profit=None,
                risk_reward_ratio=None,
                invalidation_level=None,
                risk_level=None,
                evidence=(
                    self._entry_price_evidence(entry_price),
                    self._blocking_evidence(
                        RiskEvidenceCode.MISSING_INVALIDATION_LEVEL,
                        "missing_invalidation_level",
                    ),
                ),
                warnings=("missing_invalidation_level",),
                metadata=self._metadata(risk_input),
            )

        if not self._stop_is_valid(entry_price, stop_level.level, direction):
            return RiskPlan(
                direction=direction,
                state=RiskAssessmentState.INVALID,
                entry_price=entry_price,
                stop_loss=stop_level.level,
                take_profit=None,
                risk_reward_ratio=None,
                invalidation_level=stop_level.level,
                risk_level=RiskLevel.HIGH,
                evidence=(
                    self._entry_price_evidence(entry_price),
                    self._stop_level_evidence(stop_level, direction),
                    self._blocking_evidence(RiskEvidenceCode.INVALID_STOP_PLACEMENT, "invalid_stop_placement"),
                ),
                warnings=("invalid_stop_placement",),
                metadata=self._metadata(risk_input),
            )

        minimum_rr = risk_input.minimum_risk_reward
        if minimum_rr is None or minimum_rr <= 0:
            return RiskPlan(
                direction=direction,
                state=RiskAssessmentState.INCOMPLETE,
                entry_price=entry_price,
                stop_loss=stop_level.level,
                take_profit=None,
                risk_reward_ratio=None,
                invalidation_level=stop_level.level,
                risk_level=None,
                evidence=(
                    self._entry_price_evidence(entry_price),
                    self._stop_level_evidence(stop_level, direction),
                    self._blocking_evidence(
                        RiskEvidenceCode.TAKE_PROFIT_FROM_RR_TARGET,
                        "missing_rr_target",
                    ),
                ),
                warnings=("missing_rr_target",),
                metadata=self._metadata(risk_input),
            )

        take_profit = self._take_profit(entry_price, stop_level.level, minimum_rr, direction)
        risk_reward_ratio = self._risk_reward(entry_price, stop_level.level, take_profit, direction)
        return RiskPlan(
            direction=direction,
            state=RiskAssessmentState.VALID,
            entry_price=entry_price,
            stop_loss=stop_level.level,
            take_profit=take_profit,
            risk_reward_ratio=risk_reward_ratio,
            invalidation_level=stop_level.level,
            risk_level=self._risk_level(risk_reward_ratio),
            evidence=(
                self._entry_price_evidence(entry_price),
                self._stop_level_evidence(stop_level, direction),
                self._target_evidence(take_profit, minimum_rr, direction),
                self._rr_evidence(risk_reward_ratio),
            ),
            metadata=self._metadata(risk_input),
        )

    def _stop_level(
        self,
        structure_levels: tuple[StructureSwing, ...],
        direction: RiskDirection,
    ) -> StructureSwing | None:
        target_label = StructureLabel.HL if direction is RiskDirection.LONG else StructureLabel.LH
        candidates = tuple(level for level in structure_levels if level.label is target_label)
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.candle_close_time_ms)

    def _stop_is_valid(self, entry_price: float, stop_loss: float, direction: RiskDirection) -> bool:
        if direction is RiskDirection.LONG:
            return stop_loss < entry_price
        if direction is RiskDirection.SHORT:
            return stop_loss > entry_price
        return False

    def _take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        minimum_rr: float,
        direction: RiskDirection,
    ) -> float:
        risk = abs(entry_price - stop_loss)
        if direction is RiskDirection.LONG:
            return entry_price + risk * minimum_rr
        return entry_price - risk * minimum_rr

    def _risk_reward(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        direction: RiskDirection,
    ) -> float:
        risk = abs(entry_price - stop_loss)
        reward = take_profit - entry_price if direction is RiskDirection.LONG else entry_price - take_profit
        return round(reward / risk, 4)

    def _risk_level(self, risk_reward_ratio: float) -> RiskLevel:
        if risk_reward_ratio >= 3.0:
            return RiskLevel.LOW
        if risk_reward_ratio >= 2.0:
            return RiskLevel.MEDIUM
        return RiskLevel.HIGH

    def _incomplete_plan(
        self,
        risk_input: RiskInput,
        direction: RiskDirection,
        evidence: RiskEvidence,
    ) -> RiskPlan:
        return RiskPlan(
            direction=direction,
            state=RiskAssessmentState.INCOMPLETE,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_reward_ratio=None,
            invalidation_level=None,
            risk_level=None,
            evidence=(evidence,),
            warnings=(evidence.description,),
            metadata=self._metadata(risk_input),
        )

    def _entry_price_evidence(self, entry_price: float) -> RiskEvidence:
        return self._evidence(
            RiskEvidenceCode.ENTRY_PRICE_FROM_LATEST_CLOSE,
            RiskEvidenceCategory.CANDLE,
            RiskEvidenceSeverity.INFO,
            "entry_price_from_latest_close",
            metadata={"entry_price": entry_price},
        )

    def _stop_level_evidence(self, level: StructureSwing, direction: RiskDirection) -> RiskEvidence:
        return self._evidence(
            RiskEvidenceCode.STOP_FROM_STRUCTURE_LEVEL,
            RiskEvidenceCategory.STRUCTURE,
            RiskEvidenceSeverity.INFO,
            "stop_from_structure_level",
            timeframe=level.timeframe,
            metadata={
                "direction": direction.value,
                "label": level.label.value,
                "level": level.level,
            },
        )

    def _target_evidence(
        self,
        take_profit: float,
        minimum_rr: float,
        direction: RiskDirection,
    ) -> RiskEvidence:
        return self._evidence(
            RiskEvidenceCode.TAKE_PROFIT_FROM_RR_TARGET,
            RiskEvidenceCategory.TARGET,
            RiskEvidenceSeverity.INFO,
            "take_profit_from_rr_target",
            metadata={
                "direction": direction.value,
                "take_profit": take_profit,
                "minimum_risk_reward": minimum_rr,
            },
        )

    def _rr_evidence(self, risk_reward_ratio: float) -> RiskEvidence:
        return self._evidence(
            RiskEvidenceCode.RISK_REWARD_CALCULATED,
            RiskEvidenceCategory.VALIDATION,
            RiskEvidenceSeverity.INFO,
            "risk_reward_calculated",
            metadata={"risk_reward_ratio": risk_reward_ratio},
        )

    def _blocking_evidence(self, code: RiskEvidenceCode, description: str) -> RiskEvidence:
        return self._evidence(
            code,
            RiskEvidenceCategory.VALIDATION,
            RiskEvidenceSeverity.BLOCKING,
            description,
        )

    def _evidence(
        self,
        code: RiskEvidenceCode,
        category: RiskEvidenceCategory,
        severity: RiskEvidenceSeverity,
        description: str,
        *,
        timeframe: Timeframe | None = None,
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> RiskEvidence:
        return RiskEvidence(
            code=code,
            category=category,
            severity=severity,
            description=description,
            timeframe=timeframe,
            metadata=metadata or {},
        )

    def _metadata(self, risk_input: RiskInput) -> dict[str, str | int | float | bool | None]:
        return {
            "entry_state": risk_input.entry_trace.state.value,
            "entry_direction": risk_input.entry_trace.direction.value,
            "structure_level_count": len(risk_input.structure_levels),
            "bos_event_count": len(risk_input.bos_events),
            "minimum_risk_reward": risk_input.minimum_risk_reward,
            "target_mode": risk_input.target_mode,
        }


def risk_direction_from_entry(direction: EntryDirection) -> RiskDirection:
    if direction is EntryDirection.LONG:
        return RiskDirection.LONG
    if direction is EntryDirection.SHORT:
        return RiskDirection.SHORT
    return RiskDirection.NONE
