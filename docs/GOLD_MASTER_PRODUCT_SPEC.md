# Dhad 1.0 Gold Master — Product Specification

**Release:** `1.0.0`  
**Date:** 2026-07-23  
**Positioning:** Arabic-first, offline-first writing intelligence with deterministic safety, optional local neural inference, and collaborative encrypted editing.

## Product promise

Dhad 1.0 combines a deterministic Arabic language engine, an offline browser runtime, a privacy-preserving collaboration layer, and a complete writing workspace. The product does not require text to leave the device for core checking, rewriting, analytics, templates, or document editing. Network services are optional and explicit.

## Zero-Compromise Product Matrix

The matrix records the capabilities reviewed in the official product documentation of Grammarly, LanguageTool, Wordtune, Hemingway, and DeepL Write on 2026-07-23. It is a product-planning comparison, not a claim of certification, identical model quality, or commercial interoperability.

| Capability | Global-product baseline | Dhad Gold Master implementation | Offline/privacy behavior |
|---|---|---|---|
| Grammar, spelling, style | Contextual diagnostics, explanations, safe correction | Arabic deterministic rule engine, morphology/syntax, source spans, confidence, explanations, custom suppressions | Fully local in Python/WASM/PWA |
| Multi-mode rewriting | Formal, concise, expand, creative, academic alternatives | Five conservative rewrite modes with ranked alternatives, change provenance, number/entity preservation, REST/SDK/PWA/extension parity | Deterministic local engine; optional neural layer may enrich results |
| Tone and style | Tone identification and target-style adjustment | Academic/formal/casual/persuasive analysis, tone balance, target chips, style profiles | Fully local |
| Readability | Reading grade, sentence difficulty, density and engagement signals | Sentence heatmap, clarity, complexity, density, lexical richness, engagement, reading/speaking time, trend snapshots | Fully local; history stays in IndexedDB |
| Templates and prompt assistance | Reusable prompts and assisted drafting | Six fact-bounded templates: professional email, academic abstract, cover letter, social post, meeting summary, executive brief | Local generation; missing facts remain explicit placeholders |
| Dialect bridge | Language and register rewriting | Iraqi, Egyptian, Levantine, and Gulf indicators with review-only MSA recommendations | Fully local; never silently replaces regional wording |
| Explanations | “Why this suggestion” context | Source-anchored linguistic rationale, reader impact, confidence, safe-application policy | Fully local |
| Personal dictionary | Custom vocabulary and rule control | Device-local lexicon and reversible rule overrides through IndexedDB, SDK, and REST | Local by default |
| Document workflow | Common document import/export | TXT, Markdown, semantic DOCX import/export; browser-rendered PDF export; best-effort PDF text-layer import | Client-side; no upload required |
| Rich editing | Formatting-aware editor | Sanitized semantic HTML, headings, emphasis, lists, selection-aware rewriting, formatting-preserving corrections | Client-side |
| Cross-platform surfaces | Web, extension, APIs and integrations | PWA, Chrome/Edge MV3 extension, Python SDK, REST, CLI, LSP, desktop launcher | Shared capability contract prevents feature drift |
| Themes and accessibility | Adaptive appearance and accessible controls | Light, dark, system, and high-contrast themes; keyboard operation; ARIA dialogs/tooltips; reduced-motion policy; RTL typography | Settings stored locally |
| Collaboration | Shared editing and history | Yjs/Yrs CRDT, bounded WebSocket relay, Redis persistence/fan-out, E2EE browser frames | Relay sees ciphertext when E2EE is enabled |

## Gold Master functional requirements

### 1. Smart paraphrasing and sentence rewriting

- Modes: `formal`, `concise`, `expand`, `creative`, and `academic`.
- Every candidate returns the resulting text, score, mode, and explicit changes.
- Deterministic paths preserve numbers and avoid fabricating citations, people, dates, or claims.
- Rewriting may target a selection without flattening the rest of the rich document.
- PWA and extension expose the same capability names defined in `web_demo/shared/capabilities.js`.

### 2. Document processing

- TXT and Markdown are handled without dependencies.
- DOCX is parsed and emitted in-browser with bounded ZIP processing and path traversal protection.
- Supported semantic formatting includes headings, paragraphs, emphasis, underline, and ordered/unordered lists.
- PDF export uses the browser print engine so the rendered document is retained.
- PDF import extracts a selectable text layer when available. Scanned, encrypted, malformed, or custom-encoded PDFs require OCR or a specialized PDF engine and are reported as unsupported rather than guessed.
- Imported HTML is sanitized against an allowlist; scripts, event handlers, remote resources, and arbitrary attributes are discarded.

### 3. Analytics and dashboard

- Live document-level and sentence-level analytics.
- Heatmap severity is derived from sentence complexity, density, and issue pressure.
- Trend snapshots are bounded and stored in IndexedDB.
- Metrics include reading time, speaking time, clarity, complexity, engagement, tone balance, vocabulary richness, and sentence density.
- Analytics are explanatory signals, not grades of a person or universal measures of writing quality.

### 4. Templates and prompt assistance

- Templates ask only for fields required by their declared schema.
- Missing data remains visible; the engine does not invent credentials, achievements, citations, or recipients.
- Preview, insert-at-caret, and replace-document actions are explicit and reversible through normal editor history.

### 5. Extension and PWA parity

- A shared capability manifest is asserted by both surfaces.
- Rewrite, analytics, templates, intelligence, checks, and local preferences use the same contracts.
- The extension uses the configured Dhad endpoint; the PWA can run deterministic and neural paths locally.
- Feature absence is surfaced as a recoverable error rather than silently ignored.

### 6. Theme and accessibility system

- Appearance modes: system, light, dark, and high contrast.
- Focus indicators remain visible and keyboard paths cover command controls, dialogs, issue cards, and tooltips.
- Motion is limited to opacity and transform and disabled under `prefers-reduced-motion`.
- The implementation is designed toward WCAG 2.2 AAA contrast and interaction goals, but no third-party accessibility certification is claimed.

## Architecture mapping

| Product capability | Python | REST | PWA | Extension | Persistence |
|---|---|---|---|---|---|
| Rewrite | `dhad.rewriting` | `/api/v1/rewrite` | `rewriting/offline-rewriter.js` | `DHAD_REWRITE` | none required |
| Analytics | `dhad.analytics` | `/api/v1/analytics` | `analytics/writing-analytics.js` | `DHAD_ANALYTICS` | `analyticsHistory` IndexedDB store |
| Templates | `dhad.templates` | `/api/v1/templates*` | `templates/smart-templates.js` | `DHAD_TEMPLATES`, `DHAD_GENERATE_TEMPLATE` | local settings/documents |
| Documents | SDK text contracts | optional | `documents/document-io.js` | selected-field text | IndexedDB documents |
| Themes | n/a | n/a | `themes/theme-controller.js` | popup settings | IndexedDB/browser storage |
| Capability parity | public SDK exports | versioned routes | shared contract | shared contract | n/a |

## Performance and safety budgets

- No network call in the keystroke-critical offline analysis path.
- Expensive analysis runs outside the UI main thread where supported.
- UI updates are coalesced and do not deliberately force synchronous layout reads after writes.
- Document decompression and imported content are bounded before parsing.
- All generated HTML is sanitized or produced from trusted local structures.
- Failures remain observable, retryable, and do not poison later worker, outbox, or WebSocket operations.

## Explicit boundaries

Gold Master completes the requested product surfaces, but it does not pretend that deterministic rewriting is equivalent to an unconstrained cloud LLM for every creative task. Complex PDF reconstruction, OCR for scanned documents, third-party office-suite fidelity, app-store publication, external penetration testing, natural-corpus model evaluation, and third-party WCAG certification require separate external systems or audits. These boundaries are surfaced in the UI and release evidence instead of being hidden.
