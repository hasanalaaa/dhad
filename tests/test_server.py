from fastapi.testclient import TestClient

from dhad.server import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok" and data["rules"] >= 60


def test_languages():
    r = client.get("/v2/languages")
    assert r.json()[0]["code"] == "ar"


def test_check_languagetool_shape():
    r = client.post("/v2/check", data={"text": "ذهبت الى المدرسه", "language": "ar"})
    assert r.status_code == 200
    data = r.json()
    # LanguageTool contract keys
    assert "software" in data and "language" in data and "matches" in data
    assert data["software"]["name"] == "Dhad"
    ms = data["matches"]
    assert len(ms) == 2
    m = ms[0]
    for key in ("message", "offset", "length", "replacements", "rule", "context"):
        assert key in m
    assert m["replacements"][0]["value"] == "إلى"
    assert m["rule"]["category"]["id"] == "SPELLING"
    # offsets must slice the original text correctly
    text = "ذهبت الى المدرسه"
    assert text[m["offset"] : m["offset"] + m["length"]] == "الى"


def test_check_clean_text():
    r = client.post("/v2/check", data={"text": "ذهبت إلى المدرسة"})
    assert r.json()["matches"] == []


def test_editor_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "ضاد" in r.text
