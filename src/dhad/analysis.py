"""Immutable, reusable document analysis state shared by engine layers."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace

from .syntax import DocumentParse
from .text import NormalizationMode, Sentence, Token, iter_tokens, normalize, sentence_spans


_TERMINATORS = frozenset(".!?؟؛…")


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """One source revision's token stream, sentence index, and syntax parse.

    Offsets are Unicode scalar indexes into :attr:`text`. Consumers must reject
    contexts from another source revision instead of silently mixing spans.
    """

    text: str
    sentences: tuple[Sentence, ...]
    tokens: tuple[Token, ...]
    normalized_lookup: tuple[str, ...]
    parsed: DocumentParse | None = None
    _sentence_starts: tuple[int, ...] = field(default=(), repr=False)

    @classmethod
    def build(cls, text: str, *, parsed: DocumentParse | None = None) -> "AnalysisContext":
        if parsed is not None and parsed.text != text:
            raise ValueError("Parsed document must belong to the same source text")
        if parsed is None:
            sentences = tuple(sentence_spans(text))
        else:
            sentences = tuple(
                Sentence(
                    sentence.text,
                    sentence.start,
                    sentence.end,
                    sentence.text[-1] if sentence.text and sentence.text[-1] in _TERMINATORS else "",
                )
                for sentence in parsed.sentences
            )
        tokens = tuple(iter_tokens(text))
        return cls(
            text=text,
            sentences=sentences,
            tokens=tokens,
            normalized_lookup=tuple(
                normalize(token.text, NormalizationMode.LOOKUP) for token in tokens
            ),
            parsed=parsed,
            _sentence_starts=tuple(sentence.start for sentence in sentences),
        )

    def with_parse(self, parsed: DocumentParse) -> "AnalysisContext":
        """Return this tokenized revision with a refined parse attached."""

        if parsed.text != self.text:
            raise ValueError("Parsed document must belong to the same source text")
        return replace(self, parsed=parsed)

    def sentence_at(self, offset: int) -> Sentence:
        """Return the sentence containing ``offset`` in ``O(log n)`` time."""

        if offset < 0 or offset >= len(self.text):
            raise IndexError("Sentence offset is outside the source text")
        index = bisect_right(self._sentence_starts, offset) - 1
        if index >= 0:
            sentence = self.sentences[index]
            if sentence.start <= offset < max(sentence.end, sentence.start + 1):
                return sentence
        raise LookupError(f"No sentence contains source offset {offset}")
