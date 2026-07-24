from __future__ import annotations

import os
import plistlib
from pathlib import Path

import pytest

from tools.verify_macos_bundle import VerificationError, verify_static_bundle


def create_bundle(tmp_path: Path, *, identifier: str = "com.dhad.desktop", executable_mode: int = 0o755) -> Path:
    app = tmp_path / "ضاد.app"
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    plist = {
        "CFBundleIdentifier": identifier,
        "CFBundleExecutable": "dhad-desktop",
        "CFBundlePackageType": "APPL",
        "CFBundleName": "Dhad",
        "CFBundleDisplayName": "ضاد",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "10.15",
    }
    with (app / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump(plist, stream)
    executable = macos / "dhad-desktop"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(executable_mode)
    (resources / "icon.icns").write_bytes(b"icns")
    return app


def test_static_bundle_verifier_handles_arabic_bundle_paths(tmp_path: Path):
    app = create_bundle(tmp_path)
    executable, plist = verify_static_bundle(app, "aarch64")
    assert executable.name == "dhad-desktop"
    assert plist["CFBundleDisplayName"] == "ضاد"


def test_static_bundle_verifier_rejects_identifier_conflicts(tmp_path: Path):
    app = create_bundle(tmp_path, identifier="com.dhad.desktop.app")
    with pytest.raises(VerificationError, match="CFBundleIdentifier"):
        verify_static_bundle(app)


@pytest.mark.skipif(os.name == "nt", reason="POSIX execute bits are not meaningful on Windows")
def test_static_bundle_verifier_rejects_non_executable_binary(tmp_path: Path):
    app = create_bundle(tmp_path, executable_mode=0o644)
    with pytest.raises(VerificationError, match="not executable"):
        verify_static_bundle(app)
