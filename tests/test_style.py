"""Phase 5 clarity, style, tone, safety, and scoped-evaluation tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dhad import Dhad
from dhad.cli import main as cli_main
from dhad.evaluation import GoldAnnotation, evaluate_cases
from dhad.match import Match
from dhad.style import (
    DEFAULT_STYLE_RESOURCE_PATH,
    STYLE_RESOURCE_SCHEMA_PATH,
    StyleEngine,
    StyleProfile,
    ToneLabel,
    load_style_resource,
)


class _FakeChecker:
    def check(self, text: str) -> list[Match]:
        return [
            Match("SPELL", "spelling", "m", 0, 3, replacements=["إلى"]),
            Match("STYLE", "style", "m", 4, 5, replacements=["واضح"]),
        ]


def _rules(text: str, *, profile: StyleProfile | str = StyleProfile.GENERAL) -> list[str]:
    return [item.rule_id for item in StyleEngine(profile=profile).check_text(text)]


def test_style_resource_schema_and_packaged_payload_are_valid() -> None:
    schema = json.loads(STYLE_RESOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(DEFAULT_STYLE_RESOURCE_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    assert load_style_resource().version == "1.0.0"
    assert len(load_style_resource().phrases) >= 15


@pytest.mark.parametrize(
    ("text", "rule_id", "replacement"),
    [
        ("نحن في هذا الوقت الراهن نراجع الخطة.", "STYLE_REDUNDANT_CURRENT_TIME", "حاليًا"),
        ("في حالة إذا تأخر الرد فاتصل بنا.", "STYLE_REDUNDANT_IF_CASE", "إذا"),
        ("حضر كافة جميع الأعضاء.", "STYLE_REDUNDANT_ALL_EVERY", "جميع"),
        (
            "بدأ تعاون مشترك بين الطرفين.",
            "STYLE_REDUNDANT_SHARED_COOPERATION",
            "تعاون بين الطرفين",
        ),
        ("الخدمة مجاني دون مقابل.", "STYLE_REDUNDANT_FREE_NO_CHARGE", "مجاني"),
        ("سبق وأن ناقشنا المسألة.", "STYLE_REDUNDANT_PREVIOUSLY_ALREADY", "سبق أن"),
        ("فيما يتعلق بموضوع التمويل، نرفق التقرير.", "STYLE_WORDY_REGARDING_SUBJECT", "بشأن"),
        ("أُنجز العمل في غضون فترة زمنية قدرها أسبوع.", "STYLE_WORDY_TIME_PERIOD", "خلال"),
        (
            "بناء على ما تقدم ذكره، اعتمدت اللجنة المقترح.",
            "STYLE_WORDY_BASED_ON_PREVIOUS",
            "بناءً على ما سبق",
        ),
        ("في نهاية المطاف اتفق الفريق.", "STYLE_CLICHE_END_OF_DAY", "في النهاية"),
        ("دق ناقوس الخطر بشأن التلوث.", "STYLE_CLICHE_RING_ALARM", "حذّر"),
        ("وضع النقاط على الحروف في الاجتماع.", "STYLE_CLICHE_DOTS_ON_LETTERS", "أوضح التفاصيل"),
        ("راجع القرار آنف الذكر.", "STYLE_ARCHAIC_AFOREMENTIONED", "المذكور سابقًا"),
        ("إزاء ما تقدم، نوافق على الطلب.", "STYLE_ARCHAIC_IN_VIEW_OF_ABOVE", "بناءً على ما سبق"),
        ("لا يخفى على أحد أن النتائج مهمة.", "STYLE_AWKWARD_HIDDEN_FROM_NONE", "من الواضح أن"),
        (
            "تم من قبل اللجنة اتخاذ القرار أمس.",
            "STYLE_AWKWARD_DECISION_PASSIVE",
            "اتخذت اللجنة القرار",
        ),
    ],
)
def test_phrase_families_detect_exact_span_and_suggestion(
    text: str, rule_id: str, replacement: str
) -> None:
    match = next(item for item in StyleEngine().check_text(text) if item.rule_id == rule_id)
    assert text[match.offset : match.end]
    assert replacement in match.replacements
    assert match.category == "style"
    assert match.autofix is False
    assert "requires-approval" in match.tags


def test_phrase_matching_accepts_tashkeel_without_corrupting_offsets() -> None:
    text = "نحن فِي هَذا الوقتِ الراهن نراجع الخطة."
    match = StyleEngine().check_text(text)[0]
    assert text[match.offset : match.end] == "فِي هَذا الوقتِ الراهن"
    assert match.replacements == ["حاليًا"]


def test_literary_profile_preserves_deliberate_cliche_and_metaphor() -> None:
    text = "في نهاية المطاف دق ناقوس الخطر."
    assert "STYLE_CLICHE_END_OF_DAY" in _rules(text)
    assert not any(rule.startswith("STYLE_CLICHE") for rule in _rules(text, profile="literary"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("قام بتحليل البيانات.", "حلّل"),
        ("قامت بمراجعة الخطة.", "راجعت"),
        ("قاموا بتنفيذ المشروع.", "نفّذوا"),
        ("وقام بتوضيح النتيجة.", "ووضّح"),
        ("فقامت بتقديم الطلب.", "فقدّمت"),
    ],
)
def test_morphology_aware_light_verb_rewrite_agrees_with_visible_subject(
    text: str, expected: str
) -> None:
    match = next(
        item
        for item in StyleEngine().check_text(text)
        if item.rule_id == "STYLE_LIGHT_VERB_NOMINALIZATION"
    )
    assert match.replacements == [expected]
    assert "morphology-aware" in match.tags
    assert match.autofix is False


def test_light_verb_rule_requires_prepositional_verbal_noun() -> None:
    assert "STYLE_LIGHT_VERB_NOMINALIZATION" not in _rules("قام تحليل البيانات.")
    assert "STYLE_LIGHT_VERB_NOMINALIZATION" not in _rules("قام بالكتاب.")
    assert "STYLE_LIGHT_VERB_NOMINALIZATION" not in _rules("قام في المنزل.")


def test_all_style_engine_matches_are_subjective_and_never_safe_autofix() -> None:
    text = "في هذا الوقت الراهن قام بتحليل البيانات، وفي نهاية المطاف انتهى."
    matches = StyleEngine().check_text(text)
    assert matches
    assert all(item.category == "style" for item in matches)
    assert all(item.autofix is False for item in matches)
    assert all("requires-approval" in item.tags for item in matches)


def test_safe_mode_never_applies_new_style_rewrite_but_all_mode_can() -> None:
    checker = Dhad()
    text = "نحن في هذا الوقت الراهن نراجع الخطة."
    assert checker.correct(text) == text
    assert checker.correct(text, mode="all") == "نحن حاليًا نراجع الخطة."


def test_phrase_detection_preserves_an_attached_leading_conjunction() -> None:
    checker = Dhad()
    text = "راجعنا الخطة، وفي هذا الوقت الراهن نناقش التنفيذ."
    match = next(
        item
        for item in checker.style_report(text).matches
        if item.rule_id == "STYLE_REDUNDANT_CURRENT_TIME"
    )
    assert text[match.offset : match.end] == "وفي هذا الوقت الراهن"
    assert match.replacements == ["وحاليًا"]
    assert checker.correct(text) == text
    assert checker.correct(text, mode="all") == "راجعنا الخطة، وحاليًا نناقش التنفيذ."


def test_integrated_pipeline_marks_style_separately_from_grammar() -> None:
    matches = Dhad().check("هذه الكتاب في هذا الوقت الراهن")
    by_rule = {item.rule_id: item for item in matches}
    assert by_rule["SYNTAX_DEMONSTRATIVE_AGREEMENT"].category == "grammar"
    assert by_rule["SYNTAX_DEMONSTRATIVE_AGREEMENT"].autofix is True
    assert by_rule["STYLE_REDUNDANT_CURRENT_TIME"].category == "style"
    assert by_rule["STYLE_REDUNDANT_CURRENT_TIME"].autofix is False


def test_integrated_pipeline_reuses_the_phase4_parse(monkeypatch) -> None:
    checker = Dhad()
    assert checker.syntax is not None
    calls = 0
    original_parse = checker.syntax.parse

    def counting_parse(text: str):
        nonlocal calls
        calls += 1
        return original_parse(text)

    monkeypatch.setattr(checker.syntax, "parse", counting_parse)
    checker.check("هذه الكتاب في هذا الوقت الراهن")
    assert calls == 1


def test_style_layer_can_be_disabled_without_disabling_style_report_api() -> None:
    checker = Dhad(style_checks=False)
    text = "في هذا الوقت الراهن نراجع الخطة."
    assert "STYLE_REDUNDANT_CURRENT_TIME" not in [item.rule_id for item in checker.check(text)]
    assert checker.style_report(text).matches


def test_enabled_categories_can_request_style_only() -> None:
    checker = Dhad(enabled_categories={"style"})
    matches = checker.check("ذهبت الى السوق في هذا الوقت الراهن")
    assert matches
    assert {item.category for item in matches} == {"style"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("يرجى تزويدنا بالوثائق بموجب القرار.", ToneLabel.FORMAL),
        ("تشير البيانات إلى التحسن، وبلغت النسبة 70٪.", ToneLabel.OBJECTIVE),
        ("يجب تنفيذ الخطة بلا شك.", ToneLabel.ASSERTIVE),
        ("ندعو إلى المشاركة، ومن الضروري دعم المبادرة.", ToneLabel.PERSUASIVE),
        ("يا أصدقاء، برأيي هذا حل جيد.", ToneLabel.CONVERSATIONAL),
    ],
)
def test_tone_classifier_identifies_explainable_primary_tone(
    text: str, expected: ToneLabel
) -> None:
    tone = StyleEngine().classify_tone(text)
    assert tone.primary == expected
    assert tone.evidence
    assert math.isclose(sum(score for _, score in tone.scores), 1.0, abs_tol=1e-6)
    assert 0.0 <= tone.confidence <= 1.0


def test_tone_evidence_preserves_source_offsets() -> None:
    text = "تشير البيانات إلى التحسن."
    tone = StyleEngine().classify_tone(text)
    evidence = next(item for item in tone.evidence if item.tone == ToneLabel.OBJECTIVE)
    assert text[evidence.offset : evidence.offset + evidence.length] == evidence.text
    assert evidence.reason


def test_public_dhad_tone_api_returns_scores() -> None:
    tone = Dhad().analyze_tone("نؤكد أن تنفيذ القرار يجب أن يبدأ اليوم.")
    assert tone.primary == ToneLabel.ASSERTIVE
    assert tone.score("assertive") > tone.score("neutral")


def test_document_tone_shift_is_a_warning_not_a_rewrite() -> None:
    text = (
        "تشير البيانات إلى تحسن الأداء. "
        "أظهرت النتائج انخفاض زمن الاستجابة. "
        "يا أصدقاء، برأيي النتيجة مذهلة!"
    )
    match = next(
        item for item in StyleEngine().check_text(text) if item.rule_id == "STYLE_TONE_SHIFT"
    )
    assert text[match.offset : match.end].startswith("يا أصدقاء")
    assert match.replacements == []
    assert match.autofix is False
    assert "document-consistency" in match.tags


def test_tone_shift_is_silent_without_a_stable_document_tone() -> None:
    text = "أظن أن الفكرة جيدة. برأيي يمكن تطويرها."
    assert "STYLE_TONE_SHIFT" not in _rules(text)


def test_readability_metrics_are_bounded_and_clear_text_scores_higher() -> None:
    engine = StyleEngine()
    clear = engine.analyze("راجع الفريق الخطة. ثم نفذها في موعدها.").readability
    dense_text = (
        "إن عملية تحليل المعطيات ومراجعة المؤشرات وتنفيذ الإجراءات وتقديم التوصيات "
        "وتوضيح المنهجية وربط النتائج ومقارنة السيناريوهات، مع استمرار التنسيق بين "
        "الإدارات واللجان والجهات ذات الصلة، تمثل مسارًا طويلًا يحتاج إلى إعادة تنظيم."
    )
    dense = engine.analyze(dense_text).readability
    assert 0 <= clear.clarity_score <= 100
    assert 0 <= dense.clarity_score <= 100
    assert clear.clarity_score > dense.clarity_score
    assert clear.words > 0 and dense.words > clear.words


def test_empty_text_has_stable_readability_and_neutral_tone() -> None:
    report = StyleEngine().analyze("")
    assert report.readability.words == 0
    assert report.readability.clarity_score == 100.0
    assert report.tone.primary == ToneLabel.NEUTRAL
    assert report.matches == ()


def test_dense_nominalization_sentence_gets_non_rewriting_clarity_hint() -> None:
    text = (
        "إن تحليل البيانات ومراجعة التقارير وتنفيذ الخطط وتقديم النتائج وتوضيح المنهجية "
        "ومقارنة المؤشرات وربط المخرجات وتقييم البدائل، مع التنسيق بين الإدارات واللجان "
        "والفرق والجهات المعنية، يمثل مسارًا متكاملًا للعمل المؤسسي المستمر والمنظم."
    )
    matches = StyleEngine().check_text(text)
    density = next(item for item in matches if item.rule_id == "STYLE_NOMINALIZATION_DENSITY")
    assert density.replacements == []
    assert density.autofix is False
    assert "syntax-aware" in density.tags


def test_style_report_does_not_mutate_source_and_exposes_profile() -> None:
    text = "في هذا الوقت الراهن نراجع الخطة."
    report = Dhad(style_profile="academic").style_report(text)
    assert report.text == text
    assert report.profile == StyleProfile.ACADEMIC
    assert text == "في هذا الوقت الراهن نراجع الخطة."


def test_invalid_style_profile_is_rejected() -> None:
    with pytest.raises(ValueError):
        StyleEngine(profile="unknown")


def test_scoped_evaluation_excludes_style_from_mechanical_false_positives() -> None:
    case = __import__("dhad.evaluation", fromlist=["BenchmarkCase"]).BenchmarkCase(
        id="scope-1",
        text="الى نص",
        domain="educational",
        split="test",
        dialect="msa",
        annotations=(GoldAnnotation("spelling", 0, 3, ("إلى",), "hamza"),),
        dataset="unit",
        license_id="CC0-1.0",
        synthetic=True,
    )
    all_report = evaluate_cases([case], _FakeChecker())
    mechanical = evaluate_cases(
        [case], _FakeChecker(), categories={"spelling", "grammar", "punctuation"}
    )
    assert all_report.span.false_positives == 1
    assert mechanical.span.false_positives == 0
    assert mechanical.span.true_positives == 1
    assert mechanical.categories == ("grammar", "punctuation", "spelling")


def test_style_cli_json_exposes_tone_readability_and_safe_matches(capsys) -> None:
    assert cli_main(["style", "في هذا الوقت الراهن تشير البيانات إلى التحسن.", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "general"
    assert payload["tone"]["primary"] in {"objective", "neutral"}
    assert 0 <= payload["readability"]["clarity_score"] <= 100
    assert payload["matches"][0]["autofix"] is False


def test_benchmark_cli_supports_mechanical_scope(capsys) -> None:
    assert cli_main(["benchmark", "--split", "test", "--scope", "mechanical", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["categories"] == ["grammar", "punctuation", "spelling"]
    assert payload["span"]["f0.5"] > 0.75


def test_python_sources_contain_no_placeholder_markers() -> None:
    root = Path(__file__).parents[1] / "src" / "dhad"
    forbidden = ("# TODO", "# FIXME", "NotImplementedError", "\n    pass\n")
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(marker in source for marker in forbidden), path
