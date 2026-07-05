from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import (
    BackendRuntime,
    ComponentStatus,
    RuntimeAlreadyStartedError,
    RuntimeMode,
    RuntimeState,
)
from backend.app.cli import main
from backend.models import Timeframe, Trade


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


def test_runtime_wires_trade_events_into_existing_candle_pipeline() -> None:
    """Covers RUNTIME-002 integration wiring without duplicating candle logic."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)
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
