from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import load_settings
from backend.models.domain import Timeframe


def test_load_default_settings_validates_typed_config() -> None:
    """Covers CFG-001 and TEST-001."""

    settings = load_settings()

    assert settings.app.name == "trading-intelligence-platform"
    assert settings.market_data.symbols == ("BTCUSDT",)
    assert settings.candles.base_timeframe is Timeframe.ONE_MINUTE
    assert settings.candles.derived_timeframes == (
        Timeframe.FOUR_HOUR,
        Timeframe.DAILY,
        Timeframe.WEEKLY,
    )
    assert settings.storage.candle_path == Path("data/candles")


def test_invalid_settings_raise_clear_error(tmp_path: Path) -> None:
    """Covers CFG-001 and TEST-001."""

    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        """
app:
  name: trading-intelligence-platform
  environment: local
market_data:
  exchange: binance
  symbols: []
  source: trade_stream
candles:
  base_timeframe: invalid
  derived_timeframes: []
  timezone: UTC
storage:
  candle_path: data/candles
  format: parquet
logging:
  level: INFO
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid settings file"):
        load_settings(config_path)
