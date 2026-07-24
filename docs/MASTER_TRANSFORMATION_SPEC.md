# Dhad Ultimate Dream Release — Master Transformation Specification

## Release identity

- Product: **Dhad Desktop**
- Edition: **v1.0.0 Sovereign Edition**
- Desktop shell: Tauri 2
- Primary targets: macOS (Apple Silicon + Intel) and Windows x64
- Design principle: Arabic-first, offline-first, least privilege, measurable performance

## Non-negotiable engineering rules

1. The UI thread must not execute CPU-heavy linguistic analysis or file I/O.
2. Desktop windows receive only the capabilities they require.
3. The production WebView must ship with an explicit CSP and hardened response headers.
4. User document writes must stage data before replacing the destination.
5. Offline operation is the default path; optional network and collaboration surfaces remain explicit.
6. Performance claims are evidence-based. Microbenchmarks are not presented as universal latency guarantees.
7. Release archives exclude caches, virtual environments, node_modules, Cargo targets, logs and temporary files.

## Transformation scope

### Native desktop

- Hardened Tauri CSP, cross-origin isolation headers and frozen prototypes.
- Per-window capability separation for the editor and floating assistant.
- Transparent Mica/macOS HUD material configuration with accessible fallbacks.
- Resilient primary and fallback global shortcuts.
- Active-monitor re-centering, explicit focus and always-on-top restoration.
- Installer downgrade protection and bundled VC runtime on Windows.

### Runtime and data integrity

- Native analysis and rewriting execute through `spawn_blocking` workers.
- Existing file reads remain bounded to 64 MiB and off the UI thread.
- Exports are written to a unique sibling temporary file, synchronized, then committed.
- Existing deterministic Rust engine and browser worker boundaries remain intact.

### Experience design

- Composited overlay entrance animation with reduced-motion handling.
- Native translucency, high-contrast adaptation, keyboard focus rings and refined scrollbars.
- IME-aware debounce for Arabic composition.
- Live character count, local-processing status and measured latency feedback.
- Responsive overlay behavior for constrained displays.

### Documentation and release governance

- New showcase README and custom SVG hero.
- Architecture, privacy boundary, build commands and platform matrix documented.
- Sovereign validator checks security, native concurrency, capabilities, UI and release cleanliness.
- CI/release workflow invokes both the legacy Gold Master validator and Sovereign validator.
