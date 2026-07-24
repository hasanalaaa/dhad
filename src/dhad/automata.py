"""Deterministic Aho-Corasick matching for Unicode literal rule packs."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import re
from typing import Sequence

from .text import AR_WORD_CHAR


_WORD_CHARACTER = re.compile(rf"\A[{AR_WORD_CHAR}]\Z")


@dataclass(frozen=True, slots=True)
class LiteralHit:
    """One whole-word literal occurrence in Unicode scalar offsets."""

    rule_index: int
    start: int
    end: int


@dataclass(slots=True)
class _State:
    transitions: dict[str, int] = field(default_factory=dict)
    failure: int = 0
    outputs: list[tuple[int, int]] = field(default_factory=list)


class LiteralAutomaton:
    """One linear Aho-Corasick scanner shared by all literal rules."""

    __slots__ = ("_states", "_pattern_count")

    def __init__(self, patterns: Sequence[tuple[int, str]]) -> None:
        self._states = [_State()]
        self._pattern_count = 0
        for rule_index, pattern in patterns:
            if not pattern:
                continue
            state = 0
            for character in pattern:
                child = self._states[state].transitions.get(character)
                if child is None:
                    child = len(self._states)
                    self._states[state].transitions[character] = child
                    self._states.append(_State())
                state = child
            self._states[state].outputs.append((rule_index, len(pattern)))
            self._pattern_count += 1
        self._build_failure_links()

    def __len__(self) -> int:
        return self._pattern_count

    def _build_failure_links(self) -> None:
        pending: deque[int] = deque(self._states[0].transitions.values())
        while pending:
            state_index = pending.popleft()
            state = self._states[state_index]
            for character, child_index in state.transitions.items():
                pending.append(child_index)
                failure = state.failure
                while failure and character not in self._states[failure].transitions:
                    failure = self._states[failure].failure
                self._states[child_index].failure = self._states[failure].transitions.get(
                    character, 0
                )
                inherited = self._states[self._states[child_index].failure].outputs
                if inherited:
                    self._states[child_index].outputs.extend(inherited)

    @staticmethod
    def _is_word_character(character: str) -> bool:
        return _WORD_CHARACTER.fullmatch(character) is not None

    def finditer_with_stats(self, text: str) -> tuple[list[LiteralHit], int]:
        """Return boundary-valid hits and the number of automaton transitions.

        Transition accounting includes consumed input characters and failure
        moves. Aho-Corasick bounds their sum linearly in the input length.
        """

        state = 0
        transitions = 0
        hits: list[LiteralHit] = []
        for index, character in enumerate(text):
            transitions += 1
            while state and character not in self._states[state].transitions:
                state = self._states[state].failure
                transitions += 1
            state = self._states[state].transitions.get(character, 0)
            for rule_index, length in self._states[state].outputs:
                start = index + 1 - length
                end = index + 1
                left_ok = start == 0 or not self._is_word_character(text[start - 1])
                right_ok = end == len(text) or not self._is_word_character(text[end])
                if left_ok and right_ok:
                    hits.append(LiteralHit(rule_index, start, end))
        hits.sort(key=lambda hit: (hit.start, hit.rule_index, hit.end))
        return hits, transitions

    def finditer(self, text: str) -> list[LiteralHit]:
        return self.finditer_with_stats(text)[0]
