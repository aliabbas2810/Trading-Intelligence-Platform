from __future__ import annotations

from pathlib import Path
from typing import Mapping, cast

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.models.domain import Timeframe


DEFAULT_SETTINGS_PATH = Path(__file__).with_name("default.yaml")


class AppSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    environment: str


class MarketDataSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    exchange: str
    symbols: tuple[str, ...] = Field(min_length=1)
    source: str


class CandleSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_timeframe: Timeframe
    derived_timeframes: tuple[Timeframe, ...]
    timezone: str


class StorageSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    candle_path: Path
    format: str


class LoggingSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: str


class PlatformSettings(BaseModel):
    """Typed configuration contract for CFG-001."""

    model_config = ConfigDict(frozen=True)

    app: AppSettings
    market_data: MarketDataSettings
    candles: CandleSettings
    storage: StorageSettings
    logging: LoggingSettings


def load_settings(path: Path | None = None) -> PlatformSettings:
    """Load version-controlled YAML settings and validate them for CFG-001."""

    settings_path = path or DEFAULT_SETTINGS_PATH
    raw_settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))

    if not isinstance(raw_settings, Mapping):
        raise ValueError(f"Settings file must contain a mapping: {settings_path}")

    settings_data = cast(Mapping[str, object], raw_settings)
    try:
        return PlatformSettings.model_validate(settings_data)
    except ValidationError as exc:
        raise ValueError(f"Invalid settings file: {settings_path}") from exc
