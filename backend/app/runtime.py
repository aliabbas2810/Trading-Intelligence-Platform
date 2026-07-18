from __future__ import annotations

import time
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

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
    HistoricalHorizon,
    HistoricalCandleRequest,
    HistoricalSyncPlanner,
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
from backend.exchange import (
    BitMartFuturesMarketDataAdapter,
    ExchangeName,
    HistoricalDataGap,
    HistoricalIntegrityPolicy,
    HistoricalIntegrityReport,
    HistoricalIntegrityStatus,
    MarketType,
)
from backend.models import Candle, Timeframe, Trade
from backend.pipelines.candle import CandleClosedEvent, OneMinuteCandlePipeline
from backend.pipelines.market_data import (
    BITMART_FUTURES_PUBLIC_WS_URL,
    BITMART_FUTURES_TRADE_CHANNEL,
    BitMartWebSocketLiveStreamRunner,
    BitMartTradeStreamClient,
    BitMartTradeStreamClientConfig,
    EventBusMarketDataPipeline,
    MarketDataConnectionStatus,
    MarketDataStatusEvent,
    TradeReceivedEvent,
)
from backend.pipelines.timeframe import TimeframeCandleClosedEvent, TimeframePipeline
from backend.storage import CandleAlreadyExistsError, InMemoryCandleStore, JsonlCandleHistoryStore
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
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"


class MarketDataRuntimeState(str, Enum):
    LOADING_CACHE = "loading_cache"
    CONNECTING_STREAM = "connecting_stream"
    SUBSCRIBING = "subscribing"
    BUFFERING = "buffering"
    SYNCHRONIZING = "synchronizing"
    HANDING_OFF = "handing_off"
    LIVE = "live"
    RECONNECTING = "reconnecting"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
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
    last_sync_window_integrity: HistoricalIntegrityReport | None = None
    complete_cache_integrity: HistoricalIntegrityReport | None = None
    replay_integrity: HistoricalIntegrityReport | None = None

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


@dataclass(frozen=True, slots=True)
class LiveCacheSyncDiagnostics:
    market_data_state: MarketDataRuntimeState = MarketDataRuntimeState.STOPPED
    websocket_endpoint: str = BITMART_FUTURES_PUBLIC_WS_URL
    subscription_channel: str = BITMART_FUTURES_TRADE_CHANNEL
    subscription_acknowledged: bool = False
    cache_candle_count: int = 0
    required_history_start_time_ms: int | None = None
    required_history_end_time_ms: int | None = None
    replay_start_time_ms: int | None = None
    replay_end_time_ms: int | None = None
    cache_last_open_time_ms: int | None = None
    latest_exchange_closed_open_time_ms: int | None = None
    sync_start_time_ms: int | None = None
    sync_end_time_ms: int | None = None
    sync_requested_count: int = 0
    sync_page_count: int = 0
    sync_retry_count: int = 0
    sync_loaded_count: int = 0
    sync_persisted_count: int = 0
    sync_inserted_count: int = 0
    sync_deduplicated_count: int = 0
    sync_gap_count: int = 0
    sync_window_gap_count: int = 0
    newly_discovered_gap_count: int = 0
    known_cache_gap_count: int = 0
    replay_gap_count: int = 0
    total_known_gap_count: int = 0
    sync_current_final_persisted_open_time_ms: int | None = None
    sync_target_final_open_time_ms: int | None = None
    sync_last_progress_time_ms: int | None = None
    shutdown_time_ms: int | None = None
    live_stream_connected: bool = False
    live_stream_connected_at_ms: int | None = None
    live_stream_last_message_time_ms: int | None = None
    live_stream_last_trade_time_ms: int | None = None
    buffered_trade_count: int = 0
    duplicate_trade_count: int = 0
    malformed_trade_count: int = 0
    reconnect_attempt_count: int = 0
    current_forming_candle_open_time_ms: int | None = None
    current_forming_candle_trade_count: int = 0
    last_finalized_candle_open_time_ms: int | None = None
    last_persisted_candle_open_time_ms: int | None = None
    rest_reconciliation_count: int = 0
    reconciled_candle_count: int = 0
    candle_conflict_count: int = 0
    discarded_aggregation_bucket_count: int = 0
    last_stream_error: str | None = None


class HistoricalCandleResultLoader(Protocol):
    def load_result(
        self,
        request: HistoricalCandleRequest,
        *,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> HistoricalCandleLoadResult:
        """Load or download candles plus integrity metadata."""

    def latest_completed_open_time_ms(self, symbol: str) -> int:
        """Return latest fully closed 1m candle open time."""


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
        self._buffering = False
        self._buffered_trades: list[Trade] = []
        self._seen_trade_keys: set[tuple[object, ...]] = set()
        self.duplicate_trade_count = 0

    def publish_trade(self, trade: Trade) -> None:
        if not self._accept_trade(trade):
            return
        key = self._trade_key(trade)
        if key in self._seen_trade_keys:
            self.duplicate_trade_count += 1
            return
        self._seen_trade_keys.add(key)
        if self._buffering:
            self._buffered_trades.append(trade)
            return
        super().publish_trade(trade)

    @property
    def buffered_trade_count(self) -> int:
        return len(self._buffered_trades)

    def start_buffering(self) -> None:
        self._buffering = True

    def finish_handoff(self, *, finalized_through_ms: int | None) -> tuple[Trade, ...]:
        replayable = tuple(
            sorted(
                (
                    trade
                    for trade in self._buffered_trades
                    if finalized_through_ms is None or trade.timestamp_ms >= finalized_through_ms
                ),
                key=lambda item: (item.timestamp_ms, item.price, item.quantity),
            )
        )
        self._buffered_trades.clear()
        self._buffering = False
        for trade in replayable:
            super().publish_trade(trade)
        return replayable

    def _trade_key(self, trade: Trade) -> tuple[object, ...]:
        return (trade.source, trade.symbol, trade.timestamp_ms, trade.price, trade.quantity)


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
        historical_downloader: HistoricalCandleResultLoader | None = None,
        market_data_sync_coordinator: MarketDataSyncCoordinator | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.mode = mode
        self.historical_config = historical_config
        self._historical_loader = historical_loader
        self._historical_downloader = historical_downloader
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
        self._lifecycle_lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._startup_exception: str | None = None
        self._subscribed = False
        self._demo_seeded = False
        self._historical_loaded = False
        self._historical_candle_count = 0
        self._historical_integrity_report: HistoricalIntegrityReport | None = None
        self._last_sync_window_integrity_report: HistoricalIntegrityReport | None = None
        self._complete_cache_integrity_report: HistoricalIntegrityReport | None = None
        self._replay_integrity_report: HistoricalIntegrityReport | None = None
        self._live_cache_sync = LiveCacheSyncDiagnostics()
        self._live_handoff_complete = False
        self._logger = get_logger(__name__)

    @property
    def state(self) -> RuntimeState:
        return self._state

    def start(self) -> None:
        """Start the local runtime and live stream when enabled for FR-101/RUNTIME-003."""

        with self._lifecycle_lock:
            if self._state in {RuntimeState.STARTING, RuntimeState.RUNNING}:
                raise RuntimeAlreadyStartedError("Backend runtime is already running")
            self._state = RuntimeState.STARTING
            self._stop_requested.clear()
            self._startup_exception = None

        try:
            configure_logging(self.settings)
            self._subscribe_components()
            self._hydrate_market_state_from_existing_stores()
            self._load_historical_data_if_enabled()
            if self.mode is RuntimeMode.LIVE_BITMART and self.stream_enabled:
                self.market_data_pipeline.start_buffering()
                self._start_live_stream_if_enabled()
                self._synchronize_live_cache_if_enabled()
                self._finish_live_handoff()
            else:
                self._synchronize_live_cache_if_enabled()
            self._seed_demo_data_if_enabled()
            with self._lifecycle_lock:
                self._state = RuntimeState.RUNNING
            self._start_market_data_sync_if_enabled()
            if self.mode is not RuntimeMode.LIVE_BITMART:
                self._start_live_stream_if_enabled()
            self._logger.info("Backend runtime started")
        except Exception as exc:
            self.record_startup_failure(exc)
            raise

    def stop(self) -> None:
        """Stop the local runtime for RUNTIME-003."""

        self._stop_requested.set()
        if self._live_stream_runner is not None:
            self._live_stream_runner.stop()
            self._stream_status = MarketDataConnectionStatus.STOPPED
        if self.market_data_sync_coordinator is not None:
            self.market_data_sync_coordinator.stop()
        self._live_cache_sync = self._live_cache_sync_update(
            market_data_state=MarketDataRuntimeState.STOPPED,
            live_stream_connected=False,
            shutdown_time_ms=current_time_ms(),
        )
        self._state = RuntimeState.STOPPED
        self._logger.info("Backend runtime stopped")

    @property
    def requires_background_initialization(self) -> bool:
        """Long live catch-up must not block FastAPI health availability."""

        return self.mode is RuntimeMode.LIVE_BITMART and self.stream_enabled

    def record_startup_failure(self, exc: Exception) -> None:
        """Capture background initialization failures for RUNTIME-004 diagnostics."""

        message = f"{type(exc).__name__}: {exc}"
        if self._live_stream_runner is not None:
            self._live_stream_runner.stop()
        self._stream_status = MarketDataConnectionStatus.STOPPED
        timestamp_ms = current_time_ms()
        with self._lifecycle_lock:
            if self._state is not RuntimeState.STOPPED:
                self._state = RuntimeState.FAILED
            self._startup_exception = message
        self._live_cache_sync = self._live_cache_sync_update(
            market_data_state=MarketDataRuntimeState.FAILED,
            sync_end_time_ms=self._live_cache_sync.sync_end_time_ms or timestamp_ms,
            shutdown_time_ms=timestamp_ms,
            live_stream_connected=False,
            last_stream_error=message,
        )
        self._logger.exception("Backend runtime startup failed")

    def health(self) -> RuntimeHealth:
        """Return component health/status for RUNTIME-004."""

        status = ComponentStatus.RUNNING if self._state is RuntimeState.RUNNING else ComponentStatus.READY
        if self._state is RuntimeState.STOPPED:
            status = ComponentStatus.STOPPED
        if self._state is RuntimeState.FAILED:
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
            ComponentHealth("startup_exception", ComponentStatus.READY, str(self._startup_exception)),
            ComponentHealth("market_data_state", ComponentStatus.READY, self._live_cache_sync.market_data_state.value),
            ComponentHealth("websocket_endpoint", ComponentStatus.READY, self._live_cache_sync.websocket_endpoint),
            ComponentHealth("subscription_channel", ComponentStatus.READY, self._live_cache_sync.subscription_channel),
            ComponentHealth(
                "subscription_acknowledged",
                ComponentStatus.READY,
                str(self._live_cache_sync.subscription_acknowledged),
            ),
            ComponentHealth("cache_candle_count", ComponentStatus.READY, str(self._live_cache_sync.cache_candle_count)),
            ComponentHealth(
                "required_history_start_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.required_history_start_time_ms),
            ),
            ComponentHealth(
                "required_history_end_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.required_history_end_time_ms),
            ),
            ComponentHealth(
                "replay_start_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.replay_start_time_ms),
            ),
            ComponentHealth(
                "replay_end_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.replay_end_time_ms),
            ),
            ComponentHealth(
                "cache_last_open_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.cache_last_open_time_ms),
            ),
            ComponentHealth(
                "latest_exchange_closed_open_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.latest_exchange_closed_open_time_ms),
            ),
            ComponentHealth("sync_start_time_ms", ComponentStatus.READY, str(self._live_cache_sync.sync_start_time_ms)),
            ComponentHealth("sync_end_time_ms", ComponentStatus.READY, str(self._live_cache_sync.sync_end_time_ms)),
            ComponentHealth("sync_requested_count", ComponentStatus.READY, str(self._live_cache_sync.sync_requested_count)),
            ComponentHealth("sync_page_count", ComponentStatus.READY, str(self._live_cache_sync.sync_page_count)),
            ComponentHealth("sync_retry_count", ComponentStatus.READY, str(self._live_cache_sync.sync_retry_count)),
            ComponentHealth("sync_loaded_count", ComponentStatus.READY, str(self._live_cache_sync.sync_loaded_count)),
            ComponentHealth("sync_persisted_count", ComponentStatus.READY, str(self._live_cache_sync.sync_persisted_count)),
            ComponentHealth("sync_inserted_count", ComponentStatus.READY, str(self._live_cache_sync.sync_inserted_count)),
            ComponentHealth(
                "sync_deduplicated_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.sync_deduplicated_count),
            ),
            ComponentHealth("sync_gap_count", ComponentStatus.READY, str(self._live_cache_sync.sync_gap_count)),
            ComponentHealth(
                "sync_window_gap_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.sync_window_gap_count),
            ),
            ComponentHealth(
                "newly_discovered_gap_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.newly_discovered_gap_count),
            ),
            ComponentHealth(
                "known_cache_gap_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.known_cache_gap_count),
            ),
            ComponentHealth("replay_gap_count", ComponentStatus.READY, str(self._live_cache_sync.replay_gap_count)),
            ComponentHealth(
                "total_known_gap_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.total_known_gap_count),
            ),
            ComponentHealth(
                "sync_current_final_persisted_open_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.sync_current_final_persisted_open_time_ms),
            ),
            ComponentHealth(
                "sync_target_final_open_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.sync_target_final_open_time_ms),
            ),
            ComponentHealth(
                "sync_last_progress_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.sync_last_progress_time_ms),
            ),
            ComponentHealth("sync_start_time_iso", ComponentStatus.READY, iso_timestamp(self._live_cache_sync.sync_start_time_ms)),
            ComponentHealth("sync_end_time_iso", ComponentStatus.READY, iso_timestamp(self._live_cache_sync.sync_end_time_ms)),
            ComponentHealth(
                "sync_last_progress_time_iso",
                ComponentStatus.READY,
                iso_timestamp(self._live_cache_sync.sync_last_progress_time_ms),
            ),
            ComponentHealth(
                "cache_last_open_time_iso",
                ComponentStatus.READY,
                iso_timestamp(self._live_cache_sync.cache_last_open_time_ms),
            ),
            ComponentHealth(
                "required_history_start_time_iso",
                ComponentStatus.READY,
                iso_timestamp(self._live_cache_sync.required_history_start_time_ms),
            ),
            ComponentHealth(
                "required_history_end_time_iso",
                ComponentStatus.READY,
                iso_timestamp(self._live_cache_sync.required_history_end_time_ms),
            ),
            ComponentHealth(
                "replay_start_time_iso",
                ComponentStatus.READY,
                iso_timestamp(self._live_cache_sync.replay_start_time_ms),
            ),
            ComponentHealth(
                "replay_end_time_iso",
                ComponentStatus.READY,
                iso_timestamp(self._live_cache_sync.replay_end_time_ms),
            ),
            ComponentHealth(
                "latest_exchange_closed_open_time_iso",
                ComponentStatus.READY,
                iso_timestamp(self._live_cache_sync.latest_exchange_closed_open_time_ms),
            ),
            ComponentHealth(
                "last_persisted_candle_open_time_iso",
                ComponentStatus.READY,
                iso_timestamp(self._live_cache_sync.last_persisted_candle_open_time_ms),
            ),
            ComponentHealth("shutdown_time_ms", ComponentStatus.READY, str(self._live_cache_sync.shutdown_time_ms)),
            ComponentHealth("shutdown_time_iso", ComponentStatus.READY, iso_timestamp(self._live_cache_sync.shutdown_time_ms)),
            ComponentHealth(
                "live_stream_connected",
                ComponentStatus.READY,
                str(self._live_cache_sync.live_stream_connected),
            ),
            ComponentHealth(
                "live_stream_connected_at_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.live_stream_connected_at_ms),
            ),
            ComponentHealth(
                "live_stream_last_message_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.live_stream_last_message_time_ms),
            ),
            ComponentHealth(
                "live_stream_last_trade_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.live_stream_last_trade_time_ms),
            ),
            ComponentHealth("buffered_trade_count", ComponentStatus.READY, str(self._live_cache_sync.buffered_trade_count)),
            ComponentHealth("duplicate_trade_count", ComponentStatus.READY, str(self._live_cache_sync.duplicate_trade_count)),
            ComponentHealth("malformed_trade_count", ComponentStatus.READY, str(self._live_cache_sync.malformed_trade_count)),
            ComponentHealth(
                "reconnect_attempt_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.reconnect_attempt_count),
            ),
            ComponentHealth(
                "current_forming_candle_open_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.current_forming_candle_open_time_ms),
            ),
            ComponentHealth(
                "current_forming_candle_trade_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.current_forming_candle_trade_count),
            ),
            ComponentHealth(
                "last_finalized_candle_open_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.last_finalized_candle_open_time_ms),
            ),
            ComponentHealth(
                "last_persisted_candle_open_time_ms",
                ComponentStatus.READY,
                str(self._live_cache_sync.last_persisted_candle_open_time_ms),
            ),
            ComponentHealth(
                "rest_reconciliation_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.rest_reconciliation_count),
            ),
            ComponentHealth(
                "reconciled_candle_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.reconciled_candle_count),
            ),
            ComponentHealth("candle_conflict_count", ComponentStatus.READY, str(self._live_cache_sync.candle_conflict_count)),
            ComponentHealth(
                "discarded_aggregation_bucket_count",
                ComponentStatus.READY,
                str(self._live_cache_sync.discarded_aggregation_bucket_count),
            ),
            ComponentHealth("last_stream_error", ComponentStatus.READY, str(self._live_cache_sync.last_stream_error)),
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
            ComponentHealth(
                "last_sync_window_integrity",
                self._integrity_component_status(self._last_sync_window_integrity_report),
                self._integrity_component_message(self._last_sync_window_integrity_report),
            ),
            ComponentHealth(
                "complete_cache_integrity",
                self._integrity_component_status(self._complete_cache_integrity_report),
                self._integrity_component_message(self._complete_cache_integrity_report),
            ),
            ComponentHealth(
                "replay_integrity",
                self._integrity_component_status(self._replay_integrity_report),
                self._integrity_component_message(self._replay_integrity_report),
            ),
        ]
        return RuntimeHealth(
            state=self._state,
            mode=self.mode,
            components=tuple(components),
            historical_integrity=self._historical_integrity_report,
            last_sync_window_integrity=self._last_sync_window_integrity_report,
            complete_cache_integrity=self._complete_cache_integrity_report,
            replay_integrity=self._replay_integrity_report,
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
        self._last_sync_window_integrity_report = None
        self._complete_cache_integrity_report = None
        self._replay_integrity_report = None
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
        self.event_bus.subscribe(TradeReceivedEvent, self._handle_live_trade_received)
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
        horizon_settings = sync_settings.history_horizon
        planner = IncrementalSyncPlanner(
            history_store=history_store,
            exchange=exchange,
            market_type=market_type,
            history_horizon=HistoricalHorizon(
                years=horizon_settings.years,
                months=horizon_settings.months,
                days=horizon_settings.days,
            ),
            legacy_horizon_days=sync_settings.history_horizon_days,
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
        self._live_cache_sync = self._live_cache_sync_update(
            market_data_state=MarketDataRuntimeState.CONNECTING_STREAM,
            websocket_endpoint=self.bitmart_stream_client.diagnostics.websocket_endpoint,
            subscription_channel=self.bitmart_stream_client.diagnostics.subscription_channel,
        )
        self._live_stream_runner = self._live_stream_runner_factory(self.bitmart_stream_client)
        self._live_stream_runner.start()
        if self._stream_status is MarketDataConnectionStatus.ERROR:
            self._live_cache_sync = self._live_cache_sync_update(
                market_data_state=MarketDataRuntimeState.UNAVAILABLE,
                live_stream_connected=False,
            )
        elif self.mode is RuntimeMode.LIVE_BITMART:
            self._live_cache_sync = self._live_cache_sync_update(
                market_data_state=MarketDataRuntimeState.BUFFERING,
                buffered_trade_count=self.market_data_pipeline.buffered_trade_count,
            )

    def _load_historical_data_if_enabled(self) -> None:
        if not self.historical_data_enabled or self._historical_loaded:
            return
        if self.historical_config is None:
            raise RuntimeError("Historical runtime mode requires historical_config")

        historical_result = self._historical_candles()
        candles = historical_result.candles
        self._complete_cache_integrity_report = historical_result.integrity_report
        self._historical_integrity_report = historical_result.integrity_report
        if historical_result.integrity_report.complete:
            self._replay_historical_candles(
                candles,
                integrity_policy=historical_result.integrity_report.policy,
                source_request=self._historical_request_for_candles(candles),
            )
        else:
            self._replay_historical_candles(
                candles,
                integrity_policy=historical_result.integrity_report.policy,
                source_request=self._historical_request_for_candles(candles),
            )
            self._logger.warning(
                "Loaded incomplete historical data with policy-aware segmented replay "
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

    def _synchronize_live_cache_if_enabled(self) -> None:
        if self.mode is not RuntimeMode.LIVE_BITMART:
            return
        if not self.settings.market_data.live_enabled:
            return

        symbol = self.active_symbol
        timeframe = Timeframe.ONE_MINUTE
        exchange = self.settings.market_data.exchange
        market_type = self.settings.market_data.market_type
        store = HistoricalCandleFileStore(self.settings.historical_data.data_root)
        downloader = self._historical_downloader or BitMartHistoricalCandleDownloader()
        duration_ms = 60_000
        integrity_policy = HistoricalIntegrityPolicy(self.settings.historical_data.integrity_policy)
        planner = HistoricalSyncPlanner()

        started_ms = current_time_ms()
        self._live_cache_sync = self._live_cache_sync_update(
            market_data_state=MarketDataRuntimeState.LOADING_CACHE,
            sync_start_time_ms=started_ms,
        )
        cached_result = store.merged_result(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
            integrity_policy=HistoricalIntegrityPolicy.WARN,
        )
        cached_candles = cached_result.candles if cached_result is not None else ()
        cache_last_open_time_ms = cached_candles[-1].open_time_ms if cached_candles else None
        latest_closed_open_time_ms = downloader.latest_completed_open_time_ms(symbol)
        horizon_settings = self.settings.market_data_sync.history_horizon
        sync_plan = planner.create_plan(
            latest_closed_open_time_ms=latest_closed_open_time_ms,
            timeframe=timeframe,
            horizon=HistoricalHorizon(
                years=horizon_settings.years,
                months=horizon_settings.months,
                days=horizon_settings.days,
            ),
            cached_open_times_ms=tuple(candle.open_time_ms for candle in cached_candles),
            legacy_horizon_days=self.settings.market_data_sync.history_horizon_days,
        )
        self._live_cache_sync = self._live_cache_sync_update(
            market_data_state=MarketDataRuntimeState.SYNCHRONIZING,
            cache_candle_count=len(cached_candles),
            cache_last_open_time_ms=cache_last_open_time_ms,
            required_history_start_time_ms=sync_plan.required_start_time_ms,
            required_history_end_time_ms=sync_plan.required_end_time_ms,
            replay_start_time_ms=sync_plan.replay_start_time_ms,
            replay_end_time_ms=sync_plan.replay_end_time_ms,
            latest_exchange_closed_open_time_ms=latest_closed_open_time_ms,
            current_forming_candle_open_time_ms=latest_closed_open_time_ms + duration_ms,
        )

        requested_count = sync_plan.requested_candle_count
        downloaded_parts: list[Candle] = []
        page_count = 0
        retry_count = 0
        if sync_plan.download_windows:
            self._live_cache_sync = self._live_cache_sync_update(
                sync_requested_count=requested_count,
                sync_target_final_open_time_ms=latest_closed_open_time_ms,
            )
            for window in sync_plan.download_windows:
                cursor_ms = window.start_time_ms
                while cursor_ms < window.end_time_ms:
                    if self._stop_requested.is_set():
                        break
                    page_end_ms = min(self._next_live_sync_window_end(cursor_ms), window.end_time_ms)
                    if page_end_ms <= cursor_ms:
                        raise RuntimeError(
                            "Live cache synchronization cursor did not advance "
                            f"cursor_ms={cursor_ms} page_end_ms={page_end_ms}",
                        )
                    catchup_request = HistoricalCandleRequest(
                        symbol=symbol,
                        timeframe=timeframe,
                        start_time_ms=cursor_ms,
                        end_time_ms=page_end_ms,
                        exchange=exchange,
                        market_type=market_type,
                    )
                    catchup_result = downloader.load_result(
                        catchup_request,
                        integrity_policy=integrity_policy,
                    )
                    self._last_sync_window_integrity_report = catchup_result.integrity_report
                    if self._stop_requested.is_set():
                        break
                    downloaded_parts.extend(catchup_result.candles)
                    page_count += max(1, getattr(catchup_result, "pages", 0))
                    retry_count += sum(gap.retry_count for gap in catchup_result.integrity_report.gaps)
                    if catchup_result.candles:
                        store.save_daily_segments(
                            catchup_result.candles,
                            exchange=exchange,
                            market_type=market_type,
                        )
                    self._logger.info(
                        "Live historical sync page completed "
                        "symbol=%s timeframe=%s reason=%s page_start_ms=%s page_end_ms=%s "
                        "loaded_count=%s accumulated_count=%s",
                        symbol,
                        timeframe.value,
                        window.reason,
                        cursor_ms,
                        page_end_ms,
                        len(catchup_result.candles),
                        len(downloaded_parts),
                    )
                    self._live_cache_sync = self._live_cache_sync_update(
                        sync_page_count=page_count,
                        sync_retry_count=retry_count,
                        sync_loaded_count=len(downloaded_parts),
                        sync_persisted_count=len(downloaded_parts),
                        sync_gap_count=catchup_result.integrity_report.gap_count,
                        sync_window_gap_count=catchup_result.integrity_report.gap_count,
                        newly_discovered_gap_count=catchup_result.integrity_report.gap_count,
                        sync_current_final_persisted_open_time_ms=(
                            catchup_result.candles[-1].open_time_ms if catchup_result.candles else None
                        ),
                        sync_last_progress_time_ms=current_time_ms(),
                    )
                    cursor_ms = page_end_ms
                if self._stop_requested.is_set():
                    break
        downloaded = tuple(downloaded_parts)

        repaired_result = store.merged_result(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
            integrity_policy=HistoricalIntegrityPolicy.WARN,
        )
        repaired_candles = repaired_result.candles if repaired_result is not None else ()
        repaired_plan = planner.plan(
            required_start_time_ms=sync_plan.required_start_time_ms,
            required_end_time_ms=sync_plan.required_end_time_ms,
            cached_open_times_ms=tuple(candle.open_time_ms for candle in repaired_candles),
            timeframe=timeframe,
        )
        replay_candles = sync_plan.select_replay_candles(repaired_candles)
        cached_open_times = {
            candle.open_time_ms
            for candle in cached_candles
            if sync_plan.replay_start_time_ms <= candle.open_time_ms < sync_plan.replay_end_time_ms
        }
        downloaded_open_times = {candle.open_time_ms for candle in downloaded}
        deduplicated = len(cached_open_times.intersection(downloaded_open_times))
        inserted = len(downloaded_open_times.difference(cached_open_times))
        merged_request = HistoricalCandleRequest(
            symbol=symbol,
            timeframe=timeframe,
            start_time_ms=sync_plan.replay_start_time_ms,
            end_time_ms=sync_plan.replay_end_time_ms,
            exchange=exchange,
            market_type=market_type,
        )
        merged_report = self._merged_live_integrity_report(
            merged_request,
            replay_candles,
        )
        self._historical_integrity_report = merged_report
        self._complete_cache_integrity_report = merged_report
        if integrity_policy is HistoricalIntegrityPolicy.STRICT and not merged_report.complete:
            raise ValueError(
                "Strict live startup rejected incomplete required historical cache "
                f"symbol={symbol} timeframe={timeframe.value} "
                f"required_start_time_ms={sync_plan.replay_start_time_ms} "
                f"required_end_time_ms={sync_plan.replay_end_time_ms} "
                f"remaining_window_count={len(repaired_plan.download_windows)} "
                f"missing_candle_count={merged_report.total_missing_candles}",
            )
        if replay_candles:
            self._historical_candle_count = len(replay_candles)
            self._historical_live_min_trade_timestamp_ms = (
                sync_plan.replay_end_time_ms if merged_report.complete else replay_candles[-1].close_time_ms
            )
            self._replay_historical_candles(
                replay_candles,
                integrity_policy=integrity_policy,
                source_request=merged_request,
            )
            self._seed_cached_aois_if_possible()

        self._live_cache_sync = self._live_cache_sync_update(
            market_data_state=MarketDataRuntimeState.HANDING_OFF,
            cache_candle_count=len(replay_candles),
            cache_last_open_time_ms=replay_candles[-1].open_time_ms if replay_candles else None,
            latest_exchange_closed_open_time_ms=latest_closed_open_time_ms,
            required_history_start_time_ms=sync_plan.required_start_time_ms,
            required_history_end_time_ms=sync_plan.required_end_time_ms,
            replay_start_time_ms=sync_plan.replay_start_time_ms,
            replay_end_time_ms=sync_plan.replay_end_time_ms,
            sync_end_time_ms=current_time_ms(),
            sync_requested_count=requested_count,
            sync_page_count=page_count,
            sync_retry_count=retry_count,
            sync_loaded_count=len(downloaded),
            sync_persisted_count=len(downloaded),
            sync_inserted_count=inserted,
            sync_deduplicated_count=deduplicated,
            sync_gap_count=self._historical_integrity_report.gap_count if self._historical_integrity_report else 0,
            sync_window_gap_count=(
                self._last_sync_window_integrity_report.gap_count
                if self._last_sync_window_integrity_report is not None
                else 0
            ),
            known_cache_gap_count=(
                self._complete_cache_integrity_report.gap_count
                if self._complete_cache_integrity_report is not None
                else 0
            ),
            replay_gap_count=(
                self._replay_integrity_report.gap_count
                if self._replay_integrity_report is not None
                else 0
            ),
            total_known_gap_count=(
                self._complete_cache_integrity_report.gap_count
                if self._complete_cache_integrity_report is not None
                else 0
            ),
            sync_current_final_persisted_open_time_ms=replay_candles[-1].open_time_ms if replay_candles else None,
            sync_target_final_open_time_ms=latest_closed_open_time_ms,
            sync_last_progress_time_ms=current_time_ms(),
            last_finalized_candle_open_time_ms=replay_candles[-1].open_time_ms if replay_candles else None,
            last_persisted_candle_open_time_ms=replay_candles[-1].open_time_ms if replay_candles else None,
            rest_reconciliation_count=self._live_cache_sync.rest_reconciliation_count + 1,
            reconciled_candle_count=len(downloaded),
        )

    def _next_live_sync_window_end(self, start_time_ms: int) -> int:
        """Return the next resumable UTC-day checkpoint boundary for live catch-up."""

        utc_day_ms = 24 * 60 * 60 * 1000
        day_end_ms = start_time_ms - (start_time_ms % utc_day_ms) + utc_day_ms
        return min(start_time_ms + utc_day_ms, day_end_ms)

    def _finish_live_handoff(self) -> None:
        if self.mode is not RuntimeMode.LIVE_BITMART:
            return
        replayed = self.market_data_pipeline.finish_handoff(
            finalized_through_ms=self._historical_live_min_trade_timestamp_ms,
        )
        self._live_handoff_complete = True
        diagnostics = self.bitmart_stream_client.diagnostics
        state = (
            MarketDataRuntimeState.LIVE
            if diagnostics.subscription_acknowledged and self._stream_status is MarketDataConnectionStatus.CONNECTED
            else MarketDataRuntimeState.CONNECTING_STREAM
        )
        self._live_cache_sync = self._live_cache_sync_update(
            market_data_state=state,
            subscription_acknowledged=diagnostics.subscription_acknowledged,
            live_stream_connected=diagnostics.connected,
            live_stream_connected_at_ms=diagnostics.connected_at_ms,
            live_stream_last_message_time_ms=diagnostics.last_message_time_ms,
            live_stream_last_trade_time_ms=diagnostics.last_trade_time_ms,
            buffered_trade_count=0,
            duplicate_trade_count=diagnostics.duplicate_trade_count + self.market_data_pipeline.duplicate_trade_count,
            malformed_trade_count=diagnostics.malformed_trade_count,
            reconnect_attempt_count=diagnostics.reconnect_attempt_count,
            current_forming_candle_trade_count=len(replayed),
            last_stream_error=diagnostics.last_stream_error,
        )

    def _merged_live_integrity_report(
        self,
        request: HistoricalCandleRequest,
        candles: tuple[Candle, ...],
    ) -> HistoricalIntegrityReport:
        from backend.engines.historical.loader import inferred_integrity_report

        report = inferred_integrity_report(
            request,
            candles,
            integrity_policy=HistoricalIntegrityPolicy(self.settings.historical_data.integrity_policy),
        )
        return report

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

    def _replay_historical_candles(
        self,
        candles: tuple[Candle, ...],
        *,
        integrity_policy: HistoricalIntegrityPolicy,
        source_request: HistoricalCandleRequest,
    ) -> None:
        """Replay completed cache candles through segmented downstream paths."""

        from backend.engines.historical.loader import (
            expected_candle_count,
            exchange_request_from_historical_request,
            historical_gap_from_missing_times,
            historical_status_for_policy,
            inferred_integrity_report,
        )

        sorted_candles = tuple(sorted(candles, key=lambda item: (item.timeframe.value, item.open_time_ms)))
        one_minute_candles = tuple(candle for candle in sorted_candles if candle.timeframe is Timeframe.ONE_MINUTE)
        gaps: list[HistoricalDataGap] = []
        previous: Candle | None = None
        for candle in one_minute_candles:
            if previous is not None and candle.open_time_ms != previous.close_time_ms:
                missing_times = tuple(range(previous.close_time_ms, candle.open_time_ms, 60_000))
                gap = historical_gap_from_missing_times(source_request, missing_times)
                gaps.append(gap)
                if integrity_policy is HistoricalIntegrityPolicy.STRICT:
                    self._replay_integrity_report = HistoricalIntegrityReport.from_gaps(
                        exchange_request_from_historical_request(
                            source_request,
                            integrity_policy=integrity_policy,
                        ),
                        status=HistoricalIntegrityStatus.FAILED,
                        gaps=tuple(gaps),
                        requested_candle_count=expected_candle_count(source_request),
                        loaded_candle_count=len(one_minute_candles),
                    )
                    self._historical_integrity_report = self._replay_integrity_report
                    raise ValueError(
                        "Strict historical replay rejected discontinuity "
                        f"previous_open_time_ms={previous.open_time_ms} "
                        f"expected_open_time_ms={previous.close_time_ms} "
                        f"actual_open_time_ms={candle.open_time_ms} "
                        f"missing_candle_count={len(missing_times)}",
                    )
                self._handle_historical_replay_gap(previous, candle, gap, integrity_policy)
            self._publish_historical_candle(candle)
            previous = candle

        if not gaps:
            self._replay_integrity_report = inferred_integrity_report(
                source_request,
                one_minute_candles,
                integrity_policy=integrity_policy,
            )
            return
        self._replay_integrity_report = HistoricalIntegrityReport.from_gaps(
            exchange_request_from_historical_request(
                source_request,
                integrity_policy=integrity_policy,
            ),
            status=historical_status_for_policy(integrity_policy),
            gaps=tuple(gaps),
            requested_candle_count=expected_candle_count(source_request),
            loaded_candle_count=len(one_minute_candles),
        )
        self._historical_integrity_report = self._replay_integrity_report
        self._live_cache_sync = self._live_cache_sync_update(
            replay_gap_count=len(gaps),
            total_known_gap_count=max(self._live_cache_sync.total_known_gap_count, len(gaps)),
        )

    def _handle_historical_replay_gap(
        self,
        previous: Candle,
        current: Candle,
        gap: HistoricalDataGap,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> None:
        discarded = self.timeframe_pipeline.reset_for_discontinuity()
        self._structure_engines = {}
        self._trend_engines = {}
        self._trend_snapshots = {}
        self.multi_timeframe_aggregator = MultiTimeframeTrendAggregator()
        self.market_state_service.reset()
        self.alignment_store = InMemoryAlignmentReadStore()
        self.visualization_api = VisualizationReadApi(
            candle_store=self.candle_store,
            structure_store=self.structure_store,
            trend_store=self.trend_store,
            alignment_store=self.alignment_store,
        )
        self._live_cache_sync = self._live_cache_sync_update(
            replay_gap_count=self._live_cache_sync.replay_gap_count + 1,
            discarded_aggregation_bucket_count=(
                self._live_cache_sync.discarded_aggregation_bucket_count + len(discarded)
            ),
        )
        self._logger.warning(
            "Historical replay accepted gap boundary",
            extra={
                "policy": integrity_policy.value,
                "previous_open_time_ms": previous.open_time_ms,
                "expected_open_time_ms": previous.close_time_ms,
                "actual_open_time_ms": current.open_time_ms,
                "missing_candle_count": gap.missing_candle_count,
                "discarded_aggregation_buckets": tuple(
                    {
                        "timeframe": item.timeframe.value,
                        "open_time_ms": item.open_time_ms,
                        "close_time_ms": item.close_time_ms,
                    }
                    for item in discarded
                ),
            },
        )

    def _historical_request_for_candles(self, candles: tuple[Candle, ...]) -> HistoricalCandleRequest:
        if not candles:
            if self.historical_config is None:
                raise ValueError("Cannot infer historical request for empty candle set")
            return self.historical_config.request
        one_minute_candles = tuple(candle for candle in candles if candle.timeframe is Timeframe.ONE_MINUTE)
        source = tuple(sorted(one_minute_candles or candles, key=lambda item: item.open_time_ms))
        from backend.pipelines.timeframe.aggregation import timeframe_duration_ms

        duration_ms = timeframe_duration_ms(source[0].timeframe)
        return HistoricalCandleRequest(
            symbol=source[0].symbol,
            timeframe=source[0].timeframe,
            start_time_ms=source[0].open_time_ms,
            end_time_ms=source[-1].open_time_ms + duration_ms,
            exchange=self.settings.market_data.exchange,
            market_type=self.settings.market_data.market_type,
        )

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

        if self.mode not in {RuntimeMode.HISTORICAL_LIVE, RuntimeMode.LIVE_BITMART}:
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
        state = self._live_cache_sync.market_data_state
        if event.status is MarketDataConnectionStatus.CONNECTED:
            state = (
                MarketDataRuntimeState.BUFFERING
                if self.market_data_pipeline.buffered_trade_count or not self._live_handoff_complete
                else MarketDataRuntimeState.LIVE
            )
        elif event.status is MarketDataConnectionStatus.CONNECTING:
            state = MarketDataRuntimeState.CONNECTING_STREAM
        elif event.status is MarketDataConnectionStatus.RECONNECTING:
            state = MarketDataRuntimeState.RECONNECTING
        elif event.status is MarketDataConnectionStatus.DISCONNECTED:
            state = MarketDataRuntimeState.DEGRADED
        elif event.status is MarketDataConnectionStatus.ERROR:
            state = MarketDataRuntimeState.UNAVAILABLE
        elif event.status is MarketDataConnectionStatus.STOPPED:
            state = MarketDataRuntimeState.STOPPED
        diagnostics = self.bitmart_stream_client.diagnostics
        self._live_cache_sync = self._live_cache_sync_update(
            market_data_state=state,
            live_stream_connected=event.status is MarketDataConnectionStatus.CONNECTED,
            websocket_endpoint=diagnostics.websocket_endpoint,
            subscription_channel=diagnostics.subscription_channel,
            subscription_acknowledged=diagnostics.subscription_acknowledged,
            live_stream_connected_at_ms=diagnostics.connected_at_ms,
            live_stream_last_message_time_ms=diagnostics.last_message_time_ms,
            live_stream_last_trade_time_ms=diagnostics.last_trade_time_ms,
            buffered_trade_count=self.market_data_pipeline.buffered_trade_count,
            duplicate_trade_count=diagnostics.duplicate_trade_count + self.market_data_pipeline.duplicate_trade_count,
            malformed_trade_count=diagnostics.malformed_trade_count,
            reconnect_attempt_count=diagnostics.reconnect_attempt_count,
            last_stream_error=diagnostics.last_stream_error,
        )

    def _handle_live_trade_received(self, event: TradeReceivedEvent) -> None:
        if self.mode not in {RuntimeMode.LIVE_BITMART, RuntimeMode.HISTORICAL_LIVE}:
            return
        forming_open_time_ms = (event.trade.timestamp_ms // 60_000) * 60_000
        self._live_cache_sync = self._live_cache_sync_update(
            live_stream_last_message_time_ms=event.trade.timestamp_ms,
            live_stream_last_trade_time_ms=event.trade.timestamp_ms,
            current_forming_candle_open_time_ms=forming_open_time_ms,
            buffered_trade_count=self.market_data_pipeline.buffered_trade_count,
            current_forming_candle_trade_count=self._live_cache_sync.current_forming_candle_trade_count + 1,
        )

    def _live_cache_sync_update(self, **updates: Any) -> LiveCacheSyncDiagnostics:
        return replace(self._live_cache_sync, **updates)

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
        return f"bitmart:{self.settings.market_data.market_type}:{self.active_symbol}"

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
        return self._integrity_component_message(report)

    def _integrity_component_status(self, report: HistoricalIntegrityReport | None) -> ComponentStatus:
        if report is None:
            return ComponentStatus.DISABLED
        return ComponentStatus.READY

    def _integrity_component_message(self, report: HistoricalIntegrityReport | None) -> str:
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
        if self.mode in {RuntimeMode.LIVE_BITMART, RuntimeMode.HISTORICAL_LIVE}:
            if self.mode is RuntimeMode.LIVE_BITMART and event.candle.timeframe is Timeframe.ONE_MINUTE:
                self._persist_live_closed_candle(event.candle)
            self._live_cache_sync = self._live_cache_sync_update(
                last_finalized_candle_open_time_ms=event.candle.open_time_ms,
                current_forming_candle_open_time_ms=event.candle.close_time_ms,
            )
        self._handle_completed_candle(event.candle)

    def _persist_live_closed_candle(self, candle: Candle) -> None:
        store = HistoricalCandleFileStore(self.settings.historical_data.data_root)
        try:
            store.save_candle_segment(
                candle,
                exchange=self.settings.market_data.exchange,
                market_type=self.settings.market_data.market_type,
            )
            self._live_cache_sync = self._live_cache_sync_update(
                last_persisted_candle_open_time_ms=candle.open_time_ms,
            )
        except ValueError as exc:
            self._live_cache_sync = self._live_cache_sync_update(
                candle_conflict_count=self._live_cache_sync.candle_conflict_count + 1,
                last_stream_error=str(exc),
            )
            self._logger.warning("Live candle persistence conflict: %s", exc)

    def _handle_timeframe_candle_closed(self, event: TimeframeCandleClosedEvent) -> None:
        self._handle_completed_candle(event.candle)

    def _ensure_candle_stored(self, candle: Candle) -> None:
        try:
            self.candle_store.save(candle)
        except CandleAlreadyExistsError:
            return

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


def iso_timestamp(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "None"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
