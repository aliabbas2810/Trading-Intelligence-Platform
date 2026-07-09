from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.models import Candle, Timeframe
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms


DEFAULT_HISTORICAL_DATA_ROOT = Path("data") / "historical"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


@dataclass(frozen=True, slots=True)
class HistoricalCandleRequest:
    """Historical candle request for M27 validation tooling and TEST-001."""

    symbol: str
    timeframe: Timeframe
    start_time_ms: int
    end_time_ms: int
    exchange: str = "binance"

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.start_time_ms < 0:
            raise ValueError("start_time_ms must be non-negative")
        if self.end_time_ms <= self.start_time_ms:
            raise ValueError("end_time_ms must be after start_time_ms")
        if not self.exchange:
            raise ValueError("exchange is required")


class HistoricalCandleLoader(Protocol):
    """Interface for loading historical completed candles without changing engine logic."""

    def load(self, request: HistoricalCandleRequest) -> tuple[Candle, ...]:
        """Return deterministic historical candles for the request."""


class HistoricalCandleFileStore:
    """Local JSONL storage for M27 historical candle fixtures/downloads."""

    def __init__(self, root: Path = DEFAULT_HISTORICAL_DATA_ROOT) -> None:
        self._root = root

    def path_for(self, request: HistoricalCandleRequest) -> Path:
        filename = f"{request.start_time_ms}_{request.end_time_ms}.jsonl"
        return self._root / request.exchange / request.symbol / request.timeframe.value / filename

    def save(self, request: HistoricalCandleRequest, candles: Iterable[Candle]) -> Path:
        path = self.path_for(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            for candle in candles:
                payload = asdict(candle)
                payload["timeframe"] = candle.timeframe.value
                file.write(json.dumps(payload, sort_keys=True))
                file.write("\n")
        return path

    def load(self, request: HistoricalCandleRequest) -> tuple[Candle, ...]:
        path = self.path_for(request)
        return self.load_path(path)

    def load_path(self, path: Path) -> tuple[Candle, ...]:
        candles: list[Candle] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("Historical candle row must be a JSON object")
            candles.append(candle_from_payload(cast(dict[str, object], payload)))
        return tuple(sorted(candles, key=lambda candle: candle.open_time_ms))


class BinanceHistoricalCandleDownloader:
    """Download Binance Spot klines as canonical Candle objects for M27."""

    def __init__(self, *, base_url: str = BINANCE_KLINES_URL, limit: int = 1000) -> None:
        self._base_url = base_url
        self._limit = limit

    def load(self, request: HistoricalCandleRequest) -> tuple[Candle, ...]:
        candles: list[Candle] = []
        cursor_ms = request.start_time_ms
        duration_ms = timeframe_duration_ms(request.timeframe)
        while cursor_ms < request.end_time_ms:
            rows = self._fetch_page(request, cursor_ms)
            if not rows:
                break
            for row in rows:
                candle = candle_from_binance_kline(
                    row,
                    symbol=request.symbol,
                    timeframe=request.timeframe,
                    duration_ms=duration_ms,
                )
                if candle.open_time_ms >= request.end_time_ms:
                    break
                candles.append(candle)
            last_open_time_ms = candles[-1].open_time_ms if candles else cursor_ms
            next_cursor_ms = last_open_time_ms + duration_ms
            if next_cursor_ms <= cursor_ms:
                break
            cursor_ms = next_cursor_ms
            if len(rows) < self._limit:
                break
        return tuple(candles)

    def _fetch_page(self, request: HistoricalCandleRequest, start_time_ms: int) -> list[object]:
        query = urlencode(
            {
                "symbol": request.symbol.upper(),
                "interval": request.timeframe.value,
                "startTime": start_time_ms,
                "endTime": request.end_time_ms,
                "limit": self._limit,
            },
        )
        http_request = Request(f"{self._base_url}?{query}", headers={"Accept": "application/json"})
        with urlopen(http_request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Binance kline response must be a list")
        return payload


def candle_from_binance_kline(
    row: object,
    *,
    symbol: str,
    timeframe: Timeframe,
    duration_ms: int,
) -> Candle:
    if not isinstance(row, list) or len(row) < 6:
        raise ValueError("Binance kline row must contain at least six fields")
    open_time_ms = read_int(row[0], "open_time")
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + duration_ms,
        open=read_float(row[1], "open"),
        high=read_float(row[2], "high"),
        low=read_float(row[3], "low"),
        close=read_float(row[4], "close"),
        volume=read_float(row[5], "volume"),
    )


def candle_from_payload(payload: dict[str, object]) -> Candle:
    return Candle(
        symbol=read_str(payload.get("symbol"), "symbol"),
        timeframe=Timeframe(read_str(payload.get("timeframe"), "timeframe")),
        open_time_ms=read_int(payload.get("open_time_ms"), "open_time_ms"),
        close_time_ms=read_int(payload.get("close_time_ms"), "close_time_ms"),
        open=read_float(payload.get("open"), "open"),
        high=read_float(payload.get("high"), "high"),
        low=read_float(payload.get("low"), "low"),
        close=read_float(payload.get("close"), "close"),
        volume=read_float(payload.get("volume"), "volume"),
    )


def parse_utc_timestamp_ms(value: str) -> int:
    """Parse an ISO-8601 UTC timestamp for historical validation scripts."""

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def read_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def read_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"{field_name} must be an integer")


def read_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)
