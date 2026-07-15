# Implementation Log

## v0.1.0 Foundation

### M1 - Repository Foundation

Implemented backend package skeleton, Pydantic settings, structured logging, synchronous event bus, and baseline tests.

Verification: covered by backend pytest, ruff, and mypy.

### M29 - Weekly/Daily AOI Engine Foundation

Implemented a deterministic backend AOI domain and engine that consumes existing candle,
structure, and trend outputs without recalculating HH/HL/LH/LL or trend.

Implemented scope:

- `AOI-001`/`AOI-002`: typed bullish HL-to-HH and bearish LH-to-LL active-leg inputs for
  Weekly and Daily only.
- `AOI-003`/`AOI-004`: body-overlap candidate discovery, wick exclusion, separate first-touch
  and third-touch confirmation timestamps, and replay-safe tradability.
- `AOI-005`: configurable fixed-tick, percentage, ATR-normalized, and hybrid sizing plus
  deterministic configurable ranking.
- `AOI-006`/`AOI-007`: multiple-zone support and explicit lifecycle/invalidation states.
- `AOI-008`: non-destructive Weekly/Daily overlap detection and confluence metadata.
- `AOI-009`: deterministic live location gate with wick-aware established-zone contact.
- `AOI-010`: runtime evaluation/read methods and thin API endpoints; Entry Engine semantics
  remain unchanged.

Deferred calibration: crypto sizing values, proximity tolerance, reaction excursion, ranking
weights, historical retention policy, and overlap score weight.

### M2 - Market Data Pipeline

Implemented Binance Spot trade message parser/normalizer, trade validation, market data pipeline interface, stream-client skeleton, and event publication tests.

Verification: covered by backend pytest, ruff, and mypy.

### M3 - Candle Pipeline

Implemented deterministic 1-minute candle construction, UTC closure, synthetic candles, duplicate prevention, event publication, in-memory storage, and JSONL persistence.

Verification: covered by backend pytest, ruff, and mypy.

### M4 - Timeframe Pipeline

Implemented deterministic 4H, Daily, and Weekly aggregation from completed 1-minute candles with UTC boundary alignment.

Verification: covered by backend pytest, ruff, and mypy.

### M5 - Market Structure Engine

Implemented candle body helpers, displacement-based swing confirmation, HH/HL/LH/LL labels, BOS detection, and wick-ignorance tests.

Verification: covered by backend pytest, ruff, and mypy.

### M6 - Trend Engine

Implemented timeframe-independent trend state classification, immediate and confirmed BOS flip modes, trend events, and multi-timeframe aggregation.

Verification: covered by backend pytest, ruff, and mypy.

### M7 - Visualization Platform

Implemented read-only visualization API boundaries and React + Lightweight Charts rendering foundation for candles, structure levels, BOS, trend background, trend ribbon, and timeframe selection.

Verification: covered by backend pytest, ruff, mypy, and frontend contract tests.

### M8 - Replay Engine

Implemented historical trade/candle replay sources, replay controller, pause/resume/step/speed controls, progress events, and deterministic replay tests.

Verification: covered by backend pytest, ruff, and mypy.

### M9 - Multi-Symbol Scanner

Implemented backend scanner models, deterministic setup scoring, filtering, ranking, scanner events, and no-recalculation tests.

Verification: covered by backend pytest, ruff, and mypy.

### M10 - AI Decision Engine

Implemented structured AI decision input/output models, context builder, provider interface, deterministic mock provider, engine validation, and no-recalculation tests.

Verification: covered by backend pytest, ruff, and mypy.

## Stabilization Notes

- No real LLM provider is integrated.
- No order execution is implemented.
- No all-symbol live Binance streaming is implemented.
- Frontend remains a visualization foundation and does not calculate structure or trend logic.

## Phase 2 - v0.2.0 Runtime Assembly

### Planned M11 - Local Backend Runtime

Goal: assemble existing M1-M10 components into a runnable local backend application.

Planned scope:

- `RUNTIME-001`: application orchestrator.
- `RUNTIME-002`: component wiring using existing config, logging, event bus, storage, pipelines, engines, replay, scanner, AI, and read API boundaries.
- `RUNTIME-003`: start/stop lifecycle.
- `RUNTIME-004`: health/status reporting.
- `RUNTIME-005`: dry-run or replay-friendly local mode.

Constraints:

- Do not add new trading logic.
- Do not expand Binance live networking beyond existing foundations.
- Do not add real LLM integration.
- Do not add order execution.

Verification target: backend tests, lint, typecheck, and focused runtime assembly integration tests.

## Phase 3 - Trading Intelligence

### Planned M21 - Entry Signal Engine

Goal: classify deterministic setup state from existing trend, structure, BOS, candle/body, and multi-timeframe alignment outputs.

Planned states:

- `WAIT`
- `WATCH`
- `LONG_SETUP`
- `SHORT_SETUP`
- `ENTRY_READY`
- `INVALIDATED`

Planned scope:

- `ENTRY-001`: entry state classification.
- `ENTRY-002`: consume 1W, 1D, 4H, 2H, 1H, and 30M trend outputs.
- `ENTRY-003`: consume 15M, 5M, and 1M structure/BOS outputs.
- `ENTRY-004`: consume latest completed candle and candle body context.
- `ENTRY-005`: emit deterministic reasons/explanations.
- `ENTRY-006`: explicitly exclude order execution, position sizing, and AI-driven structure decisions.

Constraints:

- Do not execute trades.
- Do not calculate position size.
- Do not place orders.
- Do not use AI to determine market structure.
- Do not recalculate candles, structure, trend, scanner score, or AI context inside the entry engine.

Verification target: focused deterministic unit tests for each state, missing-data behavior, bullish/bearish setup symmetry, BOS/body-level gating, invalidation, and replay consistency.

### M22 - Risk Engine

Implemented deterministic backend risk-plan foundation that consumes Entry DecisionTrace, latest candle/body context, structure levels, BOS events, and optional R:R target settings.

Implemented scope:

- `RISK-001`: RiskPlan model and deterministic risk plan output.
- `RISK-002`: entry, stop, take-profit, invalidation level, and R:R derivation.
- `RISK-003`: long and short risk plan support.
- `RISK-004`: NOT_APPLICABLE, INVALID, and INCOMPLETE handling for unsuitable inputs.
- `RISK-005`: typed risk evidence, readable reasons, and warnings.
- `RISK-006`: explicit exclusion of position sizing, order execution, AI risk decisions, and recalculation of upstream logic.

Verification: covered by backend pytest, ruff, and mypy.

### M23 - Checklist Engine

Implemented deterministic backend checklist foundation that consumes Entry DecisionTrace evidence, RiskPlan evidence, multi-timeframe alignment, and runtime/data-quality metadata.

Implemented scope:

- `CHECKLIST-001`: ChecklistInput, ChecklistItem, and ChecklistResult models.
- `CHECKLIST-002`: conversion of entry evidence, missing confirmations, and invalidation evidence into checklist items.
- `CHECKLIST-003`: conversion of risk evidence, warnings, and risk assessment state into checklist items.
- `CHECKLIST-004`: deterministic checklist counts, overall status, and summary.
- `CHECKLIST-005`: graceful missing Entry/Risk input handling.
- `CHECKLIST-006`: explicit exclusion of recalculating upstream analysis, AI reasoning, position sizing, and order execution.

Verification: covered by backend pytest, ruff, and mypy.

### M24 - Setup Scoring Engine

Implemented deterministic backend setup scoring foundation that consumes Entry DecisionTrace, RiskPlan, ChecklistResult, multi-timeframe alignment, and optional scanner context.

Implemented scope:

- `SCORE-001`: SetupScore, ScoreComponent, ScoreGrade, and ScoringInput models.
- `SCORE-002`: weighted trend alignment, structure/entry confirmation, risk, and checklist scoring.
- `SCORE-003`: deterministic penalties for invalidated setups, incomplete risk, checklist failures, warnings, and missing confirmations.
- `SCORE-004`: grade, percentage, component details, warnings, summary, and metadata.
- `SCORE-005`: runtime/API evaluation boundary.
- `SCORE-006`: explicit exclusion of recalculating upstream analysis, AI reasoning, position sizing, and order execution.

Verification: covered by backend pytest, ruff, and mypy.

### M25 - Trading Intelligence API Consolidation

Implemented one backend orchestration API that returns the full trading intelligence chain for a symbol.

Implemented scope:

- `INTEL-001`: consolidated TradingIntelligenceResult and API response with entry, risk, checklist, setup score, AI decision, and metadata.
- `INTEL-002`: ordered runtime orchestration: entry -> risk -> checklist -> score -> AI.
- `INTEL-003`: reuse of existing runtime/engine boundaries without duplicating deterministic logic.
- `INTEL-004`: AI decision generated from structured outputs and existing runtime stores.
- `INTEL-005`: graceful missing-data response through existing WAIT/NOT_APPLICABLE/MISSING/low-score behavior.
- `INTEL-006`: no order execution, real LLM integration, API keys, external services, or new trading rules.

Verification: covered by backend pytest, ruff, and mypy.

### M29 - Weekly/Daily AOI Engine Foundation

Implemented deterministic Weekly/Daily AOI discovery over existing structure/trend outputs.

Implemented scope:

- `AOI-001`: active bullish HL-to-HH and bearish LH-to-LL structure-leg inputs.
- `AOI-002`: Weekly and Daily AOI scope only.
- `AOI-003`: historical candidate construction from candle-body interactions, not wick-only contacts.
- `AOI-004`: third qualifying body interaction confirmation with first-touch and confirmation timestamps.
- `AOI-005`: configurable fixed-tick, percentage, ATR-normalized, and hybrid sizing modes.
- `AOI-006`: multiple AOIs and lifecycle states.
- `AOI-007`: body-close break, wick-penetration tolerance, structural invalidation, and active-leg archival behavior.
- `AOI-008`: Weekly/Daily overlap/confluence metadata without merging source AOIs.
- `AOI-009`: location states from OUTSIDE through ENTRY_WINDOW/MOVED_AWAY.
- `AOI-010`: runtime/API boundaries without recalculating structure or trend in routes.

Verification: covered by backend pytest, ruff, and mypy.

### M30 - AOI Visualization and Strategy-Gate Integration

Implemented AOI as a strategy hard gate and rendered backend-provided AOIs in the frontend.

Implemented scope:

- `AOI-VIS-001` to `AOI-VIS-006`: frontend fetches AOI read endpoints, renders Weekly/Daily AOI bounds, W+D confluence, state controls, replay cursor filtering, and missing-AOI diagnostics without local AOI detection.
- `AOI-GATE-001` to `AOI-GATE-006`: runtime computes symbol-level Weekly/Daily AOI location gate; Entry Signal Engine blocks ENTRY_READY when the gate is missing or ineligible; checklist, scoring, trading intelligence, and mock AI consume typed AOI evidence.

Design notes:

- AOI discovery semantics from M29 are unchanged.
- Demo dry-run mode seeds deterministic active Weekly/Daily AOIs for integration visibility.
- Setup scoring caps trade-ready grades when AOI gate evidence is missing or ineligible.
- Calibration values for production AOI sizing, proximity, and entry-window behavior remain unresolved.

Verification: backend and frontend test coverage added; full verification is required before commit.
