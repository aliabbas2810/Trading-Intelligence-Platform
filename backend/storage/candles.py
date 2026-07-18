from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, cast

from backend.models.domain import Candle, Timeframe


class CandleAlreadyExistsError(ValueError):
    """Raised to prevent duplicate finalized candles for FR-207."""


class CandleStore(Protocol):
    """Storage boundary for FR-207 and replay-compatible M3 persistence."""

    def save(self, candle: Candle) -> None:
        """Persist one completed candle."""

    def list(self, symbol: str, timeframe: Timeframe) -> tuple[Candle, ...]:
        """Return stored candles in deterministic open-time order."""


class InMemoryCandleStore:
    """In-memory candle storage for SRS FR-701 and user-specified FR-207."""

    def __init__(self) -> None:
        self._candles: dict[tuple[str, Timeframe, int], Candle] = {}

    def save(self, candle: Candle) -> None:
        key = self._key(candle)
        if key in self._candles:
            raise CandleAlreadyExistsError("Candle already exists")
        self._candles[key] = candle

    def save_many(self, candles: tuple[Candle, ...]) -> None:
        for candle in candles:
            key = self._key(candle)
            if key in self._candles:
                raise CandleAlreadyExistsError("Candle already exists")
        for candle in candles:
            self._candles[self._key(candle)] = candle

    def list(self, symbol: str, timeframe: Timeframe) -> tuple[Candle, ...]:
        candles = (
            candle
            for key, candle in self._candles.items()
            if key[0] == symbol and key[1] is timeframe
        )
        return tuple(sorted(candles, key=lambda candle: candle.open_time_ms))

    def _key(self, candle: Candle) -> tuple[str, Timeframe, int]:
        return (candle.symbol, candle.timeframe, candle.open_time_ms)


class JsonlCandleStore:
    """Basic replay-friendly disk persistence for one-minute candles."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._memory = InMemoryCandleStore()
        self._load_existing()

    def save(self, candle: Candle) -> None:
        self._memory.save(candle)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            payload = asdict(candle)
            payload["timeframe"] = candle.timeframe.value
            file.write(json.dumps(payload, sort_keys=True))
            file.write("\n")

    def list(self, symbol: str, timeframe: Timeframe) -> tuple[Candle, ...]:
        return self._memory.list(symbol, timeframe)

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("Candle JSONL row must be an object")
            self._memory.save(self._candle_from_payload(cast(dict[str, object], payload)))

    def _candle_from_payload(self, payload: dict[str, object]) -> Candle:
        return Candle(
            symbol=self._read_str(payload, "symbol"),
            timeframe=Timeframe(self._read_str(payload, "timeframe")),
            open_time_ms=self._read_int(payload, "open_time_ms"),
            close_time_ms=self._read_int(payload, "close_time_ms"),
            open=self._read_float(payload, "open"),
            high=self._read_float(payload, "high"),
            low=self._read_float(payload, "low"),
            close=self._read_float(payload, "close"),
            volume=self._read_float(payload, "volume"),
        )

    def _read_str(self, payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            raise ValueError(f"Candle field {key!r} must be a string")
        return value

    def _read_int(self, payload: dict[str, object], key: str) -> int:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Candle field {key!r} must be an integer")
        return value

    def _read_float(self, payload: dict[str, object], key: str) -> float:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"Candle field {key!r} must be numeric")
        return float(value)
