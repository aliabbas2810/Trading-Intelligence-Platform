from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from backend.exchange import ContractMetadata, ExchangeName, MarketType
from backend.sync.models import SyncProgress, SyncState, SymbolSyncStatus


class SyncMetadataStore(Protocol):
    """Persistent synchronization metadata/checkpoint boundary for SYNC-004..008."""

    def upsert_contract(self, metadata: ContractMetadata, *, requested_historical_start_ms: int | None = None) -> None:
        """Persist contract metadata."""

    def update_status(self, status: SymbolSyncStatus) -> None:
        """Persist symbol status/checkpoint."""

    def get_status(self, exchange: ExchangeName, symbol: str) -> SymbolSyncStatus | None:
        """Return one symbol status."""

    def list_statuses(self, exchange: ExchangeName | None = None) -> tuple[SymbolSyncStatus, ...]:
        """Return all known statuses."""


class SQLiteSyncMetadataStore:
    """Deterministic SQLite metadata store for local M31 synchronization."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def upsert_contract(self, metadata: ContractMetadata, *, requested_historical_start_ms: int | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO symbol_sync (
                    exchange, market_type, symbol, canonical_symbol, contract_status,
                    first_available_time_ms, requested_historical_start_ms, sync_state
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol) DO UPDATE SET
                    market_type=excluded.market_type,
                    canonical_symbol=excluded.canonical_symbol,
                    contract_status=excluded.contract_status,
                    first_available_time_ms=excluded.first_available_time_ms,
                    requested_historical_start_ms=COALESCE(excluded.requested_historical_start_ms, requested_historical_start_ms)
                """,
                (
                    metadata.exchange.value,
                    metadata.market_type.value,
                    metadata.exchange_symbol,
                    metadata.canonical_symbol,
                    metadata.status.value,
                    metadata.listing_time_ms,
                    requested_historical_start_ms,
                    SyncState.DISCOVERED.value,
                ),
            )

    def update_status(self, status: SymbolSyncStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO symbol_sync (
                    exchange, market_type, symbol, canonical_symbol, sync_state,
                    first_stored_candle_time_ms, last_stored_completed_candle_time_ms,
                    latest_remote_completed_candle_time_ms, sync_progress_completed,
                    sync_progress_expected, retry_count, last_successful_sync_ms,
                    last_attempted_sync_ms, last_error, detected_gap_count, readiness_state
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol) DO UPDATE SET
                    market_type=excluded.market_type,
                    canonical_symbol=excluded.canonical_symbol,
                    sync_state=excluded.sync_state,
                    first_stored_candle_time_ms=excluded.first_stored_candle_time_ms,
                    last_stored_completed_candle_time_ms=excluded.last_stored_completed_candle_time_ms,
                    latest_remote_completed_candle_time_ms=excluded.latest_remote_completed_candle_time_ms,
                    sync_progress_completed=excluded.sync_progress_completed,
                    sync_progress_expected=excluded.sync_progress_expected,
                    retry_count=excluded.retry_count,
                    last_successful_sync_ms=excluded.last_successful_sync_ms,
                    last_attempted_sync_ms=excluded.last_attempted_sync_ms,
                    last_error=excluded.last_error,
                    detected_gap_count=excluded.detected_gap_count,
                    readiness_state=excluded.readiness_state
                """,
                (
                    status.exchange.value,
                    status.market_type.value,
                    status.symbol,
                    status.canonical_symbol,
                    status.state.value,
                    status.first_stored_candle_time_ms,
                    status.last_stored_completed_candle_time_ms,
                    status.latest_remote_completed_candle_time_ms,
                    status.progress.completed_candles,
                    status.progress.expected_candles,
                    status.retry_count,
                    status.last_successful_sync_ms,
                    status.last_attempted_sync_ms,
                    status.last_error,
                    status.detected_gap_count,
                    "READY" if status.ready else status.state.value,
                ),
            )

    def get_status(self, exchange: ExchangeName, symbol: str) -> SymbolSyncStatus | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM symbol_sync WHERE exchange=? AND canonical_symbol=?",
                (exchange.value, symbol),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM symbol_sync WHERE exchange=? AND symbol=?",
                    (exchange.value, symbol),
                ).fetchone()
        return self._status_from_row(row) if row is not None else None

    def list_statuses(self, exchange: ExchangeName | None = None) -> tuple[SymbolSyncStatus, ...]:
        with self._connect() as conn:
            if exchange is None:
                rows = conn.execute("SELECT * FROM symbol_sync ORDER BY canonical_symbol").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM symbol_sync WHERE exchange=? ORDER BY canonical_symbol",
                    (exchange.value,),
                ).fetchall()
        return tuple(self._status_from_row(row) for row in rows)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_sync (
                    exchange TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    canonical_symbol TEXT NOT NULL,
                    contract_status TEXT DEFAULT 'unknown',
                    first_available_time_ms INTEGER,
                    requested_historical_start_ms INTEGER,
                    first_stored_candle_time_ms INTEGER,
                    last_stored_completed_candle_time_ms INTEGER,
                    latest_remote_completed_candle_time_ms INTEGER,
                    sync_state TEXT NOT NULL DEFAULT 'DISCOVERED',
                    sync_progress_completed INTEGER NOT NULL DEFAULT 0,
                    sync_progress_expected INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_successful_sync_ms INTEGER,
                    last_attempted_sync_ms INTEGER,
                    last_error TEXT,
                    detected_gap_count INTEGER NOT NULL DEFAULT 0,
                    readiness_state TEXT NOT NULL DEFAULT 'DISCOVERED',
                    PRIMARY KEY(exchange, symbol)
                )
                """,
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _status_from_row(self, row: sqlite3.Row) -> SymbolSyncStatus:
        return SymbolSyncStatus(
            exchange=ExchangeName(str(row["exchange"])),
            market_type=MarketType(str(row["market_type"])),
            symbol=str(row["symbol"]),
            canonical_symbol=str(row["canonical_symbol"]),
            state=SyncState(str(row["sync_state"])),
            first_stored_candle_time_ms=row["first_stored_candle_time_ms"],
            last_stored_completed_candle_time_ms=row["last_stored_completed_candle_time_ms"],
            latest_remote_completed_candle_time_ms=row["latest_remote_completed_candle_time_ms"],
            progress=SyncProgress(
                completed_candles=int(row["sync_progress_completed"]),
                expected_candles=int(row["sync_progress_expected"]),
            ),
            retry_count=int(row["retry_count"]),
            last_successful_sync_ms=row["last_successful_sync_ms"],
            last_attempted_sync_ms=row["last_attempted_sync_ms"],
            last_error=row["last_error"],
            detected_gap_count=int(row["detected_gap_count"]),
        )
