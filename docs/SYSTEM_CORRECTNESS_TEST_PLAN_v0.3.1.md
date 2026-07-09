# v0.3.1 System Correctness Test Plan

## Purpose

This pass verifies that the completed deterministic intelligence chain is internally consistent for the local dry-run BTCUSDT demo. It is not a profitability, strategy, or market-validity test.

## Scope

- Backend dry-run runtime startup and seeded demo data.
- Visualization read APIs for all supported timeframes.
- Entry, risk, checklist, setup score, and consolidated trading intelligence APIs.
- API smoke-test coverage for key read and intelligence endpoints.

Out of scope:

- Real LLM providers.
- Order execution.
- Position sizing.
- New trading rules.
- UI layout changes.
- Historical/live market validation of HH/HL/LH/LL quality.

## Automated Checks

### Demo Data Coverage

- BTCUSDT returns non-empty candles for `1w`, `1d`, `4h`, `2h`, `1h`, `30m`, `15m`, `5m`, and `1m`.
- Each supported timeframe returns structure swings including HH, HL, LH, and LL.
- Each supported timeframe returns at least one BOS event.
- Each supported timeframe returns bullish demo trend state.
- Multi-timeframe alignment returns a bullish `3/3` demo alignment.

### Trading Intelligence Consistency

- `ENTRY_READY` + `LONG` implies a `VALID` demo risk plan.
- LONG stop loss is below entry.
- LONG take profit is above entry.
- R:R is positive and deterministic.
- Checklist is `PASS` when entry is `ENTRY_READY` and risk is `VALID`.
- Setup score is grade `A` or `B` for the valid demo setup.
- The consolidated endpoint must not produce contradictory demo output such as `ENTRY_READY` with `INVALID` risk unless such behavior is explicitly modeled later.

### API Smoke Coverage

The smoke script checks:

- `/api/health`
- `/api/candles`
- `/api/market-structure`
- `/api/trend-state`
- `/api/multi-timeframe-alignment`
- `/api/replay/status`
- `/api/scanner/status`
- `/api/entry/evaluate`
- `/api/risk/evaluate`
- `/api/checklist/evaluate`
- `/api/setup-score/evaluate`
- `/api/trading-intelligence/evaluate`

It prints a concise pass/fail line for each endpoint and summarizes entry, risk, checklist, and score outputs.

## Manual Checklist

1. Start the backend:
   `py -3.12 -m backend.app --api --dry-run --host 127.0.0.1 --port 8000`
2. Run the smoke test:
   `py -3.12 scripts/smoke_api.py`
3. Confirm health reports `dry_run`.
4. Confirm BTCUSDT demo data is visible on all supported timeframes.
5. Confirm trading intelligence reports:
   - entry `ENTRY_READY`
   - direction `LONG`
   - risk `VALID`
   - checklist `PASS`
   - setup score grade `A` or `B`
6. Confirm backend logs show no startup, API, or replay errors.

## Demo Data Note

Current demo data is synthetic and proves component integration only. It is deliberately shaped to exercise the deterministic pipeline and API contracts. Real correctness of HH/HL/LH/LL, BOS, trend, entry, risk, checklist, and score behavior requires later historical and live-market validation against representative data.
