from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app import (
    BackendRuntime,
    ComponentStatus,
    HistoricalRuntimeConfig,
    RuntimeAlreadyStartedError,
    RuntimeMode,
    RuntimeState,
)
from backend.app.cli import main
from backend.config import PlatformSettings, load_settings
from backend.engines.historical import HistoricalCandleFileStore, HistoricalCandleRequest
from backend.models import Candle, Timeframe, Trade
from backend.pipelines.market_data import BinanceTradeStreamClient


def make_trade(timestamp_ms: int, price: float) -> Trade:
    return Trade(
        symbol="BTCUSDT",
        price=price,
        quantity=1.0,
        timestamp_ms=timestamp_ms,
        source="runtime-test",
    )


def test_runtime_starts_and_reports_running_health() -> None:
    """Covers RUNTIME-001, RUNTIME-002, RUNTIME-003, RUNTIME-004, and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    runtime.start()
    health = runtime.health()

    assert runtime.state is RuntimeState.RUNNING
    assert health.state is RuntimeState.RUNNING
    assert health.mode is RuntimeMode.DRY_RUN
    assert health.is_healthy
    component_statuses = {component.name: component.status for component in health.components}
    assert component_statuses["event_bus"] is ComponentStatus.RUNNING
    assert component_statuses["candle_pipeline"] is ComponentStatus.RUNNING
    assert component_statuses["timeframe_pipeline"] is ComponentStatus.RUNNING
    assert component_statuses["visualization_api"] is ComponentStatus.RUNNING


def test_runtime_stops() -> None:
    """Covers RUNTIME-003 and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)
    runtime.start()

    runtime.stop()

    assert runtime.state is RuntimeState.STOPPED
    assert runtime.health().state is RuntimeState.STOPPED
    assert not runtime.health().is_healthy


def test_runtime_rejects_duplicate_start() -> None:
    """Covers lifecycle guard behavior for RUNTIME-003."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)
    runtime.start()

    with pytest.raises(RuntimeAlreadyStartedError):
        runtime.start()


def test_dry_run_mode_does_not_require_binance_network_access() -> None:
    """Covers RUNTIME-005 and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    runtime.start()
    component_statuses = {component.name: component.status for component in runtime.health().components}

    assert component_statuses["binance_stream_client"] is ComponentStatus.DISABLED
    assert runtime.market_data_parser is not None
    assert runtime.market_data_pipeline is not None


def test_historical_runtime_mode_loads_local_fixture_candles(tmp_path: Path) -> None:
    """Covers M28 historical runtime loading into read/API stores without network calls."""

    request = historical_request()
    HistoricalCandleFileStore(tmp_path).save(request, historical_fixture_candles(count=10))
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(request=request, data_root=tmp_path),
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}

    assert runtime.health().mode is RuntimeMode.HISTORICAL
    assert components["demo_data"].status is ComponentStatus.DISABLED
    assert components["historical_data"].message == "loaded 10 1m candles for BTCUSDT"
    assert len(runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)) == 10
    assert runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)[0].open_time_ms == 0


def test_historical_runtime_mode_does_not_seed_demo_data(tmp_path: Path) -> None:
    """Historical mode must not mix synthetic demo candles into the chart dataset."""

    request = historical_request()
    HistoricalCandleFileStore(tmp_path).save(request, historical_fixture_candles(count=4))
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(request=request, data_root=tmp_path),
    )

    runtime.start()

    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)
    assert len(candles) == 4
    assert {candle.open_time_ms for candle in candles} == {0, 60_000, 120_000, 180_000}


def test_live_binance_mode_starts_stream_client() -> None:
    """Covers FR-101, RUNTIME-002, RUNTIME-003, and TEST-001."""

    runner = RecordingLiveStreamRunner()
    runtime = BackendRuntime(
        settings=live_enabled_settings(),
        mode=RuntimeMode.LIVE_BINANCE,
        live_stream_runner_factory=lambda client: runner.bind(client),
    )

    runtime.start()

    assert runner.started
    assert runner.client is runtime.binance_stream_client


def test_live_binance_mode_stops_stream_client() -> None:
    """Covers FR-102 lifecycle stop handling and RUNTIME-003."""

    runner = RecordingLiveStreamRunner()
    runtime = BackendRuntime(
        settings=live_enabled_settings(),
        mode=RuntimeMode.LIVE_BINANCE,
        live_stream_runner_factory=lambda client: runner.bind(client),
    )
    runtime.start()

    runtime.stop()

    assert runner.stopped


def test_live_binance_trade_event_reaches_candle_pipeline() -> None:
    """Covers FR-109 and RUNTIME-002 without real Binance network calls."""

    trade_payload = json.dumps(
        {
            "e": "trade",
            "s": "BTCUSDT",
            "p": "100.0",
            "q": "1.0",
            "T": 1_000,
        },
    )
    runner = RecordingLiveStreamRunner(messages=(trade_payload,))
    runtime = BackendRuntime(
        settings=live_enabled_settings(),
        mode=RuntimeMode.LIVE_BINANCE,
        live_stream_runner_factory=lambda client: runner.bind(client),
    )

    runtime.start()
    assert runner.client is not None
    runner.client.handle_message(
        json.dumps(
            {
                "e": "trade",
                "s": "BTCUSDT",
                "p": "101.0",
                "q": "1.0",
                "T": 61_000,
            },
        ),
    )

    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)
    assert len(candles) == 1
    assert candles[0].open == 100.0
    assert candles[0].close == 100.0


def test_live_binance_health_reports_stream_fields() -> None:
    """Covers RUNTIME-004 live market data health fields."""

    runner = RecordingLiveStreamRunner()
    runtime = BackendRuntime(
        settings=live_enabled_settings(symbol="ETHUSDT"),
        mode=RuntimeMode.LIVE_BINANCE,
        live_stream_runner_factory=lambda client: runner.bind(client),
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}

    assert runtime.health().mode is RuntimeMode.LIVE_BINANCE
    assert components["market_data_mode"].message == "live_binance"
    assert components["stream_enabled"].message == "True"
    assert components["stream_status"].message == "stopped"
    assert components["active_symbol"].message == "ETHUSDT"
    assert components["binance_stream_client"].status is ComponentStatus.RUNNING


def test_runtime_wires_trade_events_into_existing_candle_pipeline() -> None:
    """Covers RUNTIME-002 integration wiring without duplicating candle logic."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    runtime.start()

    runtime.market_data_pipeline.publish_trade(make_trade(1_000, 100.0))
    runtime.market_data_pipeline.publish_trade(make_trade(61_000, 101.0))

    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)
    assert len(candles) == 1
    assert candles[0].open == 100.0
    assert candles[0].close == 100.0


def test_cli_entrypoint_starts_and_stops_once(capsys: pytest.CaptureFixture[str]) -> None:
    """Covers CLI/module entrypoint for RUNTIME-001 and RUNTIME-005."""

    exit_code = main(["--dry-run", "--once"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"mode": "dry_run"' in captured.out
    assert '"state": "running"' in captured.out


def test_cli_entrypoint_starts_historical_once(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Covers M28 CLI options for local historical runtime mode."""

    request = historical_request()
    HistoricalCandleFileStore(tmp_path).save(request, historical_fixture_candles(count=4))

    exit_code = main(
        [
            "--historical",
            "--symbol",
            "BTCUSDT",
            "--timeframe",
            "1m",
            "--start",
            "1970-01-01T00:00:00Z",
            "--end",
            "1970-01-01T00:04:00Z",
            "--data-root",
            str(tmp_path),
            "--once",
        ],
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"mode": "historical"' in captured.out
    assert '"state": "running"' in captured.out


def test_runtime_does_not_duplicate_business_logic() -> None:
    """Covers no-new-trading-logic constraint and TEST-001."""

    runtime_source = Path("backend/app/runtime.py").read_text(encoding="utf-8")

    forbidden_fragments = (
        "body_high =",
        "body_low =",
        "higher_body_high",
        "lower_body_low",
        "score_candidate",
        "json.loads(",
        "connect(",
        "websockets",
    )
    for fragment in forbidden_fragments:
        assert fragment not in runtime_source


class RecordingLiveStreamRunner:
    def __init__(self, messages: tuple[str, ...] = ()) -> None:
        self.messages = messages
        self.client: BinanceTradeStreamClient | None = None
        self.started = False
        self.stopped = False

    def bind(self, client: BinanceTradeStreamClient) -> RecordingLiveStreamRunner:
        self.client = client
        return self

    def start(self) -> None:
        self.started = True
        if self.client is None:
            raise RuntimeError("Missing Binance client")
        for message in self.messages:
            self.client.handle_message(message)

    def stop(self) -> None:
        self.stopped = True


def live_enabled_settings(symbol: str = "BTCUSDT") -> PlatformSettings:
    settings = load_settings()
    return settings.model_copy(
        update={
            "market_data": settings.market_data.model_copy(
                update={
                    "symbols": (symbol,),
                    "live_enabled": True,
                    "reconnect_delay_seconds": 0.1,
                    "max_reconnect_attempts": 3,
                },
            ),
        },
    )


def demo_disabled_settings() -> PlatformSettings:
    settings = load_settings()
    return settings.model_copy(
        update={
            "demo": settings.demo.model_copy(update={"enabled": False}),
        },
    )


def historical_request() -> HistoricalCandleRequest:
    return HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=240_000,
    )


def historical_fixture_candles(*, count: int) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    close = 100.0
    for index in range(count):
        open_price = close
        close = open_price + 1.0
        open_time_ms = index * 60_000
        candles.append(
            Candle(
                symbol="BTCUSDT",
                timeframe=Timeframe.ONE_MINUTE,
                open_time_ms=open_time_ms,
                close_time_ms=open_time_ms + 60_000,
                open=open_price,
                high=close + 1.0,
                low=open_price - 1.0,
                close=close,
                volume=1.0,
            ),
        )
    return tuple(candles)
