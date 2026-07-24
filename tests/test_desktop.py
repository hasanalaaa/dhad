"""Desktop launcher and mobile-PWA foundation tests."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from dhad.desktop import LocalServer, browser_app_command, reserve_loopback_port

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_reserve_loopback_port_returns_bindable_range():
    port = reserve_loopback_port()
    assert 1 <= port <= 65535


def test_desktop_server_rejects_public_bindings_and_invalid_ports():
    with pytest.raises(ValueError, match="loopback"):
        LocalServer("0.0.0.0", 8010)
    with pytest.raises(ValueError, match="port"):
        LocalServer("127.0.0.1", 0)


def test_chromium_app_command_uses_explicit_executable(tmp_path):
    executable = tmp_path / ("browser.exe" if sys.platform == "win32" else "browser")
    executable.write_bytes(b"binary")
    executable.chmod(0o755)
    command = browser_app_command("http://127.0.0.1:8010", executable=str(executable))
    assert command is not None
    assert command[0] == str(executable)
    assert "--app=http://127.0.0.1:8010" in command
    assert any(item.startswith("--user-data-dir=") for item in command)


def test_desktop_and_mobile_documentation_describe_real_foundations():
    desktop = (PROJECT_ROOT / "desktop" / "README.md").read_text(encoding="utf-8")
    mobile = (PROJECT_ROOT / "mobile" / "README.md").read_text(encoding="utf-8")
    assert "dhad-desktop" in desktop
    assert "pywebview" in desktop
    assert "PWA" in mobile
    assert "عدم تخزين" in mobile


def test_console_entry_points_are_declared():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dhad-desktop = "dhad.desktop:main"' in pyproject
    assert 'desktop = ["pywebview>=5.1"]' in pyproject
