# Software Requirements Specification (SRS)

## Trading Intelligence Platform (TIP)

**Document ID:** TIP-SRS-001  
**Version:** 1.0  
**Status:** Draft  
**Owner:** Ali Abbas  
**Purpose:** Define the functional and non-functional requirements of the Trading Intelligence Platform and provide an implementation roadmap.

---

## Document Control

| Field | Value |
|---|---|
| Project | Trading Intelligence Platform |
| Document | Software Requirements Specification |
| Document ID | TIP-SRS-001 |
| Version | 1.0 |
| Status | Draft |
| Classification | Internal |
| Owner | Ali Abbas |

---

## Revision History

| Version | Date | Description |
|---|---|---|
| 1.0 | TBD | Initial implementation-focused SRS |

---

## 1. Introduction

### 1.1 Purpose

The Trading Intelligence Platform (TIP) is a modular software platform for deterministic market analysis. Version 1 focuses on live cryptocurrency data ingestion, deterministic candle generation, multi-timeframe market structure analysis, trend classification, professional visualization, replay compatibility, and future AI-assisted reasoning.

This document defines what the platform must do. Architecture details belong in the Software Architecture Document (SAD). Trading mathematics belong in the Research & Algorithm Specification (RAS). Development standards belong in the Developer Design Guide (DDG). Major design decisions are recorded in Architecture Decision Records (ADR).

### 1.2 Scope

Version 1 includes BitMart USDT-M market data, trade aggregation, 1-minute candle generation, higher timeframe generation, market structure detection, trend detection, local deployment, structured logging, persistence, replay compatibility, and real-time visualization.

Version 1 excludes automated trade execution, broker integration, portfolio optimisation, cloud deployment, user authentication, reinforcement learning, GPU acceleration, and HFT-level optimisation.

### 1.3 Business Objectives

| ID | Objective |
|---|---|
| BO-001 | Provide deterministic market analysis with repeatable outputs. |
| BO-002 | Reduce subjective chart interpretation using objective structure. |
| BO-003 | Provide professional analytical tooling for discretionary and quantitative traders. |
| BO-004 | Generate reusable data for future AI and quantitative research. |
| BO-005 | Maintain architecture that can evolve into a multi-symbol and AI-assisted platform. |

### 1.4 Definitions

| Term | Definition |
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
| MarketContext | Canonical structured object enriched by downstream engines. |

### 1.5 Requirement Format

Each requirement includes an ID, priority, requirement statement, rationale, dependencies, acceptance criteria, verification method, and milestone.

Priorities: Mandatory, High, Medium, Future.

---

## 2. System Overview

TIP shall be implemented as a collection of processing pipelines and analytical engines.

Processing pipelines transform data: Market Data Pipeline, Candle Pipeline, Timeframe Pipeline.

Analytical engines analyse and enrich data: Market Structure Engine, Trend Engine, Visualization Engine, and future Entry, Risk, Checklist, Scoring, Scanner, and AI Decision Engines.

The system shall be live-first and replay-compatible. Live and replay modes must produce identical analytical outputs when supplied with the same candle sequence.

---

## 3. Assumptions and Constraints

### Assumptions

| ID | Assumption |
|---|---|
| AS-001 | BitMart USDT-M public market data is available. |
| AS-002 | BTC/USDT is the first supported symbol. |
| AS-003 | All internal timestamps use UTC. |
| AS-004 | Users understand basic market structure concepts. |

### Constraints

| ID | Constraint |
|---|---|
| CON-001 | Market structure must use completed candles only. |
| CON-002 | HH, HL, LH, LL, and BOS must be calculated from candle bodies only. |
| CON-003 | Candle wicks must be preserved for visualization and future SL/TP logic. |
| CON-004 | The platform must not depend on exchange or TradingView charts for overlays. |
| CON-005 | AI components must consume structured analytical outputs, not raw ambiguous chart data. |

---

## 4. Functional Requirements

### 4.1 FR-100 Market Data Pipeline

#### FR-101 — BitMart Market Data Foundation
Priority: Mandatory  
Requirement: The platform shall use BitMart USDT-M futures market data for supported symbols.  
Rationale: Live trade data is the source of all downstream analysis.  
Dependencies: None  
Acceptance Criteria: Connection is established and real-time trade messages are received.  
Verification: Integration test, live smoke test  
Milestone: M2

#### FR-102 — Automatic Reconnection
Priority: Mandatory  
Requirement: The platform shall automatically attempt reconnection after WebSocket interruption.  
Rationale: Live analysis requires resilience against network instability.  
Dependencies: FR-101  
Acceptance Criteria: Disconnection is logged and reconnection is attempted without manual restart.  
Verification: Fault injection test  
Milestone: M2

#### FR-103 — Validate Incoming Trade Messages
Priority: Mandatory  
Requirement: The platform shall validate incoming trade messages before processing.  
Rationale: Invalid data must not corrupt candles or analytical state.  
Dependencies: FR-101  
Acceptance Criteria: Malformed messages are rejected and logged.  
Verification: Unit test  
Milestone: M2

#### FR-104 — Normalize Trade Events
Priority: Mandatory  
Requirement: The platform shall normalize raw exchange messages into a canonical Trade model.  
Rationale: Downstream components should not depend on exchange-specific schemas.  
Dependencies: FR-103  
Acceptance Criteria: Each valid message produces a Trade object with symbol, price, quantity, and UTC timestamp.  
Verification: Unit test  
Milestone: M2

#### FR-105 — Publish Trade Events
Priority: Mandatory  
Requirement: The platform shall publish normalized trade events to downstream components.  
Rationale: Pipelines must remain decoupled.  
Dependencies: FR-104  
Acceptance Criteria: Candle Pipeline receives normalized trades in real time.  
Verification: Integration test  
Milestone: M2

#### FR-106 — Support Historical Download Mode
Priority: High  
Requirement: The platform shall support downloading historical market data for replay and validation.  
Rationale: Replay and backtesting require historical data.  
Dependencies: FR-104  
Acceptance Criteria: Historical data can be loaded into the same downstream pipeline as live data.  
Verification: Integration test  
Milestone: M8

---

### 4.2 FR-200 Candle Pipeline

#### FR-201 — Generate One-Minute Candles
Priority: Mandatory  
Requirement: The platform shall construct deterministic one-minute OHLCV candles from normalized trade events.  
Rationale: One-minute candles are the authoritative base representation for all higher timeframes.  
Dependencies: FR-105  
Acceptance Criteria: Exactly one candle is produced for each UTC minute.  
Verification: Unit test, replay test  
Milestone: M3

#### FR-202 — Maintain Correct OHLC Values
Priority: Mandatory  
Requirement: The platform shall calculate open, high, low, and close values from all trades within each candle period.  
Rationale: Accurate candles are required for both visualization and analysis.  
Dependencies: FR-201  
Acceptance Criteria: OHLC values match expected values for known trade sequences.  
Verification: Unit test  
Milestone: M3

#### FR-203 — Maintain Volume
Priority: Mandatory  
Requirement: The platform shall accumulate traded quantity as candle volume.  
Rationale: Volume is required for future scoring and analysis.  
Dependencies: FR-201  
Acceptance Criteria: Candle volume equals the sum of trade quantities in the candle period.  
Verification: Unit test  
Milestone: M3

#### FR-204 — Preserve Wick Values
Priority: Mandatory  
Requirement: The platform shall preserve high and low wick values in candle data.  
Rationale: Wicks are required for charting and future SL/TP logic even though structure uses bodies only.  
Dependencies: FR-202  
Acceptance Criteria: Candle high and low reflect full traded extremes.  
Verification: Unit test  
Milestone: M3

#### FR-205 — Close Candles by UTC Time Boundary
Priority: Mandatory  
Requirement: The platform shall close candles using time-driven UTC boundaries rather than waiting for next-trade arrival.  
Rationale: Time-driven closure guarantees continuity even during quiet markets.  
Dependencies: FR-201  
Acceptance Criteria: Candles close exactly at UTC minute boundaries.  
Verification: Unit test, live test  
Milestone: M3

#### FR-206 — Generate Synthetic Candles
Priority: Mandatory  
Requirement: If no trades occur during a candle period, the platform shall generate a synthetic zero-volume candle using the previous close.  
Rationale: Missing candles break timeframe aggregation and replay consistency.  
Dependencies: FR-205  
Acceptance Criteria: No timestamp gaps occur during quiet periods.  
Verification: Unit test  
Milestone: M3

#### FR-207 — Prevent Duplicate Candles
Priority: Mandatory  
Requirement: The platform shall prevent duplicate candles for the same symbol and open time.  
Rationale: Duplicate candles corrupt state and storage.  
Dependencies: FR-201  
Acceptance Criteria: Duplicate candle writes are rejected or ignored.  
Verification: Unit test  
Milestone: M3

#### FR-208 — Publish Candle Close Events
Priority: Mandatory  
Requirement: The platform shall publish a candle close event after a candle is finalized.  
Rationale: Analytical engines must only process completed candles.  
Dependencies: FR-205  
Acceptance Criteria: Downstream pipelines receive candle close events only after candle finalization.  
Verification: Integration test  
Milestone: M3

---

### 4.3 FR-300 Timeframe Pipeline

#### FR-301 — Generate 4H Candles
Priority: Mandatory  
Requirement: The platform shall generate 4-hour candles from authoritative one-minute candles.  
Rationale: The 4H timeframe is required for structure analysis and trade filtering.  
Dependencies: FR-201  
Acceptance Criteria: 4H candles align to UTC 4-hour boundaries.  
Verification: Unit test  
Milestone: M4

#### FR-302 — Generate Daily Candles
Priority: Mandatory  
Requirement: The platform shall generate daily candles from authoritative one-minute candles.  
Rationale: Daily trend is required for multi-timeframe analysis.  
Dependencies: FR-201  
Acceptance Criteria: Daily candles align to UTC daily boundaries.  
Verification: Unit test  
Milestone: M4

#### FR-303 — Generate Weekly Candles
Priority: Mandatory  
Requirement: The platform shall generate weekly candles from authoritative one-minute candles.  
Rationale: Weekly trend is required for macro trend filtering and voting.  
Dependencies: FR-201  
Acceptance Criteria: Weekly candles align to configured UTC weekly boundaries.  
Verification: Unit test  
Milestone: M4

#### FR-304 — Deterministic Aggregation
Priority: Mandatory  
Requirement: Higher timeframe candles generated from the same one-minute candles shall always be identical.  
Rationale: Replay compatibility requires deterministic aggregation.  
Dependencies: FR-301, FR-302, FR-303  
Acceptance Criteria: Live and replay aggregation produce identical results.  
Verification: Replay test  
Milestone: M4

---

### 4.4 FR-400 Market Structure Engine

#### FR-401 — Calculate Candle Body Values
Priority: Mandatory  
Requirement: The platform shall calculate body high and body low from candle open and close.  
Rationale: Structure analysis is based on candle bodies only.  
Dependencies: FR-201  
Acceptance Criteria: Body high equals max(open, close) and body low equals min(open, close).  
Verification: Unit test  
Milestone: M5

#### FR-402 — Exclude Wicks from Structure Calculations
Priority: Mandatory  
Requirement: The platform shall not use candle high or candle low values for HH, HL, LH, LL, or BOS calculations.  
Rationale: Wicks are reserved for visualization and future SL/TP analysis.  
Dependencies: FR-401  
Acceptance Criteria: Wick-only breaches do not trigger structure changes.  
Verification: Unit test  
Milestone: M5

#### FR-403 — Support Dynamic Displacement Thresholds
Priority: Mandatory  
Requirement: The platform shall support dynamic displacement thresholds for swing detection.  
Rationale: Structure points must represent meaningful elbows rather than minor noise.  
Dependencies: FR-401  
Acceptance Criteria: Threshold mode can be configured as percentage, ATR-based, or hybrid.  
Verification: Unit test  
Milestone: M5

#### FR-404 — Detect Swing Points
Priority: Mandatory  
Requirement: The platform shall detect valid swing highs and swing lows using configured displacement logic.  
Rationale: HH, HL, LH, and LL labels depend on valid swing points.  
Dependencies: FR-403  
Acceptance Criteria: Known price sequences produce expected swing points.  
Verification: Unit test, replay test  
Milestone: M5

#### FR-405 — Detect HH, HL, LH, LL
Priority: Mandatory  
Requirement: The platform shall classify confirmed swing points as HH, HL, LH, or LL.  
Rationale: These labels form the core market structure output.  
Dependencies: FR-404  
Acceptance Criteria: Known swing sequences produce expected labels.  
Verification: Unit test  
Milestone: M5

#### FR-406 — Detect BOS
Priority: Mandatory  
Requirement: The platform shall detect Break of Structure events based on completed candle body closes.  
Rationale: BOS defines structural trend invalidation and transition.  
Dependencies: FR-405  
Acceptance Criteria: Body close beyond the relevant structure level triggers BOS; wick-only breaks do not.  
Verification: Unit test  
Milestone: M5

#### FR-407 — Support BOS Confirmation Modes
Priority: High  
Requirement: The platform shall support immediate and confirmed BOS/trend-flip modes.  
Rationale: Strategy testing requires both aggressive and conservative interpretations.  
Dependencies: FR-406  
Acceptance Criteria: Configuration switches between immediate flip and confirmation-required mode.  
Verification: Unit test  
Milestone: M5

---

### 4.5 FR-500 Trend Engine

#### FR-501 — Determine Timeframe Trend
Priority: Mandatory  
Requirement: The platform shall determine bullish, bearish, or transition trend state for any selected timeframe.  
Rationale: Timeframe-independent trend detection is required for checklist and visualization.  
Dependencies: FR-405, FR-406  
Acceptance Criteria: The engine returns trend state for 4H, daily, and weekly candles independently.  
Verification: Unit test, replay test  
Milestone: M6

#### FR-502 — Support Multi-Timeframe Trend Inputs
Priority: Mandatory  
Requirement: The platform shall provide weekly, daily, and 4H trend states for multi-timeframe analysis.  
Rationale: User strategy depends on multi-timeframe trend alignment.  
Dependencies: FR-501  
Acceptance Criteria: The system exposes all three trend states for BTC/USDT.  
Verification: Integration test  
Milestone: M6

#### FR-503 — Support Voting and Hard-Filter Modes
Priority: High  
Requirement: The platform shall support both majority-voting and weekly-hard-filter aggregation modes.  
Rationale: Both methods are required for research and comparison.  
Dependencies: FR-502  
Acceptance Criteria: Aggregation mode is configurable and produces expected direction outputs.  
Verification: Unit test  
Milestone: M6

---

### 4.6 FR-600 Visualization Engine

#### FR-601 — Display Candlestick Chart
Priority: Mandatory  
Requirement: The platform shall display OHLC candlesticks including wicks.  
Rationale: Wicks are required for visual interpretation and future SL/TP analysis.  
Dependencies: FR-201  
Acceptance Criteria: Chart displays full candles with open, high, low, and close values.  
Verification: UI test  
Milestone: M7

#### FR-602 — Display Structure Levels
Priority: Mandatory  
Requirement: The platform shall display HH, HL, LH, and LL as horizontal color-coded lines with right-aligned labels.  
Rationale: This matches the desired visual workflow.  
Dependencies: FR-405  
Acceptance Criteria: Structure levels are rendered at correct price and time.  
Verification: UI test  
Milestone: M7

#### FR-603 — Display BOS Events
Priority: Mandatory  
Requirement: The platform shall display BOS events with configurable persistence.  
Rationale: Users require control over chart clutter and historical visibility.  
Dependencies: FR-406  
Acceptance Criteria: BOS can be hidden, auto-cleared, or shown persistently.  
Verification: UI test  
Milestone: M7

#### FR-604 — Display Trend State
Priority: Mandatory  
Requirement: The platform shall display trend state using both background shading and a line/ribbon indicator.  
Rationale: The user requires both visual trend modes.  
Dependencies: FR-501  
Acceptance Criteria: Bullish, bearish, and transition states are visually distinguishable.  
Verification: UI test  
Milestone: M7

#### FR-605 — Support Timeframe Selection
Priority: Mandatory  
Requirement: The platform shall allow the user to select a timeframe and view structure/trend for that timeframe independently.  
Rationale: The checklist requires timeframe-independent engine output.  
Dependencies: FR-501, FR-601  
Acceptance Criteria: Changing timeframe updates candles, structure, and trend outputs.  
Verification: UI test  
Milestone: M7

---

### 4.7 FR-700 Persistence

#### FR-701 — Store Recent Data In Memory
Priority: Mandatory  
Requirement: The platform shall maintain recent candles and analysis state in memory.  
Rationale: Real-time UI and engines require fast access to recent state.  
Dependencies: FR-201  
Acceptance Criteria: Recent candle history can be retrieved without disk access.  
Verification: Unit test  
Milestone: M3

#### FR-702 — Persist Candles to Disk
Priority: Mandatory  
Requirement: The platform shall persist one-minute candles to disk.  
Rationale: Persistence is required for replay, debugging, and research.  
Dependencies: FR-201  
Acceptance Criteria: Closed candles are written to persistent storage.  
Verification: Integration test  
Milestone: M3

#### FR-703 — Support Append-Only Writes
Priority: High  
Requirement: Candle persistence shall be append-oriented and avoid destructive overwrites.  
Rationale: Market data history must remain auditable.  
Dependencies: FR-702  
Acceptance Criteria: New candles append to existing history without corrupting prior data.  
Verification: Integration test  
Milestone: M3

---

### 4.8 FR-800 Replay Engine

#### FR-801 — Replay Historical Candles
Priority: Mandatory  
Requirement: The platform shall replay historical candle sequences through the same analytical pipeline as live data.  
Rationale: Replay is required for debugging and backtesting.  
Dependencies: FR-702  
Acceptance Criteria: Historical candles can be streamed through the platform in chronological order.  
Verification: Replay test  
Milestone: M8

#### FR-802 — Support Step Mode
Priority: High  
Requirement: The platform shall support stepping through replay one candle at a time.  
Rationale: Step mode is required for debugging FSM and structure transitions.  
Dependencies: FR-801  
Acceptance Criteria: User can advance replay by one candle.  
Verification: UI/integration test  
Milestone: M8

#### FR-803 — Ensure Live-Replay Consistency
Priority: Mandatory  
Requirement: Live and replay modes shall produce identical analysis for identical candle sequences.  
Rationale: Determinism is foundational to the platform.  
Dependencies: FR-801, FR-501  
Acceptance Criteria: Regression test confirms identical outputs.  
Verification: Regression test  
Milestone: M8

---

### 4.9 FR-900 Multi-Symbol Scanner

#### FR-901 — Support Multi-Symbol Analysis
Priority: Future  
Requirement: The platform shall support analysis of multiple BitMart USDT-M symbols.  
Rationale: The long-term goal is to scan all pairs for high-quality setups.  
Dependencies: FR-101, FR-501  
Acceptance Criteria: Multiple symbols can run independent pipelines.  
Verification: Integration test  
Milestone: M9

#### FR-902 — Rank Setups
Priority: Future  
Requirement: The platform shall rank symbols by setup quality.  
Rationale: Ranking helps identify high-quality opportunities.  
Dependencies: FR-901  
Acceptance Criteria: Symbols are sortable by a computed setup score.  
Verification: Integration test  
Milestone: M9

---

### 4.10 FR-1000 AI Decision Engine

#### FR-1001 — Consume Structured MarketContext
Priority: Future  
Requirement: The AI Decision Engine shall consume structured MarketContext objects rather than raw chart data.  
Rationale: LLM reasoning should be based on deterministic facts.  
Dependencies: FR-501, FR-902  
Acceptance Criteria: AI input contains structure, trend, risk, checklist, and scoring fields.  
Verification: Unit test  
Milestone: M10

#### FR-1002 — Generate Trade Analysis
Priority: Future  
Requirement: The AI Decision Engine shall generate human-readable trade analysis.  
Rationale: The AI should assist decision-making by explaining setup quality and risk.  
Dependencies: FR-1001  
Acceptance Criteria: AI output includes reasons, risks, and recommendation.  
Verification: Manual review, regression prompts  
Milestone: M10

---

## 5. Non-Functional Requirements

| ID | Priority | Requirement | Verification |
|---|---|---|---|
| NFR-001 | Mandatory | The system shall be deterministic for identical input sequences. | Regression test |
| NFR-002 | Mandatory | The system shall be modular and organized around independent pipelines and engines. | Architecture review |
| NFR-003 | High | The system shall support future replacement of analytical engines without redesigning unrelated components. | Architecture review |
| NFR-004 | Mandatory | The system shall process BTC/USDT live data with less than one-second UI update delay under normal local conditions. | Performance test |
| NFR-005 | High | The system shall be maintainable using typed, documented, testable code. | Code review |
| NFR-006 | High | The system shall support future migration of selected engines to C++ without changing user-facing behaviour. | Architecture review |

---

## 6. Data Requirements

| ID | Requirement |
|---|---|
| DATA-001 | The Trade model shall include symbol, price, quantity, and UTC timestamp. |
| DATA-002 | The Candle model shall include symbol, timeframe, open time, close time, open, high, low, close, and volume. |
| DATA-003 | The platform shall preserve wick values in Candle data. |
| DATA-004 | The platform shall derive body high and body low from open and close. |
| DATA-005 | The MarketContext object shall act as the canonical structured analytical object for downstream engines. |
| DATA-006 | Persistent candle data shall be usable for replay and research. |

---

## 7. User Interface Requirements

| ID | Requirement |
|---|---|
| UI-001 | The UI shall display real-time candlestick charts. |
| UI-002 | The UI shall allow timeframe selection. |
| UI-003 | The UI shall display HH, HL, LH, and LL as horizontal right-labelled lines. |
| UI-004 | The UI shall provide toggles for BOS display. |
| UI-005 | The UI shall display trend background shading. |
| UI-006 | The UI shall display a trend line or ribbon indicator. |
| UI-007 | The UI shall support future scanner and AI analysis panels. |

---

## 8. Configuration Requirements

| ID | Requirement |
|---|---|
| CFG-001 | The platform shall load runtime configuration from version-controlled configuration files. |
| CFG-002 | The platform shall allow configuration of symbols. |
| CFG-003 | The platform shall allow configuration of displacement mode. |
| CFG-004 | The platform shall allow configuration of BOS confirmation mode. |
| CFG-005 | The platform shall allow configuration of visualization toggles. |
| CFG-006 | The platform shall allow configuration of logging level. |

---

## 9. Logging and Diagnostics Requirements

| ID | Requirement |
|---|---|
| LOG-001 | The platform shall log startup and shutdown events. |
| LOG-002 | The platform shall log WebSocket connection state. |
| LOG-003 | The platform shall log candle close events. |
| LOG-004 | The platform shall log rejected or malformed data. |
| LOG-005 | The platform shall log engine errors with enough context to diagnose the issue. |
| LOG-006 | The platform shall support separate logs for data, engine, storage, and UI-related events. |

---

## 10. Error Handling Requirements

| ID | Requirement |
|---|---|
| ERR-001 | The platform shall handle WebSocket disconnections without crashing. |
| ERR-002 | The platform shall reject invalid trade messages. |
| ERR-003 | The platform shall handle storage write failures gracefully. |
| ERR-004 | The platform shall not process incomplete candles in analytical engines. |
| ERR-005 | The platform shall surface critical runtime errors in logs. |

---

## 11. Deployment Requirements

| ID | Requirement |
|---|---|
| DEP-001 | Version 1 shall run on a local development machine. |
| DEP-002 | Backend and frontend shall be runnable independently. |
| DEP-003 | The platform shall store local data under the project data directory. |
| DEP-004 | The project shall support reproducible environment setup. |

---

## 12. Milestones

| Milestone | Name | Primary Requirements |
|---|---|---|
| M1 | Project Skeleton | NFR-002, CFG-001, LOG-001, DEP-004 |
| M2 | Market Data Pipeline | FR-101 to FR-106 |
| M3 | Candle Pipeline & Persistence | FR-201 to FR-208, FR-701 to FR-703 |
| M4 | Timeframe Pipeline | FR-301 to FR-304 |
| M5 | Market Structure Engine | FR-401 to FR-407 |
| M6 | Trend Engine | FR-501 to FR-503 |
| M7 | Visualization Platform | FR-601 to FR-605, UI-001 to UI-006 |
| M8 | Replay Engine | FR-801 to FR-803 |
| M9 | Multi-Symbol Scanner | FR-901 to FR-902 |
| M10 | AI Decision Engine | FR-1001 to FR-1002 |

---

## 13. Acceptance Criteria

Version 1 is accepted when:

1. BTC/USDT market data is received or loaded from BitMart.
2. One-minute candles are generated accurately and continuously.
3. Candles are stored in memory and persisted to disk.
4. 4H, daily, and weekly candles are generated from one-minute candles.
5. HH, HL, LH, LL, and BOS are detected using candle bodies only.
6. Wicks are displayed in charts and preserved for future SL/TP logic.
7. Trend state is produced independently for selected timeframes.
8. The UI displays candles, structure levels, BOS, and trend state.
9. Replay mode produces the same analytical outputs as live mode for identical candles.
10. Logs are sufficient to diagnose data, storage, and engine issues.

---

## 14. Requirements Traceability Matrix

| Requirement Group | Architecture Document | Implementation Area | Test Type |
|---|---|---|---|
| FR-100 | SAD Market Data Pipeline | backend/pipelines/market_data | Integration |
| FR-200 | SAD Candle Pipeline | backend/pipelines/candle | Unit + Replay |
| FR-300 | SAD Timeframe Pipeline | backend/pipelines/timeframe | Unit |
| FR-400 | RAS Structure Logic / SAD Structure Engine | backend/engines/structure | Unit + Replay |
| FR-500 | SAD Trend Engine | backend/engines/trend | Unit + Replay |
| FR-600 | SAD Visualization | frontend/src | UI |
| FR-700 | SAD Storage | backend/storage | Integration |
| FR-800 | SAD Replay | backend/pipelines/replay | Replay |
| FR-900 | SAD Scanner | backend/engines/scoring | Integration |
| FR-1000 | SAD AI Engine | backend/engines/ai | Prompt Regression |

---

## 15. ADR Index

| ADR | Decision | Status |
|---|---|---|
| ADR-001 | Use one-minute candles as authoritative base timeframe. | Accepted |
| ADR-002 | Use candle bodies only for market structure. | Accepted |
| ADR-003 | Preserve wicks for visualization and future SL/TP. | Accepted |
| ADR-004 | Use pipelines for transformation and engines for analysis. | Accepted |
| ADR-005 | Use MarketContext as canonical analytical object. | Accepted |
| ADR-006 | AI consumes structured MarketContext, not raw charts. | Accepted |
