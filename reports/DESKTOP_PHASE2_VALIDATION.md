# Dhad Desktop Phase 2 Validation

## Scope

Native system tray, global shortcut, floating mini-assistant, and native
file-dialog integration for the additive Tauri 2 desktop shell.

## Implemented

- `src-tauri/src/tray.rs`
  - Arabic tray menu: open, quick check, settings, quit.
  - Left-click restores the main window.
  - Window operations are scheduled on Tauri's main thread.
- Global shortcut
  - `Option+Space` on macOS (`ALT`/Option modifier).
  - `Alt+Space` on Windows.
  - Registration failure is non-fatal to account for OS-reserved shortcuts.
- Floating mini-assistant
  - Hidden at startup, frameless, always on top, taskbar-hidden, and focused on activation.
  - Local check, rewrite, suggestion application, clipboard copy-back, and optional blur auto-hide.
  - Reports measured execution latency rather than a synthetic fixed value.
- Native document dialogs
  - `.txt`, `.md`, `.docx`, and `.pdf` filters.
  - Rust-side extension checks and a 64 MiB file-size limit.
  - File-system reads/writes run through blocking worker tasks.
  - Browser/PWA file picker and Blob download fallbacks remain intact.

## Automated validation

- 22 targeted Node tests: passed.
- JavaScript syntax checks for all modified/new modules: passed.
- JSON parsing for Tauri configuration and capability files: passed.
- TOML parsing for workspace and Tauri manifests: passed.
- 48 static structure/configuration/IPC checks: passed.
- Static Rust delimiter checks are included in the 48 checks.
- ZIP CRC verification: performed after packaging.

## Environment limitation

The execution environment does not include `cargo` or `rustc`, so a native
`cargo check`, `.dmg`, or Windows `.exe` bundle could not be produced here.
The source scaffold and packaging configuration are included for compilation
on macOS and Windows hosts with the Tauri 2 prerequisites installed.
