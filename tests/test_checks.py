from dhad.checks import (
    check_latin_punctuation,
    check_long_sentences,
    check_number_agreement,
    check_punctuation_spacing,
    check_repeated_words,
    check_tatweel,
)


def _fix(text, m):
    return text[: m.offset] + m.replacements[0] + text[m.end :]


class TestNumberAgreement:
    def test_masc_numeral_with_fem_noun(self):
        text = "عملت ثلاثة سنوات هناك"
        ms = check_number_agreement(text)
        assert len(ms) == 1
        assert _fix(text, ms[0]) == "عملت ثلاث سنوات هناك"

    def test_fem_numeral_with_masc_noun(self):
        text = "انتظرت خمس أيام كاملة"
        ms = check_number_agreement(text)
        assert len(ms) == 1
        assert _fix(text, ms[0]) == "انتظرت خمسة أيام كاملة"

    def test_correct_forms_not_flagged(self):
        assert not check_number_agreement("عملت ثلاث سنوات وخمسة أيام")
        assert not check_number_agreement("قرأت عشرة كتب في ثماني ساعات")

    def test_thamaniya(self):
        text = "مرت ثمانية ساعات"
        ms = check_number_agreement(text)
        assert ms and _fix(text, ms[0]) == "مرت ثماني ساعات"


class TestPunctuation:
    def test_latin_comma_after_arabic(self):
        text = "جاء زيد, ثم عمرو"
        ms = check_latin_punctuation(text)
        assert len(ms) == 1 and ms[0].replacements == ["،"]
        assert _fix(text, ms[0]) == "جاء زيد، ثم عمرو"

    def test_latin_qmark(self):
        ms = check_latin_punctuation("كيف حالك?")
        assert any(m.rule_id == "PUNCT_LATIN_QMARK" for m in ms)

    def test_latin_comma_in_english_not_flagged(self):
        assert not check_latin_punctuation("hello, world 1,000")

    def test_space_before_punct(self):
        text = "انتهى الأمر ."
        ms = check_punctuation_spacing(text)
        assert len(ms) == 1 and _fix(text, ms[0]) == "انتهى الأمر."


class TestRepetitionAndTatweel:
    def test_repeated_word(self):
        text = "ذهبت إلى إلى السوق"
        ms = check_repeated_words(text)
        assert len(ms) == 1
        assert _fix(text, ms[0]) == "ذهبت إلى السوق"

    def test_no_false_repeat_across_punctuation(self):
        assert not check_repeated_words("نعم، نعم أوافق")

    def test_single_letter_not_flagged(self):
        assert not check_repeated_words("و و")

    def test_tatweel(self):
        ms = check_tatweel("مرحبـــــا بكم")
        assert len(ms) == 1 and ms[0].replacements == [""]


class TestLongSentence:
    def test_long_flagged_short_not(self):
        long_text = " ".join(["كلمة"] * 60)
        assert check_long_sentences(long_text)
        assert not check_long_sentences("جملة قصيرة جدًا.")

    def test_split_sentences_each_ok(self):
        text = ". ".join(" ".join(["كلمة"] * 30) for _ in range(2))
        assert not check_long_sentences(text)
