from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from backend.engines.historical import (
    BinanceHistoricalCandleDownloader,
    HistoricalCandleFileStore,
    HistoricalCandleRequest,
)
from backend.engines.historical.loader import parse_utc_timestamp_ms
from backend.engines.historical.validation import HistoricalValidationRunner
from backend.models import Timeframe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate historical Binance candles through TIP engines.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1m", choices=[timeframe.value for timeframe in Timeframe])
    parser.add_argument("--start", required=True, help="UTC ISO timestamp, e.g. 2025-01-01T00:00:00Z")
    parser.add_argument("--end", required=True, help="UTC ISO timestamp, e.g. 2025-01-01T02:00:00Z")
    parser.add_argument("--data-root", default=str(Path("data") / "historical"))
    parser.add_argument("--download", action="store_true", help="Download from Binance before validation.")
    args = parser.parse_args(argv)

    request = HistoricalCandleRequest(
        symbol=args.symbol.upper(),
        timeframe=Timeframe(args.timeframe),
        start_time_ms=parse_utc_timestamp_ms(args.start),
        end_time_ms=parse_utc_timestamp_ms(args.end),
    )
    store = HistoricalCandleFileStore(Path(args.data_root))
    if args.download:
        candles = BinanceHistoricalCandleDownloader().load(request)
        path = store.save(request, candles)
    else:
        path = store.path_for(request)
        candles = store.load(request)

    summary = HistoricalValidationRunner().run(
        candles,
        symbol=request.symbol,
        timeframe=request.timeframe,
    )
    print(f"source_path={path}")
    for key, value in asdict(summary).items():
        if hasattr(value, "value"):
            value = value.value
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
