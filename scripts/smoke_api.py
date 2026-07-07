from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class SmokeEndpoint:
    name: str
    path: str
    query: dict[str, str] | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the local TIP API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend API base URL.")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol for symbol-scoped endpoints.")
    parser.add_argument("--timeframe", default="4h", help="Timeframe for timeframe-scoped endpoints.")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    endpoints = (
        SmokeEndpoint("health", "/api/health"),
        SmokeEndpoint("candles", "/api/candles", {"symbol": args.symbol, "timeframe": args.timeframe}),
        SmokeEndpoint(
            "market-structure",
            "/api/market-structure",
            {"symbol": args.symbol, "timeframe": args.timeframe},
        ),
        SmokeEndpoint("trend-state", "/api/trend-state", {"symbol": args.symbol, "timeframe": args.timeframe}),
        SmokeEndpoint("multi-timeframe-alignment", "/api/multi-timeframe-alignment", {"symbol": args.symbol}),
        SmokeEndpoint("replay-status", "/api/replay/status"),
        SmokeEndpoint("scanner-status", "/api/scanner/status"),
    )

    failed = False
    for endpoint in endpoints:
        ok, detail = check_endpoint(base_url, endpoint)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {endpoint.name}: {detail}")
        failed = failed or not ok

    return 1 if failed else 0


def check_endpoint(base_url: str, endpoint: SmokeEndpoint) -> tuple[bool, str]:
    url = build_url(base_url, endpoint)
    try:
        payload = get_json(url)
    except HTTPError as error:
        return False, f"HTTP {error.code} {url}"
    except URLError as error:
        return False, f"connection failed: {error.reason}"
    except TimeoutError:
        return False, "request timed out"
    except json.JSONDecodeError as error:
        return False, f"invalid JSON: {error.msg}"

    if payload is None:
        return False, "empty JSON payload"
    return True, summarize_payload(payload)


def build_url(base_url: str, endpoint: SmokeEndpoint) -> str:
    if not endpoint.query:
        return f"{base_url}{endpoint.path}"
    return f"{base_url}{endpoint.path}?{urlencode(endpoint.query)}"


def get_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def summarize_payload(payload: Any) -> str:
    if isinstance(payload, list):
        return f"list items={len(payload)}"
    if isinstance(payload, dict):
        keys = ", ".join(sorted(payload.keys())[:6])
        return f"object keys={keys}"
    return type(payload).__name__


if __name__ == "__main__":
    sys.exit(main())
