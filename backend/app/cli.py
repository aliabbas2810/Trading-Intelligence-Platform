from __future__ import annotations

import argparse
import json
import time

from backend.app.runtime import BackendRuntime, RuntimeMode


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for local dry-run startup under RUNTIME-001 and RUNTIME-005."""

    parser = argparse.ArgumentParser(description="Start the TIP backend runtime")
    parser.add_argument("--dry-run", action="store_true", help="start without live Binance streaming")
    parser.add_argument("--once", action="store_true", help="print health and stop immediately")
    args = parser.parse_args(argv)

    runtime = BackendRuntime(mode=RuntimeMode.DRY_RUN)
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
