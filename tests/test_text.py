from dhad.match import Match, dedupe
from dhad.text import normalize, sentences, strip_diacritics, tokenize


def test_tokenize_offsets():
    text = "ذهب الولد إلى المدرسة"
    toks = tokenize(text)
    assert [t.text for t in toks] == ["ذهب", "الولد", "إلى", "المدرسة"]
    for t in toks:
        assert text[t.start : t.end] == t.text


def test_tokenize_mixed_and_digits():
    toks = tokenize("عام 2026 hello ٥ كلمات")
    assert [t.text for t in toks] == ["عام", "2026", "hello", "٥", "كلمات"]
    assert toks[0].is_arabic and not toks[2].is_arabic


def test_tokenize_with_diacritics_kept_in_word():
    toks = tokenize("قَرَأَ الكتابَ")
    assert [t.text for t in toks] == ["قَرَأَ", "الكتابَ"]


def test_sentences_offsets():
    text = "جملة أولى. جملة ثانية؟ الثالثة"
    ss = sentences(text)
    assert len(ss) == 3
    for s, a, b in ss:
        assert text[a:b] == s


def test_strip_diacritics_and_normalize():
    assert strip_diacritics("مُحَمَّد") == "محمد"
    assert normalize("الـــكتاب") == "الكتاب"


def test_match_dedupe_priority():
    a = Match("A", "spelling", "m", offset=0, length=5, severity="error")
    b = Match("B", "style", "m", offset=3, length=4, severity="hint")
    c = Match("C", "style", "m", offset=10, length=2, severity="hint")
    kept = dedupe([b, c, a])
    assert [m.rule_id for m in kept] == ["A", "C"]


def test_match_validation():
    import pytest

    with pytest.raises(ValueError):
        Match("X", "nope", "m", 0, 1)
    with pytest.raises(ValueError):
        Match("X", "spelling", "m", 0, 0)
