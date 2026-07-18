# Software Requirements Specification (SRS)

## Trading Intelligence Platform

**Document ID:** TIP-SRS-001  
**Version:** 1.0 Draft  
**Owner:** Ali Abbas  
**Purpose:** Define implementation-driving requirements for the Trading Intelligence Platform.

---

## 1. Introduction

### 1.1 Purpose

The Trading Intelligence Platform (TIP) is a modular software system for deterministic market-structure analysis and future AI-assisted trading intelligence.

This SRS defines what the system shall do. It is intended to support implementation, testing, and traceability without becoming excessive documentation.

### 1.2 Scope

Version 1 shall support:

- BitMart USDT-M futures market-data ingestion,
- deterministic candle generation,
- derived 4H / Daily / Weekly timeframes,
- body-based market structure detection,
- trend classification,
- professional visualization,
- replay-compatible processing,
- structured outputs for future AI reasoning.

Version 1 shall not include automated order execution, portfolio automation, cloud deployment, reinforcement learning, or GPU acceleration.

### 1.3 Definitions

| Term | Meaning |
|---|---|
| TIP | Trading Intelligence Platform |
| HH | Higher High |
| HL | Higher Low |
| LH | Lower High |
| LL | Lower Low |
| BOS | Break of Structure |
| OHLCV | Open, High, Low, Close, Volume |
| LLM | Large Language Model |
| UTC | Coordinated Universal Time |
| MarketContext | Canonical analytical object enriched by engines |

---

## 2. System Overview

The platform shall be organized around pipelines and engines.

Pipelines transform data:

- Market Data Pipeline
- Candle Pipeline
- Timeframe Pipeline

Engines analyze and enrich data:

- Market Structure Engine
- Trend Engine
- Visualization Engine
- Replay Engine
- Future AI Decision Engine

The first supported symbol shall be BTCUSDT. The supported visualization timeframes shall be 1W, 1D, 4H, 2H, 1H, 30M, 15M, 5M, and 1M. The architecture shall support future multi-symbol scanning.

---

## 3. Requirement Classification

Requirement IDs use the following prefixes:

| Prefix | Category |
|---|---|
| FR | Functional Requirement |
| NFR | Non-Functional Requirement |
| DATA | Data Requirement |
| UI | User Interface Requirement |
| LOG | Logging Requirement |
| ERR | Error Handling Requirement |
| CFG | Configuration Requirement |
| RUNTIME | Runtime Assembly Requirement |
| DEP | Deployment Requirement |
| TEST | Testing Requirement |
| AI | Artificial Intelligence Requirement |
| ENTRY | Entry Signal Requirement |
| RISK | Risk Requirement |
| CHECKLIST | Checklist Requirement |
| SCORE | Setup Scoring Requirement |
| INTEL | Trading Intelligence Requirement |
| EXCHANGE | Exchange Abstraction Requirement |
| STORAGE | Historical Storage Requirement |
| SYNC | Market Data Synchronization Requirement |

Priorities:

- Mandatory: required for current milestone
- High: required for Version 1
- Medium: soon after Version 1
- Future: planned future capability

---

## 4. Functional Requirements

### 4.1 Market Data Pipeline

#### FR-101 — BitMart Live Stream Foundation

Priority: Mandatory

The platform shall use BitMart USDT-M futures as the sole supported exchange/market data source.
Until BitMart WebSocket ingestion is implemented, live mode shall report that streaming is
foundation-only/unavailable rather than silently using another exchange.

Rationale: Live trade data is the foundation for candle construction.

Acceptance Criteria:

- Runtime and health status report BitMart and USDT-M perpetual market type.
- No Binance runtime, historical, or live fallback is used.
- BitMart live unavailability is reported clearly until implemented.

Milestone: M2

#### FR-102 — Reconnect After Disconnect

Priority: High

The platform shall attempt to reconnect automatically after stream interruption.

Acceptance Criteria:

- Disconnection is detected.
- Reconnection attempt is logged.
- Stream resumes without manual restart where possible.

Milestone: M2

#### FR-103 — Normalize Trade Messages

Priority: Mandatory

The platform shall convert raw exchange messages into a canonical Trade object.

Acceptance Criteria:

- Trade includes symbol, price, quantity, timestamp, and source.
- Invalid messages are rejected or logged.

Milestone: M2

#### FR-104 — Support Multiple Symbols

Priority: Future

The platform shall support live ingestion for multiple symbols.

Milestone: M9

---

### 4.2 Candle Pipeline

#### FR-201 — Construct One-Minute Candles

Priority: Mandatory

The platform shall construct deterministic one-minute OHLCV candles from normalized trade events.

Rationale: One-minute candles are the authoritative base timeframe.

Acceptance Criteria:

- Exactly one candle is produced per UTC minute.
- Open is the first trade price in the minute.
- High is the maximum trade price in the minute.
- Low is the minimum trade price in the minute.
- Close is the last trade price in the minute.
- Volume is accumulated quantity.

Milestone: M3

#### FR-202 — Preserve Wick Values

Priority: Mandatory

The platform shall preserve full candle high and low values for visualization and future SL/TP logic.

Acceptance Criteria:

- Candle high and low are stored.
- Structure logic does not depend on wick values.

Milestone: M3

#### FR-203 — Time-Driven Candle Closure

Priority: Mandatory

The platform shall close candles based on UTC time boundaries, not trade arrival.

Acceptance Criteria:

- Candle closes exactly at the end of its UTC minute.
- Missing-trade minutes are still represented.

Milestone: M3

#### FR-204 — Generate Synthetic Empty Candles

Priority: High

If no trades occur during a minute, the platform shall generate a synthetic candle using the previous close with zero volume.

Milestone: M3

#### FR-205 — Publish Candle Close Events

Priority: Mandatory

The platform shall publish an event when a one-minute candle is finalized.

Milestone: M3

---

### 4.3 Timeframe Pipeline

#### FR-301 — Generate Four-Hour Candles

Priority: High

The platform shall generate 4H candles from one-minute candles.

Milestone: M4

#### FR-302 — Generate Daily Candles

Priority: High

The platform shall generate daily candles from one-minute candles using UTC alignment.

Milestone: M4

#### FR-303 — Generate Weekly Candles

Priority: High

The platform shall generate weekly candles from one-minute candles using UTC alignment.

Milestone: M4

#### FR-304 — Deterministic Higher-Timeframe Aggregation

Priority: Mandatory

Given the same one-minute candle sequence, the platform shall always produce identical higher-timeframe candles.

Milestone: M4

---

### 4.4 Market Structure Engine

#### FR-401 — Calculate Candle Body Values

Priority: Mandatory

The platform shall calculate body high and body low for completed candles.

Acceptance Criteria:

- body_high = max(open, close)
- body_low = min(open, close)

Milestone: M5

#### FR-402 — Ignore Wicks for Structure

Priority: Mandatory

The platform shall not use candle wicks for HH, HL, LH, LL, or BOS calculation.

Milestone: M5

#### FR-403 — Detect HH, HL, LH, LL

Priority: Mandatory

The platform shall detect higher highs, higher lows, lower highs, and lower lows using body-based structure logic.

Milestone: M5

#### FR-404 — Detect Break of Structure

Priority: Mandatory

The platform shall detect body-close break of structure events.

Milestone: M5

#### FR-405 — Support Dynamic Displacement Thresholds

Priority: High

The platform shall support dynamic displacement thresholds for structure detection.

Milestone: M5

---

### 4.5 Trend Engine

#### FR-501 — Determine Trend Per Timeframe

Priority: Mandatory

The platform shall classify the selected timeframe as bullish, bearish, or transition based on structure state.

Milestone: M6

#### FR-502 — Support Weekly, Daily, and 4H Trend States

Priority: High

The platform shall maintain independent trend states for weekly, daily, and 4H timeframes.

Milestone: M6

#### FR-503 — Support Multi-Timeframe Aggregation

Priority: High

The platform shall support both voting and hard-filter modes for future multi-timeframe analysis.

Milestone: M6

---

### 4.6 Visualization Engine

#### FR-601 — Display Candlestick Chart

Priority: High

The platform shall display full OHLC candlesticks including wicks.

Milestone: M7

#### FR-602 — Display Structure Levels

Priority: High

The platform shall display HH, HL, LH, and LL as horizontal color-coded lines with right-aligned text labels.

Milestone: M7

#### FR-603 — Display Trend State

Priority: High

The platform shall display trend state using both background shading and a line/ribbon indicator.

Milestone: M7

#### FR-604 — Display BOS Events

Priority: High

The platform shall display BOS events and allow BOS visibility modes: persistent, auto-clean, and hidden.

Milestone: M7

#### FR-605 — Timeframe Selection

Priority: High

The user shall be able to select a timeframe and view that timeframe's independent structure and trend state.

Milestone: M7

---

### 4.7 Persistence and Replay

#### FR-701 — Store Candles In Memory

Priority: Mandatory

The platform shall maintain recent candle data in memory for fast access.

Milestone: M3

#### FR-702 — Persist One-Minute Candles to Disk

Priority: Mandatory

The platform shall persist one-minute candles to disk in a replay-compatible format.

Milestone: M3

#### FR-801 — Replay Historical Candles

Priority: High

The platform shall replay stored candles through the same analytical pipeline used by live data.

Milestone: M8

#### FR-802 — Live and Replay Consistency

Priority: Mandatory

Given the same candle sequence, live and replay modes shall produce identical analytical outputs.

Milestone: M8

---

### 4.8 Entry Signal Engine

#### ENTRY-001 — Classify Entry State

Priority: High

The platform shall classify each evaluated symbol/timeframe context as one of: WAIT, WATCH, LONG_SETUP, SHORT_SETUP, ENTRY_READY, or INVALIDATED.

Milestone: M21

#### ENTRY-002 — Consume Multi-Timeframe Trend Inputs

Priority: High

The Entry Signal Engine shall consume existing 1W, 1D, 4H, 2H, 1H, and 30M trend outputs without recalculating trend or structure.

Milestone: M21

#### ENTRY-003 — Consume Lower-Timeframe Structure Inputs

Priority: High

The Entry Signal Engine shall consume existing 15M, 5M, and 1M market-structure outputs, including HH, HL, LH, LL, and BOS events.

Milestone: M21

#### ENTRY-004 — Use Candle Body Context

Priority: High

The Entry Signal Engine shall consume latest completed candles and body levels as structured inputs while preserving the rule that market structure is body-based.

Milestone: M21

#### ENTRY-005 — Produce Deterministic Explanations

Priority: High

The Entry Signal Engine shall return deterministic reasons for each state using existing analytical outputs such as trend alignment, BOS presence, structure state, and latest candle/body context.

Milestone: M21

#### ENTRY-006 — No Trade Execution

Priority: Mandatory

The Entry Signal Engine shall not execute trades, calculate position size, place orders, or use AI/LLM output to decide market structure.

Milestone: M21

---

### 4.9 Risk Engine

#### RISK-001 — Build Risk Plan

Priority: High

The platform shall produce a deterministic RiskPlan from an existing Entry DecisionTrace, latest completed candle/body context, structure levels, and BOS events.

Milestone: M22

#### RISK-002 — Determine Entry, Stop, and Target

Priority: High

The Risk Engine shall derive entry price from latest candle/body context, stop loss from relevant structure/invalidation levels, and take profit from a configured risk/reward target when available.

Milestone: M22

#### RISK-003 — Support Long and Short Plans

Priority: High

The Risk Engine shall support deterministic long and short risk plans without changing Entry Signal Engine semantics.

Milestone: M22

#### RISK-004 — Handle Inapplicable or Incomplete Inputs

Priority: High

The Risk Engine shall return NOT_APPLICABLE, INVALID, or INCOMPLETE when entry state, candle context, or invalidation levels do not support a valid risk plan.

Milestone: M22

#### RISK-005 — Produce Risk Evidence

Priority: High

The Risk Engine shall return deterministic reasons/evidence and warnings suitable for future checklist, replay, scoring, and AI explanation layers.

Milestone: M22

#### RISK-006 — No Position Sizing or Execution

Priority: Mandatory

The Risk Engine shall not calculate position size, execute trades, place orders, or use AI/LLM output to decide risk.

Milestone: M22

---

### 4.10 Checklist Engine

#### CHECKLIST-001 — Build Evidence Checklist

Priority: High

The platform shall produce a deterministic checklist from existing Entry DecisionTrace evidence, RiskPlan evidence, multi-timeframe alignment, and runtime/data-quality metadata.

Milestone: M23

#### CHECKLIST-002 — Convert Entry Evidence

Priority: High

The Checklist Engine shall convert entry evidence, missing confirmations, and invalidation evidence into structured checklist items without recalculating entry, structure, BOS, or trend logic.

Milestone: M23

#### CHECKLIST-003 — Convert Risk Evidence

Priority: High

The Checklist Engine shall convert risk evidence, warnings, and risk assessment state into structured risk-validation checklist items without recalculating risk.

Milestone: M23

#### CHECKLIST-004 — Summarize Checklist Status

Priority: High

The Checklist Engine shall produce deterministic pass, fail, warning, and missing counts plus an overall status and summary.

Milestone: M23

#### CHECKLIST-005 — Handle Missing Inputs

Priority: High

The Checklist Engine shall handle missing Entry or Risk inputs gracefully using MISSING or NOT_APPLICABLE checklist items.

Milestone: M23

#### CHECKLIST-006 — No Trading Logic or Execution

Priority: Mandatory

The Checklist Engine shall not calculate candles, structure, BOS, trend, entry, risk, scanner score, AI reasoning, position size, orders, or execution decisions.

Milestone: M23

---

### 4.11 Setup Scoring Engine

#### SCORE-001 — Build Setup Score

Priority: High

The platform shall produce a deterministic weighted setup score from existing Entry DecisionTrace, RiskPlan, ChecklistResult, multi-timeframe alignment, and optional scanner context.

Milestone: M24

#### SCORE-002 — Score Deterministic Components

Priority: High

The Setup Scoring Engine shall score trend alignment, structure/entry confirmation, risk validity/R:R, and checklist status using existing deterministic outputs only.

Milestone: M24

#### SCORE-003 — Penalize Weak or Invalid Context

Priority: High

The Setup Scoring Engine shall penalize invalidated setups, incomplete risk, failed checklist items, warnings, and missing confirmations.

Milestone: M24

#### SCORE-004 — Produce Grade and Summary

Priority: High

The Setup Scoring Engine shall produce total score, max score, percentage, grade, components, warnings, and deterministic summary.

Milestone: M24

#### SCORE-005 — Support API/Runtime Evaluation

Priority: High

The platform shall expose setup-score evaluation through backend runtime/API boundaries when available.

Milestone: M24

#### SCORE-006 — No Recalculation or Execution

Priority: Mandatory

The Setup Scoring Engine shall not calculate candles, structure, BOS, trend, entry, risk, checklist logic, AI reasoning, position size, orders, or execution decisions.

Milestone: M24

---

### 4.12 Trading Intelligence API

#### INTEL-001 — Consolidate Trading Intelligence

Priority: High

The platform shall expose one backend orchestration result containing entry decision, risk plan, checklist result, setup score, AI decision output, and runtime metadata for a symbol.

Milestone: M25

#### INTEL-002 — Preserve Engine Execution Order

Priority: High

Trading intelligence orchestration shall evaluate existing outputs in this order: entry, risk, checklist, setup score, then AI decision.

Milestone: M25

#### INTEL-003 — Reuse Existing Deterministic Engines

Priority: Mandatory

Trading intelligence orchestration shall call existing runtime/engine boundaries and shall not duplicate Entry, Risk, Checklist, Scoring, Scanner, Structure, Trend, or AI logic.

Milestone: M25

#### INTEL-004 — Include AI Decision From Structured Outputs

Priority: High

The AI decision in the consolidated response shall be generated from structured deterministic outputs and existing runtime stores, not raw chart data or recalculated analysis.

Milestone: M25

#### INTEL-005 — Handle Missing Data Gracefully

Priority: High

The consolidated endpoint shall return structured WAIT, NOT_APPLICABLE, MISSING, low-score, or avoid/watch-style outputs when data is missing rather than failing.

Milestone: M25

#### INTEL-006 — No Execution or External Services

Priority: Mandatory

The consolidated Trading Intelligence API shall not execute trades, place orders, add API keys, call external services, integrate a real LLM provider, or implement new trading rules.

Milestone: M25

---

### 4.13 Future AI Decision Engine

#### AI-1001 — Consume Structured Market Context

Priority: Future

The AI Decision Engine shall consume structured MarketContext data rather than raw chart data.

Milestone: M10

#### AI-1002 — Generate Trade Analysis

Priority: Future

The AI Decision Engine shall generate textual analysis of a trade setup based on deterministic inputs.

Milestone: M10

#### AI-1003 — Highlight Risks

Priority: Future

The AI Decision Engine shall identify risks and weaknesses in a proposed trade setup.

Milestone: M10

---

## 5. Non-Functional Requirements

### NFR-001 — Determinism

Priority: Mandatory

Given identical inputs and configuration, the system shall produce identical outputs.

### NFR-002 — Modularity

Priority: Mandatory

The system shall separate pipelines, engines, models, storage, API, and UI concerns.

### NFR-003 — Maintainability

Priority: High

The codebase shall use clear module boundaries, type hints, tests, and documented configuration.

### NFR-004 — Extensibility

Priority: High

The system shall support future migration of selected components to C++ without requiring architectural redesign.

### NFR-005 — Local-First Deployment

Priority: Mandatory

Version 1 shall run on a local development machine.

---

## 6. Data Requirements

### DATA-001 — Trade Model

The system shall define a canonical Trade model containing symbol, price, quantity, timestamp, and source.

### DATA-002 — Candle Model

The system shall define a Candle model containing symbol, timeframe, open_time, close_time, open, high, low, close, and volume.

### DATA-003 — MarketContext Model

The system shall define a MarketContext model for downstream analytical enrichment.

### DATA-004 — Timestamp Standard

All internal timestamps shall use UTC.

---

## 7. Configuration Requirements

### CFG-001 — Version-Controlled Configuration

The platform shall load configurable values from version-controlled configuration files.

### CFG-002 — No Hard-Coded Trading Parameters

Trading and analysis parameters shall not be hard-coded where configuration is practical.

---

## 8. Logging and Diagnostics Requirements

### LOG-001 — Structured Logging

The platform shall produce structured logs for data ingestion, candle construction, storage, engines, and errors.

### LOG-002 — Event Logging

The platform shall log key lifecycle events such as connection, disconnection, candle close, and storage writes.

---

## 9. Error Handling Requirements

### ERR-001 — Network Failure Handling

The system shall detect and log network failures.

### ERR-002 — Invalid Message Handling

The system shall detect invalid external messages and prevent them from corrupting internal state.

### ERR-003 — Storage Failure Handling

The system shall log persistence failures and avoid silent data loss.

---

## 10. Deployment Requirements

### DEP-001 — Local Backend Runtime

The backend shall run locally during Version 1 development.

### DEP-002 — Local Frontend Runtime

The frontend shall run locally during Version 1 development.

### DEP-003 — Repository-Based Project Memory

The repository shall contain enough context for Codex or another developer to continue the project without relying on chat history.

---

## 11. Runtime Assembly Requirements

### RUNTIME-001 — Application Orchestrator

Priority: Mandatory

The platform shall provide a local backend application orchestrator that assembles existing components into a runnable process.

Milestone: M11

### RUNTIME-002 — Component Wiring

Priority: Mandatory

The orchestrator shall use existing configuration, logging, event bus, storage, pipelines, engines, replay components, scanner components, AI decision components, and read API boundaries where applicable.

Milestone: M11

### RUNTIME-003 — Lifecycle Management

Priority: Mandatory

The local backend application shall expose a clean lifecycle with start and stop operations.

Milestone: M11

### RUNTIME-004 — Health and Status Reporting

Priority: High

The local backend application shall expose health/status information for assembled components.

Milestone: M11

### RUNTIME-005 — Dry-Run or Replay-Friendly Local Mode

Priority: High

The local backend application shall support a dry-run or replay-friendly local mode that does not require live BitMart streaming.

Milestone: M11

M11 shall not add new trading logic. It shall assemble and coordinate existing components only.

---

## 11A. Weekly/Daily Area of Interest Requirements

### AOI-001 - Active Structure Leg Input

The AOI engine shall consume precomputed Weekly/Daily structure and trend outputs. Bullish
search ranges are active HL-to-HH legs; bearish search ranges are active LH-to-LL legs. It
shall not recalculate structure or trend.

### AOI-002 - Timeframe Scope

The platform shall create AOIs only for Weekly and Daily timeframes in this milestone.

### AOI-003 - Historical Body Interactions

An AOI candidate shall be formed from candle-body range overlaps inside the active structure
leg. Wick-only historical contacts shall not count.

### AOI-004 - Confirmation and Replay Safety

A candidate shall require at least three qualifying body interactions to become confirmed.
The first-touch and third-touch confirmation timestamps shall be stored separately, and the
candidate shall not be tradable before confirmation.

### AOI-005 - Configurable Sizing and Ranking

AOI sizing shall support fixed-tick, percentage, ATR-normalized, and hybrid modes without a
hardcoded crypto equivalent of the source strategy's forex pip range. Candidate ranking shall
deterministically prefer body closes, body touches, reactions, narrower zones, and recency
using configurable weights.

### AOI-006 - Multiple AOIs and Lifecycle

Multiple AOIs may coexist within one active structure leg. AOIs shall support candidate,
confirmed, active, broken, retest-pending, structurally-invalidated, and archived states.

### AOI-007 - Invalidation Rules

Wick penetration shall not invalidate an AOI. One candle-body close beyond the far boundary
shall mark it broken; no two-close rule shall be invented. Trend changes shall structurally
invalidate old AOIs, while active-leg replacement shall archive them for historical context.

### AOI-008 - Weekly/Daily Confluence

The engine shall detect partial and full Weekly/Daily AOI intersections while preserving the
source AOIs as separate objects and returning explicit confluence metadata.

### AOI-009 - Location Gate

The engine shall classify live AOI location as OUTSIDE, APPROACHING, INSIDE, REACTING,
ENTRY_WINDOW, or MOVED_AWAY. Established-zone contact may use the full candle range, while
proximity and post-reaction excursion remain configurable.

### AOI-010 - Runtime and API Boundary

The runtime/API may evaluate and read AOIs and location state, but routes shall remain
transport-only and existing entry, risk, scoring, structure, and trend semantics shall not
change in this milestone.

## 11B. AOI Visualization and Strategy Gate Requirements

### AOI-VIS-001 - Render Weekly and Daily AOIs

The frontend shall render backend-provided Weekly and Daily AOIs on all supported chart
timeframes with distinct labels and styles. It shall not calculate AOIs locally.

### AOI-VIS-002 - Render AOI Bounds and Confirmation Timing

AOI visualization shall use backend lower/upper bounds, first-touch time, confirmation
time, state, direction, ranking metadata, and active/current-leg metadata.

### AOI-VIS-003 - Render Weekly/Daily Confluence

The frontend shall preserve Weekly and Daily AOIs as separate objects and may render their
backend-provided intersection as W+D confluence.

### AOI-VIS-004 - Provide AOI Display Controls

The frontend shall provide controls for AOI visibility, Weekly visibility, Daily visibility,
overlap visibility, and active/broken/all state filtering.

### AOI-VIS-005 - Replay-Safe AOI Display

Replay visualization shall hide AOIs whose first-touch or confirmation timestamp is later
than the replay cursor.

### AOI-VIS-006 - AOI Readiness Diagnostics

The UI shall show clear messaging when Weekly/Daily AOI inputs are not ready or no eligible
AOIs are available.

### AOI-GATE-001 - Weekly/Daily AOI Location Hard Gate

The Entry Signal Engine shall require price to be inside, touching, reacting from, or within
the configured entry window of an active Weekly or Daily AOI before returning ENTRY_READY.

### AOI-GATE-002 - Gate Before Lower-Timeframe Entry Readiness

If the Weekly/Daily AOI location gate is not eligible, entry evaluation shall return WAIT
with direction NONE and typed AOI evidence before lower-timeframe entry readiness is allowed.

### AOI-GATE-003 - Typed AOI Evidence

Entry decisions shall expose typed AOI evidence for active Weekly AOI, active Daily AOI,
Weekly/Daily overlap, inside/reacting/entry-window location, moved-away, not-eligible, and
missing AOI data cases.

### AOI-GATE-004 - Downstream AOI Consumption

Checklist, setup scoring, trading intelligence, and mock AI decisions shall consume AOI gate
evidence and shall not duplicate AOI discovery or market-structure logic.

### AOI-GATE-005 - Scoring Hard-Gate Protection

Setup scoring shall not return a trade-ready A/B setup when the AOI location gate is missing
or ineligible.

### AOI-GATE-006 - Scope Boundaries

The AOI gate shall not change AOI discovery semantics, market structure detection, trend
classification, risk rules, order execution, BitMart synchronization, or real LLM behavior.

## 11C. Exchange Abstraction and Market Data Synchronization Requirements

### EXCHANGE-001 - Exchange-Agnostic Market Data Interface

The platform shall expose a generic public market-data adapter interface for contract
discovery, historical candle fetching, latest completed candle time, symbol normalization,
contract metadata, and rate-limit metadata.

### EXCHANGE-002 - BitMart USDT-M Adapter Foundation

The platform shall include a BitMart public futures adapter foundation for active USDT-M
perpetual contracts without private/account/order APIs or API keys.

### EXCHANGE-003 - Contract Metadata Normalization

Exchange adapters shall normalize exchange-specific contract responses into generic
ContractMetadata including canonical symbol, assets, market type, status, tick/step sizes,
listing time, perpetual/active flags, and metadata timestamp.

### EXCHANGE-004 - Exchange DTO Isolation

Downstream candle, structure, trend, AOI, scanner, entry, risk, checklist, scoring, and AI
code shall not depend on BitMart-specific DTOs.

### EXCHANGE-005 - Historical Candle Pagination

Adapters shall fetch historical completed 1m candles using deterministic pagination,
deduplication, current-candle exclusion, retry hooks, and injectable transports for tests.

### EXCHANGE-006 - BitMart-Only Active Exchange

BitMart USDT-M futures shall be the only configured and active exchange/market. Historical,
sync, runtime, health, and CLI paths shall not silently fall back to Binance or mix Binance
cache data with BitMart data.

### STORAGE-001 - Canonical 1m History Store

The platform shall treat completed one-minute candles as the canonical stored historical
source for synchronization.

### STORAGE-002 - Higher Timeframes Derived Internally

The platform shall not download all higher timeframes separately for synchronization; 5m,
15m, 30m, 1h, 2h, 4h, 1d, and 1w shall remain derived from canonical 1m candles.

### STORAGE-003 - Idempotent Upsert and Deduplication

Historical storage shall upsert/deduplicate by exchange, symbol, timeframe, and open time.

### STORAGE-004 - Range Queries and Counts

Historical storage shall support first/last stored timestamp, range query, and candle count
operations.

### STORAGE-005 - Gap Detection

Historical storage shall detect missing one-minute intervals for a symbol/time range.

### STORAGE-006 - Future Backend Compatibility

The storage boundary shall preserve JSONL compatibility while allowing future Parquet or
DuckDB implementations.

### SYNC-001 - Incremental Startup Planning

The synchronization planner shall download only missing completed 1m candles on startup.

### SYNC-002 - Initial Backfill Horizon

Initial backfill shall start at the configured history horizon or contract listing time,
whichever is later.

### SYNC-003 - Catch-Up Planning

For existing local data, catch-up shall start from last local completed open time plus one
minute and end at the latest fully completed remote minute.

### SYNC-004 - Gap Repair Planning

The planner shall support explicit gap-repair intervals using detected missing 1m candles.

### SYNC-005 - Persistent Checkpoints

Synchronization metadata shall persist exchange, market type, symbol, candle bounds,
remote latest completed time, state, progress, retries, errors, gaps, and readiness state.

### SYNC-006 - Restartable and Idempotent

Synchronization shall be restartable and idempotent; interrupted work shall resume from
stored history/checkpoints without redownloading the full horizon.

### SYNC-007 - Bounded Coordinator

The coordinator shall queue jobs with deterministic priority and bounded concurrency rather
than launching unbounded per-symbol tasks.

### SYNC-008 - Isolated Failures and Retries

One-symbol failures shall not stop synchronization for other symbols; retry/backoff hooks
shall be deterministic and bounded.

### SYNC-009 - Runtime Integration

BackendRuntime shall optionally start synchronization in the background, stop it cleanly,
avoid demo seeding in sync mode, and expose sync health/status.

### SYNC-010 - Sync API and Observability

The API shall expose read/control endpoints for contracts, aggregate status, per-symbol
status, start, symbol sync, and gap repair.

### SYNC-011 - Structured Logging

Synchronization shall log catalogue refresh, job execution, checkpoint updates, ready
symbols, gap repair, retries, and failures without noisy per-candle INFO logging.

### SYNC-012 - Scanner Readiness Boundary

Scanner universe selection shall be able to include only symbols marked READY; non-ready
symbols shall not be considered fully scanner-eligible.

---

## 12. Testing Requirements

### TEST-001 — Unit Tests

Deterministic components shall have unit tests where practical.

### TEST-002 — Replay Tests

Replay tests shall verify live/replay consistency for market processing logic.

### TEST-003 — Data Integrity Tests

Candle continuity, duplicate prevention, and timestamp alignment shall be testable.

---

## 13. Milestones

| Milestone | Requirements | Goal |
|---|---|---|
| M1 | DEP-003, CFG-001, LOG-001, TEST-001 | Repository foundation |
| M2 | FR-101 to FR-104 | Market data pipeline |
| M3 | FR-201 to FR-205, FR-701, FR-702 | Candle pipeline |
| M4 | FR-301 to FR-304 | Timeframe pipeline |
| M5 | FR-401 to FR-405 | Market structure engine |
| M6 | FR-501 to FR-503 | Trend engine |
| M7 | FR-601 to FR-605 | Visualization platform |
| M8 | FR-801 to FR-802 | Replay engine |
| M9 | FR-104 | Multi-symbol scanner |
| M10 | AI-1001 to AI-1003 | AI decision engine |
| M11 | RUNTIME-001 to RUNTIME-005 | Runtime assembly |
| M21 | ENTRY-001 to ENTRY-006 | Entry signal engine |
| M22 | RISK-001 to RISK-006 | Risk engine |
| M23 | CHECKLIST-001 to CHECKLIST-006 | Checklist engine |
| M24 | SCORE-001 to SCORE-006 | Setup scoring engine |
| M25 | INTEL-001 to INTEL-006 | Trading intelligence API consolidation |
| M29 | AOI-001 to AOI-010 | Weekly/Daily AOI engine foundation |
| M30 | AOI-VIS-001 to AOI-VIS-006, AOI-GATE-001 to AOI-GATE-006 | AOI visualization and strategy-gate integration |
| M31 | EXCHANGE-001 to EXCHANGE-006, STORAGE-001 to STORAGE-006, SYNC-001 to SYNC-012 | Exchange abstraction and market data synchronization foundation |

---

## 14. Acceptance Criteria Summary

Version 1 shall be considered successful when the platform can:

1. Receive live BTCUSDT trade data.
2. Build deterministic one-minute candles.
3. Persist candles to disk.
4. Generate 4H, Daily, and Weekly candles.
5. Detect body-based market structure.
6. Classify selected timeframe trend.
7. Display candles with wicks.
8. Display HH, HL, LH, LL, BOS, and trend state.
9. Replay stored data through the same logic.
10. Preserve enough documentation and context for Codex-driven development.
