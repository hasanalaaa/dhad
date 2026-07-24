from __future__ import annotations

import json
import time

import pytest

from dhad import Dhad
from dhad.cli import main as cli_main
from dhad.morphology import MorphologicalLexicon
from dhad.syntax import RelationType, SyntaxEngine, default_syntax_engine


def _rule_ids(text: str) -> list[str]:
    return [match.rule_id for match in SyntaxEngine().check_text(text)]


def test_parser_preserves_absolute_offsets_across_sentences() -> None:
    text = "هذا الكتاب مفيد. في المدرستين طالبان."
    parsed = SyntaxEngine().parse(text)
    assert len(parsed.sentences) == 2
    assert parsed.sentences[0].tokens[0].start == 0
    second = parsed.sentences[1]
    assert text[second.tokens[0].start : second.tokens[0].end] == "في"
    assert text[second.tokens[1].start : second.tokens[1].end] == "المدرستين"


def test_context_selects_noun_after_demonstrative() -> None:
    sentence = SyntaxEngine().parse_sentence("هذا الكتاب")
    assert sentence.tokens[0].pos == "pronoun"
    assert sentence.tokens[1].pos == "noun"
    relation = sentence.relations[0]
    assert relation.relation == RelationType.DEMONSTRATIVE
    assert relation.confidence > 0.85


def test_context_selects_imperfect_verb_after_governor() -> None:
    sentence = SyntaxEngine().parse_sentence("لن يكتبون")
    assert sentence.tokens[1].pos == "verb"
    assert sentence.tokens[1].feature("aspect") == "imperfect"
    assert any(r.relation == RelationType.SUBJUNCTIVE_VERB for r in sentence.relations)


def test_internal_punctuation_breaks_adjacency() -> None:
    parsed = SyntaxEngine().parse_sentence("هذه، الكتاب")
    assert not any(r.relation == RelationType.DEMONSTRATIVE for r in parsed.relations)
    assert SyntaxEngine().check_text("هذه، الكتاب") == []


def test_candidate_irab_for_preposition_object() -> None:
    parsed = SyntaxEngine().parse_sentence("في المدرستين")
    candidate = parsed.irab[1]
    assert candidate.role == "اسم مجرور"
    assert candidate.case_or_mood == "genitive"
    assert candidate.governor == "في"
    assert candidate.confidence > 0.9


def test_candidate_irab_for_idafa() -> None:
    parsed = SyntaxEngine().parse_sentence("كتاب الطالب")
    assert parsed.irab[0].role == "مضاف"
    assert parsed.irab[1].role == "مضاف إليه"
    assert parsed.irab[1].case_or_mood == "genitive"


def test_candidate_irab_for_jussive_and_subjunctive() -> None:
    jussive = SyntaxEngine().parse_sentence("لم يكتبون").irab[1]
    subjunctive = SyntaxEngine().parse_sentence("لن يكتبون").irab[1]
    assert jussive.case_or_mood == "jussive"
    assert subjunctive.case_or_mood == "subjunctive"


def test_demonstrative_gender_error_is_detected_with_benchmark_span() -> None:
    text = "هذه الكتاب مفيد"
    match = SyntaxEngine().check_text(text)[0]
    assert match.rule_id == "SYNTAX_DEMONSTRATIVE_AGREEMENT"
    assert text[match.offset : match.end] == "هذه الكتاب"
    assert match.replacements == ["هذا الكتاب"]
    assert match.autofix is True


@pytest.mark.parametrize("text", ["هذا الكتاب مفيد", "هذه المدينة جميلة", "ذلك المشروع مهم"])
def test_correct_demonstrative_phrases_are_silent(text: str) -> None:
    assert "SYNTAX_DEMONSTRATIVE_AGREEMENT" not in _rule_ids(text)


def test_feminine_demonstrative_correction_preserves_noun_surface() -> None:
    text = "هذا المدينة جميلة"
    match = SyntaxEngine().check_text(text)[0]
    assert match.replacements == ["هذه المدينة"]


def test_demonstrative_does_not_guess_unknown_noun_gender() -> None:
    assert SyntaxEngine().check_text("هذه زمرد") == []


def test_naat_gender_mismatch_is_detected() -> None:
    text = "المدينة المفيد"
    match = SyntaxEngine().check_text(text)[0]
    assert match.rule_id == "SYNTAX_NAAT_AGREEMENT"
    assert text[match.offset : match.end] == "المفيد"
    assert match.replacements == ["المفيدة"]
    assert match.autofix is False


def test_correct_naat_is_silent() -> None:
    assert SyntaxEngine().check_text("المدينة المفيدة") == []
    assert SyntaxEngine().check_text("المرجع الداخلي") == []


def test_nonhuman_plural_feminine_singular_agreement_is_accepted() -> None:
    assert SyntaxEngine().check_text("المعايير المعلنة") == []
    assert SyntaxEngine().check_text("البيانات الصحيحة") == []


def test_indefinite_nominal_predicate_is_not_misread_as_naat() -> None:
    assert not any(
        r.relation == RelationType.NAAT
        for r in SyntaxEngine().parse_sentence("مدينة جميلة").relations
    )
    assert SyntaxEngine().check_text("مدينة جميل") == []


def test_vso_feminine_subject_requires_visible_agreement() -> None:
    text = "وصل الطالبة"
    match = SyntaxEngine().check_text(text)[0]
    assert match.rule_id == "SYNTAX_VERB_SUBJECT_GENDER"
    assert match.replacements == ["وصلت"]
    assert match.autofix is False


def test_correct_vso_feminine_agreement_is_silent() -> None:
    assert SyntaxEngine().check_text("وصلت الطالبة") == []


def test_transitive_verb_does_not_trigger_vso_subject_guess() -> None:
    assert SyntaxEngine().check_text("كتب الطالبة") == []
    assert not any(
        r.relation == RelationType.SUBJECT
        for r in SyntaxEngine().parse_sentence("كتب الطالبة").relations
    )


def test_svo_feminine_subject_prefix_mismatch_is_detected() -> None:
    text = "الطالبة يكتب"
    match = SyntaxEngine().check_text(text)[0]
    assert match.rule_id == "SYNTAX_SUBJECT_VERB_PREFIX"
    assert match.replacements == ["تكتب"]


def test_correct_svo_feminine_subject_is_silent() -> None:
    assert SyntaxEngine().check_text("الطالبة تكتب") == []


def test_unknown_subject_gender_suppresses_agreement_diagnostic() -> None:
    assert SyntaxEngine().check_text("النص يكتب") == []


def test_idafa_tanween_is_removed() -> None:
    text = "كتابٌ الطالب"
    match = SyntaxEngine().check_text(text)[0]
    assert match.rule_id == "SYNTAX_IDAFA_TANWEEN"
    assert match.replacements == ["كتاب"]
    assert match.autofix is True


def test_idafa_dual_and_plural_nun_are_removed() -> None:
    plural = SyntaxEngine().check_text("مهندسون الشركة")[0]
    dual = SyntaxEngine().check_text("طالبان المدرسة")[0]
    assert plural.rule_id == "SYNTAX_IDAFA_NUN_DROP"
    assert plural.replacements == ["مهندسو"]
    assert dual.replacements == ["طالبا"]


def test_valid_idafa_is_silent_and_parsed() -> None:
    parsed = SyntaxEngine().parse_sentence("كتاب الطالب")
    assert any(r.relation == RelationType.IDAFA for r in parsed.relations)
    assert SyntaxEngine().check_text("كتاب الطالب") == []
    assert SyntaxEngine().check_text("مهندسو الشركة") == []


def test_construct_state_forms_are_licensed_by_morphology() -> None:
    lexicon = MorphologicalLexicon()
    assert lexicon.lookup("مهندسو")
    assert lexicon.lookup("مدرستا")
    assert any(
        dict(record.features).get("construct_state") == "true"
        for record in lexicon.lookup("مهندسو")
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("في المدرستان", "المدرستين"),
        ("مع المهندسون", "المهندسين"),
        ("إلى الطالبان", "الطالبين"),
    ],
)
def test_preposition_changes_visible_dual_or_plural_case(text: str, expected: str) -> None:
    match = SyntaxEngine().check_text(text)[0]
    assert match.rule_id == "SYNTAX_PREPOSITION_CASE"
    assert match.replacements == [expected]
    assert match.autofix is True


def test_correct_oblique_forms_after_prepositions_are_silent() -> None:
    for text in ("في المدرستين", "مع المهندسين", "إلى الطالبين"):
        assert SyntaxEngine().check_text(text) == []


def test_attached_preposition_is_parsed_and_checked() -> None:
    text = "بالمدرستان"
    parsed = SyntaxEngine().parse_sentence(text)
    relation = next(r for r in parsed.relations if r.relation == RelationType.PREPOSITION_OBJECT)
    assert relation.head_index is None
    match = SyntaxEngine().check_text(text)[0]
    assert match.replacements == ["بالمدرستين"]


@pytest.mark.parametrize(
    ("text", "rule_id"),
    [
        ("لن يكتبون", "SYNTAX_SUBJUNCTIVE_FIVE_VERBS"),
        ("أن يكتبون", "SYNTAX_SUBJUNCTIVE_FIVE_VERBS"),
        ("لم يكتبون", "SYNTAX_JUSSIVE_FIVE_VERBS"),
    ],
)
def test_five_verbs_drop_nun_after_governors(text: str, rule_id: str) -> None:
    match = SyntaxEngine().check_text(text)[0]
    assert match.rule_id == rule_id
    assert match.replacements == ["يكتبوا"]
    assert match.autofix is True


def test_non_imperfect_after_governor_is_not_rewritten() -> None:
    assert SyntaxEngine().check_text("لن كتب") == []


def test_singular_imperfect_has_candidate_irab_without_surface_error() -> None:
    parsed = SyntaxEngine().parse_sentence("لن يكتب")
    assert parsed.irab[1].case_or_mood == "subjunctive"
    assert SyntaxEngine().check_text("لن يكتب") == []


def test_public_dhad_parse_api_exposes_relations_and_irab() -> None:
    parsed = Dhad().parse("في المدرستين")
    assert parsed.sentences
    assert parsed.sentences[0].relations[0].relation == RelationType.PREPOSITION_OBJECT
    assert parsed.sentences[0].irab[1].role == "اسم مجرور"


def test_dhad_pipeline_integrates_syntax_after_existing_layers() -> None:
    matches = Dhad().check("هذه الكتاب")
    assert [match.rule_id for match in matches] == ["SYNTAX_DEMONSTRATIVE_AGREEMENT"]


def test_static_spelling_rule_wins_overlap_over_syntax() -> None:
    matches = Dhad().check("هذه المدرسه")
    assert [match.rule_id for match in matches] == ["TAA_MADRASA"]


def test_syntax_layer_can_be_disabled() -> None:
    checker = Dhad(syntax_checks=False)
    assert not any(match.rule_id.startswith("SYNTAX_") for match in checker.check("هذه الكتاب"))
    assert checker.parse("في المدرسة").sentences


def test_safe_autofix_applies_only_mechanical_syntax_rules() -> None:
    checker = Dhad()
    assert checker.correct("هذه الكتاب") == "هذا الكتاب"
    assert checker.correct("في المدرستان") == "في المدرستين"
    assert checker.correct("وصل الطالبة") == "وصل الطالبة"
    assert checker.correct("وصل الطالبة", mode="all") == "وصلت الطالبة"


def test_enabled_categories_still_filter_syntax_matches() -> None:
    checker = Dhad(enabled_categories={"spelling"})
    assert checker.check("هذه الكتاب") == []


def test_default_syntax_engine_is_shared() -> None:
    assert default_syntax_engine() is default_syntax_engine()
    assert Dhad().syntax is Dhad().syntax


def test_parse_cache_is_used() -> None:
    engine = SyntaxEngine()
    before = engine.cache_info().hits
    engine.parse_sentence("هذا الكتاب")
    engine.parse_sentence("هذا الكتاب")
    assert engine.cache_info().hits >= before + 1


def test_parser_rejects_invalid_confidence_configuration() -> None:
    with pytest.raises(ValueError):
        SyntaxEngine(min_token_confidence=-0.1)
    with pytest.raises(ValueError):
        SyntaxEngine(min_relation_confidence=1.1)


def test_sentence_parse_json_shape_is_serializable_by_cli(capsys) -> None:
    assert cli_main(["parse", "في المدرستين", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["tokens"][1]["text"] == "المدرستين"
    assert payload[0]["relations"][0]["type"] == "preposition_object"
    assert payload[0]["irab"][1]["role"] == "اسم مجرور"


def test_long_document_parse_and_check_meet_local_budget() -> None:
    engine = SyntaxEngine()
    text = " ".join(["هذا الكتاب المفيد. في المدرستين طالبان. لن يكتبون."] * 250)
    start = time.perf_counter()
    parsed = engine.parse(text)
    matches = engine.check_text(text)
    elapsed = time.perf_counter() - start
    assert len(parsed.sentences) == 750
    assert matches
    assert elapsed < 2.0
