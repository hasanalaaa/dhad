#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '[Dhad Desktop] ERROR: native macOS bundle verification must run on macOS.\n' >&2
  exit 1
fi

APP_PATH="${DHAD_MACOS_APP_PATH:-}"
if [[ -z "$APP_PATH" ]]; then
  while IFS= read -r -d '' candidate; do
    APP_PATH="$candidate"
    break
  done < <(find target -type d -path '*/release/bundle/macos/*.app' -print0 2>/dev/null | sort -z)
fi

if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  printf '[Dhad Desktop] ERROR: no generated macOS .app bundle was found.\n' >&2
  exit 1
fi

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
