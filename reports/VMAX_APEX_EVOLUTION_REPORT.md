# Dhad vMAX Apex — Evolution Report

**Release:** `1.0.0-rc2`  
**Archive target:** `dhad-vMAX-Apex.zip`  
**Date:** 23 July 2026

## Executive result

Apex extends the hardened Omni platform with a unified, deterministic Writing Intelligence layer. The implementation is local-first, explainable, non-destructive, and available through the Python engine, REST API, SDK, Web Worker, and PWA interface. Existing grammar, privacy, sync, neural, and offline boundaries remain intact.

## Capability expansion

### Tone and style intelligence

- Classifies academic, formal, casual, and persuasive signals.
- Exposes confidence, evidence spans, rationale, and ranked target-register chips.
- Keeps suggestions advisory; no tone rewrite is applied automatically.

### Dialect-to-MSA bridge

- Detects high-frequency Iraqi, Egyptian, Levantine, Gulf, and shared colloquial forms offline.
- Emits Unicode code-point-accurate, review-only replacements.
- Preserves the original document and supplies a separate converted preview.

### Readability and complexity

- Computes clarity and complexity scores, sentence and clause density, average word length, repeated-word pressure, lexical richness, and hapax ratio.
- Python additionally reports lemma and root diversity from the morphology layer.
- Metrics are transparent heuristics, not opaque quality claims.

### Interactive explanations

- Every diagnostic receives source text, span, reasoning, why-it-matters guidance, severity, confidence, decision policy, replacements, and references.
- PWA issue cards and the interactive detail surface use the same explanation contract.

### Custom lexicon and rule overrides

- Device-local words are stored in IndexedDB.
- Disabled rule identifiers are persistent and reversible.
- The worker, fallback runtime, REST API, and Python SDK share bounded override contracts.

## Atomic engineering improvements

### Python engine

- Added `WritingIntelligenceReport` and strict slot-based immutable domain models.
- Added `/intelligence` and `/api/v1/intelligence` with strict Pydantic contracts.
- Refactored diagnostics into `_check_private` so comprehensive intelligence reuses one masked parse and one `AnalysisContext` instead of parsing the document twice.
- Preserved the PII masking and standard suppression pipeline.

### Rust/WASM core

- Removed the tokenizer's `text.len() + 1` byte-to-character lookup allocation.
- Replaced it with monotonic capture-boundary accounting while retaining code-point offsets.
- Preallocated normalization outputs and collapsed aggressive normalization in one pass without a temporary mapped string or `Vec<&str>`.
- Added Unicode offset and normalization parity tests for CI.

### Browser/PWA

- Runs writing intelligence inside the existing analysis worker.
- Adds bounded copies for local preferences and keeps the main thread free of linguistic scans.
- Adds an Apex dashboard with contained layout surfaces, transform/opacity-only micro-interactions, keyboard issue navigation, ARIA tooltips, reduced-motion support, and explicit online/offline state.
- Includes the intelligence module in the atomic app shell under cache generation `apex-7.0.0`.

## Security and privacy properties

- No new external inference service was introduced.
- Custom lexicons and rule overrides stay on the device unless an integrator explicitly sends them to the optional local/self-hosted API.
- Override lengths and collection sizes are bounded before analysis.
- Dialect and tone suggestions are review-required and never silently rewrite user text.
- Existing E2EE, WebSocket backpressure, request-framing, and rate-limit hardening remain unchanged.

## Known validation constraints

The packaging environment does not provide `cargo/rustc`, `pycrdt`, `redis/fakeredis`, or cached npm tarballs for `yjs` and `fake-indexeddb`. Those suites remain present and mandatory in CI but were not represented as locally passing. See `VMAX_APEX_FINAL_VALIDATION.md` for exact evidence.
