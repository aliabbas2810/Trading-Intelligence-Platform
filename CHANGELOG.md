# Changelog

## Unreleased

### Added

- M31: Exchange abstraction and market-data synchronization foundation.
- Generic public market-data adapter protocol.
- BitMart USDT-M active contract discovery and completed 1m historical candle adapter foundation.
- Canonical 1m history store boundary with idempotent upserts and gap detection.
- SQLite synchronization metadata/checkpoints and bounded synchronization coordinator.
- Market-data sync runtime/API status boundaries and scanner-ready universe provider.

### Changed

- M31.1: Consolidated active market-data paths to BitMart USDT-M futures only.
- Historical cache paths now include exchange and market type to avoid cross-exchange mixing.
- Live exchange mode reports BitMart WebSocket ingestion as foundation-only/unavailable until implemented.

### Notes

- Market-data synchronization is disabled by default.
- Tests use deterministic fakes and do not make real exchange network calls.

## v0.1.0 - Foundation Release

Completed Milestones M1-M10.

### Added

- M1: Repository foundation with typed settings, structured logging, event bus, and tests.
- M2: Original exchange ingestion foundation with trade parsing, validation, and stream-client skeleton.
- M3: Deterministic 1-minute candle pipeline with synthetic candles and persistence.
- M4: Higher-timeframe aggregation for 4H, Daily, and Weekly candles.
- M5: Body-based market structure engine with displacement-confirmed swings and BOS detection.
- M6: Trend engine with multi-timeframe aggregation.
- M7: Read-only visualization API and React + Lightweight Charts frontend foundation.
- M8: Replay engine using the same event bus path as live mode.
- M9: Backend multi-symbol scanner foundation.
- M10: Backend AI decision engine foundation with structured input and deterministic mock provider.

### Verification

- Backend test, lint, and typecheck suites pass as of the stabilization pass.
- Frontend contract tests are available through `npm test`.
