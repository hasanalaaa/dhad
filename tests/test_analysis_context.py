"""Shared document analysis context contracts."""

from dhad import Dhad


def test_analysis_context_owns_one_parse_token_stream_and_sentence_index():
    checker = Dhad(neural_checks=False)
    text = "هذا خطا واضح. ثم كتب مسؤول التقرير."

    context = checker.analysis_context(text, neural_refine=False)

    assert context.text == text
    assert context.parsed is not None
    assert context.parsed.text == text
    assert [token.text for token in context.tokens if token.is_word][:3] == ["هذا", "خطا", "واضح"]
    assert context.sentence_at(text.index("مسؤول")).text.strip() == "ثم كتب مسؤول التقرير"
    assert checker.engine.check(text, context=context) == checker.engine.check(text)


def test_analysis_context_rejects_a_parse_from_another_document():
    checker = Dhad(neural_checks=False)
    parsed = checker.parse("المستند الأول.", neural_refine=False)

    try:
        checker.analysis_context("المستند الثاني.", parsed=parsed)
    except ValueError as error:
        assert "same source text" in str(error)
    else:
        raise AssertionError("A foreign parse must not enter an analysis context")
