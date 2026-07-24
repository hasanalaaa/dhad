## 1.0.10 — CI portability and release bootstrap repair

- Installed the complete official Tauri Linux prerequisite set before Rust workspace linting and tests.
- Installed the web runtime in the Python job so Yrs/Yjs compatibility tests resolve `yjs` on clean runners.
- Fixed GitHub web audit bootstrap by installing `PyYAML==6.0.3` before `tools/audit_repository.py`.
- Pinned the precompiled npm Tauri CLI wrapper to the published `@tauri-apps/cli@2.11.4` while retaining `tauri = 2.11.5` in Rust.
- Replaced source-built `cargo install tauri-cli` in release jobs with the pinned precompiled `@tauri-apps/cli@2.11.4`.
- Materialized Git LFS assets explicitly before integrity audits and release preparation.
- Upgraded first-party GitHub setup actions to Node 24 based major versions and limited general CI pushes to `main`, preventing duplicate tag runs.

## v1.0.7 — Repository audit hardening

## v1.0.9 — CI parity and transient-output isolation

- Fixed Python Ruff failures caused by two unused imports.
- Applied Rust 1.97.1 formatting and Clippy recommendations in the desktop crate.
- Excluded `.ci-venv`, `node_modules`, and Cargo `target` outputs from source audits while retaining strict ZIP exclusion checks.
- Added regression contracts for local CI parity environments and post-test release validation.


- Exclude internal `.git` metadata from Sovereign release cleanliness checks.
- Add regression coverage for Finder-created `.git/.DS_Store` files on macOS.
- Preserve strict checks for generated artifacts in the actual distributable source tree.

# Changelog


## 1.0.8 — CI determinism and recovery test repair

- Pinned the general CI Rust toolchain to 1.97.1 to match `rust-toolchain.toml`.
- Added deterministic pytest import paths for the repository-local `tools` package.
- Repaired the IndexedDB recovery test to fault the actual `listDueOutbox` read path.
- Reformatted the desktop release validator to satisfy Ruff E701/E702 checks.
- Added `.nvmrc` so local JavaScript tests use the same Node 22 runtime as GitHub Actions.

## [1.0.5] - 2026-07-24

### Fixed
- Restrict ONNX release optimization to first-party assets and exclude `.desktop-build`, dependency trees, and compiler output.
- Make GitHub Actions contract validation tolerant of valid YAML quoting and spacing.
- Validate `.desktop-build` exclusions from the local packaging source rather than a fragile runtime import.

## 1.0.0 Sovereign Edition — 2026-07-24

### Native desktop and security
- Enabled a restrictive Tauri CSP, prototype freezing, cross-origin isolation headers, no-referrer/nosniff policy, and disabled link previews, browser extensions, and zoom hotkeys in production windows.
- Split Tauri capabilities by window so the floating assistant cannot open native file dialogs and both windows remain local-origin only.
- Moved native analysis, rewriting, and document I/O to blocking worker tasks so CPU and filesystem work cannot stall the WebView event loop.
- Added staged, synced document writes with POSIX atomic replacement and Windows rollback recovery when replacing an existing file.
- Added Mica/macOS HUD material preferences, high-contrast/reduced-motion behavior, composited overlay motion, IME-aware input, reliable refocus, auto-hide cancellation, and measured latency labels.
- Added primary and fallback global shortcuts, active-monitor recentering, restored topmost state, and non-fatal tray-first recovery when shortcut registration is unavailable.

### Showcase and release engineering
- Replaced the project README with a Sovereign product showcase, architecture diagram, privacy boundary, competitor-positioning matrix, and native build quickstart.
- Added the high-resolution `docs/assets/dhad-sovereign-hero.svg` product/architecture visual and the complete transformation specification.
- Added the Sovereign contract validator, resumable multi-language validation matrix, and a direct runtime boot test for the mini assistant.
- Corrected desktop build and CI workflows so generated dependency/build directories are excluded from contract checks while final archive cleanliness remains mandatory.

### Validation performed in the packaging environment
- Desktop Gold Master structural audit: **87/87 passed**.
- Final Sovereign contracts, including repository cleanliness: **59/59 passed**.
- Available Node/Web/PWA/E2EE suites: **101/101 passed**; two dependency-backed files were blocked because the package registry returned HTTP 503.
- Resumable multi-language release matrix: **41 passed, 0 failed, 10 blocked, 0 timed out**; dependency/toolchain blocks were recorded explicitly rather than reported as passes.
- Native Rust formatting/check/tests and platform installers remain mandatory in CI, but were not executable on this Linux packaging host because Cargo and macOS/Windows runners were unavailable.

## 1.0.0 Gold Master — 2026-07-23

### Complete writing workspace
- Added conservative multi-mode rewriting: Formal, Concise, Expand, Creative, and Academic, with ranked candidates and explicit change provenance.
- Added client-side TXT, Markdown, semantic DOCX, and PDF workflows, including bounded DOCX ZIP parsing, sanitized rich HTML, print-based PDF export, and best-effort selectable-text PDF import.
- Added sentence heatmaps, clarity/complexity/engagement metrics, reading and speaking time, tone balance, vocabulary richness, and bounded IndexedDB trend history.
- Added six fact-bounded smart templates for professional email, academic abstract, cover letter, social post, meeting summary, and executive brief.
- Added a shared PWA/extension capability contract and matching REST/SDK/extension commands for rewrite, analytics, templates, and Writing Intelligence.
- Added system/light/dark/high-contrast themes, improved RTL typography, keyboard operation, ARIA dialogs/tooltips, and reduced-motion behavior.
- Preserved rich formatting across corrections, selection rewrites, template insertion, and voice dictation through a unified DOM/text offset bridge.

### APIs and release engineering
- Added `dhad.rewriting`, `dhad.analytics`, and `dhad.templates`, with sync/async SDK methods and `/api/v1/rewrite`, `/api/v1/analytics`, and `/api/v1/templates*` routes.
- Upgraded the PWA database and cache generation to `gold-1.0.0`.
- Promoted Python, Rust, web, and extension metadata to stable `1.0.0`.
- Added the Gold Master product specification, competitive matrix, evolution report, validation record, deterministic repository audit, and final archive manifest.

## vMAX Apex · 1.0.0-rc2 — 2026-07-23

### Writing Intelligence
- Added one unified Python/REST report for tone, style, dialect, readability, vocabulary richness, suggestion chips, and source-anchored explanations.
- Added deterministic real-time tone classification for academic, formal, casual, and persuasive writing.
- Added an offline dialect-to-MSA bridge with explicit review-only conversions and Unicode code-point spans.
- Added clarity, complexity, sentence-density, lexical-richness, lemma/root diversity, and hapax metrics.
- Added device-local custom lexicons and persistent rule overrides across the Web Worker, SDK, and API.

### UX and performance
- Added an RTL Apex intelligence dashboard, keyboard-operable issue cards, ARIA tooltips, and explicit offline/sync state.
- Moved browser intelligence into the analysis worker and included it in the atomic PWA shell.
- Reused one backend parse and `AnalysisContext` for the comprehensive intelligence endpoint.
- Removed the Rust tokenizer's document-sized byte-offset table and temporary aggressive-normalization vector.

### Validation
- 1,766 locally available Python tests pass.
- 73 dependency-available Node/Web/PWA/E2EE tests pass.
- Rust, native CRDT/Redis, and Yjs/IndexedDB suites remain mandatory in CI but could not be rerun locally because their toolchains/packages are unavailable in the packaging environment.

## vMAX Omni — 2026-07-23

- **Sync correctness:** added durable-cursor deduplication between Redis recovery and live fanout, bounded recovery records, cancellation-safe WebSocket teardown, strict inbound wire ordering, and commit-before-cursor advancement.
- **Security and capacity:** rejected ambiguous HTTP framing, bounded rate-limiter identity state, fixed oversized-body error dispatch, and gated CPU-bound analyses with configurable concurrency.
- **Edge AI:** reduced super-batch allocations, made model fetch abortable, isolated failed workers, and guaranteed clean retry after timeout, crash, or synchronous dispatch failure.
- **Offline/PWA:** split atomic shell precaching from optional neural assets, added on-demand neural cache warming, and hardened IndexedDB sequence allocation and outbox scans.
- **E2EE and UX:** bounded cryptographic inputs and pending key packages, zeroized replaced room keys, added stable crypto error codes, and expanded RTL accessibility state.
- **Validation:** 1,760 locally executable Python tests and 61 locally executable Web tests passed; unavailable native/dependency suites remain declared rather than misreported.

## Unreleased — v2.0 execution: M2 incremental core, M3 Rust/WASM + browser build, M4 CRDT + live sync, M5 distillation

- **vMAX Ultimate hardening:** made neural runtime initialization atomic and concurrency-safe, bounded WebSocket inbound/outbound/buffered frames, hardened reconnect and callback failures, moved Yjs update reads onto the IndexedDB document index, attached Service Worker background refreshes to `FetchEvent.waitUntil`, and eliminated unobserved asynchronous UI failures.
- **Backend security and lifecycle:** strict duplicate/negative `Content-Length` rejection, UTF-8-safe API-key parsing, consistent Bearer authentication for HTTP/WebSocket, control-frame rate limiting, tracked sync-hub maintenance tasks, deterministic peer eviction, and cancellation-safe shutdown.
- **Release engineering:** root-level Rust profiles, explicit WASM SIMD build flags, strict multi-language CI, Dependabot coverage, deterministic repository inventory with SHA-256, and regression tests for the new concurrency, backpressure, storage, and PWA contracts.

- **WASM browser build (M3.2):** `dhad-core-rs` now compiles to `wasm32-unknown-unknown` (hand-rolled C ABI over linear memory — no wasm-bindgen), carrying the tokenizer, sentence segmentation, all normalization modes, the ported sweep-line `dedupe`, and a portable literal-rule engine fed by `tools/export_wasm_rules.py` (130 rules with exact `B_LEFT`/`B_RIGHT` boundary semantics). Binary: 1.32 MB after `wasm-opt -Oz`, 471 KB gzipped. `web_demo/` contains the self-contained offline demo (`index.html`, `app.js`, `dhad-core.js` bridge), a Node parity/benchmark gate (`bench.mjs`), and a real-Chromium proof (`browser_proof.mjs`): 10/10 golden-corpus parity in-browser, sentence check p50 0.100 ms, 9.9 KB document p50 9.3 ms.
- **Multiplayer WebSocket sync (M4.2):** new `dhad.sync` — `/ws/sync/{doc_id}` relay mounted by `create_app` (and `dhad serve`; disable with `--no-sync`). The server is a blind router: op payloads are size-checked opaque strings, never parsed or logged, so E2E-encrypted CRDT traffic works unchanged (proven by a ciphertext relay test). Bounded rooms/payloads, validated doc ids, presence events, per-doc sequence numbers. Live-network proof over uvicorn: A→server→B op latency p50 0.487 ms, ~2,000 serial ops/sec, two replicas byte-identical after 300 networked ops; 9 new tests including concurrent-typing convergence.

- Replaced every quadratic overlap filter (six sites in `Dhad.check`, `match.dedupe`, the neural gateway) with sweep-line indexes (`dhad.spans`): per-KB check cost is now flat (≈13.5 ms/KB) across a 64× document-size range; the 14KB dense-error case dropped from 520 ms to 184 ms. Equivalence with the historical quadratic implementations is enforced bit-for-bit by randomized oracle tests.
- Added `dhad.incremental.IncrementalSession` (and `Dhad.session()`): chunked-memcmp diffing, sentence-aligned windows computed from a padded local slice, PII-safe edge extension, and exact match splicing. Measured on a 10,009-word document: **p50 7.26 ms / p95 10.01 ms per single-word mutation — 106× faster than a full pass** (`benchmarks/profile_incremental.py`). Sentence-local categories are bit-for-bit identical to a full pass after every update; document-global categories (semantics/consistency) are carried forward and refreshed by `reconcile()`.
- Added `rust/dhad-core-rs`: a portable Rust port of the deterministic text substrate (all four normalization modes, the full token alternation with URL trailing-punctuation splitting, sentence segmentation with abbreviation/decimal/list-marker guards), char-offset accurate, `cdylib` for WASM and optional PyO3 bindings (`--features python`, abi3 ≥ 3.10). Python remains the reference implementation: a golden corpus generated by `tools/generate_rust_golden.py` is replayed by `cargo test` (5 parity suites) and `tests/test_rust_parity.py` (corpus + 60 fuzz texts through the compiled extension).
- Added `dhad.crdt.CrdtDocument`: a tree-RGA collaborative text type with deterministic sibling ordering, idempotent causal-buffering apply, stable character anchors for diagnostics, JSON transport/persistence, and randomized 3-replica convergence fuzzing — including a combined CRDT → IncrementalSession integration test.
- Added `dhad.neural.distillation`: accepted neural corrections aggregate by support, reduce to single contiguous token replacements, self-verify through the real rule compiler (must fire on the bad example, stay silent on the good one), and emit quarantined `autofix: false` YAML drafts outside the engine's rule glob.
- Full suite: 1,744 Python tests + 5 Rust test suites green; ruff clean; the v0.13.0 controlled benchmark is preserved exactly.

## 1.0.0-rc1 — 2026-07-21

- Completed the Phase-12 governance and identity scope and opened the v2.0 evolution track.
- Replaced the short license notice with the complete verbatim GNU AGPL-3.0 text in `LICENSE`.
- Added a bilingual enterprise `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) and `SECURITY.md` with supported versions, private-reporting workflow, architectural guarantees, and declared limitations.
- Added the CLI identity banner (`dhad.cli.BANNER` / `print_banner`), shown on bare invocation and at `dhad serve` start-up on stderr so scripted stdout stays parseable.
- Added the official scalable logo at `docs/logo.svg`: obsidian/graphite ground with copper-gold accents, an abstract ض whose iʿjām dot doubles as the gold source node of an NLP lattice.
- Bumped the version to `1.0.0rc1` (PEP 440 canonical) across Python, PWA, and docs; the Chrome extension uses `version` `1.0.0` with `version_name` `1.0.0-rc1` because store manifests forbid pre-release suffixes.
- Published a measured architectural audit (`docs/STATE_OF_THE_ENGINE_AR.md`): 803 ms cold init, 74 ms full-engine check for a ~700-word document, and a quadratic overlap-filter hotspot on match-dense text.
- Published the v2.0 master plan (`docs/MASTER_PLAN_V2_AR.md`): stylometry, incremental core, portable Rust/WASM core, CRDT collaboration, transformer integration, and distribution.
- Executed v2.0 Phase 1: new `dhad.stylometry` module with a closed 40-dimension explainable feature vocabulary, immutable Welford-based `VoiceProfile` (fit/update/merge, versioned JSON persistence, non-reversible aggregates), bounded per-dimension drift reports, and `personalize_matches`, which annotates style matches only and never suppresses errors.
- Wired `Dhad.learn_voice()` and `Dhad.voice_report()` through the offset-preserving PII mask; `check()` behavior is byte-for-byte unchanged.
- Added 31 stylometry tests; the complete suite now contains 1,690 passing tests.
- Preserved the v0.13.0 controlled benchmark exactly: P 0.8602, R 0.9539, F0.5 0.8775, and 6.3511 FP/1000 words.
- Store publication, natural-corpus evaluation, distributed rate limiting, and the remaining v2.0 phases stay explicit future work.

## 0.13.0 — 2026-07-21

- Completed the requested Phase-11 engineering scope: multi-stage production container, hardened Compose deployment, Gunicorn/Uvicorn serving, HTTP security controls, and offset-preserving PII masking.
- Added `dhad.security` with validated environment settings, streaming request-body limits, a 50,000-character text cap, optional API-key authentication, and an async token-bucket limiter with standard response headers.
- Added `dhad.privacy` to mask e-mails, phones, and URLs with unique same-length Private-Use sentinels before all NLP layers and restore them after processing.
- Integrated privacy inside the public `Dhad` engine, protecting REST, SDK, CLI, LSP, style, dialect, semantics, neural analysis, parsing, and diacritization without shifting offsets.
- Added sanitized validation responses, zero-body logging policy, defensive PII log filtering, no-store analysis responses, COOP/CORP, and HTTPS HSTS.
- Added a non-root multi-stage Dockerfile, read-only/no-capability Compose service, and a validated Gunicorn configuration whose access format excludes query strings and user content.
- Added 17 Phase-11 tests; the complete suite now contains 1,659 passing tests.
- Preserved the v0.12.0 controlled benchmark exactly: P 0.8602, R 0.9539, F0.5 0.8775, and 6.3511 FP/1000 words.
- Distributed rate limiting, enterprise identity, full DLP, third-party penetration testing, SBOM signing, and published load/SLO data remain explicit future work.

## 0.12.0 — 2026-07-21

- Completed the requested Phase-10 engineering scope: responsive RTL web dashboard, installable PWA, Chrome/Edge Manifest V3 extension, and a loopback-only desktop launcher.
- Replaced the monolithic editor with maintainable HTML/CSS/JavaScript that consumes the Phase-9 `/api/v1` contracts for check, style, dialect, and diacritization.
- Added a privacy-safe service worker that caches application-shell assets only and never caches text-bearing analysis traffic.
- Added optional static serving and API-only mode (`dhad serve --no-web`), local-only default CORS, browser-extension origin support, wildcard rejection, CSP, Permissions-Policy, and frame protection.
- Added a complete Manifest V3 package in `extension/`: service-worker transport, permission-gated remote servers, textarea/contenteditable overlays, squiggles, review cards, popup settings, and safe-autofix-aware actions.
- Added `dhad.desktop`, `dhad-desktop`, and `dhad desktop`, with pywebview, Chromium/Edge app mode, and system-browser fallbacks over a loopback Uvicorn process.
- Added PWA/mobile and desktop deployment documentation and a packaged extension ZIP.
- Added 17 Phase-10 tests; the complete project suite now contains 1,642 passing tests.
- Preserved the v0.11.0 controlled benchmark exactly: P 0.8602, R 0.9539, F0.5 0.8775, and 6.3511 FP/1000 words.
- Store publication, Firefox/Safari packaging, native mobile keyboards, multi-file projects, and cross-browser visual E2E remain explicit future work.

## 0.11.0 — 2026-07-21

- Completed the requested Phase 9 scope: versioned asynchronous REST API, local/remote Python SDK, and a dependency-free LSP 3.17 server.
- Added strict Pydantic v2 contracts and JSON endpoints for `/check`, `/parse`, `/diacritize`, `/style`, and `/dialect`, plus stable `/api/v1/*` aliases and generated OpenAPI/Swagger/ReDoc documentation.
- Preserved the existing LanguageTool-v2 endpoints and editor without breaking their response contract.
- Added `DhadClient`, which returns the same validated response models in local and remote modes and provides synchronous and asynchronous methods.
- Added `dhad.lsp` with full/incremental document synchronization, publishDiagnostics, morphology/iʿrāb hover, and Quick Fix code actions restricted to the Safe Autofix policy.
- Added exact UTF-16 position conversion and Content-Length JSON-RPC framing for VS Code, Neovim, and other standards-compliant LSP clients.
- Added `dhad lsp` and the `dhad-lsp` console script.
- Added 20 Phase-9 contract and integration tests; the complete suite now contains 1,623 passing tests.
- Preserved the v0.10.0 controlled benchmark exactly: P 0.8602, R 0.9539, F0.5 0.8775, and 6.3511 FP/1000 words.
- TypeScript SDK, request cancellation, document-session APIs, and SARIF/JSONL remain future integration work and are not claimed in this release.

## 0.10.0 — 2026-07-21

- Completed the engineering scope of Phase 8: explicit diacritization, conservative semantics, and document consistency.
- Added `DiacriticsEngine` with `full`, `core`, and `endings` modes over selected morphology and candidate iʿrāb.
- Added offset-preserving token provenance, confidence-separated core/ending decisions, and neural-WSD-aware vocalization.
- Added `SemanticEngine`, schema-validated semantic resources, and `DocumentConsistencyTracker` for variant and numeral-style consistency.
- Added conservative semantic redundancy and explicit contradiction checks with temporal guards.
- Added `Dhad.diacritize()`, `Dhad.semantic_report()`, `dhad diacritize`, `dhad semantics`, and explicit check-time diacritics suggestions.
- Added the `diacritics`, `semantics`, and `consistency` categories; every Phase-8 result is `autofix=false`.
- Added 30 Phase-8 and benchmark-regression tests; the full suite now has 1,603 passing tests.
- Preserved the v0.9.0 controlled benchmark exactly: P 0.8602, R 0.9539, F0.5 0.8775, and 6.3511 FP/1000 words.
- Independent natural-corpus WER/DER and human document-consistency evaluation remain explicit limitations.

## 0.9.0 — 2026-07-21

- Completed Phase 7: a confidence-gated hybrid contextual layer that never overrides high-confidence deterministic analysis.
- Added `dhad.neural` with immutable requests, decisions, reports, a backend protocol, and a trust gateway.
- Added a schema-validated sparse n-gram model for local WSD and contextual real-word spelling without heavyweight dependencies.
- Added a functional lazy `TransformerBackend` for optional HuggingFace sequence-classification models via `dhad[neural]`.
- Constrained WSD to morphology candidates already produced by Dhad and recomputed syntax/iʿrāb through `SyntaxEngine.rebuild_sentence`.
- Added `Dhad.neural_report()`, neural refinement in `Dhad.parse()`/`Dhad.check()`, `dhad neural --json`, and `Dhad(neural_checks=False)`.
- Added the distinct `neural_suggestion` category; all probabilistic suggestions are `autofix=false` and lose overlaps to deterministic findings.
- Added 13 Phase-7 and release-regression tests; the full suite now has 1,573 passing tests.
- Preserved the v0.8.0 controlled benchmark exactly: P 0.8602, R 0.9539, F0.5 0.8775, and 6.3511 FP/1000 words.

## 0.8.0 — 2026-07-21

- Completed Phase 6: deterministic identification of Egyptian, Levantine, Gulf, Iraqi, and Maghrebi Arabic plus opt-in contextual conversion to MSA.
- Added schema-validated `dialects.json` with 79 entries, 15 desire forms, and 28 contextual verb mappings.
- Added evidence-bearing `DialectIdentification`, validated `DialectConversion`, `DialectReport`, and the public APIs `detect_dialect`, `dialect_report`, and `convert_to_msa`.
- Added morphology- and syntax-validated structural rewrites such as `عايزين نلعب → نريد أن نلعب`, while guarding ambiguous MSA contexts such as `في ذلك الحين`, `أبي كريم`, and `مشيت`.
- Added `dhad dialect`, `dhad parse --msa`, `dhad fix --dialects`, and `Dhad.correct(..., mode="dialects")`.
- Enforced `category=dialect`, `severity=hint`, `autofix=false`, and `requires-approval` for every new dialect suggestion.
- Expanded the core morphology lexicon to 229 lemmas, 121 roots, and 9,686 licensed forms to validate MSA verbal suggestions.
- Added 39 dialect tests; the full suite now has 1,560 passing tests.
- Improved the controlled all-category benchmark from P 0.8497 / R 0.8764 / F0.5 0.8549 to P 0.8602 / R 0.9539 / F0.5 0.8775, with FP/1000 unchanged at 6.3511. Mechanical-scope metrics remained exactly unchanged.
- The controlled dialect slice reached 208 TP, 0 FP, and 0 FN, but native-speaker evaluation on natural corpora remains an explicit limitation.

## 0.7.0 — 2026-07-21

- Completed the deterministic engineering scope of Phase 5: clarity, style, and explainable tone analysis.
- Added `dhad.style` with schema-validated phrase preferences, morphology-aware light-verb rewrites, syntax-aware sentence-density diagnostics, tone-consistency warnings, and a transparent Dhad Clarity Index.
- Added seven audience profiles: general, academic, administrative, journalistic, educational, friendly, and literary.
- Added `Dhad.style_report()`, `Dhad.analyze_tone()`, and `dhad style --json`.
- Categorized every Phase-5 finding as `style`, tagged it `requires-approval`, and enforced `autofix=false`; safe mode never applies subjective rewrites.
- Reused the Phase-4 parse inside the integrated pipeline to avoid duplicate morphology/syntax work.
- Added comprehensive Phase-5 and regression-isolation coverage; the full suite now has 1,530 passing tests.
- Preserved the v0.6.0 controlled benchmark exactly: P 0.8497, R 0.8764, F0.5 0.8549, and 6.3511 FP/1000 words.
- The automated corpus proves regression safety, not human usefulness; human double-review remains required before broad style-quality claims.

## 0.6.0 — 2026-07-21

- Completed Phase 4: deterministic syntax, grammar checks, and candidate iʿrāb.
- Added sentence/document parse objects, confidence-ranked morphology selection, seven relation types, and explainable iʿrāb candidates.
- Added demonstrative, noun-adjective, subject-verb, idafa, preposition-case, subjunctive, and jussive diagnostics.
- Added `Dhad.parse()` and `dhad parse --json`.
- Added construct-state morphology while excluding context-dependent forms from standalone spelling suggestions.
- Fixed Arabic abbreviation sentence-boundary handling for ordinary words ending in `د.`.
- Added 48 Phase-4 tests; full suite now has 1,479 passing tests.
- Improved controlled test F0.5 from 0.8346 to 0.8549 with FP/1000 unchanged at 6.3511.

## 0.5.0 — 2026-07-21

- Completed Phase 3: morphology-aware lexical spelling and deterministic Arabic morphology.
- Added a schema-validated 224-lemma, 116-root lexicon producing 9,608 licensed forms.
- Added root/pattern extraction, clitic and inflection segmentation, lemma candidates, and confidence-ranked analyses.
- Added weighted Arabic Damerau-Levenshtein distance and context/frequency/morphology candidate ranking.
- Integrated lexical checks after existing deterministic rules with overlap protection and safe-autofix preservation.
- Added `dhad analyze` and morphology statistics to the health endpoint.
- Added 40 Phase-3 regression tests; full suite now has 1,431 passing tests.
- Improved controlled test F0.5 from 0.8148 to 0.8346 without increasing FP/1000 words.

## 0.4.0 — 2026-07-21

- Completed Phase 2: independent data and evaluation infrastructure.
- Added a versioned benchmark JSON Schema and packaged 5,000-case controlled corpus.
- Added deterministic train/dev/test splits (3,500/750/750) with zero duplicate text leakage.
- Added 1,000 double technical-validation cases and agreement metrics.
- Added span, correction, sentence, F0.5, FP/1000-word, MRR, domain, and dialect metrics.
- Added `dhad benchmark` and reproducible JSON/Markdown reports.
- Added dataset license registry, annotation guidelines, data governance, and SHA-256 manifests.
- Published the honest v0.4.0 controlled-test baseline.

## 0.3.0 — 2026-07-21

- Completed Phase 1: Arabic Unicode text layer and Rule Engine v2.
- Added lossless offset-preserving tokenization and improved sentence segmentation.
- Added explicit normalization modes.
- Added JSON Schema v2 and migrated all 141 bundled rules.
- Added literal, regex, token-sequence, context, exception, and document rule types.
- Added confidence, priority, profiles, tags, references, and safe autofix metadata.
- Added deterministic overlap resolution and local suppression controls.
- Added 1,024 Unicode/offset regression cases; full suite now has 1,379 tests.

## v1.0.6 — macOS release hygiene and reproducible local builds

- Automatically removes Finder `.DS_Store`, AppleDouble, Python bytecode, and test caches before release audits.
- Pins PyYAML inside the isolated desktop build environment so repository auditing never modifies Homebrew Python.
- Keeps validation read-only by default; report files are updated only when `DHAD_WRITE_REPORTS=1` is explicitly set.
- Adds a verified macOS installer script that copies the built ASCII-named bundle to `/Applications/Dhad.app` while preserving the Arabic display name «ضاد».
- Makes repository audit failures print their exact path and reason immediately.
