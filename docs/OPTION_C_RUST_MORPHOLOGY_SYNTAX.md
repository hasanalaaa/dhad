# Option C — Rust/WASM morphology and syntax

## Outcome

The portable core now executes Dhad's deterministic morphology and syntax in
Rust. Python remains the reference implementation and fallback; no Python
runtime path was replaced or removed.

## Runtime architecture

- `tools/export_wasm_morphology.py` compiles the versioned Python lexicon and
  its productive forms into `rust/dhad-core-rs/data/morphology.json`.
- `src/morphology.rs` embeds that pack and natively performs lexical lookup,
  affix anchoring, derivational-template matching, root recovery, feature
  merging, confidence gating, deduplication, and oracle-compatible ranking.
- `src/syntax.rs` natively performs context selection, relation construction,
  candidate i'rab, and all conservative morphology-aware grammar checks from
  `dhad.syntax`.
- `src/wasm_api.rs` exposes `dc_analyze`, `dc_parse`, and `dc_syntax_check`.
  `dc_check` merges syntax diagnostics with portable literal rules before the
  shared overlap resolver. `dc_warmup` builds the immutable morphology indexes
  at engine load rather than on the first keystroke.
- `web_demo/dhad-core.js` exposes `analyze`, `parse`, and `syntaxCheck`, plus
  explicit Unicode-scalar/UTF-16 offset conversion helpers.

## Offset contract

Engine offsets are Unicode scalar indexes, matching Python's `str` indexing.
They are never UTF-8 byte offsets. JavaScript DOM consumers must translate
them to UTF-16 with `scalarToUtf16`; the reverse conversion is provided by
`utf16ToScalar`. Cross-language tests include astral characters before Arabic
tokens to catch accidental UTF-16 or byte indexing.

Morphological affix offsets retain the Python oracle's existing contract: they
index the normalized token, while syntax and diagnostic offsets index the
original document.

## Parity gates

- `tests/test_rust_parity.py` compares full morphology analyses, full syntax
  parse payloads, and full grammar diagnostics field-for-field against Python.
- `rust/dhad-core-rs/tests/morphology_syntax.rs` provides native smoke and
  offset contracts even when the optional CPython extension is not built.
- `web_demo/bench.mjs` and `browser_proof.mjs` exercise morphology, syntax, and
  astral-Unicode offsets in Node and Chromium respectively.
- The generated morphology pack is reproducible and matches Python's 16,626
  generated records (13,378 distinct forms) for lexicon version 1.1.0.

## Rebuild

```bash
rustup target add wasm32-unknown-unknown
tools/build_wasm_core.sh
```

The build script regenerates both data packs, runs the native Rust suite,
builds the release WASM binary, copies it into `web_demo`, and runs the Node
parity/latency gate.
