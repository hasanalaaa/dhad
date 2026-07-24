#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

[[ "$(uname -s)" == "Darwin" ]] || { echo "This installer must run on macOS." >&2; exit 1; }

APP_PATH="${1:-}"
if [[ -z "$APP_PATH" ]]; then
  while IFS= read -r -d '' candidate; do
    if [[ -x "$candidate/Contents/MacOS/dhad-desktop" ]]; then
      APP_PATH="$candidate"
      break
    fi
  done < <(find "$ROOT_DIR/target" -type d -path '*/release/bundle/macos/*.app' -print0 2>/dev/null)
fi

[[ -n "$APP_PATH" && -d "$APP_PATH" ]] || {
  echo "No built Dhad .app bundle was found. Run ./scripts/build-desktop.sh first." >&2
  exit 1
}

APP_PATH="$(cd "$(dirname "$APP_PATH")" && pwd)/$(basename "$APP_PATH")"
PYTHON="${DHAD_BUILD_PYTHON:-$ROOT_DIR/.desktop-build/venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
PYTHONDONTWRITEBYTECODE=1 "$PYTHON" tools/verify_macos_bundle.py --app "$APP_PATH"

DESTINATION="${DHAD_INSTALL_DESTINATION:-/Applications/Dhad.app}"
if [[ -e "$DESTINATION" ]]; then
  rm -rf "$DESTINATION" 2>/dev/null || sudo rm -rf "$DESTINATION"
fi
mkdir -p "$(dirname "$DESTINATION")" 2>/dev/null || sudo mkdir -p "$(dirname "$DESTINATION")"
if [[ -w "$(dirname "$DESTINATION")" ]]; then
  ditto "$APP_PATH" "$DESTINATION"
else
  sudo ditto "$APP_PATH" "$DESTINATION"
fi

if [[ "${DHAD_REMOVE_QUARANTINE:-1}" == "1" ]]; then
  xattr -dr com.apple.quarantine "$DESTINATION" 2>/dev/null || sudo xattr -dr com.apple.quarantine "$DESTINATION" 2>/dev/null || true
fi

open -n "$DESTINATION"
printf 'Installed Dhad at: %s\n' "$DESTINATION"
