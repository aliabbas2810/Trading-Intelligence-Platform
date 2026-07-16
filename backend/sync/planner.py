from __future__ import annotations

from dataclasses import dataclass

from backend.exchange import ContractMetadata, ExchangeName, MarketType
from backend.models import Timeframe
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms
from backend.storage import CandleHistoryStore
from backend.sync.models import SyncInterval, SyncJob, SyncPriority, SyncReason, SymbolSyncPlan


@dataclass(frozen=True, slots=True)
class IncrementalSyncPlanner:
    """Gap-aware 1m sync planner for SYNC-001..006."""

    history_store: CandleHistoryStore
    history_horizon_ms: int
    exchange: ExchangeName
    market_type: MarketType
    priority_symbols: tuple[str, ...] = ()

    def plan_symbol(
        self,
        *,
        contract: ContractMetadata,
        latest_remote_completed_open_time_ms: int,
        now_ms: int,
        explicit_gap_repair: bool = False,
    ) -> SymbolSyncPlan:
        local_last = self.history_store.last_timestamp(
            exchange=contract.exchange.value,
            symbol=contract.canonical_symbol,
            timeframe=Timeframe.ONE_MINUTE,
        )
        start_floor = max(
            contract.listing_time_ms or 0,
            now_ms - self.history_horizon_ms,
        )
        if local_last is None:
            start_time = align_minute(start_floor)
            reason = SyncReason.INITIAL_BACKFILL
        else:
            start_time = local_last + timeframe_duration_ms(Timeframe.ONE_MINUTE)
            reason = SyncReason.STARTUP_CATCH_UP

        end_time = latest_remote_completed_open_time_ms + timeframe_duration_ms(Timeframe.ONE_MINUTE)
        jobs: list[SyncJob] = []
        if explicit_gap_repair:
            gaps = self.history_store.detect_missing_intervals(
                exchange=contract.exchange.value,
                symbol=contract.canonical_symbol,
                timeframe=Timeframe.ONE_MINUTE,
                start_time_ms=start_floor,
                end_time_ms=end_time,
            )
            jobs.extend(
                SyncJob(
                    exchange=contract.exchange,
                    market_type=contract.market_type,
                    symbol=contract.canonical_symbol,
                    interval=SyncInterval(start, end),
                    priority=self._priority(contract.canonical_symbol),
                    reason=SyncReason.GAP_REPAIR,
                )
                for start, end in gaps
            )
            return SymbolSyncPlan(
                symbol=contract.canonical_symbol,
                jobs=tuple(jobs),
                reason=SyncReason.GAP_REPAIR if jobs else SyncReason.ALREADY_CURRENT,
                local_last_open_time_ms=local_last,
                latest_remote_completed_open_time_ms=latest_remote_completed_open_time_ms,
            )

        if start_time < end_time:
            jobs.append(
                SyncJob(
                    exchange=contract.exchange,
                    market_type=contract.market_type,
                    symbol=contract.canonical_symbol,
                    interval=SyncInterval(start_time, end_time),
                    priority=self._priority(contract.canonical_symbol),
                    reason=reason,
                ),
            )
        return SymbolSyncPlan(
            symbol=contract.canonical_symbol,
            jobs=tuple(jobs),
            reason=reason if jobs else SyncReason.ALREADY_CURRENT,
            local_last_open_time_ms=local_last,
            latest_remote_completed_open_time_ms=latest_remote_completed_open_time_ms,
        )

    def _priority(self, symbol: str) -> SyncPriority:
        return SyncPriority.HIGH if symbol in self.priority_symbols else SyncPriority.NORMAL


def align_minute(timestamp_ms: int) -> int:
    duration = timeframe_duration_ms(Timeframe.ONE_MINUTE)
    return (timestamp_ms // duration) * duration
