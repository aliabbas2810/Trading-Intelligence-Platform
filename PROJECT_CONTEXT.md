# Project Context

## Project Name

Trading Intelligence Platform (TIP)

## Current Development Phase

Phase 3 planning for Trading Intelligence.

## What We Are Building

TIP is a local-first, professional market-analysis platform for deterministic crypto market analysis and future AI-assisted trading intelligence.

The platform starts with Binance Spot trade data and BTCUSDT, but the backend now includes foundations for multi-symbol scanning, replay-compatible processing, visualization read models, and structured AI decision support.

## Completed Milestones

| Milestone | Status | Summary |
|---|---|---|
| M1 | Completed | Repository foundation, typed settings, structured logging, synchronous event bus, tests. |
| M2 | Completed | Binance Spot trade ingestion foundation, trade normalization, validation, stream client skeleton. |
| M3 | Completed | Deterministic 1-minute candle construction, synthetic candles, in-memory and JSONL persistence. |
| M4 | Completed | 4H, Daily, and Weekly aggregation from completed 1-minute candles. |
| M5 | Completed | Body-based market structure engine with displacement-based swings and BOS detection. |
| M6 | Completed | Timeframe-independent trend engine plus multi-timeframe aggregation. |
| M7 | Completed | Read-only visualization API and React + Lightweight Charts frontend foundation. |
| M8 | Completed | Replay engine that publishes historical events through the same event bus path as live mode. |
| M9 | Completed | Backend scanner foundation that ranks existing multi-symbol analytical outputs. |
| M10 | Completed | Backend AI decision engine foundation with structured input and deterministic mock provider. |
| M11-M20 | Completed | Runtime/API/frontend stabilization through local runnable backend, live Binance mode wiring, API service, visualization data connection, demo data, replay controls, scanner API/UI, AI decision API, and non-destructive chart replay cursor. |

## Current Architecture

TIP is organized around pipelines and engines:

- `backend/core/`: synchronous event bus and structured logging.
- `backend/config/`: Pydantic settings and version-controlled defaults.
- `backend/models/`: canonical domain objects such as `Trade`, `Candle`, and `Timeframe`.
- `backend/pipelines/market_data/`: Binance trade parsing, validation, status events, and stream-client skeleton.
- `backend/pipelines/candle/`: deterministic 1-minute candle building from canonical trade events.
- `backend/pipelines/timeframe/`: deterministic 4H, Daily, and Weekly aggregation from closed 1-minute candles.
- `backend/storage/`: in-memory and JSONL candle persistence boundaries.
- `backend/engines/structure/`: body-only market structure detection.
- `backend/engines/trend/`: trend classification and multi-timeframe trend aggregation.
- `backend/engines/replay/`: replay sources and controller that reuse the event bus.
- `backend/engines/scanner/`: setup candidate scoring and ranking from existing snapshots.
- `backend/engines/checklist/`: deterministic checklist results from entry/risk typed evidence.
- `backend/engines/risk/`: deterministic risk plan foundation from entry traces, candles, and structure levels.
- `backend/engines/ai/`: structured AI decision foundation with provider abstraction and mock provider.
- `backend/api/`: read-only visualization API boundaries over existing stores/snapshots.
- `frontend/`: React + Lightweight Charts visualization shell and contract tests.

## Core Decisions Already Made

1. Binance Spot trade stream is the first live data source.
2. BTCUSDT is the first symbol.
3. The system builds candles from trade stream data, not Binance chart overlays.
4. One-minute candles are the authoritative base timeframe.
5. Supported chart timeframes are 1W, 1D, 4H, 2H, 1H, 30M, 15M, 5M, and 1M; higher timeframes are derived from one-minute candles.
6. Candle closure is time-driven and UTC aligned.
7. Millisecond precision is used internally.
8. In-memory and disk persistence are both supported for candles.
9. Market structure is based on candle bodies only.
10. Wicks are preserved for visualization and future SL/TP logic.
11. Replay and live modes should share the same downstream event path wherever practical.
12. React + Lightweight Charts is the target UI stack.
13. Python is used first for correctness and speed of development.
14. C++ migration is planned later only for performance-critical hotspots.
15. LLMs are future reasoning layers, not structure-calculation engines.
16. The repository is the source of truth for Codex and future agents.

## Current Capability Snapshot

The backend can normalize trades, build and persist candles, aggregate higher timeframes, detect body-based structure, classify trends, aggregate multi-timeframe trend state, expose local API endpoints, replay historical events through deterministic replay components, drive non-destructive chart replay with a cursor, scan existing outputs for ranked setup candidates, classify entry state, produce deterministic risk plans, produce evidence-driven checklists, and produce structured mock AI decision outputs.

The frontend can render backend-provided candles, structure overlays, BOS overlays, trend background/ribbon state, replay cursor controls, scanner results, and timeframe/symbol controls. It does not calculate market structure, trend, scanner score, or entry logic.

## Next Recommended Phase

Recommended next phase: Phase 3 Trading Intelligence.

Goal: add deterministic setup-state classification on top of the completed market data, candle, structure, trend, replay, scanner, visualization, and AI foundations.

Planned M21: Entry Signal Engine.

M21 should consume existing deterministic outputs only:

- 1W, 1D, 4H, 2H, 1H, and 30M trend states.
- 15M, 5M, and 1M structure snapshots.
- BOS events, latest candles/body levels, and multi-timeframe alignment.

M21 should classify the market as `WAIT`, `WATCH`, `LONG_SETUP`, `SHORT_SETUP`, `ENTRY_READY`, or `INVALIDATED`.

M21 shall not execute trades, calculate position size, place orders, or use AI to decide structure. AI remains a downstream explanation layer over structured facts.

Short roadmap after M21: expose entry signal state through backend APIs, then add optional UI rendering for entry-state diagnostics without adding order execution.

## LLM Role

The LLM receives structured facts such as trend state, multi-timeframe alignment, scanner score, structure snapshot, risk/reward placeholders, and setup context. It produces explanation, risks, confidence, and recommendation. It must not calculate candles, HH/HL/LH/LL, BOS, trend, risk metrics, or scanner scores.
