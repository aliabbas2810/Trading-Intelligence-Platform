# AGENTS.md

Instructions for Codex and other AI coding agents working on this repository.

## Mission

Build the Trading Intelligence Platform as a professional, modular, deterministic market-analysis platform.

The platform must ingest live Binance trade data, build deterministic candles, generate higher timeframes, detect body-based market structure, classify trends, visualize results, and later support AI-assisted trade analysis.

## Required Reading Before Changes

Before editing code, read:

1. `PROJECT_CONTEXT.md`
2. `docs/SRS.md`
3. `docs/ADR/README.md`
4. Relevant ADRs in `docs/ADR/`

## Engineering Rules

1. Do not implement features that are not traceable to SRS requirements or explicit user instructions.
2. Keep code modular and testable.
3. Prefer clear OOP boundaries and dependency injection.
4. Do not mix UI logic with trading logic.
5. Do not let AI/LLM components calculate market structure.
6. Use completed candles only for analytical calculations.
7. Market structure uses candle bodies only.
8. Preserve wick data for visualization and future SL/TP logic.
9. All timestamps are UTC.
10. Live mode and replay mode must use the same processing path wherever possible.

## Python Standards

- Python 3.12+
- Type hints everywhere
- `dataclasses` or `pydantic` for typed data contracts
- `Enum` for finite state/status values
- `pathlib` for paths
- `logging` for diagnostics
- `asyncio` for live streaming
- `pytest` for tests
- `ruff`, `black`, and `mypy` should be supported

## Repository Structure Rules

- `backend/pipelines/` transforms data.
- `backend/engines/` analyzes or enriches market context.
- `backend/models/` contains domain objects and data contracts.
- `backend/storage/` contains persistence logic.
- `backend/api/` contains API boundaries.
- `frontend/` contains the React UI.
- `docs/ADR/` records design decisions.

## Requirement Traceability

When implementing a feature, reference the relevant requirement IDs in comments, tests, commit messages, or PR descriptions where practical.

Example:

```text
Implements FR-201, FR-202, FR-205
```

## Testing Expectations

For new backend functionality, add tests when practical.

Minimum expected test types:

- Unit tests for deterministic logic
- Integration tests for pipelines
- Replay tests for live/replay consistency

## Clarification Rule

If a requested change conflicts with the SRS or ADRs, stop and ask for clarification before implementing.
