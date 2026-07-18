from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.service import create_app
from backend.app import BackendRuntime, RuntimeMode
from backend.models import Timeframe


SUPPORTED_TIMEFRAMES = (
    "1w",
    "1d",
    "4h",
    "2h",
    "1h",
    "30m",
    "15m",
    "5m",
    "1m",
)


def test_demo_btcusdt_has_complete_read_models_for_all_supported_timeframes() -> None:
    """v0.3.1 correctness net for FR-601 through FR-605 and TEST-001."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        for timeframe in SUPPORTED_TIMEFRAMES:
            candles = client.get(
                "/api/candles",
                params={"symbol": "BTCUSDT", "timeframe": timeframe},
            )
            structure = client.get(
                "/api/market-structure",
                params={"symbol": "BTCUSDT", "timeframe": timeframe},
            )
            trend = client.get(
                "/api/trend-state",
                params={"symbol": "BTCUSDT", "timeframe": timeframe},
            )

            assert candles.status_code == 200
            assert structure.status_code == 200
            assert trend.status_code == 200
            assert candles.json(), timeframe
            swings = structure.json()["swings"]
            assert swings, timeframe
            assert {item["source_timeframe"] for item in swings} <= {"1w", "1d", "4h"}
            assert len(swings) <= 6
            assert all(item["display_label"][0] in {"W", "D", "4"} for item in swings)
            assert structure.json()["breaks_of_structure"], timeframe
            assert trend.json()["update"]["state"] == "bullish"

        alignment = client.get("/api/multi-timeframe-alignment", params={"symbol": "BTCUSDT"})

    assert alignment.status_code == 200
    assert alignment.json()["alignment_score"] == 3
    assert alignment.json()["bias"] == "bullish"
    assert alignment.json()["missing_timeframes"] == []


def test_demo_seed_data_is_directionally_consistent_for_long_intelligence() -> None:
    """Demo data proves integration only; seeded LONG levels must still be internally coherent."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)):
        latest_candle = runtime.candle_store.list("BTCUSDT", Timeframe.ONE_MINUTE)[-1]
        projected_swings = [
            swing
            for swing in runtime.market_state_service.structure_snapshot("BTCUSDT", Timeframe.ONE_MINUTE).swings
        ]
        higher_timeframe_trends = [
            runtime.trend_store.get("BTCUSDT", timeframe).update
            for timeframe in (
                Timeframe.WEEKLY,
                Timeframe.DAILY,
                Timeframe.FOUR_HOUR,
                Timeframe.TWO_HOUR,
                Timeframe.ONE_HOUR,
                Timeframe.THIRTY_MINUTE,
            )
        ]

    assert latest_candle.close > 0
    assert all(update is not None and update.state.value == "bullish" for update in higher_timeframe_trends)
    assert all(swing.level > 0 for swing in projected_swings)
    assert any(swing.label.value == "HL" and swing.level < latest_candle.close for swing in projected_swings)
    assert any(swing.label.value == "HH" for swing in projected_swings)
    assert all(
        bos.direction.value == "bullish"
        for bos in runtime.market_state_service.structure_snapshot(
            "BTCUSDT",
            Timeframe.ONE_MINUTE,
        ).breaks_of_structure
    )


def test_demo_trading_intelligence_is_internally_consistent() -> None:
    """Covers ENTRY/RISK/CHECKLIST/SCORE/INTEL consistency for synthetic BTCUSDT demo."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/trading-intelligence/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "4h", "minimum_risk_reward": 2.0},
        )
        repeat_response = client.post(
            "/api/trading-intelligence/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "4h", "minimum_risk_reward": 2.0},
        )

    assert response.status_code == 200
    assert repeat_response.status_code == 200
    payload = response.json()
    assert payload == repeat_response.json()

    entry = payload["entry_decision"]
    risk = payload["risk_plan"]
    checklist = payload["checklist"]
    score = payload["setup_score"]

    assert entry["state"] == "ENTRY_READY"
    assert entry["direction"] == "LONG"
    assert risk["state"] == "VALID"
    assert risk["entry_price"] is not None
    assert risk["stop_loss"] < risk["entry_price"]
    assert risk["take_profit"] > risk["entry_price"]
    assert risk["risk_reward_ratio"] == 2.0
    assert checklist["overall_status"] == "PASS"
    assert checklist["fail_count"] == 0
    assert score["grade"] in {"A", "B"}
    assert score["percentage"] >= 70.0
    assert payload["metadata"]["execution_order"] == "entry,risk,checklist,score,ai"


def test_demo_intelligence_does_not_emit_entry_ready_with_invalid_risk() -> None:
    """Regression guard against contradictory ENTRY_READY + INVALID risk demo output."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        payload = client.post(
            "/api/trading-intelligence/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "4h"},
        ).json()

    contradictory = (
        payload["entry_decision"]["state"] == "ENTRY_READY"
        and payload["risk_plan"]["state"] == "INVALID"
    )
    assert not contradictory
