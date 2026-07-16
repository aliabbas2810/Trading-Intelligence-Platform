from __future__ import annotations

from pydantic import BaseModel

from backend.sync import SyncCoordinatorStatus, SyncProgress, SyncQueueSummary, SymbolSyncStatus


class SyncProgressResponse(BaseModel):
    completed_candles: int
    expected_candles: int
    ratio: float

    @classmethod
    def from_progress(cls, progress: SyncProgress) -> SyncProgressResponse:
        return cls(
            completed_candles=progress.completed_candles,
            expected_candles=progress.expected_candles,
            ratio=progress.ratio,
        )


class SymbolSyncStatusResponse(BaseModel):
    exchange: str
    market_type: str
    symbol: str
    canonical_symbol: str
    state: str
    first_stored_candle_time_ms: int | None
    last_stored_completed_candle_time_ms: int | None
    latest_remote_completed_candle_time_ms: int | None
    progress: SyncProgressResponse
    retry_count: int
    last_successful_sync_ms: int | None
    last_attempted_sync_ms: int | None
    last_error: str | None
    detected_gap_count: int

    @classmethod
    def from_status(cls, status: SymbolSyncStatus) -> SymbolSyncStatusResponse:
        return cls(
            exchange=status.exchange.value,
            market_type=status.market_type.value,
            symbol=status.symbol,
            canonical_symbol=status.canonical_symbol,
            state=status.state.value,
            first_stored_candle_time_ms=status.first_stored_candle_time_ms,
            last_stored_completed_candle_time_ms=status.last_stored_completed_candle_time_ms,
            latest_remote_completed_candle_time_ms=status.latest_remote_completed_candle_time_ms,
            progress=SyncProgressResponse.from_progress(status.progress),
            retry_count=status.retry_count,
            last_successful_sync_ms=status.last_successful_sync_ms,
            last_attempted_sync_ms=status.last_attempted_sync_ms,
            last_error=status.last_error,
            detected_gap_count=status.detected_gap_count,
        )


class SyncQueueSummaryResponse(BaseModel):
    queued: int
    syncing: int
    ready: int
    failed: int
    stale: int

    @classmethod
    def from_summary(cls, summary: SyncQueueSummary) -> SyncQueueSummaryResponse:
        return cls(
            queued=summary.queued,
            syncing=summary.syncing,
            ready=summary.ready,
            failed=summary.failed,
            stale=summary.stale,
        )


class SyncCoordinatorStatusResponse(BaseModel):
    running: bool
    exchange: str
    market_type: str
    total_discovered_contracts: int
    active_contracts: int
    queue: SyncQueueSummaryResponse
    symbols: tuple[SymbolSyncStatusResponse, ...]

    @classmethod
    def from_status(cls, status: SyncCoordinatorStatus) -> SyncCoordinatorStatusResponse:
        return cls(
            running=status.running,
            exchange=status.exchange.value,
            market_type=status.market_type.value,
            total_discovered_contracts=status.total_discovered_contracts,
            active_contracts=status.active_contracts,
            queue=SyncQueueSummaryResponse.from_summary(status.queue),
            symbols=tuple(SymbolSyncStatusResponse.from_status(item) for item in status.symbols),
        )


class ContractsResponse(BaseModel):
    symbols: tuple[str, ...]
    total: int
