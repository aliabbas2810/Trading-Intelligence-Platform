from __future__ import annotations

import json
from dataclasses import dataclass
from time import sleep, time
from typing import Callable, Protocol, cast
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.exchange.models import (
    CandlePage,
    ContractMetadata,
    ContractStatus,
    ExchangeHistoricalCandleRequest,
    ExchangeName,
    HistoricalCandleResult,
    MarketType,
    RateLimitMetadata,
)
from backend.models import Candle, Timeframe
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms


BITMART_FUTURES_BASE_URL = "https://api-cloud-v2.bitmart.com"
ONE_MINUTE_MS = 60_000


class HttpTransport(Protocol):
    def get_json(self, path: str, params: dict[str, str | int]) -> object:
        """Return decoded JSON without leaking transport details into adapters."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 0.0
    multiplier: float = 2.0


class UrlLibJsonTransport:
    def __init__(self, *, base_url: str = BITMART_FUTURES_BASE_URL, timeout_seconds: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def get_json(self, path: str, params: dict[str, str | int]) -> object:
        query = urlencode(params)
        url = f"{self._base_url}{path}?{query}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Trading-Intelligence-Platform/0.3",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"BitMart HTTP request failed url={url} status={exc.code} body={truncate_text(body)}",
            ) from exc


class BitMartFuturesMarketDataAdapter:
    """BitMart public USDT-M futures adapter for EXCHANGE-002..006."""

    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        retry_policy: RetryPolicy | None = None,
        page_size: int = 500,
        clock_ms: Callable[[], int] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._transport = transport or UrlLibJsonTransport()
        self._retry_policy = retry_policy or RetryPolicy()
        self._page_size = page_size
        self._clock_ms = clock_ms or (lambda: int(time() * 1000))
        self._sleeper = sleeper or sleep
        self._metadata: dict[str, ContractMetadata] = {}

    def discover_contracts(self) -> tuple[ContractMetadata, ...]:
        payload = self._request("/contract/public/details", {})
        contracts = tuple(
            item
            for item in (self._contract_from_raw(raw) for raw in self._contract_rows(payload))
            if item is not None
            and item.quote_asset == "USDT"
            and item.market_type is MarketType.USDT_M_PERPETUAL
            and item.is_active
            and item.is_perpetual
        )
        self._metadata = {
            item.canonical_symbol: item for item in contracts
        } | {item.exchange_symbol: item for item in contracts}
        return contracts

    def fetch_historical_candles(
        self,
        request: ExchangeHistoricalCandleRequest,
    ) -> HistoricalCandleResult:
        candles: dict[int, Candle] = {}
        pages = 0
        cursor = request.start_time_ms
        latest_completed = self.fetch_latest_completed_candle_time(request.symbol)
        end_time_ms = min(request.end_time_ms, latest_completed + ONE_MINUTE_MS)
        while cursor < end_time_ms:
            page_request = ExchangeHistoricalCandleRequest(
                exchange=request.exchange,
                market_type=request.market_type,
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_time_ms=cursor,
                end_time_ms=end_time_ms,
                limit=request.limit,
            )
            page = self.fetch_historical_candle_page(page_request)
            pages += 1
            for candle in page.candles:
                candles[candle.open_time_ms] = candle
            if page.next_start_time_ms is None or not page.candles:
                break
            cursor = page.next_start_time_ms
        return HistoricalCandleResult(
            request=request,
            candles=tuple(candles[key] for key in sorted(candles)),
            pages=pages,
            latest_completed_time_ms=latest_completed,
        )

    def fetch_historical_candle_page(
        self,
        request: ExchangeHistoricalCandleRequest,
    ) -> CandlePage:
        duration_ms = timeframe_duration_ms(request.timeframe)
        limit = min(request.limit, self._page_size)
        path = "/contract/public/kline"
        params: dict[str, str | int] = {
            "symbol": self.exchange_symbol_for(request.symbol),
            "step": 1,
            "start_time": request.start_time_ms // 1000,
            "end_time": request.end_time_ms // 1000,
            "limit": limit,
        }
        payload = self._request(path, params)
        try:
            rows = self._kline_rows(payload)
            candles = tuple(
                sorted(
                    (
                        candle
                        for candle in (
                            self._candle_from_row(row, request.symbol, request.timeframe, duration_ms)
                            for row in rows
                        )
                        if request.start_time_ms <= candle.open_time_ms < request.end_time_ms
                        and candle.open_time_ms <= self.fetch_latest_completed_candle_time(request.symbol)
                    ),
                    key=lambda item: item.open_time_ms,
                ),
            )
        except Exception as exc:
            raise ValueError(
                "BitMart kline parsing failed "
                f"path={path} params={params} http_status=200 "
                f"response_body={truncate_text(json.dumps(payload, sort_keys=True, default=str))} "
                "parsed_candle_count=0",
            ) from exc
        if not candles or len(candles) < limit:
            return CandlePage(candles=candles, next_start_time_ms=None, complete=True)
        return CandlePage(
            candles=candles,
            next_start_time_ms=candles[-1].open_time_ms + duration_ms,
            complete=False,
        )

    def fetch_latest_completed_candle_time(self, _symbol: str) -> int:
        now_ms = self._clock_ms()
        if now_ms <= 0:
            return 0
        return ((now_ms // ONE_MINUTE_MS) * ONE_MINUTE_MS) - ONE_MINUTE_MS

    def normalize_symbol(self, exchange_symbol: str) -> str:
        return exchange_symbol.replace("_", "").replace("-", "").upper()

    def exchange_symbol_for(self, canonical_symbol: str) -> str:
        metadata = self.get_contract_metadata(canonical_symbol)
        if metadata is not None:
            return metadata.exchange_symbol
        if canonical_symbol.endswith("USDT"):
            return f"{canonical_symbol[:-4]}USDT"
        return canonical_symbol

    def get_contract_metadata(self, symbol: str) -> ContractMetadata | None:
        if not self._metadata:
            self.discover_contracts()
        return self._metadata.get(symbol) or self._metadata.get(self.normalize_symbol(symbol))

    def get_rate_limit_metadata(self) -> RateLimitMetadata:
        return RateLimitMetadata(requests_per_second=None, page_size=self._page_size)

    def _request(self, path: str, params: dict[str, str | int]) -> object:
        attempts = max(1, self._retry_policy.max_attempts)
        delay = self._retry_policy.backoff_seconds
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._transport.get_json(path, params)
            except Exception as exc:
                last_error = exc
                if attempt < attempts - 1 and delay > 0:
                    self._sleeper(delay)
                    delay *= self._retry_policy.multiplier
        if last_error is not None:
            raise last_error
        raise RuntimeError("BitMart request failed without an exception")

    def _contract_rows(self, payload: object) -> tuple[dict[str, object], ...]:
        data = self._payload_data(payload)
        rows = data.get("symbols") or data.get("contracts") or data.get("data")
        if not isinstance(rows, list):
            raise ValueError("BitMart contract response missing symbols list")
        return tuple(cast(dict[str, object], row) for row in rows if isinstance(row, dict))

    def _kline_rows(self, payload: object) -> tuple[dict[str, object], ...]:
        data = self._payload_data(payload)
        rows = data.get("klines") or data.get("kline") or data.get("data")
        if not isinstance(rows, list):
            raise ValueError("BitMart kline response missing klines list")
        return tuple(cast(dict[str, object], row) for row in rows if isinstance(row, dict))

    def _payload_data(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("BitMart response must be an object")
        data = payload.get("data")
        if isinstance(data, dict):
            return cast(dict[str, object], data)
        if isinstance(data, list):
            return {"data": data}
        return cast(dict[str, object], payload)

    def _contract_from_raw(self, raw: dict[str, object]) -> ContractMetadata | None:
        exchange_symbol = self._read_optional_str(raw, "symbol")
        if exchange_symbol is None:
            return None
        canonical = self.normalize_symbol(exchange_symbol)
        split_base, split_quote = split_symbol(canonical)
        base = self._read_optional_str(raw, "base_currency") or split_base
        quote = self._read_optional_str(raw, "quote_currency") or split_quote
        if not base or not quote:
            return None
        contract_type = (self._read_optional_str(raw, "contract_type") or "").lower()
        product_type = (self._read_optional_str(raw, "product_type") or "").lower()
        status_text = (self._read_optional_str(raw, "status") or "").lower()
        is_active = status_text in {"trading", "online", "open", "1"} or raw.get("trade_status") in {1, "1"}
        is_perpetual = "perpetual" in contract_type or "perpetual" in product_type or raw.get("expire_time") in {0, "0", None}
        return ContractMetadata(
            exchange=ExchangeName.BITMART,
            exchange_symbol=exchange_symbol,
            canonical_symbol=canonical,
            base_asset=base,
            quote_asset=quote,
            market_type=MarketType.USDT_M_PERPETUAL,
            status=ContractStatus.TRADING if is_active else ContractStatus.UNKNOWN,
            price_tick_size=self._read_optional_float(raw, "price_precision") or self._read_optional_float(raw, "price_tick"),
            quantity_step_size=self._read_optional_float(raw, "vol_precision") or self._read_optional_float(raw, "quantity_step"),
            listing_time_ms=self._read_optional_int(raw, "open_timestamp"),
            is_perpetual=is_perpetual,
            is_active=is_active,
            metadata_time_ms=self._clock_ms() or None,
            raw_metadata=flatten_metadata(raw),
        )

    def _candle_from_row(
        self,
        row: dict[str, object],
        symbol: str,
        timeframe: Timeframe,
        duration_ms: int,
    ) -> Candle:
        open_time_s = self._read_required_int(row, "timestamp", "time", "ts")
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open_time_ms=open_time_s * 1000,
            close_time_ms=open_time_s * 1000 + duration_ms,
            open=self._read_required_float(row, "open", "open_price", "o"),
            high=self._read_required_float(row, "high", "high_price", "h"),
            low=self._read_required_float(row, "low", "low_price", "l"),
            close=self._read_required_float(row, "close", "close_price", "c"),
            volume=self._read_required_float(row, "volume", "vol", "v"),
        )

    def _read_optional_str(self, raw: dict[str, object], key: str) -> str | None:
        value = raw.get(key)
        return value if isinstance(value, str) and value else None

    def _read_optional_float(self, raw: dict[str, object], key: str) -> float | None:
        value = raw.get(key)
        if value is None:
            return None
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    def _read_optional_int(self, raw: dict[str, object], key: str) -> int | None:
        value = raw.get(key)
        if value is None:
            return None
        try:
            number = int(str(value))
        except (TypeError, ValueError):
            return None
        return number * 1000 if number < 10_000_000_000 else number

    def _read_required_int(self, raw: dict[str, object], *keys: str) -> int:
        for key in keys:
            raw_value = raw.get(key)
            if raw_value is None:
                continue
            try:
                return int(str(raw_value))
            except (TypeError, ValueError):
                continue
        raise ValueError(f"BitMart kline row missing integer field {keys}")

    def _read_required_float(self, raw: dict[str, object], *keys: str) -> float:
        for key in keys:
            value = self._read_optional_float(raw, key)
            if value is not None:
                return value
        raise ValueError(f"BitMart kline row missing numeric field {keys}")


def split_symbol(canonical_symbol: str) -> tuple[str, str]:
    if canonical_symbol.endswith("USDT"):
        return canonical_symbol[:-4], "USDT"
    if canonical_symbol.endswith("USDC"):
        return canonical_symbol[:-4], "USDC"
    return canonical_symbol, ""


def flatten_metadata(raw: dict[str, object]) -> dict[str, str | int | float | bool | None]:
    flat: dict[str, str | int | float | bool | None] = {}
    for key, value in raw.items():
        if value is None or isinstance(value, str | int | float | bool):
            flat[key] = value
    return flat


def truncate_text(value: str, *, limit: int = 1000) -> str:
    return value if len(value) <= limit else f"{value[:limit]}...<truncated>"
