import json

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from dhad import Dhad
from dhad.checks import check_dialect_letters
from dhad.cli import main as cli_main
from dhad.dialects import (
    DEFAULT_DIALECT_RESOURCE_PATH,
    DIALECT_RESOURCE_SCHEMA_PATH,
    DialectEngine,
    DialectLabel,
    load_dialect_resource,
)
from dhad.server import app

client = TestClient(app)
checker = Dhad()


class TestDialectLexicons:
    def test_iraqi_words_detected(self):
        text = "شلونك؟ اكو شغل هواي هسه"
        ids = {m.rule_id for m in checker.check(text)}
        assert "IQ_SHLONAK" in ids
        assert "IQ_AKU" in ids
        assert "IQ_HASSA" in ids

    def test_gulf_levant_egyptian(self):
        assert any(m.rule_id == "GF_ABGHA" for m in checker.check("ابغى قهوة"))
        assert any(m.rule_id == "LV_KTIR" for m in checker.check("الجو حلو كتير"))
        assert any(m.rule_id == "EG_DILWAQTI" for m in checker.check("دلوقتي نمشي"))

    def test_dialect_is_hint_not_error(self):
        for m in checker.check("شلونك؟ وين رايح؟"):
            if m.category == "dialect":
                assert m.severity == "hint"

    def test_dialect_to_fusha_conversion(self):
        assert checker.correct("ماكو وقت اليوم", mode="all") == "لا يوجد وقت اليوم"
        assert checker.correct("وين رحت؟", mode="all") == "أين رحت؟"

    def test_fusha_text_not_flagged_as_dialect(self):
        clean = "في ذلك الحين كان الوقت متأخرًا، وما زال الطريق طويلًا"
        assert not [m for m in checker.check(clean) if m.category == "dialect"]


class TestDialectLetters:
    def test_persian_letters_flagged(self):
        ms = check_dialect_letters("گلت له تعال")
        assert len(ms) == 1 and ms[0].rule_id == "DIALECT_LETTERS"
        assert "گلت" in ms[0].message

    def test_specific_rule_wins_over_letters_check(self):
        # «چان» لها قاعدة باقتراح «كان» — يجب أن تفوز على فحص الأحرف العام
        ms = [m for m in checker.check("چان الجو باردًا")]
        chan = [m for m in ms if m.offset == 0]
        assert len(chan) == 1
        assert chan[0].replacements == ["كان"]

    def test_veh_not_flagged(self):
        # ڤ تُستخدم في أسماء أعجمية (ڤيديو) — لا نعتبرها لهجة
        assert not check_dialect_letters("شاهدت ڤيديو جميلًا")


class TestServerDisabledCategories:
    def test_disable_dialect(self):
        text = "شلونك؟ ذهبت الى السوق"
        r1 = client.post("/v2/check", data={"text": text})
        cats1 = {m["rule"]["category"]["id"] for m in r1.json()["matches"]}
        assert "DIALECT" in cats1 and "SPELLING" in cats1

        r2 = client.post("/v2/check", data={"text": text, "disabledCategories": "DIALECT"})
        cats2 = {m["rule"]["category"]["id"] for m in r2.json()["matches"]}
        assert "DIALECT" not in cats2 and "SPELLING" in cats2


def test_dialect_resource_schema_and_packaged_payload_are_valid() -> None:
    schema = json.loads(DIALECT_RESOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(DEFAULT_DIALECT_RESOURCE_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    resource = load_dialect_resource()
    assert resource.version == "1.0.0"
    assert len(resource.entries) >= 75
    assert len(resource.names) == 5


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("دلوقتي عايز أشرب شاي", DialectLabel.EGYPTIAN),
        ("هلق بدي نام", DialectLabel.LEVANTINE),
        ("دحين أبغى أروح", DialectLabel.GULF),
        ("هسه ماكو وقت", DialectLabel.IRAQI),
        ("دابا كاين بزاف", DialectLabel.MAGHREBI),
    ],
)
def test_identifies_each_supported_major_dialect(text: str, expected: DialectLabel) -> None:
    result = DialectEngine().identify(text)
    assert result.primary == expected
    assert result.confidence >= 0.75
    assert result.evidence
    assert result.score(expected) > 0.0


def test_mixed_dialect_document_is_not_forced_into_one_label() -> None:
    result = DialectEngine().identify("دلوقتي هسه")
    assert result.primary == DialectLabel.MIXED
    assert result.confidence <= 0.69
    assert {item.rule_id for item in result.evidence} == {"EG_DILWAQTI", "IQ_HASSA"}


def test_dialect_evidence_preserves_exact_source_offsets() -> None:
    text = "وصلت هسه إلى البيت"
    result = DialectEngine().identify(text)
    evidence = next(item for item in result.evidence if item.rule_id == "IQ_HASSA")
    assert text[evidence.offset : evidence.end] == "هسه"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("عايزين نلعب", "نريد أن نلعب"),
        ("بدي نام", "أريد أن أنام"),
        ("ابغى اروح", "أريد أن أذهب"),
        ("بغينا نمشيو", "نريد أن نذهب"),
        ("أبي أروح", "أريد أن أذهب"),
    ],
)
def test_contextual_desire_conversion_inflects_msa_by_person(source: str, expected: str) -> None:
    report = DialectEngine().report(source)
    assert report.converted_text == expected
    conversion = report.conversions[0]
    assert conversion.rule_id == "DIALECT_DESIRE_CONTEXT"
    assert conversion.contextual is True
    assert conversion.morphology_validated is True
    assert conversion.syntax_validated is True
    assert conversion.confidence >= 0.95


def test_contextual_conversion_preserves_attached_conjunction() -> None:
    report = DialectEngine().report("والنهارده عايز اشرب")
    assert report.converted_text == "واليوم أريد أن أشرب"
    assert report.conversions[0].replacement == "واليوم"


def test_nonverb_after_desire_word_does_not_generate_ungrammatical_structure() -> None:
    report = DialectEngine().report("ابغى قهوة")
    assert not any(item.rule_id == "DIALECT_DESIRE_CONTEXT" for item in report.conversions)
    assert any(item.rule_id == "GF_ABGHA" for item in report.conversions)
    assert report.converted_text == "أريد قهوة"


def test_all_dialect_matches_are_hints_and_never_safe_autofix() -> None:
    matches = DialectEngine().check_text("دلوقتي عايزين نلعب وهسه ماكو وقت")
    assert matches
    assert all(item.category == "dialect" for item in matches)
    assert all(item.severity == "hint" for item in matches)
    assert all(item.autofix is False for item in matches)
    assert all("requires-approval" in item.tags for item in matches)


def test_safe_dialect_and_all_fix_modes_are_strictly_separated() -> None:
    checker = Dhad()
    text = "ذهبت الى السوق وعايزين نلعب"
    assert checker.correct(text) == "ذهبت إلى السوق وعايزين نلعب"
    assert checker.correct(text, mode="dialects") == "ذهبت الى السوق ونريد أن نلعب"
    assert checker.correct(text, mode="all") == "ذهبت إلى السوق ونريد أن نلعب"


def test_invalid_fix_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="dialects"):
        Dhad().correct("هسه", mode="unsafe")  # type: ignore[arg-type]


def test_parse_can_explicitly_convert_dialect_before_candidate_irab() -> None:
    checker = Dhad()
    original = checker.parse("عايزين نلعب")
    converted = checker.parse("عايزين نلعب", dialect_to_msa=True)
    assert original.text == "عايزين نلعب"
    assert converted.text == "نريد أن نلعب"
    assert converted.sentences
    assert any(token.pos == "verb" for token in converted.sentences[0].tokens)


def test_public_dialect_report_and_detection_apis_are_consistent() -> None:
    checker = Dhad()
    report = checker.dialect_report("شلونك هسه")
    assert checker.detect_dialect("شلونك هسه") == report.identification
    assert checker.convert_to_msa("شلونك هسه").converted_text == "كيف حالك الآن"


def test_dialect_engine_can_be_disabled_without_disabling_legacy_rules_or_report_api() -> None:
    checker = Dhad(dialect_checks=False)
    text = "دلوقتي عايز اشرب"
    ids = {item.rule_id for item in checker.check(text) if item.category == "dialect"}
    assert "EG_DILWAQTI" in ids
    assert "DIALECT_DESIRE_CONTEXT" not in ids
    assert checker.dialect_report(text).converted_text == "الآن أريد أن أشرب"


def test_enabled_categories_can_request_dialect_only() -> None:
    matches = Dhad(enabled_categories={"dialect"}).check("ذهبت الى السوق وهسه ماكو وقت")
    assert matches
    assert {item.category for item in matches} == {"dialect"}


@pytest.mark.parametrize(
    "text",
    [
        "في ذلك الحين كان الوقت متأخرًا، وما زال الطريق طويلًا.",
        "أبي كريم حضر إلى الاجتماع.",
        "مشيت إلى المدرسة ثم عدت إلى المنزل.",
        "هذا نص عربي فصيح واضح لا يحتوي تعبيرات عامية.",
        "القرار جيد، وقد نوقش في الاجتماع الرسمي.",
    ],
)
def test_context_sensitive_msa_words_do_not_create_dialect_false_positives(text: str) -> None:
    assert DialectEngine().identify(text).primary == DialectLabel.MSA
    assert not DialectEngine().check_text(text)


def test_cli_dialect_json_contains_identification_and_conversion(capsys) -> None:
    assert cli_main(["dialect", "عايزين نلعب", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["primary"] == "egyptian"
    assert payload["converted_text"] == "نريد أن نلعب"
    assert payload["conversions"][0]["syntax_validated"] is True


def test_cli_fix_dialects_applies_no_mechanical_correction(capsys) -> None:
    assert cli_main(["fix", "ذهبت الى السوق وهسه ماكو وقت", "--dialects"]) == 0
    assert capsys.readouterr().out.strip() == "ذهبت الى السوق والآن لا يوجد وقت"


def test_cli_parse_msa_uses_converted_document(capsys) -> None:
    assert cli_main(["parse", "عايزين نلعب", "--msa", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["text"] == "نريد أن نلعب"
