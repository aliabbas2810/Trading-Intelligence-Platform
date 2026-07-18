from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

from backend.api.ai import AiDecisionRequest, AiDecisionResponse
from backend.api.aoi import (
    AoiDiagnosticsResponse,
    AoiEvaluateRequest,
    AoiGateResponse,
    AoiLocationRequest,
    AoiOverlapResponse,
    AoiReadResponse,
    AoiResponse,
)
from backend.api.checklist import ChecklistEvaluateRequest, ChecklistResultResponse
from backend.api.entry import EntryDecisionResponse, EntryEvaluateRequest
from backend.api.market_data_sync import ContractsResponse, SyncCoordinatorStatusResponse, SymbolSyncStatusResponse
from backend.api.replay import ReplayStartRequest, ReplayStatusResponse
from backend.api.readiness import AnalysisReadinessResponse
from backend.api.risk import RiskEvaluateRequest, RiskPlanResponse
from backend.api.scanner import ScannerRunRequest, ScannerSummaryResponse
from backend.api.scoring import SetupScoreEvaluateRequest, SetupScoreResponse
from backend.api.trading_intelligence import TradingIntelligenceRequest, TradingIntelligenceResponse
from backend.app.runtime import BackendRuntime, RuntimeState
from backend.engines.aoi import AoiTimeframe
from backend.models import Timeframe


LOCAL_FRONTEND_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runtime = runtime_from_app(app)
    if runtime.state is not RuntimeState.RUNNING:
        if runtime.requires_background_initialization:
            app.state.runtime_start_task = asyncio.create_task(_start_runtime_in_background(runtime))
        else:
            runtime.start()
    try:
        yield
    finally:
        start_task = getattr(app.state, "runtime_start_task", None)
        if isinstance(start_task, asyncio.Task):
            runtime.stop()
            with suppress(asyncio.CancelledError):
                await start_task
        elif runtime.state in {RuntimeState.RUNNING, RuntimeState.STARTING, RuntimeState.FAILED}:
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
    def candles(
        request: Request,
        symbol: str,
        timeframe: Timeframe,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int | None = None,
    ) -> object:
        """Read stored candles through the visualization boundary for FR-601."""

        _validate_bounded_read_request(start_time_ms=start_time_ms, end_time_ms=end_time_ms, limit=limit)
        api = runtime_from_request(request).visualization_api
        return jsonable_encoder(
            tuple(
                {
                    "symbol": candle.symbol,
                    "timeframe": candle.timeframe.value,
                    "open_time_ms": candle.open_time_ms,
                    "close_time_ms": candle.close_time_ms,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                }
                for candle in api.get_candles(
                    symbol,
                    timeframe,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    limit=limit,
                )
            )
        )

    @app.get("/api/market-structure")
    def market_structure(
        request: Request,
        symbol: str,
        timeframe: Timeframe,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int | None = None,
    ) -> object:
        """Read precomputed structure through the visualization boundary for FR-602/FR-604."""

        _validate_bounded_read_request(start_time_ms=start_time_ms, end_time_ms=end_time_ms, limit=limit)
        snapshot = runtime_from_request(request).market_structure_snapshot(symbol, timeframe)
        return jsonable_encoder(_public_market_structure_response(snapshot))

    @app.get("/api/market-state")
    def market_state(request: Request, symbol: str) -> object:
        """Return only the authoritative Weekly/Daily/4H current market state."""

        return jsonable_encoder(runtime_from_request(request).market_state(symbol))

    @app.get("/api/market-structure/diagnostics")
    def market_structure_diagnostics(request: Request, symbol: str, timeframe: Timeframe) -> object:
        """Expose structure lifecycle diagnostics for M31.3 acceptance analysis."""

        return jsonable_encoder(runtime_from_request(request).market_structure_diagnostics(symbol, timeframe))

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

    @app.get("/api/market-data/contracts")
    def market_data_contracts(request: Request) -> object:
        """Return synchronized/discovered market-data contracts for EXCHANGE-001."""

        symbols = runtime_from_request(request).market_data_contracts()
        return ContractsResponse(symbols=symbols, total=len(symbols))

    @app.get("/api/market-data/sync/status")
    def market_data_sync_status(request: Request) -> object:
        """Return aggregate market-data sync status for SYNC-010."""

        status = runtime_from_request(request).market_data_sync_status()
        if status is None:
            return {"enabled": False}
        return SyncCoordinatorStatusResponse.from_status(status)

    @app.get("/api/market-data/sync/status/{symbol}")
    def market_data_sync_symbol_status(request: Request, symbol: str) -> object:
        """Return per-symbol market-data sync status for SYNC-010."""

        coordinator = runtime_from_request(request).market_data_sync_coordinator
        if coordinator is None:
            return {"enabled": False, "symbol": symbol}
        status = coordinator.symbol_status(symbol)
        if status is None:
            return {"enabled": True, "symbol": symbol, "state": "UNKNOWN"}
        return SymbolSyncStatusResponse.from_status(status)

    @app.post("/api/market-data/sync/start")
    def market_data_sync_start(request: Request) -> object:
        """Run one deterministic synchronization pass for SYNC-007."""

        status = runtime_from_request(request).start_market_data_sync()
        if status is None:
            return {"enabled": False}
        return SyncCoordinatorStatusResponse.from_status(status)

    @app.post("/api/market-data/sync/symbol/{symbol}")
    def market_data_sync_symbol(request: Request, symbol: str) -> object:
        """Synchronize one symbol through runtime orchestration."""

        status = runtime_from_request(request).sync_market_data_symbol(symbol)
        if status is None:
            return {"enabled": False, "symbol": symbol}
        return SymbolSyncStatusResponse.from_status(status)

    @app.post("/api/market-data/sync/gap-repair/{symbol}")
    def market_data_sync_gap_repair(request: Request, symbol: str) -> object:
        """Run explicit gap-repair planning for one symbol."""

        status = runtime_from_request(request).sync_market_data_symbol(symbol, gap_repair=True)
        if status is None:
            return {"enabled": False, "symbol": symbol}
        return SymbolSyncStatusResponse.from_status(status)

    @app.get("/api/data-readiness")
    def data_readiness(request: Request, symbol: str) -> object:
        """Return historical/data warm-up diagnostics without recalculating analysis."""

        readiness = runtime_from_request(request).evaluate_data_readiness(symbol=symbol)
        return AnalysisReadinessResponse.from_readiness(readiness)

    @app.post("/api/aois/evaluate")
    def aoi_evaluate(request: Request, payload: AoiEvaluateRequest) -> object:
        """Evaluate Weekly/Daily AOIs through the runtime orchestration boundary."""

        result = runtime_from_request(request).evaluate_aois(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            sizing=payload.to_sizing_config(),
            tick_size=payload.tick_size,
            atr=payload.atr,
        )
        return jsonable_encoder(result)

    @app.get("/api/aois")
    def aois(
        request: Request,
        symbol: str,
        timeframe: AoiTimeframe | None = None,
        state_filter: str = "active",
    ) -> object:
        """List cached AOIs, overlaps, and location gate without recomputing AOIs."""

        runtime = runtime_from_request(request)
        areas = runtime.list_aois(symbol=symbol, timeframe=timeframe)
        if state_filter == "active":
            areas = tuple(area for area in areas if area.state.value == "active")
        elif state_filter == "active_broken":
            areas = tuple(area for area in areas if area.state.value in {"active", "broken", "retest_pending"})
        overlaps = runtime.list_aoi_overlaps(symbol=symbol, confluence_weight=1.0)
        gate = runtime.evaluate_aoi_gate(symbol=symbol)
        diagnostics = runtime.aoi_diagnostics(symbol=symbol, timeframe=timeframe)
        return AoiReadResponse(
            symbol=symbol,
            aois=tuple(AoiResponse.from_area(area) for area in areas),
            overlaps=tuple(AoiOverlapResponse.from_overlap(item) for item in overlaps),
            location_gate=AoiGateResponse.from_gate(gate),
            location_gate_eligible=gate.eligible,
            reason_codes=gate.reason_codes,
            diagnostics=tuple(
                AoiDiagnosticsResponse(
                    timeframe=item.timeframe.value,
                    evaluated=item.evaluated,
                    reason_code=item.reason_code,
                    candle_count=item.candle_count,
                    swing_count=item.swing_count,
                    trend_available=item.trend_available,
                    candidate_count=item.candidate_count,
                    active_count=item.active_count,
                    broken_count=item.broken_count,
                    archived_count=item.archived_count,
                )
                for item in diagnostics
            ),
        )

    @app.get("/api/aoi-overlaps")
    def aoi_overlaps(
        request: Request,
        symbol: str,
        confluence_weight: float,
    ) -> object:
        """Return Weekly/Daily AOI intersections without merging their source zones."""

        return jsonable_encoder(
            runtime_from_request(request).list_aoi_overlaps(
                symbol=symbol,
                confluence_weight=confluence_weight,
            )
        )

    @app.post("/api/aoi-location")
    def aoi_location(request: Request, payload: AoiLocationRequest) -> object:
        """Evaluate the deterministic live AOI location gate."""

        return jsonable_encoder(
            runtime_from_request(request).evaluate_aoi_location(
                symbol=payload.symbol,
                aoi_id=payload.aoi_id,
                config=payload.to_location_config(),
            )
        )

    @app.get("/api/aoi-location")
    def aoi_location_read(request: Request, symbol: str) -> object:
        """Read the symbol-level Weekly/Daily AOI location hard gate."""

        return AoiGateResponse.from_gate(runtime_from_request(request).evaluate_aoi_gate(symbol=symbol))

    @app.post("/api/replay/start")
    def replay_start(request: Request, payload: ReplayStartRequest | None = None) -> object:
        """Start demo replay through the runtime for FR-801 and FR-802."""

        replay_request = payload or ReplayStartRequest()
        snapshot = runtime_from_request(request).start_replay(
            source_type=replay_request.source_type,
            speed_multiplier=replay_request.speed_multiplier,
            start_index=replay_request.start_index,
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
        """Advance the runtime replay cursor for FR-805."""

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

    @app.post("/api/ai/decision")
    def ai_decision(request: Request, payload: AiDecisionRequest) -> object:
        """Return structured mock-provider decision output for FR-1001 through FR-1006."""

        output = runtime_from_request(request).generate_ai_decision(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            entry_signal=payload.entry_signal,
            risk_reward=payload.risk_reward,
        )
        return AiDecisionResponse.from_output(output)

    @app.post("/api/entry/evaluate")
    def entry_evaluate(request: Request, payload: EntryEvaluateRequest) -> object:
        """Evaluate deterministic entry state for ENTRY-001 through ENTRY-006."""

        trace = runtime_from_request(request).evaluate_entry_signal(symbol=payload.symbol)
        return EntryDecisionResponse.from_trace(trace)

    @app.post("/api/risk/evaluate")
    def risk_evaluate(request: Request, payload: RiskEvaluateRequest) -> object:
        """Evaluate deterministic risk plan for RISK-001 through RISK-006."""

        plan = runtime_from_request(request).evaluate_risk(
            symbol=payload.symbol,
            minimum_risk_reward=payload.minimum_risk_reward,
            target_mode=payload.target_mode,
        )
        return RiskPlanResponse.from_plan(plan)

    @app.post("/api/checklist/evaluate")
    def checklist_evaluate(request: Request, payload: ChecklistEvaluateRequest) -> object:
        """Evaluate evidence-driven checklist for CHECKLIST-001 through CHECKLIST-006."""

        result = runtime_from_request(request).evaluate_checklist(
            symbol=payload.symbol,
            minimum_risk_reward=payload.minimum_risk_reward,
        )
        return ChecklistResultResponse.from_result(result)

    @app.post("/api/setup-score/evaluate")
    def setup_score_evaluate(request: Request, payload: SetupScoreEvaluateRequest) -> object:
        """Evaluate deterministic weighted setup score for SCORE-001 through SCORE-006."""

        score = runtime_from_request(request).evaluate_setup_score(
            symbol=payload.symbol,
            minimum_risk_reward=payload.minimum_risk_reward,
        )
        return SetupScoreResponse.from_score(score)

    @app.post("/api/trading-intelligence/evaluate")
    def trading_intelligence_evaluate(request: Request, payload: TradingIntelligenceRequest) -> object:
        """Evaluate the full trading intelligence chain for INTEL-001 through INTEL-006."""

        result = runtime_from_request(request).evaluate_trading_intelligence(
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            minimum_risk_reward=payload.minimum_risk_reward,
        )
        return TradingIntelligenceResponse.from_result(result)

    return app


def runtime_from_request(request: Request) -> BackendRuntime:
    return runtime_from_app(request.app)


def _public_market_structure_response(snapshot: Any) -> dict[str, object]:
    """Expose prefixed public labels for M31.7 without leaking generic chart labels."""

    swings = tuple(
        {
            **jsonable_encoder(swing),
            "internal_label": swing.label.value,
            "label": swing.display_label or swing.label.value,
        }
        for swing in snapshot.swings
    )
    breaks = tuple(
        {
            **jsonable_encoder(break_of_structure),
            "internal_broken_label": break_of_structure.broken_label.value,
            "broken_label": break_of_structure.display_label or break_of_structure.broken_label.value,
            "label": break_of_structure.display_label or break_of_structure.broken_label.value,
        }
        for break_of_structure in snapshot.breaks_of_structure
    )
    return {"swings": swings, "breaks_of_structure": breaks}


def runtime_from_app(app: FastAPI) -> BackendRuntime:
    runtime = app.state.runtime
    if not isinstance(runtime, BackendRuntime):
        raise RuntimeError("FastAPI app state does not contain BackendRuntime")
    return runtime


async def _start_runtime_in_background(runtime: BackendRuntime) -> None:
    """Start long-running live initialization without blocking API availability."""

    try:
        await asyncio.to_thread(runtime.start)
    except Exception as exc:  # pragma: no cover - exercised through health surface.
        if runtime.state is not RuntimeState.FAILED:
            runtime.record_startup_failure(exc)


def _validate_bounded_read_request(
    *,
    start_time_ms: int | None,
    end_time_ms: int | None,
    limit: int | None,
) -> None:
    if start_time_ms is not None and end_time_ms is not None and end_time_ms <= start_time_ms:
        raise HTTPException(status_code=422, detail="end_time_ms must be greater than start_time_ms")
    if limit is not None and limit <= 0:
        raise HTTPException(status_code=422, detail="limit must be greater than zero")
