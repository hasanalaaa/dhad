//! Parity of the portable literal-rule engine and the ported `dedupe`
//! against the Python oracle over the shared golden corpus.

use serde::Deserialize;

use dhad_core::rules::RuleSet;
use dhad_core::spans::{dedupe, FrozenSpanIndex};

#[derive(Deserialize)]
struct Record {
    text: String,
    matches: Vec<(String, usize, usize, String)>,
    resolved: Vec<(String, usize, usize)>,
}

fn rule_pack() -> RuleSet {
    // The web_demo rule pack is the single source of truth for both the
    // browser and this test; the golden corpus was generated against it.
    let payload = include_str!("../../../web_demo/rules.json");
    RuleSet::from_json(payload).expect("rule pack must parse")
}

fn records() -> Vec<Record> {
    include_str!("data/rules_golden.jsonl")
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| serde_json::from_str(line).expect("golden line must parse"))
        .collect()
}

#[test]
fn literal_scan_matches_python_oracle() {
    let rules = rule_pack();
    assert!(rules.len() >= 100, "expected the full portable subset");
    for record in records() {
        let actual: Vec<(String, usize, usize, String)> = rules
            .check(&record.text)
            .into_iter()
            .map(|m| {
                (
                    m.rule_id,
                    m.offset,
                    m.length,
                    m.replacements.first().cloned().unwrap_or_default(),
                )
            })
            .collect();
        assert_eq!(
            actual, record.matches,
            "scan diverged for: {:?}",
            record.text
        );
    }
}

#[test]
fn dedupe_matches_python_oracle() {
    let rules = rule_pack();
    for record in records() {
        let resolved: Vec<(String, usize, usize)> = dedupe(rules.check(&record.text))
            .into_iter()
            .map(|m| (m.rule_id, m.offset, m.length))
            .collect();
        assert_eq!(
            resolved, record.resolved,
            "dedupe diverged for: {:?}",
            record.text
        );
    }
}

#[test]
fn frozen_span_index_answers_bruteforce() {
    let spans = vec![(0usize, 3usize), (5, 9), (7, 12), (20, 21)];
    let index = FrozenSpanIndex::new(spans.clone());
    for start in 0..25 {
        for width in 1..6 {
            let end = start + width;
            let expected = spans.iter().any(|(s, e)| start < *e && *s < end);
            assert_eq!(index.overlaps(start, end), expected, "({start}, {end})");
        }
    }
}
