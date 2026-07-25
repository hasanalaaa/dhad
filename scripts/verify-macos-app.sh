#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '[Dhad Desktop] ERROR: native macOS bundle verification must run on macOS.\n' >&2
  exit 1
fi

TEMP_ROOT=""
MOUNT_POINT=""
cleanup() {
  if [[ -n "$MOUNT_POINT" && -d "$MOUNT_POINT" ]]; then
    hdiutil detach -quiet "$MOUNT_POINT" >/dev/null 2>&1 || hdiutil detach -force -quiet "$MOUNT_POINT" >/dev/null 2>&1 || true
  fi
  if [[ -n "$TEMP_ROOT" && -d "$TEMP_ROOT" ]]; then
    rm -rf "$TEMP_ROOT"
  fi
}
trap cleanup EXIT

first_match() {
  local pattern="$1"
  find target -type f -path "$pattern" -print 2>/dev/null | LC_ALL=C sort | head -n 1
}

first_app() {
  find "$1" -type d -name '*.app' -print 2>/dev/null | LC_ALL=C sort | head -n 1
}

APP_PATH="${DHAD_MACOS_APP_PATH:-}"
if [[ -z "$APP_PATH" ]]; then
  APP_PATH="$(first_app target || true)"
fi

# Tauri's DMG bundler intentionally removes the intermediate bundle after the
# image is created. Verify the exact app shipped inside the DMG instead of
# treating that cleanup as a build failure.
if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  DMG_PATH="${DHAD_MACOS_DMG_PATH:-$(first_match '*/release/bundle/dmg/*.dmg' || true)}"
  if [[ -n "$DMG_PATH" && -f "$DMG_PATH" ]]; then
    TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dhad-macos-verify.XXXXXX")"
    MOUNT_POINT="$TEMP_ROOT/mount"
    mkdir -p "$MOUNT_POINT"
    printf '[Dhad Desktop] Mounting generated DMG for verification: %s\n' "$DMG_PATH"
    hdiutil attach -readonly -nobrowse -mountpoint "$MOUNT_POINT" "$DMG_PATH" >/dev/null
    MOUNTED_APP="$(first_app "$MOUNT_POINT" || true)"
    if [[ -z "$MOUNTED_APP" || ! -d "$MOUNTED_APP" ]]; then
      printf '[Dhad Desktop] ERROR: generated DMG contains no macOS .app bundle.\n' >&2
      exit 1
    fi
    APP_PATH="$TEMP_ROOT/$(basename "$MOUNTED_APP")"
    ditto "$MOUNTED_APP" "$APP_PATH"
    hdiutil detach -quiet "$MOUNT_POINT"
    MOUNT_POINT=""
  fi
fi

# The updater archive is a second deterministic fallback for local builds that
# retain it but not the DMG-mounted application directory.
if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  ARCHIVE_PATH="$(first_match '*/release/bundle/macos/*.app.tar.gz' || true)"
  if [[ -n "$ARCHIVE_PATH" && -f "$ARCHIVE_PATH" ]]; then
    [[ -n "$TEMP_ROOT" ]] || TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dhad-macos-verify.XXXXXX")"
    EXTRACT_ROOT="$TEMP_ROOT/archive"
    mkdir -p "$EXTRACT_ROOT"
    printf '[Dhad Desktop] Extracting generated app archive for verification: %s\n' "$ARCHIVE_PATH"
    tar -xzf "$ARCHIVE_PATH" -C "$EXTRACT_ROOT"
    APP_PATH="$(first_app "$EXTRACT_ROOT" || true)"
  fi
fi

if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  printf '[Dhad Desktop] ERROR: no generated macOS .app, DMG-contained app, or app archive was found.\n' >&2
  exit 1
fi

printf '[Dhad Desktop] Verifying macOS application bundle: %s\n' "$APP_PATH"
ARGS=(--app "$APP_PATH")
case "${DHAD_EXPECTED_MACOS_ARCH:-$(uname -m)}" in
  arm64|aarch64) ARGS+=(--expected-arch aarch64) ;;
  x86_64) ARGS+=(--expected-arch x86_64) ;;
esac

if [[ "${DHAD_SKIP_MACOS_LAUNCH_SMOKE:-0}" != "1" ]]; then
  ARGS+=(--launch --launch-seconds "${DHAD_MACOS_LAUNCH_SECONDS:-5}")
fi
if [[ "${DHAD_REQUIRE_NOTARIZED:-0}" == "1" ]]; then
  ARGS+=(--require-notarized)
fi

python3 tools/verify_macos_bundle.py "${ARGS[@]}"
