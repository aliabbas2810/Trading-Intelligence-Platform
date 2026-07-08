from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
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
from backend.engines.entry import DecisionTrace, EntrySignalEngine, EntrySignalInput
from backend.engines.replay import HistoricalTradeReplaySource, ReplayController
from backend.engines.risk import RiskEngine, RiskInput, RiskPlan
from backend.engines.scanner import ScannerEngine, ScannerSummary, SetupCandidate, SymbolScanInput
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
    ) -> None:
        self.settings = settings or load_settings()
        self.mode = mode
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
            ComponentHealth("visualization_api", status, "read-only API boundary ready"),
            ComponentHealth(
                "demo_data",
                self._demo_component_status(),
                self._demo_component_message(),
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
        )
        return self.ai_decision_engine.generate_decision(decision_input)

    def evaluate_entry_signal(self, *, symbol: str) -> DecisionTrace:
        """Evaluate entry state from existing stores for ENTRY-001 through ENTRY-006."""

        return self.entry_signal_engine.evaluate(self._entry_signal_input_for(symbol))

    def evaluate_risk(
        self,
        *,
        symbol: str,
        minimum_risk_reward: float | None = 2.0,
        target_mode: str | None = "rr",
    ) -> RiskPlan:
        """Evaluate risk from existing deterministic outputs for RISK-001 through RISK-006."""

        return self.risk_engine.evaluate(
            RiskInput(
                entry_trace=self.evaluate_entry_signal(symbol=symbol),
                latest_candle=self._latest_candle(symbol, Timeframe.ONE_MINUTE),
                structure_levels=self._risk_structure_levels(symbol),
                bos_events=self._risk_bos_events(symbol),
                minimum_risk_reward=minimum_risk_reward,
                target_mode=target_mode,
            ),
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
        return self.settings.market_data.symbols[0]

    @property
    def stream_enabled(self) -> bool:
        return self.mode is RuntimeMode.LIVE_BINANCE and self.settings.market_data.live_enabled

    @property
    def demo_data_enabled(self) -> bool:
        return self.mode is RuntimeMode.DRY_RUN and self.settings.demo.enabled

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
        if self.mode is RuntimeMode.DRY_RUN:
            return ComponentStatus.DISABLED
        if not self.settings.market_data.live_enabled:
            return ComponentStatus.DISABLED
        return fallback

    def _binance_component_message(self) -> str:
        if self.mode is RuntimeMode.DRY_RUN:
            return "disabled in dry-run mode"
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
