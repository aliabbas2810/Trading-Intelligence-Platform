from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import threading
import time
from pathlib import Path

from backend.app.runtime import BackendRuntime, HistoricalRuntimeConfig, RuntimeMode
from backend.api.service import create_app
from backend.config import PlatformSettings, load_settings
from backend.engines.historical import HistoricalCandleRequest
from backend.engines.historical.loader import parse_utc_timestamp_ms
from backend.exchange import HistoricalIntegrityPolicy
from backend.models import Timeframe
from backend.pipelines.timeframe.aggregation import DAILY_MS, WEEKLY_MS


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for local runtime startup under RUNTIME-001 and RUNTIME-005."""

    parser = argparse.ArgumentParser(description="Start the TIP backend runtime")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="start without live BitMart streaming")
    mode_group.add_argument(
        "--live",
        "--live-bitmart",
        dest="live_bitmart",
        action="store_true",
        help="load BitMart cache, REST catch up closed 1m candles, then start live stream mode",
    )
    mode_group.add_argument("--historical", action="store_true", help="load local historical candle data")
    mode_group.add_argument(
        "--historical-live",
        action="store_true",
        help="load historical 1m candles, then continue with BitMart live mode",
    )
    parser.add_argument("--api", action="store_true", help="run the local FastAPI service")
    parser.add_argument("--host", default="127.0.0.1", help="API host when --api is used")
    parser.add_argument("--port", type=int, default=8000, help="API port when --api is used")
    parser.add_argument("--once", action="store_true", help="print health and stop immediately")
    parser.add_argument("--symbol", default="BTCUSDT", help="symbol for historical runtime mode")
    parser.add_argument(
        "--timeframe",
        default="1m",
        choices=[timeframe.value for timeframe in Timeframe],
        help="timeframe for historical runtime mode",
    )
    parser.add_argument("--start", help="historical UTC ISO start, e.g. 2025-01-01T00:00:00Z")
    parser.add_argument("--end", help="historical UTC ISO end, e.g. 2025-01-01T02:00:00Z")
    parser.add_argument("--download", action="store_true", help="download BitMart historical candles before loading")
    parser.add_argument("--data-root", default=str(Path("data") / "historical"), help="historical candle data root")
    parser.add_argument(
        "--historical-integrity-policy",
        default=HistoricalIntegrityPolicy.STRICT.value,
        choices=[policy.value for policy in HistoricalIntegrityPolicy],
        help="historical candle gap policy: strict, warn, or allow",
    )
    args = parser.parse_args(argv)

    mode = runtime_mode_from_args(args)
    if args.api:
        api_bind_preflight(args.host, args.port, mode)
    historical_modes = {RuntimeMode.HISTORICAL, RuntimeMode.HISTORICAL_LIVE}
    if mode in historical_modes:
        print_historical_preflight(args)
    runtime = BackendRuntime(
        settings=settings_from_args(args),
        mode=mode,
        historical_config=historical_config_from_args(args) if mode in historical_modes else None,
    )
    if args.api:
        import uvicorn

        LOGGER.info(
            "Starting Uvicorn server",
            extra={
                "operation": "uvicorn_run",
                "host_repr": repr(args.host),
                "port": args.port,
                "process_id": os.getpid(),
                "thread_name": threading.current_thread().name,
                "runtime_mode": mode.value,
            },
        )
        uvicorn.run(create_app(runtime), host=args.host, port=args.port)
        return 0

    runtime.start()
    health = runtime.health()
    print(
        json.dumps(
            {
                "state": health.state.value,
                "mode": health.mode.value,
                "components": {
                    component.name: component.status.value for component in health.components
                },
            },
            sort_keys=True,
        ),
    )
    if args.once:
        runtime.stop()
        return 0

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        runtime.stop()
    return 0


def api_bind_preflight(host: str, port: int, mode: RuntimeMode) -> None:
    """Validate the exact API bind host before runtime construction."""

    host_repr = repr(host)
    LOGGER.info(
        "API bind preflight starting",
        extra={
            "operation": "api_bind_preflight",
            "host_repr": host_repr,
            "port": port,
            "runtime_mode": mode.value,
            "thread_name": threading.current_thread().name,
        },
    )
    try:
        socket.getaddrinfo(host, port)
    except OSError as exc:
        LOGGER.exception(
            "API bind preflight failed",
            extra={
                "operation": "api_bind_preflight",
                "host_repr": host_repr,
                "port": port,
                "exception_type": type(exc).__name__,
                "thread_name": threading.current_thread().name,
            },
        )
        raise


def runtime_mode_from_args(args: argparse.Namespace) -> RuntimeMode:
    if args.live_bitmart:
        return RuntimeMode.LIVE_BITMART
    if args.historical_live:
        return RuntimeMode.HISTORICAL_LIVE
    if args.historical:
        return RuntimeMode.HISTORICAL
    return RuntimeMode.DRY_RUN


def settings_from_args(args: argparse.Namespace) -> PlatformSettings:
    settings = load_settings()
    updates: dict[str, object] = {
        "historical_data": settings.historical_data.model_copy(
            update={
                "integrity_policy": args.historical_integrity_policy,
                "data_root": Path(args.data_root),
            },
        ),
    }
    if not (args.live_bitmart or args.historical_live):
        return settings.model_copy(update=updates)
    updates["market_data"] = settings.market_data.model_copy(
        update={
            "symbols": (args.symbol.upper(),),
            "live_enabled": True,
        },
    )
    return settings.model_copy(
        update=updates,
    )


def historical_config_from_args(args: argparse.Namespace) -> HistoricalRuntimeConfig:
    if args.start is None or args.end is None:
        raise SystemExit("--historical/--historical-live requires --start and --end")
    if args.download and Timeframe(args.timeframe) is not Timeframe.ONE_MINUTE:
        raise SystemExit("--download uses canonical BitMart 1m futures candles; use --timeframe 1m")
    if args.historical_live and Timeframe(args.timeframe) is not Timeframe.ONE_MINUTE:
        raise SystemExit("--historical-live requires --timeframe 1m")
    return HistoricalRuntimeConfig(
        request=HistoricalCandleRequest(
            symbol=args.symbol.upper(),
            timeframe=Timeframe(args.timeframe),
            start_time_ms=parse_utc_timestamp_ms(args.start),
            end_time_ms=parse_utc_timestamp_ms(args.end),
        ),
        data_root=Path(args.data_root),
        download=args.download,
        integrity_policy=HistoricalIntegrityPolicy(args.historical_integrity_policy),
    )


def print_historical_preflight(args: argparse.Namespace) -> None:
    """Print non-blocking M28.1 historical warm-up diagnostics before runtime start."""

    if args.start is None or args.end is None:
        return
    start_time_ms = parse_utc_timestamp_ms(args.start)
    end_time_ms = parse_utc_timestamp_ms(args.end)
    expected_one_minute_candles = max(0, (end_time_ms - start_time_ms) // 60_000)
    print(
        "Historical preflight: "
        f"symbol={args.symbol.upper()} start={args.start} end={args.end} "
        f"expected_1m_candles={expected_one_minute_candles} "
        f"integrity_policy={args.historical_integrity_policy}",
    )
    if end_time_ms - start_time_ms < DAILY_MS:
        print("Historical preflight warning: range is shorter than 1d; daily/weekly analysis will be unavailable.")
    elif end_time_ms - start_time_ms < WEEKLY_MS:
        print("Historical preflight warning: range is shorter than 1w; weekly analysis will be unavailable.")
