#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

log() { printf '\n\033[1;36m[Dhad Desktop]\033[0m %s\n' "$*"; }
fail() { printf '\n[Dhad Desktop] ERROR: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || fail "Python 3 is required."
command -v node >/dev/null 2>&1 || fail "Node.js 22 is required."
command -v npm >/dev/null 2>&1 || fail "npm is required."
command -v cargo >/dev/null 2>&1 || fail "Rust/Cargo is required."

TAURI_CLI_VERSION="${DHAD_TAURI_CLI_VERSION:-2.11.4}"
[[ -f ".github/workflows/desktop-release.yml" ]] || fail "Missing .github/workflows/desktop-release.yml. Preserve hidden directories when copying or extracting the release archive."
[[ -f "src-tauri/tauri.conf.json" ]] || fail "Missing src-tauri/tauri.conf.json."
python3 tools/validate_tauri_config.py --config src-tauri/tauri.conf.json || fail "Tauri configuration is incompatible with CLI 2.11.x."

case "$(uname -s)" in
  Darwin) DEFAULT_BUNDLES="dmg" ;;
  *) fail "Use scripts/build-desktop.bat on Windows. This shell script builds the macOS DMG." ;;
esac

BUNDLES="${DHAD_BUNDLES:-$DEFAULT_BUNDLES}"
BUILD_VENV="$ROOT_DIR/.desktop-build/venv"
PYTHON="$BUILD_VENV/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  log "Creating isolated desktop build environment"
  python3 -m venv "$BUILD_VENV"
fi
log "Installing pinned desktop build tooling"
"$PYTHON" -m pip install --disable-pip-version-check --quiet -r tools/desktop-build-requirements.txt

log "Cleaning host-generated repository artifacts"
"$PYTHON" tools/clean_repository.py --root .

log "Optimizing and validating ONNX release assets"
OPTIMIZE_ARGS=(--root .)
if [[ "${DHAD_WRITE_REPORTS:-0}" == "1" ]]; then OPTIMIZE_ARGS+=(--write-manifest); fi
"$PYTHON" tools/optimize_onnx_assets.py "${OPTIMIZE_ARGS[@]}"

log "Running desktop release audits"
DESKTOP_AUDIT_ARGS=(--root . --strict)
SOVEREIGN_AUDIT_ARGS=(--root . --strict)
if [[ "${DHAD_WRITE_REPORTS:-0}" == "1" ]]; then
  DESKTOP_AUDIT_ARGS+=(--write-reports)
  SOVEREIGN_AUDIT_ARGS+=(--write-report)
fi
"$PYTHON" tools/validate_desktop_release.py "${DESKTOP_AUDIT_ARGS[@]}"
"$PYTHON" tools/validate_sovereign_release.py "${SOVEREIGN_AUDIT_ARGS[@]}"
"$PYTHON" tools/audit_repository.py

if [[ "${DHAD_SKIP_WEB_TESTS:-0}" != "1" ]]; then
  log "Installing and testing the web/PWA surface"
  npm ci --prefix web_demo --ignore-scripts
  npm run check --prefix web_demo
  npm test --prefix web_demo
fi

if [[ "${DHAD_SKIP_RUST_TESTS:-0}" != "1" ]]; then
  log "Checking Rust formatting and workspace tests"
  cargo fmt --all -- --check
  cargo clippy --workspace --all-targets -- -D warnings
  cargo test --workspace
fi

log "Staging dependency-free Tauri frontend"
node tools/build_web_dist.mjs

INSTALLED_TAURI_VERSION="$(tauri --version 2>/dev/null || true)"
if [[ "$INSTALLED_TAURI_VERSION" != *"$TAURI_CLI_VERSION"* ]]; then
  if [[ "${DHAD_SKIP_CLI_INSTALL:-0}" == "1" ]]; then
    fail "Tauri npm CLI $TAURI_CLI_VERSION is required. Install it with: npm install --global @tauri-apps/cli@$TAURI_CLI_VERSION"
  fi
  log "Installing pinned Tauri npm CLI $TAURI_CLI_VERSION"
  npm install --global "@tauri-apps/cli@$TAURI_CLI_VERSION"
fi
command -v tauri >/dev/null 2>&1 || fail "Pinned Tauri CLI is not available on PATH after installation."

log "Building native bundle(s): $BUNDLES"
tauri build --bundles "$BUNDLES" "$@"

log "Verifying generated macOS application bundle"
./scripts/verify-macos-app.sh

log "Build complete. Bundles are under target/*/release/bundle or target/release/bundle."
