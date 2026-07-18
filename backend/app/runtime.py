from __future__ import annotations

import time
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
from backend.engines.aoi import (
    ActiveStructureLeg,
    AoiEngine,
    AoiEvaluation,
    AoiGateResult,
    AoiLocationConfig,
    AoiLocationResult,
    AoiLocationState,
    AoiOverlap,
    AoiRankingMetadata,
    AoiSizingConfig,
    AoiSizingMode,
    AoiState,
    AoiTimeframe,
    AreaOfInterest,
)
from backend.engines.checklist import ChecklistEngine, ChecklistInput, ChecklistResult
from backend.engines.entry import DecisionTrace, EntrySignalEngine, EntrySignalInput
from backend.engines.intelligence import TradingIntelligenceResult
from backend.engines.market_state import MARKET_STRUCTURE_TIMEFRAMES, MarketStateService
from backend.engines.readiness import AnalysisReadiness, AnalysisReadinessEngine
from backend.engines.historical import (
    BitMartHistoricalCandleDownloader,
    HistoricalCandleFileStore,
    HistoricalCandleLoadResult,
    HistoricalCandleLoader,
    HistoricalCandleRequest,
)
from backend.engines.replay import HistoricalTradeReplaySource, ReplayController
from backend.engines.risk import RiskEngine, RiskInput, RiskPlan
from backend.engines.scanner import ScannerEngine, ScannerSummary, SetupCandidate, SymbolScanInput
from backend.engines.scoring import ScoringInput, SetupScore, SetupScoringEngine
from backend.engines.structure import (
    BreakOfStructure,
    MarketStructureEngine,
    PercentDisplacementThreshold,
    StructureDiagnostics,
    StructureEvent,
    StructureLabel,
    StructureSwing,
    SwingKind,
)
from backend.engines.trend import (
    DirectionalBias,
    MultiTimeframeTrendAggregatedEvent,
    MultiTimeframeTrendAggregator,
    TimeframeTrendSnapshot,
    TrendChangedEvent,
    TrendEngine,
    TrendState,
)
from backend.exchange import BitMartFuturesMarketDataAdapter, ExchangeName, HistoricalIntegrityPolicy, HistoricalIntegrityReport, MarketType
from backend.models import Candle, Timeframe, Trade
from backend.pipelines.candle import CandleClosedEvent, OneMinuteCandlePipeline
from backend.pipelines.market_data import (
    BitMartTradeStreamClient,
    BitMartTradeStreamClientConfig,
    BitMartWebSocketLiveStreamRunner,
    EventBusMarketDataPipeline,
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
)
from backend.pipelines.timeframe import TimeframeCandleClosedEvent, TimeframePipeline
from backend.storage import InMemoryCandleStore, JsonlCandleHistoryStore
from backend.sync import (
    IncrementalSyncPlanner,
    MarketDataSyncCoordinator,
    SQLiteSyncMetadataStore,
    SyncCoordinatorStatus,
    SymbolSyncStatus,
)
from backend.app.demo import seed_demo_visualization_data
from backend.app.replay_runtime import ReplaySourceType, ReplayStatusSnapshot, RuntimeReplayService


class RuntimeMode(str, Enum):
    DRY_RUN = "dry_run"
    LIVE_BITMART = "live_bitmart"
    HISTORICAL = "historical"
    HISTORICAL_LIVE = "historical_live"


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
    historical_integrity: HistoricalIntegrityReport | None = None

    @property
    def is_healthy(self) -> bool:
        return self.state is RuntimeState.RUNNING and all(
            component.status in {ComponentStatus.RUNNING, ComponentStatus.READY}
            for component in self.components
            if component.status is not ComponentStatus.DISABLED
        )


@dataclass(frozen=True, slots=True)
class AoiEvaluationDiagnostics:
    """Runtime-only AOI evaluation diagnostics for historical acceptance testing."""

    symbol: str
    timeframe: AoiTimeframe
    evaluated: bool
    reason_code: str
    candle_count: int
    swing_count: int
    trend_available: bool
    candidate_count: int = 0
    active_count: int = 0
    broken_count: int = 0
    archived_count: int = 0


@dataclass(frozen=True, slots=True)
class HistoricalRuntimeConfig:
    """Historical runtime input config for M28 local API visualization."""

    request: HistoricalCandleRequest
    data_root: Path = Path("data") / "historical"
    download: bool = False
    integrity_policy: HistoricalIntegrityPolicy = HistoricalIntegrityPolicy.STRICT


class RuntimeAlreadyStartedError(RuntimeError):
    """Raised when the local backend runtime is started twice."""


class LiveStreamRunner(Protocol):
    def start(self) -> None:
        """Start live market data streaming."""

    def stop(self) -> None:
        """Stop live market data streaming."""


class BitMartUnavailableLiveStreamRunner:
    """Legacy test runner that reports BitMart live stream unavailability."""

    def __init__(self, client: BitMartTradeStreamClient) -> None:
        self._client = client

    def start(self) -> None:
        self._client.start_unavailable()

    def stop(self) -> None:
        self._client.stop()


LiveStreamRunnerFactory = Callable[[BitMartTradeStreamClient], LiveStreamRunner]


class BoundaryFilteringMarketDataPipeline(EventBusMarketDataPipeline):
    """Drops live trades before the historical/live handoff for FR-101 and RUNTIME-002."""

    def __init__(self, event_bus: EventBus, accept_trade: Callable[[Trade], bool]) -> None:
        super().__init__(event_bus)
        self._accept_trade = accept_trade

    def publish_trade(self, trade: Trade) -> None:
        if not self._accept_trade(trade):
            return
        super().publish_trade(trade)


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
        market_data_sync_coordinator: MarketDataSyncCoordinator | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.mode = mode
        self.historical_config = historical_config
        self._historical_loader = historical_loader
        self.market_data_sync_coordinator = (
            market_data_sync_coordinator
            if market_data_sync_coordinator is not None
            else self._build_market_data_sync_coordinator_if_enabled()
        )
        self.event_bus = EventBus()
        self.candle_store = InMemoryCandleStore()
        self._historical_live_min_trade_timestamp_ms: int | None = None
        self.market_data_pipeline = BoundaryFilteringMarketDataPipeline(
            self.event_bus,
            self._accept_trade_for_runtime,
        )
        self.bitmart_stream_client = self._build_bitmart_stream_client()
        self._live_stream_runner_factory = live_stream_runner_factory or BitMartWebSocketLiveStreamRunner
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
        self.market_state_service = MarketStateService()
        self.readiness_engine = AnalysisReadinessEngine(
            self.candle_store,
            self.structure_store,
            self.trend_store,
            self.market_state_service,
        )
        self.aoi_engine = AoiEngine()
        self._aoi_evaluations: dict[tuple[str, AoiTimeframe], AoiEvaluation] = {}
        self._aoi_diagnostics: dict[tuple[str, AoiTimeframe], AoiEvaluationDiagnostics] = {}
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
        self._historical_integrity_report: HistoricalIntegrityReport | None = None
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
        self._hydrate_market_state_from_existing_stores()
        self._load_historical_data_if_enabled()
        self._seed_demo_data_if_enabled()
        self._state = RuntimeState.RUNNING
        self._start_market_data_sync_if_enabled()
        self._start_live_stream_if_enabled()
        self._logger.info("Backend runtime started")

    def stop(self) -> None:
        """Stop the local runtime for RUNTIME-003."""

        if self._live_stream_runner is not None:
            self._live_stream_runner.stop()
            self._stream_status = MarketDataConnectionStatus.STOPPED
        if self.market_data_sync_coordinator is not None:
            self.market_data_sync_coordinator.stop()
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
                "bitmart_stream_client",
                self._bitmart_component_status(status),
                self._bitmart_component_message(),
            ),
            ComponentHealth("market_data_mode", ComponentStatus.READY, self.mode.value),
            ComponentHealth("exchange", ComponentStatus.READY, self.settings.market_data.exchange),
            ComponentHealth("market_type", ComponentStatus.READY, self.settings.market_data.market_type),
            ComponentHealth("stream_enabled", ComponentStatus.READY, str(self.stream_enabled)),
            ComponentHealth("stream_status", ComponentStatus.READY, self._stream_status.value),
            ComponentHealth("active_symbol", ComponentStatus.READY, self.active_symbol),
            ComponentHealth("candle_pipeline", status, "1m candle pipeline subscribed"),
            ComponentHealth("timeframe_pipeline", status, "higher timeframe pipeline subscribed"),
            ComponentHealth("structure_engine", status, "created lazily per symbol/timeframe"),
            ComponentHealth("trend_engine", status, "created lazily per symbol/timeframe"),
            ComponentHealth("aoi_engine", status, "weekly/daily AOI foundation ready"),
            ComponentHealth(
                "market_data_sync",
                self._market_data_sync_component_status(),
                self._market_data_sync_component_message(),
            ),
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
            ComponentHealth(
                "historical_candles_loaded",
                ComponentStatus.READY,
                str(self._historical_candle_count),
            ),
            ComponentHealth(
                "historical_integrity",
                self._historical_integrity_component_status(),
                self._historical_integrity_component_message(),
            ),
        ]
        return RuntimeHealth(
            state=self._state,
            mode=self.mode,
            components=tuple(components),
            historical_integrity=self._historical_integrity_report,
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
        self.market_state_service = MarketStateService()
        self.readiness_engine = AnalysisReadinessEngine(
            self.candle_store,
            self.structure_store,
            self.trend_store,
            self.market_state_service,
        )
        self.aoi_engine = AoiEngine()
        self._aoi_evaluations = {}
        self._aoi_diagnostics = {}
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
        self._historical_integrity_report = None
        self._historical_live_min_trade_timestamp_ms = None

    def market_structure_snapshot(self, symbol: str, timeframe: Timeframe) -> object:
        """Return projected authoritative 1W/1D/4H market state for chart rendering."""

        return self.market_state_service.structure_snapshot(symbol, timeframe)

    def market_state(self, symbol: str) -> dict[str, object]:
        """Return the current authoritative Weekly/Daily/4H market state."""

        return {
            "symbol": symbol,
            "timeframes": self.market_state_service.state(symbol),
        }

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

        if symbols is None and self.settings.market_data_sync.scanner_ready_only:
            ready_symbols = (
                self.market_data_sync_coordinator.ready_symbols()
                if self.market_data_sync_coordinator is not None
                else ()
            )
            scan_symbols = ready_symbols or tuple(self.settings.market_data.symbols)
        else:
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

        structure = self.market_state_service.structure_snapshot(symbol, timeframe)
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
            aoi_gate_eligible=(
                bool(entry_trace.metadata["aoi_gate_eligible"])
                if entry_trace is not None and isinstance(entry_trace.metadata.get("aoi_gate_eligible"), bool)
                else None
            ),
            aoi_reason_codes=(
                tuple(str(entry_trace.metadata["aoi_reason_codes"]).split(","))
                if entry_trace is not None and entry_trace.metadata.get("aoi_reason_codes")
                else ()
            ),
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
            historical_integrity=self._historical_integrity_report,
        )

    def evaluate_aois(
        self,
        *,
        symbol: str,
        timeframe: AoiTimeframe,
        sizing: AoiSizingConfig,
        tick_size: float | None = None,
        atr: float | None = None,
    ) -> AoiEvaluation:
        """Evaluate AOIs from stored candles and precomputed structure/trend snapshots."""

        leg = self._active_structure_leg(symbol, timeframe)
        evaluation = self.aoi_engine.evaluate(
            leg=leg,
            candles=self.candle_store.list(symbol, timeframe.to_timeframe()),
            sizing=sizing,
            tick_size=tick_size,
            atr=atr,
        )
        evaluation = self._merge_previous_aoi_lifecycle(symbol, timeframe, leg, evaluation)
        self._aoi_evaluations[(symbol, timeframe)] = evaluation
        self._record_aoi_evaluation(symbol, timeframe, evaluation)
        return evaluation

    def list_aois(
        self,
        *,
        symbol: str,
        timeframe: AoiTimeframe | None = None,
    ) -> tuple[AreaOfInterest, ...]:
        """Read cached AOIs without recalculating structure, trend, or AOI candidates."""

        timeframes = (timeframe,) if timeframe is not None else tuple(AoiTimeframe)
        return tuple(
            area
            for item in timeframes
            for area in (
                self._aoi_evaluations[(symbol, item)].areas
                if (symbol, item) in self._aoi_evaluations
                else ()
            )
        )

    def aoi_diagnostics(
        self,
        *,
        symbol: str,
        timeframe: AoiTimeframe | None = None,
    ) -> tuple[AoiEvaluationDiagnostics, ...]:
        timeframes = (timeframe,) if timeframe is not None else tuple(AoiTimeframe)
        return tuple(
            diagnostic
            for item in timeframes
            if (diagnostic := self._aoi_diagnostics.get((symbol, item))) is not None
        )

    def evaluate_aoi_location(
        self,
        *,
        symbol: str,
        aoi_id: str,
        config: AoiLocationConfig,
    ) -> AoiLocationResult:
        """Evaluate the location gate against a cached AOI and latest completed candle."""

        area = next((item for item in self.list_aois(symbol=symbol) if item.aoi_id == aoi_id), None)
        if area is None:
            raise ValueError(f"Unknown AOI {aoi_id!r} for {symbol}")
        candles = self.candle_store.list(symbol, area.timeframe.to_timeframe())
        if not candles:
            raise ValueError("AOI location evaluation requires a completed candle")
        return self.aoi_engine.locate(
            area,
            candle=candles[-1],
            previous_candle=candles[-2] if len(candles) > 1 else None,
            config=config,
        )

    def list_aoi_overlaps(
        self,
        *,
        symbol: str,
        confluence_weight: float,
    ) -> tuple[AoiOverlap, ...]:
        """Return non-destructive Weekly/Daily AOI intersections."""

        return self.aoi_engine.find_overlaps(
            self.list_aois(symbol=symbol, timeframe=AoiTimeframe.WEEKLY),
            self.list_aois(symbol=symbol, timeframe=AoiTimeframe.DAILY),
            confluence_weight=confluence_weight,
        )

    def evaluate_aoi_gate(
        self,
        *,
        symbol: str,
        config: AoiLocationConfig | None = None,
        confluence_weight: float = 1.0,
    ) -> AoiGateResult:
        """Evaluate the Weekly/Daily AOI location hard gate from cached AOIs."""

        location_config = config or self._default_aoi_location_config()
        active_aois = tuple(
            area
            for area in self.list_aois(symbol=symbol)
            if area.state is AoiState.ACTIVE and area.confirmation_time_ms is not None
        )
        locations: list[AoiLocationResult] = []
        for area in active_aois:
            candles = self.candle_store.list(symbol, area.timeframe.to_timeframe())
            if not candles:
                continue
            locations.append(
                self.aoi_engine.locate(
                    area,
                    candle=candles[-1],
                    previous_candle=candles[-2] if len(candles) > 1 else None,
                    config=location_config,
                ),
            )
        overlaps = self.list_aoi_overlaps(symbol=symbol, confluence_weight=confluence_weight)
        eligible = any(location.gate_open for location in locations)
        reason_codes = self._aoi_gate_reason_codes(symbol, active_aois, tuple(locations), overlaps, eligible)
        return AoiGateResult(
            symbol=symbol,
            eligible=eligible,
            active_aois=active_aois,
            locations=tuple(locations),
            overlaps=overlaps,
            reason_codes=reason_codes,
        )

    def _aoi_gate_reason_codes(
        self,
        symbol: str,
        active_aois: tuple[AreaOfInterest, ...],
        locations: tuple[AoiLocationResult, ...],
        overlaps: tuple[AoiOverlap, ...],
        eligible: bool,
    ) -> tuple[str, ...]:
        codes: list[str] = []
        if not active_aois:
            codes.append(self._empty_aoi_reason_code(symbol))
        if any(area.timeframe is AoiTimeframe.WEEKLY for area in active_aois):
            codes.append("weekly_aoi_active")
        if any(area.timeframe is AoiTimeframe.DAILY for area in active_aois):
            codes.append("daily_aoi_active")
        if overlaps:
            codes.append("weekly_daily_aoi_overlap")
        for location in locations:
            if location.state is AoiLocationState.INSIDE:
                codes.append("aoi_location_inside")
            elif location.state is AoiLocationState.REACTING:
                codes.append("aoi_location_reacting")
            elif location.state is AoiLocationState.ENTRY_WINDOW:
                codes.append("aoi_location_entry_window")
            elif location.state is AoiLocationState.MOVED_AWAY:
                codes.append("aoi_moved_away")
        if not eligible and "aoi_data_missing" not in codes and "no_active_aoi" not in codes:
            codes.append("aoi_location_not_eligible")
        return tuple(dict.fromkeys(codes))

    def _merge_previous_aoi_lifecycle(
        self,
        symbol: str,
        timeframe: AoiTimeframe,
        leg: ActiveStructureLeg,
        evaluation: AoiEvaluation,
    ) -> AoiEvaluation:
        previous = self._aoi_evaluations.get((symbol, timeframe))
        if previous is None:
            return evaluation

        latest_candle = self._latest_candle(symbol, timeframe.to_timeframe())
        if latest_candle is None:
            return evaluation

        transitioned: list[AreaOfInterest] = []
        for area in previous.areas:
            updated = self.aoi_engine.update_lifecycle(
                area,
                candle=latest_candle,
                current_structure_leg_id=leg.leg_id,
                current_trend_id=leg.trend_id,
            )
            if updated.state is not AoiState.ACTIVE or not any(
                item.aoi_id == updated.aoi_id for item in evaluation.areas
            ):
                transitioned.append(updated)
        if not transitioned:
            return evaluation
        transitioned_ids = {area.aoi_id for area in transitioned}
        return AoiEvaluation(
            leg=evaluation.leg,
            candidates=evaluation.candidates,
            areas=(
                *transitioned,
                *(area for area in evaluation.areas if area.aoi_id not in transitioned_ids),
            ),
        )

    def _empty_aoi_reason_code(self, symbol: str) -> str:
        diagnostics = tuple(
            self._aoi_diagnostics.get((symbol, timeframe))
            for timeframe in (AoiTimeframe.WEEKLY, AoiTimeframe.DAILY)
        )
        if any(item is not None and item.evaluated for item in diagnostics):
            return "no_active_aoi"
        return "aoi_data_missing"

    def _record_aoi_evaluation(
        self,
        symbol: str,
        timeframe: AoiTimeframe,
        evaluation: AoiEvaluation,
    ) -> None:
        areas = evaluation.areas
        diagnostic = AoiEvaluationDiagnostics(
            symbol=symbol,
            timeframe=timeframe,
            evaluated=True,
            reason_code="aoi_evaluated",
            candle_count=len(self.candle_store.list(symbol, timeframe.to_timeframe())),
            swing_count=len(self.structure_store.list(symbol, timeframe.to_timeframe()).swings),
            trend_available=self.trend_store.get(symbol, timeframe.to_timeframe()).update is not None,
            candidate_count=len(evaluation.candidates),
            active_count=sum(area.state is AoiState.ACTIVE for area in areas),
            broken_count=sum(area.state is AoiState.BROKEN for area in areas),
            archived_count=sum(area.state is AoiState.ARCHIVED for area in areas),
        )
        self._aoi_diagnostics[(symbol, timeframe)] = diagnostic
        self._logger.info(
            "AOI evaluation completed",
            extra={
                "symbol": symbol,
                "timeframe": timeframe.value,
                "weekly_candle_count": len(self.candle_store.list(symbol, Timeframe.WEEKLY)),
                "daily_candle_count": len(self.candle_store.list(symbol, Timeframe.DAILY)),
                "candle_count": diagnostic.candle_count,
                "swing_count": diagnostic.swing_count,
                "trend_available": diagnostic.trend_available,
                "candidate_count": diagnostic.candidate_count,
                "active_count": diagnostic.active_count,
                "broken_count": diagnostic.broken_count,
                "archived_count": diagnostic.archived_count,
            },
        )

    def _record_aoi_missing_inputs(
        self,
        symbol: str,
        timeframe: AoiTimeframe,
        reason: str,
    ) -> None:
        candle_count = len(self.candle_store.list(symbol, timeframe.to_timeframe()))
        swing_count = len(self.structure_store.list(symbol, timeframe.to_timeframe()).swings)
        trend_available = self.trend_store.get(symbol, timeframe.to_timeframe()).update is not None
        no_active_leg = reason.startswith("No active") and candle_count > 0 and swing_count > 0 and trend_available
        diagnostic = AoiEvaluationDiagnostics(
            symbol=symbol,
            timeframe=timeframe,
            evaluated=no_active_leg,
            reason_code="no_active_aoi" if no_active_leg else "aoi_data_missing",
            candle_count=candle_count,
            swing_count=swing_count,
            trend_available=trend_available,
        )
        self._aoi_diagnostics[(symbol, timeframe)] = diagnostic
        self._logger.info(
            "AOI evaluation input assessment completed",
            extra={
                "symbol": symbol,
                "timeframe": timeframe.value,
                "weekly_candle_count": len(self.candle_store.list(symbol, Timeframe.WEEKLY)),
                "daily_candle_count": len(self.candle_store.list(symbol, Timeframe.DAILY)),
                "candle_count": diagnostic.candle_count,
                "swing_count": diagnostic.swing_count,
                "trend_available": diagnostic.trend_available,
                "reason_code": diagnostic.reason_code,
                "reason": reason,
            },
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
                    "historical_integrity_status": (
                        self._historical_integrity_report.status.value
                        if self._historical_integrity_report is not None
                        else None
                    ),
                    "historical_integrity_complete": (
                        self._historical_integrity_report.complete
                        if self._historical_integrity_report is not None
                        else None
                    ),
                    "historical_gap_count": (
                        self._historical_integrity_report.gap_count
                        if self._historical_integrity_report is not None
                        else None
                    ),
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
        aoi_gate = self.evaluate_aoi_gate(symbol=symbol)
        return TradingIntelligenceResult(
            symbol=symbol,
            timeframe=timeframe,
            entry_decision=entry_trace,
            risk_plan=risk_plan,
            checklist=checklist_result,
            setup_score=setup_score,
            ai_decision=ai_decision,
            readiness=readiness,
            aoi_gate=aoi_gate,
            metadata={
                "execution_order": "entry,risk,checklist,score,ai",
                "runtime_state": self.state.value,
                "mode": self.mode.value,
                "minimum_risk_reward": minimum_risk_reward,
                "readiness_state": readiness.overall_state.value,
                "readiness_reason": readiness.reason,
                "historical_integrity_status": (
                    self._historical_integrity_report.status.value
                    if self._historical_integrity_report is not None
                    else None
                ),
                "historical_integrity_complete": (
                    self._historical_integrity_report.complete
                    if self._historical_integrity_report is not None
                    else None
                ),
                "historical_gap_count": (
                    self._historical_integrity_report.gap_count
                    if self._historical_integrity_report is not None
                    else None
                ),
                "aoi_gate_eligible": aoi_gate.eligible,
                "aoi_reason_codes": ",".join(aoi_gate.reason_codes),
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
        return (
            self.mode in {RuntimeMode.LIVE_BITMART, RuntimeMode.HISTORICAL_LIVE}
            and self.settings.market_data.live_enabled
        )

    @property
    def demo_data_enabled(self) -> bool:
        return (
            self.mode is RuntimeMode.DRY_RUN
            and self.settings.demo.enabled
            and not self.settings.market_data_sync.enabled
        )

    @property
    def historical_data_enabled(self) -> bool:
        return (
            self.mode in {RuntimeMode.HISTORICAL, RuntimeMode.HISTORICAL_LIVE}
            and self.historical_config is not None
        )

    @property
    def market_data_sync_enabled(self) -> bool:
        return self.settings.market_data_sync.enabled

    def market_data_sync_status(self) -> SyncCoordinatorStatus | None:
        if self.market_data_sync_coordinator is None:
            return None
        return self.market_data_sync_coordinator.status()

    def start_market_data_sync(self) -> SyncCoordinatorStatus | None:
        if self.market_data_sync_coordinator is None:
            return None
        return self.market_data_sync_coordinator.run_once()

    def sync_market_data_symbol(self, symbol: str, *, gap_repair: bool = False) -> SymbolSyncStatus | None:
        if self.market_data_sync_coordinator is None:
            return None
        return self.market_data_sync_coordinator.sync_symbol(symbol, gap_repair=gap_repair)

    def market_data_contracts(self) -> tuple[str, ...]:
        if self.market_data_sync_coordinator is None:
            return ()
        return tuple(status.canonical_symbol for status in self.market_data_sync_coordinator.status().symbols)

    def _build_bitmart_stream_client(self) -> BitMartTradeStreamClient:
        return BitMartTradeStreamClient(
            config=BitMartTradeStreamClientConfig(
                symbol=self.active_symbol if hasattr(self, "settings") else "",
            ),
            event_bus=self.event_bus,
            pipeline=self.market_data_pipeline,
        )

    def _build_market_data_sync_coordinator_if_enabled(self) -> MarketDataSyncCoordinator | None:
        if not self.settings.market_data_sync.enabled:
            return None
        sync_settings = self.settings.market_data_sync
        exchange = ExchangeName(sync_settings.exchange)
        market_type = MarketType(sync_settings.market_type)
        metadata_store = SQLiteSyncMetadataStore(sync_settings.metadata_database_path)
        history_store = JsonlCandleHistoryStore(sync_settings.data_root)
        adapter = BitMartFuturesMarketDataAdapter(
            page_size=sync_settings.page_size,
            clock_ms=current_time_ms,
        )
        horizon_ms = sync_settings.history_horizon_days * 24 * 60 * 60 * 1000
        planner = IncrementalSyncPlanner(
            history_store=history_store,
            history_horizon_ms=horizon_ms,
            exchange=exchange,
            market_type=market_type,
            priority_symbols=sync_settings.priority_symbols,
        )
        return MarketDataSyncCoordinator(
            adapter=adapter,
            history_store=history_store,
            metadata_store=metadata_store,
            planner=planner,
            exchange=exchange,
            market_type=market_type,
            max_concurrent_jobs=sync_settings.max_concurrent_jobs,
            page_size=sync_settings.page_size,
            clock_ms=current_time_ms,
        )

    def _start_market_data_sync_if_enabled(self) -> None:
        if (
            self.market_data_sync_coordinator is not None
            and self.settings.market_data_sync.enabled
            and self.settings.market_data_sync.startup_enabled
        ):
            self.market_data_sync_coordinator.start_background()

    def _start_live_stream_if_enabled(self) -> None:
        if not self.stream_enabled:
            return
        self._live_stream_runner = self._live_stream_runner_factory(self.bitmart_stream_client)
        self._live_stream_runner.start()

    def _load_historical_data_if_enabled(self) -> None:
        if not self.historical_data_enabled or self._historical_loaded:
            return
        if self.historical_config is None:
            raise RuntimeError("Historical runtime mode requires historical_config")

        historical_result = self._historical_candles()
        candles = historical_result.candles
        self._historical_integrity_report = historical_result.integrity_report
        if historical_result.integrity_report.complete:
            for candle in candles:
                self._publish_historical_candle(candle)
        else:
            if isinstance(self.candle_store, InMemoryCandleStore):
                self.candle_store.save_many(candles)
            else:
                for candle in candles:
                    self._ensure_candle_stored(candle)
            self._logger.warning(
                "Loaded incomplete historical data without higher-timeframe aggregation "
                "policy=%s status=%s symbol=%s timeframe=%s requested_candle_count=%s "
                "loaded_candle_count=%s gap_count=%s total_missing_candles=%s",
                historical_result.integrity_report.policy.value,
                historical_result.integrity_report.status.value,
                historical_result.integrity_report.symbol,
                historical_result.integrity_report.timeframe.value,
                historical_result.integrity_report.requested_candle_count,
                historical_result.integrity_report.loaded_candle_count,
                historical_result.integrity_report.gap_count,
                historical_result.integrity_report.total_missing_candles,
            )
        self._historical_candle_count = len(candles)
        self._set_historical_live_boundary(candles)
        self._historical_loaded = True
        self._seed_cached_aois_if_possible()
        self._logger.info("Loaded historical candles into runtime")

    def _historical_candles(self) -> HistoricalCandleLoadResult:
        if self.historical_config is None:
            raise RuntimeError("Historical runtime mode requires historical_config")
        if self._historical_loader is not None:
            candles = self._historical_loader.load(self.historical_config.request)
            report = self._valid_historical_integrity_report(len(candles))
            return HistoricalCandleLoadResult(candles=candles, integrity_report=report)

        store = HistoricalCandleFileStore(self.historical_config.data_root)
        if not self.historical_config.download:
            return store.load_result(
                self.historical_config.request,
                integrity_policy=self.historical_config.integrity_policy,
            )

        downloader = BitMartHistoricalCandleDownloader()
        result = downloader.load_result(
            self.historical_config.request,
            integrity_policy=self.historical_config.integrity_policy,
        )
        store.save_result(self.historical_config.request, result)
        return result

    def _valid_historical_integrity_report(self, loaded_candle_count: int) -> HistoricalIntegrityReport:
        if self.historical_config is None:
            raise RuntimeError("Historical runtime mode requires historical_config")
        request = self.historical_config.request
        from backend.engines.historical.loader import expected_candle_count, exchange_request_from_historical_request

        return HistoricalIntegrityReport.valid(
            exchange_request_from_historical_request(
                request,
                integrity_policy=self.historical_config.integrity_policy,
            ),
            requested_candle_count=expected_candle_count(request),
            loaded_candle_count=loaded_candle_count,
        )

    def _publish_historical_candle(self, candle: Candle) -> None:
        """Publish completed historical candles through existing runtime paths."""

        if candle.timeframe is Timeframe.ONE_MINUTE:
            self.event_bus.publish(CandleClosedEvent(candle=candle))
            return
        self._ensure_candle_stored(candle)
        self.event_bus.publish(TimeframeCandleClosedEvent(candle=candle))

    def _set_historical_live_boundary(self, candles: tuple[Candle, ...]) -> None:
        """Set the earliest accepted live trade timestamp after historical preload."""

        if self.mode is not RuntimeMode.HISTORICAL_LIVE:
            return
        one_minute_close_times = (
            candle.close_time_ms for candle in candles if candle.timeframe is Timeframe.ONE_MINUTE
        )
        self._historical_live_min_trade_timestamp_ms = max(one_minute_close_times, default=None)

    def _accept_trade_for_runtime(self, trade: Trade) -> bool:
        """Keep historical/live continuity deterministic without changing candle rules."""

        if self.mode is not RuntimeMode.HISTORICAL_LIVE:
            return True
        if self._historical_live_min_trade_timestamp_ms is None:
            return True
        return trade.timestamp_ms >= self._historical_live_min_trade_timestamp_ms

    def _seed_demo_data_if_enabled(self) -> None:
        if not self.demo_data_enabled or self._demo_seeded:
            return
        seed_demo_visualization_data(
            symbol=self.active_symbol,
            candle_store=self.candle_store,
            structure_store=self.structure_store,
            trend_store=self.trend_store,
            alignment_store=self.alignment_store,
            market_state_service=self.market_state_service,
        )
        self._seed_cached_aois_if_possible()
        self._demo_seeded = True

    def _hydrate_market_state_from_existing_stores(self) -> None:
        for timeframe in MARKET_STRUCTURE_TIMEFRAMES:
            snapshot = self.structure_store.list(self.active_symbol, timeframe)
            for swing in snapshot.swings:
                self.market_state_service.update_swing(swing)
            for break_of_structure in snapshot.breaks_of_structure:
                self.market_state_service.update_break_of_structure(break_of_structure)
            trend = self.trend_store.get(self.active_symbol, timeframe).update
            if trend is not None:
                self.market_state_service.update_trend(trend)

    def _seed_cached_aois_if_possible(self) -> None:
        """Seed cached AOIs from existing stores for AOI-VIS-001 and AOI-GATE-001."""

        sizing = self._default_aoi_sizing_config()
        for timeframe in (AoiTimeframe.WEEKLY, AoiTimeframe.DAILY):
            try:
                self.evaluate_aois(
                    symbol=self.active_symbol,
                    timeframe=timeframe,
                    sizing=sizing,
                )
            except ValueError as exc:
                self._record_aoi_missing_inputs(self.active_symbol, timeframe, str(exc))
                self._logger.debug(
                    "AOI seed skipped for %s %s: %s",
                    self.active_symbol,
                    timeframe.value,
                    exc,
                )
        if self.demo_data_enabled:
            self._seed_synthetic_demo_aois_if_needed()

    def _seed_synthetic_demo_aois_if_needed(self) -> None:
        if self.list_aois(symbol=self.active_symbol):
            return
        for timeframe in (AoiTimeframe.WEEKLY, AoiTimeframe.DAILY):
            candle = self._latest_candle(self.active_symbol, timeframe.to_timeframe())
            if candle is None:
                continue
            half_width = max(1_000.0, candle.close * 0.04)
            lower = max(1.0, candle.close - half_width)
            upper = candle.close + half_width
            start_swing = StructureSwing(
                symbol=self.active_symbol,
                timeframe=timeframe.to_timeframe(),
                kind=SwingKind.LOW,
                label=StructureLabel.HL,
                level=lower,
                candle_open_time_ms=candle.open_time_ms,
                candle_close_time_ms=candle.close_time_ms,
            )
            end_swing = StructureSwing(
                symbol=self.active_symbol,
                timeframe=timeframe.to_timeframe(),
                kind=SwingKind.HIGH,
                label=StructureLabel.HH,
                level=upper,
                candle_open_time_ms=candle.open_time_ms,
                candle_close_time_ms=candle.close_time_ms,
            )
            leg = ActiveStructureLeg(
                symbol=self.active_symbol,
                timeframe=timeframe,
                trend_state=TrendState.BULLISH,
                start_swing=start_swing,
                end_swing=end_swing,
                leg_id=f"{self.active_symbol}:{timeframe.value}:demo-aoi-leg",
                trend_id=f"{self.active_symbol}:{timeframe.value}:demo-aoi-trend",
            )
            area = AreaOfInterest(
                aoi_id=f"{self.active_symbol}:{timeframe.value}:demo-active-aoi",
                symbol=self.active_symbol,
                timeframe=timeframe,
                direction=leg.direction,
                bounds=leg.price_bounds,
                state=AoiState.ACTIVE,
                origin_structure_leg_id=leg.leg_id,
                origin_trend_id=leg.trend_id,
                origin_timeframe=timeframe,
                contributing_candle_timestamps=(candle.open_time_ms,),
                first_touch_time_ms=candle.open_time_ms,
                confirmation_time_ms=candle.close_time_ms,
                touch_count=3,
                close_count=1,
                reaction_count=1,
                ranking=AoiRankingMetadata(
                    score=10.0,
                    body_close_count=1,
                    body_touch_count=3,
                    reaction_count=1,
                    recency_time_ms=candle.close_time_ms,
                    normalized_width=0.08,
                ),
                state_changed_time_ms=candle.close_time_ms,
            )
            self._aoi_evaluations[(self.active_symbol, timeframe)] = AoiEvaluation(
                leg=leg,
                areas=(area,),
            )

    def _default_aoi_sizing_config(self) -> AoiSizingConfig:
        """Generic percentage AOI sizing placeholder; instrument calibration remains unresolved."""

        return AoiSizingConfig(
            mode=AoiSizingMode.PERCENTAGE,
            minimum_percentage=0.0001,
            maximum_percentage=0.25,
        )

    def _default_aoi_location_config(self) -> AoiLocationConfig:
        return AoiLocationConfig(
            proximity_tolerance=0.0,
            maximum_post_reaction_excursion=0.0,
        )

    def _handle_market_data_status(self, event: MarketDataStatusEvent) -> None:
        self._stream_status = event.status

    def _bitmart_component_status(self, fallback: ComponentStatus) -> ComponentStatus:
        if self.mode in {RuntimeMode.DRY_RUN, RuntimeMode.HISTORICAL}:
            return ComponentStatus.DISABLED
        if not self.settings.market_data.live_enabled:
            return ComponentStatus.DISABLED
        if self._stream_status is MarketDataConnectionStatus.ERROR:
            return ComponentStatus.STOPPED
        return fallback

    def _bitmart_component_message(self) -> str:
        if self.mode is RuntimeMode.DRY_RUN:
            return "disabled in dry-run mode"
        if self.mode is RuntimeMode.HISTORICAL:
            return "disabled in historical mode"
        if not self.settings.market_data.live_enabled:
            return "disabled by config"
        if self._stream_status is MarketDataConnectionStatus.ERROR:
            return "bitmart_live_stream_unavailable"
        return f"bitmart:{self.settings.market_data_sync.market_type}:{self.active_symbol}"

    def _demo_component_status(self) -> ComponentStatus:
        if not self.demo_data_enabled:
            return ComponentStatus.DISABLED
        if self._demo_seeded:
            return ComponentStatus.READY
        return ComponentStatus.READY

    def _demo_component_message(self) -> str:
        if self.mode is not RuntimeMode.DRY_RUN:
            return "disabled outside dry-run mode"
        if self.settings.market_data_sync.enabled:
            return "disabled while exchange synchronization is enabled"
        if not self.settings.demo.enabled:
            return "disabled by config"
        if self._demo_seeded:
            return f"seeded deterministic visualization data for {self.active_symbol}"
        return "ready to seed deterministic visualization data"

    def _market_data_sync_component_status(self) -> ComponentStatus:
        if not self.settings.market_data_sync.enabled:
            return ComponentStatus.DISABLED
        if self.market_data_sync_coordinator is None:
            return ComponentStatus.STOPPED
        status = self.market_data_sync_coordinator.status()
        return ComponentStatus.RUNNING if status.running else ComponentStatus.READY

    def _market_data_sync_component_message(self) -> str:
        if not self.settings.market_data_sync.enabled:
            return "disabled by config"
        if self.market_data_sync_coordinator is None:
            return "not configured"
        status = self.market_data_sync_coordinator.status()
        return (
            f"{status.exchange.value}:{status.market_type.value} "
            f"ready={status.queue.ready} queued={status.queue.queued} failed={status.queue.failed}"
        )

    def _historical_component_status(self) -> ComponentStatus:
        if not self.historical_data_enabled:
            return ComponentStatus.DISABLED
        return ComponentStatus.READY if self._historical_loaded else ComponentStatus.READY

    def _historical_component_message(self) -> str:
        if self.mode not in {RuntimeMode.HISTORICAL, RuntimeMode.HISTORICAL_LIVE}:
            return "disabled outside historical mode"
        if self.historical_config is None:
            return "historical config missing"
        request = self.historical_config.request
        if self._historical_loaded:
            return f"loaded {self._historical_candle_count} {request.timeframe.value} candles for {request.symbol}"
        return f"ready to load {request.symbol} {request.timeframe.value}"

    def _historical_integrity_component_status(self) -> ComponentStatus:
        if self._historical_integrity_report is None:
            return ComponentStatus.DISABLED if not self.historical_data_enabled else ComponentStatus.READY
        return ComponentStatus.READY

    def _historical_integrity_component_message(self) -> str:
        report = self._historical_integrity_report
        if report is None:
            return "no historical integrity report"
        return (
            f"policy={report.policy.value} status={report.status.value} complete={report.complete} "
            f"requested={report.requested_candle_count} loaded={report.loaded_candle_count} "
            f"gaps={report.gap_count} missing={report.total_missing_candles}"
        )

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
        if candle.timeframe not in MARKET_STRUCTURE_TIMEFRAMES:
            return
        structure_engine = self._structure_engine_for(candle)
        for structure_event in structure_engine.add_candle(candle):
            self._store_structure_event(structure_event)
            self._handle_structure_event(structure_event)

    def _store_structure_event(self, event: StructureEvent) -> None:
        if event.swing is not None:
            self.structure_store.add_swing(event.swing)
            self.market_state_service.update_swing(event.swing)
        if event.break_of_structure is not None:
            self.structure_store.add_break_of_structure(event.break_of_structure)
            self.market_state_service.update_break_of_structure(event.break_of_structure)

    def _handle_structure_event(self, event: StructureEvent) -> None:
        trend_engine = self._trend_engine_for(event)
        trend_update = trend_engine.add_event(event)
        if trend_update is None:
            return

        self.trend_store.set(trend_update)
        self.market_state_service.update_trend(trend_update)
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
        if candle.timeframe not in MARKET_STRUCTURE_TIMEFRAMES:
            raise RuntimeError(f"Market structure is only owned by 1w, 1d, and 4h, not {candle.timeframe.value}")
        key = (candle.symbol, candle.timeframe)
        if key not in self._structure_engines:
            self._structure_engines[key] = MarketStructureEngine(
                bullish_displacement=PercentDisplacementThreshold(
                    percent=self.settings.structure.effective_bullish_displacement_percent,
                ),
                bearish_displacement=PercentDisplacementThreshold(
                    percent=self.settings.structure.effective_bearish_displacement_percent,
                ),
            )
        return self._structure_engines[key]

    def market_structure_diagnostics(self, symbol: str, timeframe: Timeframe) -> StructureDiagnostics:
        """Report confirmed-structure density without recalculating market structure."""

        candles = self.candle_store.list(symbol, timeframe)
        store_diagnostics = self.structure_store.diagnostics(
            symbol,
            timeframe,
            candle_count=len(candles),
            density_anomaly_ratio=self.settings.structure.density_anomaly_ratio,
            bos_anomaly_ratio=self.settings.structure.bos_anomaly_ratio,
        )
        engine = self._structure_engines.get((symbol, timeframe))
        if engine is None:
            return store_diagnostics
        engine_diagnostics = engine.diagnostics(
            duplicate_structures=store_diagnostics.duplicate_structures,
            duplicate_bos=store_diagnostics.duplicate_bos,
            density_anomaly_ratio=self.settings.structure.density_anomaly_ratio,
            bos_anomaly_ratio=self.settings.structure.bos_anomaly_ratio,
        )
        if engine_diagnostics.confirmed_swings == store_diagnostics.confirmed_swings:
            return engine_diagnostics
        return store_diagnostics

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

    def _active_structure_leg(
        self,
        symbol: str,
        timeframe: AoiTimeframe,
    ) -> ActiveStructureLeg:
        domain_timeframe = timeframe.to_timeframe()
        trend = self.trend_store.get(symbol, domain_timeframe).update
        if trend is None:
            raise ValueError(f"No precomputed trend is available for {symbol} {timeframe.value}")
        labels = (
            (StructureLabel.HL, StructureLabel.HH)
            if trend.state is TrendState.BULLISH
            else (StructureLabel.LH, StructureLabel.LL)
        )
        swings = self.market_state_service.structure_snapshot(symbol, domain_timeframe).swings
        end = next((item for item in reversed(swings) if item.label is labels[1]), None)
        start = next(
            (
                item
                for item in reversed(swings)
                if item.label is labels[0]
                and end is not None
                and item.candle_close_time_ms <= end.candle_close_time_ms
            ),
            None,
        )
        if start is None or end is None:
            raise ValueError(
                f"No active {labels[0].value}->{labels[1].value} leg is available for "
                f"{symbol} {timeframe.value}"
            )
        leg_id = f"{symbol}:{timeframe.value}:{start.candle_close_time_ms}:{end.candle_close_time_ms}"
        trend_id = f"{symbol}:{timeframe.value}:{trend.state.value}:{trend.event_time_ms}"
        return ActiveStructureLeg(
            symbol=symbol,
            timeframe=timeframe,
            trend_state=trend.state,
            start_swing=start,
            end_swing=end,
            leg_id=leg_id,
            trend_id=trend_id,
        )

    def _scanner_input_for(self, symbol: str, timeframe: Timeframe) -> SymbolScanInput:
        structure = self.market_state_service.structure_snapshot(symbol, timeframe)
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
            timeframe: self.market_state_service.structure_snapshot(symbol, timeframe)
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
            aoi_gate=self.evaluate_aoi_gate(symbol=symbol),
        )

    def _latest_candle(self, symbol: str, timeframe: Timeframe) -> Candle | None:
        candles = self.candle_store.list(symbol, timeframe)
        return candles[-1] if candles else None

    def _risk_structure_levels(self, symbol: str) -> tuple[StructureSwing, ...]:
        return tuple(
            swing
            for timeframe in (Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE, Timeframe.ONE_MINUTE)
            for swing in self.market_state_service.structure_snapshot(symbol, timeframe).swings
        )

    def _risk_bos_events(self, symbol: str) -> tuple[BreakOfStructure, ...]:
        return tuple(
            event
            for timeframe in (Timeframe.FIFTEEN_MINUTE, Timeframe.FIVE_MINUTE, Timeframe.ONE_MINUTE)
            for event in self.market_state_service.structure_snapshot(symbol, timeframe).breaks_of_structure
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


def current_time_ms() -> int:
    return int(time.time() * 1000)
