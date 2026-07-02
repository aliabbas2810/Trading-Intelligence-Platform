# ADR-008: Start With Python and Migrate Hotspots to C++ Later

## Status

Accepted

## Context

Python enables fast iteration, while the user has long-term C++/HFT ambitions.

## Decision

Implement Version 1 in Python first. Migrate performance-critical engines to C++ only after correctness is validated.

## Consequences

Development velocity remains high while preserving future high-performance paths.
