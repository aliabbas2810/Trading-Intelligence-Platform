# ADR-001: Use One-Minute Candles as Authoritative Base Timeframe

## Status

Accepted

## Context

The platform needs deterministic higher-timeframe candles and replay compatibility.

## Decision

All higher timeframes shall be derived from one-minute candles.

## Consequences

This simplifies replay, consistency checks, and future custom timeframe support.
