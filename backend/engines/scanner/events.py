from __future__ import annotations

from dataclasses import dataclass

from backend.engines.scanner.models import ScannerSummary, SetupCandidate


@dataclass(frozen=True, slots=True)
class SetupCandidateFoundEvent:
    """Published scanner candidate event for FR-903."""

    candidate: SetupCandidate


@dataclass(frozen=True, slots=True)
class ScannerCompletedEvent:
    """Published scanner summary event for FR-901 and FR-902 batch scans."""

    summary: ScannerSummary
