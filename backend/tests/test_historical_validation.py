from __future__ import annotations

from pathlib import Path

import pytest

from backend.engines.historical import (
    BitMartHistoricalCandleDownloader,
    HistoricalCandleFileStore,
    HistoricalCandleRequest,
)
from backend.engines.historical.loader import candle_from_bitmart_kline
from backend.exchange import (
    BitMartFuturesMarketDataAdapter,
    ExchangeHistoricalCandleRequest,
    HistoricalCandleResult,
    HistoricalDataGap,
    HistoricalGapRecoveryStatus,
    HistoricalIntegrityPolicy,
    HistoricalIntegrityReport,
    HistoricalIntegrityStatus,
    ExchangeName,
    MarketType,
)
from backend.engines.historical.validation import HistoricalValidationRunner
from backend.engines.historical.loader import HistoricalCandleLoadResult
from backend.models import Candle, Timeframe
from scripts.validate_historical import main


def test_historical_file_store_round_trips_candles(tmp_path: Path) -> None:
    """Covers M27 local historical candle storage and TEST-001."""

    request = make_request()
    store = HistoricalCandleFileStore(tmp_path)
    candles = make_fixture_candles(count=4)

    path = store.save(request, candles)
    loaded = store.load(request)

    assert path == tmp_path / "bitmart" / "usdt_m_perpetual" / "BTCUSDT" / "1m" / "0_240000.jsonl"
    assert loaded == candles


def test_historical_file_store_sorts_deduplicates_and_rejects_empty_cache(tmp_path: Path) -> None:
    request = make_request()
    store = HistoricalCandleFileStore(tmp_path)
    candles = make_fixture_candles(count=4)

    path = store.save(request, (candles[2], candles[0], candles[2], candles[1]))
    loaded = store.load(request)

    assert loaded == (candles[0], candles[1], candles[2])
    assert path.read_text(encoding="utf-8").count("\n") == 3

    empty_request = HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=10_000,
        end_time_ms=20_000,
    )
    empty_path = store.path_for(empty_request)
    with pytest.raises(ValueError, match="Refusing to create empty"):
        store.save(empty_request, ())
    assert not empty_path.exists()


def test_historical_file_store_writes_and_restores_integrity_metadata(tmp_path: Path) -> None:
    request = make_request()
    store = HistoricalCandleFileStore(tmp_path)
    candles = make_fixture_candles(count=3)
    report = incomplete_report(request, loaded_candle_count=3)

    data_path = store.save_result(
        request,
        HistoricalCandleLoadResult(candles=candles, integrity_report=report),
    )
    loaded = store.load_result(request, integrity_policy=HistoricalIntegrityPolicy.WARN)

    assert data_path.exists()
    assert store.integrity_path_for(request).exists()
    assert loaded.candles == candles
    assert loaded.integrity_report == report


def test_historical_file_store_strict_rejects_incomplete_cache(tmp_path: Path) -> None:
    request = make_request()
    store = HistoricalCandleFileStore(tmp_path)
    store.save_result(
        request,
        HistoricalCandleLoadResult(
            candles=make_fixture_candles(count=3),
            integrity_report=incomplete_report(request, loaded_candle_count=3),
        ),
    )

    with pytest.raises(ValueError, match="Strict historical load rejected incomplete cache"):
        store.load_result(request, integrity_policy=HistoricalIntegrityPolicy.STRICT)


def test_historical_file_store_complete_cache_has_valid_integrity_metadata(tmp_path: Path) -> None:
    request = make_request()
    store = HistoricalCandleFileStore(tmp_path)
    store.save(request, make_fixture_candles(count=4))

    loaded = store.load_result(request, integrity_policy=HistoricalIntegrityPolicy.STRICT)

    assert loaded.integrity_report.complete is True
    assert loaded.integrity_report.status is HistoricalIntegrityStatus.VALID
    assert loaded.integrity_report.requested_candle_count == 4
    assert loaded.integrity_report.loaded_candle_count == 4


def test_historical_file_store_persists_live_candles_into_daily_segments(tmp_path: Path) -> None:
    store = HistoricalCandleFileStore(tmp_path)
    candles = make_fixture_candles(count=3)

    paths = store.save_daily_segments(
        (candles[0], candles[1]),
        exchange=ExchangeName.BITMART.value,
        market_type=MarketType.USDT_M_PERPETUAL.value,
    )
    second_paths = store.save_daily_segments(
        (candles[1], candles[2]),
        exchange=ExchangeName.BITMART.value,
        market_type=MarketType.USDT_M_PERPETUAL.value,
    )
    result = store.merged_result(
        exchange=ExchangeName.BITMART.value,
        market_type=MarketType.USDT_M_PERPETUAL.value,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        integrity_policy=HistoricalIntegrityPolicy.WARN,
    )

    assert paths == (tmp_path / "bitmart" / "usdt_m_perpetual" / "BTCUSDT" / "1m" / "0_86400000.jsonl",)
    assert second_paths == paths
    assert result is not None
    assert result.candles == candles


def test_historical_file_store_rejects_conflicting_daily_candle(tmp_path: Path) -> None:
    """M31.6 reports segment conflicts instead of silently overwriting candles."""

    store = HistoricalCandleFileStore(tmp_path)
    candle = make_fixture_candles(count=1)[0]
    conflicting = Candle(
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        open_time_ms=candle.open_time_ms,
        close_time_ms=candle.close_time_ms,
        open=candle.open,
        high=candle.high + 10.0,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
    )
    store.save_daily_segments(
        (candle,),
        exchange=ExchangeName.BITMART.value,
        market_type=MarketType.USDT_M_PERPETUAL.value,
    )

    with pytest.raises(ValueError, match="cache conflict"):
        store.save_daily_segments(
            (conflicting,),
            exchange=ExchangeName.BITMART.value,
            market_type=MarketType.USDT_M_PERPETUAL.value,
        )


def test_historical_file_store_cleans_leftover_temp_files(tmp_path: Path) -> None:
    """M31.6 allows interrupted atomic writes to be recovered on restart."""

    temp_file = tmp_path / "bitmart" / "usdt_m_perpetual" / "BTCUSDT" / "1m" / "0_60000.jsonl.tmp"
    temp_file.parent.mkdir(parents=True)
    temp_file.write_text("partial", encoding="utf-8")

    removed = HistoricalCandleFileStore(tmp_path).cleanup_temporary_files()

    assert removed == (temp_file,)
    assert not temp_file.exists()


def test_bitmart_kline_row_normalizes_to_canonical_candle() -> None:
    """Covers M27/M31.1 BitMart candle normalization without network access."""

    candle = candle_from_bitmart_kline(
        {
            "timestamp": 0,
            "open": "100.0",
            "high": "105.0",
            "low": "99.0",
            "close": "104.0",
            "volume": "12.5",
        },
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        duration_ms=60_000,
    )

    assert candle == Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=0,
        close_time_ms=60_000,
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.0,
        volume=12.5,
    )


def test_bitmart_kline_row_accepts_real_price_field_names() -> None:
    candle = candle_from_bitmart_kline(
        {
            "timestamp": 0,
            "open_price": "100.0",
            "high_price": "105.0",
            "low_price": "99.0",
            "close_price": "104.0",
            "volume": "12.5",
        },
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        duration_ms=60_000,
    )

    assert candle.open == 100.0
    assert candle.high == 105.0
    assert candle.low == 99.0
    assert candle.close == 104.0


def test_bitmart_downloader_rejects_zero_candle_download() -> None:
    downloader = BitMartHistoricalCandleDownloader(adapter=EmptyBitMartAdapter())

    with pytest.raises(RuntimeError) as exc_info:
        downloader.load(make_request())

    message = str(exc_info.value)
    assert "zero candles" in message
    assert "/contract/public/kline" in message
    assert "symbol=BTCUSDT" in message
    assert "start_time=0" in message
    assert "end_time=240" in message


def test_historical_validation_runner_feeds_existing_runtime_paths() -> None:
    """M27 validation runner reuses candle events, structure, trend, and intelligence boundaries."""

    candles = make_fixture_candles(count=30)

    summary = HistoricalValidationRunner().run(
        candles,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
    )

    assert summary.symbol == "BTCUSDT"
    assert summary.timeframe is Timeframe.ONE_MINUTE
    assert summary.candle_count == 30
    # M31.7 restores structure ownership to 1W/1D/4H only; a short 1m
    # fixture exercises the pipeline without fabricating lower-timeframe swings.
    assert summary.structure_count == 0
    assert summary.bos_count >= 0
    assert summary.entry_state.value in {
        "WAIT",
        "WATCH",
        "LONG_SETUP",
        "SHORT_SETUP",
        "ENTRY_READY",
        "INVALIDATED",
    }
    assert summary.risk_state.value in {"NOT_APPLICABLE", "VALID", "INVALID", "INCOMPLETE"}
    assert summary.checklist_status.value in {"PASS", "FAIL", "MISSING", "WARNING", "NOT_APPLICABLE"}
    assert 0.0 <= summary.setup_score <= 100.0


def test_validate_historical_script_loads_local_fixture(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Covers the M27 script with deterministic local data and no live network calls."""

    request = make_request()
    HistoricalCandleFileStore(tmp_path).save(request, make_fixture_candles(count=4))

    exit_code = main(
        [
            "--symbol",
            "BTCUSDT",
            "--timeframe",
            "1m",
            "--start",
            "1970-01-01T00:00:00Z",
            "--end",
            "1970-01-01T00:04:00Z",
            "--data-root",
            str(tmp_path),
        ],
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "candle_count=4" in captured.out
    assert "entry_state=" in captured.out
    assert "risk_state=" in captured.out
    assert "checklist_status=" in captured.out
    assert "setup_score=" in captured.out


def make_request() -> HistoricalCandleRequest:
    return HistoricalCandleRequest(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=240_000,
    )


def make_fixture_candles(*, count: int) -> tuple[Candle, ...]:
    candles: list[Candle] = []
    close = 100.0
    for index in range(count):
        open_price = close
        direction = 1 if index % 2 == 0 else -1
        close = open_price + direction * (3.0 + index % 3)
        high = max(open_price, close) + 1.0
        low = min(open_price, close) - 1.0
        open_time_ms = index * 60_000
        candles.append(
            Candle(
                symbol="BTCUSDT",
                timeframe=Timeframe.ONE_MINUTE,
                open_time_ms=open_time_ms,
                close_time_ms=open_time_ms + 60_000,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1.0 + index,
            ),
        )
    return tuple(candles)


def incomplete_report(request: HistoricalCandleRequest, *, loaded_candle_count: int) -> HistoricalIntegrityReport:
    gap = HistoricalDataGap(
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_open_time_ms=180_000,
        end_open_time_ms=240_000,
        missing_candle_count=1,
        missing_open_times_ms=(180_000,),
        retry_count=3,
        exchange=ExchangeName.BITMART,
        recovery_status=HistoricalGapRecoveryStatus.UNRECOVERABLE,
        detected_at_ms=300_000,
    )
    return HistoricalIntegrityReport.from_gaps(
        ExchangeHistoricalCandleRequest(
            exchange=ExchangeName.BITMART,
            market_type=MarketType.USDT_M_PERPETUAL,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_time_ms=request.start_time_ms,
            end_time_ms=request.end_time_ms,
            integrity_policy=HistoricalIntegrityPolicy.WARN,
        ),
        status=HistoricalIntegrityStatus.DEGRADED,
        gaps=(gap,),
        requested_candle_count=4,
        loaded_candle_count=loaded_candle_count,
    )


class EmptyBitMartAdapter(BitMartFuturesMarketDataAdapter):
    def fetch_historical_candles(self, request: ExchangeHistoricalCandleRequest) -> HistoricalCandleResult:
        return HistoricalCandleResult(
            request=request,
            candles=(),
            pages=1,
            latest_completed_time_ms=0,
        )

    def exchange_symbol_for(self, canonical_symbol: str) -> str:
        return canonical_symbol
