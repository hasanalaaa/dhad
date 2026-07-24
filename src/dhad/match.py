"""Unified issue model and deterministic conflict resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from .spans import DisjointSpanIndex

CATEGORIES = {
    "spelling": "إملاء",
    "grammar": "نحو",
    "style": "أسلوب",
    "punctuation": "ترقيم",
    "dialect": "عامية",
    "neural_suggestion": "اقتراح عصبي",
    "diacritics": "تشكيل",
    "semantics": "دلالة",
    "consistency": "اتساق",
}
SEVERITIES = ("error", "warning", "hint")


@dataclass(slots=True)
class Match:
    """A single issue found in the original input string."""

    rule_id: str
    category: str
    message: str
    offset: int
    length: int
    replacements: list[str] = field(default_factory=list)
    severity: str = "error"
    explanation: str = ""
    autofix: bool = False
    confidence: float = 1.0
    priority: int = 0
    tags: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ("default",)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown category: {self.category}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"Unknown severity: {self.severity}")
        if self.offset < 0:
            raise ValueError("Match offset must be non-negative")
        if self.length <= 0:
            raise ValueError("Match length must be positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Match confidence must be between 0 and 1")

    @property
    def end(self) -> int:
        return self.offset + self.length

    def overlaps(self, other: "Match") -> bool:
        return self.offset < other.end and other.offset < self.end


def dedupe(matches: list[Match]) -> list[Match]:
    """Resolve overlaps by priority, confidence, severity, and span.

    Selection is global rather than position-first: a later high-priority,
    high-confidence rule can defeat an earlier broad hint. Results are returned
    in source order after the winning non-overlapping set is selected.
    """

    severity_rank = {"error": 3, "warning": 2, "hint": 1}
    ranked = sorted(
        matches,
        key=lambda item: (
            -item.priority,
            -item.confidence,
            -severity_rank[item.severity],
            -int(bool(item.replacements)),
            -item.length,
            item.offset,
            item.rule_id,
        ),
    )
    kept: list[Match] = []
    winners = DisjointSpanIndex()
    for candidate in ranked:
        if not winners.overlaps(candidate.offset, candidate.end):
            winners.add(candidate.offset, candidate.end)
            kept.append(candidate)
    return sorted(kept, key=lambda item: (item.offset, item.end, item.rule_id))
