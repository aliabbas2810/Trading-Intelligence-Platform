# ADR-003: Preserve Wicks for Visualization and SL/TP Logic

## Status

Accepted

## Context

Although structure is body-based, traders need wick data for stop-loss and take-profit analysis.

## Decision

Candles shall preserve full high and low wick values.

## Consequences

Future SL/TP simulation can use wick data without affecting structure detection.
