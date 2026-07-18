from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.service import create_app
from backend.app import BackendRuntime, RuntimeMode
from backend.config import load_settings
from backend.exchange import (
    BitMartFuturesMarketDataAdapter,
    CandlePage,
    ContractMetadata,
    ContractStatus,
    ExchangeHistoricalCandleRequest,
    ExchangeName,
    HistoricalCandleResult,
    MarketType,
    RateLimitMetadata,
    RetryPolicy,
)
from backend.models import Candle, Timeframe
from backend.storage import InMemoryCandleHistoryStore, JsonlCandleHistoryStore
from backend.sync import (
    IncrementalSyncPlanner,
    MarketDataSyncCoordinator,
    SQLiteSyncMetadataStore,
    SyncState,
    SymbolSyncStatus,
)


NOW_MS = 10 * 60_000


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str | int]]] = []
        self.failures = 0

    def get_json(self, path: str, params: dict[str, str | int]) -> object:
        self.calls.append((path, params))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("transient")
        if path.endswith("/details"):
            return {
                "data": {
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "base_currency": "BTC",
                            "quote_currency": "USDT",
                            "contract_type": "perpetual",
                            "status": "trading",
                            "price_tick": "0.1",
                            "quantity_step": "0.001",
                            "open_timestamp": 0,
                        },
                        {
                            "symbol": "ETHUSDC",
                            "contract_type": "perpetual",
                            "status": "trading",
                        },
                        {
                            "symbol": "OLDUSDT",
                            "contract_type": "perpetual",
                            "status": "paused",
                        },
                    ],
                },
            }
        start = int(params["start_time"])
        end = int(params["end_time"])
        limit = int(params["limit"])
        step_seconds = int(params["step"]) * 60
        rows = [
            {
                "timestamp": timestamp,
                "open": "100",
                "high": "110",
                "low": "90",
                "close": "105",
                "volume": "1",
            }
            for timestamp in range(start, end, step_seconds)
        ][:limit]
        return {"data": {"klines": rows}}


class EmptyKlineTransport(FakeTransport):
    def get_json(self, path: str, params: dict[str, str | int]) -> object:
        self.calls.append((path, params))
        if path.endswith("/details"):
            return super().get_json(path, params)
        return {"data": {"klines": []}}


class GapKlineTransport(FakeTransport):
    def get_json(self, path: str, params: dict[str, str | int]) -> object:
        payload = super().get_json(path, params)
        if path.endswith("/details"):
            return payload
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                rows = data.get("klines")
                if isinstance(rows, list) and len(rows) > 2:
                    del rows[1]
        return payload


class BitMartPriceFieldTransport(FakeTransport):
    def get_json(self, path: str, params: dict[str, str | int]) -> object:
        self.calls.append((path, params))
        if path.endswith("/details"):
            return super().get_json(path, params)
        return {
            "data": [
                {
                    "timestamp": int(params["start_time"]),
                    "open_price": "100",
                    "high_price": "110",
                    "low_price": "90",
                    "close_price": "105",
                    "volume": "1",
                },
            ],
        }


class BadKlineTransport(FakeTransport):
    def get_json(self, path: str, params: dict[str, str | int]) -> object:
        self.calls.append((path, params))
        if path.endswith("/details"):
            return super().get_json(path, params)
        return {"data": [{"timestamp": int(params["start_time"]), "volume": "1"}]}


def test_bitmart_discovers_only_active_usdt_perpetual_contracts() -> None:
    adapter = BitMartFuturesMarketDataAdapter(transport=FakeTransport(), clock_ms=lambda: NOW_MS)

    contracts = adapter.discover_contracts()

    assert [contract.canonical_symbol for contract in contracts] == ["BTCUSDT"]
    assert contracts[0].exchange is ExchangeName.BITMART
    assert contracts[0].market_type is MarketType.USDT_M_PERPETUAL
    assert contracts[0].is_active
    assert contracts[0].is_perpetual


def test_bitmart_historical_pagination_deduplicates_and_excludes_forming_candle() -> None:
    adapter = BitMartFuturesMarketDataAdapter(
        transport=FakeTransport(),
        page_size=2,
        clock_ms=lambda: NOW_MS,
    )
    request = ExchangeHistoricalCandleRequest(
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=NOW_MS + 60_000,
        limit=2,
    )

    result = adapter.fetch_historical_candles(request)

    assert result.latest_completed_time_ms == NOW_MS - 60_000
    assert result.candles[-1].open_time_ms == NOW_MS - 60_000
    assert len({candle.open_time_ms for candle in result.candles}) == len(result.candles)
    assert result.pages >= 2


def test_bitmart_short_historical_range_uses_one_bounded_page() -> None:
    transport = FakeTransport()
    adapter = BitMartFuturesMarketDataAdapter(
        transport=transport,
        page_size=500,
        clock_ms=lambda: 3 * 60 * 60_000,
    )
    request = historical_request(start=0, end=120 * 60_000, limit=500)

    result = adapter.fetch_historical_candles(request)

    kline_calls = kline_calls_from(transport)
    assert len(kline_calls) == 1
    assert kline_calls[0]["start_time"] == 0
    assert kline_calls[0]["end_time"] == 120 * 60
    assert len(result.candles) == 120
    assert len({candle.open_time_ms for candle in result.candles}) == 120


def test_bitmart_long_historical_range_windows_by_limit_without_gaps() -> None:
    transport = FakeTransport()
    expected_count = 44_640
    adapter = BitMartFuturesMarketDataAdapter(
        transport=transport,
        page_size=500,
        clock_ms=lambda: (expected_count + 1) * 60_000,
    )
    request = historical_request(start=0, end=expected_count * 60_000, limit=500)

    result = adapter.fetch_historical_candles(request)

    kline_calls = kline_calls_from(transport)
    assert len(kline_calls) == 90
    assert result.pages == 90
    assert len(result.candles) == expected_count
    assert result.candles[0].open_time_ms == 0
    assert result.candles[-1].open_time_ms == (expected_count - 1) * 60_000
    assert [call["start_time"] for call in kline_calls[:3]] == [0, 30_000, 60_000]
    assert kline_calls[-1]["end_time"] == expected_count * 60
    assert len({candle.open_time_ms for candle in result.candles}) == expected_count


def test_bitmart_final_partial_page_continues_to_requested_end() -> None:
    transport = FakeTransport()
    expected_count = 1_001
    adapter = BitMartFuturesMarketDataAdapter(
        transport=transport,
        page_size=500,
        clock_ms=lambda: (expected_count + 1) * 60_000,
    )
    request = historical_request(start=0, end=expected_count * 60_000, limit=500)

    result = adapter.fetch_historical_candles(request)

    kline_calls = kline_calls_from(transport)
    assert len(kline_calls) == 3
    assert len(result.candles) == expected_count
    assert kline_calls[-1]["start_time"] == 60_000
    assert kline_calls[-1]["end_time"] == 60_060


def test_bitmart_pagination_is_timeframe_aware_for_five_minute_candles() -> None:
    transport = FakeTransport()
    adapter = BitMartFuturesMarketDataAdapter(
        transport=transport,
        page_size=2,
        clock_ms=lambda: 30 * 60_000,
    )
    request = historical_request(start=0, end=25 * 60_000, timeframe=Timeframe.FIVE_MINUTE, limit=2)

    result = adapter.fetch_historical_candles(request)

    kline_calls = kline_calls_from(transport)
    assert [call["step"] for call in kline_calls] == [5, 5, 5]
    assert [call["start_time"] for call in kline_calls] == [0, 600, 1_200]
    assert len(result.candles) == 5
    assert result.candles[-1].open_time_ms == 20 * 60_000


def test_bitmart_pagination_rejects_non_contiguous_page_data() -> None:
    adapter = BitMartFuturesMarketDataAdapter(
        transport=GapKlineTransport(),
        page_size=500,
        clock_ms=lambda: 10 * 60_000,
    )
    request = historical_request(start=0, end=5 * 60_000, limit=500)

    with pytest.raises(RuntimeError, match="not contiguous"):
        adapter.fetch_historical_candles(request)


def test_bitmart_empty_historical_page_reports_exact_window() -> None:
    adapter = BitMartFuturesMarketDataAdapter(
        transport=EmptyKlineTransport(),
        page_size=500,
        clock_ms=lambda: 10 * 60_000,
    )
    request = historical_request(start=0, end=5 * 60_000, limit=500)

    with pytest.raises(RuntimeError) as exc_info:
        adapter.fetch_historical_candles(request)

    message = str(exc_info.value)
    assert "zero candles" in message
    assert "page_start_time_ms=0" in message
    assert "page_end_time_ms=300000" in message


def test_bitmart_pagination_rejects_non_advancing_cursor() -> None:
    adapter = NonAdvancingCursorAdapter(
        transport=FakeTransport(),
        page_size=500,
        clock_ms=lambda: 10 * 60_000,
    )
    request = historical_request(start=0, end=5 * 60_000, limit=500)

    with pytest.raises(RuntimeError, match="cursor did not advance"):
        adapter.fetch_historical_candles(request)


def test_bitmart_historical_parser_accepts_real_price_field_names() -> None:
    transport = BitMartPriceFieldTransport()
    adapter = BitMartFuturesMarketDataAdapter(
        transport=transport,
        clock_ms=lambda: NOW_MS,
    )
    request = ExchangeHistoricalCandleRequest(
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=60_000,
        limit=500,
    )

    result = adapter.fetch_historical_candles(request)

    assert len(result.candles) == 1
    assert result.candles[0].open == 100.0
    assert result.candles[0].high == 110.0
    assert result.candles[0].low == 90.0
    assert result.candles[0].close == 105.0


def test_bitmart_historical_parse_failure_includes_download_diagnostics() -> None:
    adapter = BitMartFuturesMarketDataAdapter(
        transport=BadKlineTransport(),
        clock_ms=lambda: NOW_MS,
    )
    request = ExchangeHistoricalCandleRequest(
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=60_000,
        limit=500,
    )

    with pytest.raises(ValueError) as exc_info:
        adapter.fetch_historical_candles(request)

    message = str(exc_info.value)
    assert "/contract/public/kline" in message
    assert "params=" in message
    assert "http_status=200" in message
    assert "response_body=" in message
    assert "parsed_candle_count=0" in message


def test_bitmart_retry_backoff_is_deterministic() -> None:
    transport = FakeTransport()
    transport.failures = 1
    sleeps: list[float] = []
    adapter = BitMartFuturesMarketDataAdapter(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0.5),
        sleeper=sleeps.append,
        clock_ms=lambda: NOW_MS,
    )

    assert adapter.discover_contracts()
    assert sleeps == [0.5]
    assert len(transport.calls) == 2


def test_history_store_is_idempotent_and_detects_gaps() -> None:
    store = InMemoryCandleHistoryStore()
    candles = (candle(0), candle(120_000))

    assert store.upsert_many(exchange="bitmart", candles=candles) == 2
    assert store.upsert_many(exchange="bitmart", candles=candles) == 0
    assert store.first_timestamp(exchange="bitmart", symbol="BTCUSDT", timeframe=Timeframe.ONE_MINUTE) == 0
    assert store.last_timestamp(exchange="bitmart", symbol="BTCUSDT", timeframe=Timeframe.ONE_MINUTE) == 120_000
    assert store.detect_missing_intervals(
        exchange="bitmart",
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start_time_ms=0,
        end_time_ms=180_000,
    ) == ((60_000, 120_000),)


def test_jsonl_history_store_hydrates_existing_candles(tmp_path: Path) -> None:
    store = JsonlCandleHistoryStore(tmp_path)
    store.upsert_many(exchange="bitmart", candles=(candle(0), candle(60_000)))

    reloaded = JsonlCandleHistoryStore(tmp_path)

    assert reloaded.count(exchange="bitmart", symbol="BTCUSDT", timeframe=Timeframe.ONE_MINUTE) == 2
    assert reloaded.last_timestamp(exchange="bitmart", symbol="BTCUSDT", timeframe=Timeframe.ONE_MINUTE) == 60_000


def test_planner_fresh_existing_current_and_gap_repair() -> None:
    store = InMemoryCandleHistoryStore()
    planner = planner_for(store)
    metadata = contract()

    fresh = planner.plan_symbol(contract=metadata, latest_remote_completed_open_time_ms=120_000, now_ms=NOW_MS)
    assert fresh.reason.value == "initial_backfill"
    assert fresh.jobs[0].interval.end_time_ms == 180_000

    store.upsert_many(exchange="bitmart", candles=(candle(0), candle(60_000), candle(120_000)))
    current = planner.plan_symbol(contract=metadata, latest_remote_completed_open_time_ms=120_000, now_ms=NOW_MS)
    assert current.is_noop

    catch_up = planner.plan_symbol(contract=metadata, latest_remote_completed_open_time_ms=180_000, now_ms=NOW_MS)
    assert catch_up.jobs[0].interval.start_time_ms == 180_000

    gap_store = InMemoryCandleHistoryStore()
    gap_store.upsert_many(exchange="bitmart", candles=(candle(0), candle(120_000)))
    gap_plan = planner_for(gap_store).plan_symbol(
        contract=metadata,
        latest_remote_completed_open_time_ms=120_000,
        now_ms=NOW_MS,
        explicit_gap_repair=True,
    )
    assert gap_plan.jobs[0].reason.value == "gap_repair"


def test_sqlite_metadata_persists_checkpoint(tmp_path: Path) -> None:
    store = SQLiteSyncMetadataStore(tmp_path / "sync.sqlite3")
    status = sync_status()

    store.update_status(status)

    loaded = store.get_status(ExchangeName.BITMART, "BTCUSDT")
    assert loaded is not None
    assert loaded.state is SyncState.READY
    assert SQLiteSyncMetadataStore(tmp_path / "sync.sqlite3").get_status(ExchangeName.BITMART, "BTCUSDT") is not None


def test_coordinator_syncs_symbols_and_isolates_failures(tmp_path: Path) -> None:
    adapter = FakeAdapter(fail_symbol="FAILUSDT")
    history = InMemoryCandleHistoryStore()
    metadata = SQLiteSyncMetadataStore(tmp_path / "sync.sqlite3")
    coordinator = MarketDataSyncCoordinator(
        adapter=adapter,
        history_store=history,
        metadata_store=metadata,
        planner=planner_for(history),
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        max_concurrent_jobs=1,
        clock_ms=lambda: NOW_MS,
    )

    status = coordinator.run_once()

    assert status.queue.ready == 1
    assert status.queue.failed == 1
    assert coordinator.symbol_status("BTCUSDT") is not None
    assert coordinator.symbol_status("FAILUSDT") is not None
    assert coordinator.ready_symbols() == ("BTCUSDT",)


def test_runtime_api_exposes_sync_status_without_demo_mix(tmp_path: Path) -> None:
    settings = load_settings().model_copy(
        update={
            "demo": load_settings().demo.model_copy(update={"enabled": True}),
            "market_data_sync": load_settings().market_data_sync.model_copy(update={"enabled": True}),
        },
    )
    history = InMemoryCandleHistoryStore()
    coordinator = MarketDataSyncCoordinator(
        adapter=FakeAdapter(),
        history_store=history,
        metadata_store=SQLiteSyncMetadataStore(tmp_path / "sync.sqlite3"),
        planner=planner_for(history),
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        clock_ms=lambda: NOW_MS,
    )
    runtime = BackendRuntime(settings=settings, mode=RuntimeMode.DRY_RUN, market_data_sync_coordinator=coordinator)

    with TestClient(create_app(runtime)) as client:
        health = client.get("/api/health")
        start = client.post("/api/market-data/sync/start")
        status = client.get("/api/market-data/sync/status")
        contracts = client.get("/api/market-data/contracts")

    assert health.status_code == 200
    assert any(component["name"] == "demo_data" for component in health.json()["components"])
    assert runtime.candle_store.list("BTCUSDT", Timeframe.ONE_MINUTE) == ()
    assert start.status_code == 200
    assert status.json()["queue"]["ready"] >= 1
    assert contracts.json()["total"] >= 1


def test_sync_architecture_does_not_call_analysis_engines() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path("backend/sync/coordinator.py"),
            Path("backend/sync/planner.py"),
            Path("backend/exchange/bitmart.py"),
        )
    )
    forbidden = (
        "MarketStructureEngine",
        "TrendEngine",
        "AoiEngine",
        "EntrySignalEngine",
        "RiskEngine",
        "ChecklistEngine",
        "SetupScoringEngine",
        "AiDecisionEngine",
    )
    for fragment in forbidden:
        assert fragment not in source


class FakeAdapter:
    def __init__(self, *, fail_symbol: str | None = None) -> None:
        self.fail_symbol = fail_symbol

    def discover_contracts(self) -> tuple[ContractMetadata, ...]:
        contracts = [contract()]
        if self.fail_symbol is not None:
            contracts.append(contract(symbol=self.fail_symbol))
        return tuple(contracts)

    def fetch_historical_candles(self, request: ExchangeHistoricalCandleRequest) -> HistoricalCandleResult:
        if request.symbol == self.fail_symbol:
            raise RuntimeError("symbol failed")
        candles = tuple(
            candle(open_time)
            for open_time in range(request.start_time_ms, request.end_time_ms, 60_000)
        )
        return HistoricalCandleResult(
            request=request,
            candles=candles,
            pages=1,
            latest_completed_time_ms=self.fetch_latest_completed_candle_time(request.symbol),
        )

    def fetch_historical_candle_page(self, request: ExchangeHistoricalCandleRequest) -> CandlePage:
        candles = tuple(candle(open_time) for open_time in range(request.start_time_ms, request.end_time_ms, 60_000))
        return CandlePage(candles=candles, next_start_time_ms=None, complete=True)

    def fetch_latest_completed_candle_time(self, _symbol: str) -> int:
        return 120_000

    def normalize_symbol(self, exchange_symbol: str) -> str:
        return exchange_symbol

    def get_contract_metadata(self, symbol: str) -> ContractMetadata | None:
        return contract(symbol=symbol)

    def get_rate_limit_metadata(self) -> RateLimitMetadata:
        return RateLimitMetadata(requests_per_second=1.0, page_size=500)


class NonAdvancingCursorAdapter(BitMartFuturesMarketDataAdapter):
    def fetch_historical_candle_page(self, request: ExchangeHistoricalCandleRequest) -> CandlePage:
        return CandlePage(candles=(candle(request.start_time_ms),), next_start_time_ms=request.start_time_ms, complete=False)


def historical_request(
    *,
    start: int,
    end: int,
    timeframe: Timeframe = Timeframe.ONE_MINUTE,
    limit: int = 500,
) -> ExchangeHistoricalCandleRequest:
    return ExchangeHistoricalCandleRequest(
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        symbol="BTCUSDT",
        timeframe=timeframe,
        start_time_ms=start,
        end_time_ms=end,
        limit=limit,
    )


def kline_calls_from(transport: FakeTransport) -> list[dict[str, str | int]]:
    return [params for path, params in transport.calls if path.endswith("/kline")]


def planner_for(store: InMemoryCandleHistoryStore) -> IncrementalSyncPlanner:
    return IncrementalSyncPlanner(
        history_store=store,
        history_horizon_ms=NOW_MS,
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        priority_symbols=("BTCUSDT",),
    )


def contract(symbol: str = "BTCUSDT") -> ContractMetadata:
    return ContractMetadata(
        exchange=ExchangeName.BITMART,
        exchange_symbol=symbol,
        canonical_symbol=symbol,
        base_asset=symbol[:-4],
        quote_asset="USDT",
        market_type=MarketType.USDT_M_PERPETUAL,
        status=ContractStatus.TRADING,
        is_perpetual=True,
        is_active=True,
        listing_time_ms=0,
    )


def candle(open_time_ms: int) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        open_time_ms=open_time_ms,
        close_time_ms=open_time_ms + 60_000,
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1.0,
    )


def sync_status() -> SymbolSyncStatus:
    from backend.sync import SyncProgress, SymbolSyncStatus

    return SymbolSyncStatus(
        exchange=ExchangeName.BITMART,
        market_type=MarketType.USDT_M_PERPETUAL,
        symbol="BTCUSDT",
        canonical_symbol="BTCUSDT",
        state=SyncState.READY,
        progress=SyncProgress(3, 3),
    )
