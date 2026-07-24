"""Apex writing-intelligence, custom lexicon, and API contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dhad import Dhad, Suppression, WritingTarget
from dhad.api.models import IntelligenceResponse
from dhad.client import DhadClient
from dhad.server import create_app


def _checker() -> Dhad:
    return Dhad(neural_checks=False)


def test_intelligence_report_combines_tone_dialect_readability_and_explanations() -> None:
    text = (
        "تشير البيانات إلى تحسن النتائج. "
        "وفي هذا الوقت الراهن نراجع الخطة. "
        "شلون نكتب الخلاصة الرسمية؟"
    )
    report = _checker().intelligence_report(text, style_profile="academic")

    assert report.text == text
    assert report.style.profile.value == "academic"
    assert report.style.readability.words > 0
    assert report.vocabulary.words == report.style.readability.words
    assert report.vocabulary.unique_words <= report.vocabulary.words
    assert 0.0 <= report.vocabulary.complexity_score <= 100.0
    assert report.dialect.converted_text != text
    assert "كيف" in report.dialect.converted_text
    assert {chip.target for chip in report.suggestion_chips} == set(WritingTarget)
    assert all(chip.actions for chip in report.suggestion_chips)
    assert len(report.explanations) == len(report.matches)
    assert all(text[item.offset : item.offset + item.length] == item.source_text for item in report.explanations)
    assert all(item.reasoning and item.why_it_matters for item in report.explanations)


def test_intelligence_empty_document_has_stable_zero_metrics() -> None:
    report = _checker().intelligence_report("")
    metrics = report.vocabulary
    assert metrics.words == 0
    assert metrics.unique_words == 0
    assert metrics.type_token_ratio == 0.0
    assert metrics.complexity_score == 0.0
    assert metrics.band == "accessible"
    assert report.explanations == ()


def test_custom_lexicon_and_rule_override_share_the_standard_suppression_pipeline() -> None:
    checker = _checker()
    text = "ذهبت الى السوق في هذا الوقت الراهن."
    baseline = checker.intelligence_report(text)
    assert {item.rule_id for item in baseline.matches} >= {
        "HAMZA_ILA",
        "STYLE_REDUNDANT_CURRENT_TIME",
    }

    report = checker.intelligence_report(
        text,
        suppression=Suppression(
            words=frozenset({"الى"}),
            rule_ids=frozenset({"STYLE_REDUNDANT_CURRENT_TIME"}),
        ),
    )
    assert "HAMZA_ILA" not in {item.rule_id for item in report.matches}
    assert "STYLE_REDUNDANT_CURRENT_TIME" not in {item.rule_id for item in report.matches}
    assert {item.rule_id for item in report.explanations} == {
        item.rule_id for item in report.matches
    }


def test_intelligence_rest_api_is_strict_and_applies_local_overrides() -> None:
    application = create_app(engine=_checker(), serve_web=False, serve_sync=False)
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/intelligence",
            json={
                "text": "ذهبت الى السوق. شلون نكتب التقرير؟",
                "profile": "administrative",
                "custom_words": ["الى"],
                "disabled_rules": [],
            },
        )
    assert response.status_code == 200
    payload = IntelligenceResponse.model_validate(response.json())
    assert payload.style.profile == "administrative"
    assert payload.dialect.converted_text != payload.text
    assert "HAMZA_ILA" not in {item.rule_id for item in payload.matches}
    assert payload.suggestion_chips
    assert len(payload.explanations) == len(payload.matches)


def test_check_api_accepts_custom_words_without_persisting_them() -> None:
    application = create_app(engine=_checker(), serve_web=False, serve_sync=False)
    with TestClient(application) as client:
        suppressed = client.post(
            "/api/v1/check",
            json={"text": "ذهبت الى السوق", "custom_words": ["الى"]},
        )
        baseline = client.post("/api/v1/check", json={"text": "ذهبت الى السوق"})
    assert suppressed.status_code == 200
    assert baseline.status_code == 200
    assert "HAMZA_ILA" not in {item["rule_id"] for item in suppressed.json()["matches"]}
    assert "HAMZA_ILA" in {item["rule_id"] for item in baseline.json()["matches"]}


def test_sdk_exposes_identical_local_intelligence_contract() -> None:
    response = DhadClient(engine=_checker()).intelligence(
        "ذهبت الى السوق. شلون نكتب التقرير؟",
        profile="administrative",
        custom_words=["الى"],
    )
    assert isinstance(response, IntelligenceResponse)
    assert response.style.profile == "administrative"
    assert "HAMZA_ILA" not in {item.rule_id for item in response.matches}
    assert response.vocabulary.words > 0
