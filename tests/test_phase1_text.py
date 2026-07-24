"""Phase 1 Unicode, tokenization, sentence, and normalization regression bank."""

from __future__ import annotations

import time

import itertools

import pytest

from dhad.text import (
    NormalizationMode,
    TokenKind,
    normalize,
    sentence_spans,
    tokenize,
)


def test_dot_dense_single_line_segmentation_stays_linear() -> None:
    text = "word." * 20_000
    started = time.perf_counter()

    result = sentence_spans(text)

    assert len(result) == 20_000
    assert time.perf_counter() - started < 0.20


def test_punctuation_only_line_does_not_rescan_its_prefix() -> None:
    text = ". " * 50_000
    started = time.perf_counter()

    result = sentence_spans(text)

    assert result == []
    assert time.perf_counter() - started < 0.20

_BASES = (
    "كتاب",
    "مُحَمَّد",
    "الـــلغة",
    "چان",
    "گلت",
    "hello",
    "co-operate",
    "2026",
    "١٢٫٥",
    "https://example.com/path?q=ضاد",
    "writer@example.org",
    "`x = 1`",
    "#اللغة_العربية",
    "@dhad_project",
    "🙂",
    "ضادDhad2026",
)
_PREFIXES = ("", " ", "\n", "قال: ", "( ", "—", "١. ", "• ")
_SUFFIXES = ("", " ", "\n", ".", "؟", "!", " )", "، ثم")

# 16 × 8 × 8 = 1024 independent Unicode/offset cases, exceeding the Phase 1 gate.
_OFFSET_CASES = ["".join(parts) for parts in itertools.product(_PREFIXES, _BASES, _SUFFIXES)]


@pytest.mark.parametrize("text", _OFFSET_CASES)
def test_lossless_unicode_token_offsets(text: str) -> None:
    tokens = tokenize(text, include_non_words=True)
    assert "".join(token.text for token in tokens) == text
    previous_end = 0
    for token in tokens:
        assert text[token.start : token.end] == token.text
        assert token.start == previous_end
        previous_end = token.end
    assert previous_end == len(text)


def test_token_kinds_cover_mixed_real_world_text() -> None:
    text = "راسل writer@example.org عبر https://dhad.dev أو اكتب `dhad check` #ضاد @user ١٢٫٥ 🙂"
    tokens = tokenize(text, include_non_words=True)
    kinds = {token.kind for token in tokens}
    assert {
        TokenKind.ARABIC_WORD,
        TokenKind.EMAIL,
        TokenKind.URL,
        TokenKind.CODE,
        TokenKind.HASHTAG,
        TokenKind.MENTION,
        TokenKind.NUMBER,
        TokenKind.SYMBOL,
        TokenKind.WHITESPACE,
    }.issubset(kinds)
    for token in tokens:
        assert text[token.start : token.end] == token.text


def test_compatibility_tokenize_omits_separators() -> None:
    tokens = tokenize("عام 2026، hello!")
    assert [token.text for token in tokens] == ["عام", "2026", "hello"]


def test_sentence_segmentation_handles_abbreviations_decimals_and_lists() -> None:
    text = "د. أحمد حضر الساعة 3.14 مساءً.\n1. البند الأول\n2. البند الثاني؟ انتهى."
    spans = sentence_spans(text)
    assert [sentence.text.strip() for sentence in spans] == [
        "د. أحمد حضر الساعة 3.14 مساءً",
        "1. البند الأول",
        "2. البند الثاني",
        "انتهى",
    ]
    for sentence in spans:
        assert text[sentence.start : sentence.end] == sentence.text


def test_sentence_offsets_with_quotes_and_arabic_punctuation() -> None:
    text = "قال: «وصلنا!» ثم سأل: هل نبدأ؟ نعم؛ الآن."
    spans = sentence_spans(text)
    assert len(spans) == 4
    for sentence in spans:
        assert text[sentence.start : sentence.end] == sentence.text


def test_normalization_modes_are_explicit_and_distinct() -> None:
    source = "  إِلــى، مَدْرَسَةٍ  "
    assert normalize(source, NormalizationMode.STRICT) == source
    assert normalize(source, "lookup") == "  إلى، مدرسة  "
    assert normalize(source, "search") == "  الي، مدرسه  "
    assert normalize(source, "aggressive") == "الي مدرسه"


def test_invalid_normalization_mode_fails_fast() -> None:
    with pytest.raises(ValueError):
        normalize("نص", "mystery")


def test_url_does_not_swallow_sentence_punctuation() -> None:
    text = "راجع https://dhad.dev/path، ثم أكمل."
    tokens = tokenize(text, include_non_words=True)
    url = next(token for token in tokens if token.kind == TokenKind.URL)
    assert url.text == "https://dhad.dev/path"
    assert text[url.start : url.end] == url.text
