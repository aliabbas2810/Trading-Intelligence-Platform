# ADR-005: Use MarketContext as Canonical Analytical Object

## Status

Accepted

## Context

Many engines will need to share analytical state.

## Decision

MarketContext shall become the canonical object enriched by downstream engines.

## Consequences

This reduces interface sprawl and supports future AI reasoning.
