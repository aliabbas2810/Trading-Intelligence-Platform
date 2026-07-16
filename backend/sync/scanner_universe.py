from __future__ import annotations

from backend.exchange import ExchangeName
from backend.sync.metadata import SyncMetadataStore
from backend.sync.models import SyncState


class ScannerReadyUniverseProvider:
    """Return scanner-eligible symbols from sync readiness only for SYNC-012."""

    def __init__(self, metadata_store: SyncMetadataStore, *, exchange: ExchangeName) -> None:
        self._metadata_store = metadata_store
        self._exchange = exchange

    def symbols(self) -> tuple[str, ...]:
        return tuple(
            status.canonical_symbol
            for status in self._metadata_store.list_statuses(self._exchange)
            if status.state is SyncState.READY
        )
