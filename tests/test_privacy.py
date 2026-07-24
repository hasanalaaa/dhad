"""Phase 11 offset-preserving PII privacy tests."""

from __future__ import annotations

import logging
import time

from dhad import Dhad
from dhad.privacy import PIIKind, PrivacyEngine, PrivacyLogFilter


def test_mask_detects_email_phone_url_without_changing_length():
    text = "راسل user@example.com أو +964 770 123 4567 وزر https://example.com/path، ثم اكتب الى."
    session = PrivacyEngine().mask(text)
    assert len(session.masked_text) == len(text)
    assert [span.kind for span in session.spans] == [PIIKind.EMAIL, PIIKind.PHONE, PIIKind.URL]
    assert all(span.original not in session.masked_text for span in session.spans)
    assert session.restore(session.masked_text) == text
    assert session.spans[-1].original == "https://example.com/path"
    assert text[session.spans[-1].end] == "،"


def test_mask_uses_unique_reversible_tokens_for_repeated_pii():
    text = "a@example.com ثم a@example.com"
    session = PrivacyEngine().mask(text)
    assert len(session.spans) == 2
    assert session.spans[0].sentinel != session.spans[1].sentinel
    generated = "مُقَدِّمَة " + session.masked_text
    assert session.restore(generated) == "مُقَدِّمَة " + text


def test_masked_text_builds_a_sorted_overlap_index_once():
    text = "a@example.com ثم +9647701234567 ثم https://example.com"
    session = PrivacyEngine().mask(text)

    assert session.span_starts == tuple(span.start for span in session.spans)
    assert session.overlaps(text.index("+964"), text.index("+964") + 1)
    assert not session.overlaps(text.index("ثم"), text.index("ثم") + 2)


def test_restoring_maximum_pii_spans_is_linear():
    text = " ".join(f"user{index}@x.com" for index in range(4096))
    session = PrivacyEngine().mask(text)
    started = time.perf_counter()

    restored = session.restore(session.masked_text)

    assert restored == text
    assert time.perf_counter() - started < 0.025


def test_engine_never_emits_diagnostics_inside_pii_and_preserves_later_offsets():
    text = "البريد user@example.com ثم ذهبت الى المدرسه"
    matches = Dhad().check(text)
    assert [item.rule_id for item in matches] == ["HAMZA_ILA", "TAA_MADRASA"]
    assert all(text[item.offset : item.end] in {"الى", "المدرسه"} for item in matches)
    assert matches[0].offset == text.index("الى")


def test_parse_restores_public_text_and_excludes_pii_tokens():
    text = "كتب الطالب إلى user@example.com ثم عاد"
    parsed = Dhad().parse(text)
    assert parsed.text == text
    assert "user@example.com" in parsed.sentences[0].text
    assert all("@" not in token.text for sentence in parsed.sentences for token in sentence.tokens)
    returned = [token for sentence in parsed.sentences for token in sentence.tokens]
    assert next(token for token in returned if token.text == "عاد").start == text.index("عاد")


def test_diacritization_restores_pii_verbatim_after_length_changing_generation():
    text = "كتب user@example.com الدرس"
    result = Dhad().diacritize(text, mode="full")
    assert result.source_text == text
    assert "user@example.com" in result.text
    assert "كَتَبَ" in result.text
    assert result.text.count("user@example.com") == 1


def test_style_dialect_and_semantics_restore_original_text():
    engine = Dhad()
    text = "user@example.com وفي هذا الوقت الراهن نبدأ"
    assert engine.style_report(text).text == text
    dialect = engine.dialect_report("عايزين نلعب مع user@example.com")
    assert dialect.text == "عايزين نلعب مع user@example.com"
    assert "user@example.com" in dialect.converted_text
    semantics = engine.semantic_report("مسؤول ثم user@example.com ثم مسئول")
    assert semantics.text == "مسؤول ثم user@example.com ثم مسئول"
    assert semantics.matches and semantics.matches[0].offset == semantics.text.rindex("مسئول")


def test_privacy_can_be_explicitly_disabled_for_controlled_internal_use():
    text = "user@example.com"
    protected = Dhad().parse(text)
    unprotected = Dhad(pii_masking=False).parse(text)
    assert protected.text == unprotected.text == text
    assert protected.sentences
    assert unprotected.sentences


def test_log_filter_redacts_common_pii_without_dropping_record():
    record = logging.LogRecord(
        "dhad.test",
        logging.INFO,
        __file__,
        1,
        "contact user@example.com at +9647701234567",
        (),
        None,
    )
    assert PrivacyLogFilter().filter(record) is True
    message = record.getMessage()
    assert "user@example.com" not in message
    assert "+9647701234567" not in message
    assert "[REDACTED_EMAIL]" in message and "[REDACTED_PHONE]" in message
