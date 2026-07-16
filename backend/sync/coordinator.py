from __future__ import annotations

import threading
from collections.abc import Callable

from backend.core import get_logger
from backend.exchange import ExchangeHistoricalCandleRequest, ExchangeMarketDataAdapter, ExchangeName, MarketType
from backend.models import Timeframe
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms
from backend.storage import CandleHistoryStore
from backend.sync.metadata import SyncMetadataStore
from backend.sync.models import (
    SyncCoordinatorStatus,
    SyncJob,
    SyncProgress,
    SyncQueueSummary,
    SyncReason,
    SyncState,
    SymbolSyncStatus,
)
from backend.sync.planner import IncrementalSyncPlanner


class MarketDataSyncCoordinator:
    """Deterministic market-data synchronization coordinator for SYNC-001..012."""

    def __init__(
        self,
        *,
        adapter: ExchangeMarketDataAdapter,
        history_store: CandleHistoryStore,
        metadata_store: SyncMetadataStore,
        planner: IncrementalSyncPlanner,
        exchange: ExchangeName,
        market_type: MarketType,
        max_concurrent_jobs: int = 2,
        page_size: int = 500,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._adapter = adapter
        self._history_store = history_store
        self._metadata_store = metadata_store
        self._planner = planner
        self._exchange = exchange
        self._market_type = market_type
        self._max_concurrent_jobs = max(1, max_concurrent_jobs)
        self._page_size = page_size
        self._clock_ms = clock_ms or (lambda: 0)
        self._contracts = tuple(adapter.discover_contracts())
        self._queue: list[SyncJob] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._logger = get_logger(__name__)

    def start_background(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_requested = False
        self._thread = threading.Thread(target=self.run_once, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested = True
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    def refresh_catalogue(self) -> tuple[str, ...]:
        self._contracts = tuple(self._adapter.discover_contracts())
        now_ms = self._clock_ms()
        for contract in self._contracts:
            self._metadata_store.upsert_contract(contract, requested_historical_start_ms=now_ms)
        self._logger.info("Market data contract catalogue refreshed")
        return tuple(contract.canonical_symbol for contract in self._contracts)

    def build_plans(self, *, symbols: tuple[str, ...] | None = None, gap_repair: bool = False) -> tuple[SyncJob, ...]:
        now_ms = self._clock_ms()
        selected = set(symbols or ())
        jobs: list[SyncJob] = []
        for contract in self._contracts:
            if selected and contract.canonical_symbol not in selected:
                continue
            latest_remote = self._adapter.fetch_latest_completed_candle_time(contract.canonical_symbol)
            plan = self._planner.plan_symbol(
                contract=contract,
                latest_remote_completed_open_time_ms=latest_remote,
                now_ms=now_ms,
                explicit_gap_repair=gap_repair,
            )
            if plan.is_noop:
                self._persist_status(contract.canonical_symbol, SyncState.READY, latest_remote)
            for job in plan.jobs:
                jobs.append(job)
                self._persist_status(job.symbol, SyncState.QUEUED, latest_remote)
        self._queue = sorted(jobs, key=lambda job: (job.priority.value, job.symbol, job.interval.start_time_ms))
        return tuple(self._queue)

    def run_once(self) -> SyncCoordinatorStatus:
        self._running = True
        try:
            self.refresh_catalogue()
            if not self._queue:
                self.build_plans()
            active = 0
            while self._queue and not self._stop_requested:
                batch = self._queue[: self._max_concurrent_jobs]
                self._queue = self._queue[self._max_concurrent_jobs :]
                active = len(batch)
                for job in batch:
                    self._run_job(job)
                active = 0
            return self.status(syncing=active)
        finally:
            self._running = False

    def sync_symbol(self, symbol: str, *, gap_repair: bool = False) -> SymbolSyncStatus | None:
        self.build_plans(symbols=(symbol,), gap_repair=gap_repair)
        while self._queue and not self._stop_requested:
            self._run_job(self._queue.pop(0))
        return self.symbol_status(symbol)

    def symbol_status(self, symbol: str) -> SymbolSyncStatus | None:
        return self._metadata_store.get_status(self._exchange, symbol)

    def ready_symbols(self) -> tuple[str, ...]:
        return tuple(
            status.canonical_symbol
            for status in self._metadata_store.list_statuses(self._exchange)
            if status.state is SyncState.READY
        )

    def status(self, *, syncing: int = 0) -> SyncCoordinatorStatus:
        statuses = self._metadata_store.list_statuses(self._exchange)
        return SyncCoordinatorStatus(
            running=self._running,
            exchange=self._exchange,
            market_type=self._market_type,
            total_discovered_contracts=len(self._contracts),
            active_contracts=len(self._contracts),
            queue=SyncQueueSummary(
                queued=len(self._queue),
                syncing=syncing,
                ready=sum(1 for status in statuses if status.state is SyncState.READY),
                failed=sum(1 for status in statuses if status.state is SyncState.FAILED),
                stale=sum(1 for status in statuses if status.state is SyncState.STALE),
            ),
            symbols=statuses,
        )

    def _run_job(self, job: SyncJob) -> None:
        state = SyncState.GAP_REPAIR if job.reason is SyncReason.GAP_REPAIR else (
            SyncState.INITIAL_BACKFILL if job.reason is SyncReason.INITIAL_BACKFILL else SyncState.CATCHING_UP
        )
        try:
            self._persist_status(job.symbol, state, None)
            result = self._adapter.fetch_historical_candles(
                ExchangeHistoricalCandleRequest(
                    exchange=job.exchange,
                    market_type=job.market_type,
                    symbol=job.symbol,
                    timeframe=Timeframe.ONE_MINUTE,
                    start_time_ms=job.interval.start_time_ms,
                    end_time_ms=job.interval.end_time_ms,
                    limit=self._page_size,
                ),
            )
            self._history_store.upsert_many(exchange=job.exchange.value, candles=result.candles)
            gaps = self._history_store.detect_missing_intervals(
                exchange=job.exchange.value,
                symbol=job.symbol,
                timeframe=Timeframe.ONE_MINUTE,
                start_time_ms=job.interval.start_time_ms,
                end_time_ms=job.interval.end_time_ms,
            )
            final_state = SyncState.READY if not gaps else SyncState.STALE
            self._persist_status(job.symbol, final_state, result.latest_completed_time_ms, gap_count=len(gaps))
            self._logger.info("Market data symbol sync completed")
        except Exception as exc:
            self._persist_status(job.symbol, SyncState.FAILED, None, error=str(exc))
            self._logger.exception("Market data symbol sync failed")

    def _persist_status(
        self,
        symbol: str,
        state: SyncState,
        latest_remote: int | None,
        *,
        error: str | None = None,
        gap_count: int = 0,
    ) -> None:
        first = self._history_store.first_timestamp(
            exchange=self._exchange.value,
            symbol=symbol,
            timeframe=Timeframe.ONE_MINUTE,
        )
        last = self._history_store.last_timestamp(
            exchange=self._exchange.value,
            symbol=symbol,
            timeframe=Timeframe.ONE_MINUTE,
        )
        count = self._history_store.count(
            exchange=self._exchange.value,
            symbol=symbol,
            timeframe=Timeframe.ONE_MINUTE,
        )
        expected = 0
        if first is not None and latest_remote is not None:
            expected = max(0, ((latest_remote - first) // timeframe_duration_ms(Timeframe.ONE_MINUTE)) + 1)
        self._metadata_store.update_status(
            SymbolSyncStatus(
                exchange=self._exchange,
                market_type=self._market_type,
                symbol=symbol,
                canonical_symbol=symbol,
                state=state,
                first_stored_candle_time_ms=first,
                last_stored_completed_candle_time_ms=last,
                latest_remote_completed_candle_time_ms=latest_remote,
                progress=SyncProgress(count, expected),
                retry_count=1 if error else 0,
                last_successful_sync_ms=self._clock_ms() if state is SyncState.READY else None,
                last_attempted_sync_ms=self._clock_ms(),
                last_error=error,
                detected_gap_count=gap_count,
            ),
        )
