from __future__ import annotations

import json

import pytest

from dhad import Dhad, DocumentConsistencyTracker
from dhad.cli import main
from dhad.semantics import SemanticEngine, SemanticResource


@pytest.fixture(scope="module")
def checker() -> Dhad:
    return Dhad()


def test_variant_consistency_uses_first_observed_form(checker: Dhad) -> None:
    text = "كتب مسؤول التقرير، ثم راجعه مسئول آخر."
    report = checker.semantic_report(text)
    match = next(item for item in report.matches if item.rule_id == "CONSISTENCY_VARIANT_MASUUL")
    assert text[match.offset : match.end] == "مسئول"
    assert match.replacements == ["مسؤول"]
    assert match.category == "consistency"
    assert match.autofix is False


def test_first_observed_noncanonical_form_still_controls_document() -> None:
    tracker = DocumentConsistencyTracker()
    matches = tracker.observe("بلغت مائة وحدة ثم مئة وحدة.")
    assert len(matches) == 1
    assert matches[0].replacements == ["مائة"]


def test_streaming_tracker_preserves_absolute_offsets() -> None:
    tracker = DocumentConsistencyTracker()
    first = "كتب مسؤول التقرير. "
    assert tracker.observe(first) == ()
    matches = tracker.observe("راجعه مسئول آخر.")
    assert len(matches) == 1
    assert matches[0].offset == len(first) + len("راجعه ")
    assert tracker.choices[0].occurrences == 2


def test_numeral_style_consistency_western_first(checker: Dhad) -> None:
    text = "بلغت النتيجة 123 ثم أصبحت ٤٥٦."
    match = next(
        item
        for item in checker.semantic_report(text).matches
        if item.rule_id == "CONSISTENCY_NUMERAL_STYLE"
    )
    assert match.replacements == ["456"]


def test_numeral_style_consistency_arabic_indic_first(checker: Dhad) -> None:
    text = "بلغت النتيجة ١٢٣ ثم أصبحت 456."
    match = next(
        item
        for item in checker.semantic_report(text).matches
        if item.rule_id == "CONSISTENCY_NUMERAL_STYLE"
    )
    assert match.replacements == ["٤٥٦"]


def test_mixed_digits_inside_one_number_are_flagged(checker: Dhad) -> None:
    matches = checker.semantic_report("الرمز ١2٣ غير متجانس.").matches
    assert any(item.rule_id == "CONSISTENCY_NUMERAL_MIXED_TOKEN" for item in matches)


def test_redundancy_patterns_are_suggestions_only(checker: Dhad) -> None:
    report = checker.semantic_report("صعد إلى الأعلى ثم عاد مرة أخرى.")
    ids = {item.rule_id for item in report.matches}
    assert "SEMANTIC_REDUNDANCY_ASCEND_UP" in ids
    assert "SEMANTIC_REDUNDANCY_RETURN_AGAIN" in ids
    assert all(item.category == "semantics" for item in report.matches)
    assert all(item.autofix is False for item in report.matches)


def test_morphology_aware_explicit_contradiction(checker: Dhad) -> None:
    text = "وافق الفريق على القرار ولم يوافق الفريق على القرار."
    match = next(
        item
        for item in checker.semantic_report(text).matches
        if item.rule_id == "SEMANTIC_EXPLICIT_SELF_CONTRADICTION"
    )
    assert text[match.offset : match.end] == "ولم يوافق"
    assert match.replacements == []


def test_temporal_qualification_suppresses_false_contradiction(checker: Dhad) -> None:
    report = checker.semantic_report("وافق الفريق أمس ولم يوافق اليوم.")
    assert not any("CONTRADICTION" in item.rule_id for item in report.matches)


def test_standard_msa_without_variant_conflict_stays_silent(checker: Dhad) -> None:
    text = "كتب مسؤول التقرير مستخدمًا الأرقام ١٢٣ و٤٥٦."
    assert checker.semantic_report(text).matches == ()


def test_integrated_check_prefers_document_consistency_over_lexical_guess(checker: Dhad) -> None:
    text = "كتب مسؤول التقرير، ثم راجعه مسئول آخر."
    matches = checker.check(text)
    relevant = [item for item in matches if text[item.offset : item.end] == "مسئول"]
    assert len(relevant) == 1
    assert relevant[0].category == "consistency"


def test_safe_mode_never_applies_consistency_or_semantic_rewrites(checker: Dhad) -> None:
    text = "كتب مسؤول التقرير ثم راجعه مسئول آخر."
    assert checker.correct(text) == text
    assert checker.correct(text, mode="all") != text


def test_semantic_checks_can_be_disabled() -> None:
    checker = Dhad(semantic_checks=False, lexical_spellcheck=False, style_checks=False)
    text = "بلغت النتيجة 123 ثم أصبحت ٤٥٦."
    assert not any(item.category in {"semantics", "consistency"} for item in checker.check(text))


def test_resource_is_schema_validated() -> None:
    resource = SemanticResource()
    assert resource.version == "1.0.0"
    assert len(resource.variant_groups) >= 4


def test_foreign_parse_is_rejected(checker: Dhad) -> None:
    engine = SemanticEngine(checker.syntax)
    parsed = checker.parse("نص أول")
    with pytest.raises(ValueError, match="same source text"):
        engine.analyze("نص ثان", parsed=parsed)


def test_cli_semantics_json(capsys: pytest.CaptureFixture[str]) -> None:
    text = "بلغت النتيجة ١٢٣ ثم أصبحت 456."
    assert main(["semantics", text, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["numeral_style"] == "arabic_indic"
    assert payload["matches"][0]["category"] == "consistency"
