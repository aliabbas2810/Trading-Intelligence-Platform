from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from backend.api import (
    InMemoryAlignmentReadStore,
    InMemoryStructureReadStore,
    InMemoryTrendReadStore,
    VisualizationReadApi,
)
from backend.config import PlatformSettings, load_settings
from backend.core import EventBus, configure_logging, get_logger
from backend.engines.ai import AiDecisionEngine, AiDecisionInput, AiDecisionOutput, RuleBasedMockAiDecisionProvider
from backend.engines.checklist import ChecklistEngine, ChecklistInput, ChecklistResult
from backend.engines.entry import DecisionTrace, EntrySignalEngine, EntrySignalInput
from backend.engines.intelligence import TradingIntelligenceResult
from backend.engines.readiness import AnalysisReadiness, AnalysisReadinessEngine
from backend.engines.historical import (
    BinanceHistoricalCandleDownloader,
    HistoricalCandleFileStore,
    HistoricalCandleLoader,
    HistoricalCandleRequest,
)
from backend.engines.replay import HistoricalTradeReplaySource, ReplayController
from backend.engines.risk import RiskEngine, RiskInput, RiskPlan
from backend.engines.scanner import ScannerEngine, ScannerSummary, SetupCandidate, SymbolScanInput
from backend.engines.scoring import ScoringInput, SetupScore, SetupScoringEngine
from backend.engines.structure import BreakOfStructure, MarketStructureEngine, StructureEvent, StructureSwing
from backend.engines.trend import (
    DirectionalBias,
    MultiTimeframeTrendAggregatedEvent,
    MultiTimeframeTrendAggregator,
    TimeframeTrendSnapshot,
    TrendChangedEvent,
    TrendEngine,
)
from backend.models import Candle, Timeframe
from backend.pipelines.candle import CandleClosedEvent, OneMinuteCandlePipeline
from backend.pipelines.market_data import (
    BinanceTradeStreamClient,
    BinanceTradeStreamClientConfig,
    BinanceTradeMessageParser,
    EventBusMarketDataPipeline,
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
)
from backend.pipelines.timeframe import TimeframeCandleClosedEvent, TimeframePipeline
from backend.storage import InMemoryCandleStore
from backend.app.demo import seed_demo_visualization_data
from backend.app.replay_runtime import ReplaySourceType, ReplayStatusSnapshot, RuntimeReplayService


class RuntimeMode(str, Enum):
    DRY_RUN = "dry_run"
    LIVE_BINANCE = "live_binance"
    HISTORICAL = "historical"


class RuntimeState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"


class ComponentStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """Component readiness report for RUNTIME-004."""

    name: str
    status: ComponentStatus
    message: str


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    """Application health/status model for RUNTIME-003 and RUNTIME-004."""

    state: RuntimeState
    mode: RuntimeMode
    components: tuple[ComponentHealth, ...]

    @property
    def is_healthy(self) -> bool:
        return self.state is RuntimeState.RUNNING and all(
            component.status in {ComponentStatus.RUNNING, ComponentStatus.READY}
            for component in self.components
            if component.status is not ComponentStatus.DISABLED
        )


@dataclass(frozen=True, slots=True)
class HistoricalRuntimeConfig:
    """Historical runtime input config for M28 local API visualization."""

    request: HistoricalCandleRequest
    data_root: Path = Path("data") / "historical"
    download: bool = False


class RuntimeAlreadyStartedError(RuntimeError):
    """Raised when the local backend runtime is started twice."""


class LiveStreamRunner(Protocol):
    def start(self) -> None:
        """Start live market data streaming."""

    def stop(self) -> None:
        """Stop live market data streaming."""


class BinanceLiveStreamRunner:
    """Background runner for the async Binance stream client under FR-101 and FR-102."""

    def __init__(self, client: BinanceTradeStreamClient) -> None:
        self._client = client
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start Binance streaming without blocking runtime startup."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_client, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._client.stop()

    def _run_client(self) -> None:
        asyncio.run(self._client.run())


LiveStreamRunnerFactory = Callable[[BinanceTradeStreamClient], LiveStreamRunner]


class BackendRuntime:
    """Application orchestrator that wires existing components for RUNTIME-001 to RUNTIME-005."""

    def __init__(
        self,
        settings: PlatformSettings | None = None,
        *,
        mode: RuntimeMode = RuntimeMode.DRY_RUN,
        live_stream_runner_factory: LiveStreamRunnerFactory | None = None,
        historical_config: HistoricalRuntimeConfig | None = None,
        historical_loader: HistoricalCandleLoader | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.mode = mode
        self.historical_config = historical_config
        self._historical_loader = historical_loader
        self.event_bus = EventBus()
        self.candle_store = InMemoryCandleStore()
        self.market_data_parser = BinanceTradeMessageParser()
        self.market_data_pipeline = EventBusMarketDataPipeline(self.event_bus)
        self.binance_stream_client = self._build_binance_stream_client()
        self._live_stream_runner_factory = live_stream_runner_factory or BinanceLiveStreamRunner
        self._live_stream_runner: LiveStreamRunner | None = None
        self._stream_status = MarketDataConnectionStatus.STOPPED
        self.candle_pipeline = OneMinuteCandlePipeline(self.event_bus, self.candle_store)
        self.timeframe_pipeline = TimeframePipeline(self.event_bus, self.candle_store)
        self.structure_store = InMemoryStructureReadStore()
        self.trend_store = InMemoryTrendReadStore()
        self.alignment_store = InMemoryAlignmentReadStore()
        self.visualization_api = VisualizationReadApi(
            candle_store=self.candle_store,
            structure_store=self.structure_store,
            trend_store=self.trend_store,
            alignment_store=self.alignment_store,
        )
        self.scanner = ScannerEngine(self.event_bus)
        self._scanner_summary: ScannerSummary | None = None
        self.ai_decision_engine = AiDecisionEngine(RuleBasedMockAiDecisionProvider())
        self.entry_signal_engine = EntrySignalEngine()
        self.risk_engine = RiskEngine()
        self.checklist_engine = ChecklistEngine()
        self.setup_scoring_engine = SetupScoringEngine()
        self.readiness_engine = AnalysisReadinessEngine(
            self.candle_store,
            self.structure_store,
            self.trend_store,
        )
        self.replay_controller = ReplayController(
            self.event_bus,
            HistoricalTradeReplaySource(()),
        )
        self.replay_service = RuntimeReplayService(symbol=self.active_symbol)
        self.multi_timeframe_aggregator = MultiTimeframeTrendAggregator()
        self._structure_engines: dict[tuple[str, Timeframe], MarketStructureEngine] = {}
        self._trend_engines: dict[tuple[str, Timeframe], TrendEngine] = {}
        self._trend_snapshots: dict[tuple[str, Timeframe], TimeframeTrendSnapshot] = {}
        self._state = RuntimeState.CREATED
        self._subscribed = False
        self._demo_seeded = False
        self._historical_loaded = False
        self._historical_candle_count = 0
        self._logger = get_logger(__name__)

    @property
    def state(self) -> RuntimeState:
        return self._state

    def start(self) -> None:
        """Start the local runtime and live stream when enabled for FR-101/RUNTIME-003."""

        if self._state is RuntimeState.RUNNING:
            raise RuntimeAlreadyStartedError("Backend runtime is already running")

        configure_logging(self.settings)
        self._subscribe_components()
        self._load_historical_data_if_enabled()
        self._seed_demo_data_if_enabled()
        self._state = RuntimeState.RUNNING
        self._start_live_stream_if_enabled()
        self._logger.info("Backend runtime started")

    def stop(self) -> None:
        """Stop the local runtime for RUNTIME-003."""

        if self._live_stream_runner is not None:
            self._live_stream_runner.stop()
            self._stream_status = MarketDataConnectionStatus.STOPPED
        self._state = RuntimeState.STOPPED
        self._logger.info("Backend runtime stopped")

    def health(self) -> RuntimeHealth:
        """Return component health/status for RUNTIME-004."""

        status = ComponentStatus.RUNNING if self._state is RuntimeState.RUNNING else ComponentStatus.READY
        if self._state is RuntimeState.STOPPED:
            status = ComponentStatus.STOPPED

        components = [
            ComponentHealth("settings", ComponentStatus.READY, self.settings.app.name),
            ComponentHealth("logging", status, "structured logging configured on start"),
            ComponentHealth("event_bus", status, "synchronous event bus"),
            ComponentHealth("candle_storage", status, "in-memory candle store"),
            ComponentHealth("market_data_pipeline", status, "event bus publisher foundation"),
            ComponentHealth(
                "binance_stream_client",
                self._binance_component_status(status),
                self._binance_component_message(),
            ),
            ComponentHealth("market_data_mode", ComponentStatus.READY, self.mode.value),
            ComponentHealth("stream_enabled", ComponentStatus.READY, str(self.stream_enabled)),
            ComponentHealth("stream_status", ComponentStatus.READY, self._stream_status.value),
            ComponentHealth("active_symbol", ComponentStatus.READY, self.active_symbol),
            ComponentHealth("candle_pipeline", status, "1m candle pipeline subscribed"),
            ComponentHealth("timeframe_pipeline", status, "higher timeframe pipeline subscribed"),
            ComponentHealth("structure_engine", status, "created lazily per symbol/timeframe"),
            ComponentHealth("trend_engine", status, "created lazily per symbol/timeframe"),
            ComponentHealth("multi_timeframe_aggregator", status, "aggregates trend snapshots"),
            ComponentHealth("replay_engine", status, self._replay_component_message()),
            ComponentHealth("scanner", status, "scanner foundation ready"),
            ComponentHealth("ai_decision_engine", status, "mock provider ready"),
            ComponentHealth("entry_signal_engine", status, "deterministic entry-state foundation ready"),
            ComponentHealth("risk_engine", status, "deterministic risk foundation ready"),
            ComponentHealth("checklist_engine", status, "evidence-driven checklist foundation ready"),
            ComponentHealth("setup_scoring_engine", status, "weighted setup scoring foundation ready"),
            ComponentHealth("visualization_api", status, "read-only API boundary ready"),
            ComponentHealth(
                "demo_data",
                self._demo_component_status(),
                self._demo_component_message(),
            ),
            ComponentHealth(
                "historical_data",
                self._historical_component_status(),
                self._historical_component_message(),
            ),
        ]
        return RuntimeHealth(
            state=self._state,
            mode=self.mode,
            components=tuple(components),
        )

    def start_replay(
        self,
        *,
        source_type: ReplaySourceType,
        speed_multiplier: float = 1.0,
        start_index: int = 0,
    ) -> ReplayStatusSnapshot:
        """Start a non-destructive chart replay cursor for FR-801 and FR-802."""

        return self.replay_service.start(
            source_type=source_type,
            speed_multiplier=speed_multiplier,
            start_index=start_index,
        )

    def pause_replay(self) -> ReplayStatusSnapshot:
        """Pause runtime replay for FR-803."""

        return self.replay_service.pause()

    def resume_replay(self) -> ReplayStatusSnapshot:
        """Resume runtime replay for FR-804."""

        return self.replay_service.resume()

    def stop_replay(self) -> ReplayStatusSnapshot:
        """Stop runtime replay for FR-801."""

        return self.replay_service.stop()

    def step_replay(self) -> ReplayStatusSnapshot:
        """Step runtime replay for FR-805."""

        return self.replay_service.step()

    def replay_status(self) -> ReplayStatusSnapshot:
        """Return replay progress/status for RUNTIME-004."""

        return self.replay_service.status()

    def reset_analysis_state(self) -> None:
        """Reset stateful analysis components before a fresh replay session."""

        self.candle_store = InMemoryCandleStore()
        self.candle_pipeline.reset(self.candle_store)
        self.timeframe_pipeline.reset(self.candle_store)
        self.structure_store = InMemoryStructureReadStore()
        self.trend_store = InMemoryTrendReadStore()
        self.alignment_store = InMemoryAlignmentReadStore()
        self.visualization_api = VisualizationReadApi(
            candle_store=self.candle_store,
            structure_store=self.structure_store,
            trend_store=self.trend_store,
            alignment_store=self.alignment_store,
        )
        self.multi_timeframe_aggregator = MultiTimeframeTrendAggregator()
        self.entry_signal_engine = EntrySignalEngine()
        self.risk_engine = RiskEngine()
        self.checklist_engine = ChecklistEngine()
        self.setup_scoring_engine = SetupScoringEngine()
        self.readiness_engine = AnalysisReadinessEngine(
            self.candle_store,
            self.structure_store,
            self.trend_store,
        )
        self._structure_engines = {}
        self._trend_engines = {}
        self._trend_snapshots = {}
        self._scanner_summary = None
        self.replay_controller = ReplayController(
            self.event_bus,
            HistoricalTradeReplaySource(()),
        )
        self.replay_service = RuntimeReplayService(symbol=self.active_symbol)
        self._demo_seeded = False
        self._historical_loaded = False
        self._historical_candle_count = 0

    def run_scanner(
        self,
        *,
        symbols: tuple[str, ...] | None = None,
        timeframe: Timeframe = Timeframe.FOUR_HOUR,
        bias: DirectionalBias | None = None,
        minimum_alignment_score: int = 0,
        minimum_setup_score: float = 0.0,
    ) -> ScannerSummary:
        """Run ScannerEngine over existing runtime snapshots for FR-901 through FR-905."""

        scan_symbols = symbols or tuple(self.settings.market_data.symbols)
        inputs = tuple(self._scanner_input_for(symbol, timeframe) for symbol in scan_symbols)
        self._scanner_summary = self.scanner.scan(
            inputs,
            bias=bias,
            minimum_alignment_score=minimum_alignment_score,
            minimum_setup_score=minimum_setup_score,
        )
        return self._scanner_summary

    def scanner_status(self) -> ScannerSummary | None:
        """Return latest scanner summary for RUNTIME-004."""

        return self._scanner_summary

    def generate_ai_decision(
        self,
        *,
        symbol: str,
        timeframe: Timeframe = Timeframe.FOUR_HOUR,
        entry_signal: str | None = None,
        risk_reward: str | None = None,
        entry_trace: DecisionTrace | None = None,
        risk_plan: RiskPlan | None = None,
        checklist_result: ChecklistResult | None = None,
        setup_score: SetupScore | None = None,
    ) -> AiDecisionOutput:
        """Generate a structured mock-provider decision for FR-1001 through FR-1006."""

        structure = self.structure_store.list(symbol, timeframe)
        trend = self.trend_store.get(symbol, timeframe)
        alignment = self.alignment_store.get(symbol)
        setup_candidate = self._latest_setup_candidate(symbol)
        decision_input = AiDecisionInput(
            symbol=symbol,
            timeframe_states=alignment.snapshots if alignment is not None else (),
            alignment=alignment,
            setup_candidate=setup_candidate,
            latest_structure=structure,
            latest_trend=trend,
            entry_signal=entry_signal,
            risk_reward=risk_reward,
            entry_state=entry_trace.state if entry_trace is not None else None,
            entry_direction=entry_trace.direction if entry_trace is not None else None,
            risk_state=risk_plan.state if risk_plan is not None else None,
            checklist_status=checklist_result.overall_status if checklist_result is not None else None,
            setup_grade=setup_score.grade if setup_score is not None else None,
            setup_score_percentage=setup_score.percentage if setup_score is not None else None,
            risk_reward_ratio=risk_plan.risk_reward_ratio if risk_plan is not None else None,
        )
        return self.ai_decision_engine.generate_decision(decision_input)

    def evaluate_entry_signal(self, *, symbol: str) -> DecisionTrace:
        """Evaluate entry state from existing stores for ENTRY-001 through ENTRY-006."""

        return self.entry_signal_engine.evaluate(self._entry_signal_input_for(symbol))

    def evaluate_data_readiness(self, *, symbol: str) -> AnalysisReadiness:
        """Evaluate historical/data warm-up readiness from existing read stores."""

        alignment = self.alignment_store.get(symbol)
        return self.readiness_engine.evaluate(
            symbol=symbol,
            alignment_missing_timeframes=(
                alignment.missing_timeframes if alignment is not None else ()
            ),
            alignment_score=alignment.alignment_score if alignment is not None else None,
        )

    def evaluate_risk(
        self,
        *,
        symbol: str,
        minimum_risk_reward: float | None = 2.0,
        target_mode: str | None = "rr",
        entry_trace: DecisionTrace | None = None,
    ) -> RiskPlan:
        """Evaluate risk from existing deterministic outputs for RISK-001 through RISK-006."""

        return self.risk_engine.evaluate(
            RiskInput(
                entry_trace=entry_trace or self.evaluate_entry_signal(symbol=symbol),
                latest_candle=self._latest_candle(symbol, Timeframe.ONE_MINUTE),
                structure_levels=self._risk_structure_levels(symbol),
                bos_events=self._risk_bos_events(symbol),
                minimum_risk_reward=minimum_risk_reward,
                target_mode=target_mode,
            ),
        )

    def evaluate_checklist(
        self,
        *,
        symbol: str,
        minimum_risk_reward: float | None = 2.0,
        entry_trace: DecisionTrace | None = None,
        risk_plan: RiskPlan | None = None,
    ) -> ChecklistResult:
        """Evaluate checklist from existing entry/risk evidence for CHECKLIST-001 through CHECKLIST-006."""

        entry_trace = entry_trace or self.evaluate_entry_signal(symbol=symbol)
        risk_plan = risk_plan or self.evaluate_risk(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            entry_trace=entry_trace,
        )
        return self.checklist_engine.evaluate(
            ChecklistInput(
                symbol=symbol,
                entry_trace=entry_trace,
                risk_plan=risk_plan,
                alignment=self.alignment_store.get(symbol),
                runtime_metadata={
                    "runtime_state": self.state.value,
                    "mode": self.mode.value,
                    "demo_data_enabled": self.demo_data_enabled,
                },
            ),
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
        """Evaluate weighted setup score from existing outputs for SCORE-001 through SCORE-006."""

        entry_trace = entry_trace or self.evaluate_entry_signal(symbol=symbol)
        risk_plan = risk_plan or self.evaluate_risk(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            entry_trace=entry_trace,
        )
        checklist_result = checklist_result or self.evaluate_checklist(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            entry_trace=entry_trace,
            risk_plan=risk_plan,
        )
        return self.setup_scoring_engine.evaluate(
            ScoringInput(
                symbol=symbol,
                entry_trace=entry_trace,
                risk_plan=risk_plan,
                checklist_result=checklist_result,
                alignment=self.alignment_store.get(symbol),
                scanner_candidate=self._latest_setup_candidate(symbol),
                metadata={
                    "runtime_state": self.state.value,
                    "mode": self.mode.value,
                },
            ),
        )

    def evaluate_trading_intelligence(
        self,
        *,
        symbol: str,
        timeframe: Timeframe = Timeframe.FOUR_HOUR,
        minimum_risk_reward: float | None = 2.0,
    ) -> TradingIntelligenceResult:
        """Run ordered trading intelligence orchestration for INTEL-001 through INTEL-006."""

        entry_trace = self.evaluate_entry_signal(symbol=symbol)
        risk_plan = self.evaluate_risk(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            entry_trace=entry_trace,
        )
        checklist_result = self.evaluate_checklist(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            entry_trace=entry_trace,
            risk_plan=risk_plan,
        )
        setup_score = self.evaluate_setup_score(
            symbol=symbol,
            minimum_risk_reward=minimum_risk_reward,
            entry_trace=entry_trace,
            risk_plan=risk_plan,
            checklist_result=checklist_result,
        )
        ai_decision = self.generate_ai_decision(
            symbol=symbol,
            timeframe=timeframe,
            entry_signal=f"{entry_trace.state.value}:{entry_trace.direction.value}",
            risk_reward=(
                f"risk_state={risk_plan.state.value};"
                f"rr={risk_plan.risk_reward_ratio};"
                f"score={setup_score.grade.value}:{setup_score.percentage:.2f}"
            ),
            entry_trace=entry_trace,
            risk_plan=risk_plan,
            checklist_result=checklist_result,
            setup_score=setup_score,
        )
        readiness = self.evaluate_data_readiness(symbol=symbol)
        return TradingIntelligenceResult(
            symbol=symbol,
            timeframe=timeframe,
            entry_decision=entry_trace,
            risk_plan=risk_plan,
            checklist=checklist_result,
            setup_score=setup_score,
            ai_decision=ai_decision,
            readiness=readiness,
            metadata={
                "execution_order": "entry,risk,checklist,score,ai",
                "runtime_state": self.state.value,
                "mode": self.mode.value,
                "minimum_risk_reward": minimum_risk_reward,
                "readiness_state": readiness.overall_state.value,
                "readiness_reason": readiness.reason,
            },
        )

    def _subscribe_components(self) -> None:
        if self._subscribed:
            return

        self.candle_pipeline.subscribe()
        self.timeframe_pipeline.subscribe()
        self.event_bus.subscribe(MarketDataStatusEvent, self._handle_market_data_status)
        self.event_bus.subscribe(CandleClosedEvent, self._handle_candle_closed)
        self.event_bus.subscribe(TimeframeCandleClosedEvent, self._handle_timeframe_candle_closed)
        self._subscribed = True

    @property
    def active_symbol(self) -> str:
        if self.historical_config is not None:
            return self.historical_config.request.symbol
        return self.settings.market_data.symbols[0]

    @property
    def stream_enabled(self) -> bool:
        return self.mode is RuntimeMode.LIVE_BINANCE and self.settings.market_data.live_enabled

    @property
    def demo_data_enabled(self) -> bool:
        return self.mode is RuntimeMode.DRY_RUN and self.settings.demo.enabled

    @property
    def historical_data_enabled(self) -> bool:
        return self.mode is RuntimeMode.HISTORICAL and self.historical_config is not None

    def _build_binance_stream_client(self) -> BinanceTradeStreamClient:
        return BinanceTradeStreamClient(
            config=BinanceTradeStreamClientConfig(
                symbol=self.active_symbol if hasattr(self, "settings") else "",
                reconnect_delay_seconds=self.settings.market_data.reconnect_delay_seconds,
                max_reconnect_attempts=self.settings.market_data.max_reconnect_attempts,
            ),
            event_bus=self.event_bus,
            parser=self.market_data_parser,
            pipeline=self.market_data_pipeline,
        )

    def _start_live_stream_if_enabled(self) -> None:
        if not self.stream_enabled:
            return
        self._live_stream_runner = self._live_stream_runner_factory(self.binance_stream_client)
        self._live_stream_runner.start()

    def _load_historical_data_if_enabled(self) -> None:
        if not self.historical_data_enabled or self._historical_loaded:
            return
        if self.historical_config is None:
            raise RuntimeError("Historical runtime mode requires historical_config")

        candles = self._historical_candles()
        for candle in candles:
            self._publish_historical_candle(candle)
        self._historical_candle_count = len(candles)
        self._historical_loaded = True
        self._logger.info("Loaded historical candles into runtime")

    def _historical_candles(self) -> tuple[Candle, ...]:
        if self.historical_config is None:
            raise RuntimeError("Historical runtime mode requires historical_config")
        if self._historical_loader is not None:
            return self._historical_loader.load(self.historical_config.request)

        store = HistoricalCandleFileStore(self.historical_config.data_root)
        if not self.historical_config.download:
            return store.load(self.historical_config.request)

        downloader = BinanceHistoricalCandleDownloader()
        candles = downloader.load(self.historical_config.request)
        store.save(self.historical_config.request, candles)
        return candles

    def _publish_historical_candle(self, candle: Candle) -> None:
        """Publish completed historical candles through existing runtime paths."""

        if candle.timeframe is Timeframe.ONE_MINUTE:
            self.event_bus.publish(CandleClosedEvent(candle=candle))
            return
        self._ensure_candle_stored(candle)
        self.event_bus.publish(TimeframeCandleClosedEvent(candle=candle))

    def _seed_demo_data_if_enabled(self) -> None:
        if not self.demo_data_enabled or self._demo_seeded:
            return
        seed_demo_visualization_data(
            symbol=self.active_symbol,
            candle_store=self.candle_store,
            structure_store=self.structure_store,
            trend_store=self.trend_store,
            alignment_store=self.alignment_store,
        )
        self._demo_seeded = True

    def _handle_market_data_status(self, event: MarketDataStatusEvent) -> None:
        self._stream_status = event.status

    def _binance_component_status(self, fallback: ComponentStatus) -> ComponentStatus:
        if self.mode in {RuntimeMode.DRY_RUN, RuntimeMode.HISTORICAL}:
            return ComponentStatus.DISABLED
        if not self.settings.market_data.live_enabled:
            return ComponentStatus.DISABLED
        return fallback

    def _binance_component_message(self) -> str:
        if self.mode is RuntimeMode.DRY_RUN:
            return "disabled in dry-run mode"
        if self.mode is RuntimeMode.HISTORICAL:
            return "disabled in historical mode"
        if not self.settings.market_data.live_enabled:
            return "disabled by config"
        return f"{self.settings.market_data.exchange}:{self.active_symbol}"

    def _demo_component_status(self) -> ComponentStatus:
        if not self.demo_data_enabled:
            return ComponentStatus.DISABLED
        if self._demo_seeded:
            return ComponentStatus.READY
        return ComponentStatus.READY

    def _demo_component_message(self) -> str:
        if self.mode is not RuntimeMode.DRY_RUN:
            return "disabled outside dry-run mode"
        if not self.settings.demo.enabled:
            return "disabled by config"
        if self._demo_seeded:
            return f"seeded deterministic visualization data for {self.active_symbol}"
        return "ready to seed deterministic visualization data"

    def _historical_component_status(self) -> ComponentStatus:
        if not self.historical_data_enabled:
            return ComponentStatus.DISABLED
        return ComponentStatus.READY if self._historical_loaded else ComponentStatus.READY

    def _historical_component_message(self) -> str:
        if self.mode is not RuntimeMode.HISTORICAL:
            return "disabled outside historical mode"
        if self.historical_config is None:
            return "historical config missing"
        request = self.historical_config.request
        if self._historical_loaded:
            return f"loaded {self._historical_candle_count} {request.timeframe.value} candles for {request.symbol}"
        return f"ready to load {request.symbol} {request.timeframe.value}"

    def _replay_component_message(self) -> str:
        replay_status = self.replay_status()
        return (
            f"{replay_status.status.value} "
            f"{replay_status.processed_events}/{replay_status.total_events} "
            f"source={replay_status.source_type.value if replay_status.source_type else 'none'}"
        )

    def _handle_candle_closed(self, event: CandleClosedEvent) -> None:
        self._ensure_candle_stored(event.candle)
        self._handle_completed_candle(event.candle)

    def _handle_timeframe_candle_closed(self, event: TimeframeCandleClosedEvent) -> None:
        self._handle_completed_candle(event.candle)

    def _ensure_candle_stored(self, candle: Candle) -> None:
        existing = self.candle_store.list(candle.symbol, candle.timeframe)
        if any(stored.open_time_ms == candle.open_time_ms for stored in existing):
            return
        self.candle_store.save(candle)

    def _handle_completed_candle(self, candle: Candle) -> None:
        structure_engine = self._structure_engine_for(candle)
        for structure_event in structure_engine.add_candle(candle):
            self._store_structure_event(structure_event)
            self._handle_structure_event(structure_event)

    def _store_structure_event(self, event: StructureEvent) -> None:
        if event.swing is not None:
            self.structure_store.add_swing(event.swing)
        if event.break_of_structure is not None:
            self.structure_store.add_break_of_structure(event.break_of_structure)

    def _handle_structure_event(self, event: StructureEvent) -> None:
        trend_engine = self._trend_engine_for(event)
        trend_update = trend_engine.add_event(event)
        if trend_update is None:
            return

        self.trend_store.set(trend_update)
        self.event_bus.publish(TrendChangedEvent(update=trend_update))
        self._trend_snapshots[(trend_update.symbol, trend_update.timeframe)] = TimeframeTrendSnapshot(
            symbol=trend_update.symbol,
            timeframe=trend_update.timeframe,
            state=trend_update.state,
            strength=trend_update.strength,
            event_time_ms=trend_update.event_time_ms,
        )
        result = self.multi_timeframe_aggregator.aggregate(self._snapshots_for(trend_update.symbol))
        self.alignment_store.set(result)
        self.event_bus.publish(MultiTimeframeTrendAggregatedEvent(result=result))

    def _structure_engine_for(self, candle: Candle) -> MarketStructureEngine:
        key = (candle.symbol, candle.timeframe)
        if key not in self._structure_engines:
            self._structure_engines[key] = MarketStructureEngine()
        return self._structure_engines[key]

    def _trend_engine_for(self, event: StructureEvent) -> TrendEngine:
        symbol, timeframe = structure_event_identity(event)
        key = (symbol, timeframe)
        if key not in self._trend_engines:
            self._trend_engines[key] = TrendEngine()
        return self._trend_engines[key]

    def _snapshots_for(self, symbol: str) -> Iterable[TimeframeTrendSnapshot]:
        return (
            snapshot
            for (snapshot_symbol, _), snapshot in self._trend_snapshots.items()
            if snapshot_symbol == symbol
        )

    def _scanner_input_for(self, symbol: str, timeframe: Timeframe) -> SymbolScanInput:
        structure = self.structure_store.list(symbol, timeframe)
        trend = self.trend_store.get(symbol, timeframe).update
        candles = self.candle_store.list(symbol, timeframe)
        return SymbolScanInput(
            symbol=symbol,
            trend=trend,
            alignment=self.alignment_store.get(symbol),
            structure_swings=structure.swings,
            breaks_of_structure=structure.breaks_of_structure,
            latest_candle=candles[-1] if candles else None,
        )

    def _entry_signal_input_for(self, symbol: str) -> EntrySignalInput:
        structures = {
            timeframe: self.structure_store.list(symbol, timeframe)
            for timeframe in (Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE, Timeframe.ONE_MINUTE)
        }
        one_minute_candles = self.candle_store.list(symbol, Timeframe.ONE_MINUTE)
        return EntrySignalInput(
            symbol=symbol,
            trend_1w=self.trend_store.get(symbol, Timeframe.WEEKLY).update,
            trend_1d=self.trend_store.get(symbol, Timeframe.DAILY).update,
            trend_4h=self.trend_store.get(symbol, Timeframe.FOUR_HOUR).update,
            trend_2h=self.trend_store.get(symbol, Timeframe.TWO_HOUR).update,
            trend_1h=self.trend_store.get(symbol, Timeframe.ONE_HOUR).update,
            trend_30m=self.trend_store.get(symbol, Timeframe.THIRTY_MINUTE).update,
            structure_15m=structures[Timeframe.FIFTEEN_MINUTE],
            structure_5m=structures[Timeframe.FIVE_MINUTE],
            structure_1m=structures[Timeframe.ONE_MINUTE],
            bos_events=tuple(
                event
                for structure in structures.values()
                for event in structure.breaks_of_structure
            ),
            latest_candle=one_minute_candles[-1] if one_minute_candles else None,
            alignment=self.alignment_store.get(symbol),
        )

    def _latest_candle(self, symbol: str, timeframe: Timeframe) -> Candle | None:
        candles = self.candle_store.list(symbol, timeframe)
        return candles[-1] if candles else None

    def _risk_structure_levels(self, symbol: str) -> tuple[StructureSwing, ...]:
        return tuple(
            swing
            for timeframe in (Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE, Timeframe.ONE_MINUTE)
            for swing in self.structure_store.list(symbol, timeframe).swings
        )

    def _risk_bos_events(self, symbol: str) -> tuple[BreakOfStructure, ...]:
        return tuple(
            event
            for timeframe in (Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE, Timeframe.ONE_MINUTE)
            for event in self.structure_store.list(symbol, timeframe).breaks_of_structure
        )

    def _latest_setup_candidate(self, symbol: str) -> SetupCandidate | None:
        if self._scanner_summary is None:
            return None
        for candidate in self._scanner_summary.candidates:
            if candidate.symbol == symbol:
                return candidate
        return None


def structure_event_identity(event: StructureEvent) -> tuple[str, Timeframe]:
    if event.swing is not None:
        return event.swing.symbol, event.swing.timeframe
    if event.break_of_structure is not None:
        return event.break_of_structure.symbol, event.break_of_structure.timeframe
    raise ValueError("StructureEvent must contain structure data")
