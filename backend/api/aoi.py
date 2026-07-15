from __future__ import annotations

from pydantic import BaseModel, Field

from backend.engines.aoi import (
    AoiLocationConfig,
    AoiSizingConfig,
    AoiSizingMode,
    AoiTimeframe,
)


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
