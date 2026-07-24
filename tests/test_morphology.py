from __future__ import annotations

import json
from pathlib import Path

import pytest

from dhad import Dhad
from dhad.cli import main as cli_main
from dhad.morphology import (
    DEFAULT_LEXICON_PATH,
    MorphologicalAnalyzer,
    MorphologicalLexicon,
    MorphologyBackend,
    default_analyzer,
    default_lexicon,
)


def test_packaged_lexicon_is_schema_valid_and_substantial() -> None:
    lexicon = MorphologicalLexicon()
    assert lexicon.version == "1.1.0"
    assert len(lexicon.lexemes) >= 180
    assert len(lexicon.known_forms) >= 7000
    assert len(lexicon.roots) >= 90


def test_direct_lexical_analysis_returns_root_pattern_and_lemma() -> None:
    analysis = MorphologicalAnalyzer().best("كتابة")
    assert analysis is not None
    assert analysis.lemma == "كتابة"
    assert analysis.root == "كتب"
    assert analysis.pattern == "فعالة"
    assert analysis.pos == "verbal_noun"
    assert analysis.source == "lexicon"
    assert analysis.confidence >= 0.99
    assert [segment.surface for segment in analysis.infixes] == ["ا", "ة"]


def test_prefix_segmentation_preserves_surface_offsets() -> None:
    analysis = MorphologicalAnalyzer().best("وبالمدرسة")
    assert analysis is not None
    assert analysis.lemma == "مدرسة"
    assert analysis.root == "درس"
    assert [segment.surface for segment in analysis.prefixes] == ["و", "ب", "ال"]
    assert [(segment.start, segment.end) for segment in analysis.prefixes] == [
        (0, 1),
        (1, 2),
        (2, 4),
    ]
    assert analysis.stem == "مدرسة"


def test_assimilated_lam_article_is_segmented_without_overlap() -> None:
    analysis = MorphologicalAnalyzer().best("للمدرسة")
    assert analysis is not None
    assert analysis.lemma == "مدرسة"
    assert [segment.surface for segment in analysis.prefixes] == ["ل", "ال"]
    assert all(segment.start < segment.end for segment in analysis.prefixes)


def test_taa_marbuta_is_restored_before_possessive_suffix() -> None:
    analysis = MorphologicalAnalyzer().best("مدرستها")
    assert analysis is not None
    assert analysis.lemma == "مدرسة"
    assert analysis.root == "درس"
    assert [segment.surface for segment in analysis.suffixes] == ["ها"]
    assert analysis.feature("possessive") == "pronoun_feminine"


def test_future_imperfect_plural_has_prefixes_and_suffix() -> None:
    analysis = MorphologicalAnalyzer().best("سيكتبون")
    assert analysis is not None
    assert analysis.lemma == "كتب"
    assert analysis.root == "كتب"
    assert [segment.surface for segment in analysis.prefixes] == ["س", "ي"]
    assert [segment.surface for segment in analysis.suffixes] == ["ون"]
    assert analysis.feature("aspect") == "future"
    assert analysis.feature("number") == "plural"


def test_irregular_explicit_form_uses_lexicon_root() -> None:
    analysis = MorphologicalAnalyzer().best("يقول")
    assert analysis is not None
    assert analysis.lemma == "قال"
    assert analysis.root == "قول"
    assert analysis.source == "lexicon"


def test_sound_and_irregular_plural_forms_are_valid() -> None:
    analyzer = MorphologicalAnalyzer()
    for word, lemma in (("المهندسين", "مهندس"), ("الجامعات", "جامعة"), ("المشاريع", "مشروع")):
        analysis = analyzer.best(word)
        assert analysis is not None
        assert analysis.lemma == lemma
        assert analysis.is_lexical


def test_template_analysis_extracts_root_from_unlisted_derived_form() -> None:
    analyses = MorphologicalAnalyzer().analyze("استعمال")
    target = next(item for item in analyses if item.pattern == "استفعال")
    assert target.root == "عمل"
    assert target.lemma == "عمل"
    assert target.source == "segmented"
    assert [segment.surface for segment in target.infixes] == ["ا", "س", "ت", "ا"]


def test_pattern_only_unknown_root_is_lower_confidence() -> None:
    analysis = MorphologicalAnalyzer().best("زمردة")
    assert analysis is not None
    assert analysis.source == "pattern"
    assert analysis.confidence < 0.6
    assert not analysis.is_lexical


def test_diacritics_are_removed_for_lookup_but_original_token_is_preserved() -> None:
    analysis = MorphologicalAnalyzer().best("كِتَاب")
    assert analysis is not None
    assert analysis.token == "كِتَاب"
    assert analysis.normalized == "كتاب"
    assert analysis.lemma == "كتاب"


def test_non_arabic_and_punctuation_have_no_analysis() -> None:
    analyzer = MorphologicalAnalyzer()
    assert analyzer.analyze("Dhad") == ()
    assert analyzer.analyze("123") == ()
    assert analyzer.analyze("؟") == ()


def test_minimum_confidence_filters_pattern_guesses() -> None:
    analyzer = MorphologicalAnalyzer()
    assert analyzer.analyze("زمردة", min_confidence=0.8) == ()
    assert analyzer.analyze("كتابة", min_confidence=0.8)
    with pytest.raises(ValueError):
        analyzer.analyze("كتاب", min_confidence=1.1)


def test_lexical_validity_rejects_template_only_guess() -> None:
    analyzer = MorphologicalAnalyzer()
    assert analyzer.is_lexically_valid("وبالمدرسة")
    assert not analyzer.is_lexically_valid("زمردة")


def test_root_index_returns_related_lexemes() -> None:
    lemmas = {item.lemma for item in MorphologicalLexicon().by_root("كتب")}
    assert {"كتب", "كتاب", "كاتب", "كتابة", "مكتبة"}.issubset(lemmas)


def test_shared_defaults_are_singletons() -> None:
    assert default_lexicon() is default_lexicon()
    assert default_analyzer() is default_analyzer()
    assert default_analyzer().lexicon is default_lexicon()


def test_analysis_cache_is_used() -> None:
    analyzer = MorphologicalAnalyzer()
    before = analyzer.cache_info().hits
    analyzer.analyze("المهندسون")
    analyzer.analyze("المهندسون")
    assert analyzer.cache_info().hits >= before + 1


def test_public_dhad_api_exposes_morphological_analysis() -> None:
    analyses = Dhad().analyze_word("وبالمدرسة", min_confidence=0.9)
    assert analyses
    assert analyses[0].lemma == "مدرسة"


def test_invalid_lexicon_fails_closed(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_LEXICON_PATH.read_text(encoding="utf-8"))
    payload["entries"][0]["frequency"] = 0
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="schema validation"):
        MorphologicalLexicon(path)


def test_cli_analyze_emits_machine_readable_analysis(capsys) -> None:
    assert cli_main(["analyze", "سيكتبون", "--json", "--min-confidence", "0.7"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["lemma"] == "كتب"
    assert payload[0]["root"] == "كتب"
    assert payload[0]["prefixes"] == ["س", "ي"]
    assert payload[0]["suffixes"] == ["ون"]


def test_default_analyzer_implements_backend_protocol() -> None:
    assert isinstance(default_analyzer(), MorphologyBackend)
