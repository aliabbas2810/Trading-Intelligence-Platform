from __future__ import annotations

from pydantic import BaseModel, Field

from backend.engines.aoi import (
    AoiGateResult,
    AoiLocationConfig,
    AoiSizingConfig,
    AoiSizingMode,
    AoiTimeframe,
    AreaOfInterest,
    AoiLocationResult,
    AoiOverlap,
)
from backend.engines.entry.models import MetadataValue


class AoiEvaluateRequest(BaseModel):
    symbol: str
    timeframe: AoiTimeframe
    sizing_mode: AoiSizingMode
    minimum_ticks: float | None = Field(default=None, gt=0)
    maximum_ticks: float | None = Field(default=None, gt=0)
    minimum_percentage: float | None = Field(default=None, gt=0)
    maximum_percentage: float | None = Field(default=None, gt=0)
    minimum_atr_multiple: float | None = Field(default=None, gt=0)
    maximum_atr_multiple: float | None = Field(default=None, gt=0)
    tick_size: float | None = Field(default=None, gt=0)
    atr: float | None = Field(default=None, gt=0)

    def to_sizing_config(self) -> AoiSizingConfig:
        return AoiSizingConfig(
            mode=self.sizing_mode,
            minimum_ticks=self.minimum_ticks,
            maximum_ticks=self.maximum_ticks,
            minimum_percentage=self.minimum_percentage,
            maximum_percentage=self.maximum_percentage,
            minimum_atr_multiple=self.minimum_atr_multiple,
            maximum_atr_multiple=self.maximum_atr_multiple,
        )


class AoiLocationRequest(BaseModel):
    symbol: str
    aoi_id: str
    proximity_tolerance: float = Field(ge=0)
    maximum_post_reaction_excursion: float = Field(ge=0)

    def to_location_config(self) -> AoiLocationConfig:
        return AoiLocationConfig(
            proximity_tolerance=self.proximity_tolerance,
            maximum_post_reaction_excursion=self.maximum_post_reaction_excursion,
        )


class AoiBoundsResponse(BaseModel):
    lower: float
    upper: float


class AoiRankingResponse(BaseModel):
    score: float
    body_close_count: int
    body_touch_count: int
    reaction_count: int
    recency_time_ms: int
    normalized_width: float


class AoiResponse(BaseModel):
    """Read-only AOI transport model for AOI-VIS-001..006."""

    aoi_id: str
    symbol: str
    timeframe: str
    direction: str
    state: str
    lower: float
    upper: float
    first_touch_time_ms: int
    confirmation_time_ms: int | None
    touch_count: int
    body_close_count: int
    reaction_count: int
    origin_structure_leg_id: str
    origin_trend_id: str
    ranking: AoiRankingResponse
    active_current_leg: bool
    metadata: dict[str, MetadataValue]

    @classmethod
    def from_area(cls, area: AreaOfInterest) -> AoiResponse:
        return cls(
            aoi_id=area.aoi_id,
            symbol=area.symbol,
            timeframe=area.timeframe.value,
            direction=area.direction.value,
            state=area.state.value,
            lower=area.bounds.lower,
            upper=area.bounds.upper,
            first_touch_time_ms=area.first_touch_time_ms,
            confirmation_time_ms=area.confirmation_time_ms,
            touch_count=area.touch_count,
            body_close_count=area.close_count,
            reaction_count=area.reaction_count,
            origin_structure_leg_id=area.origin_structure_leg_id,
            origin_trend_id=area.origin_trend_id,
            ranking=AoiRankingResponse(
                score=area.ranking.score,
                body_close_count=area.ranking.body_close_count,
                body_touch_count=area.ranking.body_touch_count,
                reaction_count=area.ranking.reaction_count,
                recency_time_ms=area.ranking.recency_time_ms,
                normalized_width=area.ranking.normalized_width,
            ),
            active_current_leg=area.state.value == "active",
            metadata={
                "origin_timeframe": area.origin_timeframe.value,
                "state_changed_time_ms": area.state_changed_time_ms,
            },
        )


class AoiOverlapResponse(BaseModel):
    weekly_aoi_id: str
    daily_aoi_id: str
    lower: float
    upper: float
    overlap_ratio: float
    is_full_intersection: bool
    confluence_weight: float

    @classmethod
    def from_overlap(cls, overlap: AoiOverlap) -> AoiOverlapResponse:
        return cls(
            weekly_aoi_id=overlap.weekly_aoi_id,
            daily_aoi_id=overlap.daily_aoi_id,
            lower=overlap.intersection_bounds.lower,
            upper=overlap.intersection_bounds.upper,
            overlap_ratio=overlap.overlap_ratio,
            is_full_intersection=overlap.is_full_intersection,
            confluence_weight=overlap.confluence_weight,
        )


class AoiLocationResponse(BaseModel):
    aoi_id: str
    state: str
    distance: float
    current_touch: bool
    gate_open: bool
    reason: str

    @classmethod
    def from_location(cls, location: AoiLocationResult) -> AoiLocationResponse:
        return cls(
            aoi_id=location.aoi_id,
            state=location.state.value,
            distance=location.distance,
            current_touch=location.current_touch,
            gate_open=location.gate_open,
            reason=location.reason,
        )


class AoiGateResponse(BaseModel):
    symbol: str
    eligible: bool
    active_aois: tuple[AoiResponse, ...]
    locations: tuple[AoiLocationResponse, ...]
    overlaps: tuple[AoiOverlapResponse, ...]
    reason_codes: tuple[str, ...]

    @classmethod
    def from_gate(cls, gate: AoiGateResult) -> AoiGateResponse:
        return cls(
            symbol=gate.symbol,
            eligible=gate.eligible,
            active_aois=tuple(AoiResponse.from_area(area) for area in gate.active_aois),
            locations=tuple(AoiLocationResponse.from_location(item) for item in gate.locations),
            overlaps=tuple(AoiOverlapResponse.from_overlap(item) for item in gate.overlaps),
            reason_codes=gate.reason_codes,
        )


class AoiReadResponse(BaseModel):
    symbol: str
    aois: tuple[AoiResponse, ...]
    overlaps: tuple[AoiOverlapResponse, ...]
    location_gate: AoiGateResponse
    location_gate_eligible: bool
    reason_codes: tuple[str, ...]
