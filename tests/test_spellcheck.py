from __future__ import annotations

import time

import pytest

from dhad import Dhad
from dhad.spellcheck import SpellChecker, arabic_edit_distance, default_spellchecker


def test_weighted_distance_models_arabic_confusions() -> None:
    assert arabic_edit_distance("مسوول", "مسؤول") < 0.25
    assert arabic_edit_distance("البرمجه", "البرمجة") < 0.25
    assert arabic_edit_distance("قراة", "قراءة") < 0.5
    assert arabic_edit_distance("كاتب", "كابت") == pytest.approx(0.75)
    assert arabic_edit_distance("كتاب", "مدرسة") > 2.0


def test_unique_hamza_candidate_is_detected() -> None:
    decision = SpellChecker().validate("مسوول")
    assert not decision.valid
    assert decision.reason == "high_confidence_candidate"
    assert decision.candidates[0].value == "مسؤول"


def test_repeated_letter_typo_is_detected() -> None:
    decision = SpellChecker().validate("معلوومات")
    assert not decision.valid
    assert decision.candidates[0].value == "معلومات"


def test_missing_internal_hamza_is_detected() -> None:
    decision = SpellChecker().validate("قراة")
    assert not decision.valid
    assert decision.candidates[0].value == "قراءة"
    assert decision.candidates[0].distance < decision.candidates[1].distance


def test_taa_marbuta_typo_with_article_is_detected() -> None:
    decision = SpellChecker().validate("البرمجه")
    assert not decision.valid
    assert decision.candidates[0].value == "البرمجة"


def test_valid_inflected_forms_are_never_flagged() -> None:
    checker = SpellChecker()
    for word in (
        "وبالمدرسة",
        "مدرستها",
        "المهندسين",
        "الجامعات",
        "سيكتبون",
        "كتبوا",
        "المشاريع",
    ):
        assert checker.validate(word).valid, word


def test_valid_derived_known_root_form_is_accepted() -> None:
    decision = SpellChecker().validate("استعمال")
    assert decision.valid
    assert decision.reason == "known_root_derivation"


def test_unknown_word_without_reliable_candidate_stays_silent() -> None:
    decision = SpellChecker().validate("زمردة")
    assert decision.valid
    assert decision.reason == "no_reliable_candidate"


def test_proper_name_candidates_are_not_used_for_correction() -> None:
    decision = SpellChecker().validate("ساره")
    assert decision.valid
    assert not decision.candidates


def test_name_context_suppresses_unknown_tokens() -> None:
    decision = SpellChecker().validate("كريستوف", previous="الدكتور")
    assert decision.valid
    assert decision.reason == "name_context"


def test_dialect_letters_and_vocalized_words_are_not_lexically_corrected() -> None:
    checker = SpellChecker()
    assert checker.validate("چان").valid
    assert checker.validate("كِتَاب").valid


def test_ambiguous_transposition_stays_silent() -> None:
    decision = SpellChecker().validate("كابت")
    assert decision.valid
    assert decision.reason in {"ambiguous_candidates", "low_confidence"}
    assert len(decision.candidates) >= 2


def test_context_raises_nominal_candidate_after_preposition() -> None:
    checker = SpellChecker()
    candidates = checker.suggest("البرمجه", previous="في")
    assert candidates
    assert candidates[0].value == "البرمجة"
    assert candidates[0].pos in {"noun", "verbal_noun"}


def test_check_text_preserves_offsets_and_never_autofixes_lexical_warning() -> None:
    text = "هذا مسوول عن المشروع."
    matches = SpellChecker().check_text(text)
    assert len(matches) == 1
    match = matches[0]
    assert text[match.offset : match.end] == "مسوول"
    assert match.replacements[0] == "مسؤول"
    assert match.rule_id == "SPELL_LEXICAL_UNKNOWN"
    assert match.autofix is False
    assert match.severity == "warning"


def test_dhad_pipeline_integrates_lexical_match() -> None:
    matches = Dhad().check("هذا مسوول عن المشروع")
    match = next(item for item in matches if item.rule_id == "SPELL_LEXICAL_UNKNOWN")
    assert match.replacements == ["مسؤول"]


def test_safe_correction_policy_does_not_apply_lexical_guess() -> None:
    checker = Dhad()
    text = "هذا مسوول عن المشروع"
    assert checker.correct(text) == text
    assert checker.correct(text, mode="all") == "هذا مسؤول عن المشروع"


def test_static_yaml_rule_wins_overlap_against_lexical_layer() -> None:
    matches = Dhad().check("ذهبت الى المدرسه")
    assert [item.rule_id for item in matches] == ["HAMZA_ILA", "TAA_MADRASA"]


def test_lexical_layer_can_be_disabled_without_affecting_rules() -> None:
    checker = Dhad(lexical_spellcheck=False)
    assert not any(item.rule_id == "SPELL_LEXICAL_UNKNOWN" for item in checker.check("مسوول"))
    assert any(item.rule_id == "HAMZA_ILA" for item in checker.check("ذهبت الى البيت"))


def test_default_spellchecker_is_shared() -> None:
    assert default_spellchecker() is default_spellchecker()
    assert Dhad().spellchecker is Dhad().spellchecker


def test_repeated_document_check_meets_local_latency_budget() -> None:
    checker = SpellChecker()
    text = " ".join(["المهندسون", "كتبوا", "التقرير", "ومدرستها", "مسوول"] * 80)
    start = time.perf_counter()
    matches = checker.check_text(text)
    elapsed = time.perf_counter() - start
    assert matches
    assert elapsed < 0.25
