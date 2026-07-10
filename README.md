# Trading Intelligence Platform

Trading Intelligence Platform (TIP) is a deterministic multi-timeframe trading intelligence platform for crypto market analysis. It currently focuses on a local BTCUSDT demo workflow while preserving architecture for Binance Spot live trade ingestion.

The system uses an event-driven Python backend, a FastAPI API service, and a React + Lightweight Charts frontend. Trading logic remains in the backend; the frontend renders backend outputs and does not calculate market structure, trend, entry, risk, checklist, score, or AI reasoning.

## Current Status

- Version/status: v0.3.1, active development.
- Completed milestones: M1-M26.
- Latest major capability: Trading Intelligence Panel in the React frontend.
- Backend verification: 167 pytest tests passing as of the v0.3.1 correctness pass.
- Frontend verification: 26 frontend contract tests passing as of M26.

TIP is not production-ready trading software. It is a local-first deterministic analysis platform under active development.

## Architecture Summary

Core processing flow:

```text
Market Data
-> Candle Builder
-> Timeframe Aggregation
-> Market Structure
-> Trend Engine
-> Multi-Timeframe Alignment
-> Scanner
-> Entry Engine
-> Risk Engine
-> Checklist Engine
-> Setup Scoring
-> AI Decision
-> Trading Intelligence API
-> React Frontend
```

Repository areas:

- `backend/core/`: event bus and structured logging.
- `backend/config/`: Pydantic settings and default configuration.
- `backend/models/`: canonical domain contracts such as trades, candles, and timeframes.
- `backend/pipelines/`: market data, candle, and timeframe pipelines.
- `backend/engines/`: structure, trend, replay, scanner, entry, risk, checklist, scoring, intelligence, and AI engines.
- `backend/storage/`: in-memory and file persistence boundaries.
- `backend/api/`: FastAPI transport/read/action boundaries.
- `frontend/`: React visualization, replay, scanner, and trading intelligence UI.
- `docs/`: SRS, ADRs, stabilization plans, and correctness documentation.

## Supported Timeframes

The platform currently supports:

- `1w`
- `1d`
- `4h`
- `2h`
- `1h`
- `30m`
- `15m`
- `5m`
- `1m`

## Completed Milestones

### Phase 1: Foundation / M1-M10

- M1: Repository foundation, typed settings, structured logging, synchronous event bus, tests.
- M2: Binance Spot trade ingestion foundation, trade normalization, validation, stream-client skeleton.
- M3: Deterministic 1-minute candle pipeline, synthetic candles, in-memory and JSONL persistence.
- M4: Higher-timeframe aggregation from completed 1-minute candles.
- M5: Body-based market structure with displacement-confirmed swings and BOS detection.
- M6: Trend engine and multi-timeframe aggregation.
- M7: Visualization API and React + Lightweight Charts foundation.
- M8: Replay engine foundation.
- M9: Multi-symbol scanner foundation.
- M10: AI decision engine foundation with deterministic mock provider.

### Phase 2: Runtime, API, Visualization / M11-M20

- M11: Local backend runtime assembly.
- M12: Live Binance integration foundation inside runtime mode selection.
- M13: FastAPI service wiring.
- M14: Frontend live API data connection.
- M15: Dry-run demo mode and deterministic seed data.
- M16: Replay API and runtime controls.
- M17: Replay UI.
- M18: Scanner API.
- M19: Scanner UI.
- M20: AI Decision API.

### Phase 3: Trading Intelligence / M21-M26

- M21: Entry Signal Engine and typed decision evidence.
- M22: Risk Engine.
- M23: Checklist Engine.
- M24: Setup Scoring Engine.
- M25: Consolidated Trading Intelligence API.
- M26: Trading Intelligence Panel.

## Implemented Capabilities

- Dry-run demo mode for BTCUSDT.
- Live Binance Spot trade-stream integration foundation.
- Deterministic candle generation and higher-timeframe aggregation.
- Market structure overlays: HH, HL, LH, LL, and BOS.
- Trend state and multi-timeframe alignment.
- TradingView-style non-destructive replay cursor.
- Scanner backend and frontend panel.
- Entry Signal Engine.
- Risk Engine.
- Checklist Engine.
- Setup Scoring Engine.
- Consolidated Trading Intelligence API.
- Trading Intelligence Panel.
- Deterministic mock AI decision provider.
- API smoke test script.
- v0.3.1 system correctness tests.

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

## Running Locally

Start the backend API in dry-run mode:

```powershell
py -3.12 -m backend.app --api --dry-run --host 127.0.0.1 --port 8000
```

Start the backend API with local historical candles:

```powershell
py -3.12 -m backend.app --api --historical --symbol BTCUSDT --timeframe 1m --start 2025-01-01T00:00:00Z --end 2025-01-01T02:00:00Z --host 127.0.0.1 --port 8000
```

Add `--download` to fetch Binance candles into `data/historical` before loading them:

```powershell
py -3.12 -m backend.app --api --historical --symbol BTCUSDT --timeframe 1m --start 2025-01-01T00:00:00Z --end 2025-01-01T02:00:00Z --download --host 127.0.0.1 --port 8000
```

Start the frontend development server in another terminal:

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Open:

- Backend health: `http://127.0.0.1:8000/api/health`
- Frontend: `http://127.0.0.1:5173`

Run the API smoke test while the backend is running:

```powershell
py -3.12 scripts/smoke_api.py --base-url http://127.0.0.1:8000 --symbol BTCUSDT --timeframe 4h
```

Frontend API configuration defaults to `http://127.0.0.1:8000`. Override it when needed:

```powershell
$env:VITE_TIP_API_BASE_URL="http://127.0.0.1:8000"
$env:VITE_TIP_POLL_INTERVAL_MS="5000"
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

## Verification Commands

Backend:

```powershell
pytest
ruff check .
mypy backend
```

Windows module form if command shims are unavailable:

```powershell
py -3.12 -m pytest
py -3.12 -m ruff check .
py -3.12 -m mypy backend
```

Frontend:

```powershell
npm test
```

## Local Manual Checklist

1. Start the backend API in dry-run mode.
2. Confirm `/api/health` reports `running` and `dry_run`.
3. Run `scripts/smoke_api.py`.
4. Start the frontend dev server.
5. Confirm the chart, structure overlays, BOS overlays, trend ribbon, replay controls, scanner panel, and trading intelligence panel render.
6. Switch through all supported timeframes.
7. Run scanner and confirm selecting a result updates the chart/intelligence context when demo data exists.
8. Check browser developer tools and backend logs for errors.

## Current Limitations

- Demo data is synthetic.
- Historical mode loads local/downloaded candle data into the same read APIs as the frontend, but historical replay controls are not implemented yet.
- Current correctness proves integration consistency, not real-market strategy validity.
- Real HH/HL/LH/LL, BOS, trend, entry, and risk correctness still needs historical and live-market validation.
- AI provider is currently deterministic/mock, not a real LLM.
- No order execution.
- No live trading.
- No position sizing.
- No financial advice.

## Roadmap / Next Focus

- System correction and validation.
- Historical and live-market validation of structure, trend, entry, and risk behavior.
- Frontend usability and visualization maturity.
- Real LLM provider integration later, using structured deterministic outputs only.
- Strategy and risk refinement later, without bypassing deterministic engine boundaries.

## Project Principles

- Deterministic first.
- Completed candles only for analysis.
- Market structure uses candle bodies only.
- Wicks are preserved for visualization and future SL/TP logic.
- Replay and live modes share downstream processing paths where practical.
- Pipelines transform data; engines analyze or enrich context.
- AI reasons over structured outputs, not raw chart data.
