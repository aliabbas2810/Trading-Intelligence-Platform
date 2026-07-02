# Trading Intelligence Platform

A modular, deterministic market-structure analysis platform for crypto markets.

The first implementation milestone focuses on live Binance trade ingestion, deterministic candle generation, storage, logging, and replay-ready foundations.

## Current Scope

- Binance Spot trade stream
- BTCUSDT first, multi-symbol later
- 1-minute authoritative candles
- 4H / Daily / Weekly derived timeframes
- Body-based market structure analysis
- Wick-aware visualization and future SL/TP logic
- React + Lightweight Charts frontend
- Python backend first, C++ migration later where justified

## Project Principles

- Deterministic first
- Completed candles only
- Body-based structure, wick-preserved candles
- Replay-compatible live pipeline
- Modular pipeline + engine architecture
- AI reasons over structured outputs, not raw charts

## Start Here

For AI coding agents and Codex, read these first:

1. [`AGENTS.md`](AGENTS.md)
2. [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md)
3. [`docs/SRS.md`](docs/SRS.md)
4. [`docs/ADR/README.md`](docs/ADR/README.md)

## Milestones

| Milestone | Goal |
|---|---|
| M1 | Repository foundation, configuration, logging, event system |
| M2 | Binance market data pipeline |
| M3 | 1-minute candle pipeline and persistence |
| M4 | 4H / Daily / Weekly timeframe pipeline |
| M5 | Market structure engine |
| M6 | Trend engine |
| M7 | React visualization platform |
| M8 | Replay and backtesting |
| M9 | Multi-symbol scanner |
| M10 | AI decision engine |

## Status

Initial repository foundation.
