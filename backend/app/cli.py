from __future__ import annotations

import argparse
import json
import time

from backend.app.runtime import BackendRuntime, RuntimeMode
from backend.api import create_app


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for local runtime startup under RUNTIME-001 and RUNTIME-005."""

    parser = argparse.ArgumentParser(description="Start the TIP backend runtime")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="start without live Binance streaming")
    mode_group.add_argument("--live-binance", action="store_true", help="start Binance live stream when config enables it")
    parser.add_argument("--api", action="store_true", help="run the local FastAPI service")
    parser.add_argument("--host", default="127.0.0.1", help="API host when --api is used")
    parser.add_argument("--port", type=int, default=8000, help="API port when --api is used")
    parser.add_argument("--once", action="store_true", help="print health and stop immediately")
    args = parser.parse_args(argv)

    mode = RuntimeMode.LIVE_BINANCE if args.live_binance else RuntimeMode.DRY_RUN
    runtime = BackendRuntime(mode=mode)
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
