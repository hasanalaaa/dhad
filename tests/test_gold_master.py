"""Gold Master rewriting, analytics, templates, SDK and REST contracts."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from dhad import Dhad, RewriteMode, TemplateId, generate_document, list_templates
from dhad.api.models import AnalyticsResponse, RewriteResponse, TemplateGenerateResponse, TemplateListResponse
from dhad.client import DhadClient
from dhad.server import create_app


def checker() -> Dhad:
    return Dhad(neural_checks=False)


@pytest.mark.parametrize("mode", list(RewriteMode))
def test_rewrite_modes_are_offline_bounded_and_preserve_numbers(mode: RewriteMode) -> None:
    text = "في واقع الأمر، أعتقد أن هذا شيء مهم. شلون نراجع 2026 نتيجة؟"
    report = checker().rewrite(text, mode=mode, alternatives=3)
    assert report.offline is True
    assert 1 <= len(report.candidates) <= 3
    assert all(0.0 <= item.confidence <= 1.0 for item in report.candidates)
    assert all(item.meaning_preservation >= 0.72 for item in report.candidates)
    assert all(re.findall(r"\d+", item.text) == ["2026"] for item in report.candidates)
    assert report == checker().rewrite(text, mode=mode, alternatives=3)


def test_rewrite_rejects_invalid_alternative_count() -> None:
    with pytest.raises(ValueError):
        checker().rewrite("نص", alternatives=0)


def test_analytics_heatmap_offsets_and_bounds() -> None:
    text = "هذه جملة واضحة. وهذه جملة أطول، تحتوي تفاصيل عديدة، وتحتاج إلى مراجعة."
    report = checker().analytics_report(text)
    assert report.words > 0
    assert report.sentences == 2
    assert report.estimated_reading_seconds > 0
    assert 0 <= report.clarity_score <= 100
    assert 0 <= report.engagement_score <= 100
    assert 0 <= report.vocabulary_richness <= 100
    for item in report.sentence_heatmap:
        assert text[item.start : item.end].strip() == item.text


def test_templates_expose_product_jobs_and_never_hide_missing_facts() -> None:
    templates = list_templates()
    assert {item.id for item in templates} == set(TemplateId)
    generated = generate_document(
        TemplateId.ACADEMIC_ABSTRACT,
        {"objective": "قياس الأثر"},
        tone="academic",
    )
    assert "results" in generated.missing_fields
    assert "[النتائج الفعلية]" in generated.text
    assert generated.offline is True


def test_local_sdk_has_identical_gold_contracts() -> None:
    client = DhadClient(engine=checker())
    rewrite = client.rewrite("شلون نكتب التقرير؟", mode="formal")
    analytics = client.analytics("هذه جملة واضحة.")
    templates = client.templates()
    generated = client.generate_template(
        "professional_email",
        {
            "recipient": "فريق العمل",
            "subject": "الخطة",
            "context": "اكتملت المراجعة",
            "request": "اعتماد النسخة",
            "sender": "ضاد",
        },
        tone="formal",
    )
    assert isinstance(rewrite, RewriteResponse)
    assert isinstance(analytics, AnalyticsResponse)
    assert isinstance(templates, TemplateListResponse)
    assert isinstance(generated, TemplateGenerateResponse)
    assert rewrite.offline and generated.offline


def test_gold_rest_endpoints_are_strict_and_private() -> None:
    app = create_app(engine=checker(), serve_web=False, serve_sync=False)
    with TestClient(app) as client:
        rewrite = client.post("/api/v1/rewrite", json={"text": "شلون نكتب التقرير؟", "mode": "formal", "alternatives": 2})
        analytics = client.post("/api/v1/analytics", json={"text": "هذه جملة واضحة."})
        templates = client.get("/api/v1/templates")
        generated = client.post(
            "/api/v1/templates/generate",
            json={"template_id": "academic_abstract", "values": {"objective": "قياس الأثر"}, "tone": "academic"},
        )
        invalid = client.post("/api/v1/rewrite", json={"text": "نص", "mode": "unsafe"})
    assert rewrite.status_code == analytics.status_code == templates.status_code == generated.status_code == 200
    assert invalid.status_code == 422
    assert rewrite.headers["cache-control"] == "no-store"
    assert analytics.headers["cache-control"] == "no-store"
    assert RewriteResponse.model_validate(rewrite.json()).offline is True
    assert AnalyticsResponse.model_validate(analytics.json()).words > 0
    assert len(TemplateListResponse.model_validate(templates.json()).templates) == 6
    assert "results" in TemplateGenerateResponse.model_validate(generated.json()).missing_fields
