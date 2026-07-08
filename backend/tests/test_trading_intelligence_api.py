from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.service import create_app
from backend.app import BackendRuntime, RuntimeMode
from backend.config import PlatformSettings, load_settings
from backend.engines.ai import AiDecisionOutput
from backend.engines.checklist import ChecklistResult
from backend.engines.entry import DecisionTrace
from backend.engines.risk import RiskPlan
from backend.engines.scoring import SetupScore
from backend.models import Timeframe
from backend.tests.test_api_service import seed_entry_ready_symbol


def test_trading_intelligence_endpoint_returns_all_sections() -> None:
    """Covers INTEL-001, INTEL-004, and TEST-001."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_entry_ready_symbol(runtime, "BTCUSDT")

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/trading-intelligence/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "4h", "minimum_risk_reward": 2.0},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "BTCUSDT"
    assert payload["timeframe"] == "4h"
    assert payload["entry_decision"]["state"] == "ENTRY_READY"
    assert payload["risk_plan"]["state"] == "VALID"
    assert payload["checklist"]["overall_status"] == "PASS"
    assert payload["setup_score"]["grade"] in {"A", "B"}
    assert payload["ai_decision"]["provider"] == "rule_based_mock"
    assert payload["metadata"]["execution_order"] == "entry,risk,checklist,score,ai"


def test_trading_intelligence_runtime_execution_order_is_correct() -> None:
    """Covers INTEL-002 ordered orchestration."""

    runtime = RecordingTradingIntelligenceRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)
    seed_entry_ready_symbol(runtime, "BTCUSDT")

    result = runtime.evaluate_trading_intelligence(symbol="BTCUSDT", timeframe=Timeframe.FOUR_HOUR)

    assert result.symbol == "BTCUSDT"
    assert runtime.calls == ["entry", "risk", "checklist", "score", "ai"]
    assert runtime.captured_entry_signal == "ENTRY_READY:LONG"
    assert runtime.captured_risk_reward is not None
    assert "risk_state=VALID" in runtime.captured_risk_reward


def test_trading_intelligence_missing_data_is_graceful() -> None:
    """Covers INTEL-005 missing-data behavior."""

    runtime = BackendRuntime(settings=demo_disabled_settings(), mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/api/trading-intelligence/evaluate",
            json={"symbol": "MISSINGUSDT", "timeframe": "4h"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["entry_decision"]["state"] == "WAIT"
    assert payload["risk_plan"]["state"] == "NOT_APPLICABLE"
    assert payload["checklist"]["overall_status"] in {"FAIL", "MISSING", "WARNING"}
    assert payload["setup_score"]["grade"] in {"D", "F"}
    assert payload["ai_decision"]["provider"] == "rule_based_mock"


def test_trading_intelligence_response_is_deterministic_for_demo_data() -> None:
    """Covers deterministic INTEL-001 response behavior."""

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)

    with TestClient(create_app(runtime)) as client:
        first = client.post("/api/trading-intelligence/evaluate", json={"symbol": "BTCUSDT"}).json()
        second = client.post("/api/trading-intelligence/evaluate", json={"symbol": "BTCUSDT"}).json()

    assert first == second


def test_trading_intelligence_api_does_not_recompute_analysis_logic() -> None:
    """Covers INTEL-003 and INTEL-006 transport-only API constraint."""

    source = "\n".join(
        (
            Path("backend/api/service.py").read_text(encoding="utf-8"),
            Path("backend/api/trading_intelligence.py").read_text(encoding="utf-8"),
        ),
    )

    forbidden_fragments = (
        "MarketStructureEngine",
        "TrendEngine",
        "ScannerEngine",
        "EntrySignalEngine",
        "RiskEngine",
        "ChecklistEngine",
        "SetupScoringEngine",
        ".add_candle(",
        ".add_event(",
        "score_candidate",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source


class RecordingTradingIntelligenceRuntime(BackendRuntime):
    def __init__(self, settings: PlatformSettings, mode: RuntimeMode) -> None:
        super().__init__(settings=settings, mode=mode)
        self.calls: list[str] = []
        self.captured_entry_signal: str | None = None
        self.captured_risk_reward: str | None = None

    def evaluate_entry_signal(self, *, symbol: str) -> DecisionTrace:
        self.calls.append("entry")
        return super().evaluate_entry_signal(symbol=symbol)

    def evaluate_risk(
        self,
        *,
        symbol: str,
        minimum_risk_reward: float | None = 2.0,
        target_mode: str | None = "rr",
        entry_trace: DecisionTrace | None = None,
    ) -> RiskPlan:
        self.calls.append("risk")
        assert entry_trace is not None
        return super().evaluate_risk(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            target_mode=target_mode,
            entry_trace=entry_trace,
        )

    def evaluate_checklist(
        self,
        *,
        symbol: str,
        minimum_risk_reward: float | None = 2.0,
        entry_trace: DecisionTrace | None = None,
        risk_plan: RiskPlan | None = None,
    ) -> ChecklistResult:
        self.calls.append("checklist")
        assert entry_trace is not None
        assert risk_plan is not None
        return super().evaluate_checklist(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            entry_trace=entry_trace,
            risk_plan=risk_plan,
        )

    def evaluate_setup_score(
        self,
        *,
        symbol: str,
        minimum_risk_reward: float | None = 2.0,
        entry_trace: DecisionTrace | None = None,
        risk_plan: RiskPlan | None = None,
        checklist_result: ChecklistResult | None = None,
    ) -> SetupScore:
        self.calls.append("score")
        assert entry_trace is not None
        assert risk_plan is not None
        assert checklist_result is not None
        return super().evaluate_setup_score(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            entry_trace=entry_trace,
            risk_plan=risk_plan,
            checklist_result=checklist_result,
        )

    def generate_ai_decision(
        self,
        *,
        symbol: str,
        timeframe: Timeframe = Timeframe.FOUR_HOUR,
        entry_signal: str | None = None,
        risk_reward: str | None = None,
    ) -> AiDecisionOutput:
        self.calls.append("ai")
        self.captured_entry_signal = entry_signal
        self.captured_risk_reward = risk_reward
        return super().generate_ai_decision(
            symbol=symbol,
            timeframe=timeframe,
            entry_signal=entry_signal,
            risk_reward=risk_reward,
        )


def demo_disabled_settings() -> PlatformSettings:
    settings = load_settings()
    return settings.model_copy(
        update={
            "demo": settings.demo.model_copy(update={"enabled": False}),
        },
    )
