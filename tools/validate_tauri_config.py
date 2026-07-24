#!/usr/bin/env python3
"""Strict compatibility checks for Dhad's Tauri CLI 2.11.x configuration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROFILE = "tauri-cli 2.11.x"

ROOT_KEYS = {"$schema", "productName", "version", "identifier", "mainBinaryName", "build", "app", "bundle", "plugins"}
BUILD_KEYS = {"beforeBuildCommand", "beforeDevCommand", "devUrl", "frontendDist", "additionalWatchFolders", "removeUnusedCommands", "windows"}
BUILD_WINDOWS_KEYS = {"staticVCRuntime"}
APP_KEYS = {"windows", "security", "trayIcon", "withGlobalTauri", "enableGTKAppId", "macOSPrivateApi"}
SECURITY_KEYS = {"csp", "devCsp", "freezePrototype", "assetProtocol", "dangerousDisableAssetCspModification", "pattern", "capabilities"}
WINDOW_KEYS = {
    "label", "create", "url", "userAgent", "fileDropEnabled", "dragDropEnabled", "center", "x", "y", "width", "height",
    "minWidth", "minHeight", "maxWidth", "maxHeight", "resizable", "maximizable", "minimizable", "closable", "title",
    "fullscreen", "focus", "focusable", "transparent", "maximized", "visible", "decorations", "alwaysOnBottom", "alwaysOnTop",
    "visibleOnAllWorkspaces", "contentProtected", "skipTaskbar", "theme", "titleBarStyle", "trafficLightPosition", "hiddenTitle",
    "acceptFirstMouse", "tabbingIdentifier", "additionalBrowserArgs", "shadow", "windowEffects", "incognito", "parent", "proxyUrl",
    "zoomHotkeysEnabled", "browserExtensionsEnabled", "useHttpsScheme", "backgroundColor", "backgroundThrottling", "javascriptDisabled",
    "allowLinkPreview", "dataDirectory", "dataStoreIdentifier", "scrollBarStyle", "preventOverflow", "devtools"
}
WINDOW_EFFECT_KEYS = {"effects", "state", "radius", "color"}
BUNDLE_KEYS = {
    "active", "targets", "createUpdaterArtifacts", "publisher", "homepage", "icon", "resources", "copyright", "category",
    "shortDescription", "longDescription", "externalBin", "fileAssociations", "linux", "macOS", "windows", "iOS", "android",
    "useLocalToolsDir"
}
MACOS_KEYS = {
    "frameworks", "minimumSystemVersion", "exceptionDomain", "signingIdentity", "providerShortName", "entitlements", "infoPlist",
    "dmg", "hardenedRuntime", "files", "bundleVersion"
}
DMG_KEYS = {"background", "windowSize", "appPosition", "applicationFolderPosition"}
POSITION_KEYS = {"x", "y"}
SIZE_KEYS = {"width", "height"}
WINDOWS_BUNDLE_KEYS = {
    "digestAlgorithm", "certificateThumbprint", "timestampUrl", "tsp", "webviewInstallMode", "wix", "nsis", "signCommand",
    "allowDowngrades", "minimumWebview2Version"
}
WEBVIEW_INSTALL_KEYS = {"type", "silent", "path"}
NSIS_KEYS = {
    "template", "headerImage", "sidebarImage", "installerIcon", "installMode", "languages", "customLanguageFiles",
    "displayLanguageSelector", "compression", "startMenuFolder", "installerHooks", "minimumWebview2Version", "uninstallerIcon",
    "uninstallerHeaderImage"
}
WIX_KEYS = {
    "language", "template", "fragmentPaths", "componentGroupRefs", "componentRefs", "featureGroupRefs", "featureRefs", "mergeRefs",
    "skipWebviewInstall", "license", "enableElevatedUpdateTask", "bannerPath", "dialogImagePath", "fipsCompliant", "upgradeCode"
}

FORBIDDEN_PATHS = {
    "app.windows[].noRedirectionBitmap": "unsupported by the pinned Tauri 2.11 compatibility profile",
    "app.security.headers": "custom response headers are not accepted in this Tauri config schema",
    "bundle.windows.bundleVCRuntime": "use the schema default/build toolchain instead of this unsupported bundle key",
}


def _unknown(obj: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if not isinstance(obj, dict):
        errors.append(f"{path} must be an object")
        return
    for key in sorted(set(obj) - allowed):
        errors.append(f"{path}.{key} is not allowed by {PROFILE}")


def validate_tauri_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _unknown(config, ROOT_KEYS, "$", errors)
    if config.get("$schema") != "https://schema.tauri.app/config/2":
        errors.append("$.$schema must be https://schema.tauri.app/config/2")

    build = config.get("build", {})
    _unknown(build, BUILD_KEYS, "$.build", errors)
    if "windows" in build:
        _unknown(build["windows"], BUILD_WINDOWS_KEYS, "$.build.windows", errors)

    app = config.get("app", {})
    _unknown(app, APP_KEYS, "$.app", errors)
    security = app.get("security", {})
    _unknown(security, SECURITY_KEYS, "$.app.security", errors)
    csp = security.get("csp")
    if csp is not None and not isinstance(csp, (str, dict)):
        errors.append("$.app.security.csp must be a string, object, or null")
    if isinstance(csp, dict):
        for directive, value in csp.items():
            if not isinstance(directive, str) or not isinstance(value, (str, list)):
                errors.append(f"$.app.security.csp.{directive} must be a string or string array")
            elif isinstance(value, list) and not all(isinstance(item, str) for item in value):
                errors.append(f"$.app.security.csp.{directive} contains a non-string source")

    windows = app.get("windows", [])
    if not isinstance(windows, list):
        errors.append("$.app.windows must be an array")
    else:
        for index, window in enumerate(windows):
            _unknown(window, WINDOW_KEYS, f"$.app.windows[{index}]", errors)
            if isinstance(window, dict) and "noRedirectionBitmap" in window:
                errors.append(f"$.app.windows[{index}].noRedirectionBitmap: {FORBIDDEN_PATHS['app.windows[].noRedirectionBitmap']}")
            if isinstance(window, dict) and "windowEffects" in window:
                _unknown(window["windowEffects"], WINDOW_EFFECT_KEYS, f"$.app.windows[{index}].windowEffects", errors)

    if isinstance(security, dict) and "headers" in security:
        errors.append(f"$.app.security.headers: {FORBIDDEN_PATHS['app.security.headers']}")

    bundle = config.get("bundle", {})
    _unknown(bundle, BUNDLE_KEYS, "$.bundle", errors)
    macos = bundle.get("macOS", {})
    if macos:
        _unknown(macos, MACOS_KEYS, "$.bundle.macOS", errors)
        dmg = macos.get("dmg", {})
        if dmg:
            _unknown(dmg, DMG_KEYS, "$.bundle.macOS.dmg", errors)
            for name in ("appPosition", "applicationFolderPosition"):
                if name in dmg:
                    _unknown(dmg[name], POSITION_KEYS, f"$.bundle.macOS.dmg.{name}", errors)
            if "windowSize" in dmg:
                _unknown(dmg["windowSize"], SIZE_KEYS, "$.bundle.macOS.dmg.windowSize", errors)

    win_bundle = bundle.get("windows", {})
    if win_bundle:
        _unknown(win_bundle, WINDOWS_BUNDLE_KEYS, "$.bundle.windows", errors)
        if "bundleVCRuntime" in win_bundle:
            errors.append(f"$.bundle.windows.bundleVCRuntime: {FORBIDDEN_PATHS['bundle.windows.bundleVCRuntime']}")
        if "webviewInstallMode" in win_bundle:
            _unknown(win_bundle["webviewInstallMode"], WEBVIEW_INSTALL_KEYS, "$.bundle.windows.webviewInstallMode", errors)
        if win_bundle.get("nsis") is not None:
            _unknown(win_bundle["nsis"], NSIS_KEYS, "$.bundle.windows.nsis", errors)
        if win_bundle.get("wix") is not None:
            _unknown(win_bundle["wix"], WIX_KEYS, "$.bundle.windows.wix", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("src-tauri/tauri.conf.json"))
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Tauri config parse failed: {exc}", file=sys.stderr)
        return 1
    errors = validate_tauri_config(config)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Tauri config compatibility: PASS ({PROFILE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
