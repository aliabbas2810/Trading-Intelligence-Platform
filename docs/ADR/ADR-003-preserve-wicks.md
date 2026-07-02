# ADR-003 — Preserve Wicks for Visualization and SL/TP

Status: Accepted

## Context

Structure uses candle bodies, but wicks are still necessary for realistic charting and trade management.

## Decision

Candles shall preserve full OHLC values. Structure uses body values; visualization and future SL/TP logic may use high and low.

## Consequences

The Candle model must store both full OHLC and derived body values where needed.
