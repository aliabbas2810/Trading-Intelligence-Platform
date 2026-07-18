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
    HistoricalDataGap,
    HistoricalGapRecoveryStatus,
    MarketType,
    HistoricalIntegrityPolicy,
    HistoricalIntegrityReport,
    HistoricalIntegrityStatus,
)
from backend.models import Candle, Timeframe
from backend.pipelines.timeframe.aggregation import timeframe_duration_ms


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


@dataclass(frozen=True, slots=True)
class HistoricalCandleLoadResult:
    candles: tuple[Candle, ...]
    integrity_report: HistoricalIntegrityReport


class HistoricalCandleFileStore:
    """Local JSONL storage for M27 historical candle fixtures/downloads."""

    def __init__(self, root: Path = DEFAULT_HISTORICAL_DATA_ROOT) -> None:
        self._root = root

    def path_for(self, request: HistoricalCandleRequest) -> Path:
        filename = f"{request.start_time_ms}_{request.end_time_ms}.jsonl"
        return self._root / request.exchange / request.market_type / request.symbol / request.timeframe.value / filename

    def integrity_path_for(self, request: HistoricalCandleRequest) -> Path:
        return self.path_for(request).with_suffix(".integrity.json")

    def save(self, request: HistoricalCandleRequest, candles: Iterable[Candle]) -> Path:
        sorted_candles = self._normalized_candles(candles)
        report = HistoricalIntegrityReport.valid(
            exchange_request_from_historical_request(
                request,
                integrity_policy=HistoricalIntegrityPolicy.STRICT,
            ),
            requested_candle_count=expected_candle_count(request),
            loaded_candle_count=len(sorted_candles),
        )
        return self.save_result(
            request,
            HistoricalCandleLoadResult(candles=sorted_candles, integrity_report=report),
        )

    def save_result(self, request: HistoricalCandleRequest, result: HistoricalCandleLoadResult) -> Path:
        path = self.path_for(request)
        sorted_candles = self._normalized_candles(result.candles)
        if not sorted_candles:
            raise ValueError(f"Refusing to create empty historical candle cache at {path}")
        self._validate_report_identity(request, result.integrity_report)
        path.parent.mkdir(parents=True, exist_ok=True)
        integrity_path = self.integrity_path_for(request)
        temporary_data_path = path.with_suffix(".jsonl.tmp")
        temporary_integrity_path = integrity_path.with_suffix(".json.tmp")
        temporary_integrity_path.write_text(
            json.dumps(integrity_report_to_payload(result.integrity_report), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        with temporary_data_path.open("w", encoding="utf-8") as file:
            for candle in sorted_candles:
                payload = asdict(candle)
                payload["timeframe"] = candle.timeframe.value
                file.write(json.dumps(payload, sort_keys=True))
                file.write("\n")
        temporary_data_path.replace(path)
        temporary_integrity_path.replace(integrity_path)
        return path

    def load(self, request: HistoricalCandleRequest) -> tuple[Candle, ...]:
        return self.load_result(request, integrity_policy=HistoricalIntegrityPolicy.STRICT).candles

    def load_result(
        self,
        request: HistoricalCandleRequest,
        *,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> HistoricalCandleLoadResult:
        path = self.path_for(request)
        candles = self.load_path(path)
        report = self.load_integrity_report(request)
        if report is None:
            report = inferred_integrity_report(request, candles, integrity_policy=integrity_policy)
        if integrity_policy is HistoricalIntegrityPolicy.STRICT and not report.complete:
            raise ValueError(f"Strict historical load rejected incomplete cache at {path}")
        return HistoricalCandleLoadResult(candles=candles, integrity_report=report)

    def load_integrity_report(self, request: HistoricalCandleRequest) -> HistoricalIntegrityReport | None:
        path = self.integrity_path_for(request)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Historical integrity metadata must be a JSON object")
        report = integrity_report_from_payload(cast(dict[str, object], payload))
        self._validate_report_identity(request, report)
        return report

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

    def _normalized_candles(self, candles: Iterable[Candle]) -> tuple[Candle, ...]:
        candle_by_open_time = {candle.open_time_ms: candle for candle in candles}
        return tuple(candle_by_open_time[open_time] for open_time in sorted(candle_by_open_time))

    def _validate_report_identity(self, request: HistoricalCandleRequest, report: HistoricalIntegrityReport) -> None:
        if (
            report.exchange.value != request.exchange
            or report.market_type.value != request.market_type
            or report.symbol != request.symbol
            or report.timeframe is not request.timeframe
            or report.start_time_ms != request.start_time_ms
            or report.end_time_ms != request.end_time_ms
        ):
            raise ValueError("Historical integrity metadata does not match requested cache identity")


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
        return self.load_result(request, integrity_policy=HistoricalIntegrityPolicy.STRICT).candles

    def load_result(
        self,
        request: HistoricalCandleRequest,
        *,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> HistoricalCandleLoadResult:
        exchange_request = ExchangeHistoricalCandleRequest(
            exchange=ExchangeName(request.exchange),
            market_type=MarketType(request.market_type),
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_time_ms=request.start_time_ms,
            end_time_ms=request.end_time_ms,
            limit=self._limit,
            integrity_policy=integrity_policy,
        )
        result = self._adapter.fetch_historical_candles(exchange_request)
        if not result.candles:
            exchange_symbol = self._adapter.exchange_symbol_for(request.symbol)
            raise RuntimeError(
                "BitMart historical download returned zero candles "
                "endpoint=/contract/public/kline "
                f"symbol={exchange_symbol} "
                f"start_time={request.start_time_ms // 1000} "
                f"end_time={request.end_time_ms // 1000} "
                f"pages={result.pages} "
                f"latest_completed_time_ms={result.latest_completed_time_ms}",
            )
        integrity_report = result.integrity_report or HistoricalIntegrityReport.valid(
            exchange_request,
            requested_candle_count=expected_candle_count(request),
            loaded_candle_count=len(result.candles),
        )
        return HistoricalCandleLoadResult(candles=result.candles, integrity_report=integrity_report)


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
        open=read_float(first_present(row, "open", "open_price", "o"), "open"),
        high=read_float(first_present(row, "high", "high_price", "h"), "high"),
        low=read_float(first_present(row, "low", "low_price", "l"), "low"),
        close=read_float(first_present(row, "close", "close_price", "c"), "close"),
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


def expected_candle_count(request: HistoricalCandleRequest) -> int:
    return max(0, (request.end_time_ms - request.start_time_ms) // timeframe_duration_ms(request.timeframe))


def exchange_request_from_historical_request(
    request: HistoricalCandleRequest,
    *,
    integrity_policy: HistoricalIntegrityPolicy,
) -> ExchangeHistoricalCandleRequest:
    return ExchangeHistoricalCandleRequest(
        exchange=ExchangeName(request.exchange),
        market_type=MarketType(request.market_type),
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_time_ms=request.start_time_ms,
        end_time_ms=request.end_time_ms,
        integrity_policy=integrity_policy,
    )


def inferred_integrity_report(
    request: HistoricalCandleRequest,
    candles: tuple[Candle, ...],
    *,
    integrity_policy: HistoricalIntegrityPolicy,
) -> HistoricalIntegrityReport:
    expected_count = expected_candle_count(request)
    complete = len(candles) == expected_count
    exchange_request = exchange_request_from_historical_request(
        request,
        integrity_policy=integrity_policy,
    )
    if complete:
        return HistoricalIntegrityReport.valid(
            exchange_request,
            requested_candle_count=expected_count,
            loaded_candle_count=len(candles),
        )
    return HistoricalIntegrityReport.from_gaps(
        exchange_request,
        status=HistoricalIntegrityStatus.FAILED if integrity_policy is HistoricalIntegrityPolicy.STRICT else HistoricalIntegrityStatus.INCOMPLETE,
        gaps=(),
        requested_candle_count=expected_count,
        loaded_candle_count=len(candles),
    )


def integrity_report_to_payload(report: HistoricalIntegrityReport) -> dict[str, object]:
    return {
        "policy": report.policy.value,
        "status": report.status.value,
        "gap_count": report.gap_count,
        "total_missing_candles": report.total_missing_candles,
        "gaps": [
            {
                "symbol": gap.symbol,
                "timeframe": gap.timeframe.value,
                "start_open_time_ms": gap.start_open_time_ms,
                "end_open_time_ms": gap.end_open_time_ms,
                "missing_candle_count": gap.missing_candle_count,
                "missing_open_times_ms": list(gap.missing_open_times_ms),
                "retry_count": gap.retry_count,
                "exchange": gap.exchange.value,
                "recovery_status": gap.recovery_status.value,
                "detected_at_ms": gap.detected_at_ms,
            }
            for gap in report.gaps
        ],
        "requested_candle_count": report.requested_candle_count,
        "loaded_candle_count": report.loaded_candle_count,
        "complete": report.complete,
        "exchange": report.exchange.value,
        "market_type": report.market_type.value,
        "symbol": report.symbol,
        "timeframe": report.timeframe.value,
        "start_time_ms": report.start_time_ms,
        "end_time_ms": report.end_time_ms,
    }


def integrity_report_from_payload(payload: dict[str, object]) -> HistoricalIntegrityReport:
    gaps_payload = payload.get("gaps", ())
    if not isinstance(gaps_payload, list):
        raise ValueError("Historical integrity gaps must be a list")
    gaps = tuple(
        HistoricalDataGap(
            symbol=read_str(gap.get("symbol"), "gap.symbol"),
            timeframe=Timeframe(read_str(gap.get("timeframe"), "gap.timeframe")),
            start_open_time_ms=read_int(gap.get("start_open_time_ms"), "gap.start_open_time_ms"),
            end_open_time_ms=read_int(gap.get("end_open_time_ms"), "gap.end_open_time_ms"),
            missing_candle_count=read_int(gap.get("missing_candle_count"), "gap.missing_candle_count"),
            missing_open_times_ms=tuple(
                read_int(item, "gap.missing_open_times_ms")
                for item in cast(list[object], gap.get("missing_open_times_ms", []))
            ),
            retry_count=read_int(gap.get("retry_count"), "gap.retry_count"),
            exchange=ExchangeName(read_str(gap.get("exchange"), "gap.exchange")),
            recovery_status=HistoricalGapRecoveryStatus(read_str(gap.get("recovery_status"), "gap.recovery_status")),
            detected_at_ms=read_int(gap.get("detected_at_ms"), "gap.detected_at_ms"),
        )
        for gap in gaps_payload
        if isinstance(gap, dict)
    )
    return HistoricalIntegrityReport(
        policy=HistoricalIntegrityPolicy(read_str(payload.get("policy"), "policy")),
        status=HistoricalIntegrityStatus(read_str(payload.get("status"), "status")),
        gap_count=read_int(payload.get("gap_count"), "gap_count"),
        total_missing_candles=read_int(payload.get("total_missing_candles"), "total_missing_candles"),
        gaps=gaps,
        requested_candle_count=read_int(payload.get("requested_candle_count"), "requested_candle_count"),
        loaded_candle_count=read_int(payload.get("loaded_candle_count"), "loaded_candle_count"),
        complete=read_bool(payload.get("complete"), "complete"),
        exchange=ExchangeName(read_str(payload.get("exchange"), "exchange")),
        market_type=MarketType(read_str(payload.get("market_type"), "market_type")),
        symbol=read_str(payload.get("symbol"), "symbol"),
        timeframe=Timeframe(read_str(payload.get("timeframe"), "timeframe")),
        start_time_ms=read_int(payload.get("start_time_ms"), "start_time_ms"),
        end_time_ms=read_int(payload.get("end_time_ms"), "end_time_ms"),
    )


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


def read_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be a boolean")


def read_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)


def first_present(payload: dict[str, object], *keys: str) -> object:
    for key in keys:
        if key in payload:
            return payload[key]
    return None
