# v0.2.1 Stabilization Test Plan

Purpose: verify the local runtime, API, and visualization shell after M1-M20 without adding product features or trading logic.

## Automated Checks

Run from the repository root:

```powershell
pytest
ruff check .
mypy backend
npm test
```

Run the API smoke test while the backend API is running:

```powershell
py -3.12 scripts/smoke_api.py --base-url http://127.0.0.1:8000 --symbol BTCUSDT --timeframe 4h
```

## Manual Checklist

### Backend Startup

- [ ] Run `py -3.12 -m backend.app --api --dry-run --host 127.0.0.1 --port 8000`.
- [ ] Confirm the process stays running without requiring BitMart network access.
- [ ] Confirm startup logs show the runtime started.
- [ ] Confirm no traceback appears during startup.

### Frontend Startup

- [ ] Run `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173`.
- [ ] Open `http://127.0.0.1:5173`.
- [ ] Confirm the chart shell renders without a blank screen.
- [ ] Confirm the manual refresh button remains available.

### Health Endpoint

- [ ] Open `http://127.0.0.1:8000/api/health`.
- [ ] Confirm `state` is `running`.
- [ ] Confirm `mode` is `dry_run`.
- [ ] Confirm runtime components are listed.

### Timeframe Switching

- [ ] Switch through `1w`, `1d`, `4h`, `2h`, `1h`, `30m`, `15m`, `5m`, and `1m`.
- [ ] Confirm candles render for each timeframe in dry-run demo mode.
- [ ] Confirm diagnostics update candle, structure, BOS, and trend counts.
- [ ] Confirm no chart crash occurs while switching.

### BOS Toggle And Modes

- [ ] Toggle BOS visibility off and confirm BOS lines disappear.
- [ ] Toggle BOS visibility on and confirm BOS lines return.
- [ ] Select `permanent` BOS mode and confirm all backend BOS overlays are shown.
- [ ] Select `auto-clean` BOS mode and confirm only the latest BOS overlay is shown.

### Trend Background And Ribbon

- [ ] Toggle trend background off and confirm the page background returns to neutral.
- [ ] Toggle trend background on and confirm trend shading returns.
- [ ] Toggle trend ribbon off and confirm the ribbon is hidden.
- [ ] Toggle trend ribbon on and confirm trend state and alignment are visible.

### Replay Controls

- [ ] Confirm replay status is visible.
- [ ] Start trade replay and confirm processed event count changes.
- [ ] Pause replay and confirm paused status.
- [ ] Resume replay and confirm progress continues.
- [ ] Step replay and confirm one event is processed.
- [ ] Stop replay and confirm stopped status.

### Scanner Panel

- [ ] Confirm scanner controls are visible: symbols, bias, min alignment, min setup score, top N.
- [ ] Run a scan using demo symbols.
- [ ] Confirm ranked candidates appear without frontend score calculation.
- [ ] Click a candidate with chart data and confirm the chart symbol changes.
- [ ] Click or enter a symbol without chart data and confirm a clear no-data message appears.

### AI Decision API

- [ ] Run a scanner request for `BTCUSDT` if setup candidate context is desired.
- [ ] POST to `/api/ai/decision` with `symbol`, `timeframe`, and optional placeholders.
- [ ] Confirm the response includes `recommendation`, `confidence`, `reasons`, and `risk_assessment`.
- [ ] Confirm `provider` is `rule_based_mock`.
- [ ] Confirm no external LLM/API key is required.

Example:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/ai/decision `
  -ContentType "application/json" `
  -Body '{"symbol":"BTCUSDT","timeframe":"4h","entry_signal":"manual-test","risk_reward":"placeholder"}'
```

### Browser Console Errors

- [ ] Open browser developer tools.
- [ ] Refresh the frontend.
- [ ] Confirm no uncaught React errors appear.
- [ ] Confirm no Lightweight Charts runtime errors appear.
- [ ] Confirm failed API calls are reflected in visible UI error states.

### Backend Logs

- [ ] Confirm health, replay, scanner, and AI calls do not produce tracebacks.
- [ ] Confirm dry-run mode does not start BitMart live streaming.
- [ ] Confirm shutdown with `Ctrl+C` exits cleanly.

## Known Stabilization Boundaries

- No real LLM provider is expected.
- No order execution is expected.
- No all-symbol live BitMart streaming is expected.
- Frontend should render backend outputs only and must not calculate candles, structure, trend, scanner scores, or AI decisions.
