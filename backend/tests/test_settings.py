from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import load_settings
from backend.models.domain import Timeframe


def test_load_default_settings_validates_typed_config() -> None:
    """Covers CFG-001 and TEST-001."""

    settings = load_settings()

    assert settings.app.name == "trading-intelligence-platform"
    assert settings.market_data.exchange == "bitmart"
    assert settings.market_data.market_type == "usdt_m_perpetual"
    assert settings.market_data.symbols == ("BTCUSDT",)
    assert not settings.market_data.live_enabled
    assert settings.market_data.reconnect_delay_seconds == 1.0
    assert settings.market_data.max_reconnect_attempts is None
    assert settings.candles.base_timeframe is Timeframe.ONE_MINUTE
    assert settings.candles.derived_timeframes == (
        Timeframe.FIVE_MINUTE,
        Timeframe.FIFTEEN_MINUTE,
        Timeframe.THIRTY_MINUTE,
        Timeframe.ONE_HOUR,
        Timeframe.TWO_HOUR,
        Timeframe.FOUR_HOUR,
        Timeframe.DAILY,
        Timeframe.WEEKLY,
    )
    assert settings.storage.candle_path == Path("data/candles")
    assert settings.demo.enabled
    assert settings.historical_data.integrity_policy == "strict"


def test_invalid_settings_raise_clear_error(tmp_path: Path) -> None:
    """Covers CFG-001 and TEST-001."""

    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        """
app:
  name: trading-intelligence-platform
  environment: local
market_data:
  exchange: unsupported
  market_type: spot
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
historical_data:
  integrity_policy: impossible
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid settings file"):
        load_settings(config_path)
