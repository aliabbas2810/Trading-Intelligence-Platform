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

- live Binance crypto data ingestion,
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

Priorities:

- Mandatory: required for current milestone
- High: required for Version 1
- Medium: soon after Version 1
- Future: planned future capability

---

## 4. Functional Requirements

### 4.1 Market Data Pipeline

#### FR-101 — Connect to Binance Trade Stream

Priority: Mandatory

The platform shall establish a live connection to the Binance Spot trade stream for supported symbols.

Rationale: Live trade data is the foundation for candle construction.

Acceptance Criteria:

- The system connects to Binance trade stream.
- Trade messages are received for BTCUSDT.
- Connection status is logged.

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

### 4.8 Future AI Decision Engine

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

The local backend application shall support a dry-run or replay-friendly local mode that does not require live Binance streaming.

Milestone: M11

M11 shall not add new trading logic. It shall assemble and coordinate existing components only.

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
