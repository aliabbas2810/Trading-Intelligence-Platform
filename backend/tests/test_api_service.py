from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.service import create_app
from backend.app import BackendRuntime, HistoricalRuntimeConfig, RuntimeMode, RuntimeState
from backend.app.cli import main
from backend.config import PlatformSettings, load_settings
from backend.engines.aoi import (
    ActiveStructureLeg,
    AoiBounds,
    AoiDirection,
    AoiEvaluation,
    AoiRankingMetadata,
    AoiState,
    AoiTimeframe,
    AreaOfInterest,
)
from backend.engines.historical import HistoricalCandleFileStore, HistoricalCandleLoadResult, HistoricalCandleRequest
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
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms


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


def test_historical_mode_returns_fixture_candles_from_api(tmp_path: Path) -> None:
    """Covers M28 historical runtime loading through visualization API stores."""

    request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=240_000,
    )
    HistoricalCandleFileStore(tmp_path).save(
        request,
        (
            Candle("BTCUSDT", Timeframe.ONE_MINUTE, 0, 60_000, 100.0, 102.0, 99.0, 101.0, 1.0),
            Candle("BTCUSDT", Timeframe.ONE_MINUTE, 60_000, 120_000, 101.0, 103.0, 100.0, 102.0, 1.0),
            Candle("BTCUSDT", Timeframe.ONE_MINUTE, 120_000, 180_000, 102.0, 104.0, 101.0, 103.0, 1.0),
            Candle("BTCUSDT", Timeframe.ONE_MINUTE, 180_000, 240_000, 103.0, 105.0, 102.0, 104.0, 1.0),
        ),
    )
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(request=request, data_root=tmp_path),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.get("/api/candles", params={"symbol": "BTCUSDT", "timeframe": "1m"})

    assert response.status_code == 200
    candles = response.json()
    assert len(candles) == 4
    assert candles[0]["open_time_ms"] == 0
    assert candles[-1]["close"] == 104.0


def test_data_readiness_reports_insufficient_higher_timeframes_for_short_history(tmp_path: Path) -> None:
    """Covers M28.1 insufficient historical warm-up diagnostics and TEST-001."""

    request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=120 * 60_000,
    )
    HistoricalCandleFileStore(tmp_path).save(request, make_minute_fixture_candles(count=120))
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(request=request, data_root=tmp_path),
    )

    with TestClient(create_app(runtime)) as client:
        readiness = client.get("/api/data-readiness", params={"symbol": "BTCUSDT"})
        intelligence = client.post(
            "/api/trading-intelligence/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "4h"},
        )

    assert readiness.status_code == 200
    readiness_payload = readiness.json()
    assert readiness_payload["overall_state"] == "INSUFFICIENT_DATA"
    assert readiness_payload["reason"] == "insufficient_historical_range"
    assert readiness_payload["candle_counts_by_timeframe"][-1] == {
        "timeframe": "1m",
        "candle_count": 120,
        "available": True,
    }
    assert {"1w", "1d", "4h"}.issubset(set(readiness_payload["missing_timeframes"]))

    assert intelligence.status_code == 200
    intelligence_payload = intelligence.json()
    assert intelligence_payload["entry_decision"]["state"] == "WAIT"
    assert intelligence_payload["metadata"]["readiness_state"] == "INSUFFICIENT_DATA"
    assert intelligence_payload["readiness"]["reason"] == "insufficient_historical_range"
    evidence_codes = {
        item["code"]
        for item in intelligence_payload["entry_decision"]["evidence"]
    }
    assert "alignment_data_missing" in evidence_codes
    assert "alignment_weak_or_neutral" not in evidence_codes
    assert "aoi_data_missing" in evidence_codes
    assert intelligence_payload["aoi_gate"]["eligible"] is False
    assert "aoi_data_missing" in intelligence_payload["aoi_gate"]["reason_codes"]
    assert intelligence_payload["setup_score"]["metadata"]["aoi_gate_failed"] is True

    checklist_items = {
        item["id"]: item
        for item in intelligence_payload["checklist"]["items"]
    }
    assert checklist_items["aoi.weekly"]["status"] == "MISSING"
    assert checklist_items["aoi.daily"]["status"] == "MISSING"
    assert checklist_items["aoi.weekly_daily_overlap"]["status"] == "MISSING"
    assert checklist_items["aoi.location_gate"]["status"] == "MISSING"


def test_api_exposes_degraded_historical_integrity_in_health_readiness_and_intelligence(tmp_path: Path) -> None:
    request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=240_000,
    )
    report = incomplete_report(request, policy=HistoricalIntegrityPolicy.WARN)
    HistoricalCandleFileStore(tmp_path).save_result(
        request,
        HistoricalCandleLoadResult(
            candles=make_minute_fixture_candles(count=3),
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

    with TestClient(create_app(runtime)) as client:
        health = client.get("/api/health")
        readiness = client.get("/api/data-readiness", params={"symbol": "BTCUSDT"})
        intelligence = client.post(
            "/api/trading-intelligence/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "4h"},
        )

    assert health.status_code == 200
    health_integrity = health.json()["historical_integrity"]
    assert health_integrity["policy"] == "warn"
    assert health_integrity["status"] == "degraded"
    assert health_integrity["complete"] is False
    assert health_integrity["gap_count"] == 1
    assert health_integrity["total_missing_candles"] == 1

    assert readiness.status_code == 200
    readiness_payload = readiness.json()
    assert readiness_payload["overall_state"] == "DEGRADED"
    assert readiness_payload["historical_integrity"]["status"] == "degraded"
    assert "historical_data_gap" in readiness_payload["missing_reasons"]

    assert intelligence.status_code == 200
    intelligence_payload = intelligence.json()
    assert intelligence_payload["metadata"]["historical_integrity_status"] == "degraded"
    assert intelligence_payload["readiness"]["historical_integrity"]["gap_count"] == 1
    checklist_items = {
        item["id"]: item
        for item in intelligence_payload["checklist"]["items"]
    }
    assert checklist_items["data_quality.historical_integrity"]["status"] == "WARNING"


def test_readiness_reports_generated_higher_timeframes_for_long_fixture(tmp_path: Path) -> None:
    """Long historical fixtures report available generated higher timeframe candle data."""

    request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=10_080 * 60_000,
    )
    HistoricalCandleFileStore(tmp_path).save(request, make_minute_fixture_candles(count=10_080))
    runtime = BackendRuntime(
        mode=RuntimeMode.HISTORICAL,
        historical_config=HistoricalRuntimeConfig(request=request, data_root=tmp_path),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.get("/api/data-readiness", params={"symbol": "BTCUSDT"})

    assert response.status_code == 200
    candle_counts = {
        item["timeframe"]: item["candle_count"]
        for item in response.json()["candle_counts_by_timeframe"]
    }
    assert candle_counts["1w"] == 1
    assert candle_counts["1d"] == 7
    assert candle_counts["4h"] == 42
    assert "1w" in response.json()["available_timeframes"]


def test_wait_due_to_weak_alignment_is_distinct_from_insufficient_data() -> None:
    """Complete readiness plus weak alignment remains a market-condition WAIT."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_entry_ready_symbol(runtime, "BTCUSDT")
    seed_required_candles(runtime, "BTCUSDT")
    runtime.alignment_store.set(
        MultiTimeframeTrendResult(
            symbol="BTCUSDT",
            mode=MultiTimeframeMode.VOTING,
            bias=DirectionalBias.NEUTRAL,
            alignment_score=0,
            required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
            present_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
            missing_timeframes=(),
            snapshots=(),
            reason="weak-alignment-test",
        ),
    )

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/trading-intelligence/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "4h"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["entry_decision"]["state"] == "WAIT"
    assert payload["metadata"]["readiness_state"] == "READY"
    assert payload["readiness"]["overall_state"] == "READY"
    assert payload["entry_decision"]["reasons"] == ["alignment_weak_or_neutral"]


def test_startup_and_shutdown_call_runtime_lifecycle_without_network() -> None:
    """Covers RUNTIME-003 and TEST-001 without live exchange networking."""

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
    assert start_response.json()["status"] == "running"
    assert start_response.json()["speed_multiplier"] == 2.0
    assert start_response.json()["processed_events"] == 1
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"
    assert pause_response.json()["paused"]
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "running"
    assert resume_response.json()["processed_events"] == 1
    assert step_response.status_code == 200
    assert step_response.json()["status"] == "running"
    assert step_response.json()["processed_events"] == 2
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopped"
    assert stop_response.json()["stopped"]


def test_replay_api_supports_demo_candle_source() -> None:
    """Covers FR-801 candle replay source controls and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/replay/start", json={"source_type": "candles", "start_index": 4})

    assert response.status_code == 200
    assert response.json()["source_type"] == "candles"
    assert response.json()["status"] == "running"
    assert response.json()["processed_events"] == 5
    assert response.json()["total_events"] == 12


def test_demo_candle_replay_keeps_full_chart_data_loaded() -> None:
    """TradingView-style replay must not replace the stored chart dataset."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        before_response = client.get(
            "/api/candles",
            params={"symbol": "BTCUSDT", "timeframe": "1m"},
        )
        start_response = client.post("/api/replay/start", json={"source_type": "candles"})
        candles_response = client.get(
            "/api/candles",
            params={"symbol": "BTCUSDT", "timeframe": "1m"},
        )
        step_response = client.post("/api/replay/step")
        updated_candles_response = client.get(
            "/api/candles",
            params={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert start_response.status_code == 200
    assert start_response.json()["processed_events"] == 1
    assert before_response.status_code == 200
    assert candles_response.status_code == 200
    assert len(before_response.json()) == 90
    assert len(candles_response.json()) == 90
    assert step_response.status_code == 200
    assert step_response.json()["processed_events"] == 2
    assert updated_candles_response.status_code == 200
    assert len(updated_candles_response.json()) == 90


def test_chart_replay_api_does_not_publish_trade_events_to_candle_pipeline() -> None:
    """Chart replay exposes a cursor and leaves the event replay engine separate."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        before_count = len(runtime.candle_store.list("BTCUSDT", Timeframe.ONE_MINUTE))
        client.post("/api/replay/start", json={"source_type": "trades"})
        client.post("/api/replay/step")
        after_count = len(runtime.candle_store.list("BTCUSDT", Timeframe.ONE_MINUTE))

    assert before_count == 90
    assert after_count == 90
    assert replay_one_minute_candles(runtime) == ()


def test_replay_start_after_pause_restarts_cursor_without_clearing_chart_data() -> None:
    """Regression: repeated chart replay sessions must not trigger LateTradeError."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        first_start = client.post("/api/replay/start", json={"source_type": "trades"})
        pause_response = client.post("/api/replay/pause")
        candles_before_restart = client.get(
            "/api/candles",
            params={"symbol": "BTCUSDT", "timeframe": "1m"},
        )
        restarted = client.post("/api/replay/start", json={"source_type": "trades"})
        step_response = client.post("/api/replay/step")
        candles_after_restart = client.get(
            "/api/candles",
            params={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert first_start.status_code == 200
    assert first_start.json()["status"] == "running"
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"
    assert restarted.status_code == 200
    assert restarted.json()["status"] == "running"
    assert restarted.json()["processed_events"] == 1
    assert restarted.json()["current_timestamp_ms"] == 2_000_000_000_000
    assert step_response.status_code == 200
    assert candles_before_restart.status_code == 200
    assert candles_after_restart.status_code == 200
    assert len(candles_before_restart.json()) == 90
    assert len(candles_after_restart.json()) == 90
    assert replay_one_minute_candles(runtime) == ()


def test_replay_start_after_stop_restarts_cursor_without_clearing_chart_data() -> None:
    """Regression: stopped chart replay can restart from the first cursor position."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        first_start = client.post("/api/replay/start", json={"source_type": "trades"})
        first_step = client.post("/api/replay/step")
        stop_response = client.post("/api/replay/stop")
        restarted = client.post("/api/replay/start", json={"source_type": "trades"})
        restarted_step = client.post("/api/replay/step")

    assert first_start.status_code == 200
    assert first_step.status_code == 200
    assert stop_response.status_code == 200
    assert restarted.status_code == 200
    assert restarted.json()["status"] == "running"
    assert restarted.json()["processed_events"] == 1
    assert restarted_step.status_code == 200
    assert len(runtime.candle_store.list("BTCUSDT", Timeframe.ONE_MINUTE)) == 90
    assert replay_one_minute_candles(runtime) == ()


def test_candle_replay_step_stop_start_sequence_restores_full_chart_view() -> None:
    """Stop/Start should move the replay cursor without mutating full chart data."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        first_start = client.post("/api/replay/start", json={"source_type": "candles"})
        first_step = client.post("/api/replay/step")
        stop_response = client.post("/api/replay/stop")
        restarted = client.post("/api/replay/start", json={"source_type": "candles"})
        candles_response = client.get(
            "/api/candles",
            params={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert first_start.status_code == 200
    assert first_start.json()["status"] == "running"
    assert first_step.status_code == 200
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopped"
    assert restarted.status_code == 200
    assert restarted.json()["status"] == "running"
    assert restarted.json()["processed_events"] == 1
    assert candles_response.status_code == 200
    candles = candles_response.json()
    assert len(candles) == 90
    assert candles[0]["open_time_ms"] == 1_735_689_600_000


def test_scanner_endpoint_returns_ranked_candidates() -> None:
    """Covers FR-901, FR-902, FR-903, RUNTIME-004, and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_scanner_symbol(runtime, "ETHUSDT", DirectionalBias.BULLISH, 2, strength=1)
    seed_scanner_symbol(runtime, "BTCUSDT", DirectionalBias.BULLISH, 3, strength=4)

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/scanner/run",
            json={"symbols": ["ETHUSDT", "BTCUSDT"], "timeframe": "4h"},
        )
        status_response = client.get("/api/scanner/status")

    assert response.status_code == 200
    payload = response.json()
    assert [candidate["symbol"] for candidate in payload["candidates"]] == ["BTCUSDT", "ETHUSDT"]
    assert payload["total_symbols"] == 2
    assert status_response.status_code == 200
    assert status_response.json()["total_symbols"] == 2


def test_scanner_endpoint_filters_by_bias_score_and_limit() -> None:
    """Covers FR-904, FR-905, and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_scanner_symbol(runtime, "BTCUSDT", DirectionalBias.BULLISH, 3, strength=4)
    seed_scanner_symbol(runtime, "ETHUSDT", DirectionalBias.BEARISH, 3, strength=5)
    seed_scanner_symbol(runtime, "SOLUSDT", DirectionalBias.BULLISH, 1, strength=0)
    seed_scanner_symbol(runtime, "ADAUSDT", DirectionalBias.BULLISH, 2, strength=1)

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/scanner/run",
            json={
                "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"],
                "bias": "bullish",
                "minimum_alignment_score": 2,
                "minimum_setup_score": 25.0,
                "limit": 1,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert [candidate["symbol"] for candidate in payload["candidates"]] == ["BTCUSDT"]
    excluded = {result["symbol"]: result["excluded_reasons"] for result in payload["results"]}
    assert excluded["ETHUSDT"] == ["bias_filter"]
    assert excluded["SOLUSDT"] == ["alignment_filter", "score_filter"]


def test_scanner_endpoint_handles_missing_data_cleanly() -> None:
    """Covers missing data handling for FR-901 and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/scanner/run", json={"symbols": ["MISSINGUSDT"], "bias": "any"})

    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["symbol"] == "MISSINGUSDT"
    assert candidate["bias"] == "neutral"
    assert candidate["score"] == 0.0
    assert candidate["reasons"] == ["insufficient_data"]


def test_ai_decision_endpoint_returns_structured_decision() -> None:
    """Covers FR-1001 through FR-1006, RUNTIME-004, and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_scanner_symbol(runtime, "BTCUSDT", DirectionalBias.BULLISH, 3, strength=4)

    with TestClient(create_app(runtime)) as client:
        scanner_response = client.post(
            "/api/scanner/run",
            json={"symbols": ["BTCUSDT"], "timeframe": "4h"},
        )
        response = client.post(
            "/api/ai/decision",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "4h",
                "entry_signal": "pullback-confirmation-placeholder",
                "risk_reward": "2R-placeholder",
            },
        )

    assert scanner_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "BTCUSDT"
    assert payload["recommendation"] == "consider_long"
    assert payload["provider"] == "rule_based_mock"
    assert 0.0 <= payload["confidence"] <= 1.0
    assert payload["risk_assessment"]["risks"]
    assert {reason["category"] for reason in payload["reasons"]} == {"alignment", "scanner", "trend"}


def test_ai_decision_endpoint_handles_missing_data_cleanly() -> None:
    """Covers missing data handling for FR-1001 through FR-1005 and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/ai/decision",
            json={"symbol": "MISSINGUSDT", "timeframe": "4h"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommendation"] == "avoid"
    assert payload["confidence"] == 0.1
    assert payload["provider"] == "rule_based_mock"
    assert payload["risk_assessment"]["severity"] == "high"
    assert payload["reasons"][0]["category"] == "missing_data"


def test_entry_evaluate_endpoint_returns_decision_trace() -> None:
    """Covers ENTRY-001 through ENTRY-006 and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        response = client.post("/api/entry/evaluate", json={"symbol": "BTCUSDT"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "ENTRY_READY"
    assert payload["direction"] == "LONG"
    assert payload["trigger_timeframe"] == "1m"
    assert "one_minute_trigger" in payload["reasons"]
    assert {item["code"] for item in payload["evidence"]} >= {
        "higher_timeframes_aligned",
        "one_minute_trigger",
    }
    assert payload["evidence"][0]["category"] == "alignment"
    assert payload["metadata"]["alignment_score"] == 3


def test_risk_evaluate_endpoint_returns_risk_plan() -> None:
    """Covers RISK-001 through RISK-006 and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_entry_ready_symbol(runtime, "BTCUSDT")

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/risk/evaluate",
            json={"symbol": "BTCUSDT", "minimum_risk_reward": 2.0},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["direction"] == "LONG"
    assert payload["state"] == "VALID"
    assert payload["entry_price"] == 105.0
    assert payload["stop_loss"] == 95.0
    assert payload["take_profit"] == 125.0
    assert payload["risk_reward_ratio"] == 2.0
    assert {item["code"] for item in payload["evidence"]} >= {
        "entry_price_from_latest_close",
        "stop_from_structure_level",
        "risk_reward_calculated",
    }


def test_checklist_evaluate_endpoint_returns_checklist_result() -> None:
    """Covers CHECKLIST-001 through CHECKLIST-006 and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_entry_ready_symbol(runtime, "BTCUSDT")

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/checklist/evaluate",
            json={"symbol": "BTCUSDT", "minimum_risk_reward": 2.0},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "BTCUSDT"
    assert payload["overall_status"] == "PASS"
    assert payload["pass_count"] > 0
    assert payload["fail_count"] == 0
    assert {item["category"] for item in payload["items"]} >= {
        "TREND_ALIGNMENT",
        "AOI_LOCATION",
        "STRUCTURE_CONFIRMATION",
        "ENTRY_CONFIRMATION",
        "RISK_VALIDATION",
    }
    assert "PASS:" in payload["summary"]


def test_setup_score_evaluate_endpoint_returns_score() -> None:
    """Covers SCORE-001 through SCORE-006 and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_entry_ready_symbol(runtime, "BTCUSDT")

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/setup-score/evaluate",
            json={"symbol": "BTCUSDT", "minimum_risk_reward": 2.0},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "BTCUSDT"
    assert payload["grade"] in {"A", "B"}
    assert payload["percentage"] >= 70.0
    assert {component["name"] for component in payload["components"]} == {
        "trend_alignment",
        "aoi_location_gate",
        "entry_confirmation",
        "risk_validity",
        "checklist_health",
    }
    assert payload["metadata"]["entry_state"] == "ENTRY_READY"


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

    source = "\n".join(
        (
            Path("backend/api/service.py").read_text(encoding="utf-8"),
            Path("backend/api/ai.py").read_text(encoding="utf-8"),
            Path("backend/api/entry.py").read_text(encoding="utf-8"),
            Path("backend/api/risk.py").read_text(encoding="utf-8"),
            Path("backend/api/checklist.py").read_text(encoding="utf-8"),
            Path("backend/api/scoring.py").read_text(encoding="utf-8"),
            Path("backend/api/trading_intelligence.py").read_text(encoding="utf-8"),
            Path("backend/api/readiness.py").read_text(encoding="utf-8"),
        ),
    )

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


def replay_one_minute_candles(runtime: BackendRuntime) -> tuple[Candle, ...]:
    return tuple(
        candle
        for candle in runtime.candle_store.list("BTCUSDT", Timeframe.ONE_MINUTE)
        if 1_999_999_980_000 <= candle.open_time_ms < 2_000_000_060_000
    )


def seed_scanner_symbol(
    runtime: BackendRuntime,
    symbol: str,
    bias: DirectionalBias,
    alignment_score: int,
    *,
    strength: int,
) -> None:
    trend_state = trend_state_for_bias(bias)
    trend = TrendUpdate(
        symbol=symbol,
        timeframe=Timeframe.FOUR_HOUR,
        state=trend_state,
        previous_state=None,
        strength=TrendStrength(confirming_structure_count=strength),
        reason="scanner-test",
        event_time_ms=120_000,
    )
    snapshot = TimeframeTrendSnapshot(
        symbol=symbol,
        timeframe=Timeframe.FOUR_HOUR,
        state=trend_state,
        strength=trend.strength,
        event_time_ms=trend.event_time_ms,
    )
    alignment = MultiTimeframeTrendResult(
        symbol=symbol,
        mode=MultiTimeframeMode.VOTING,
        bias=bias,
        alignment_score=alignment_score,
        required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
        present_timeframes=(Timeframe.FOUR_HOUR,),
        missing_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY),
        snapshots=(snapshot,),
        reason="scanner-test",
    )
    runtime.trend_store.set(trend)
    runtime.alignment_store.set(alignment)
    runtime.structure_store.add_swing(
        StructureSwing(
            symbol=symbol,
            timeframe=Timeframe.FOUR_HOUR,
            kind=SwingKind.HIGH,
            label=StructureLabel.HH,
            level=120.0,
            candle_open_time_ms=0,
            candle_close_time_ms=60_000,
        ),
    )
    runtime.structure_store.add_break_of_structure(
        BreakOfStructure(
            symbol=symbol,
            timeframe=Timeframe.FOUR_HOUR,
            direction=BreakDirection.BULLISH if bias is not DirectionalBias.BEARISH else BreakDirection.BEARISH,
            broken_label=StructureLabel.HH,
            broken_level=120.0,
            candle_close=125.0,
            candle_open_time_ms=60_000,
            candle_close_time_ms=120_000,
        ),
    )
    runtime.candle_store.save(
        Candle(
            symbol=symbol,
            timeframe=Timeframe.FOUR_HOUR,
            open_time_ms=0,
            close_time_ms=60_000,
            open=100.0,
            high=130.0,
            low=90.0,
            close=125.0,
            volume=10.0,
        ),
    )


def seed_entry_ready_symbol(runtime: BackendRuntime, symbol: str) -> None:
    trend_updates = tuple(
        TrendUpdate(
            symbol=symbol,
            timeframe=timeframe,
            state=TrendState.BULLISH,
            previous_state=None,
            strength=TrendStrength(confirming_structure_count=3),
            reason="entry-ready-test",
            event_time_ms=120_000,
        )
        for timeframe in (
            Timeframe.WEEKLY,
            Timeframe.DAILY,
            Timeframe.FOUR_HOUR,
            Timeframe.TWO_HOUR,
            Timeframe.ONE_HOUR,
            Timeframe.THIRTY_MINUTE,
        )
    )
    for update in trend_updates:
        runtime.trend_store.set(update)

    runtime.alignment_store.set(
        MultiTimeframeTrendResult(
            symbol=symbol,
            mode=MultiTimeframeMode.VOTING,
            bias=DirectionalBias.BULLISH,
            alignment_score=3,
            required_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
            present_timeframes=(Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR),
            missing_timeframes=(),
            snapshots=tuple(
                TimeframeTrendSnapshot(
                    symbol=update.symbol,
                    timeframe=update.timeframe,
                    state=update.state,
                    strength=update.strength,
                    event_time_ms=update.event_time_ms,
                )
                for update in trend_updates
                if update.timeframe in {Timeframe.WEEKLY, Timeframe.DAILY, Timeframe.FOUR_HOUR}
            ),
            reason="entry-ready-test",
        ),
    )

    for timeframe in (Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE, Timeframe.ONE_MINUTE):
        runtime.structure_store.add_swing(
            StructureSwing(
                symbol=symbol,
                timeframe=timeframe,
                kind=SwingKind.HIGH,
                label=StructureLabel.HH,
                level=115.0,
                candle_open_time_ms=0,
                candle_close_time_ms=60_000,
            ),
        )
        runtime.structure_store.add_swing(
            StructureSwing(
                symbol=symbol,
                timeframe=timeframe,
                kind=SwingKind.LOW,
                label=StructureLabel.HL,
                level=95.0,
                candle_open_time_ms=60_000,
                candle_close_time_ms=120_000,
            ),
        )
        runtime.structure_store.add_break_of_structure(
            BreakOfStructure(
                symbol=symbol,
                timeframe=timeframe,
                direction=BreakDirection.BULLISH,
                broken_label=StructureLabel.HH,
                broken_level=115.0,
                candle_close=116.0,
                candle_open_time_ms=120_000,
                candle_close_time_ms=180_000,
            ),
        )

    runtime.candle_store.save(
        Candle(
            symbol=symbol,
            timeframe=Timeframe.ONE_MINUTE,
            open_time_ms=180_000,
            close_time_ms=240_000,
            open=104.0,
            high=106.0,
            low=103.0,
            close=105.0,
            volume=1.0,
        ),
    )
    seed_test_aois(runtime, symbol)


def seed_test_aois(runtime: BackendRuntime, symbol: str) -> None:
    for timeframe in (AoiTimeframe.WEEKLY, AoiTimeframe.DAILY):
        domain_timeframe = timeframe.to_timeframe()
        candle = Candle(
            symbol=symbol,
            timeframe=domain_timeframe,
            open_time_ms=0,
            close_time_ms=timeframe_duration_ms(domain_timeframe),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1.0,
        )
        runtime.candle_store.save(candle)
        start = StructureSwing(
            symbol=symbol,
            timeframe=domain_timeframe,
            kind=SwingKind.LOW,
            label=StructureLabel.HL,
            level=95.0,
            candle_open_time_ms=0,
            candle_close_time_ms=60_000,
        )
        end = StructureSwing(
            symbol=symbol,
            timeframe=domain_timeframe,
            kind=SwingKind.HIGH,
            label=StructureLabel.HH,
            level=115.0,
            candle_open_time_ms=60_000,
            candle_close_time_ms=120_000,
        )
        leg = ActiveStructureLeg(
            symbol=symbol,
            timeframe=timeframe,
            trend_state=TrendState.BULLISH,
            start_swing=start,
            end_swing=end,
            leg_id=f"{symbol}:{timeframe.value}:test-leg",
            trend_id=f"{symbol}:{timeframe.value}:test-trend",
        )
        area = AreaOfInterest(
            aoi_id=f"{symbol}:{timeframe.value}:test-aoi",
            symbol=symbol,
            timeframe=timeframe,
            direction=AoiDirection.SUPPORT,
            bounds=AoiBounds(95.0, 115.0),
            state=AoiState.ACTIVE,
            origin_structure_leg_id=leg.leg_id,
            origin_trend_id=leg.trend_id,
            origin_timeframe=timeframe,
            contributing_candle_timestamps=(0, 60_000, 120_000),
            first_touch_time_ms=0,
            confirmation_time_ms=120_000,
            touch_count=3,
            close_count=1,
            reaction_count=1,
            ranking=AoiRankingMetadata(
                score=10.0,
                body_close_count=1,
                body_touch_count=3,
                reaction_count=1,
                recency_time_ms=120_000,
                normalized_width=0.1,
            ),
            state_changed_time_ms=120_000,
        )
        runtime._aoi_evaluations[(symbol, timeframe)] = AoiEvaluation(leg=leg, areas=(area,))


def seed_required_candles(runtime: BackendRuntime, symbol: str) -> None:
    for timeframe in (
        Timeframe.WEEKLY,
        Timeframe.DAILY,
        Timeframe.FOUR_HOUR,
        Timeframe.TWO_HOUR,
        Timeframe.ONE_HOUR,
        Timeframe.THIRTY_MINUTE,
        Timeframe.FIFTEEN_MINUTE,
        Timeframe.FIVE_MINUTE,
    ):
        duration_ms = timeframe_duration_ms(timeframe)
        if any(candle.open_time_ms == 0 for candle in runtime.candle_store.list(symbol, timeframe)):
            continue
        runtime.candle_store.save(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time_ms=0,
                close_time_ms=duration_ms,
                open=100.0,
                high=110.0,
                low=95.0,
                close=105.0,
                volume=1.0,
            ),
        )


def make_minute_fixture_candles(*, count: int) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    close = 100.0
    for index in range(count):
        open_price = close
        close = open_price + (1.0 if index % 2 == 0 else -0.25)
        open_time_ms = index * 60_000
        candles.append(
            Candle(
                symbol="BTCUSDT",
                timeframe=Timeframe.ONE_MINUTE,
                open_time_ms=open_time_ms,
                close_time_ms=open_time_ms + 60_000,
                open=open_price,
                high=max(open_price, close) + 1.0,
                low=min(open_price, close) - 1.0,
                close=close,
                volume=1.0,
            ),
        )
    return tuple(candles)


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


def trend_state_for_bias(bias: DirectionalBias) -> TrendState:
    if bias is DirectionalBias.BULLISH:
        return TrendState.BULLISH
    if bias is DirectionalBias.BEARISH:
        return TrendState.BEARISH
    return TrendState.TRANSITION


def demo_disabled_settings() -> PlatformSettings:
    settings = load_settings()
    return settings.model_copy(
        update={
            "demo": settings.demo.model_copy(update={"enabled": False}),
        },
    )
