from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from time import sleep, time
from typing import Callable, Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlparse, urlencode
from urllib.request import Request, urlopen

from backend.exchange.models import (
    CandlePage,
    ContractMetadata,
    ContractStatus,
    ExchangeHistoricalCandleRequest,
    ExchangeName,
    HistoricalDataGap,
    HistoricalGapRecoveryStatus,
    HistoricalCandleResult,
    HistoricalIntegrityPolicy,
    HistoricalIntegrityReport,
    HistoricalIntegrityStatus,
    MarketType,
    RateLimitMetadata,
)
from backend.models import Candle, Timeframe
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms


BITMART_FUTURES_BASE_URL = "https://api-cloud-v2.bitmart.com"
ONE_MINUTE_MS = 60_000
LOGGER = logging.getLogger(__name__)
LATEST_AVAILABLE_PROBE_CANDLE_COUNT = 10


@dataclass(frozen=True, slots=True)
class MissingCandleInterval:
    start_time_ms: int
    end_time_ms: int
    duration_ms: int

    @property
    def timestamps_ms(self) -> tuple[int, ...]:
        return tuple(range(self.start_time_ms, self.end_time_ms, self.duration_ms))


@dataclass(frozen=True, slots=True)
class SparseKlineNormalizationResult:
    candles: tuple[Candle, ...]
    exchange_candle_count: int
    synthetic_candle_count: int


class HistoricalDataGapError(RuntimeError):
    """Raised when BitMart historical candles remain non-contiguous after bounded recovery."""

    def __init__(
        self,
        *,
        symbol: str,
        timeframe: Timeframe,
        interval: MissingCandleInterval,
        retry_count: int,
        page_context: str,
    ) -> None:
        super().__init__(
            "BitMart historical data gap could not be recovered "
            f"symbol={symbol} timeframe={timeframe.value} "
            f"missing_start_time_ms={interval.start_time_ms} "
            f"missing_end_time_ms={interval.end_time_ms} "
            f"missing_start_utc={format_utc_ms(interval.start_time_ms)} "
            f"missing_end_utc={format_utc_ms(interval.end_time_ms)} "
            f"missing_timestamps_ms={interval.timestamps_ms} "
            f"retry_count={retry_count} page_context={page_context}",
        )
        self.symbol = symbol
        self.timeframe = timeframe
        self.interval = interval
        self.retry_count = retry_count
        self.page_context = page_context


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

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

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
            LOGGER.exception(
                "BitMart HTTP request failed",
                extra={
                    "operation": "bitmart_historical_rest_request",
                    "method": "GET",
                    "endpoint_url": url,
                    "base_url": self._base_url,
                    "path": path,
                    "parsed_hostname": urlparse(self._base_url).hostname,
                    "symbol": params.get("symbol"),
                    "request_start_time": params.get("start_time"),
                    "request_end_time": params.get("end_time"),
                    "timeout_seconds": self._timeout_seconds,
                    "thread_name": threading.current_thread().name,
                    "http_status": exc.code,
                },
            )
            raise RuntimeError(
                f"BitMart HTTP request failed url={url} status={exc.code} body={truncate_text(body)}",
            ) from exc
        except Exception:
            LOGGER.exception(
                "BitMart HTTP request raised",
                extra={
                    "operation": "bitmart_historical_rest_request",
                    "method": "GET",
                    "endpoint_url": url,
                    "base_url": self._base_url,
                    "path": path,
                    "parsed_hostname": urlparse(self._base_url).hostname,
                    "symbol": params.get("symbol"),
                    "request_start_time": params.get("start_time"),
                    "request_end_time": params.get("end_time"),
                    "timeout_seconds": self._timeout_seconds,
                    "thread_name": threading.current_thread().name,
                },
            )
            raise


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
        max_gap_recovery_attempts: int = 3,
        gap_recovery_backoff_seconds: float = 0.2,
    ) -> None:
        self._transport = transport or UrlLibJsonTransport()
        self._retry_policy = retry_policy or RetryPolicy()
        self._page_size = page_size
        self._clock_ms = clock_ms or (lambda: int(time() * 1000))
        self._sleeper = sleeper or sleep
        self._max_gap_recovery_attempts = max(1, max_gap_recovery_attempts)
        self._gap_recovery_backoff_seconds = max(0.0, gap_recovery_backoff_seconds)
        self._metadata: dict[str, ContractMetadata] = {}
        self._active_latest_completed_time_ms: int | None = None

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
        duration_ms = timeframe_duration_ms(request.timeframe)
        window_ms = duration_ms * min(request.limit, self._page_size)
        latest_completed = self.fetch_latest_completed_candle_time(request.symbol)
        end_time_ms = min(request.end_time_ms, latest_completed + duration_ms)
        previous_active_latest = self._active_latest_completed_time_ms
        self._active_latest_completed_time_ms = latest_completed
        try:
            while cursor < end_time_ms:
                page_end_time_ms = min(cursor + window_ms, end_time_ms)
                page_request = ExchangeHistoricalCandleRequest(
                    exchange=request.exchange,
                    market_type=request.market_type,
                    symbol=request.symbol,
                    timeframe=request.timeframe,
                    start_time_ms=cursor,
                    end_time_ms=page_end_time_ms,
                    limit=request.limit,
                )
                page = self.fetch_historical_candle_page(page_request)
                pages += 1
                if not page.candles:
                    if self._is_freshest_tail_page(cursor, page_end_time_ms, end_time_ms, latest_completed, duration_ms):
                        LOGGER.warning(
                            "BitMart freshest historical tail is temporarily unavailable "
                            "symbol=%s timeframe=%s page_start_time_ms=%s page_end_time_ms=%s "
                            "latest_confirmed_open_time_ms=%s",
                            request.symbol,
                            request.timeframe.value,
                            cursor,
                            page_end_time_ms,
                            latest_completed,
                            extra={
                                "symbol": request.symbol,
                                "timeframe": request.timeframe.value,
                                "page_start_time_ms": cursor,
                                "page_end_time_ms": page_end_time_ms,
                                "latest_confirmed_open_time_ms": latest_completed,
                                "skipped_unavailable_tail_range": (cursor, page_end_time_ms),
                            },
                        )
                        break
                    page = self._normalize_empty_historical_page_if_confirmed(
                        page_request,
                        duration_ms=duration_ms,
                        latest_completed_open_time_ms=latest_completed,
                    )
                    if not page.candles:
                        raise RuntimeError(
                            "BitMart historical page returned zero candles "
                            f"symbol={request.symbol} timeframe={request.timeframe.value} "
                            f"page_start_time_ms={cursor} page_end_time_ms={page_end_time_ms} "
                            f"limit={min(request.limit, self._page_size)} http_status=200",
                        )
                for candle in page.candles:
                    self._merge_candle_by_precedence(candles, candle)
                next_cursor = page.next_start_time_ms
                LOGGER.info(
                    "Fetched BitMart historical candle page "
                    "symbol=%s timeframe=%s page_start_time_ms=%s page_end_time_ms=%s "
                    "returned_candle_count=%s next_cursor_time_ms=%s total_accumulated_candle_count=%s",
                    request.symbol,
                    request.timeframe.value,
                    cursor,
                    page_end_time_ms,
                    len(page.candles),
                    next_cursor,
                    len(candles),
                    extra={
                        "symbol": request.symbol,
                        "timeframe": request.timeframe.value,
                        "page_start_time_ms": cursor,
                        "page_end_time_ms": page_end_time_ms,
                        "limit": min(request.limit, self._page_size),
                        "http_status": 200,
                        "returned_candle_count": len(page.candles),
                        "first_returned_open_time_ms": page.candles[0].open_time_ms,
                        "first_returned_open_utc": format_utc_ms(page.candles[0].open_time_ms),
                        "last_returned_open_time_ms": page.candles[-1].open_time_ms,
                        "last_returned_open_utc": format_utc_ms(page.candles[-1].open_time_ms),
                        "expected_next_time_ms": page_end_time_ms,
                        "expected_next_utc": format_utc_ms(page_end_time_ms),
                        "next_cursor_time_ms": next_cursor,
                        "total_accumulated_candle_count": len(candles),
                    },
                )
                if next_cursor is None:
                    if page_end_time_ms < end_time_ms:
                        raise RuntimeError(
                            "BitMart historical pagination stopped before requested range ended "
                            f"symbol={request.symbol} timeframe={request.timeframe.value} "
                            f"page_start_time_ms={cursor} page_end_time_ms={page_end_time_ms} "
                            f"requested_end_time_ms={end_time_ms}",
                        )
                    break
                if next_cursor <= cursor:
                    raise RuntimeError(
                        "BitMart historical pagination cursor did not advance "
                        f"symbol={request.symbol} timeframe={request.timeframe.value} "
                        f"page_start_time_ms={cursor} page_end_time_ms={page_end_time_ms} "
                        f"next_cursor_time_ms={next_cursor}",
                    )
                cursor = next_cursor
        finally:
            self._active_latest_completed_time_ms = previous_active_latest
        normalization = self._normalize_sparse_klines(
            tuple(candles[key] for key in sorted(candles)),
            request,
            end_time_ms,
            duration_ms,
        )
        sorted_candles = normalization.candles
        sorted_candles, recovery_pages, unrecovered_gaps = self._recover_gaps_if_needed(
            sorted_candles,
            request,
            end_time_ms,
            duration_ms,
            window_ms,
        )
        pages += recovery_pages
        exchange_candle_count = sum(1 for candle in sorted_candles if candle.source_kind == "exchange")
        synthetic_candle_count = sum(1 for candle in sorted_candles if candle.source_kind == "synthetic_no_trade")
        requested_candle_count = max(0, (end_time_ms - request.start_time_ms) // duration_ms)
        if not unrecovered_gaps:
            self._validate_contiguous_candles(sorted_candles, request, end_time_ms, duration_ms)
            integrity_report = HistoricalIntegrityReport.valid(
                request,
                requested_candle_count=requested_candle_count,
                loaded_candle_count=len(sorted_candles),
                exchange_candle_count=exchange_candle_count,
                synthetic_candle_count=synthetic_candle_count,
                canonical_candle_count=len(sorted_candles),
            )
        else:
            integrity_report = HistoricalIntegrityReport.from_gaps(
                request,
                status=(
                    HistoricalIntegrityStatus.DEGRADED
                    if request.integrity_policy is HistoricalIntegrityPolicy.WARN
                    else HistoricalIntegrityStatus.INCOMPLETE
                ),
                gaps=unrecovered_gaps,
                requested_candle_count=requested_candle_count,
                loaded_candle_count=len(sorted_candles),
                exchange_candle_count=exchange_candle_count,
                synthetic_candle_count=synthetic_candle_count,
                canonical_candle_count=len(sorted_candles),
            )
            LOGGER.warning(
                "Continuing with incomplete BitMart historical data "
                "policy=%s status=%s symbol=%s timeframe=%s requested_candle_count=%s "
                "loaded_candle_count=%s gap_count=%s total_missing_candles=%s",
                integrity_report.policy.value,
                integrity_report.status.value,
                request.symbol,
                request.timeframe.value,
                integrity_report.requested_candle_count,
                integrity_report.loaded_candle_count,
                integrity_report.gap_count,
                integrity_report.total_missing_candles,
            )
        return HistoricalCandleResult(
            request=request,
            candles=sorted_candles,
            pages=pages,
            latest_completed_time_ms=latest_completed,
            integrity_report=integrity_report,
        )

    def fetch_historical_candle_page(
        self,
        request: ExchangeHistoricalCandleRequest,
    ) -> CandlePage:
        duration_ms = timeframe_duration_ms(request.timeframe)
        limit = min(request.limit, self._page_size)
        latest_completed = self._active_latest_completed_time_ms
        if latest_completed is None:
            latest_completed = self.fetch_latest_completed_candle_time(request.symbol)
        return self._fetch_historical_candle_page(
            request,
            duration_ms=duration_ms,
            limit=limit,
            latest_completed_open_time_ms=latest_completed,
        )

    def _fetch_historical_candle_page(
        self,
        request: ExchangeHistoricalCandleRequest,
        *,
        duration_ms: int,
        limit: int,
        latest_completed_open_time_ms: int,
    ) -> CandlePage:
        path = "/contract/public/kline"
        params: dict[str, str | int] = {
            "symbol": self.exchange_symbol_for(request.symbol),
            "step": duration_ms // ONE_MINUTE_MS,
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
                        and candle.open_time_ms <= latest_completed_open_time_ms
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
            return CandlePage(candles=candles, next_start_time_ms=request.end_time_ms, complete=True)
        return CandlePage(
            candles=candles,
            next_start_time_ms=request.end_time_ms,
            complete=False,
        )

    def _normalize_empty_historical_page_if_confirmed(
        self,
        request: ExchangeHistoricalCandleRequest,
        *,
        duration_ms: int,
        latest_completed_open_time_ms: int,
    ) -> CandlePage:
        context_start_ms = max(0, request.start_time_ms - duration_ms)
        context_end_ms = min(request.end_time_ms + duration_ms, latest_completed_open_time_ms + duration_ms)
        if context_start_ms >= request.start_time_ms or context_end_ms <= request.end_time_ms:
            return CandlePage(candles=(), next_start_time_ms=request.end_time_ms, complete=True)
        context_request = ExchangeHistoricalCandleRequest(
            exchange=request.exchange,
            market_type=request.market_type,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_time_ms=context_start_ms,
            end_time_ms=context_end_ms,
            limit=max(3, request.limit),
            integrity_policy=request.integrity_policy,
        )
        context_page = self._fetch_historical_candle_page(
            context_request,
            duration_ms=duration_ms,
            limit=max(3, min(request.limit, self._page_size)),
            latest_completed_open_time_ms=latest_completed_open_time_ms,
        )
        context_by_open = {candle.open_time_ms: candle for candle in context_page.candles}
        previous = context_by_open.get(request.start_time_ms - duration_ms)
        later = next((candle for candle in context_page.candles if candle.open_time_ms >= request.end_time_ms), None)
        if previous is None or later is None:
            return CandlePage(candles=(), next_start_time_ms=request.end_time_ms, complete=True)
        synthetic = self._synthetic_no_trade_candles(
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_time_ms=request.start_time_ms,
            end_time_ms=request.end_time_ms,
            duration_ms=duration_ms,
            previous_close=previous.close,
        )
        LOGGER.info(
            "Normalized BitMart sparse historical empty page as no-trade candles "
            "symbol=%s timeframe=%s start_time_ms=%s end_time_ms=%s synthetic_count=%s",
            request.symbol,
            request.timeframe.value,
            request.start_time_ms,
            request.end_time_ms,
            len(synthetic),
            extra={
                "symbol": request.symbol,
                "timeframe": request.timeframe.value,
                "start_time_ms": request.start_time_ms,
                "end_time_ms": request.end_time_ms,
                "synthetic_no_trade_candle_count": len(synthetic),
                "context_start_time_ms": context_start_ms,
                "context_end_time_ms": context_end_ms,
            },
        )
        return CandlePage(candles=synthetic, next_start_time_ms=request.end_time_ms, complete=True)

    def _normalize_sparse_klines(
        self,
        candles: tuple[Candle, ...],
        request: ExchangeHistoricalCandleRequest,
        end_time_ms: int,
        duration_ms: int,
    ) -> SparseKlineNormalizationResult:
        if not candles:
            return SparseKlineNormalizationResult(candles=(), exchange_candle_count=0, synthetic_candle_count=0)
        normalized: dict[int, Candle] = {}
        synthetic_count = 0
        previous: Candle | None = None
        for candle in sorted(candles, key=lambda item: item.open_time_ms):
            if previous is not None and previous.close_time_ms < candle.open_time_ms:
                synthetic = self._synthetic_no_trade_candles(
                    symbol=request.symbol,
                    timeframe=request.timeframe,
                    start_time_ms=previous.close_time_ms,
                    end_time_ms=candle.open_time_ms,
                    duration_ms=duration_ms,
                    previous_close=previous.close,
                )
                synthetic_count += len(synthetic)
                for synthetic_candle in synthetic:
                    self._merge_candle_by_precedence(normalized, synthetic_candle)
            self._merge_candle_by_precedence(normalized, candle)
            previous = candle
        sorted_normalized = tuple(normalized[key] for key in sorted(normalized))
        exchange_count = sum(1 for candle in sorted_normalized if candle.source_kind == "exchange")
        if synthetic_count:
            LOGGER.info(
                "Normalized BitMart sparse historical klines "
                "symbol=%s timeframe=%s synthetic_count=%s canonical_count=%s",
                request.symbol,
                request.timeframe.value,
                synthetic_count,
                len(sorted_normalized),
                extra={
                    "symbol": request.symbol,
                    "timeframe": request.timeframe.value,
                    "synthetic_no_trade_candle_count": synthetic_count,
                    "canonical_candle_count": len(sorted_normalized),
                    "request_start_time_ms": request.start_time_ms,
                    "request_end_time_ms": end_time_ms,
                },
            )
        return SparseKlineNormalizationResult(
            candles=sorted_normalized,
            exchange_candle_count=exchange_count,
            synthetic_candle_count=synthetic_count,
        )

    def _synthetic_no_trade_candles(
        self,
        *,
        symbol: str,
        timeframe: Timeframe,
        start_time_ms: int,
        end_time_ms: int,
        duration_ms: int,
        previous_close: float,
    ) -> tuple[Candle, ...]:
        return tuple(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time_ms=open_time_ms,
                close_time_ms=open_time_ms + duration_ms,
                open=previous_close,
                high=previous_close,
                low=previous_close,
                close=previous_close,
                volume=0.0,
                source_kind="synthetic_no_trade",
            )
            for open_time_ms in range(start_time_ms, end_time_ms, duration_ms)
        )

    def _merge_candle_by_precedence(self, candles: dict[int, Candle], candle: Candle) -> None:
        existing = candles.get(candle.open_time_ms)
        if existing is None or (existing.source_kind == "synthetic_no_trade" and candle.source_kind == "exchange"):
            candles[candle.open_time_ms] = candle

    def fetch_latest_completed_candle_time(self, _symbol: str) -> int:
        theoretical_latest = self._theoretical_latest_completed_open_time_ms()
        if theoretical_latest <= 0:
            return 0
        probe_start_ms = max(0, theoretical_latest - (LATEST_AVAILABLE_PROBE_CANDLE_COUNT - 1) * ONE_MINUTE_MS)
        probe_request = ExchangeHistoricalCandleRequest(
            exchange=ExchangeName.BITMART,
            market_type=MarketType.USDT_M_PERPETUAL,
            symbol=_symbol,
            timeframe=Timeframe.ONE_MINUTE,
            start_time_ms=probe_start_ms,
            end_time_ms=theoretical_latest + ONE_MINUTE_MS,
            limit=LATEST_AVAILABLE_PROBE_CANDLE_COUNT,
        )
        LOGGER.info(
            "Starting BitMart latest historical candle availability probe",
            extra={
                "operation": "bitmart_latest_candle_probe",
                "rest_base_url": self._transport_base_url(),
                "parsed_hostname": self._transport_hostname(),
                "symbol": _symbol,
                "timeout_seconds": self._transport_timeout_seconds(),
                "retry_attempt": 1,
                "thread_name": threading.current_thread().name,
            },
        )
        try:
            page = self._fetch_historical_candle_page(
                probe_request,
                duration_ms=ONE_MINUTE_MS,
                limit=LATEST_AVAILABLE_PROBE_CANDLE_COUNT,
                latest_completed_open_time_ms=theoretical_latest,
            )
        except Exception as exc:
            fallback = self._conservative_latest_completed_open_time_ms(theoretical_latest)
            LOGGER.exception(
                "BitMart latest historical candle probe failed; using conservative fallback "
                "symbol=%s theoretical_latest_open_time_ms=%s fallback_open_time_ms=%s error=%s",
                _symbol,
                theoretical_latest,
                fallback,
                exc,
                extra={
                    "symbol": _symbol,
                    "theoretical_latest_open_time_ms": theoretical_latest,
                    "fallback_open_time_ms": fallback,
                    "probe_error": str(exc),
                    "operation": "bitmart_latest_candle_probe",
                    "rest_base_url": self._transport_base_url(),
                    "parsed_hostname": self._transport_hostname(),
                    "timeout_seconds": self._transport_timeout_seconds(),
                    "exception_type": type(exc).__name__,
                    "thread_name": threading.current_thread().name,
                },
            )
            return fallback
        if not page.candles:
            fallback = self._conservative_latest_completed_open_time_ms(theoretical_latest)
            LOGGER.warning(
                "BitMart latest historical candle probe returned no candles; using conservative fallback "
                "symbol=%s theoretical_latest_open_time_ms=%s fallback_open_time_ms=%s",
                _symbol,
                theoretical_latest,
                fallback,
                extra={
                    "symbol": _symbol,
                    "theoretical_latest_open_time_ms": theoretical_latest,
                    "fallback_open_time_ms": fallback,
                    "probe_start_time_ms": probe_start_ms,
                    "probe_end_time_ms": theoretical_latest + ONE_MINUTE_MS,
                },
            )
            return fallback
        latest_available = page.candles[-1].open_time_ms
        LOGGER.info(
            "Confirmed latest BitMart historical candle availability "
            "symbol=%s theoretical_latest_open_time_ms=%s latest_available_open_time_ms=%s",
            _symbol,
            theoretical_latest,
            latest_available,
            extra={
                "symbol": _symbol,
                "theoretical_latest_open_time_ms": theoretical_latest,
                "latest_available_open_time_ms": latest_available,
                "probe_start_time_ms": probe_start_ms,
                "probe_end_time_ms": theoretical_latest + ONE_MINUTE_MS,
                "probe_returned_candle_count": len(page.candles),
            },
        )
        return latest_available

    def _theoretical_latest_completed_open_time_ms(self) -> int:
        now_ms = self._clock_ms()
        if now_ms <= 0:
            return 0
        return ((now_ms // ONE_MINUTE_MS) * ONE_MINUTE_MS) - ONE_MINUTE_MS

    def _conservative_latest_completed_open_time_ms(self, theoretical_latest_open_time_ms: int) -> int:
        return max(0, theoretical_latest_open_time_ms - ONE_MINUTE_MS)

    def _is_freshest_tail_page(
        self,
        page_start_time_ms: int,
        page_end_time_ms: int,
        request_end_time_ms: int,
        latest_completed_open_time_ms: int,
        duration_ms: int,
    ) -> bool:
        return (
            page_end_time_ms == request_end_time_ms
            and request_end_time_ms == latest_completed_open_time_ms + duration_ms
            and page_start_time_ms <= latest_completed_open_time_ms
        )

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
                LOGGER.exception(
                    "BitMart REST request attempt failed",
                    extra={
                        "operation": "bitmart_historical_rest_request",
                        "method": "GET",
                        "base_url": self._transport_base_url(),
                        "path": path,
                        "parsed_hostname": self._transport_hostname(),
                        "symbol": params.get("symbol"),
                        "request_start_time": params.get("start_time"),
                        "request_end_time": params.get("end_time"),
                        "attempt_number": attempt + 1,
                        "max_attempts": attempts,
                        "timeout_seconds": self._transport_timeout_seconds(),
                        "thread_name": threading.current_thread().name,
                        "exception_type": type(exc).__name__,
                    },
                )
                if attempt < attempts - 1 and delay > 0:
                    self._sleeper(delay)
                    delay *= self._retry_policy.multiplier
        if last_error is not None:
            raise last_error
        raise RuntimeError("BitMart request failed without an exception")

    def _transport_base_url(self) -> str:
        return str(getattr(self._transport, "base_url", "unknown"))

    def _transport_timeout_seconds(self) -> float | None:
        value = getattr(self._transport, "timeout_seconds", None)
        return float(value) if value is not None else None

    def _transport_hostname(self) -> str | None:
        base_url = self._transport_base_url()
        if base_url == "unknown":
            return None
        return urlparse(base_url).hostname

    def _validate_contiguous_candles(
        self,
        candles: tuple[Candle, ...],
        request: ExchangeHistoricalCandleRequest,
        end_time_ms: int,
        duration_ms: int,
    ) -> None:
        expected_time = request.start_time_ms
        for candle in candles:
            if candle.open_time_ms != expected_time:
                raise RuntimeError(
                    "BitMart historical candles are not contiguous "
                    f"symbol={request.symbol} timeframe={request.timeframe.value} "
                    f"expected_open_time_ms={expected_time} actual_open_time_ms={candle.open_time_ms}",
                )
            expected_time += duration_ms
        if candles and expected_time < end_time_ms:
            raise RuntimeError(
                "BitMart historical candles ended before requested range "
                f"symbol={request.symbol} timeframe={request.timeframe.value} "
                f"expected_next_open_time_ms={expected_time} requested_end_time_ms={end_time_ms}",
            )

    def _recover_gaps_if_needed(
        self,
        candles: tuple[Candle, ...],
        request: ExchangeHistoricalCandleRequest,
        end_time_ms: int,
        duration_ms: int,
        window_ms: int,
    ) -> tuple[tuple[Candle, ...], int, tuple[HistoricalDataGap, ...]]:
        recovery_pages = 0
        merged = {candle.open_time_ms: candle for candle in candles}
        unrecovered_gaps: list[HistoricalDataGap] = []
        while True:
            sorted_candles = tuple(merged[key] for key in sorted(merged))
            gaps = self._missing_intervals(sorted_candles, request.start_time_ms, end_time_ms, duration_ms)
            if not gaps:
                LOGGER.info(
                    "BitMart historical contiguous validation passed "
                    "symbol=%s timeframe=%s candle_count=%s start_utc=%s end_utc=%s",
                    request.symbol,
                    request.timeframe.value,
                    len(sorted_candles),
                    format_utc_ms(request.start_time_ms),
                    format_utc_ms(end_time_ms),
                    extra={
                        "symbol": request.symbol,
                        "timeframe": request.timeframe.value,
                        "candle_count": len(sorted_candles),
                        "start_time_ms": request.start_time_ms,
                        "start_utc": format_utc_ms(request.start_time_ms),
                        "end_time_ms": end_time_ms,
                        "end_utc": format_utc_ms(end_time_ms),
                    },
                )
                return sorted_candles, recovery_pages, tuple(unrecovered_gaps)
            for interval in gaps:
                recovered, pages, unrecovered = self._recover_missing_interval(request, interval, duration_ms, window_ms)
                recovery_pages += pages
                if unrecovered is not None:
                    unrecovered_gaps.append(unrecovered)
                    continue
                for candle in recovered:
                    merged[candle.open_time_ms] = candle
            if unrecovered_gaps:
                return tuple(merged[key] for key in sorted(merged)), recovery_pages, tuple(unrecovered_gaps)

    def _missing_intervals(
        self,
        candles: tuple[Candle, ...],
        start_time_ms: int,
        end_time_ms: int,
        duration_ms: int,
    ) -> tuple[MissingCandleInterval, ...]:
        missing: list[MissingCandleInterval] = []
        expected_time_ms = start_time_ms
        for candle in candles:
            if candle.open_time_ms < expected_time_ms:
                continue
            if candle.open_time_ms > expected_time_ms:
                missing.append(MissingCandleInterval(expected_time_ms, candle.open_time_ms, duration_ms))
            expected_time_ms = candle.open_time_ms + duration_ms
        if expected_time_ms < end_time_ms:
            missing.append(MissingCandleInterval(expected_time_ms, end_time_ms, duration_ms))
        return tuple(missing)

    def _recover_missing_interval(
        self,
        request: ExchangeHistoricalCandleRequest,
        interval: MissingCandleInterval,
        duration_ms: int,
        window_ms: int,
    ) -> tuple[tuple[Candle, ...], int, HistoricalDataGap | None]:
        recovered: dict[int, Candle] = {}
        recovery_pages = 0
        LOGGER.warning(
            "Detected BitMart historical gap "
            "symbol=%s timeframe=%s missing_start_utc=%s missing_end_utc=%s missing_timestamps_ms=%s",
            request.symbol,
            request.timeframe.value,
            format_utc_ms(interval.start_time_ms),
            format_utc_ms(interval.end_time_ms),
            interval.timestamps_ms,
            extra={
                "symbol": request.symbol,
                "timeframe": request.timeframe.value,
                "missing_start_time_ms": interval.start_time_ms,
                "missing_start_utc": format_utc_ms(interval.start_time_ms),
                "missing_end_time_ms": interval.end_time_ms,
                "missing_end_utc": format_utc_ms(interval.end_time_ms),
                "missing_timestamps_ms": interval.timestamps_ms,
            },
        )
        for attempt in range(1, self._max_gap_recovery_attempts + 1):
            attempt_recovered: dict[int, Candle] = {}
            cursor = interval.start_time_ms
            while cursor < interval.end_time_ms:
                page_end_time_ms = min(cursor + window_ms, interval.end_time_ms)
                page_request = ExchangeHistoricalCandleRequest(
                    exchange=request.exchange,
                    market_type=request.market_type,
                    symbol=request.symbol,
                    timeframe=request.timeframe,
                    start_time_ms=cursor,
                    end_time_ms=page_end_time_ms,
                    limit=request.limit,
                )
                page = self.fetch_historical_candle_page(page_request)
                recovery_pages += 1
                for candle in page.candles:
                    attempt_recovered[candle.open_time_ms] = candle
                next_cursor = page.next_start_time_ms or page_end_time_ms
                LOGGER.warning(
                    "Retried BitMart historical gap page "
                    "symbol=%s timeframe=%s attempt=%s recovery_start_utc=%s recovery_end_utc=%s "
                    "returned_candle_count=%s next_cursor_time_ms=%s total_attempt_recovered_count=%s",
                    request.symbol,
                    request.timeframe.value,
                    attempt,
                    format_utc_ms(cursor),
                    format_utc_ms(page_end_time_ms),
                    len(page.candles),
                    next_cursor,
                    len(attempt_recovered),
                    extra={
                        "symbol": request.symbol,
                        "timeframe": request.timeframe.value,
                        "attempt": attempt,
                        "recovery_start_time_ms": cursor,
                        "recovery_start_utc": format_utc_ms(cursor),
                        "recovery_end_time_ms": page_end_time_ms,
                        "recovery_end_utc": format_utc_ms(page_end_time_ms),
                        "returned_candle_count": len(page.candles),
                        "next_cursor_time_ms": next_cursor,
                        "total_attempt_recovered_count": len(attempt_recovered),
                    },
                )
                if next_cursor <= cursor:
                    raise RuntimeError(
                        "BitMart historical gap recovery cursor did not advance "
                        f"symbol={request.symbol} timeframe={request.timeframe.value} "
                        f"attempt={attempt} recovery_start_time_ms={cursor} "
                        f"recovery_end_time_ms={page_end_time_ms} next_cursor_time_ms={next_cursor}",
                    )
                cursor = next_cursor
            attempt_candles = tuple(attempt_recovered[key] for key in sorted(attempt_recovered))
            if not self._missing_intervals(attempt_candles, interval.start_time_ms, interval.end_time_ms, duration_ms):
                return attempt_candles, recovery_pages, None
            recovered.update(attempt_recovered)
            if attempt < self._max_gap_recovery_attempts and self._gap_recovery_backoff_seconds:
                self._sleeper(self._gap_recovery_backoff_seconds)
        recovered_candles = tuple(recovered[key] for key in sorted(recovered))
        if self._missing_intervals(recovered_candles, interval.start_time_ms, interval.end_time_ms, duration_ms):
            gap = HistoricalDataGap(
                symbol=request.symbol,
                timeframe=request.timeframe,
                start_open_time_ms=interval.start_time_ms,
                end_open_time_ms=interval.end_time_ms,
                missing_candle_count=len(interval.timestamps_ms),
                missing_open_times_ms=interval.timestamps_ms,
                retry_count=self._max_gap_recovery_attempts,
                exchange=request.exchange,
                recovery_status=HistoricalGapRecoveryStatus.UNRECOVERABLE,
                detected_at_ms=self._clock_ms(),
            )
            LOGGER.warning(
                "BitMart historical gap remains unrecovered "
                "policy=%s symbol=%s timeframe=%s missing_start_utc=%s missing_end_utc=%s "
                "missing_candle_count=%s retry_count=%s",
                request.integrity_policy.value,
                request.symbol,
                request.timeframe.value,
                format_utc_ms(interval.start_time_ms),
                format_utc_ms(interval.end_time_ms),
                gap.missing_candle_count,
                self._max_gap_recovery_attempts,
            )
            if request.integrity_policy is not HistoricalIntegrityPolicy.STRICT:
                return recovered_candles, recovery_pages, gap
            raise HistoricalDataGapError(
                symbol=request.symbol,
                timeframe=request.timeframe,
                interval=interval,
                retry_count=self._max_gap_recovery_attempts,
                page_context="narrow_gap_recovery_incomplete",
            )
        return recovered_candles, recovery_pages, None

    def _contract_rows(self, payload: object) -> tuple[dict[str, object], ...]:
        data = self._payload_data(payload)
        rows = data.get("symbols") or data.get("contracts") or data.get("data")
        if not isinstance(rows, list):
            raise ValueError("BitMart contract response missing symbols list")
        return tuple(cast(dict[str, object], row) for row in rows if isinstance(row, dict))

    def _kline_rows(self, payload: object) -> tuple[dict[str, object], ...]:
        data = self._payload_data(payload)
        rows = first_present(data, "klines", "kline", "data")
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


def format_utc_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def first_present(payload: dict[str, object], *keys: str) -> object:
    for key in keys:
        if key in payload:
            return payload[key]
    return None
