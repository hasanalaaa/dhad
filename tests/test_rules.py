"""الفحص الآلي لكل قاعدة YAML: مثالها الخاطئ يجب أن يُلتقط، والصحيح لا.

Data-driven verification: every rule's `bad` example MUST trigger that rule,
and its `good` example must NOT. New rules are automatically tested — this is
the contract that keeps linguist contributions safe to merge.
"""

import pytest

from dhad.rules import RuleEngine

ENGINE = RuleEngine()
RULES = {r.id: r for r in ENGINE.rules}


def test_rules_loaded():
    assert len(ENGINE.rules) >= 60, f"Expected >=60 rules, got {len(ENGINE.rules)}"


def test_every_rule_has_examples_and_message():
    for rule in ENGINE.rules:
        assert rule.message, f"{rule.id}: missing message"
        assert rule.examples.get("bad"), f"{rule.id}: missing bad example"
        assert rule.examples.get("good"), f"{rule.id}: missing good example"


@pytest.mark.parametrize("rule_id", list(RULES))
def test_bad_example_triggers(rule_id):
    rule = RULES[rule_id]
    hits = [m for m in rule.apply(rule.examples["bad"]) if m.rule_id == rule_id]
    assert hits, f"{rule_id}: bad example did not trigger: {rule.examples['bad']!r}"


@pytest.mark.parametrize("rule_id", list(RULES))
def test_good_example_clean(rule_id):
    rule = RULES[rule_id]
    hits = [m for m in rule.apply(rule.examples["good"]) if m.rule_id == rule_id]
    assert not hits, f"{rule_id}: good example wrongly flagged: {rule.examples['good']!r}"


def test_word_boundaries_respected():
    """«الى» داخل كلمة أطول يجب ألا يُلتقط."""
    engine = ENGINE
    # "الىوم" ليست كلمة لكنها تختبر الحدود؛ الأهم: لا التقاط داخل كلمات حقيقية
    hits = engine.check("موالي الىسار")
    assert not any(m.rule_id == "HAMZA_ILA" and m.offset == 0 for m in hits)
    # وكلمة «والى» (فعل) يجب ألا تُلتقط لأن «الى» ليست منفصلة
    hits2 = [m for m in engine.check("والى فلان الأمر") if m.rule_id == "HAMZA_ILA"]
    assert not hits2


def test_offsets_point_to_error():
    text = "ذهبت الى المدرسه"
    hits = ENGINE.check(text)
    by_id = {m.rule_id: m for m in hits}
    m1 = by_id["HAMZA_ILA"]
    assert text[m1.offset : m1.end] == "الى"
    m2 = by_id["TAA_MADRASA"]
    assert text[m2.offset : m2.end] == "المدرسه"


def test_replacement_produces_correct_text():
    text = "سأزورك انشاء الله غدًا"
    m = [x for x in ENGINE.check(text) if x.rule_id == "PHRASE_INSHALLAH"][0]
    fixed = text[: m.offset] + m.replacements[0] + text[m.end :]
    assert fixed == "سأزورك إن شاء الله غدًا"


def test_diacritics_block_false_positive():
    """كلمة مشكولة مثل «اذاً»؟ الحدود تشمل الحركات فلا التقاط داخلها."""
    hits = [m for m in ENGINE.check("قرأَ اذاً الكتاب") if m.rule_id == "HAMZA_IDHA"]
    # «اذاً» متبوعة بتنوين — حرف حركة — فلا تُعتبر «اذا» منفصلة
    assert not hits
