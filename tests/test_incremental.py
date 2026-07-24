"""V2 Phase 2 — incremental sessions: bit-for-bit equivalence with the full
pass for sentence-local categories, document-global carry-over semantics,
and window geometry safety."""

import random

import pytest

from dhad import DOCUMENT_CATEGORIES, Dhad, IncrementalSession

SENTENCES = [
    "ذهبت الى المدرسه صباحا والتقيت بالمعلم الجديد.",
    "انا احب القراءة كثيرا في المساء.",
    "عملت ثلاثة سنوات في هذه الشركة الكبيرة.",
    "كان الطقس جميلا والسماء صافية تماما.",
    "سأزورك انشاء الله في نهاية الاسبوع.",
    "المهندسة الجديد وصلت الى المكتب مبكرا.",
    "هذا الكتاب مفيد جدا جدا للطلاب الجدد.",
    "نسيت المفتاح في البيت فرجعت مسرعا.",
]

WORDS = ["اليوم", "غدا", "المدرسه", "الجميل", "كتاب", "الى", "انا"]


def _doc(rng, count):
    return " ".join(rng.choice(SENTENCES) for _ in range(count))


def _local(matches):
    return [m for m in matches if m.category not in DOCUMENT_CATEGORIES]


@pytest.fixture(scope="module")
def checker():
    return Dhad()


class TestDiffing:
    def test_word_replacement_produces_small_window(self, checker):
        base = " ".join(SENTENCES * 4)  # 32 sentences
        session = checker.session(base)
        edited = base.replace("القراءة", "الكتابة", 1)
        session.update(edited)
        stats = session.last_stats
        assert not stats.full_pass
        # One mutated sentence ± one context sentence out of 32.
        assert stats.window_chars < len(edited) / 6
        assert stats.reused_matches > 0

    def test_noop_update_reuses_everything(self, checker):
        base = " ".join(SENTENCES[:4])
        session = checker.session(base)
        before = session.matches
        session.update(base)
        assert session.matches == before
        assert session.last_stats.fresh_matches == 0


class TestFullEquivalence:
    """Randomized edit scripts: after every single edit, the session's
    sentence-local matches must equal a from-scratch full pass exactly."""

    def _assert_equivalent(self, checker, session):
        expected = _local(checker.check(session.text))
        actual = _local(session.matches)
        assert actual == expected

    def test_word_replacements(self, checker):
        rng = random.Random(1)
        text = _doc(rng, 10)
        session = checker.session(text)
        for _ in range(12):
            words = session.text.split(" ")
            index = rng.randrange(len(words))
            words[index] = rng.choice(WORDS)
            session.update(" ".join(words))
            self._assert_equivalent(checker, session)

    def test_insertions_and_deletions(self, checker):
        rng = random.Random(2)
        session = checker.session(_doc(rng, 8))
        for step in range(12):
            words = session.text.split(" ")
            if step % 3 == 2 and len(words) > 6:
                del words[rng.randrange(len(words))]
            else:
                words.insert(rng.randrange(len(words) + 1), rng.choice(WORDS))
            session.update(" ".join(words))
            self._assert_equivalent(checker, session)

    def test_sentence_level_edits(self, checker):
        rng = random.Random(3)
        session = checker.session(_doc(rng, 6))
        for step in range(8):
            parts = session.text.split(". ")
            if step % 2 == 0:
                parts.insert(rng.randrange(len(parts) + 1), rng.choice(SENTENCES).rstrip("."))
            elif len(parts) > 3:
                del parts[rng.randrange(len(parts))]
            session.update(". ".join(parts))
            self._assert_equivalent(checker, session)

    def test_append_typing_simulation(self, checker):
        rng = random.Random(4)
        session = checker.session(SENTENCES[0])
        for _ in range(10):
            session.update(session.text + " " + rng.choice(WORDS))
            self._assert_equivalent(checker, session)

    def test_edit_adjacent_to_pii(self, checker):
        base = (
            "راسلني على user@example.com اليوم. "
            "رقمي هو 07701 234 567 للطوارئ. "
            "ذهبت الى المدرسه صباحا."
        )
        session = checker.session(base)
        edited = base.replace("المدرسه", "المكتبه")
        session.update(edited)
        self._assert_equivalent(checker, session)
        edited2 = edited.replace("اليوم", "غدا")
        session.update(edited2)
        self._assert_equivalent(checker, session)

    def test_growing_and_shrinking_document(self, checker):
        rng = random.Random(5)
        session = checker.session(_doc(rng, 2))
        for count in (4, 8, 5, 12, 3):
            session.update(_doc(rng, count))
            self._assert_equivalent(checker, session)


class TestDocumentGlobalContract:
    def test_reconcile_matches_full_pass_completely(self, checker):
        rng = random.Random(6)
        session = checker.session(_doc(rng, 8))
        for _ in range(4):
            words = session.text.split(" ")
            words[rng.randrange(len(words))] = rng.choice(WORDS)
            session.update(" ".join(words))
        session.reconcile()
        assert session.matches == checker.check(session.text)

    def test_hot_path_never_fabricates_document_global(self, checker):
        rng = random.Random(7)
        session = checker.session(_doc(rng, 6))
        baseline_global = {
            (m.rule_id, m.offset) for m in session.matches if m.category in DOCUMENT_CATEGORIES
        }
        words = session.text.split(" ")
        words[0] = "غدا"
        session.update(" ".join(words))
        for match in session.matches:
            if match.category in DOCUMENT_CATEGORIES:
                # Carried forward from the last full pass, possibly shifted —
                # never minted from window-local context.
                assert match.rule_id in {rule for rule, _ in baseline_global}


class TestSessionBasics:
    def test_requires_positive_context(self, checker):
        with pytest.raises(ValueError):
            IncrementalSession(checker, context_sentences=0)

    def test_load_from_empty_and_to_empty(self, checker):
        session = checker.session()
        assert session.matches == []
        session.update("ذهبت الى المدرسه.")
        assert session.matches == checker.check(session.text)
        session.update("")
        assert session.text == ""
        assert session.matches == []

    def test_matches_returns_copy(self, checker):
        session = checker.session(SENTENCES[0])
        copy = session.matches
        copy.clear()
        assert session.matches != []
