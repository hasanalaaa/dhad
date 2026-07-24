"""Phase 9 REST API and Python SDK contracts."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from dhad import Dhad, __version__
from dhad.client import DhadClient
from dhad.server import create_app


client = TestClient(create_app(Dhad()))


def test_openapi_documents_every_phase9_endpoint():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in ("/check", "/parse", "/diacritize", "/style", "/dialect"):
        assert path in paths
        assert "post" in paths[path]


def test_check_endpoint_has_strict_lossless_match_contract():
    response = client.post("/api/v1/check", json={"text": "ذهبت الى المدرسه"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == __version__
    assert [item["rule_id"] for item in payload["matches"]] == ["HAMZA_ILA", "TAA_MADRASA"]
    first = payload["matches"][0]
    assert first["replacements"] == ["إلى"]
    assert first["autofix"] is True
    assert first["category"] == "spelling"
    assert first["offset"] == 5 and first["length"] == 3


def test_check_endpoint_supports_suppression_and_category_filter():
    response = client.post(
        "/check",
        json={
            "text": "ذهبت الى المدرسه",
            "disabled_rules": ["HAMZA_ILA"],
            "disabled_categories": ["style"],
        },
    )
    assert response.status_code == 200
    assert [item["rule_id"] for item in response.json()["matches"]] == ["TAA_MADRASA"]


def test_request_models_reject_unknown_fields():
    response = client.post("/check", json={"text": "نص", "surprise": True})
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_parse_endpoint_preserves_offsets_and_analysis_tree():
    response = client.post("/parse", json={"text": "كتب الطالب الدرس"})
    assert response.status_code == 200
    sentence = response.json()["sentences"][0]
    assert sentence["text"] == "كتب الطالب الدرس"
    assert sentence["tokens"][0]["text"] == "كتب"
    assert sentence["tokens"][0]["analysis"]["lemma"]
    assert sentence["tokens"][0]["start"] == 0
    assert sentence["irab"][0]["token_index"] == 0
    assert 0.0 <= sentence["confidence"] <= 1.0


def test_diacritize_endpoint_uses_explicit_mode():
    response = client.post("/diacritize", json={"text": "كتب الطالب", "mode": "core"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "core"
    assert payload["source_text"] == "كتب الطالب"
    assert payload["text"] != payload["source_text"]
    assert all(item["mode"] == "core" for item in payload["tokens"])


def test_style_endpoint_keeps_subjective_suggestions_non_autofix():
    response = client.post(
        "/style", json={"text": "وفي هذا الوقت الراهن نبدأ", "profile": "general"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "general"
    assert payload["matches"]
    assert all(
        item["category"] == "style" and item["autofix"] is False for item in payload["matches"]
    )
    assert 0.0 <= payload["readability"]["clarity_score"] <= 100.0


def test_dialect_endpoint_returns_detection_and_contextual_conversion():
    response = client.post("/dialect", json={"text": "عايزين نلعب"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["primary"] == "egyptian"
    assert payload["converted_text"] == "نريد أن نلعب"
    assert payload["conversions"][0]["morphology_validated"] is True
    assert payload["conversions"][0]["syntax_validated"] is True


def test_health_and_languagetool_backward_compatibility():
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["version"] == __version__
    legacy = client.post("/v2/check", data={"text": "ذهبت الى المدرسه"})
    assert legacy.status_code == 200
    assert legacy.json()["software"]["name"] == "Dhad"
    assert legacy.json()["matches"][0]["rule"]["id"] == "HAMZA_ILA"


def test_local_sdk_returns_same_validated_contracts():
    sdk = DhadClient(engine=Dhad())
    checked = sdk.check("ذهبت الى المدرسه")
    parsed = sdk.parse("كتب الطالب الدرس")
    dialect = sdk.dialect("عايزين نلعب")
    assert checked.version == __version__
    assert checked.matches[0].rule_id == "HAMZA_ILA"
    assert parsed.sentences[0].tokens[0].analysis is not None
    assert dialect.converted_text == "نريد أن نلعب"


def test_async_sdk_runs_without_blocking_contract_changes():
    sdk = DhadClient(engine=Dhad())

    async def execute():
        checked, parsed = await asyncio.gather(
            sdk.acheck("ذهبت الى المدرسه"),
            sdk.aparse("كتب الطالب الدرس"),
        )
        return checked, parsed

    checked, parsed = asyncio.run(execute())
    assert checked.matches[0].rule_id == "HAMZA_ILA"
    assert parsed.sentences
