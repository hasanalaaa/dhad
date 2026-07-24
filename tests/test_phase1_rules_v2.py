"""Rule Engine v2 schema, rule kinds, profiles, suppression, and conflicts."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from dhad import Dhad, Suppression
from dhad.match import Match, dedupe
from dhad.rules import RULE_SCHEMA_PATH, RuleEngine


def _base(rule_id: str, rule_type: str, **extra):
    data = {
        "schema_version": 2,
        "id": rule_id,
        "type": rule_type,
        "category": "spelling",
        "severity": "error",
        "confidence": 0.95,
        "priority": 50,
        "autofix": True,
        "profiles": ["default"],
        "tags": ["phase1-test"],
        "references": ["اختبار داخلي"],
        "message": "رسالة اختبار",
        "explanation": "شرح",
        "examples": {"bad": "خطا", "good": "خطأ"},
    }
    data.update(extra)
    return data


def _engine(tmp_path: Path, rules: list[dict]) -> RuleEngine:
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return RuleEngine(tmp_path)


def test_bundled_schema_is_valid_json_schema() -> None:
    schema = json.loads(RULE_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_all_bundled_rules_are_explicit_v2() -> None:
    root = Path(__file__).parents[1] / "src" / "dhad" / "data" / "rules"
    count = 0
    for path in root.glob("*.yaml"):
        for rule in yaml.safe_load(path.read_text(encoding="utf-8")):
            count += 1
            assert rule["schema_version"] == 2
            assert rule["type"] in {
                "literal",
                "regex",
                "token_sequence",
                "context",
                "exception",
                "document",
            }
            assert 0 <= rule["confidence"] <= 1
            assert isinstance(rule["autofix"], bool)
            assert rule["profiles"]
    assert count == 141


def test_literal_regex_and_token_sequence_rules(tmp_path: Path) -> None:
    rules = [
        _base("LITERAL_TEST", "literal", pattern="خطا", suggestion="خطأ"),
        _base(
            "REGEX_TEST",
            "regex",
            regex=r"(جدا)\s+\1",
            suggestion=r"\1",
            examples={"bad": "جدا جدا", "good": "جدا"},
        ),
        _base(
            "TOKENS_TEST",
            "token_sequence",
            tokens=["من", {"literal": "اجل"}],
            suggestion="من أجل",
            examples={"bad": "من اجل", "good": "من أجل"},
        ),
    ]
    engine = _engine(tmp_path, rules)
    text = "هذا خطا وكان جدا جدا من اجل الاختبار"
    matches = {match.rule_id: match for match in engine.check(text)}
    assert set(matches) == {"LITERAL_TEST", "REGEX_TEST", "TOKENS_TEST"}
    for match in matches.values():
        assert text[match.offset : match.end]
    assert matches["REGEX_TEST"].replacements == ["جدا"]


def test_literal_rules_share_one_linear_aho_corasick_scan(tmp_path: Path) -> None:
    engine = _engine(
        tmp_path,
        [
            _base("SHORT", "literal", pattern="خطا", suggestion="خطأ"),
            _base("LONG", "literal", pattern="خطاب", suggestion="رسالة"),
        ],
    )
    text = "خطا خطاب خطا"

    hits, transitions = engine._literal_matcher.finditer_with_stats(text)

    assert [(hit.rule_index, hit.start, hit.end) for hit in hits] == [
        (0, 0, 3),
        (1, 4, 8),
        (0, 9, 12),
    ]
    assert transitions <= 2 * len(text)


def test_context_rule_requires_both_sides(tmp_path: Path) -> None:
    rule = _base(
        "CONTEXT_TEST",
        "context",
        pattern="عين",
        suggestion="عَيْن",
        context={"before": r"شرب\s+", "after": r"\s+الماء", "window": 30},
        examples={"bad": "شرب عين الماء", "good": "هذه عين جميلة"},
    )
    engine = _engine(tmp_path, [rule])
    assert engine.check("شرب عين الماء")
    assert not engine.check("هذه عين الماء")
    assert not engine.check("شرب عين جميلة")


def test_inline_exception_and_exception_rule_type(tmp_path: Path) -> None:
    literal = _base(
        "BASE_ERROR",
        "literal",
        pattern="سلم",
        suggestion="سلّم",
        exceptions=[{"pattern": "اسم سلم", "scope": "window", "window": 20}],
        examples={"bad": "سلم عليه", "good": "سلّم عليه"},
    )
    suppressor = _base(
        "PROPER_NAME_EXCEPTION",
        "exception",
        pattern="سلمى سلم",
        target_rules=["BASE_ERROR"],
        autofix=False,
        examples={"bad": "سلمى سلم", "good": "سلم"},
    )
    engine = _engine(tmp_path, [literal, suppressor])
    assert engine.check("سلم عليه")
    assert not engine.check("هذا اسم سلم في القائمة")
    assert not engine.check("قالت سلمى سلم بسرعة")


def test_document_consistency_rule(tmp_path: Path) -> None:
    rule = _base(
        "DOC_TERM_CONSISTENCY",
        "document",
        category="style",
        severity="warning",
        autofix=False,
        document={
            "mode": "consistency",
            "variants": ["الذكاء الاصطناعي", "الذكاء الصناعي"],
            "preferred": "الذكاء الاصطناعي",
        },
        suggestions=[],
        examples={
            "bad": "الذكاء الاصطناعي مهم، ويسمى أحيانًا الذكاء الصناعي.",
            "good": "الذكاء الاصطناعي مهم.",
        },
    )
    engine = _engine(tmp_path, [rule])
    text = "يشرح الفصل الذكاء الاصطناعي. ثم يستخدم تعبير الذكاء الصناعي."
    matches = engine.check(text)
    assert len(matches) == 1
    assert text[matches[0].offset : matches[0].end] == "الذكاء الصناعي"
    assert matches[0].replacements == ["الذكاء الاصطناعي"]
    assert not engine.check("الذكاء الصناعي مجال مهم")


def test_profiles_filter_rules(tmp_path: Path) -> None:
    default = _base("DEFAULT_PROFILE", "literal", pattern="خطا", suggestion="خطأ")
    academic = _base(
        "ACADEMIC_PROFILE",
        "literal",
        pattern="احنا",
        suggestion="نحن",
        profiles=["academic"],
        examples={"bad": "احنا ندرس", "good": "نحن ندرس"},
    )
    engine = _engine(tmp_path, [default, academic])
    assert {match.rule_id for match in engine.check("خطا احنا")} == {"DEFAULT_PROFILE"}
    assert {match.rule_id for match in engine.check("خطا احنا", profiles=["academic"])} == {
        "ACADEMIC_PROFILE"
    }


def test_schema_rejects_unknown_fields_and_invalid_confidence(tmp_path: Path) -> None:
    broken = _base("BROKEN_RULE", "literal", pattern="خطا", suggestion="خطأ")
    broken["confidence"] = 1.5
    broken["mystery"] = True
    with pytest.raises(ValueError, match="schema validation"):
        _engine(tmp_path, [broken])


def test_conflict_resolution_uses_priority_confidence_and_span() -> None:
    broad = Match("BROAD", "style", "m", 0, 10, severity="hint", priority=10, confidence=0.7)
    precise = Match(
        "PRECISE", "spelling", "m", 3, 4, severity="error", priority=100, confidence=0.99
    )
    independent = Match("OTHER", "grammar", "m", 20, 3, priority=1, confidence=0.5)
    assert [match.rule_id for match in dedupe([broad, precise, independent])] == [
        "PRECISE",
        "OTHER",
    ]


def test_local_suppression_rule_word_line_and_document() -> None:
    checker = Dhad()
    text = "ذهبت الى المدرسة\nثم رجعت الى البيت"
    assert len([m for m in checker.check(text) if m.rule_id == "HAMZA_ILA"]) == 2
    assert not [
        m
        for m in checker.check(text, suppression=Suppression(rule_ids=frozenset({"HAMZA_ILA"})))
        if m.rule_id == "HAMZA_ILA"
    ]
    word_matches = checker.check(text, suppression=Suppression(words=frozenset({"الى"})))
    assert not [m for m in word_matches if m.rule_id == "HAMZA_ILA"]
    line_matches = checker.check(text, suppression=Suppression(lines=frozenset({2})))
    assert len([m for m in line_matches if m.rule_id == "HAMZA_ILA"]) == 1
    assert checker.check(text, suppression=Suppression(ignore_document=True)) == []


def test_deterministic_core_performance_budget() -> None:
    checker = Dhad()
    text = ("ذهبت إلى المدرسة وقرأت كتابًا مفيدًا، ثم عدت إلى البيت. " * 9)[:500]
    samples = []
    for _ in range(40):
        started = time.perf_counter()
        checker.check(text)
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    assert p95 < 75, f"P95={p95:.2f}ms exceeds the 75ms Phase 1 budget"
