from __future__ import annotations

from pathlib import Path
from typing import Literal, Mapping, cast

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

    exchange: Literal["bitmart"]
    market_type: Literal["usdt_m_perpetual"]
    symbols: tuple[str, ...] = Field(min_length=1)
    source: str
    live_enabled: bool = False
    reconnect_delay_seconds: float = Field(default=1.0, gt=0)
    max_reconnect_attempts: int | None = Field(default=None, ge=1)


class CandleSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_timeframe: Timeframe
    derived_timeframes: tuple[Timeframe, ...]
    timezone: str


class StructureSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    displacement_mode: Literal["percent", "atr", "hybrid"] = "percent"
    displacement_percent: float = Field(default=0.02, gt=0)
    bullish_displacement_percent: float | None = Field(default=None, gt=0)
    bearish_displacement_percent: float | None = Field(default=None, gt=0)
    density_anomaly_ratio: float = Field(default=0.35, gt=0, le=1)
    bos_anomaly_ratio: float = Field(default=0.75, gt=0)

    @property
    def effective_bullish_displacement_percent(self) -> float:
        return self.bullish_displacement_percent or self.displacement_percent

    @property
    def effective_bearish_displacement_percent(self) -> float:
        return self.bearish_displacement_percent or self.displacement_percent


class StorageSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    candle_path: Path
    format: str


class LoggingSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: str


class DemoSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = True


class MarketDataSyncSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    startup_enabled: bool = False
    exchange: Literal["bitmart"] = "bitmart"
    market_type: Literal["usdt_m_perpetual"] = "usdt_m_perpetual"
    quote_asset: str = "USDT"
    history_horizon_days: int = Field(default=180, ge=1)
    canonical_timeframe: Timeframe = Timeframe.ONE_MINUTE
    max_concurrent_jobs: int = Field(default=2, ge=1)
    page_size: int = Field(default=500, ge=1)
    retry_count: int = Field(default=3, ge=0)
    backoff_initial_seconds: float = Field(default=0.25, ge=0)
    backoff_multiplier: float = Field(default=2.0, ge=1)
    request_pacing_seconds: float = Field(default=0.0, ge=0)
    data_root: Path = Path("data") / "market_data"
    metadata_database_path: Path = Path("data") / "market_data" / "sync_metadata.sqlite3"
    priority_symbols: tuple[str, ...] = ("BTCUSDT",)
    scanner_ready_only: bool = True


class HistoricalDataSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    integrity_policy: Literal["strict", "warn", "allow"] = "strict"
    data_root: Path = Path("data") / "historical"


class PlatformSettings(BaseModel):
    """Typed configuration contract for CFG-001."""

    model_config = ConfigDict(frozen=True)

    app: AppSettings
    market_data: MarketDataSettings
    candles: CandleSettings
    structure: StructureSettings = Field(default_factory=StructureSettings)
    storage: StorageSettings
    logging: LoggingSettings
    demo: DemoSettings = Field(default_factory=DemoSettings)
    historical_data: HistoricalDataSettings = Field(default_factory=HistoricalDataSettings)
    market_data_sync: MarketDataSyncSettings = Field(default_factory=MarketDataSyncSettings)


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
