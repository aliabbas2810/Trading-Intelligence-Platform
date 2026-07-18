from __future__ import annotations

from backend.api import StructureSnapshot
from backend.engines.aoi import AoiLocationState
from backend.engines.entry.models import (
    DecisionEvidence,
    DecisionEvidenceCategory,
    DecisionEvidenceCode,
    DecisionEvidencePolarity,
    DecisionEvidenceSeverity,
    DecisionTrace,
    EntryDirection,
    EntrySignalInput,
    EntryState,
    MetadataValue,
)
from backend.engines.structure import BreakDirection, StructureLabel
from backend.engines.trend import DirectionalBias, TrendState
from backend.models import Candle, Timeframe


class EntrySignalEngine:
    """Deterministic entry-state engine consuming existing outputs only."""

    def evaluate(self, signal_input: EntrySignalInput) -> DecisionTrace:
        """Classify entry state for ENTRY-001 through ENTRY-006."""

        direction = self._alignment_direction(signal_input)
        if direction is EntryDirection.NONE:
            return DecisionTrace(
                state=EntryState.WAIT,
                direction=EntryDirection.NONE,
                confidence=0.1,
                evidence=(
                    self._alignment_blocking_evidence(signal_input),
                    *(
                        self._aoi_gate_blocking_evidence(signal_input)
                        if signal_input.alignment is None
                        else ()
                    ),
                    *self._missing_evidence(signal_input),
                ),
                metadata=self._metadata(signal_input),
            )

        aoi_blocking = self._aoi_gate_blocking_evidence(signal_input)
        if aoi_blocking:
            return DecisionTrace(
                state=EntryState.WAIT,
                direction=EntryDirection.NONE,
                confidence=0.1,
                evidence=(
                    self._alignment_support_evidence(signal_input),
                    *aoi_blocking,
                ),
                metadata=self._metadata(signal_input),
            )

        aoi_support = self._aoi_support_evidence(signal_input)
        conflicting = self._conflicting_trend_evidence(signal_input, direction)
        if conflicting:
            return DecisionTrace(
                state=EntryState.WAIT,
                direction=direction,
                confidence=0.2,
                evidence=(
                    self._alignment_support_evidence(signal_input),
                    *aoi_support,
                    *conflicting,
                ),
                metadata=self._metadata(signal_input),
            )

        invalidations = self._invalidation_evidence(signal_input, direction)
        if invalidations:
            return DecisionTrace(
                state=EntryState.INVALIDATED,
                direction=direction,
                confidence=0.0,
                evidence=(
                    self._alignment_support_evidence(signal_input),
                    *aoi_support,
                    *invalidations,
                ),
                trigger_timeframe=self._latest_bos_timeframe(signal_input),
                metadata=self._metadata(signal_input),
            )

        missing = self._missing_evidence(signal_input)
        if missing:
            return DecisionTrace(
                state=EntryState.WATCH,
                direction=direction,
                confidence=0.35,
                evidence=(
                    self._alignment_support_evidence(signal_input),
                    *aoi_support,
                    self._status_evidence(
                        DecisionEvidenceCode.WAITING_FOR_LOWER_TIMEFRAME_DATA,
                        DecisionEvidenceCategory.MISSING_CONFIRMATION,
                        DecisionEvidencePolarity.MISSING,
                        DecisionEvidenceSeverity.WARNING,
                        "waiting_for_lower_timeframe_data",
                    ),
                    *missing,
                ),
                metadata=self._metadata(signal_input),
            )

        setup_timeframes = self._setup_timeframes(signal_input, direction)
        if len(setup_timeframes) < 2:
            return DecisionTrace(
                state=EntryState.WATCH,
                direction=direction,
                confidence=0.45,
                evidence=(
                    self._alignment_support_evidence(signal_input),
                    *aoi_support,
                    self._status_evidence(
                        DecisionEvidenceCode.WAITING_FOR_15M_5M_STRUCTURE,
                        DecisionEvidenceCategory.STRUCTURE,
                        DecisionEvidencePolarity.MISSING,
                        DecisionEvidenceSeverity.WARNING,
                        "waiting_for_15m_5m_structure",
                    ),
                    *self._missing_structure_support_evidence(
                        signal_input,
                        direction,
                        (Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE),
                    ),
                ),
                metadata=self._metadata(signal_input),
            )

        if self._entry_confirmation(signal_input, direction):
            return DecisionTrace(
                state=EntryState.ENTRY_READY,
                direction=direction,
                confidence=0.85,
                evidence=(
                    self._alignment_support_evidence(signal_input),
                    *aoi_support,
                    *self._structure_confirmation_evidence(setup_timeframes, direction),
                    self._status_evidence(
                        DecisionEvidenceCode.SETUP_CONFIRMED,
                        DecisionEvidenceCategory.STRUCTURE,
                        DecisionEvidencePolarity.SUPPORTS,
                        DecisionEvidenceSeverity.INFO,
                        "setup_confirmed",
                    ),
                    self._one_minute_confirmation_evidence(signal_input, direction),
                ),
                trigger_timeframe=Timeframe.ONE_MINUTE,
                metadata=self._metadata(signal_input),
            )

        setup_state = EntryState.LONG_SETUP if direction is EntryDirection.LONG else EntryState.SHORT_SETUP
        return DecisionTrace(
            state=setup_state,
            direction=direction,
            confidence=0.65,
            evidence=(
                self._alignment_support_evidence(signal_input),
                *aoi_support,
                *self._structure_confirmation_evidence(setup_timeframes, direction),
                self._status_evidence(
                    DecisionEvidenceCode.MISSING_CONFIRMATION,
                    DecisionEvidenceCategory.MISSING_CONFIRMATION,
                    DecisionEvidencePolarity.MISSING,
                    DecisionEvidenceSeverity.WARNING,
                    "1m_confirmation",
                    metadata={"missing_key": "1m_confirmation"},
                ),
            ),
            trigger_timeframe=Timeframe.FIVE_MINUTE,
            metadata=self._metadata(signal_input),
        )

    def _alignment_direction(self, signal_input: EntrySignalInput) -> EntryDirection:
        alignment = signal_input.alignment
        if alignment is None or alignment.alignment_score < 2:
            return EntryDirection.NONE
        if alignment.bias is DirectionalBias.BULLISH:
            return EntryDirection.LONG
        if alignment.bias is DirectionalBias.BEARISH:
            return EntryDirection.SHORT
        return EntryDirection.NONE

    def _conflicting_trend_evidence(
        self,
        signal_input: EntrySignalInput,
        direction: EntryDirection,
    ) -> tuple[DecisionEvidence, ...]:
        conflicts: list[DecisionEvidence] = []
        expected_state = TrendState.BULLISH if direction is EntryDirection.LONG else TrendState.BEARISH
        opposite_state = TrendState.BEARISH if direction is EntryDirection.LONG else TrendState.BULLISH
        for timeframe, trend in signal_input.trend_by_timeframe.items():
            if trend is None:
                continue
            if trend.state is opposite_state:
                conflicts.append(
                    self._status_evidence(
                        DecisionEvidenceCode.HIGHER_TIMEFRAME_CONFLICT,
                        DecisionEvidenceCategory.TREND,
                        DecisionEvidencePolarity.OPPOSES,
                        DecisionEvidenceSeverity.BLOCKING,
                        "higher_timeframe_conflict",
                        timeframe=timeframe,
                        metadata={"missing_key": f"{timeframe.value}_trend_conflicts"},
                    ),
                )
            elif trend.state is not expected_state and timeframe in {
                Timeframe.WEEKLY,
                Timeframe.DAILY,
                Timeframe.FOUR_HOUR,
            }:
                conflicts.append(
                    self._status_evidence(
                        DecisionEvidenceCode.HIGHER_TIMEFRAME_CONFLICT,
                        DecisionEvidenceCategory.TREND,
                        DecisionEvidencePolarity.OPPOSES,
                        DecisionEvidenceSeverity.BLOCKING,
                        "higher_timeframe_conflict",
                        timeframe=timeframe,
                        metadata={"missing_key": f"{timeframe.value}_trend_not_confirmed"},
                    ),
                )
        return tuple(conflicts)

    def _missing_evidence(self, signal_input: EntrySignalInput) -> tuple[DecisionEvidence, ...]:
        missing: list[DecisionEvidence] = []
        for timeframe, trend in signal_input.trend_by_timeframe.items():
            if trend is None:
                missing.append(self._missing_confirmation_evidence(f"{timeframe.value}_trend", timeframe))
        for timeframe, structure in signal_input.structure_by_timeframe.items():
            if structure is None or (not structure.swings and not structure.breaks_of_structure):
                missing.append(self._missing_confirmation_evidence(f"{timeframe.value}_structure", timeframe))
        if signal_input.latest_candle is None:
            missing.append(self._missing_confirmation_evidence("latest_candle", None))
        if signal_input.alignment is None:
            missing.append(self._missing_confirmation_evidence("alignment", None))
        return tuple(missing)

    def _invalidation_evidence(
        self,
        signal_input: EntrySignalInput,
        direction: EntryDirection,
    ) -> tuple[DecisionEvidence, ...]:
        invalidating_direction = (
            BreakDirection.BEARISH if direction is EntryDirection.LONG else BreakDirection.BULLISH
        )
        return tuple(
            self._status_evidence(
                DecisionEvidenceCode.OPPOSING_BOS_INVALIDATION,
                DecisionEvidenceCategory.INVALIDATION,
                DecisionEvidencePolarity.OPPOSES,
                DecisionEvidenceSeverity.BLOCKING,
                "lower_timeframe_invalidation",
                timeframe=event.timeframe,
                metadata={
                    "condition": f"{event.timeframe.value}_{event.direction.value}_bos",
                    "bos_direction": event.direction.value,
                    "broken_level": event.broken_level,
                },
            )
            for event in signal_input.bos_events
            if event.direction is invalidating_direction
        )

    def _setup_timeframes(
        self,
        signal_input: EntrySignalInput,
        direction: EntryDirection,
    ) -> tuple[Timeframe, ...]:
        timeframes: list[Timeframe] = []
        for timeframe in (Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE):
            structure = signal_input.structure_by_timeframe[timeframe]
            if structure is not None and self._structure_supports_direction(structure, direction):
                timeframes.append(timeframe)
        return tuple(timeframes)

    def _entry_confirmation(self, signal_input: EntrySignalInput, direction: EntryDirection) -> bool:
        structure = signal_input.structure_1m
        if structure is None or not self._structure_supports_direction(structure, direction):
            return False
        if signal_input.latest_candle is None:
            return False
        return candle_body_supports_direction(signal_input.latest_candle, direction)

    def _missing_structure_support_evidence(
        self,
        signal_input: EntrySignalInput,
        direction: EntryDirection,
        timeframes: tuple[Timeframe, ...],
    ) -> tuple[DecisionEvidence, ...]:
        missing: list[DecisionEvidence] = []
        for timeframe in timeframes:
            structure = signal_input.structure_by_timeframe[timeframe]
            if structure is None:
                missing.append(self._missing_confirmation_evidence(f"{timeframe.value}_structure", timeframe))
            elif not self._structure_supports_direction(structure, direction):
                missing.append(
                    self._missing_confirmation_evidence(f"{timeframe.value}_structure_support", timeframe),
                )
        return tuple(missing)

    def _structure_supports_direction(
        self,
        structure: StructureSnapshot,
        direction: EntryDirection,
    ) -> bool:
        target_bos = BreakDirection.BULLISH if direction is EntryDirection.LONG else BreakDirection.BEARISH
        if any(event.direction is target_bos for event in structure.breaks_of_structure):
            return True

        labels = {swing.label for swing in structure.swings}
        if direction is EntryDirection.LONG:
            return {StructureLabel.HH, StructureLabel.HL}.issubset(labels)
        return {StructureLabel.LH, StructureLabel.LL}.issubset(labels)

    def _latest_bos_timeframe(self, signal_input: EntrySignalInput) -> Timeframe | None:
        if not signal_input.bos_events:
            return None
        return max(signal_input.bos_events, key=lambda event: event.candle_close_time_ms).timeframe

    def _metadata(self, signal_input: EntrySignalInput) -> dict[str, str | int | float | bool | None]:
        return {
            "symbol": signal_input.symbol,
            "alignment_score": (
                signal_input.alignment.alignment_score if signal_input.alignment is not None else None
            ),
            "alignment_bias": (
                signal_input.alignment.bias.value if signal_input.alignment is not None else None
            ),
            "latest_body_high": (
                signal_input.latest_candle.body_high if signal_input.latest_candle is not None else None
            ),
            "latest_body_low": (
                signal_input.latest_candle.body_low if signal_input.latest_candle is not None else None
            ),
            "aoi_gate_eligible": (
                signal_input.aoi_gate.eligible if signal_input.aoi_gate is not None else None
            ),
            "aoi_reason_codes": (
                ",".join(signal_input.aoi_gate.reason_codes) if signal_input.aoi_gate is not None else None
            ),
        }

    def _aoi_gate_blocking_evidence(
        self,
        signal_input: EntrySignalInput,
    ) -> tuple[DecisionEvidence, ...]:
        gate = signal_input.aoi_gate
        if gate is None:
            return (
                self._status_evidence(
                    DecisionEvidenceCode.AOI_DATA_MISSING,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.MISSING,
                    DecisionEvidenceSeverity.BLOCKING,
                    "aoi_data_missing",
                    metadata={"missing_key": "weekly_daily_aoi_location"},
                ),
            )
        if gate.eligible:
            return ()
        codes = set(gate.reason_codes)
        evidence: list[DecisionEvidence] = []
        if "aoi_data_missing" in codes:
            evidence.append(
                self._status_evidence(
                    DecisionEvidenceCode.AOI_DATA_MISSING,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.MISSING,
                    DecisionEvidenceSeverity.BLOCKING,
                    "aoi_data_missing",
                    metadata={
                        "missing_key": "weekly_daily_aoi_location",
                        "reason_codes": ",".join(gate.reason_codes),
                    },
                ),
            )
        if "no_active_aoi" in codes:
            evidence.append(
                self._status_evidence(
                    DecisionEvidenceCode.NO_ACTIVE_AOI,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.OPPOSES,
                    DecisionEvidenceSeverity.BLOCKING,
                    "no_active_aoi",
                    metadata={
                        "condition": "aoi_evaluated_without_active_weekly_or_daily_zone",
                        "reason_codes": ",".join(gate.reason_codes),
                    },
                ),
            )
        if "aoi_moved_away" in codes:
            evidence.append(
                self._status_evidence(
                    DecisionEvidenceCode.AOI_MOVED_AWAY,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.OPPOSES,
                    DecisionEvidenceSeverity.BLOCKING,
                    "aoi_moved_away",
                    metadata={"condition": "price_moved_away_from_weekly_daily_aoi"},
                ),
            )
        if "aoi_location_not_eligible" in codes:
            evidence.append(
                self._status_evidence(
                    DecisionEvidenceCode.AOI_LOCATION_NOT_ELIGIBLE,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.OPPOSES,
                    DecisionEvidenceSeverity.BLOCKING,
                    "aoi_location_not_eligible",
                    metadata={
                        "condition": "price_not_inside_touching_reacting_or_entry_window",
                        "reason_codes": ",".join(gate.reason_codes),
                    },
                ),
            )
        return tuple(evidence)

    def _aoi_support_evidence(self, signal_input: EntrySignalInput) -> tuple[DecisionEvidence, ...]:
        gate = signal_input.aoi_gate
        if gate is None or not gate.eligible:
            return ()

        evidence: list[DecisionEvidence] = []
        if gate.weekly_active:
            evidence.append(
                self._status_evidence(
                    DecisionEvidenceCode.WEEKLY_AOI_ACTIVE,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.SUPPORTS,
                    DecisionEvidenceSeverity.INFO,
                    "weekly_aoi_active",
                    timeframe=Timeframe.WEEKLY,
                ),
            )
        if gate.daily_active:
            evidence.append(
                self._status_evidence(
                    DecisionEvidenceCode.DAILY_AOI_ACTIVE,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.SUPPORTS,
                    DecisionEvidenceSeverity.INFO,
                    "daily_aoi_active",
                    timeframe=Timeframe.DAILY,
                ),
            )
        if gate.overlaps:
            evidence.append(
                self._status_evidence(
                    DecisionEvidenceCode.WEEKLY_DAILY_AOI_OVERLAP,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.SUPPORTS,
                    DecisionEvidenceSeverity.INFO,
                    "weekly_daily_aoi_overlap",
                    metadata={"overlap_count": len(gate.overlaps)},
                ),
            )
        for location in gate.locations:
            if not location.gate_open:
                continue
            code = {
                AoiLocationState.INSIDE: DecisionEvidenceCode.AOI_LOCATION_INSIDE,
                AoiLocationState.REACTING: DecisionEvidenceCode.AOI_LOCATION_REACTING,
                AoiLocationState.ENTRY_WINDOW: DecisionEvidenceCode.AOI_LOCATION_ENTRY_WINDOW,
            }.get(location.state, DecisionEvidenceCode.AOI_LOCATION_INSIDE)
            area = next((item for item in gate.active_aois if item.aoi_id == location.aoi_id), None)
            evidence.append(
                self._status_evidence(
                    code,
                    DecisionEvidenceCategory.AOI,
                    DecisionEvidencePolarity.SUPPORTS,
                    DecisionEvidenceSeverity.INFO,
                    code.value,
                    timeframe=area.timeframe.to_timeframe() if area is not None else None,
                    metadata={
                        "aoi_id": location.aoi_id,
                        "location_state": location.state.value,
                        "distance": location.distance,
                    },
                ),
            )
        return tuple(evidence)

    def _alignment_support_evidence(self, signal_input: EntrySignalInput) -> DecisionEvidence:
        return self._alignment_evidence(
            DecisionEvidenceCode.HIGHER_TIMEFRAMES_ALIGNED,
            DecisionEvidencePolarity.SUPPORTS,
            DecisionEvidenceSeverity.INFO,
            "higher_timeframes_aligned",
            signal_input,
        )

    def _alignment_blocking_evidence(self, signal_input: EntrySignalInput) -> DecisionEvidence:
        if signal_input.alignment is None:
            return self._alignment_evidence(
                DecisionEvidenceCode.ALIGNMENT_DATA_MISSING,
                DecisionEvidencePolarity.MISSING,
                DecisionEvidenceSeverity.BLOCKING,
                "alignment_data_missing",
                signal_input,
            )
        return self._alignment_evidence(
            DecisionEvidenceCode.ALIGNMENT_WEAK_OR_NEUTRAL,
            DecisionEvidencePolarity.NEUTRAL,
            DecisionEvidenceSeverity.BLOCKING,
            "alignment_weak_or_neutral",
            signal_input,
        )

    def _alignment_evidence(
        self,
        code: DecisionEvidenceCode,
        polarity: DecisionEvidencePolarity,
        severity: DecisionEvidenceSeverity,
        description: str,
        signal_input: EntrySignalInput,
    ) -> DecisionEvidence:
        return self._status_evidence(
            code,
            DecisionEvidenceCategory.ALIGNMENT,
            polarity,
            severity,
            description,
            metadata={
                "alignment_score": (
                    signal_input.alignment.alignment_score
                    if signal_input.alignment is not None
                    else None
                ),
                "alignment_bias": (
                    signal_input.alignment.bias.value if signal_input.alignment is not None else None
                ),
            },
        )

    def _structure_confirmation_evidence(
        self,
        timeframes: tuple[Timeframe, ...],
        direction: EntryDirection,
    ) -> tuple[DecisionEvidence, ...]:
        code_by_timeframe = {
            Timeframe.FIFTEEN_MINUTE: DecisionEvidenceCode.FIFTEEN_MINUTE_STRUCTURE_CONFIRMATION,
            Timeframe.FIVE_MINUTE: DecisionEvidenceCode.FIVE_MINUTE_STRUCTURE_CONFIRMATION,
        }
        return tuple(
            self._status_evidence(
                code_by_timeframe[timeframe],
                DecisionEvidenceCategory.STRUCTURE,
                DecisionEvidencePolarity.SUPPORTS,
                DecisionEvidenceSeverity.INFO,
                f"{timeframe.value}_structure_confirmation",
                timeframe=timeframe,
                metadata={"direction": direction.value},
            )
            for timeframe in timeframes
            if timeframe in code_by_timeframe
        )

    def _one_minute_confirmation_evidence(
        self,
        signal_input: EntrySignalInput,
        direction: EntryDirection,
    ) -> DecisionEvidence:
        return self._status_evidence(
            DecisionEvidenceCode.ONE_MINUTE_ENTRY_CONFIRMATION,
            DecisionEvidenceCategory.CANDLE,
            DecisionEvidencePolarity.SUPPORTS,
            DecisionEvidenceSeverity.INFO,
            "one_minute_trigger",
            timeframe=Timeframe.ONE_MINUTE,
            metadata={
                "direction": direction.value,
                "latest_body_high": (
                    signal_input.latest_candle.body_high
                    if signal_input.latest_candle is not None
                    else None
                ),
                "latest_body_low": (
                    signal_input.latest_candle.body_low
                    if signal_input.latest_candle is not None
                    else None
                ),
            },
        )

    def _missing_confirmation_evidence(
        self,
        missing_key: str,
        timeframe: Timeframe | None,
    ) -> DecisionEvidence:
        return self._status_evidence(
            DecisionEvidenceCode.MISSING_CONFIRMATION,
            DecisionEvidenceCategory.MISSING_CONFIRMATION,
            DecisionEvidencePolarity.MISSING,
            DecisionEvidenceSeverity.WARNING,
            missing_key,
            timeframe=timeframe,
            metadata={"missing_key": missing_key},
        )

    def _status_evidence(
        self,
        code: DecisionEvidenceCode,
        category: DecisionEvidenceCategory,
        polarity: DecisionEvidencePolarity,
        severity: DecisionEvidenceSeverity,
        description: str,
        *,
        timeframe: Timeframe | None = None,
        metadata: dict[str, MetadataValue] | None = None,
    ) -> DecisionEvidence:
        return DecisionEvidence(
            code=code,
            category=category,
            timeframe=timeframe,
            polarity=polarity,
            severity=severity,
            description=description,
            metadata=metadata or {},
        )


def candle_body_supports_direction(candle: Candle, direction: EntryDirection) -> bool:
    """Use latest completed candle body context for ENTRY-004."""

    if direction is EntryDirection.LONG:
        return candle.close >= candle.open
    if direction is EntryDirection.SHORT:
        return candle.close <= candle.open
    return False
