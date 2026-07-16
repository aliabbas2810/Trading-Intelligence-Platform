from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from backend.models import Candle, Timeframe
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms


class CandleHistoryStore(Protocol):
    """Canonical 1m candle history boundary for STORAGE-001..006."""

    def upsert_many(self, *, exchange: str, candles: tuple[Candle, ...]) -> int:
        """Insert or replace completed candles and return changed count."""

    def first_timestamp(self, *, exchange: str, symbol: str, timeframe: Timeframe) -> int | None:
        """Return first stored candle open time."""

    def last_timestamp(self, *, exchange: str, symbol: str, timeframe: Timeframe) -> int | None:
        """Return last stored candle open time."""

    def query_range(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        start_time_ms: int,
        end_time_ms: int,
    ) -> tuple[Candle, ...]:
        """Return candles within [start, end)."""

    def detect_missing_intervals(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        start_time_ms: int,
        end_time_ms: int,
    ) -> tuple[tuple[int, int], ...]:
        """Return missing 1m intervals in [start, end)."""

    def count(self, *, exchange: str, symbol: str, timeframe: Timeframe) -> int:
        """Return candle count."""


class InMemoryCandleHistoryStore:
    """Deterministic idempotent local store for M31 tests and runtime foundation."""

    def __init__(self) -> None:
        self._candles: dict[tuple[str, str, Timeframe, int], Candle] = {}

    def upsert_many(self, *, exchange: str, candles: tuple[Candle, ...]) -> int:
        changed = 0
        for candle in candles:
            key = self._key(exchange, candle)
            if self._candles.get(key) != candle:
                changed += 1
            self._candles[key] = candle
        return changed

    def first_timestamp(self, *, exchange: str, symbol: str, timeframe: Timeframe) -> int | None:
        times = self._times(exchange=exchange, symbol=symbol, timeframe=timeframe)
        return min(times, default=None)

    def last_timestamp(self, *, exchange: str, symbol: str, timeframe: Timeframe) -> int | None:
        times = self._times(exchange=exchange, symbol=symbol, timeframe=timeframe)
        return max(times, default=None)

    def query_range(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        start_time_ms: int,
        end_time_ms: int,
    ) -> tuple[Candle, ...]:
        return tuple(
            sorted(
                (
                    candle
                    for (stored_exchange, stored_symbol, stored_timeframe, open_time), candle in self._candles.items()
                    if stored_exchange == exchange
                    and stored_symbol == symbol
                    and stored_timeframe is timeframe
                    and start_time_ms <= open_time < end_time_ms
                ),
                key=lambda candle: candle.open_time_ms,
            ),
        )

    def detect_missing_intervals(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        start_time_ms: int,
        end_time_ms: int,
    ) -> tuple[tuple[int, int], ...]:
        duration_ms = timeframe_duration_ms(timeframe)
        existing = set(self._times(exchange=exchange, symbol=symbol, timeframe=timeframe))
        gaps: list[tuple[int, int]] = []
        gap_start: int | None = None
        cursor = start_time_ms
        while cursor < end_time_ms:
            if cursor not in existing and gap_start is None:
                gap_start = cursor
            elif cursor in existing and gap_start is not None:
                gaps.append((gap_start, cursor))
                gap_start = None
            cursor += duration_ms
        if gap_start is not None:
            gaps.append((gap_start, end_time_ms))
        return tuple(gaps)

    def count(self, *, exchange: str, symbol: str, timeframe: Timeframe) -> int:
        return len(self._times(exchange=exchange, symbol=symbol, timeframe=timeframe))

    def _key(self, exchange: str, candle: Candle) -> tuple[str, str, Timeframe, int]:
        return (exchange, candle.symbol, candle.timeframe, candle.open_time_ms)

    def _times(self, *, exchange: str, symbol: str, timeframe: Timeframe) -> tuple[int, ...]:
        return tuple(
            open_time
            for stored_exchange, stored_symbol, stored_timeframe, open_time in self._candles
            if stored_exchange == exchange and stored_symbol == symbol and stored_timeframe is timeframe
        )


class JsonlCandleHistoryStore(InMemoryCandleHistoryStore):
    """JSONL-compatible canonical history store foundation; parquet/duckdb can replace it later."""

    def __init__(self, root: Path) -> None:
        self._root = root
        super().__init__()
        self._load_existing()

    def upsert_many(self, *, exchange: str, candles: tuple[Candle, ...]) -> int:
        changed = super().upsert_many(exchange=exchange, candles=candles)
        if changed:
            for candle in candles:
                self._write(exchange, candle)
        return changed

    def _write(self, exchange: str, candle: Candle) -> None:
        path = self._root / exchange / candle.symbol / candle.timeframe.value / "candles.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Compact rewrite keeps idempotence for the local foundation.
        candles = self.query_range(
            exchange=exchange,
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            start_time_ms=0,
            end_time_ms=2**63 - 1,
        )
        with path.open("w", encoding="utf-8") as file:
            for item in candles:
                payload = asdict(item)
                payload["timeframe"] = item.timeframe.value
                file.write(json.dumps(payload, sort_keys=True))
                file.write("\n")

    def _load_existing(self) -> None:
        if not self._root.exists():
            return
        for path in self._root.glob("*/*/*/candles.jsonl"):
            exchange = path.parts[-4]
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    timeframe = Timeframe(str(payload["timeframe"]))
                    candle = Candle(
                        symbol=str(payload["symbol"]),
                        timeframe=timeframe,
                        open_time_ms=int(payload["open_time_ms"]),
                        close_time_ms=int(payload["close_time_ms"]),
                        open=float(payload["open"]),
                        high=float(payload["high"]),
                        low=float(payload["low"]),
                        close=float(payload["close"]),
                        volume=float(payload["volume"]),
                    )
                    super().upsert_many(exchange=exchange, candles=(candle,))
