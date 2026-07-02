# ADR-002 — Use Candle Bodies Only for Market Structure

Status: Accepted

## Context

The user wants HH, HL, LH, LL, and BOS to be based on candle openings and closes, not wicks.

## Decision

Market structure calculations shall use candle body high and body low only.

## Rationale

This reduces wick noise and makes structure detection deterministic and less sensitive to liquidity sweeps.

## Consequences

Wick-only breaks do not trigger BOS. Wicks remain available for visualization and future SL/TP logic.
