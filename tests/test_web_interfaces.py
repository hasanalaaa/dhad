"""Phase 10 web/PWA integration contracts."""

from __future__ import annotations

import json
from fastapi.testclient import TestClient

from dhad import Dhad, __version__
from dhad.server import WEB_ASSETS_DIR, WEB_DIR, create_app


def test_web_dashboard_and_static_assets_are_served():
    client = TestClient(create_app(Dhad()))
    root = client.get("/")
    assert root.status_code == 200
    assert "ضاد" in root.text
    assert "/static/app.css" in root.text
    assert "/static/app.js" in root.text
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/icons/icon-192.png").headers["content-type"] == "image/png"


def test_pwa_manifest_and_service_worker_are_valid_and_privacy_preserving():
    client = TestClient(create_app(Dhad()))
    manifest_response = client.get("/manifest.webmanifest")
    assert manifest_response.status_code == 200
    assert manifest_response.headers["content-type"].startswith("application/manifest+json")
    manifest = manifest_response.json()
    assert manifest["dir"] == "rtl"
    assert manifest["display"] == "standalone"
    assert {item["sizes"] for item in manifest["icons"]} == {"192x192", "512x512"}

    worker = client.get("/service-worker.js")
    assert worker.status_code == 200
    assert worker.headers["service-worker-allowed"] == "/"
    assert worker.headers["cache-control"] == "no-cache"
    assert "Never cache text-bearing analysis requests" in worker.text
    assert "API_PREFIXES" in worker.text


def test_dashboard_calls_all_required_phase9_endpoints():
    source = (WEB_DIR / "assets" / "app.js").read_text(encoding="utf-8")
    for endpoint in ("/api/v1/check", "/api/v1/style", "/api/v1/dialect", "/api/v1/diacritize"):
        assert endpoint in source
    assert "match.autofix" in source
    assert (
        "requires approval" not in source.lower()
    )  # Arabic UI, no accidental English placeholder.


def test_api_only_app_does_not_expose_web_assets():
    client = TestClient(create_app(Dhad(), serve_web=False))
    assert client.get("/").status_code == 404
    assert client.get("/static/app.js").status_code == 404
    assert client.post("/check", json={"text": "ذهبت الى المدرسة"}).status_code == 200


def test_security_headers_and_local_cors_defaults():
    client = TestClient(create_app(Dhad()))
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "microphone=()" in response.headers["permissions-policy"]

    local = client.options(
        "/check",
        headers={
            "Origin": "http://127.0.0.1:8010",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert local.status_code == 200
    assert local.headers["access-control-allow-origin"] == "http://127.0.0.1:8010"

    extension = client.options(
        "/check",
        headers={
            "Origin": "chrome-extension://abcdefghijklmnop",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert extension.status_code == 200
    assert extension.headers["access-control-allow-origin"] == "chrome-extension://abcdefghijklmnop"

    untrusted = client.options(
        "/check",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in untrusted.headers


def test_wildcard_cors_is_rejected():
    try:
        create_app(Dhad(), cors_origins=["*"])
    except ValueError as exc:
        assert "forbidden" in str(exc)
    else:
        raise AssertionError("Wildcard CORS must not be accepted")


def test_pwa_manifest_files_exist_on_disk():
    manifest = json.loads((WEB_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
    for item in manifest["icons"]:
        path = WEB_ASSETS_DIR / item["src"].removeprefix("/static/")
        assert path.is_file() and path.stat().st_size > 100
    assert __version__ == "1.0.15"
