# ADR-001 — Use 1-Minute Candles as Authoritative Base Timeframe

Status: Accepted

## Context

The platform requires 4H, daily, and weekly candles for analysis.

## Decision

All higher timeframes shall be derived from authoritative one-minute candles.

## Rationale

This provides deterministic aggregation, replay compatibility, and consistent behaviour across live and historical modes.

## Consequences

The platform must reliably generate and persist one-minute candles before higher timeframe analysis can be trusted.
