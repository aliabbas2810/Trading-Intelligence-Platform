from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.service import create_app
from backend.app import BackendRuntime, RuntimeMode, RuntimeState
from backend.app.cli import main
from backend.config import PlatformSettings, load_settings
from backend.engines.structure import (
    BreakDirection,
    BreakOfStructure,
    StructureLabel,
    StructureSwing,
    SwingKind,
)
from backend.engines.trend import (
    DirectionalBias,
    MultiTimeframeMode,
    MultiTimeframeTrendResult,
    TimeframeTrendSnapshot,
    TrendState,
    TrendStrength,
    TrendUpdate,
)
from backend.models import Candle, Timeframe


class RecordingRuntime(BackendRuntime):
    def __init__(self) -> None:
        super().__init__(mode=RuntimeMode.DRY_RUN)
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        super().start()

    def stop(self) -> None:
        self.stop_calls += 1
        super().stop()


def make_candle() -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=0,
        close_time_ms=60_000,
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
        volume=2.0,
    )


def test_app_factory_creates_fastapi_app() -> None:
    """Covers RUNTIME-001 and TEST-001."""

    app = create_app(BackendRuntime(mode=RuntimeMode.DRY_RUN))

    assert app.title == "Trading Intelligence Platform API"


def test_health_endpoint_returns_runtime_status() -> None:
    """Covers RUNTIME-003, RUNTIME-004, and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "running"
    assert payload["mode"] == "dry_run"
    assert any(component["name"] == "visualization_api" for component in payload["components"])


def test_candles_endpoint_returns_stored_candles() -> None:
    """Covers FR-601 and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    runtime.candle_store.save(make_candle())

    with TestClient(create_app(runtime)) as client:
        response = client.get("/api/candles", params={"symbol": "BTCUSDT", "timeframe": "1m"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "open_time_ms": 0,
            "close_time_ms": 60_000,
            "open": 100.0,
            "high": 110.0,
            "low": 95.0,
            "close": 105.0,
            "volume": 2.0,
        },
    ]


def test_structure_trend_and_alignment_endpoints_use_read_boundaries() -> None:
    """Covers FR-602, FR-603, FR-604, FR-605, and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    swing = StructureSwing(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        kind=SwingKind.HIGH,
        label=StructureLabel.HH,
        level=120.0,
        candle_open_time_ms=0,
        candle_close_time_ms=60_000,
    )
    bos = BreakOfStructure(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        direction=BreakDirection.BULLISH,
        broken_label=StructureLabel.HH,
        broken_level=120.0,
        candle_close=125.0,
        candle_open_time_ms=60_000,
        candle_close_time_ms=120_000,
    )
    trend = TrendUpdate(
        symbol="BTCUSDT",
        timeframe=Timeframe.FOUR_HOUR,
        state=TrendState.BULLISH,
        previous_state=None,
        strength=TrendStrength(confirming_structure_count=3),
        reason="test",
        event_time_ms=120_000,
    )
    alignment = MultiTimeframeTrendResult(
        symbol="BTCUSDT",
        mode=MultiTimeframeMode.VOTING,
        bias=DirectionalBias.BULLISH,
        alignment_score=2,
        required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        present_timeframes=(Timeframe.DAILY, Timeframe.FOUR_HOUR),
        missing_timeframes=(Timeframe.WEEKLY,),
        snapshots=(
            TimeframeTrendSnapshot(
                symbol="BTCUSDT",
                timeframe=Timeframe.FOUR_HOUR,
                state=TrendState.BULLISH,
                strength=TrendStrength(confirming_structure_count=3),
                event_time_ms=120_000,
            ),
        ),
        reason="test",
    )
    runtime.structure_store.add_swing(swing)
    runtime.structure_store.add_break_of_structure(bos)
    runtime.trend_store.set(trend)
    runtime.alignment_store.set(alignment)

    with TestClient(create_app(runtime)) as client:
        structure_response = client.get(
            "/api/market-structure",
            params={"symbol": "BTCUSDT", "timeframe": "4h"},
        )
        trend_response = client.get(
            "/api/trend-state",
            params={"symbol": "BTCUSDT", "timeframe": "4h"},
        )
        alignment_response = client.get(
            "/api/multi-timeframe-alignment",
            params={"symbol": "BTCUSDT"},
        )

    assert structure_response.status_code == 200
    assert structure_response.json()["swings"][0]["label"] == "HH"
    assert structure_response.json()["breaks_of_structure"][0]["direction"] == "bullish"
    assert trend_response.status_code == 200
    assert trend_response.json()["update"]["state"] == "bullish"
    assert alignment_response.status_code == 200
    assert alignment_response.json()["bias"] == "bullish"


def test_dry_run_demo_mode_returns_non_empty_visualization_api_responses() -> None:
    """Covers RUNTIME-005, FR-601 through FR-605, and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)
    timeframes = ("1w", "1d", "4h", "2h", "1h", "30m", "15m", "5m", "1m")

    with TestClient(create_app(runtime)) as client:
        responses = {
            timeframe: (
                client.get("/api/candles", params={"symbol": "BTCUSDT", "timeframe": timeframe}),
                client.get(
                    "/api/market-structure",
                    params={"symbol": "BTCUSDT", "timeframe": timeframe},
                ),
                client.get("/api/trend-state", params={"symbol": "BTCUSDT", "timeframe": timeframe}),
            )
            for timeframe in timeframes
        }
        alignment_response = client.get("/api/multi-timeframe-alignment", params={"symbol": "BTCUSDT"})

    for candles_response, structure_response, trend_response in responses.values():
        assert candles_response.status_code == 200
        assert structure_response.status_code == 200
        assert trend_response.status_code == 200
        assert len(candles_response.json()) > 0
        assert {item["label"] for item in structure_response.json()["swings"]} == {"HH", "HL", "LH", "LL"}
        assert len(structure_response.json()["breaks_of_structure"]) > 0
        assert trend_response.json()["update"]["state"] == "bullish"

    assert alignment_response.status_code == 200
    assert alignment_response.json()["alignment_score"] == 3
    assert alignment_response.json()["bias"] == "bullish"


def test_startup_and_shutdown_call_runtime_lifecycle_without_network() -> None:
    """Covers RUNTIME-003 and TEST-001 without live Binance networking."""

    runtime = RecordingRuntime()

    with TestClient(create_app(runtime)):
        assert runtime.start_calls == 1
        assert_runtime_state(runtime, RuntimeState.RUNNING)

    assert runtime.stop_calls == 1
    assert_runtime_state(runtime, RuntimeState.STOPPED)


def test_replay_api_start_pause_resume_step_stop_and_status() -> None:
    """Covers FR-801 through FR-805, RUNTIME-004, and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        status_response = client.get("/api/replay/status")
        start_response = client.post(
            "/api/replay/start",
            json={"source_type": "trades", "speed_multiplier": 2.0},
        )
        pause_response = client.post("/api/replay/pause")
        resume_response = client.post("/api/replay/resume")
        step_response = client.post("/api/replay/step")
        stop_response = client.post("/api/replay/stop")

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "ready"
    assert start_response.status_code == 200
    assert start_response.json()["source_type"] == "trades"
    assert start_response.json()["speed_multiplier"] == 2.0
    assert start_response.json()["processed_events"] == 1
    assert pause_response.status_code == 200
    assert pause_response.json()["paused"]
    assert resume_response.status_code == 200
    assert resume_response.json()["processed_events"] == 2
    assert step_response.status_code == 200
    assert step_response.json()["status"] == "completed"
    assert stop_response.status_code == 200
    assert stop_response.json()["stopped"]


def test_replay_api_supports_demo_candle_source() -> None:
    """Covers FR-801 candle replay source controls and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/replay/start", json={"source_type": "candles"})

    assert response.status_code == 200
    assert response.json()["source_type"] == "candles"
    assert response.json()["total_events"] == 3


def test_replay_trade_events_reach_existing_candle_pipeline() -> None:
    """Covers FR-806: replay reuses the live downstream event path."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        client.post("/api/replay/start", json={"source_type": "trades"})
        client.post("/api/replay/step")

    replay_candles = tuple(
        candle
        for candle in runtime.candle_store.list("BTCUSDT", Timeframe.ONE_MINUTE)
        if 1_999_999_980_000 <= candle.open_time_ms < 2_000_000_060_000
    )
    assert len(replay_candles) == 1
    assert replay_candles[0].open == 50_000.0
    assert replay_candles[0].close == 50_000.0


def test_cli_can_run_api_mode_without_starting_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers local API CLI wiring for RUNTIME-001 and TEST-001."""

    calls: list[tuple[str, int]] = []

    def fake_run(_app: object, *, host: str, port: int) -> None:
        calls.append((host, port))

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)

    exit_code = main(["--api", "--dry-run", "--host", "0.0.0.0", "--port", "9000"])

    assert exit_code == 0
    assert calls == [("0.0.0.0", 9000)]


def test_api_layer_does_not_recompute_analysis_logic() -> None:
    """Covers API transport-only constraint and TEST-001."""

    source = Path("backend/api/service.py").read_text(encoding="utf-8")

    forbidden_fragments = (
        "MarketStructureEngine",
        "TrendEngine",
        "ScannerEngine",
        "AiDecisionEngine",
        ".add_candle(",
        ".add_event(",
        "score_candidate",
        "body_high",
        "body_low",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source


def assert_runtime_state(runtime: BackendRuntime, expected: RuntimeState) -> None:
    assert runtime.state is expected


def demo_disabled_settings() -> PlatformSettings:
    settings = load_settings()
    return settings.model_copy(
        update={
            "demo": settings.demo.model_copy(update={"enabled": False}),
        },
    )
