from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.app.runtime as runtime_module
from backend.app import (
    BackendRuntime,
    ComponentStatus,
    HistoricalRuntimeConfig,
    RuntimeAlreadyStartedError,
    RuntimeMode,
    RuntimeState,
)
from backend.app.cli import main
from backend.api.service import create_app
from backend.config import PlatformSettings, load_settings
from backend.engines.historical import HistoricalCandleFileStore, HistoricalCandleLoadResult, HistoricalCandleRequest
from backend.engines.historical.loader import inferred_integrity_report
from backend.exchange import (
    ExchangeHistoricalCandleRequest,
    ExchangeName,
    HistoricalDataGap,
    HistoricalGapRecoveryStatus,
    HistoricalIntegrityPolicy,
    HistoricalIntegrityReport,
    HistoricalIntegrityStatus,
    MarketType,
)
from backend.models import Candle, Timeframe, Trade
from backend.pipelines.candle import CandleClosedEvent, CandleEventSource
from backend.pipelines.market_data import BitMartTradeStreamClient, MarketDataConnectionStatus, TradeReceivedEvent


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


def test_dry_run_mode_does_not_require_bitmart_network_access() -> None:
    """Covers RUNTIME-005 and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    runtime.start()
    component_statuses = {component.name: component.status for component in runtime.health().components}

    assert component_statuses["bitmart_stream_client"] is ComponentStatus.DISABLED
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


def test_historical_runtime_warn_policy_loads_partial_cache_with_degraded_integrity(tmp_path: Path) -> None:
    request = historical_request()
    report = incomplete_report(request, policy=HistoricalIntegrityPolicy.WARN)
    HistoricalCandleFileStore(tmp_path).save_result(
        request,
        HistoricalCandleLoadResult(
            candles=historical_fixture_candles(count=3),
            integrity_report=report,
        ),
    )
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(
            request=request,
            data_root=tmp_path,
            integrity_policy=HistoricalIntegrityPolicy.WARN,
        ),
    )

    runtime.start()
    health = runtime.health()
    components = {component.name: component for component in health.components}

    assert runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)
    assert components["historical_candles_loaded"].message == "3"
    assert components["historical_integrity"].message.startswith("policy=warn status=degraded complete=False")
    assert health.historical_integrity == report
    readiness = runtime.evaluate_data_readiness(symbol="BTCUSDT")
    assert readiness.overall_state.value == "DEGRADED"
    assert "historical_data_gap" in readiness.missing_reasons
    assert runtime.evaluate_trading_intelligence(symbol="BTCUSDT").metadata["historical_integrity_status"] == "degraded"
    checklist = runtime.evaluate_checklist(symbol="BTCUSDT")
    assert any(item.id == "data_quality.historical_integrity" and item.status.value == "WARNING" for item in checklist.items)


def test_historical_runtime_allow_policy_loads_partial_cache_with_incomplete_integrity(tmp_path: Path) -> None:
    request = historical_request()
    report = incomplete_report(request, policy=HistoricalIntegrityPolicy.ALLOW)
    HistoricalCandleFileStore(tmp_path).save_result(
        request,
        HistoricalCandleLoadResult(
            candles=historical_fixture_candles(count=3),
            integrity_report=report,
        ),
    )
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(
            request=request,
            data_root=tmp_path,
            integrity_policy=HistoricalIntegrityPolicy.ALLOW,
        ),
    )

    runtime.start()

    assert runtime.health().historical_integrity == report
    assert runtime.evaluate_data_readiness(symbol="BTCUSDT").reason == "historical_integrity_incomplete"


def test_historical_runtime_strict_policy_rejects_partial_cache(tmp_path: Path) -> None:
    request = historical_request()
    HistoricalCandleFileStore(tmp_path).save_result(
        request,
        HistoricalCandleLoadResult(
            candles=historical_fixture_candles(count=3),
            integrity_report=incomplete_report(request, policy=HistoricalIntegrityPolicy.WARN),
        ),
    )
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(
            request=request,
            data_root=tmp_path,
            integrity_policy=HistoricalIntegrityPolicy.STRICT,
        ),
    )

    with pytest.raises(ValueError, match="Strict historical load rejected incomplete cache"):
        runtime.start()


def test_historical_live_runtime_loads_fixture_and_starts_stream(tmp_path: Path) -> None:
    """Covers M29 historical preload followed by injected live stream startup."""

    request = historical_request()
    HistoricalCandleFileStore(tmp_path).save(request, historical_fixture_candles(count=4))
    runner = RecordingLiveStreamRunner()
    runtime = BackendRuntime(
        settings=live_enabled_settings(),
        mode=RuntimeMode.HISTORICAL_LIVE,
        historical_config=HistoricalRuntimeConfig(request=request, data_root=tmp_path),
        live_stream_runner_factory=lambda client: runner.bind(client),
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}

    assert runtime.health().mode is RuntimeMode.HISTORICAL_LIVE
    assert runner.started
    assert components["market_data_mode"].message == "historical_live"
    assert components["stream_enabled"].message == "True"
    assert components["bitmart_stream_client"].status is ComponentStatus.RUNNING
    assert components["historical_data"].message == "loaded 4 1m candles for BTCUSDT"
    assert components["historical_candles_loaded"].message == "4"
    assert components["demo_data"].status is ComponentStatus.DISABLED
    assert len(runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)) == 4


def test_historical_live_boundary_drops_old_live_trades(tmp_path: Path) -> None:
    """Historical/live continuity must not republish trades before the loaded 1m boundary."""

    request = historical_request()
    HistoricalCandleFileStore(tmp_path).save(request, historical_fixture_candles(count=2))
    runner = RecordingLiveStreamRunner(
        messages=(
            make_trade(119_000, 200.0),
            make_trade(120_000, 300.0),
            make_trade(180_000, 301.0),
        ),
    )
    runtime = BackendRuntime(
        settings=live_enabled_settings(),
        mode=RuntimeMode.HISTORICAL_LIVE,
        historical_config=HistoricalRuntimeConfig(request=request, data_root=tmp_path),
        live_stream_runner_factory=lambda client: runner.bind(client),
    )
    received_live_trades: list[Trade] = []
    runtime.event_bus.subscribe(TradeReceivedEvent, lambda event: received_live_trades.append(event.trade))

    runtime.start()

    assert [trade.timestamp_ms for trade in received_live_trades] == [120_000, 180_000]
    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)
    assert len(candles) == 3
    assert candles[-1].open_time_ms == 120_000
    assert candles[-1].open == 300.0


def test_historical_live_does_not_add_duplicate_event_subscriptions(tmp_path: Path) -> None:
    """M29 keeps runtime wiring single-path and avoids duplicate trade subscribers."""

    request = historical_request()
    HistoricalCandleFileStore(tmp_path).save(request, historical_fixture_candles(count=2))
    runtime = BackendRuntime(
        settings=live_enabled_settings(),
        mode=RuntimeMode.HISTORICAL_LIVE,
        historical_config=HistoricalRuntimeConfig(request=request, data_root=tmp_path),
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
    )

    runtime.start()

    assert len(runtime.event_bus._handlers[TradeReceivedEvent]) == 2  # noqa: SLF001


def test_live_bitmart_mode_uses_real_websocket_runner_by_default(tmp_path: Path) -> None:
    """M31.5 wires the real BitMart WebSocket runner by default."""

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path, historical_integrity_policy=HistoricalIntegrityPolicy.WARN),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=FakeLiveCatchupDownloader(latest_completed_open_time_ms=0),
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}

    assert runtime.health().mode is RuntimeMode.LIVE_BITMART
    assert components["market_data_mode"].message == "live_bitmart"
    assert components["exchange"].message == "bitmart"
    assert components["market_type"].message == "usdt_m_perpetual"
    assert components["stream_enabled"].message == "True"
    assert components["stream_status"].message == MarketDataConnectionStatus.STOPPED.value
    assert components["bitmart_stream_client"].message == "bitmart:usdt_m_perpetual:BTCUSDT"
    assert components["websocket_endpoint"].message.startswith("wss://openapi-ws")
    assert components["subscription_channel"].message == "futures/trade:BTCUSDT"
    assert components["sync_loaded_count"].message == "1"


def test_live_bitmart_mode_stops_injected_stream_client(tmp_path: Path) -> None:
    """Covers FR-102 lifecycle stop handling and RUNTIME-003."""

    runner = RecordingLiveStreamRunner()
    runtime = BackendRuntime(
        settings=live_enabled_settings(
            data_root=tmp_path,
            historical_integrity_policy=HistoricalIntegrityPolicy.WARN,
        ),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: runner.bind(client),
        historical_downloader=FakeLiveCatchupDownloader(latest_completed_open_time_ms=0),
    )
    runtime.start()

    runtime.stop()

    assert runner.stopped


def test_live_bitmart_injected_trade_event_reaches_candle_pipeline(tmp_path: Path) -> None:
    """Covers FR-109 and RUNTIME-002 without real BitMart network calls."""

    runner = RecordingLiveStreamRunner(messages=(make_trade(61_000, 100.0),))
    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: runner.bind(client),
        historical_downloader=FakeLiveCatchupDownloader(latest_completed_open_time_ms=0),
    )

    runtime.start()
    assert runner.client is not None
    runner.client.publish_trade(make_trade(121_000, 101.0))

    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)
    assert len(candles) == 2
    assert candles[-1].open_time_ms == 60_000
    assert candles[-1].open == 100.0
    assert candles[-1].close == 100.0


def test_live_bitmart_buffers_and_hands_off_current_minute_trades(tmp_path: Path) -> None:
    """Covers race-safe REST/WebSocket handoff without duplicate finalized candles."""

    runner = RecordingLiveStreamRunner(
        messages=(
            make_trade(60_000, 90.0),
            make_trade(180_000, 101.0),
        ),
    )
    runtime = BackendRuntime(
        settings=live_enabled_settings(
            data_root=tmp_path,
            historical_integrity_policy=HistoricalIntegrityPolicy.WARN,
        ),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: runner.bind(client),
        historical_downloader=FakeLiveCatchupDownloader(latest_completed_open_time_ms=120_000),
    )

    runtime.start()
    assert runner.client is not None
    runner.client.publish_trade(make_trade(240_000, 102.0))

    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)
    assert [candle.open_time_ms for candle in candles] == [0, 60_000, 120_000, 180_000]
    assert candles[-1].open == 101.0
    assert candles[-1].close == 101.0


def test_live_bitmart_persists_finalized_live_candle_as_segment(tmp_path: Path) -> None:
    """Covers append-friendly live 1m persistence and restart-compatible discovery."""

    runner = RecordingLiveStreamRunner(messages=(make_trade(60_000, 100.0),))
    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: runner.bind(client),
        historical_downloader=FakeLiveCatchupDownloader(latest_completed_open_time_ms=0),
    )

    runtime.start()
    assert runner.client is not None
    runner.client.publish_trade(make_trade(120_000, 101.0))

    segment = (
        tmp_path
        / "bitmart"
        / "usdt_m_perpetual"
        / "BTCUSDT"
        / "1m"
        / "0_86400000.jsonl"
    )
    components = {component.name: component for component in runtime.health().components}
    assert segment.exists()
    assert components["last_persisted_candle_open_time_ms"].message == "60000"


def test_historical_replay_candle_event_does_not_invoke_live_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical replay must feed analysis without being persisted as live data."""

    persisted: list[Candle] = []

    def record_persist(self: HistoricalCandleFileStore, candle: Candle, *, exchange: str, market_type: str) -> Path:
        persisted.append(candle)
        return tmp_path / "unexpected.jsonl"

    monkeypatch.setattr(HistoricalCandleFileStore, "save_candle_segment", record_persist)
    runtime = BackendRuntime(settings=live_enabled_settings(data_root=tmp_path), mode=RuntimeMode.LIVE_BITMART)
    runtime._subscribe_components()
    observed: list[CandleClosedEvent] = []
    runtime.event_bus.subscribe(CandleClosedEvent, observed.append)

    for open_time_ms in range(0, 300_000, 60_000):
        runtime.event_bus.publish(
            CandleClosedEvent(
                candle=candle_for_open_time("BTCUSDT", open_time_ms),
                source=CandleEventSource.HISTORICAL_REPLAY,
            )
        )

    assert persisted == []
    assert len(observed) == 5
    assert len(runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)) == 5
    assert len(runtime.visualization_api.get_candles("BTCUSDT", Timeframe.FIVE_MINUTE)) == 1


def test_live_stream_candle_event_invokes_live_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only LIVE_STREAM 1m events use the append-friendly live persistence path."""

    persisted: list[Candle] = []

    def record_persist(self: HistoricalCandleFileStore, candle: Candle, *, exchange: str, market_type: str) -> Path:
        persisted.append(candle)
        return tmp_path / "live.jsonl"

    monkeypatch.setattr(HistoricalCandleFileStore, "save_candle_segment", record_persist)
    runtime = BackendRuntime(settings=live_enabled_settings(data_root=tmp_path), mode=RuntimeMode.LIVE_BITMART)

    runtime._handle_candle_closed(
        CandleClosedEvent(
            candle=candle_for_open_time("BTCUSDT", 0),
            source=CandleEventSource.LIVE_STREAM,
        )
    )

    assert [candle.open_time_ms for candle in persisted] == [0]


def test_non_one_minute_live_candle_event_does_not_use_one_minute_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Higher timeframe live events are not written through the 1m daily segment path."""

    persisted: list[Candle] = []

    def record_persist(self: HistoricalCandleFileStore, candle: Candle, *, exchange: str, market_type: str) -> Path:
        persisted.append(candle)
        return tmp_path / "unexpected.jsonl"

    monkeypatch.setattr(HistoricalCandleFileStore, "save_candle_segment", record_persist)
    runtime = BackendRuntime(settings=live_enabled_settings(data_root=tmp_path), mode=RuntimeMode.LIVE_BITMART)

    runtime._handle_candle_closed(
        CandleClosedEvent(
            candle=candle_for_timeframe("BTCUSDT", Timeframe.FOUR_HOUR, 0),
            source=CandleEventSource.LIVE_STREAM,
        )
    )

    assert persisted == []


def test_publish_historical_candle_uses_replay_provenance() -> None:
    """Historical replay publishers must not rely on the event's live default provenance."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)
    observed: list[CandleClosedEvent] = []
    runtime.event_bus.subscribe(CandleClosedEvent, observed.append)

    runtime._publish_historical_candle(candle_for_open_time("BTCUSDT", 0))

    assert observed[0].source is CandleEventSource.HISTORICAL_REPLAY


def test_one_year_historical_replay_events_produce_zero_live_persistence_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-year replay event volume must not trigger any live cache writes."""

    persisted_count = 0

    def record_persist(self: HistoricalCandleFileStore, candle: Candle, *, exchange: str, market_type: str) -> Path:
        nonlocal persisted_count
        persisted_count += 1
        return tmp_path / "unexpected.jsonl"

    monkeypatch.setattr(HistoricalCandleFileStore, "save_candle_segment", record_persist)
    runtime = BackendRuntime(settings=live_enabled_settings(data_root=tmp_path), mode=RuntimeMode.LIVE_BITMART)
    event = CandleClosedEvent(
        candle=candle_for_open_time("BTCUSDT", 0),
        source=CandleEventSource.HISTORICAL_REPLAY,
    )

    for _ in range(365 * 24 * 60):
        runtime._handle_candle_closed(event)

    assert persisted_count == 0


def test_live_bitmart_health_reports_stream_fields(tmp_path: Path) -> None:
    """Covers RUNTIME-004 live market data health fields."""

    runner = RecordingLiveStreamRunner()
    runtime = BackendRuntime(
        settings=live_enabled_settings(symbol="ETHUSDT", data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: runner.bind(client),
        historical_downloader=FakeLiveCatchupDownloader(symbol="ETHUSDT", latest_completed_open_time_ms=0),
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}

    assert runtime.health().mode is RuntimeMode.LIVE_BITMART
    assert components["market_data_mode"].message == "live_bitmart"
    assert components["stream_enabled"].message == "True"
    assert components["stream_status"].message == "stopped"
    assert components["active_symbol"].message == "ETHUSDT"
    assert components["exchange"].message == "bitmart"
    assert components["market_type"].message == "usdt_m_perpetual"
    assert components["bitmart_stream_client"].status is ComponentStatus.RUNNING


def test_live_startup_discovers_cache_and_fetches_only_missing_closed_candles(tmp_path: Path) -> None:
    cached_request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=120_000,
    )
    HistoricalCandleFileStore(tmp_path).save(cached_request, historical_fixture_candles(count=2))
    runner = RecordingLiveStreamRunner()
    downloader = FakeLiveCatchupDownloader(latest_completed_open_time_ms=240_000)

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: runner.bind(client),
        historical_downloader=downloader,
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}
    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)

    assert downloader.requests == [(120_000, 300_000)]
    assert len(candles) == 5
    assert components["cache_candle_count"].message == "5"
    assert components["cache_last_open_time_ms"].message == "240000"
    assert components["sync_requested_count"].message == "3"
    assert components["sync_loaded_count"].message == "3"
    assert components["sync_inserted_count"].message == "3"
    assert components["sync_deduplicated_count"].message == "0"
    assert runner.started


def test_live_startup_backfills_cache_prefix_when_existing_cache_starts_too_recently(tmp_path: Path) -> None:
    """M31.6.2 startup must not accept a partial cache as the replay baseline."""

    cached_request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=120_000,
        end_time_ms=300_000,
    )
    HistoricalCandleFileStore(tmp_path).save(
        cached_request,
        tuple(candle_for_open_time("BTCUSDT", open_time_ms) for open_time_ms in (120_000, 180_000, 240_000)),
    )
    downloader = FakeLiveCatchupDownloader(latest_completed_open_time_ms=240_000)

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=downloader,
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}
    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)

    assert downloader.requests == [(0, 120_000)]
    assert [candle.open_time_ms for candle in candles] == [0, 60_000, 120_000, 180_000, 240_000]
    assert components["required_history_start_time_ms"].message == "0"
    assert components["required_history_end_time_ms"].message == "300000"
    assert components["replay_start_time_ms"].message == "0"
    assert components["replay_end_time_ms"].message == "300000"


def test_live_startup_repairs_internal_cache_gap_before_replay(tmp_path: Path) -> None:
    """M31.6.2 planned windows include internal gaps, not only tail catch-up."""

    store = HistoricalCandleFileStore(tmp_path)
    store.save(
        HistoricalCandleRequest(
            symbol="BTCUSDT",
            timeframe=Timeframe.ONE_MINUTE,
            start_time_ms=0,
            end_time_ms=120_000,
        ),
        tuple(candle_for_open_time("BTCUSDT", open_time_ms) for open_time_ms in (0, 60_000)),
    )
    store.save(
        HistoricalCandleRequest(
            symbol="BTCUSDT",
            timeframe=Timeframe.ONE_MINUTE,
            start_time_ms=180_000,
            end_time_ms=300_000,
        ),
        tuple(candle_for_open_time("BTCUSDT", open_time_ms) for open_time_ms in (180_000, 240_000)),
    )
    downloader = FakeLiveCatchupDownloader(latest_completed_open_time_ms=240_000)

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=downloader,
    )

    runtime.start()
    candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)

    assert downloader.requests == [(120_000, 180_000)]
    assert [candle.open_time_ms for candle in candles] == [0, 60_000, 120_000, 180_000, 240_000]
    complete_cache_integrity = runtime.health().complete_cache_integrity
    assert complete_cache_integrity is not None
    assert complete_cache_integrity.complete


def test_live_startup_with_complete_cache_only_downloads_new_tail_on_next_startup(tmp_path: Path) -> None:
    """M31.6.2 repeated startup reuses the complete window and avoids full redownload."""

    cached_request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=300_000,
    )
    HistoricalCandleFileStore(tmp_path).save(cached_request, historical_fixture_candles(count=5))
    downloader = FakeLiveCatchupDownloader(latest_completed_open_time_ms=300_000)

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=downloader,
    )

    runtime.start()

    assert downloader.requests == [(300_000, 360_000)]
    assert [candle.open_time_ms for candle in runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)] == [
        0,
        60_000,
        120_000,
        180_000,
        240_000,
        300_000,
    ]


def test_live_startup_with_current_cache_does_not_request_rest_catchup(tmp_path: Path) -> None:
    cached_request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=300_000,
    )
    HistoricalCandleFileStore(tmp_path).save(cached_request, historical_fixture_candles(count=5))
    downloader = FakeLiveCatchupDownloader(latest_completed_open_time_ms=240_000)

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=downloader,
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}

    assert downloader.requests == []
    assert components["sync_requested_count"].message == "0"
    assert components["sync_loaded_count"].message == "0"
    assert components["cache_candle_count"].message == "5"


def test_live_startup_strict_mode_can_repair_incomplete_cached_segment(tmp_path: Path) -> None:
    cached_request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=300_000,
    )
    incomplete_report = HistoricalIntegrityReport(
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=300_000,
        requested_candle_count=5,
        loaded_candle_count=2,
        gap_count=1,
        total_missing_candles=3,
        gaps=(),
        status=HistoricalIntegrityStatus.INCOMPLETE,
        policy=HistoricalIntegrityPolicy.STRICT,
        complete=False,
    )
    HistoricalCandleFileStore(tmp_path).save_result(
        cached_request,
        HistoricalCandleLoadResult(candles=historical_fixture_candles(count=2), integrity_report=incomplete_report),
    )
    downloader = FakeLiveCatchupDownloader(latest_completed_open_time_ms=240_000)

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=downloader,
    )

    runtime.start()

    assert downloader.requests == [(120_000, 300_000)]
    assert len(runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)) == 5


def test_live_startup_bootstraps_when_no_cache_exists(tmp_path: Path) -> None:
    downloader = FakeLiveCatchupDownloader(latest_completed_open_time_ms=120_000)

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path, history_horizon_days=1),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=downloader,
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}

    assert downloader.requests == [(0, 180_000)]
    assert components["sync_loaded_count"].message == "3"
    assert len(runtime.visualization_api.get_candles("BTCUSDT", Timeframe.ONE_MINUTE)) == 3


def test_historical_replay_strict_policy_fails_on_gap() -> None:
    """M31.6.1 STRICT replay rejects exact 1m discontinuities before aggregation."""

    request = gapped_replay_request()
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(request=request),
        historical_loader=FixtureHistoricalLoader(gapped_replay_candles()),
    )

    with pytest.raises(ValueError, match="Strict historical replay rejected discontinuity"):
        runtime.start()

    health = runtime.health()
    assert health.state is RuntimeState.FAILED
    assert health.replay_integrity is not None
    assert health.replay_integrity.gap_count == 1
    assert health.replay_integrity.gaps[0].missing_candle_count == 5


def test_historical_replay_warn_policy_records_gap_and_continues(tmp_path: Path) -> None:
    """M31.6.1 WARN replay resets aggregation and continues after known gaps."""

    request = gapped_replay_request()
    candles = gapped_replay_candles(post_gap_count=8)
    store = HistoricalCandleFileStore(tmp_path)
    store.save_result(
        request,
        HistoricalCandleLoadResult(
            candles=candles,
            integrity_report=inferred_integrity_report(
                request,
                candles,
                integrity_policy=HistoricalIntegrityPolicy.WARN,
            ),
        ),
    )
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(
            request=request,
            data_root=tmp_path,
            integrity_policy=HistoricalIntegrityPolicy.WARN,
        ),
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}
    five_minute_candles = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.FIVE_MINUTE)

    replay_integrity = runtime.health().replay_integrity
    assert replay_integrity is not None
    assert replay_integrity.status is HistoricalIntegrityStatus.DEGRADED
    assert replay_integrity.gap_count == 1
    assert components["replay_gap_count"].message == "1"
    assert components["discarded_aggregation_bucket_count"].message != "0"
    assert all(candle.open_time_ms >= 720_000 for candle in five_minute_candles)


def test_historical_replay_allow_policy_records_gap_and_continues(tmp_path: Path) -> None:
    """M31.6.1 ALLOW replay marks integrity incomplete and continues."""

    request = gapped_replay_request()
    candles = gapped_replay_candles(post_gap_count=8)
    store = HistoricalCandleFileStore(tmp_path)
    store.save_result(
        request,
        HistoricalCandleLoadResult(
            candles=candles,
            integrity_report=inferred_integrity_report(
                request,
                candles,
                integrity_policy=HistoricalIntegrityPolicy.ALLOW,
            ),
        ),
    )
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(
            request=request,
            data_root=tmp_path,
            integrity_policy=HistoricalIntegrityPolicy.ALLOW,
        ),
    )

    runtime.start()

    assert runtime.health().state is RuntimeState.RUNNING
    replay_integrity = runtime.health().replay_integrity
    assert replay_integrity is not None
    assert replay_integrity.status is HistoricalIntegrityStatus.INCOMPLETE


def test_historical_replay_boundary_does_not_emit_cross_gap_higher_timeframe_candle(tmp_path: Path) -> None:
    """M31.6.1 incomplete 5m/15m buckets touching a gap are discarded."""

    request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=720_000,
        end_time_ms=1_860_000,
    )
    candles = tuple(
        candle_for_open_time("BTCUSDT", open_time_ms)
        for open_time_ms in (
            960_000,
            1_020_000,
            1_380_000,
            1_440_000,
            1_500_000,
            1_560_000,
            1_620_000,
            1_680_000,
            1_740_000,
            1_800_000,
        )
    )
    store = HistoricalCandleFileStore(tmp_path)
    store.save_result(
        request,
        HistoricalCandleLoadResult(
            candles=candles,
            integrity_report=inferred_integrity_report(
                request,
                candles,
                integrity_policy=HistoricalIntegrityPolicy.WARN,
            ),
        ),
    )
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(
            request=request,
            data_root=tmp_path,
            integrity_policy=HistoricalIntegrityPolicy.WARN,
        ),
    )

    runtime.start()
    five_minute = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.FIVE_MINUTE)
    fifteen_minute = runtime.visualization_api.get_candles("BTCUSDT", Timeframe.FIFTEEN_MINUTE)

    assert [candle.open_time_ms for candle in five_minute] == [1_500_000]
    assert fifteen_minute == ()


def test_live_warn_policy_repairs_known_cache_gap_before_live_handoff(tmp_path: Path) -> None:
    """M31.6.2 live startup repairs known gaps when REST data is available."""

    request = gapped_replay_request()
    candles = gapped_replay_candles(post_gap_count=8)
    HistoricalCandleFileStore(tmp_path).save_result(
        request,
        HistoricalCandleLoadResult(
            candles=candles,
            integrity_report=inferred_integrity_report(
                request,
                candles,
                integrity_policy=HistoricalIntegrityPolicy.WARN,
            ),
        ),
    )
    runtime = BackendRuntime(
        settings=live_enabled_settings(
            data_root=tmp_path,
            historical_integrity_policy=HistoricalIntegrityPolicy.WARN,
        ),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=FakeLiveCatchupDownloader(latest_completed_open_time_ms=candles[-1].open_time_ms),
    )

    runtime.start()
    components = {component.name: component for component in runtime.health().components}

    assert runtime.health().state is RuntimeState.RUNNING
    assert components["market_data_state"].message in {"live", "connecting_stream"}
    complete_cache_integrity = runtime.health().complete_cache_integrity
    replay_integrity = runtime.health().replay_integrity
    assert complete_cache_integrity is not None
    assert complete_cache_integrity.complete
    assert replay_integrity is not None
    assert replay_integrity.complete


def test_api_health_available_while_live_sync_initializes_in_background(tmp_path: Path) -> None:
    """M31.6 keeps health reachable while long REST catch-up runs."""

    downloader = BlockingLiveCatchupDownloader(latest_completed_open_time_ms=120_000)
    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path, history_horizon_days=1),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=downloader,
    )

    with TestClient(create_app(runtime)) as client:
        assert downloader.entered.wait(timeout=2.0)
        response = client.get("/api/health")
        components = {component["name"]: component for component in response.json()["components"]}

        assert response.status_code == 200
        assert response.json()["state"] == RuntimeState.STARTING.value
        assert components["market_data_state"]["message"] == "synchronizing"
        assert components["sync_start_time_iso"]["message"].endswith("Z")

        downloader.release.set()
        assert wait_for_state(runtime, RuntimeState.RUNNING)


def test_api_health_reports_live_startup_failure(tmp_path: Path) -> None:
    """M31.6 surfaces background initialization failures through health."""

    runtime = BackendRuntime(
        settings=live_enabled_settings(data_root=tmp_path, history_horizon_days=1),
        mode=RuntimeMode.LIVE_BITMART,
        live_stream_runner_factory=lambda client: RecordingLiveStreamRunner().bind(client),
        historical_downloader=FailingLiveCatchupDownloader(latest_completed_open_time_ms=120_000),
    )

    with TestClient(create_app(runtime)) as client:
        assert wait_for_state(runtime, RuntimeState.FAILED)
        response = client.get("/api/health")
        components = {component["name"]: component for component in response.json()["components"]}

        assert response.status_code == 200
        assert response.json()["state"] == RuntimeState.FAILED.value
        assert components["market_data_state"]["message"] == "failed"
        assert "RuntimeError" in components["startup_exception"]["message"]


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


def test_cli_rejects_removed_live_binance_option() -> None:
    """M31.1 removes Binance runtime mode instead of silently falling back."""

    with pytest.raises(SystemExit):
        main(["--live-binance", "--once"])


def test_cli_rejects_invalid_historical_integrity_policy() -> None:
    with pytest.raises(SystemExit):
        main(["--historical", "--historical-integrity-policy", "sometimes", "--once"])


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
    assert "Historical preflight:" in captured.out
    assert "expected_1m_candles=4" in captured.out
    assert "integrity_policy=strict" in captured.out
    assert "range is shorter than 1d" in captured.out
    assert '"mode": "historical"' in captured.out
    assert '"state": "running"' in captured.out


def test_cli_entrypoint_starts_historical_live_once(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers M29 CLI mode selection for historical-live runtime."""

    request = historical_request()
    HistoricalCandleFileStore(tmp_path).save(request, historical_fixture_candles(count=4))
    monkeypatch.setattr(
        runtime_module,
        "BitMartUnavailableLiveStreamRunner",
        lambda client: RecordingLiveStreamRunner().bind(client),
    )

    exit_code = main(
        [
            "--historical-live",
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
    assert '"mode": "historical_live"' in captured.out
    assert '"state": "running"' in captured.out


def test_cli_entrypoint_accepts_live_alias(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal live startup uses cache sync before stream handoff without manual dates."""

    monkeypatch.setattr(
        runtime_module,
        "BitMartHistoricalCandleDownloader",
        lambda: FakeLiveCatchupDownloader(latest_completed_open_time_ms=0),
    )
    monkeypatch.setattr(
        runtime_module,
        "BitMartUnavailableLiveStreamRunner",
        lambda client: RecordingLiveStreamRunner().bind(client),
    )

    exit_code = main(
        [
            "--live",
            "--symbol",
            "BTCUSDT",
            "--timeframe",
            "1m",
            "--historical-integrity-policy",
            "strict",
            "--data-root",
            str(tmp_path),
            "--once",
        ],
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"mode": "live_bitmart"' in captured.out
    assert '"state": "running"' in captured.out


def test_runtime_does_not_duplicate_business_logic() -> None:
    """Covers no-new-trading-logic constraint and TEST-001."""

    runtime_source = Path("backend/app/runtime.py").read_text(encoding="utf-8")

    forbidden_fragments = (
        "Binance",
        "binance",
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
    def __init__(self, messages: tuple[Trade, ...] = ()) -> None:
        self.messages = messages
        self.client: BitMartTradeStreamClient | None = None
        self.started = False
        self.stopped = False

    def bind(self, client: BitMartTradeStreamClient) -> RecordingLiveStreamRunner:
        self.client = client
        return self

    def start(self) -> None:
        self.started = True
        if self.client is None:
            raise RuntimeError("Missing BitMart client")
        for trade in self.messages:
            self.client.publish_trade(trade)

    def stop(self) -> None:
        self.stopped = True


class FakeLiveCatchupDownloader:
    def __init__(self, *, symbol: str = "BTCUSDT", latest_completed_open_time_ms: int) -> None:
        self.symbol = symbol
        self.latest_completed = latest_completed_open_time_ms
        self.requests: list[tuple[int, int]] = []

    def latest_completed_open_time_ms(self, symbol: str) -> int:
        assert symbol == self.symbol
        return self.latest_completed

    def load_result(
        self,
        request: HistoricalCandleRequest,
        *,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> HistoricalCandleLoadResult:
        self.requests.append((request.start_time_ms, request.end_time_ms))
        candles = tuple(
            candle_for_open_time(request.symbol, open_time_ms)
            for open_time_ms in range(request.start_time_ms, request.end_time_ms, 60_000)
        )
        report = HistoricalIntegrityReport.valid(
            ExchangeHistoricalCandleRequest(
                exchange=ExchangeName.BITMART,
                market_type=MarketType.USDT_M_PERPETUAL,
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_time_ms=request.start_time_ms,
                end_time_ms=request.end_time_ms,
                integrity_policy=integrity_policy,
            ),
            requested_candle_count=len(candles),
            loaded_candle_count=len(candles),
        )
        return HistoricalCandleLoadResult(candles=candles, integrity_report=report)


class BlockingLiveCatchupDownloader(FakeLiveCatchupDownloader):
    def __init__(self, *, latest_completed_open_time_ms: int) -> None:
        super().__init__(latest_completed_open_time_ms=latest_completed_open_time_ms)
        self.entered = threading.Event()
        self.release = threading.Event()

    def load_result(
        self,
        request: HistoricalCandleRequest,
        *,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> HistoricalCandleLoadResult:
        self.entered.set()
        assert self.release.wait(timeout=5.0)
        return super().load_result(request, integrity_policy=integrity_policy)


class FailingLiveCatchupDownloader(FakeLiveCatchupDownloader):
    def load_result(
        self,
        request: HistoricalCandleRequest,
        *,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> HistoricalCandleLoadResult:
        raise RuntimeError("simulated catch-up failure")


class FixtureHistoricalLoader:
    def __init__(self, candles: tuple[Candle, ...]) -> None:
        self._candles = candles

    def load(self, request: HistoricalCandleRequest) -> tuple[Candle, ...]:
        return self._candles


def live_enabled_settings(
    symbol: str = "BTCUSDT",
    *,
    data_root: Path | None = None,
    history_horizon_days: int | None = None,
    historical_integrity_policy: HistoricalIntegrityPolicy | None = None,
) -> PlatformSettings:
    settings = load_settings()
    historical_data = settings.historical_data
    market_data_sync = settings.market_data_sync
    if data_root is not None:
        historical_data = historical_data.model_copy(update={"data_root": data_root})
    if historical_integrity_policy is not None:
        historical_data = historical_data.model_copy(update={"integrity_policy": historical_integrity_policy.value})
    if history_horizon_days is not None:
        market_data_sync = market_data_sync.model_copy(update={"history_horizon_days": history_horizon_days})
    return settings.model_copy(
        update={
            "market_data": settings.market_data.model_copy(
                update={
                    "symbols": (symbol,),
                    "live_enabled": True,
                },
            ),
            "historical_data": historical_data,
            "market_data_sync": market_data_sync,
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


def gapped_replay_request() -> HistoricalCandleRequest:
    return HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=960_000,
        end_time_ms=1_860_000,
    )


def gapped_replay_candles(*, post_gap_count: int = 2) -> tuple[Candle, ...]:
    # Fixture shape: 12:16, 12:17, missing 12:18-12:22, then 12:23 onward.
    open_times = [960_000, 1_020_000]
    open_times.extend(1_380_000 + index * 60_000 for index in range(post_gap_count))
    return tuple(candle_for_open_time("BTCUSDT", open_time_ms) for open_time_ms in open_times)


def candle_for_open_time(symbol: str, open_time_ms: int) -> Candle:
    index = open_time_ms // 60_000
    open_price = 100.0 + index
    close = open_price + 1.0
    return Candle(
        symbol=symbol,
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + 60_000,
        open=open_price,
        high=close + 1.0,
        low=open_price - 1.0,
        close=close,
        volume=1.0,
    )


def candle_for_timeframe(symbol: str, timeframe: Timeframe, open_time_ms: int) -> Candle:
    duration_ms = 4 * 60 * 60 * 1000 if timeframe is Timeframe.FOUR_HOUR else 60_000
    candle = candle_for_open_time(symbol, open_time_ms)
    return Candle(
        symbol=candle.symbol,
        timeframe=timeframe,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + duration_ms,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
    )


def wait_for_state(runtime: BackendRuntime, state: RuntimeState, *, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if runtime.state is state:
            return True
        time.sleep(0.01)
    return runtime.state is state


def incomplete_report(
    request: HistoricalCandleRequest,
    *,
    policy: HistoricalIntegrityPolicy,
) -> HistoricalIntegrityReport:
    gap = HistoricalDataGap(
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_open_time_ms=180_000,
        end_open_time_ms=240_000,
        missing_candle_count=1,
        missing_open_times_ms=(180_000,),
        retry_count=3,
        exchange=ExchangeName.BITMART,
        recovery_status=HistoricalGapRecoveryStatus.UNRECOVERABLE,
        detected_at_ms=300_000,
    )
    return HistoricalIntegrityReport.from_gaps(
        ExchangeHistoricalCandleRequest(
            exchange=ExchangeName.BITMART,
            market_type=MarketType.USDT_M_PERPETUAL,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_time_ms=request.start_time_ms,
            end_time_ms=request.end_time_ms,
            integrity_policy=policy,
        ),
        status=(
            HistoricalIntegrityStatus.DEGRADED
            if policy is HistoricalIntegrityPolicy.WARN
            else HistoricalIntegrityStatus.INCOMPLETE
        ),
        gaps=(gap,),
        requested_candle_count=4,
        loaded_candle_count=3,
    )
