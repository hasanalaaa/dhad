//! # dhad-core
//!
//! The portable deterministic core of the Dhad Arabic writing engine —
//! V2 Phase 3 ("edge computing") foundation. This crate targets native,
//! WASM (`cdylib`), and optional CPython embedding (`--features python`).
//!
//! **Python is the reference implementation.** Behavior here is a port of
//! `dhad.text` and the shared value types; equivalence is enforced by a
//! golden corpus generated from Python (`tools/generate_rust_golden.py`)
//! and replayed by `tests/golden.rs`. Any divergence is a bug in this
//! crate, not a new behavior.

pub mod morphology;
mod packed;
pub mod rules;
pub mod spans;
pub mod syntax;
pub mod text;
pub mod types;
pub mod wasm_api;

pub use morphology::{
    AffixSegment, MorphologicalAnalysis, MorphologicalAnalyzer, MorphologicalLexicon,
};
pub use syntax::{
    DocumentParse, IrabCandidate, RelationType, SentenceParse, SyntacticRelation, SyntaxEngine,
    SyntaxToken,
};
pub use text::{
    normalize, sentence_spans, strip_diacritics, strip_tatweel, tokenize, tokenize_all,
    NormalizationMode, TATWEEL,
};
pub use types::{Sentence, Token, TokenKind};

#[cfg(feature = "python")]
mod python {
    use pyo3::prelude::*;

    use crate::text;
    use crate::{MorphologicalAnalyzer, SyntaxEngine};

    fn parse_mode(mode: &str) -> PyResult<text::NormalizationMode> {
        match mode {
            "strict" => Ok(text::NormalizationMode::Strict),
            "lookup" => Ok(text::NormalizationMode::Lookup),
            "search" => Ok(text::NormalizationMode::Search),
            "aggressive" => Ok(text::NormalizationMode::Aggressive),
            other => Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown normalization mode: {other:?}"
            ))),
        }
    }

    /// Normalize text with the same policy names as `dhad.text.normalize`.
    #[pyfunction]
    #[pyo3(signature = (value, mode = "lookup"))]
    fn normalize(value: &str, mode: &str) -> PyResult<String> {
        Ok(text::normalize(value, parse_mode(mode)?))
    }

    /// `(text, start, end, kind)` tuples matching the Python token stream.
    #[pyfunction]
    #[pyo3(signature = (value, include_non_words = false))]
    fn tokenize(value: &str, include_non_words: bool) -> Vec<(String, usize, usize, &'static str)> {
        let tokens = if include_non_words {
            text::tokenize_all(value)
        } else {
            text::tokenize(value)
        };
        tokens
            .into_iter()
            .map(|t| (t.text, t.start, t.end, t.kind.as_str()))
            .collect()
    }

    /// `(text, start, end, terminator)` tuples matching `sentence_spans`.
    #[pyfunction]
    fn sentence_spans(value: &str) -> Vec<(String, usize, usize, String)> {
        text::sentence_spans(value)
            .into_iter()
            .map(|s| (s.text, s.start, s.end, s.terminator))
            .collect()
    }

    /// Full morphology payload using the same JSON shape as the public API.
    #[pyfunction]
    #[pyo3(signature = (token, min_confidence = 0.0))]
    fn analyze_json(token: &str, min_confidence: f64) -> PyResult<String> {
        let analyses = MorphologicalAnalyzer::default()
            .analyze(token, min_confidence)
            .map_err(|error| pyo3::exceptions::PyValueError::new_err(error))?;
        serde_json::to_string(&analyses)
            .map_err(|error| pyo3::exceptions::PyRuntimeError::new_err(error.to_string()))
    }

    /// Full deterministic syntax parse as a JSON document.
    #[pyfunction]
    fn parse_json(value: &str) -> PyResult<String> {
        serde_json::to_string(&SyntaxEngine::default().parse(value))
            .map_err(|error| pyo3::exceptions::PyRuntimeError::new_err(error.to_string()))
    }

    /// Morphology-aware grammar diagnostics as JSON.
    #[pyfunction]
    fn syntax_check_json(value: &str) -> PyResult<String> {
        serde_json::to_string(&SyntaxEngine::default().check_text(value))
            .map_err(|error| pyo3::exceptions::PyRuntimeError::new_err(error.to_string()))
    }

    #[pymodule]
    fn dhad_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
        module.add_function(wrap_pyfunction!(normalize, module)?)?;
        module.add_function(wrap_pyfunction!(tokenize, module)?)?;
        module.add_function(wrap_pyfunction!(sentence_spans, module)?)?;
        module.add_function(wrap_pyfunction!(analyze_json, module)?)?;
        module.add_function(wrap_pyfunction!(parse_json, module)?)?;
        module.add_function(wrap_pyfunction!(syntax_check_json, module)?)?;
        module.add("__engine__", "dhad-core-rs")?;
        module.add("__version__", env!("CARGO_PKG_VERSION"))?;
        Ok(())
    }
}
