# Dhad Tauri 2 desktop shell

This directory is an additive native wrapper around the existing `web_demo/`
assets and `rust/dhad-core-rs` engine. It does not replace the Web/PWA, Python,
or Rust CLI entry points.

## Architecture

- `tauri.conf.json` embeds the generated `../web_dist` tree. `tools/build_web_dist.mjs` stages runtime assets from `web_demo` while excluding `node_modules`, tests, and package metadata.
- `analyze_text_native` executes the shared Rust `RuleSet` and `SyntaxEngine`.
- `paraphrase_native` performs deterministic, offline Rust rewriting while
  reusing core normalization, tokenization, and sentence segmentation.
- `web_demo/js/desktop-adapter.js` selects Tauri IPC when available and retains
  the existing WASM/Worker implementation in browsers.

## Development

Install the Tauri 2 prerequisites for the host operating system, then run:

```bash
cargo tauri dev --config src-tauri/tauri.conf.json
```

## Packaging

macOS (`.dmg`):

```bash
cargo tauri build --config src-tauri/tauri.conf.json --bundles dmg
```

Windows NSIS installer (`.exe`):

```powershell
cargo tauri build --config src-tauri/tauri.conf.json --bundles nsis
```

## Desktop Phase 2

Phase 2 adds a native desktop interaction layer while preserving the existing
browser and PWA paths:

- A native system tray menu opens Dhad, toggles the quick assistant, opens
  settings, or exits the process.
- The quick assistant is a predeclared, frameless, always-on-top window. It is
  toggled with `Option+Space` on macOS and `Alt+Space` on Windows.
- Closing the main or quick-assistant window hides it instead of terminating
  the tray process.
- Native `.txt`, `.md`, `.docx`, and `.pdf` selection uses
  `tauri-plugin-dialog`; byte reads and writes are delegated to Rust commands
  and dispatched through blocking-worker tasks instead of the UI thread.
- Browser/PWA builds continue to use the original `<input type="file">` and
  Blob download paths.
- PDF export retains the existing operating-system print dialog because the
  current PDF generator is print-based rather than Blob-based.

Some Windows shell configurations reserve `Alt+Space`. Shortcut registration
is therefore non-fatal; the tray menu remains a guaranteed way to open the
quick assistant.
