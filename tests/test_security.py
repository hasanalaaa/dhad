"""Phase 11 production HTTP security and deployment tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dhad import Dhad
from dhad.security import SecuritySettings, TokenBucketLimiter
from dhad.server import create_app

ROOT = Path(__file__).resolve().parents[1]


def settings(**changes) -> SecuritySettings:
    values = {
        "max_text_characters": 50_000,
        "max_request_bytes": 262_144,
        "rate_limit_requests": 120,
        "rate_limit_window_seconds": 60.0,
        "rate_limit_enabled": True,
        "rate_limit_max_identities": 50_000,
        "api_keys": (),
    }
    values.update(changes)
    return SecuritySettings(**values)


def test_api_key_authentication_supports_x_api_key_and_bearer():
    client = TestClient(
        create_app(Dhad(), serve_web=False, security_settings=settings(api_keys=("secret-key",)))
    )
    assert client.get("/api/health").status_code == 200
    denied = client.post("/check", json={"text": "ذهبت الى"})
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "invalid_api_key"
    assert "secret-key" not in denied.text
    direct = client.post("/check", json={"text": "ذهبت الى"}, headers={"X-API-Key": "secret-key"})
    bearer = client.post(
        "/check", json={"text": "ذهبت الى"}, headers={"Authorization": "Bearer secret-key"}
    )
    assert direct.status_code == bearer.status_code == 200


def test_token_bucket_rate_limit_returns_retry_headers():
    client = TestClient(
        create_app(
            Dhad(),
            serve_web=False,
            security_settings=settings(rate_limit_requests=2, rate_limit_window_seconds=600),
        )
    )
    first = client.post("/check", json={"text": "نص صحيح"})
    second = client.post("/check", json={"text": "نص صحيح"})
    third = client.post("/check", json={"text": "نص صحيح"})
    assert first.status_code == second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limit_exceeded"
    assert int(third.headers["retry-after"]) >= 1
    assert third.headers["x-ratelimit-limit"] == "2"


def test_payload_byte_limit_rejects_before_json_or_nlp_parsing():
    client = TestClient(
        create_app(
            Dhad(),
            serve_web=False,
            security_settings=settings(max_request_bytes=1024),
        )
    )
    response = client.post("/check", json={"text": "ن" * 700})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_text_character_limit_applies_to_json_and_languagetool_forms():
    configured = settings(max_text_characters=10)
    client = TestClient(create_app(Dhad(), serve_web=False, security_settings=configured))
    json_response = client.post("/check", json={"text": "ن" * 11})
    form_response = client.post("/v2/check", data={"text": "ن" * 11})
    assert json_response.status_code == form_response.status_code == 413
    assert "10" in form_response.json()["detail"]


def test_validation_response_never_echoes_user_text():
    client = TestClient(create_app(Dhad(), serve_web=False, security_settings=settings()))
    secret = "very-private-user-text@example.com"
    response = client.post("/check", json={"text": "نص", "unknown": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_analysis_responses_have_no_store_and_security_headers():
    client = TestClient(create_app(Dhad(), serve_web=False, security_settings=settings()))
    response = client.post("/check", json={"text": "نص صحيح"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"


def test_security_settings_load_and_validate_environment(monkeypatch):
    monkeypatch.setenv("DHAD_API_KEYS", "alpha,beta,alpha")
    monkeypatch.setenv("DHAD_RATE_LIMIT_REQUESTS", "42")
    monkeypatch.setenv("DHAD_MAX_TEXT_CHARACTERS", "1234")
    loaded = SecuritySettings.from_env()
    assert loaded.api_keys == ("alpha", "beta")
    assert loaded.rate_limit_requests == 42
    assert loaded.max_text_characters == 1234
    assert loaded.authentication_enabled is True


def test_token_bucket_refills_deterministically():
    now = [100.0]
    limiter = TokenBucketLimiter(2, 10.0, clock=lambda: now[0])

    import asyncio

    async def consume_three():
        assert (await limiter.consume("client"))[0] is True
        assert (await limiter.consume("client"))[0] is True
        assert (await limiter.consume("client"))[0] is False
        now[0] += 5.0
        return await limiter.consume("client")

    allowed, remaining, retry_after = asyncio.run(consume_three())
    assert allowed is True and remaining == 0 and retry_after == 0.0


def test_production_deployment_files_are_hardened_and_complete():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    gunicorn = (ROOT / "gunicorn_conf.py").read_text(encoding="utf-8")
    assert dockerfile.count("FROM ") >= 2
    assert "USER dhad" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "--no-index" in dockerfile
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop" in compose
    assert "UvicornWorker" in gunicorn
    assert "preload_app = False" in gunicorn



def test_token_bucket_identity_state_is_hard_bounded():
    import asyncio

    limiter = TokenBucketLimiter(10, 60.0, max_identities=3)

    async def populate():
        for identity in ("a", "b", "c", "d", "e"):
            assert (await limiter.consume(identity))[0] is True

    asyncio.run(populate())
    assert list(limiter._buckets) == ["c", "d", "e"]


def test_security_settings_load_rate_limit_identity_cap(monkeypatch):
    monkeypatch.setenv("DHAD_RATE_LIMIT_MAX_IDENTITIES", "321")
    assert SecuritySettings.from_env().rate_limit_max_identities == 321


def test_middleware_rejects_ambiguous_http_framing():
    import asyncio

    from dhad.security import ProductionSecurityMiddleware

    calls = []

    async def downstream(scope, receive, send):
        calls.append(scope)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def exercise(headers):
        messages = []

        async def send(message):
            messages.append(message)

        middleware = ProductionSecurityMiddleware(downstream, settings=settings())
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/check",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
        }
        await middleware(scope, receive, send)
        return messages

    duplicate = asyncio.run(
        exercise([(b"content-length", b"1"), (b"content-length", b"1")])
    )
    ambiguous = asyncio.run(
        exercise([(b"content-length", b"1"), (b"transfer-encoding", b"chunked")])
    )
    assert duplicate[0]["status"] == 400
    assert ambiguous[0]["status"] == 400
    assert calls == []
