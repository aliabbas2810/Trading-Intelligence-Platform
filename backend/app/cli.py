from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from backend.app.runtime import BackendRuntime, HistoricalRuntimeConfig, RuntimeMode
from backend.api.service import create_app
from backend.engines.historical import HistoricalCandleRequest
from backend.engines.historical.loader import parse_utc_timestamp_ms
from backend.models import Timeframe


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for local runtime startup under RUNTIME-001 and RUNTIME-005."""

    parser = argparse.ArgumentParser(description="Start the TIP backend runtime")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="start without live Binance streaming")
    mode_group.add_argument("--live-binance", action="store_true", help="start Binance live stream when config enables it")
    mode_group.add_argument("--historical", action="store_true", help="load local historical candle data")
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
    parser.add_argument("--download", action="store_true", help="download Binance historical candles before loading")
    parser.add_argument("--data-root", default=str(Path("data") / "historical"), help="historical candle data root")
    args = parser.parse_args(argv)

    mode = runtime_mode_from_args(args)
    runtime = BackendRuntime(
        mode=mode,
        historical_config=historical_config_from_args(args) if mode is RuntimeMode.HISTORICAL else None,
    )
    if args.api:
        import uvicorn

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


def runtime_mode_from_args(args: argparse.Namespace) -> RuntimeMode:
    if args.live_binance:
        return RuntimeMode.LIVE_BINANCE
    if args.historical:
        return RuntimeMode.HISTORICAL
    return RuntimeMode.DRY_RUN


def historical_config_from_args(args: argparse.Namespace) -> HistoricalRuntimeConfig:
    if args.start is None or args.end is None:
        raise SystemExit("--historical requires --start and --end")
    return HistoricalRuntimeConfig(
        request=HistoricalCandleRequest(
            symbol=args.symbol.upper(),
            timeframe=Timeframe(args.timeframe),
            start_time_ms=parse_utc_timestamp_ms(args.start),
            end_time_ms=parse_utc_timestamp_ms(args.end),
        ),
        data_root=Path(args.data_root),
        download=args.download,
    )
