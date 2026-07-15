from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.service import create_app
from backend.app import BackendRuntime, RuntimeMode
from backend.config import load_settings
from backend.engines.structure import StructureLabel, StructureSwing, SwingKind
from backend.engines.trend import TrendState, TrendStrength, TrendUpdate
from backend.models import Candle, Timeframe


def test_runtime_api_evaluates_and_reads_cached_daily_aois() -> None:
    runtime = _runtime_with_bullish_leg(Timeframe.DAILY, body_low=100, body_high=101)

    with TestClient(create_app(runtime)) as client:
        evaluated = client.post(
            "/api/aois/evaluate",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1d",
                "sizing_mode": "fixed_ticks",
                "minimum_ticks": 1,
                "maximum_ticks": 1,
                "tick_size": 1,
            },
        )
        listed = client.get("/api/aois", params={"symbol": "BTCUSDT", "timeframe": "1d"})

    assert evaluated.status_code == 200
    assert len(evaluated.json()["areas"]) == 1
    assert listed.status_code == 200
    assert listed.json()["aois"][0]["state"] == "active"
    assert listed.json()["aois"][0]["confirmation_time_ms"] == 4_000
    assert listed.json()["location_gate_eligible"] is True


def test_runtime_api_reports_weekly_daily_aoi_overlap() -> None:
    runtime = _runtime_with_bullish_leg(Timeframe.DAILY, body_low=100, body_high=101)
    _seed_bullish_leg(runtime, Timeframe.WEEKLY, body_low=100.5, body_high=101.5)

    with TestClient(create_app(runtime)) as client:
        daily = client.post(
            "/api/aois/evaluate",
            json=_evaluate_payload("1d"),
        )
        weekly = client.post(
            "/api/aois/evaluate",
            json=_evaluate_payload("1w"),
        )
        overlaps = client.get(
            "/api/aoi-overlaps",
            params={"symbol": "BTCUSDT", "confluence_weight": 0.25},
        )

    assert daily.status_code == 200
    assert weekly.status_code == 200
    assert overlaps.status_code == 200
    assert len(overlaps.json()) == 1
    assert overlaps.json()[0]["intersection_bounds"] == {"lower": 100.5, "upper": 101.0}


def test_runtime_api_evaluates_live_aoi_location() -> None:
    runtime = _runtime_with_bullish_leg(Timeframe.DAILY, body_low=100, body_high=101)

    with TestClient(create_app(runtime)) as client:
        evaluated = client.post(
            "/api/aois/evaluate",
            json=_evaluate_payload("1d"),
        )
        aoi_id = evaluated.json()["areas"][0]["aoi_id"]
        location = client.post(
            "/api/aoi-location",
            json={
                "symbol": "BTCUSDT",
                "aoi_id": aoi_id,
                "proximity_tolerance": 1,
                "maximum_post_reaction_excursion": 3,
            },
        )

    assert location.status_code == 200
    assert location.json()["state"] in {"inside", "reacting"}
    assert location.json()["gate_open"] is True


def test_runtime_api_reads_symbol_level_aoi_location_gate() -> None:
    runtime = _runtime_with_bullish_leg(Timeframe.DAILY, body_low=100, body_high=101)

    with TestClient(create_app(runtime)) as client:
        client.post("/api/aois/evaluate", json=_evaluate_payload("1d"))
        location = client.get("/api/aoi-location", params={"symbol": "BTCUSDT"})

    assert location.status_code == 200
    assert location.json()["eligible"] is True
    assert location.json()["reason_codes"]


def test_runtime_archives_cached_aoi_when_active_leg_changes() -> None:
    runtime = _runtime_with_bullish_leg(Timeframe.DAILY, body_low=100, body_high=101)

    with TestClient(create_app(runtime)) as client:
        first = client.post("/api/aois/evaluate", json=_evaluate_payload("1d"))
        runtime.structure_store.add_swing(_swing(StructureLabel.HL, 91, 30, Timeframe.DAILY))
        runtime.structure_store.add_swing(_swing(StructureLabel.HH, 111, 40, Timeframe.DAILY))
        second = client.post("/api/aois/evaluate", json=_evaluate_payload("1d"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["areas"][0]["state"] == "archived"


def test_runtime_marks_cached_aoi_broken_after_body_close_beyond_boundary() -> None:
    runtime = _runtime_with_bullish_leg(Timeframe.DAILY, body_low=100, body_high=101)

    with TestClient(create_app(runtime)) as client:
        first = client.post("/api/aois/evaluate", json=_evaluate_payload("1d"))
        runtime.candle_store.save(
            Candle(
                symbol="BTCUSDT",
                timeframe=Timeframe.DAILY,
                open_time_ms=4_000,
                close_time_ms=5_000,
                open=98,
                high=101,
                low=97,
                close=99,
                volume=1,
            )
        )
        second = client.post("/api/aois/evaluate", json=_evaluate_payload("1d"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["areas"][0]["state"] == "broken"


def test_runtime_invalidates_cached_aoi_when_trend_changes() -> None:
    runtime = _runtime_with_bullish_leg(Timeframe.DAILY, body_low=100, body_high=101)

    with TestClient(create_app(runtime)) as client:
        first = client.post("/api/aois/evaluate", json=_evaluate_payload("1d"))
        runtime.trend_store.set(_trend(Timeframe.DAILY, TrendState.BEARISH, 31_000))
        runtime.structure_store.add_swing(_swing(StructureLabel.LH, 111, 30, Timeframe.DAILY))
        runtime.structure_store.add_swing(_swing(StructureLabel.LL, 91, 40, Timeframe.DAILY))
        second = client.post("/api/aois/evaluate", json=_evaluate_payload("1d"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["areas"][0]["state"] == "structurally_invalidated"


def _runtime_with_bullish_leg(timeframe: Timeframe, *, body_low: float, body_high: float) -> BackendRuntime:
    settings = load_settings()
    runtime = BackendRuntime(
        settings=settings.model_copy(update={"demo": settings.demo.model_copy(update={"enabled": False})}),
        mode=RuntimeMode.DRY_RUN,
    )
    _seed_bullish_leg(runtime, timeframe, body_low=body_low, body_high=body_high)
    return runtime


def _seed_bullish_leg(
    runtime: BackendRuntime,
    timeframe: Timeframe,
    *,
    body_low: float,
    body_high: float,
) -> None:
    for index in range(1, 4):
        runtime.candle_store.save(
            Candle(
                symbol="BTCUSDT",
                timeframe=timeframe,
                open_time_ms=index * 1_000,
                close_time_ms=(index + 1) * 1_000,
                open=body_low,
                high=body_high,
                low=body_low,
                close=body_high,
                volume=1,
            )
        )
    runtime.structure_store.add_swing(_swing(StructureLabel.HL, 90, 0, timeframe))
    runtime.structure_store.add_swing(_swing(StructureLabel.HH, 110, 20, timeframe))
    runtime.trend_store.set(_trend(timeframe, TrendState.BULLISH, 21_000))


def _evaluate_payload(timeframe: str) -> dict[str, str | float]:
    return {
        "symbol": "BTCUSDT",
        "timeframe": timeframe,
        "sizing_mode": "fixed_ticks",
        "minimum_ticks": 1,
        "maximum_ticks": 1,
        "tick_size": 1,
    }


def _trend(timeframe: Timeframe, state: TrendState, event_time_ms: int) -> TrendUpdate:
    return TrendUpdate(
        symbol="BTCUSDT",
        timeframe=timeframe,
        state=state,
        previous_state=None,
        strength=TrendStrength(confirming_structure_count=2),
        reason="test_precomputed_trend",
        event_time_ms=event_time_ms,
    )


def _swing(
    label: StructureLabel,
    level: float,
    index: int,
    timeframe: Timeframe,
) -> StructureSwing:
    return StructureSwing(
        symbol="BTCUSDT",
        timeframe=timeframe,
        kind=SwingKind.HIGH if label in {StructureLabel.HH, StructureLabel.LH} else SwingKind.LOW,
        label=label,
        level=level,
        candle_open_time_ms=index * 1_000,
        candle_close_time_ms=(index + 1) * 1_000,
    )
