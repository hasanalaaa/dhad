"""Privacy primitives and offset-preserving PII masking for Dhad.

The NLP pipeline must never inspect e-mail addresses, telephone numbers, or
URLs.  :class:`PrivacyEngine` replaces each sensitive span with a unique
Private-Use Unicode sentinel of exactly the same length.  Stable length keeps
all Python offsets valid; unique sentinels let generated text be restored even
when diacritics inserted before a protected span change later character
positions.
"""

from __future__ import annotations

import logging
import re
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable, TypeVar

from .match import Match


class PIIKind(str, Enum):
    """Sensitive span classes protected before linguistic processing."""

    EMAIL = "email"
    PHONE = "phone"
    URL = "url"


@dataclass(frozen=True, slots=True)
class PIISpan:
    """One source-anchored protected span."""

    kind: PIIKind
    start: int
    end: int
    original: str
    sentinel: str

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("PII span must be positive and ordered")
        if len(self.original) != self.end - self.start:
            raise ValueError("PII original text must match its source span")
        if len(self.sentinel) != 1:
            raise ValueError("PII sentinel must be one Unicode code point")

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def token(self) -> str:
        return self.sentinel * self.length

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end


_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class MaskedText:
    """Original and same-length masked views of one document."""

    original_text: str
    masked_text: str
    spans: tuple[PIISpan, ...]
    _span_starts: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.original_text) != len(self.masked_text):
            raise ValueError("PII masking must preserve exact source length")
        previous_end = 0
        for span in self.spans:
            if span.start < previous_end:
                raise ValueError("PII spans must be ordered and non-overlapping")
            if self.original_text[span.start : span.end] != span.original:
                raise ValueError("PII span does not match original text")
            if self.masked_text[span.start : span.end] != span.token:
                raise ValueError("PII span does not match masked text")
            previous_end = span.end
        object.__setattr__(self, "_span_starts", tuple(span.start for span in self.spans))

    @property
    def has_pii(self) -> bool:
        return bool(self.spans)

    @property
    def span_starts(self) -> tuple[int, ...]:
        """Sorted protected offsets used by the logarithmic overlap index."""

        return self._span_starts

    def overlaps(self, start: int, end: int) -> bool:
        predecessor = bisect_right(self._span_starts, start) - 1
        if predecessor >= 0 and self.spans[predecessor].end > start:
            return True
        successor = predecessor + 1
        return successor < len(self.spans) and self.spans[successor].start < end

    def filter_matches(self, matches: Iterable[Match]) -> list[Match]:
        """Remove diagnostics whose source spans intersect protected PII."""

        return [match for match in matches if not self.overlaps(match.offset, match.end)]

    def restore(self, value: str) -> str:
        """Restore protected runs in original or generated text.

        Restoration searches for each unique sentinel run instead of assuming
        unchanged output offsets.  This is essential when generated tashkeel
        adds combining marks before a protected span.
        """

        if not self.spans:
            return value
        by_sentinel = {span.sentinel: span for span in self.spans}
        restored: list[str] = []
        cursor = 0
        while cursor < len(value):
            span = by_sentinel.get(value[cursor])
            if span is not None and value.startswith(span.token, cursor):
                restored.append(span.original)
                cursor += span.length
            else:
                restored.append(value[cursor])
                cursor += 1
        return "".join(restored)

    def restore_parse(self, parsed):
        """Restore public text fields in a ``DocumentParse`` value."""

        sentences = tuple(
            replace(sentence, text=self.restore(sentence.text)) for sentence in parsed.sentences
        )
        return replace(parsed, text=self.original_text, sentences=sentences)

    def restore_diacritization(self, result):
        """Restore protected spans in a ``DiacritizationResult`` value."""

        return replace(
            result,
            source_text=self.original_text,
            text=self.restore(result.text),
        )

    def restore_style_report(self, report):
        return replace(
            report,
            text=self.original_text,
            matches=tuple(self.filter_matches(report.matches)),
        )

    def restore_dialect_report(self, report):
        conversions = tuple(
            item
            for item in report.conversions
            if not self.overlaps(item.offset, item.offset + item.length)
        )
        return replace(
            report,
            text=self.original_text,
            conversions=conversions,
            converted_text=self.restore(report.converted_text),
        )

    def restore_semantic_report(self, report):
        return replace(
            report,
            text=self.original_text,
            matches=tuple(self.filter_matches(report.matches)),
        )

    def restore_neural_report(self, report):
        decisions = tuple(
            item
            for item in report.decisions
            if not self.overlaps(item.offset, item.offset + item.length)
        )
        return replace(
            report,
            refined_parse=self.restore_parse(report.refined_parse),
            decisions=decisions,
            suggestions=tuple(self.filter_matches(report.suggestions)),
        )


# URL precedes e-mail and phone matching so embedded digits never become a
# second overlapping PII span.  Terminal Arabic/Latin prose punctuation is
# stripped in ``_iter_candidates`` and remains visible to the sentence parser.
_URL_RE = re.compile(r"(?:https?://|ftp://|www\.)[^\s<>\[\]{}\"'`]+", re.IGNORECASE)
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
)
_PHONE_RE = re.compile(r"(?<![\w@])(?:\+?[0-9٠-٩](?:[\s().\-]?[0-9٠-٩]){6,14})(?![\w@])")
_TRAILING_URL_PUNCTUATION = ".,،؛؟!?:;)»]}>"


class PrivacyEngine:
    """Detect and mask PII without changing source offsets."""

    def __init__(self, *, max_spans: int = 4096) -> None:
        if max_spans < 1:
            raise ValueError("max_spans must be positive")
        self.max_spans = max_spans

    @staticmethod
    def _sentinel(text: str, index: int, reserved: set[str]) -> str:
        # BMP Private Use Area has 6,400 values.  Skip any value already present
        # in the document or assigned to another span.
        for offset in range(0x1900):
            candidate = chr(0xE000 + ((index + offset) % 0x1900))
            if candidate not in text and candidate not in reserved:
                return candidate
        raise ValueError("Unable to allocate a unique PII sentinel")

    @staticmethod
    def _phone_is_plausible(value: str) -> bool:
        digits = [char for char in value if char in "0123456789٠١٢٣٤٥٦٧٨٩"]
        return 7 <= len(digits) <= 15

    def _iter_candidates(self, text: str):
        for kind, pattern in (
            (PIIKind.URL, _URL_RE),
            (PIIKind.EMAIL, _EMAIL_RE),
            (PIIKind.PHONE, _PHONE_RE),
        ):
            for match in pattern.finditer(text):
                start, end = match.span()
                if kind == PIIKind.URL:
                    candidate = text[start:end].rstrip(_TRAILING_URL_PUNCTUATION)
                    end = start + len(candidate)
                    if end <= start:
                        continue
                if kind == PIIKind.PHONE and not self._phone_is_plausible(text[start:end]):
                    continue
                yield kind, start, end

    def mask(self, text: str) -> MaskedText:
        """Return a same-length masked document and auditable span metadata."""

        if not text:
            return MaskedText(text, text, ())
        candidates = sorted(
            self._iter_candidates(text),
            key=lambda item: (item[1], -(item[2] - item[1]), item[0].value),
        )
        accepted: list[tuple[PIIKind, int, int]] = []
        for kind, start, end in candidates:
            if accepted and accepted[-1][2] > start:
                continue
            accepted.append((kind, start, end))
            if len(accepted) > self.max_spans:
                raise ValueError(f"PII span count exceeds configured limit {self.max_spans}")
        accepted.sort(key=lambda item: item[1])

        mutable = list(text)
        spans: list[PIISpan] = []
        reserved: set[str] = set()
        for index, (kind, start, end) in enumerate(accepted):
            sentinel = self._sentinel(text, index, reserved)
            reserved.add(sentinel)
            original = text[start:end]
            mutable[start:end] = sentinel * (end - start)
            spans.append(PIISpan(kind, start, end, original, sentinel))
        return MaskedText(text, "".join(mutable), tuple(spans))

    def redact_for_logs(self, value: str) -> str:
        """Replace PII with typed labels for defensive logging filters."""

        session = self.mask(value)
        redacted = session.masked_text
        for span in session.spans:
            redacted = redacted.replace(span.token, f"[REDACTED_{span.kind.value.upper()}]", 1)
        return redacted


class PrivacyLogFilter(logging.Filter):
    """Defensive PII redaction for operational logs.

    Dhad never logs request bodies.  This filter additionally protects against
    accidental logging of common PII by application or dependency messages.
    """

    def __init__(self, engine: PrivacyEngine | None = None) -> None:
        super().__init__()
        self.engine = engine or PrivacyEngine()

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self.engine.redact_for_logs(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_zero_text_logging(engine: PrivacyEngine | None = None) -> None:
    """Install defensive filters without ever enabling body/request logging."""

    privacy_filter = PrivacyLogFilter(engine)
    for name in ("dhad", "uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, PrivacyLogFilter) for item in logger.filters):
            logger.addFilter(privacy_filter)
