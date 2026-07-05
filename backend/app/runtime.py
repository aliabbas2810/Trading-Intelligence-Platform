from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from backend.api import (
    InMemoryAlignmentReadStore,
    InMemoryStructureReadStore,
    InMemoryTrendReadStore,
    VisualizationReadApi,
)
from backend.config import PlatformSettings, load_settings
from backend.core import EventBus, configure_logging, get_logger
from backend.engines.ai import AiDecisionEngine, RuleBasedMockAiDecisionProvider
from backend.engines.replay import HistoricalTradeReplaySource, ReplayController
from backend.engines.scanner import ScannerEngine
from backend.engines.structure import MarketStructureEngine, StructureEvent
from backend.engines.trend import (
    MultiTimeframeTrendAggregatedEvent,
    MultiTimeframeTrendAggregator,
    TimeframeTrendSnapshot,
    TrendChangedEvent,
    TrendEngine,
)
from backend.models import Candle, Timeframe
from backend.pipelines.candle import CandleClosedEvent, OneMinuteCandlePipeline
from backend.pipelines.market_data import (
    BinanceTradeMessageParser,
    EventBusMarketDataPipeline,
)
from backend.pipelines.timeframe import TimeframeCandleClosedEvent, TimeframePipeline
from backend.storage import InMemoryCandleStore


class RuntimeMode(str, Enum):
    DRY_RUN = "dry_run"


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


class RuntimeAlreadyStartedError(RuntimeError):
    """Raised when the local backend runtime is started twice."""


class BackendRuntime:
    """Application orchestrator that wires existing components for RUNTIME-001 to RUNTIME-005."""

    def __init__(
        self,
        settings: PlatformSettings | None = None,
        *,
        mode: RuntimeMode = RuntimeMode.DRY_RUN,
    ) -> None:
        self.settings = settings or load_settings()
        self.mode = mode
        self.event_bus = EventBus()
        self.candle_store = InMemoryCandleStore()
        self.market_data_parser = BinanceTradeMessageParser()
        self.market_data_pipeline = EventBusMarketDataPipeline(self.event_bus)
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
        self.ai_decision_engine = AiDecisionEngine(RuleBasedMockAiDecisionProvider())
        self.replay_controller = ReplayController(
            self.event_bus,
            HistoricalTradeReplaySource(()),
        )
        self.multi_timeframe_aggregator = MultiTimeframeTrendAggregator()
        self._structure_engines: dict[tuple[str, Timeframe], MarketStructureEngine] = {}
        self._trend_engines: dict[tuple[str, Timeframe], TrendEngine] = {}
        self._trend_snapshots: dict[tuple[str, Timeframe], TimeframeTrendSnapshot] = {}
        self._state = RuntimeState.CREATED
        self._subscribed = False
        self._logger = get_logger(__name__)

    @property
    def state(self) -> RuntimeState:
        return self._state

    def start(self) -> None:
        """Start the local runtime and subscribe existing event-driven components."""

        if self._state is RuntimeState.RUNNING:
            raise RuntimeAlreadyStartedError("Backend runtime is already running")

        configure_logging(self.settings)
        self._subscribe_components()
        self._state = RuntimeState.RUNNING
        self._logger.info("Backend runtime started")

    def stop(self) -> None:
        """Stop the local runtime for RUNTIME-003."""

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
            ComponentHealth("binance_stream_client", ComponentStatus.DISABLED, "disabled in dry-run mode"),
            ComponentHealth("candle_pipeline", status, "1m candle pipeline subscribed"),
            ComponentHealth("timeframe_pipeline", status, "higher timeframe pipeline subscribed"),
            ComponentHealth("structure_engine", status, "created lazily per symbol/timeframe"),
            ComponentHealth("trend_engine", status, "created lazily per symbol/timeframe"),
            ComponentHealth("multi_timeframe_aggregator", status, "aggregates trend snapshots"),
            ComponentHealth("replay_engine", status, "empty replay controller ready"),
            ComponentHealth("scanner", status, "scanner foundation ready"),
            ComponentHealth("ai_decision_engine", status, "mock provider ready"),
            ComponentHealth("visualization_api", status, "read-only API boundary ready"),
        ]
        return RuntimeHealth(
            state=self._state,
            mode=self.mode,
            components=tuple(components),
        )

    def _subscribe_components(self) -> None:
        if self._subscribed:
            return

        self.candle_pipeline.subscribe()
        self.timeframe_pipeline.subscribe()
        self.event_bus.subscribe(CandleClosedEvent, self._handle_candle_closed)
        self.event_bus.subscribe(TimeframeCandleClosedEvent, self._handle_timeframe_candle_closed)
        self._subscribed = True

    def _handle_candle_closed(self, event: CandleClosedEvent) -> None:
        self._handle_completed_candle(event.candle)

    def _handle_timeframe_candle_closed(self, event: TimeframeCandleClosedEvent) -> None:
        self._handle_completed_candle(event.candle)

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


def structure_event_identity(event: StructureEvent) -> tuple[str, Timeframe]:
    if event.swing is not None:
        return event.swing.symbol, event.swing.timeframe
    if event.break_of_structure is not None:
        return event.break_of_structure.symbol, event.break_of_structure.timeframe
    raise ValueError("StructureEvent must contain structure data")
