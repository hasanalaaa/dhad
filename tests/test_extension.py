"""Manifest V3 extension completeness and executable-JavaScript tests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"


def test_manifest_v3_is_complete_and_minimizes_permanent_host_access():
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert manifest["version"] == "1.0.0"
    assert manifest["version_name"] == "1.0.0 Gold Master"
    assert manifest["background"]["service_worker"] == "background.js"
    assert manifest["host_permissions"] == ["http://127.0.0.1/*", "http://localhost/*"]
    assert "https://*/*" in manifest["optional_host_permissions"]
    assert manifest["content_scripts"][0]["js"] == ["shared.js", "content.js"]
    assert manifest["content_scripts"][0]["css"] == ["content.css"]


def test_every_manifest_resource_exists():
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    paths = {
        manifest["background"]["service_worker"],
        manifest["action"]["default_popup"],
        *manifest["icons"].values(),
    }
    for content in manifest["content_scripts"]:
        paths.update(content["js"])
        paths.update(content["css"])
    for relative in paths:
        target = EXTENSION / relative
        assert target.is_file(), relative
        assert target.stat().st_size > 0


def test_extension_enforces_central_transport_and_safe_action_labels():
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    content = (EXTENSION / "content.js").read_text(encoding="utf-8")
    assert 'importScripts("shared.js")' in background
    assert 'credentials: "omit"' in background
    assert "chrome.permissions.contains" in background
    assert "match.autofix" in content
    assert "تطبيق:" in content
    assert "مراجعة:" in content
    assert "replaceContentEditableRange" in content
    assert "dhad-squiggle" in content


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_all_extension_javascript_parses_in_node():
    for path in sorted(EXTENSION.glob("*.js")):
        subprocess.run(["node", "--check", str(path)], check=True, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_shared_extension_algorithms_execute():
    script = """
      require('./shared.js');
      const s = globalThis.DhadShared;
      if (s.normalizeApiBase('http://127.0.0.1:8010/') !== 'http://127.0.0.1:8010') process.exit(2);
      if (s.applyTextReplacement('ذهبت الى', 5, 3, 'إلى') !== 'ذهبت إلى') process.exit(3);
      const kept = s.nonOverlappingMatches([{offset:0,length:3,priority:1},{offset:0,length:2,priority:0},{offset:4,length:2,priority:0}]);
      if (kept.length !== 2) process.exit(4);
    """
    subprocess.run(
        ["node", "-e", script], cwd=EXTENSION, check=True, capture_output=True, text=True
    )
