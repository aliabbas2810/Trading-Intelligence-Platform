# ADR-006: LLM Consumes Structured Context Not Raw Charts

## Status

Accepted

## Context

LLMs are useful for reasoning but unreliable for deterministic market calculations.

## Decision

Future LLMs shall consume MarketContext and produce explanation/risk/recommendation only.

## Consequences

Deterministic engines remain the source of truth.
