//! Native smoke/contract tests for the morphology and syntax WASM core.
//! Full field-for-field oracle parity lives in `tests/test_rust_parity.py`.

use dhad_core::{MorphologicalAnalyzer, RelationType, SyntaxEngine};

#[test]
fn lexical_morphology_and_affix_offsets_are_stable() {
    let analyzer = MorphologicalAnalyzer::default();
    let analysis = analyzer.best("وبالمدرسة", 0.0).expect("analysis");
    assert_eq!(analysis.lemma, "مدرسة");
    assert_eq!(analysis.root.as_deref(), Some("درس"));
    assert_eq!(
        analysis
            .prefixes
            .iter()
            .map(|part| (part.surface.as_str(), part.start, part.end))
            .collect::<Vec<_>>(),
        vec![("و", 0, 1), ("ب", 1, 2), ("ال", 2, 4)]
    );
}

#[test]
fn derivational_pattern_extracts_the_oracle_root() {
    let analyses = MorphologicalAnalyzer::default()
        .analyze("استعمال", 0.0)
        .unwrap();
    let target = analyses
        .iter()
        .find(|item| item.pattern.as_deref() == Some("استفعال"))
        .unwrap();
    assert_eq!(target.root.as_deref(), Some("عمل"));
    assert_eq!(target.source, "segmented");
}

#[test]
fn syntax_uses_unicode_scalar_offsets_after_astral_text() {
    let text = "😀 هذه الكتاب";
    let engine = SyntaxEngine::default();
    let parsed = engine.parse(text);
    assert_eq!(parsed.sentences[0].tokens[0].start, 2);
    let issue = engine.check_text(text).remove(0);
    assert_eq!(issue.rule_id, "SYNTAX_DEMONSTRATIVE_AGREEMENT");
    assert_eq!(issue.offset, 2);
    assert_eq!(issue.length, 10);
}

#[test]
fn parser_and_checker_share_morphology_selected_relations() {
    let engine = SyntaxEngine::default();
    let parsed = engine.parse_sentence("لن يكتبون", 0);
    assert!(parsed
        .relations
        .iter()
        .any(|item| item.relation == RelationType::SubjunctiveVerb));
    let issues = engine.check_text("لن يكتبون");
    assert_eq!(issues[0].rule_id, "SYNTAX_SUBJUNCTIVE_FIVE_VERBS");
    assert_eq!(issues[0].replacements, vec!["يكتبوا"]);
}
