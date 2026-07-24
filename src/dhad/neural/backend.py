"""Backend contracts for statistical and transformer contextual classifiers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import CandidateScore, NeuralRequest


@runtime_checkable
class NeuralBackend(Protocol):
    """Stable production interface for contextual candidate scorers."""

    @property
    def name(self) -> str:
        """Human-readable backend identifier."""

    @property
    def available(self) -> bool:
        """Whether the backend can score requests in the current environment."""

    def score(self, request: NeuralRequest) -> tuple[CandidateScore, ...]:
        """Return probabilities for request candidates, highest first."""
