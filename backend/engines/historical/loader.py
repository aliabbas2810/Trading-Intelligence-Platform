from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

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
UTC_DAY_MS = 24 * 60 * 60 * 1000
LOGGER = logging.getLogger(__name__)


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
    pages: int = 0


class HistoricalCandleFileStore:
    """Local JSONL storage for M27 historical candle fixtures/downloads."""

    def __init__(self, root: Path = DEFAULT_HISTORICAL_DATA_ROOT) -> None:
        self._root = root

    def path_for(self, request: HistoricalCandleRequest) -> Path:
        filename = f"{request.start_time_ms}_{request.end_time_ms}.jsonl"
        return self._root / request.exchange / request.market_type / request.symbol / request.timeframe.value / filename

    def discover_compatible_requests(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: Timeframe,
    ) -> tuple[HistoricalCandleRequest, ...]:
        """Discover local compatible BitMart cache segments for SYNC-001/SYNC-006."""

        directory = self._root / exchange / market_type / symbol / timeframe.value
        if not directory.exists():
            return ()
        requests: list[HistoricalCandleRequest] = []
        for path in directory.glob("*.jsonl"):
            match = re.fullmatch(r"(\d+)_(\d+)\.jsonl", path.name)
            if match is None:
                continue
            requests.append(
                HistoricalCandleRequest(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time_ms=int(match.group(1)),
                    end_time_ms=int(match.group(2)),
                    exchange=exchange,
                    market_type=market_type,
                )
            )
        return tuple(sorted(requests, key=lambda item: (item.start_time_ms, item.end_time_ms)))

    def load_compatible_segments(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: Timeframe,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> tuple[HistoricalCandleLoadResult, ...]:
        return tuple(
            self.load_result(request, integrity_policy=integrity_policy)
            for request in self.discover_compatible_requests(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                timeframe=timeframe,
            )
        )

    def merged_result(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: Timeframe,
        integrity_policy: HistoricalIntegrityPolicy,
    ) -> HistoricalCandleLoadResult | None:
        segments = self.load_compatible_segments(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
            integrity_policy=integrity_policy,
        )
        if not segments:
            return None
        candles = self._normalized_candles(candle for segment in segments for candle in segment.candles)
        if not candles:
            return None
        request = HistoricalCandleRequest(
            symbol=symbol,
            timeframe=timeframe,
            start_time_ms=candles[0].open_time_ms,
            end_time_ms=candles[-1].open_time_ms + timeframe_duration_ms(timeframe),
            exchange=exchange,
            market_type=market_type,
        )
        report = inferred_integrity_report(request, candles, integrity_policy=integrity_policy)
        return HistoricalCandleLoadResult(candles=candles, integrity_report=report)

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

    def save_candle_segment(
        self,
        candle: Candle,
        *,
        exchange: str,
        market_type: str,
    ) -> Path:
        """Persist one finalized live candle into an atomic UTC-day segment."""

        return self.save_daily_segments(
            (candle,),
            exchange=exchange,
            market_type=market_type,
        )[0]

    def save_daily_segments(
        self,
        candles: Iterable[Candle],
        *,
        exchange: str,
        market_type: str,
    ) -> tuple[Path, ...]:
        """Persist candles into deterministic UTC-day JSONL segments for live/cache catch-up."""

        grouped: dict[tuple[str, Timeframe, int], list[Candle]] = {}
        incoming_count = 0
        for candle in candles:
            incoming_count += 1
            day_start_ms = floor_to_utc_day_ms(candle.open_time_ms)
            grouped.setdefault((candle.symbol, candle.timeframe, day_start_ms), []).append(candle)

        paths: list[Path] = []
        for (symbol, timeframe, day_start_ms), segment_candles in sorted(grouped.items()):
            request = HistoricalCandleRequest(
                symbol=symbol,
                timeframe=timeframe,
                start_time_ms=day_start_ms,
                end_time_ms=day_start_ms + UTC_DAY_MS,
                exchange=exchange,
                market_type=market_type,
            )
            existing: tuple[Candle, ...] = ()
            if self.path_for(request).exists():
                existing = self.load_result(request, integrity_policy=HistoricalIntegrityPolicy.WARN).candles
            self._validate_no_conflicting_candles(existing, segment_candles)
            merged = self._normalized_candles((*existing, *segment_candles))
            report = inferred_integrity_report(request, merged, integrity_policy=HistoricalIntegrityPolicy.WARN)
            paths.append(self.save_result(request, HistoricalCandleLoadResult(candles=merged, integrity_report=report)))
        LOGGER.info(
            "Historical daily persistence completed incoming_candle_count=%s changed_utc_day_count=%s "
            "written_day_count=%s unchanged_day_count=%s",
            incoming_count,
            len(grouped),
            len(paths),
            0,
        )
        return tuple(paths)

    def save_range_segment(
        self,
        candles: Iterable[Candle],
        *,
        exchange: str,
        market_type: str,
    ) -> Path:
        sorted_candles = self._normalized_candles(candles)
        if not sorted_candles:
            raise ValueError("Cannot persist an empty historical range segment")
        duration_ms = timeframe_duration_ms(sorted_candles[0].timeframe)
        request = HistoricalCandleRequest(
            symbol=sorted_candles[0].symbol,
            timeframe=sorted_candles[0].timeframe,
            start_time_ms=sorted_candles[0].open_time_ms,
            end_time_ms=sorted_candles[-1].open_time_ms + duration_ms,
            exchange=exchange,
            market_type=market_type,
        )
        report = inferred_integrity_report(request, sorted_candles, integrity_policy=HistoricalIntegrityPolicy.WARN)
        return self.save_result(request, HistoricalCandleLoadResult(candles=sorted_candles, integrity_report=report))

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
        with temporary_integrity_path.open("w", encoding="utf-8") as file:
            file.write(json.dumps(integrity_report_to_payload(result.integrity_report), indent=2, sort_keys=True))
            file.flush()
            os.fsync(file.fileno())
        with temporary_data_path.open("w", encoding="utf-8") as file:
            for candle in sorted_candles:
                payload = asdict(candle)
                payload["timeframe"] = candle.timeframe.value
                file.write(json.dumps(payload, sort_keys=True))
                file.write("\n")
            file.flush()
            os.fsync(file.fileno())
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

    def cleanup_temporary_files(self) -> tuple[Path, ...]:
        """Remove incomplete atomic-write temp files left by interrupted cache writes."""

        if not self._root.exists():
            return ()
        removed: list[Path] = []
        for path in self._root.rglob("*.tmp"):
            path.unlink()
            removed.append(path)
        return tuple(sorted(removed))

    def _normalized_candles(self, candles: Iterable[Candle]) -> tuple[Candle, ...]:
        candle_by_open_time: dict[int, Candle] = {}
        for candle in candles:
            existing = candle_by_open_time.get(candle.open_time_ms)
            if existing is None or (existing.source_kind == "synthetic_no_trade" and candle.source_kind == "exchange"):
                candle_by_open_time[candle.open_time_ms] = candle
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

    def _validate_no_conflicting_candles(
        self,
        existing: tuple[Candle, ...],
        incoming: Iterable[Candle],
    ) -> None:
        existing_by_open_time = {candle.open_time_ms: candle for candle in existing}
        for candle in incoming:
            existing_candle = existing_by_open_time.get(candle.open_time_ms)
            if existing_candle is None or existing_candle == candle:
                continue
            if existing_candle.source_kind == "synthetic_no_trade" and candle.source_kind == "exchange":
                continue
            if existing_candle.source_kind == "exchange" and candle.source_kind == "synthetic_no_trade":
                continue
            raise ValueError(
                "Historical candle cache conflict "
                f"symbol={candle.symbol} timeframe={candle.timeframe.value} "
                f"open_time_ms={candle.open_time_ms}",
            )


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

    def latest_completed_open_time_ms(self, symbol: str) -> int:
        """Return latest fully closed BitMart 1m candle open time for SYNC-003."""

        return self._adapter.fetch_latest_completed_candle_time(symbol)

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
        if not result.candles and (
            integrity_policy is HistoricalIntegrityPolicy.STRICT
            or result.integrity_report is None
            or result.integrity_report.complete
        ):
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
        return HistoricalCandleLoadResult(candles=result.candles, integrity_report=integrity_report, pages=result.pages)


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
    source_kind = read_str(payload.get("source_kind", "exchange"), "source_kind")
    if source_kind not in {"exchange", "synthetic_no_trade"}:
        raise ValueError("source_kind must be exchange or synthetic_no_trade")
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
        source_kind=cast(Literal["exchange", "synthetic_no_trade"], source_kind),
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


def floor_to_utc_day_ms(timestamp_ms: int) -> int:
    return timestamp_ms - (timestamp_ms % UTC_DAY_MS)


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
    gaps = detect_historical_gaps(request, candles)
    return HistoricalIntegrityReport.from_gaps(
        exchange_request,
        status=historical_status_for_policy(integrity_policy),
        gaps=gaps,
        requested_candle_count=expected_count,
        loaded_candle_count=len(candles),
    )


def detect_historical_gaps(
    request: HistoricalCandleRequest,
    candles: tuple[Candle, ...],
) -> tuple[HistoricalDataGap, ...]:
    """Return exact missing candle runs in [start_time, end_time)."""

    duration_ms = timeframe_duration_ms(request.timeframe)
    present = {candle.open_time_ms for candle in candles}
    gaps: list[HistoricalDataGap] = []
    current_gap: list[int] = []
    for open_time_ms in range(request.start_time_ms, request.end_time_ms, duration_ms):
        if open_time_ms not in present:
            current_gap.append(open_time_ms)
            continue
        if current_gap:
            gaps.append(historical_gap_from_missing_times(request, tuple(current_gap)))
            current_gap = []
    if current_gap:
        gaps.append(historical_gap_from_missing_times(request, tuple(current_gap)))
    return tuple(gaps)


def historical_gap_from_missing_times(
    request: HistoricalCandleRequest,
    missing_open_times_ms: tuple[int, ...],
) -> HistoricalDataGap:
    duration_ms = timeframe_duration_ms(request.timeframe)
    return HistoricalDataGap(
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_open_time_ms=missing_open_times_ms[0],
        end_open_time_ms=missing_open_times_ms[-1] + duration_ms,
        missing_candle_count=len(missing_open_times_ms),
        missing_open_times_ms=missing_open_times_ms,
        retry_count=0,
        exchange=ExchangeName(request.exchange),
        recovery_status=HistoricalGapRecoveryStatus.UNRECOVERABLE,
        detected_at_ms=int(datetime.now(tz=UTC).timestamp() * 1000),
    )


def historical_status_for_policy(policy: HistoricalIntegrityPolicy) -> HistoricalIntegrityStatus:
    if policy is HistoricalIntegrityPolicy.STRICT:
        return HistoricalIntegrityStatus.FAILED
    if policy is HistoricalIntegrityPolicy.WARN:
        return HistoricalIntegrityStatus.DEGRADED
    return HistoricalIntegrityStatus.INCOMPLETE


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
        "exchange_candle_count": report.exchange_candle_count,
        "synthetic_candle_count": report.synthetic_candle_count,
        "canonical_candle_count": report.canonical_candle_count,
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
        exchange_candle_count=read_int(payload.get("exchange_candle_count", payload.get("loaded_candle_count")), "exchange_candle_count"),
        synthetic_candle_count=read_int(payload.get("synthetic_candle_count", 0), "synthetic_candle_count"),
        canonical_candle_count=read_int(payload.get("canonical_candle_count", payload.get("loaded_candle_count")), "canonical_candle_count"),
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
