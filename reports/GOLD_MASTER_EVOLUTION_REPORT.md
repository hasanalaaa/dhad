# Dhad 1.0 Gold Master — Evolution Report

**Release:** `1.0.0`  
**Archive target:** `dhad-v1.0-GoldMaster.zip`  
**Date:** 2026-07-23

## Executive result

Gold Master promotes Dhad from an explainable Arabic checker into a complete offline-first writing workspace. It adds conservative multi-mode rewriting, semantic document workflows, longitudinal analytics, fact-bounded templates, extension/PWA capability parity, and an adaptive accessible theme system without weakening the privacy, CRDT, E2EE, or deterministic-core guarantees established in earlier releases.

## Product additions

### Rewriting

- Five native modes: formal, concise, expand, creative, and academic.
- Ranked deterministic candidates and explicit change provenance.
- Number-preservation and no-fabricated-citation constraints.
- Selection-aware rich-editor application and matching REST/SDK contracts.

### Documents

- Client-side TXT, Markdown, semantic DOCX, and PDF workflows.
- Sanitized rich document model with headings, emphasis, and lists.
- Bounded ZIP parsing and traversal protection for DOCX.
- Print-engine PDF export and honest best-effort text-layer PDF import.

### Analytics

- Sentence heatmaps and live clarity, complexity, density, engagement, vocabulary, tone, and time estimates.
- Bounded local trend snapshots in IndexedDB.
- Explanatory metrics that do not classify or grade the author.

### Templates

- Professional email, academic abstract, cover letter, social post, meeting summary, and executive brief.
- Required-field schemas, explicit missing facts, and no hidden invention.
- Preview, insertion, and replacement actions inside the editor.

### Surface parity and visual system

- Shared capability contract across PWA and Chrome/Edge MV3 extension.
- Gold command bar and dialogs, keyboard navigation, ARIA semantics, high-contrast mode, system/dark/light themes, and reduced-motion behavior.
- Rich-text offset bridge preserves formatting when corrections, rewrites, templates, or voice input change text.

## Engineering changes

- Added `dhad.rewriting`, `dhad.analytics`, and `dhad.templates`.
- Added strict API models and serializers for rewrite, analytics, and templates.
- Added SDK sync/async methods and versioned REST endpoints.
- Added browser modules for offline rewrite, analytics, templates, documents, themes, and capability parity.
- Upgraded the PWA database schema with bounded analytics history.
- Upgraded cache generation to `gold-1.0.0` and retained tiered on-demand neural assets.
- Bumped Python, Rust, web package, and extension release metadata to `1.0.0`.

## Product-quality boundaries

The release does not claim pixel-identical reconstruction of arbitrary PDF/DOCX files, third-party accessibility certification, or equality with cloud foundation models on unrestricted generative writing. Unsupported or lossy cases are declared explicitly. Core local analysis, templates, deterministic rewrites, and supported document semantics remain available without sending text to an external AI provider.
