from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from backend.engines.replay.models import ReplayRecord
from backend.models.domain import Candle, Timeframe, Trade
from backend.pipelines.candle import CandleClosedEvent
from backend.pipelines.market_data import TradeReceivedEvent
from backend.storage import CandleStore


class ReplaySource(Protocol):
    """Historical event source boundary; downstream processing remains unchanged."""

    def list_records(self) -> tuple[ReplayRecord, ...]:
        """Return deterministic replay records for FR-801 and FR-806."""


class HistoricalTradeReplaySource:
    """Replay canonical historical trades as live-equivalent TradeReceivedEvents."""

    def __init__(self, trades: Iterable[Trade]) -> None:
        self._trades = tuple(trades)

    def list_records(self) -> tuple[ReplayRecord, ...]:
        records = (
            ReplayRecord(
                timestamp_ms=trade.timestamp_ms,
                sequence=sequence,
                event=TradeReceivedEvent(trade=trade),
            )
            for sequence, trade in enumerate(self._trades)
        )
        return tuple(sorted(records, key=lambda record: (record.timestamp_ms, record.sequence)))


class HistoricalCandleReplaySource:
    """Replay completed historical candles through the candle-close event path."""

    def __init__(self, candles: Iterable[Candle]) -> None:
        self._candles = tuple(candles)

    @classmethod
    def from_store(cls, store: CandleStore, symbol: str, timeframe: Timeframe) -> HistoricalCandleReplaySource:
        return cls(store.list(symbol, timeframe))

    def list_records(self) -> tuple[ReplayRecord, ...]:
        records = (
            ReplayRecord(
                timestamp_ms=candle.close_time_ms,
                sequence=sequence,
                event=CandleClosedEvent(candle=candle, is_synthetic=False),
            )
            for sequence, candle in enumerate(self._candles)
        )
        return tuple(sorted(records, key=lambda record: (record.timestamp_ms, record.sequence)))
