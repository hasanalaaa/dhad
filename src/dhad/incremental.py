"""Incremental checking sessions — V2 Phase 2, latency domination.

An :class:`IncrementalSession` owns one live document. On every edit it
re-analyzes only the mutated sentences plus a configurable ring of context
sentences, then splices the fresh results into the retained ones with exact
offset shifting. The expensive layers (morphology, syntax, style, dialect,
neural) therefore run over a handful of sentences per keystroke instead of
the whole document.

Correctness contract, enforced by ``tests/test_incremental.py``:

* **Sentence-local categories** (spelling, grammar, punctuation, style,
  dialect, diacritics, neural suggestions) are *bit-for-bit identical* to a
  full pass after every update.
* **Document-global categories** (``semantics``, ``consistency``) need the
  whole document by definition; the hot path carries the last full-pass
  results forward (offset-shifted) and :meth:`reconcile` — a full pass —
  refreshes them. ``update`` never fabricates document-global matches from
  window-local context.
* Window edges are safe by construction: the window is expanded to sentence
  boundaries, ±``context_sentences`` whole sentences, then across any
  adjacent phone-like digit runs so the PII mask can never straddle an edge
  differently than in a full pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .match import Match
from .text import sentence_spans

#: Categories whose truth depends on the entire document. They are refreshed
#: by full passes only and carried forward (shifted) on the hot path.
DOCUMENT_CATEGORIES = frozenset({"semantics", "consistency"})

#: Characters that may participate in a phone-number mask. Window edges are
#: pushed across runs of these so partial masking at an edge is impossible.
_PHONE_RUN_RE = re.compile(r"[0-9٠-٩+()\s.\-]")


#: Block size for the chunked diff: block equality checks run at C memcmp
#: speed, so total copying stays O(document) with a ≤ one-block char scan.
_DIFF_BLOCK = 4096

#: The window is computed from a padded slice around the edit instead of a
#: full-document segmentation. The pad dwarfs any realistic sentence length;
#: pathological pad-length sentences fall back to a full pass (see _window).
_SLICE_PAD = 4000


def _common_prefix_length(old: str, new: str) -> int:
    limit = min(len(old), len(new))
    position = 0
    while position < limit:
        if old[position : position + _DIFF_BLOCK] == new[position : position + _DIFF_BLOCK]:
            position += _DIFF_BLOCK
            continue
        stop = min(position + _DIFF_BLOCK, limit)
        while position < stop and old[position] == new[position]:
            position += 1
        return position
    return limit


def _common_suffix_length(old: str, new: str, limit: int) -> int:
    length = 0
    while length < limit:
        step = min(_DIFF_BLOCK, limit - length)
        if (
            old[len(old) - length - step : len(old) - length]
            == new[len(new) - length - step : len(new) - length]
        ):
            length += step
            continue
        while (
            length < limit
            and old[len(old) - length - 1] == new[len(new) - length - 1]
        ):
            length += 1
        return length
    return limit


@dataclass(frozen=True, slots=True)
class UpdateStats:
    """Telemetry for one :meth:`IncrementalSession.update` call."""

    full_pass: bool
    window_start: int
    window_end: int
    window_chars: int
    reused_matches: int
    fresh_matches: int


class IncrementalSession:
    """A live document whose diagnostics update in sub-keystroke time."""

    def __init__(self, checker, *, context_sentences: int = 1) -> None:
        if context_sentences < 1:
            raise ValueError("context_sentences must be at least 1")
        self._checker = checker
        self._context = context_sentences
        self._text = ""
        self._matches: list[Match] = []
        self.last_stats = UpdateStats(True, 0, 0, 0, 0, 0)

    # -- public surface ---------------------------------------------------

    @property
    def text(self) -> str:
        return self._text

    @property
    def matches(self) -> list[Match]:
        return list(self._matches)

    def load(self, text: str) -> list[Match]:
        """Adopt ``text`` with a full authoritative pass."""

        self._text = text
        self._matches = self._checker.check(text)
        self.last_stats = UpdateStats(
            True, 0, len(text), len(text), 0, len(self._matches)
        )
        return self.matches

    def reconcile(self) -> list[Match]:
        """Re-run the full pass, refreshing document-global categories."""

        return self.load(self._text)

    def update(self, new_text: str) -> list[Match]:
        """Apply an edit and return the updated diagnostics."""

        old_text = self._text
        if new_text == old_text:
            self.last_stats = UpdateStats(False, 0, 0, 0, len(self._matches), 0)
            return self.matches
        if not old_text:
            return self.load(new_text)

        prefix = _common_prefix_length(old_text, new_text)
        max_suffix = min(len(old_text), len(new_text)) - prefix
        suffix = _common_suffix_length(old_text, new_text, max_suffix)
        delta = len(new_text) - len(old_text)
        changed_start = prefix
        changed_end_new = len(new_text) - suffix

        window_start, window_end = self._window(new_text, changed_start, changed_end_new)
        old_window_start = window_start
        old_window_end = window_end - delta

        fresh = [
            replace(match, offset=match.offset + window_start)
            for match in self._checker.check(new_text[window_start:window_end])
            if match.category not in DOCUMENT_CATEGORIES
        ]

        merged: list[Match] = []
        reused = 0
        for match in self._matches:
            if match.end <= old_window_start:
                merged.append(match)
                reused += 1
            elif match.offset >= old_window_end:
                merged.append(replace(match, offset=match.offset + delta))
                reused += 1
            # Matches overlapping the old window are superseded by ``fresh``;
            # document-global matches inside it return on the next reconcile.
        merged.extend(fresh)
        merged.sort(key=lambda item: (item.offset, item.end, item.rule_id))

        self._text = new_text
        self._matches = merged
        self.last_stats = UpdateStats(
            False, window_start, window_end, window_end - window_start, reused, len(fresh)
        )
        return self.matches

    # -- window geometry --------------------------------------------------

    def _window(self, text: str, changed_start: int, changed_end: int) -> tuple[int, int]:
        # Segment only a padded slice around the edit. Sentence-boundary
        # decisions in dhad.text depend on a few characters of context, so
        # boundaries detected in the slice interior are identical to a
        # full-document segmentation; the possibly-fragmentary first/last
        # slice spans are discarded below.
        slice_start = 0 if changed_start <= _SLICE_PAD else changed_start - _SLICE_PAD
        slice_end = (
            len(text) if changed_end + _SLICE_PAD >= len(text) else changed_end + _SLICE_PAD
        )
        spans = sentence_spans(text[slice_start:slice_end])
        if not spans:
            return 0, len(text)
        low = 0 if slice_start == 0 else 1
        high = len(spans) if slice_end == len(text) else len(spans) - 1
        usable = spans[low:high]
        if not usable:
            return 0, len(text)

        relative_start = changed_start - slice_start
        relative_end = changed_end - slice_start
        first = len(usable) - 1
        for index, span in enumerate(usable):
            if span.end > relative_start:
                first = index
                break
        last = 0
        for index in range(len(usable) - 1, -1, -1):
            if usable[index].start < relative_end:
                last = index
                break

        first = max(0, first - self._context)
        last = min(len(usable) - 1, last + self._context)

        # The window opens at the selected sentence's start and closes at
        # the start of the next known-genuine boundary, so trailing
        # terminators stay inside the window.
        if first == 0 and slice_start == 0:
            start = 0
        else:
            start = slice_start + usable[first].start
        if last == len(usable) - 1:
            end = len(text) if high == len(spans) else slice_start + spans[high].start
        else:
            end = slice_start + usable[last + 1].start

        # Safety net: if pathological segmentation (e.g., a sentence longer
        # than the pad) left the edit outside the window, fall back to a
        # correct full-document pass rather than a wrong incremental one.
        if start > changed_start or end < changed_end:
            return 0, len(text)

        # Never let a phone-like digit run straddle an edge: the PII mask
        # would otherwise see half a phone number inside the window.
        while start > 0 and (
            _PHONE_RUN_RE.match(text[start - 1])
            and _PHONE_RUN_RE.match(text[start])
        ):
            start -= 1
        while end < len(text) and (
            end > 0
            and _PHONE_RUN_RE.match(text[end - 1])
            and _PHONE_RUN_RE.match(text[end])
        ):
            end += 1
        return start, end
