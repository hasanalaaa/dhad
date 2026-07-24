from __future__ import annotations

import json

import pytest

from dhad import Dhad, DiacritizationMode
from dhad.cli import main
from dhad.diacritics import DiacriticsEngine


@pytest.fixture(scope="module")
def checker() -> Dhad:
    return Dhad()


def test_full_mode_combines_core_and_candidate_irab(checker: Dhad) -> None:
    result = checker.diacritize("ذهب الطالب إلى المدرسة", mode="full")
    assert result.text == "ذَهَبَ الْطَالِبُ إِلَى الْمَدْرَسَةِ"
    assert result.mode == DiacritizationMode.FULL
    assert result.confidence > 0.90


def test_endings_mode_changes_only_word_endings(checker: Dhad) -> None:
    result = checker.diacritize("ذهب الطالب إلى المدرسة", mode="endings")
    assert result.text == "ذهب الطالبُ إلى المدرسةِ"
    assert "ذَهَب" not in result.text


def test_core_mode_omits_candidate_case_endings(checker: Dhad) -> None:
    result = checker.diacritize("ذهب الطالب إلى المدرسة", mode="core")
    assert result.text == "ذَهَبَ الْطَالِب إِلَى الْمَدْرَسَة"


def test_subjunctive_and_jussive_endings_are_syntax_driven(checker: Dhad) -> None:
    assert checker.diacritize("لن يكتب الطلاب الدرس").text.startswith("لَنْ يَكْتُبَ")
    assert checker.diacritize("لم يذهب الطالب").text == "لَمْ يَذْهَبْ الْطَالِبُ"


def test_neural_wsd_reading_controls_internal_vowels(checker: Dhad) -> None:
    verb = checker.diacritize("كتب الطالب الدرس", mode="core")
    plural = checker.diacritize("ثلاثة كتب مفيدة", mode="core")
    assert verb.tokens[0].output == "كَتَبَ"
    assert plural.tokens[1].output == "كُتُب"


def test_attached_prefixes_and_preposition_case(checker: Dhad) -> None:
    result = checker.diacritize("وبالمدرسة")
    assert result.text == "وَبِالْمَدْرَسَةِ"
    token = result.tokens[0]
    assert "exact-vocalization" in token.provenance
    assert "irab:genitive" in token.provenance


def test_offsets_are_anchored_to_original_text(checker: Dhad) -> None:
    source = "قال: ذهب الطالب، ثم عاد."
    result = checker.diacritize(source)
    assert result.text.startswith("قَالَ: ")
    assert result.text.endswith(".")
    for token in result.tokens:
        assert source[token.start : token.end] == token.source


def test_existing_marks_are_replaced_without_duplicate_short_vowels(checker: Dhad) -> None:
    result = checker.diacritize("ذَهَب الطالب")
    assert "ذََه" not in result.text
    assert result.text.startswith("ذَهَبَ")


def test_unknown_word_remains_unchanged_at_low_confidence(checker: Dhad) -> None:
    result = checker.diacritize("زرغنب", mode="full")
    assert result.text == "زرغنب"
    assert result.tokens[0].confidence < 0.55


def test_explicit_check_suggestions_are_never_autofixed(checker: Dhad) -> None:
    ordinary = checker.check("ذهب الطالب")
    explicit = checker.check("ذهب الطالب", diacritics_mode="full")
    assert not any(item.category == "diacritics" for item in ordinary)
    diacritics = [item for item in explicit if item.category == "diacritics"]
    assert diacritics
    assert all(item.autofix is False for item in diacritics)
    assert checker.correct("ذهب الطالب") == "ذهب الطالب"


def test_diacritics_engine_rejects_foreign_parse(checker: Dhad) -> None:
    parsed = checker.parse("ذهب الطالب")
    with pytest.raises(ValueError, match="same source text"):
        checker.diacritics.diacritize("ذهب المعلم", parsed=parsed)


def test_all_modes_are_validated() -> None:
    engine = DiacriticsEngine()
    with pytest.raises(ValueError):
        engine.diacritize("نص", mode="unsupported")


def test_cli_diacritize_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["diacritize", "لم يذهب الطالب", "--mode", "full", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "full"
    assert payload["text"] == "لَمْ يَذْهَبْ الْطَالِبُ"
    assert payload["tokens"][1]["case_or_mood"] == "jussive"
