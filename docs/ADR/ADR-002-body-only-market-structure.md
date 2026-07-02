# ADR-002: Market Structure Uses Candle Bodies Only

## Status

Accepted

## Context

The market-structure logic must avoid wick noise and liquidity sweeps.

## Decision

HH, HL, LH, LL, and BOS calculations shall use candle open/close body values only.

## Consequences

Structure signals become more deterministic. Wick-only breaks do not alter structure.
