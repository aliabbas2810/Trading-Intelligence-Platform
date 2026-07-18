# Trading Intelligence Platform

Trading Intelligence Platform (TIP) is a deterministic multi-timeframe trading intelligence platform for crypto market analysis. It currently focuses on BTCUSDT using BitMart USDT-M futures as the sole supported exchange/market-data source.

The system uses an event-driven Python backend, a FastAPI API service, and a React + Lightweight Charts frontend. Trading logic remains in the backend; the frontend renders backend outputs and does not calculate market structure, trend, entry, risk, checklist, score, or AI reasoning.

## Current Status

- Version/status: active development after v0.3.1.
- Completed milestones: M1-M31.
- Latest major capability: Exchange abstraction and background market-data synchronization foundation.
- Backend verification: 217 pytest tests passing after M31.
- Frontend verification: 26 frontend contract tests passing as of M26.

TIP is not production-ready trading software. It is a local-first deterministic analysis platform under active development.

## Architecture Summary

Core processing flow:

```text
Market Data
-> Exchange Sync / Historical Store
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
- `backend/exchange/`: exchange-agnostic public market-data adapter contracts and BitMart USDT-M adapter foundation.
- `backend/sync/`: incremental synchronization planning, metadata checkpoints, bounded coordination, and scanner-ready symbol universe boundary.
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
- M2: Original exchange ingestion foundation, now superseded by BitMart-only M31.1 market-data paths.
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
- M12: Original live exchange mode foundation inside runtime mode selection.
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
- M27-M31: Historical validation/runtime modes, AOI foundation and visualization/gate integration, and exchange synchronization foundation.

## Implemented Capabilities

- Dry-run demo mode for BTCUSDT.
- BitMart USDT-M market-data integration foundation.
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
- Exchange abstraction for public market data.
- BitMart USDT-M active contract discovery and historical completed 1m candle adapter foundation.
- Incremental market-data synchronization planner, metadata checkpoints, and status APIs.
- Scanner-ready symbol universe boundary based on completed sync state.
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

Add `--download` to fetch BitMart USDT-M 1m candles into the exchange/market-specific local cache before loading them:

```powershell
py -3.12 -m backend.app --api --historical --symbol BTCUSDT --timeframe 1m --start 2025-01-01T00:00:00Z --end 2025-01-01T02:00:00Z --download --host 127.0.0.1 --port 8000
```

Start the backend API with historical 1m preload followed by BitMart live mode. BitMart WebSocket ingestion is currently foundation-only and reports unavailable until implemented:

```powershell
py -3.12 -m backend.app --api --historical-live --symbol BTCUSDT --start 2025-01-01T00:00:00Z --end 2025-01-01T02:00:00Z --download --host 127.0.0.1 --port 8000
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

Market-data synchronization is disabled by default. Enable it in configuration before using the M31 sync APIs:

```yaml
market_data_sync:
  enabled: true
  startup_enabled: false
  exchange: bitmart
  market_type: usdt_m_perpetual
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
5. Confirm the chart, structure overlays, BOS overlays, Weekly/Daily AOI boxes, W+D confluence, trend ribbon, replay controls, scanner panel, and trading intelligence panel render.
6. Switch through all supported timeframes.
7. Run scanner and confirm selecting a result updates the chart/intelligence context when demo data exists.
8. Check browser developer tools and backend logs for errors.

## Current Limitations

- Demo data is synthetic.
- Historical and historical-live modes load local/downloaded candle data into the same read APIs as the frontend, but historical replay controls are not implemented yet.
- M31 exchange synchronization is a foundation: it is opt-in, currently includes a BitMart USDT-M public adapter, and uses JSONL/SQLite local storage suitable for development rather than production-scale retention.
- BitMart USDT-M futures is the only active exchange/market. Historical and sync caches include exchange and market type to avoid cross-exchange mixing.
- Scanner all-symbol execution is gated to synchronized READY symbols only when the sync foundation is enabled; live all-symbol streaming is not implemented.
- Current correctness proves integration consistency, not real-market strategy validity.
- Real HH/HL/LH/LL, BOS, trend, AOI, entry, and risk correctness still needs historical and live-market validation.
- AOI sizing, proximity tolerance, entry-window excursion, and ranking weights are not production calibrated.
- Candidate AOIs are not tradable before the third qualifying body interaction; current demo AOIs are synthetic integration fixtures.
- AI provider is currently deterministic/mock, not a real LLM.
- No order execution.
- No live trading.
- No position sizing.
- No financial advice.

## Roadmap / Next Focus

- System correction and validation.
- Historical and live-market validation of structure, trend, AOI, entry, and risk behavior.
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
