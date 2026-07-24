"""Local suppression policies for rules, words, lines, and documents."""

from __future__ import annotations

from dataclasses import dataclass, field

from .match import Match
from .text import normalize


@dataclass(frozen=True, slots=True)
class Suppression:
    """Per-call suppression configuration.

    Nothing is persisted or transmitted. Callers can ignore a whole document,
    selected rule IDs, normalized words, or 1-based source lines.
    """

    ignore_document: bool = False
    rule_ids: frozenset[str] = field(default_factory=frozenset)
    words: frozenset[str] = field(default_factory=frozenset)
    lines: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if any(line < 1 for line in self.lines):
            raise ValueError("Suppressed line numbers are 1-based and must be positive")

    @property
    def normalized_words(self) -> frozenset[str]:
        return frozenset(normalize(word) for word in self.words)

    def allows(self, text: str, match: Match) -> bool:
        if self.ignore_document or match.rule_id in self.rule_ids:
            return False
        line_number = text.count("\n", 0, match.offset) + 1
        if line_number in self.lines:
            return False
        matched_text = text[match.offset : match.end]
        if normalize(matched_text) in self.normalized_words:
            return False
        return True


def apply_suppression(text: str, matches: list[Match], policy: Suppression | None) -> list[Match]:
    if policy is None:
        return matches
    return [match for match in matches if policy.allows(text, match)]
