from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from backend.exchange import (
    BitMartFuturesMarketDataAdapter,
    ExchangeHistoricalCandleRequest,
    ExchangeName,
    MarketType,
)
from backend.models import Candle, Timeframe


DEFAULT_HISTORICAL_DATA_ROOT = Path("data") / "historical"


@dataclass(frozen=True, slots=True)
class HistoricalCandleRequest:
    """Historical candle request for M27 validation tooling and TEST-001."""

    symbol: str
    timeframe: Timeframe
    start_time_ms: int
    end_time_ms: int
    exchange: str = ExchangeName.BITMART.value
    market_type: str = MarketType.USDT_M_PERPETUAL.value

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.start_time_ms < 0:
            raise ValueError("start_time_ms must be non-negative")
        if self.end_time_ms <= self.start_time_ms:
            raise ValueError("end_time_ms must be after start_time_ms")
        if not self.exchange:
            raise ValueError("exchange is required")
        if not self.market_type:
            raise ValueError("market_type is required")


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
        return self._root / request.exchange / request.market_type / request.symbol / request.timeframe.value / filename

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


class BitMartHistoricalCandleDownloader:
    """Download BitMart USDT-M futures candles as canonical Candle objects for M27/M31.1."""

    def __init__(
        self,
        *,
        adapter: BitMartFuturesMarketDataAdapter | None = None,
        limit: int = 500,
    ) -> None:
        self._adapter = adapter or BitMartFuturesMarketDataAdapter(page_size=limit)
        self._limit = limit

    def load(self, request: HistoricalCandleRequest) -> tuple[Candle, ...]:
        result = self._adapter.fetch_historical_candles(
            ExchangeHistoricalCandleRequest(
                exchange=ExchangeName(request.exchange),
                market_type=MarketType(request.market_type),
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_time_ms=request.start_time_ms,
                end_time_ms=request.end_time_ms,
                limit=self._limit,
            ),
        )
        return result.candles


def candle_from_bitmart_kline(
    row: dict[str, object],
    *,
    symbol: str,
    timeframe: Timeframe,
    duration_ms: int,
) -> Candle:
    open_time_s = read_int(first_present(row, "timestamp", "time", "ts"), "timestamp")
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time_ms=open_time_s * 1000,
        close_time_ms=open_time_s * 1000 + duration_ms,
        open=read_float(first_present(row, "open", "o"), "open"),
        high=read_float(first_present(row, "high", "h"), "high"),
        low=read_float(first_present(row, "low", "l"), "low"),
        close=read_float(first_present(row, "close", "c"), "close"),
        volume=read_float(first_present(row, "volume", "vol", "v"), "volume"),
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


def first_present(payload: dict[str, object], *keys: str) -> object:
    for key in keys:
        if key in payload:
            return payload[key]
    return None
