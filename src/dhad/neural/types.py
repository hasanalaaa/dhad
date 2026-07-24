"""Immutable value objects for Dhad's confidence-gated neural layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from ..match import Match
from ..syntax import DocumentParse


class NeuralTask(str, Enum):
    """Tasks supported by neural/statistical backends."""

    WORD_SENSE = "word_sense"
    CONTEXTUAL_SPELLING = "contextual_spelling"


@dataclass(frozen=True, slots=True)
class NeuralCandidate:
    """One candidate exposed to a contextual backend."""

    label: str
    value: str
    lemma: str = ""
    pos: str = "unknown"
    root: str | None = None
    prior: float = 0.0


@dataclass(frozen=True, slots=True)
class NeuralRequest:
    """A source-anchored contextual classification request."""

    task: NeuralTask
    sentence_text: str
    sentence_start: int
    token_index: int
    tokens: tuple[str, ...]
    parts_of_speech: tuple[str, ...]
    candidates: tuple[NeuralCandidate, ...]
    metadata: tuple[tuple[str, str], ...] = ()

    @property
    def token(self) -> str:
        return self.tokens[self.token_index]

    @property
    def metadata_map(self) -> Mapping[str, str]:
        return dict(self.metadata)


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Normalized probability and raw score for one candidate."""

    label: str
    probability: float
    score: float
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("Candidate probability must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class NeuralDecision:
    """A backend decision with an explicit confidence margin."""

    task: NeuralTask
    token: str
    offset: int
    length: int
    selected_label: str
    confidence: float
    margin: float
    backend: str
    evidence: tuple[str, ...] = ()
    changed: bool = False

    def __post_init__(self) -> None:
        if self.offset < 0 or self.length <= 0:
            raise ValueError("Decision span must be positive and ordered")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Decision confidence must be between 0 and 1")
        if not 0.0 <= self.margin <= 1.0:
            raise ValueError("Decision margin must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class NeuralReport:
    """Full hybrid-layer result for one document."""

    refined_parse: DocumentParse
    decisions: tuple[NeuralDecision, ...]
    suggestions: tuple[Match, ...]
    triggered_tokens: int
    skipped_high_confidence: int
    backend: str
