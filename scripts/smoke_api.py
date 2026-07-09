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
    method: str = "GET"
    query: dict[str, str] | None = None
    body: dict[str, str | float] | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the local TIP API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend API base URL.")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol for symbol-scoped endpoints.")
    parser.add_argument("--timeframe", default="4h", help="Timeframe for timeframe-scoped endpoints.")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    endpoints = (
        SmokeEndpoint("health", "/api/health"),
        SmokeEndpoint("candles", "/api/candles", query={"symbol": args.symbol, "timeframe": args.timeframe}),
        SmokeEndpoint(
            "market-structure",
            "/api/market-structure",
            query={"symbol": args.symbol, "timeframe": args.timeframe},
        ),
        SmokeEndpoint("trend-state", "/api/trend-state", query={"symbol": args.symbol, "timeframe": args.timeframe}),
        SmokeEndpoint("multi-timeframe-alignment", "/api/multi-timeframe-alignment", query={"symbol": args.symbol}),
        SmokeEndpoint("replay-status", "/api/replay/status"),
        SmokeEndpoint("scanner-status", "/api/scanner/status"),
        SmokeEndpoint("entry", "/api/entry/evaluate", method="POST", body={"symbol": args.symbol}),
        SmokeEndpoint(
            "risk",
            "/api/risk/evaluate",
            method="POST",
            body={"symbol": args.symbol, "minimum_risk_reward": 2.0},
        ),
        SmokeEndpoint(
            "checklist",
            "/api/checklist/evaluate",
            method="POST",
            body={"symbol": args.symbol, "minimum_risk_reward": 2.0},
        ),
        SmokeEndpoint(
            "setup-score",
            "/api/setup-score/evaluate",
            method="POST",
            body={"symbol": args.symbol, "minimum_risk_reward": 2.0},
        ),
        SmokeEndpoint(
            "trading-intelligence",
            "/api/trading-intelligence/evaluate",
            method="POST",
            body={
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "minimum_risk_reward": 2.0,
            },
        ),
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
        payload = request_json(url, method=endpoint.method, body=endpoint.body)
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


def request_json(url: str, *, method: str, body: dict[str, str | float] | None = None) -> Any:
    encoded_body = None
    headers = {"Accept": "application/json"}
    if body is not None:
        encoded_body = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=encoded_body, headers=headers, method=method)
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def summarize_payload(payload: Any) -> str:
    if isinstance(payload, list):
        return f"list items={len(payload)}"
    if isinstance(payload, dict):
        intelligence_summary = summarize_intelligence_payload(payload)
        if intelligence_summary is not None:
            return intelligence_summary
        keys = ", ".join(sorted(payload.keys())[:6])
        return f"object keys={keys}"
    return type(payload).__name__


def summarize_intelligence_payload(payload: dict[str, Any]) -> str | None:
    if "entry_decision" in payload and "risk_plan" in payload and "setup_score" in payload:
        return (
            "entry="
            f"{payload['entry_decision'].get('state')}/"
            f"{payload['entry_decision'].get('direction')} "
            f"risk={payload['risk_plan'].get('state')} "
            f"checklist={payload['checklist'].get('overall_status')} "
            f"score={payload['setup_score'].get('grade')}"
        )
    if {"state", "direction", "confidence"}.issubset(payload):
        return f"entry={payload.get('state')}/{payload.get('direction')}"
    if "risk_reward_ratio" in payload and "state" in payload:
        return f"risk={payload.get('state')} rr={payload.get('risk_reward_ratio')}"
    if "overall_status" in payload:
        return (
            f"checklist={payload.get('overall_status')} "
            f"pass={payload.get('pass_count')} fail={payload.get('fail_count')}"
        )
    if "grade" in payload and "percentage" in payload:
        return f"score={payload.get('grade')} percentage={payload.get('percentage')}"
    return None


if __name__ == "__main__":
    sys.exit(main())
