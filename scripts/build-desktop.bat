@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "PYTHONDONTWRITEBYTECODE=1"
cd /d "%~dp0\.."

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul || (echo [Dhad Desktop] ERROR: Python 3 is required.& exit /b 1)
  set "PY=python"
)
where node >nul 2>nul || (echo [Dhad Desktop] ERROR: Node.js 22 is required.& exit /b 1)
where npm >nul 2>nul || (echo [Dhad Desktop] ERROR: npm is required.& exit /b 1)
where cargo >nul 2>nul || (echo [Dhad Desktop] ERROR: Rust/Cargo is required.& exit /b 1)

if not defined DHAD_TAURI_CLI_VERSION set "DHAD_TAURI_CLI_VERSION=2.11.5"
if not exist ".github\workflows\desktop-release.yml" (echo [Dhad Desktop] ERROR: Missing .github\workflows\desktop-release.yml. Preserve hidden directories when extracting the archive.& exit /b 1)
if not exist "src-tauri\tauri.conf.json" (echo [Dhad Desktop] ERROR: Missing src-tauri\tauri.conf.json.& exit /b 1)
%PY% tools\validate_tauri_config.py --config src-tauri\tauri.conf.json || exit /b 1

if not defined DHAD_BUNDLES set "DHAD_BUNDLES=nsis,msi"

set "BUILD_VENV=.desktop-build\venv"
set "BUILD_PY=%BUILD_VENV%\Scripts\python.exe"
if not exist "%BUILD_PY%" (
  echo.
  echo [Dhad Desktop] Creating isolated desktop build environment
  %PY% -m venv "%BUILD_VENV%" || exit /b 1
)
echo.
echo [Dhad Desktop] Installing pinned desktop build tooling
"%BUILD_PY%" -m pip install --disable-pip-version-check --quiet -r tools\desktop-build-requirements.txt || exit /b 1

echo.
echo [Dhad Desktop] Optimizing and validating ONNX release assets
"%BUILD_PY%" tools\optimize_onnx_assets.py --root . --write-manifest || exit /b 1

echo.
echo [Dhad Desktop] Running desktop release audits
"%BUILD_PY%" tools\validate_desktop_release.py --root . --strict || exit /b 1
"%BUILD_PY%" tools\validate_sovereign_release.py --root . --skip-cleanliness --strict --write-report || exit /b 1

if not "%DHAD_SKIP_WEB_TESTS%"=="1" (
  echo.
  echo [Dhad Desktop] Installing and testing the web/PWA surface
  call npm ci --prefix web_demo --ignore-scripts || exit /b 1
  call npm run check --prefix web_demo || exit /b 1
  call npm test --prefix web_demo || exit /b 1
)

if not "%DHAD_SKIP_RUST_TESTS%"=="1" (
  echo.
  echo [Dhad Desktop] Checking Rust formatting and workspace tests
  cargo fmt --all -- --check || exit /b 1
  cargo clippy --workspace --all-targets -- -D warnings || exit /b 1
  cargo test --workspace || exit /b 1
)

for /f "delims=" %%V in ('cargo tauri --version 2^>nul') do set "INSTALLED_TAURI_VERSION=%%V"
echo !INSTALLED_TAURI_VERSION! | findstr /c:"%DHAD_TAURI_CLI_VERSION%" >nul
if errorlevel 1 (
  if "%DHAD_SKIP_CLI_INSTALL%"=="1" (
    echo [Dhad Desktop] ERROR: Tauri CLI %DHAD_TAURI_CLI_VERSION% is required. Run: cargo install tauri-cli --version "=%DHAD_TAURI_CLI_VERSION%" --locked --force
    exit /b 1
  )
  echo.
  echo [Dhad Desktop] Installing pinned Tauri CLI %DHAD_TAURI_CLI_VERSION%
  cargo install tauri-cli --version "=%DHAD_TAURI_CLI_VERSION%" --locked --force || exit /b 1
)

echo.
echo [Dhad Desktop] Building native bundle(s): %DHAD_BUNDLES%
cargo tauri build --bundles "%DHAD_BUNDLES%" %* || exit /b 1

echo.
echo [Dhad Desktop] Build complete. Bundles are under target\release\bundle.
endlocal
