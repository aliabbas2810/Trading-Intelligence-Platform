# Project Context

## Project Name

Trading Intelligence Platform (TIP)

## Current Development Phase

Phase 3 Trading Intelligence implementation and validation.

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
| M21-M26 | Completed | Entry, risk, checklist, setup scoring, consolidated trading intelligence API, and Trading Intelligence Panel. |
| M27-M30 | In progress | Historical validation/runtime modes, Weekly/Daily AOI foundation, AOI visualization, and AOI hard-gate integration. |

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
- `backend/engines/scoring/`: deterministic weighted setup scoring from entry, risk, checklist, alignment, and optional scanner context.
- `backend/engines/intelligence/`: consolidated trading-intelligence result model for ordered orchestration.
- `backend/engines/ai/`: structured AI decision foundation with provider abstraction and mock provider.
- `backend/engines/aoi/`: Weekly/Daily AOI discovery, lifecycle, overlap, and location-gate foundation.
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

The backend can normalize trades, build and persist candles, aggregate higher timeframes, detect body-based structure, classify trends, aggregate multi-timeframe trend state, expose local API endpoints, replay historical events through deterministic replay components, drive non-destructive chart replay with a cursor, scan existing outputs for ranked setup candidates, classify entry state, produce deterministic risk plans, produce evidence-driven checklists, produce weighted setup scores, return consolidated trading-intelligence chains, and produce structured mock AI decision outputs.

The backend also has a Weekly/Daily AOI foundation and strategy gate. Precomputed bullish
HL-to-HH or bearish LH-to-LL legs define the search range; at least three candle-body
interactions confirm a zone. Wicks are excluded during historical construction but may count
when live price interacts with an established zone. Entry readiness now requires an eligible
active Weekly or Daily AOI location before lower-timeframe confirmation can become trade-ready.
The frontend renders backend-provided Weekly/Daily AOIs and W+D confluence without calculating
zones locally.

## AOI Calibration Decisions Still Open

- Instrument-specific crypto AOI minimum and maximum sizing values.
- AOI proximity tolerance and maximum post-reaction excursion.
- Production candidate-ranking weights.
- Historical AOI retention policy after an active-leg change.
- Weekly/Daily overlap score weight.
- Production AOI location gate tolerance and entry-window calibration.

The frontend can render backend-provided candles, structure overlays, BOS overlays, trend background/ribbon state, Weekly/Daily AOIs, W+D confluence, replay cursor controls, scanner results, trading intelligence, and timeframe/symbol controls. It does not calculate market structure, trend, AOIs, scanner score, or entry logic.

## Next Recommended Phase

Recommended next phase: continue Phase 3 validation.

Near-term focus:

- Validate AOI sizing/location calibration on historical and live market data.
- Add stronger historical acceptance tests for AOI gate behavior.
- Improve frontend visualization maturity without moving strategy logic into the UI.
- Keep real LLM providers and order execution out of scope until deterministic behavior is validated.

## LLM Role

The LLM receives structured facts such as trend state, multi-timeframe alignment, scanner score, structure snapshot, risk/reward placeholders, and setup context. It produces explanation, risks, confidence, and recommendation. It must not calculate candles, HH/HL/LH/LL, BOS, trend, risk metrics, or scanner scores.
