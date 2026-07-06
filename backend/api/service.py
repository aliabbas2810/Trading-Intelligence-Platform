from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

from backend.api.replay import ReplayStartRequest, ReplayStatusResponse
from backend.api.scanner import ScannerRunRequest, ScannerSummaryResponse
from backend.app.runtime import BackendRuntime, RuntimeState
from backend.models import Timeframe


LOCAL_FRONTEND_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime = runtime_from_app(app)
    if runtime.state is not RuntimeState.RUNNING:
        runtime.start()
    try:
        yield
    finally:
        if runtime.state is RuntimeState.RUNNING:
            runtime.stop()


def create_app(runtime: BackendRuntime | None = None) -> FastAPI:
    """Create the local API service for RUNTIME-001 through RUNTIME-004."""

    api_runtime = runtime or BackendRuntime()
    app = FastAPI(
        title="Trading Intelligence Platform API",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.runtime = api_runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LOCAL_FRONTEND_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(request: Request) -> object:
        """Return runtime health/status for RUNTIME-004."""

        return jsonable_encoder(runtime_from_request(request).health())

    @app.get("/api/health")
    def api_health(request: Request) -> object:
        """API-prefixed health/status for local clients."""

        return jsonable_encoder(runtime_from_request(request).health())

    @app.get("/api/candles")
    def candles(request: Request, symbol: str, timeframe: Timeframe) -> object:
        """Read stored candles through the visualization boundary for FR-601."""

        api = runtime_from_request(request).visualization_api
        return jsonable_encoder(api.get_candles(symbol, timeframe))

    @app.get("/api/market-structure")
    def market_structure(request: Request, symbol: str, timeframe: Timeframe) -> object:
        """Read precomputed structure through the visualization boundary for FR-602/FR-604."""

        api = runtime_from_request(request).visualization_api
        return jsonable_encoder(api.get_market_structure(symbol, timeframe))

    @app.get("/api/trend-state")
    def trend_state(request: Request, symbol: str, timeframe: Timeframe) -> object:
        """Read precomputed trend state through the visualization boundary for FR-603."""

        api = runtime_from_request(request).visualization_api
        return jsonable_encoder(api.get_trend_state(symbol, timeframe))

    @app.get("/api/multi-timeframe-alignment")
    def multi_timeframe_alignment(request: Request, symbol: str) -> object:
        """Read precomputed multi-timeframe alignment through the API boundary."""

        api = runtime_from_request(request).visualization_api
        return jsonable_encoder(api.get_multi_timeframe_alignment(symbol))

    @app.post("/api/replay/start")
    def replay_start(request: Request, payload: ReplayStartRequest | None = None) -> object:
        """Start demo replay through the runtime for FR-801 and FR-802."""

        replay_request = payload or ReplayStartRequest()
        snapshot = runtime_from_request(request).start_replay(
            source_type=replay_request.source_type,
            speed_multiplier=replay_request.speed_multiplier,
        )
        return ReplayStatusResponse.from_snapshot(snapshot)

    @app.post("/api/replay/pause")
    def replay_pause(request: Request) -> object:
        """Pause replay for FR-803."""

        return ReplayStatusResponse.from_snapshot(runtime_from_request(request).pause_replay())

    @app.post("/api/replay/resume")
    def replay_resume(request: Request) -> object:
        """Resume replay for FR-804."""

        return ReplayStatusResponse.from_snapshot(runtime_from_request(request).resume_replay())

    @app.post("/api/replay/stop")
    def replay_stop(request: Request) -> object:
        """Stop replay for FR-801."""

        return ReplayStatusResponse.from_snapshot(runtime_from_request(request).stop_replay())

    @app.post("/api/replay/step")
    def replay_step(request: Request) -> object:
        """Publish one replay event through the runtime for FR-805 and FR-806."""

        return ReplayStatusResponse.from_snapshot(runtime_from_request(request).step_replay())

    @app.get("/api/replay/status")
    def replay_status(request: Request) -> object:
        """Return replay status/progress for RUNTIME-004."""

        return ReplayStatusResponse.from_snapshot(runtime_from_request(request).replay_status())

    @app.post("/api/scanner/run")
    def scanner_run(request: Request, payload: ScannerRunRequest | None = None) -> object:
        """Run scanner over existing snapshots for FR-901 through FR-905."""

        scan_request = payload or ScannerRunRequest()
        summary = runtime_from_request(request).run_scanner(
            symbols=scan_request.symbols,
            timeframe=scan_request.timeframe,
            bias=scan_request.bias.to_directional_bias(),
            minimum_alignment_score=scan_request.minimum_alignment_score,
            minimum_setup_score=scan_request.minimum_setup_score,
        )
        return ScannerSummaryResponse.from_summary(summary, limit=scan_request.limit)

    @app.get("/api/scanner/status")
    def scanner_status(request: Request) -> object:
        """Return latest scanner summary for RUNTIME-004."""

        summary = runtime_from_request(request).scanner_status()
        if summary is None:
            return ScannerSummaryResponse(
                scanned_symbols=(),
                total_symbols=0,
                filtered_symbols=0,
                candidates=(),
                results=(),
            )
        return ScannerSummaryResponse.from_summary(summary)

    return app


def runtime_from_request(request: Request) -> BackendRuntime:
    return runtime_from_app(request.app)


def runtime_from_app(app: FastAPI) -> BackendRuntime:
    runtime = app.state.runtime
    if not isinstance(runtime, BackendRuntime):
        raise RuntimeError("FastAPI app state does not contain BackendRuntime")
    return runtime
