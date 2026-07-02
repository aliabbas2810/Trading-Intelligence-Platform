# Project Context

## Project Name

Trading Intelligence Platform (TIP)

## Current Development Phase

Repository foundation and Milestone M1 preparation.

## What We Are Building

A local-first, professional market-analysis platform that will eventually become an AI-assisted trading intelligence system.

The platform starts with Binance crypto market data and BTCUSDT, but the architecture must support future multi-symbol scanning.

## Core Decisions Already Made

1. Binance Spot trade stream is the first live data source.
2. BTCUSDT is the first symbol.
3. The system starts live from the beginning.
4. The system builds candles from trade stream data, not Binance chart overlays.
5. One-minute candles are the authoritative base timeframe.
6. 4H, Daily, and Weekly candles are derived from one-minute candles.
7. Candle closure is time-driven and UTC aligned.
8. Millisecond precision is used internally.
9. In-memory and disk persistence are both required.
10. Market structure is based on candle bodies only.
11. Wicks are preserved for visualization and future SL/TP logic.
12. React + Lightweight Charts is the target UI.
13. Python is used first for correctness and speed of development.
14. C++ migration is planned later for performance-critical engines.
15. LLMs are future reasoning layers, not structure-calculation engines.
16. The repository is the source of truth for Codex and future agents.

## Current Immediate Goal

Build Milestone M1:

- Repository foundation
- Backend package skeleton
- Logging framework
- Configuration framework
- Event system
- Basic tests
- CI-ready structure

Then proceed to Milestone M2:

- Binance trade stream
- Trade normalization
- Connection health handling

## Architecture Philosophy

The system is divided into:

- Pipelines: transform data
- Engines: analyze/enrich context

Examples:

- Market Data Pipeline
- Candle Pipeline
- Timeframe Pipeline
- Market Structure Engine
- Trend Engine
- Visualization Engine
- AI Decision Engine

## Canonical Object

The long-term canonical object is `MarketContext`.

Engines should consume and enrich context rather than passing many unrelated values around.

## LLM Role

The LLM should receive structured facts such as:

- Weekly trend
- Daily trend
- 4H trend
- Entry signal
- Trend strength
- Risk/reward
- Checklist status

The LLM should produce explanation, risks, checklist review, and recommendation. It must not calculate HH/HL/LH/LL directly.

## Next Codex Task

Read this file, `AGENTS.md`, and `docs/SRS.md`. Then implement Milestone M1 only.
