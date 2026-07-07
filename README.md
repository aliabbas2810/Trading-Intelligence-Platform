# Trading Intelligence Platform

A modular, deterministic market-structure analysis platform for crypto markets.

TIP is currently at the v0.1.0 foundation stage after Milestones M1-M10. The repository contains backend foundations for market data ingestion, candle generation, timeframe aggregation, market structure, trend state, replay, scanner ranking, and structured AI decision support, plus a React visualization foundation.

## Current Capabilities

- Typed Python backend foundation with Pydantic settings, structured logging, and synchronous event bus.
- Binance Spot trade message parsing, normalization, validation, and stream-client skeleton.
- Deterministic 1-minute UTC candle construction from canonical trades.
- Synthetic empty candles for missing minutes.
- In-memory and JSONL candle persistence.
- Deterministic 4H, Daily, and Weekly candle aggregation from completed 1-minute candles.
- Body-only market structure detection with displacement-confirmed swings and BOS events.
- Trend engine with immediate and confirmed flip modes.
- Multi-timeframe trend aggregation over Weekly, Daily, and 4H outputs.
- Read-only visualization API boundaries.
- React + Lightweight Charts frontend foundation.
- Replay engine that reuses the same event bus path as live mode.
- Backend multi-symbol scanner foundation over existing engine outputs.
- Backend AI decision engine foundation over structured deterministic inputs with a mock provider.

## Project Principles

- Deterministic first.
- Completed candles only for analysis.
- Market structure uses candle bodies only.
- Wicks are preserved for visualization and future SL/TP logic.
- Replay and live modes share downstream processing paths where practical.
- Pipelines transform data; engines analyze or enrich context.
- AI reasons over structured outputs, not raw chart data.

## Repository Layout

- `backend/core/`: event bus and logging.
- `backend/config/`: typed settings and default config.
- `backend/models/`: domain contracts.
- `backend/pipelines/`: market data, candle, and timeframe pipelines.
- `backend/engines/`: structure, trend, replay, scanner, and AI engines.
- `backend/storage/`: persistence boundaries.
- `backend/api/`: read-only API boundaries.
- `backend/tests/`: backend tests.
- `frontend/`: React visualization shell and frontend contract tests.
- `docs/ADR/`: accepted architecture decisions.
- `docs/SRS.md`: software requirements specification.

## Setup

Backend requires Python 3.12+.

```powershell
py -3.12 -m pip install --upgrade pip
py -3.12 -m pip install -e ".[dev]"
```

Frontend requires Node.js and npm.

```powershell
npm install
```

## Backend Verification

```powershell
pytest
ruff check .
mypy backend
```

If command shims are unavailable on Windows, use:

```powershell
py -3.12 -m pytest
py -3.12 -m ruff check .
py -3.12 -m mypy backend
```

## Frontend Verification

```powershell
npm test
```

The root npm test script delegates to the frontend workspace:

```powershell
npm --prefix frontend test
```

## Running Locally

Start the backend API in dry-run mode:

```powershell
py -3.12 -m backend.app --api --dry-run --host 127.0.0.1 --port 8000
```

Start the frontend development server in another terminal:

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

## Local Run Checklist

Use this quick checklist when validating the local backend/frontend loop:

1. Start the backend API with `py -3.12 -m backend.app --api --dry-run --host 127.0.0.1 --port 8000`.
2. Open `http://127.0.0.1:8000/api/health` and confirm the runtime reports `running`.
3. Run `py -3.12 scripts/smoke_api.py --base-url http://127.0.0.1:8000 --symbol BTCUSDT --timeframe 4h`.
4. Start the frontend with `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173`.
5. Open `http://127.0.0.1:5173` and confirm the chart, diagnostics strip, replay controls, and scanner panel render.
6. Switch through all supported timeframes and confirm candles/structure/trend diagnostics update.
7. Check browser developer tools for uncaught errors.

The frontend defaults to `http://127.0.0.1:8000` for API calls. Override it with:

```powershell
$env:VITE_TIP_API_BASE_URL="http://127.0.0.1:8000"
$env:VITE_TIP_POLL_INTERVAL_MS="5000"
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

## Milestone Status

| Milestone | Status | Goal |
|---|---|---|
| M1 | Completed | Repository foundation, configuration, logging, event system |
| M2 | Completed | Binance market data pipeline foundation |
| M3 | Completed | 1-minute candle pipeline and persistence |
| M4 | Completed | 4H / Daily / Weekly timeframe pipeline |
| M5 | Completed | Body-based market structure engine |
| M6 | Completed | Trend engine and multi-timeframe aggregation |
| M7 | Completed | Visualization platform foundation |
| M8 | Completed | Replay engine |
| M9 | Completed | Multi-symbol scanner foundation |
| M10 | Completed | AI decision engine foundation |

## Current Status

v0.1.0 foundation is complete. The next recommended phase is integration hardening: assemble runtime services, wire live/replay outputs into read stores, add end-to-end replay integration tests, and stabilize the local backend/frontend development loop.
