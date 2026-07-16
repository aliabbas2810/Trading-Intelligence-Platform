from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.exchange import ContractMetadata, ExchangeName, MarketType


class SyncState(str, Enum):
    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    INITIAL_BACKFILL = "INITIAL_BACKFILL"
    CATCHING_UP = "CATCHING_UP"
    GAP_REPAIR = "GAP_REPAIR"
    READY = "READY"
    STALE = "STALE"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


class SyncPriority(int, Enum):
    SELECTED = 0
    WATCHLIST = 1
    HIGH = 2
    NORMAL = 3


class SyncReason(str, Enum):
    INITIAL_BACKFILL = "initial_backfill"
    STARTUP_CATCH_UP = "startup_catch_up"
    GAP_REPAIR = "gap_repair"
    ALREADY_CURRENT = "already_current"


@dataclass(frozen=True, slots=True)
class SyncInterval:
    start_time_ms: int
    end_time_ms: int

    def __post_init__(self) -> None:
        if self.end_time_ms <= self.start_time_ms:
            raise ValueError("SyncInterval end must be after start")


@dataclass(frozen=True, slots=True)
class SyncJob:
    exchange: ExchangeName
    market_type: MarketType
    symbol: str
    interval: SyncInterval
    priority: SyncPriority
    reason: SyncReason


@dataclass(frozen=True, slots=True)
class SymbolSyncPlan:
    symbol: str
    jobs: tuple[SyncJob, ...]
    reason: SyncReason
    local_last_open_time_ms: int | None
    latest_remote_completed_open_time_ms: int

    @property
    def is_noop(self) -> bool:
        return not self.jobs and self.reason is SyncReason.ALREADY_CURRENT


@dataclass(frozen=True, slots=True)
class SyncProgress:
    completed_candles: int
    expected_candles: int

    @property
    def ratio(self) -> float:
        if self.expected_candles <= 0:
            return 1.0
        return min(1.0, self.completed_candles / self.expected_candles)


@dataclass(frozen=True, slots=True)
class SyncErrorRecord:
    symbol: str
    message: str
    attempted_at_ms: int
    retry_count: int


@dataclass(frozen=True, slots=True)
class SymbolSyncStatus:
    exchange: ExchangeName
    market_type: MarketType
    symbol: str
    canonical_symbol: str
    state: SyncState
    first_stored_candle_time_ms: int | None = None
    last_stored_completed_candle_time_ms: int | None = None
    latest_remote_completed_candle_time_ms: int | None = None
    progress: SyncProgress = SyncProgress(0, 0)
    retry_count: int = 0
    last_successful_sync_ms: int | None = None
    last_attempted_sync_ms: int | None = None
    last_error: str | None = None
    detected_gap_count: int = 0

    @property
    def ready(self) -> bool:
        return self.state is SyncState.READY


@dataclass(frozen=True, slots=True)
class SyncQueueSummary:
    queued: int
    syncing: int
    ready: int
    failed: int
    stale: int


@dataclass(frozen=True, slots=True)
class SyncCoordinatorStatus:
    running: bool
    exchange: ExchangeName
    market_type: MarketType
    total_discovered_contracts: int
    active_contracts: int
    queue: SyncQueueSummary
    symbols: tuple[SymbolSyncStatus, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredContract:
    metadata: ContractMetadata
    state: SyncState = SyncState.DISCOVERED
