"""Arabic-aware text primitives with stable source offsets.

The module deliberately separates *segmentation* from *normalization*:
segmentation always reports spans in the original Python string, while
normalization is opt-in and must never be used to calculate replacements.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

# Arabic letters used by MSA and common Arabic-script dialect orthographies.
# The ranges intentionally omit Arabic punctuation and digits.
AR_EXT_LETTER = "چگپژڤ"
AR_LETTER = "ء-غف-يٱٮ-ۓۺ-ۼۿ" + AR_EXT_LETTER
AR_DIACRITIC = "ً-ٰٟۖ-ۜ۟-۪ۨ-ۭ"
TATWEEL = "ـ"
AR_WORD_CHAR = AR_LETTER + AR_DIACRITIC + TATWEEL

B_LEFT = rf"(?<![{AR_WORD_CHAR}])"
B_RIGHT = rf"(?![{AR_WORD_CHAR}])"

DIACRITICS_RE = re.compile(rf"[{AR_DIACRITIC}]")
TATWEEL_RE = re.compile(TATWEEL)

_URL = r"(?:https?://|ftp://|www\.)[^\s<>\[\]{}\"'`]+"
_EMAIL = r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
_FENCED_CODE = r"```[\s\S]*?```"
_INLINE_CODE = r"`[^`\n]+`"
_ARABIC_WORD = rf"[{AR_LETTER}](?:[{AR_WORD_CHAR}]*[{AR_LETTER}{AR_DIACRITIC}])?"
_LATIN_WORD = r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’\-][A-Za-zÀ-ÖØ-öø-ÿ]+)*"
_NUMBER = r"[+\-]?[0-9٠-٩]+(?:[.,٫٬][0-9٠-٩]+)*(?:[%٪])?"
_HASHTAG = rf"#[{AR_LETTER}A-Za-z0-9_]+"
_MENTION = rf"@[{AR_LETTER}A-Za-z0-9_]+"

_TOKEN_RE = re.compile(
    "|".join(
        (
            rf"(?P<code>{_FENCED_CODE}|{_INLINE_CODE})",
            rf"(?P<url>{_URL})",
            rf"(?P<email>{_EMAIL})",
            rf"(?P<hashtag>{_HASHTAG})",
            rf"(?P<mention>{_MENTION})",
            rf"(?P<arabic>{_ARABIC_WORD})",
            rf"(?P<number>{_NUMBER})",
            rf"(?P<latin>{_LATIN_WORD})",
            r"(?P<whitespace>\s+)",
            r"(?P<punctuation>[،؛؟.!?,;:…]+)",
            r"(?P<symbol>\S)",
        )
    ),
    re.UNICODE,
)


class TokenKind(str, Enum):
    ARABIC_WORD = "arabic_word"
    LATIN_WORD = "latin_word"
    NUMBER = "number"
    URL = "url"
    EMAIL = "email"
    HASHTAG = "hashtag"
    MENTION = "mention"
    CODE = "code"
    PUNCTUATION = "punctuation"
    SYMBOL = "symbol"
    WHITESPACE = "whitespace"


_KIND_BY_GROUP = {
    "arabic": TokenKind.ARABIC_WORD,
    "latin": TokenKind.LATIN_WORD,
    "number": TokenKind.NUMBER,
    "url": TokenKind.URL,
    "email": TokenKind.EMAIL,
    "hashtag": TokenKind.HASHTAG,
    "mention": TokenKind.MENTION,
    "code": TokenKind.CODE,
    "punctuation": TokenKind.PUNCTUATION,
    "symbol": TokenKind.SYMBOL,
    "whitespace": TokenKind.WHITESPACE,
}


@dataclass(frozen=True, slots=True)
class Token:
    """A token whose ``start``/``end`` always index the original input."""

    text: str
    start: int
    end: int
    kind: TokenKind = TokenKind.ARABIC_WORD

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Token span must be positive and ordered")

    @property
    def is_arabic(self) -> bool:
        return self.kind == TokenKind.ARABIC_WORD

    @property
    def is_word(self) -> bool:
        return self.kind in {
            TokenKind.ARABIC_WORD,
            TokenKind.LATIN_WORD,
            TokenKind.HASHTAG,
            TokenKind.MENTION,
        }


@dataclass(frozen=True, slots=True)
class Sentence:
    """A sentence-like unit with a stable span in the source text."""

    text: str
    start: int
    end: int
    terminator: str = ""


class NormalizationMode(str, Enum):
    """Normalization policies for distinct use-cases.

    STRICT
        Unicode NFC only; suitable for storage and display comparisons.
    LOOKUP
        NFC + remove tashkeel and tatweel; backwards-compatible default.
    SEARCH
        LOOKUP + fold visually/orthographically related Arabic letters.
    AGGRESSIVE
        SEARCH + collapse whitespace and remove most punctuation. Intended for
        retrieval only, never for displaying or replacing user text.
    """

    STRICT = "strict"
    LOOKUP = "lookup"
    SEARCH = "search"
    AGGRESSIVE = "aggressive"


_SEARCH_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ة": "ه",
    }
)

# Abbreviations whose terminal dot is not a sentence boundary.
_ABBREVIATIONS = {
    "د.",
    "أ.د.",
    "م.",
    "أ.",
    "ص.",
    "ج.",
    "هـ.",
    "ق.م.",
    "م.م.",
    "Dr.",
    "Mr.",
    "Mrs.",
    "Ms.",
    "Prof.",
    "e.g.",
    "i.e.",
}
_TERMINATORS = ".!?؟؛…"
_CLOSERS = "\"'»”’)]}"


def iter_tokens(text: str) -> Iterator[Token]:
    """Yield every token, including whitespace and punctuation."""

    for match in _TOKEN_RE.finditer(text):
        group = match.lastgroup
        if group is None:  # pragma: no cover - impossible for a named alternation
            continue
        raw = match.group()
        if group == "url":
            core = raw.rstrip(".,،؛؟!")
            if core:
                core_end = match.start() + len(core)
                yield Token(core, match.start(), core_end, TokenKind.URL)
                for position, char in enumerate(raw[len(core) :], start=core_end):
                    yield Token(char, position, position + 1, TokenKind.PUNCTUATION)
                continue
        yield Token(raw, match.start(), match.end(), _KIND_BY_GROUP[group])


def tokenize(text: str, *, include_non_words: bool = False) -> list[Token]:
    """Tokenize text while preserving source offsets.

    The compatibility default returns semantic content tokens (words, numbers,
    URLs, e-mails, mentions, hashtags, and code) but omits whitespace,
    punctuation, and standalone symbols. Set ``include_non_words=True`` for a
    lossless token stream whose concatenated token texts equal the input.
    """

    tokens = list(iter_tokens(text))
    if include_non_words:
        return tokens
    excluded = {TokenKind.WHITESPACE, TokenKind.PUNCTUATION, TokenKind.SYMBOL}
    return [token for token in tokens if token.kind not in excluded]


def _looks_like_list_marker(
    text: str,
    dot_index: int,
    line_content_start: int | None,
) -> bool:
    if line_content_start is None:
        return False
    tail = dot_index
    while tail > line_content_start and text[tail - 1].isspace():
        tail -= 1
    width = tail - line_content_start
    if width == 1:
        character = text[line_content_start]
        return character in "0123456789٠١٢٣٤٥٦٧٨٩" or character.isascii() and character.isalpha() or "أ" <= character <= "ي"
    return 2 <= width <= 3 and all(
        character in "0123456789٠١٢٣٤٥٦٧٨٩"
        for character in text[line_content_start:tail]
    )


def _looks_like_decimal(text: str, index: int) -> bool:
    return (
        index > 0
        and index + 1 < len(text)
        and text[index - 1] in "0123456789٠١٢٣٤٥٦٧٨٩"
        and text[index + 1] in "0123456789٠١٢٣٤٥٦٧٨٩"
    )


def _preceding_abbreviation(text: str, index: int) -> bool:
    window_start = max(0, index - 12)
    left = text[window_start : index + 1]
    for abbreviation in _ABBREVIATIONS:
        if not left.endswith(abbreviation):
            continue
        absolute_start = index + 1 - len(abbreviation)
        if absolute_start == 0:
            return True
        preceding = text[absolute_start - 1]
        if preceding.isspace() or preceding in "([{'\"«،؛:—-":
            return True
    return False


def sentence_spans(text: str) -> list[Sentence]:
    """Segment Arabic/mixed text without corrupting offsets.

    Newlines and Arabic/Latin sentence terminators split sentences, except for
    decimal points, common abbreviations, and numbered-list markers. Closing
    quotes/brackets following a terminator are consumed as part of the
    terminator but excluded from the sentence body for compatibility.
    """

    if not text:
        return []
    out: list[Sentence] = []
    start = 0
    index = 0
    line_content_start: int | None = None
    length = len(text)
    while index < length:
        char = text[index]
        boundary = False
        if char == "\n":
            boundary = True
        elif char in _TERMINATORS:
            if char == "." and (
                _looks_like_decimal(text, index)
                or _looks_like_list_marker(text, index, line_content_start)
                or _preceding_abbreviation(text, index)
            ):
                index += 1
                continue
            boundary = True
        if not boundary:
            if line_content_start is None and not char.isspace():
                line_content_start = index
            index += 1
            continue

        body_end = index
        term_end = index + 1
        while term_end < length and text[term_end] in _TERMINATORS:
            term_end += 1
        while term_end < length and text[term_end] in _CLOSERS:
            term_end += 1
        chunk = text[start:body_end]
        if chunk.strip():
            out.append(Sentence(chunk, start, body_end, text[body_end:term_end]))
        start = term_end
        index = term_end
        if char == "\n":
            line_content_start = None
    tail = text[start:]
    if tail.strip():
        out.append(Sentence(tail, start, length, ""))
    return out


def sentences(text: str) -> list[tuple[str, int, int]]:
    """Compatibility wrapper returning ``(text, start, end)`` tuples."""

    return [(item.text, item.start, item.end) for item in sentence_spans(text)]


def strip_diacritics(value: str) -> str:
    """Remove Arabic combining marks without altering the source string."""

    return DIACRITICS_RE.sub("", value)


def strip_tatweel(value: str) -> str:
    """Remove kashida/tatweel."""

    return TATWEEL_RE.sub("", value)


def normalize(value: str, mode: NormalizationMode | str = NormalizationMode.LOOKUP) -> str:
    """Normalize text according to an explicit policy.

    ``mode='lookup'`` preserves the historical Dhad behavior.
    """

    policy = NormalizationMode(mode)
    result = unicodedata.normalize("NFC", value)
    if policy == NormalizationMode.STRICT:
        return result
    result = strip_tatweel(strip_diacritics(result))
    if policy == NormalizationMode.LOOKUP:
        return result
    result = result.translate(_SEARCH_TRANSLATION)
    if policy == NormalizationMode.SEARCH:
        return result
    result = re.sub(r"[^\w\s]", " ", result, flags=re.UNICODE)
    return " ".join(result.split())
