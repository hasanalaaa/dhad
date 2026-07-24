//! Portable literal-rule engine — the deterministic browser subset.
//!
//! Loads the rule pack exported by `tools/export_wasm_rules.py` (every
//! `literal` rule with plain word-boundary semantics) and scans text with
//! char-accurate offsets. Boundary semantics mirror the Python engine's
//! `B_LEFT`/`B_RIGHT` lookarounds: the characters immediately before and
//! after an occurrence must not be Arabic word characters. Parity with the
//! Python oracle is enforced by `tests/rules_parity.rs` over the shared
//! golden corpus.

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, VecDeque};

use crate::text::is_arabic_word_char_pub;

#[derive(Debug, Clone, Deserialize)]
pub struct LiteralRule {
    pub id: String,
    pub pattern: String,
    #[serde(default)]
    pub suggestions: Vec<String>,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub category: String,
    #[serde(default = "default_severity")]
    pub severity: String,
    #[serde(default = "default_confidence")]
    pub confidence: f64,
    #[serde(default)]
    pub priority: i32,
    #[serde(default)]
    pub autofix: bool,
    #[serde(default)]
    pub explanation: String,
}

fn default_severity() -> String {
    "error".to_string()
}

fn default_confidence() -> f64 {
    0.8
}

#[derive(Debug, Clone, Deserialize)]
struct RulePack {
    #[allow(dead_code)]
    format: u32,
    rules: Vec<LiteralRule>,
}

/// One issue found in the input, mirroring `dhad.match.Match` field-for-field
/// on the portable subset. Offsets are char offsets into the original text.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuleMatch {
    pub rule_id: String,
    pub category: String,
    pub message: String,
    pub offset: usize,
    pub length: usize,
    pub replacements: Vec<String>,
    pub severity: String,
    pub explanation: String,
    pub autofix: bool,
    pub confidence: f64,
    pub priority: i32,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub references: Vec<String>,
    #[serde(default = "default_profiles")]
    pub profiles: Vec<String>,
}

fn default_profiles() -> Vec<String> {
    vec!["default".to_string()]
}

#[derive(Default)]
struct AutomatonState {
    transitions: HashMap<char, usize>,
    failure: usize,
    outputs: Vec<(usize, usize)>,
}

struct LiteralHit {
    rule_index: usize,
    start: usize,
    end: usize,
}

struct LiteralAutomaton {
    states: Vec<AutomatonState>,
}

impl LiteralAutomaton {
    fn new(rules: &[LiteralRule]) -> Self {
        let mut automaton = Self {
            states: vec![AutomatonState::default()],
        };
        for (rule_index, rule) in rules.iter().enumerate() {
            let pattern: Vec<char> = rule.pattern.chars().collect();
            if pattern.is_empty() {
                continue;
            }
            let mut state = 0usize;
            for character in &pattern {
                let next = if let Some(next) = automaton.states[state].transitions.get(character) {
                    *next
                } else {
                    let next = automaton.states.len();
                    automaton.states.push(AutomatonState::default());
                    automaton.states[state].transitions.insert(*character, next);
                    next
                };
                state = next;
            }
            automaton.states[state]
                .outputs
                .push((rule_index, pattern.len()));
        }
        automaton.build_failure_links();
        automaton
    }

    fn build_failure_links(&mut self) {
        let mut pending: VecDeque<usize> = self.states[0].transitions.values().copied().collect();
        while let Some(state_index) = pending.pop_front() {
            let transitions: Vec<(char, usize)> = self.states[state_index]
                .transitions
                .iter()
                .map(|(character, child)| (*character, *child))
                .collect();
            for (character, child_index) in transitions {
                pending.push_back(child_index);
                let mut failure = self.states[state_index].failure;
                while failure != 0 && !self.states[failure].transitions.contains_key(&character) {
                    failure = self.states[failure].failure;
                }
                let target = self.states[failure]
                    .transitions
                    .get(&character)
                    .copied()
                    .unwrap_or(0);
                self.states[child_index].failure = target;
                let inherited = self.states[target].outputs.clone();
                self.states[child_index].outputs.extend(inherited);
            }
        }
    }

    fn scan(&self, chars: &[char]) -> (Vec<LiteralHit>, usize) {
        let mut state = 0usize;
        let mut transitions = 0usize;
        let mut hits = Vec::new();
        for (index, character) in chars.iter().enumerate() {
            transitions += 1;
            while state != 0 && !self.states[state].transitions.contains_key(character) {
                state = self.states[state].failure;
                transitions += 1;
            }
            state = self.states[state]
                .transitions
                .get(character)
                .copied()
                .unwrap_or(0);
            for (rule_index, length) in &self.states[state].outputs {
                let start = index + 1 - length;
                let end = index + 1;
                let left_ok = start == 0 || !is_arabic_word_char_pub(chars[start - 1]);
                let right_ok = end == chars.len() || !is_arabic_word_char_pub(chars[end]);
                if left_ok && right_ok {
                    hits.push(LiteralHit {
                        rule_index: *rule_index,
                        start,
                        end,
                    });
                }
            }
        }
        (hits, transitions)
    }
}

pub struct RuleSet {
    rules: Vec<LiteralRule>,
    automaton: LiteralAutomaton,
}

impl RuleSet {
    pub fn from_json(payload: &str) -> Result<Self, String> {
        let pack: RulePack =
            serde_json::from_str(payload).map_err(|error| format!("invalid rule pack: {error}"))?;
        let rules = pack.rules;
        let automaton = LiteralAutomaton::new(&rules);
        Ok(Self { rules, automaton })
    }

    pub fn len(&self) -> usize {
        self.rules.len()
    }

    pub fn is_empty(&self) -> bool {
        self.rules.is_empty()
    }

    /// Scan `text`, returning matches in rule-major order (the same order
    /// the Python oracle produces when applying each rule sequentially).
    pub fn check(&self, text: &str) -> Vec<RuleMatch> {
        self.check_internal(text).0
    }

    fn check_internal(&self, text: &str) -> (Vec<RuleMatch>, usize) {
        let chars: Vec<char> = text.chars().collect();
        let (mut hits, transitions) = self.automaton.scan(&chars);
        hits.sort_by_key(|hit| (hit.rule_index, hit.start, hit.end));
        let mut last_ends = vec![None; self.rules.len()];
        let mut out = Vec::with_capacity(hits.len());
        for hit in hits {
            if last_ends[hit.rule_index].is_some_and(|end| hit.start < end) {
                continue;
            }
            last_ends[hit.rule_index] = Some(hit.end);
            let rule = &self.rules[hit.rule_index];
            out.push(RuleMatch {
                rule_id: rule.id.clone(),
                category: rule.category.clone(),
                message: rule.message.clone(),
                offset: hit.start,
                length: hit.end - hit.start,
                replacements: rule.suggestions.clone(),
                severity: rule.severity.clone(),
                explanation: rule.explanation.clone(),
                autofix: rule.autofix,
                confidence: rule.confidence,
                priority: rule.priority,
                tags: Vec::new(),
                references: Vec::new(),
                profiles: default_profiles(),
            });
        }
        (out, transitions)
    }

    #[cfg(test)]
    fn check_with_transition_count(&self, text: &str) -> (Vec<RuleMatch>, usize) {
        self.check_internal(text)
    }
}

#[cfg(test)]
mod tests {
    use super::RuleSet;

    #[test]
    fn all_literal_rules_share_one_linear_automaton_scan() {
        let payload = r#"{
            "format": 1,
            "rules": [
                {"id":"SHORT","pattern":"خطا","suggestions":["خطأ"]},
                {"id":"LONG","pattern":"خطاب","suggestions":["رسالة"]}
            ]
        }"#;
        let rules = RuleSet::from_json(payload).expect("valid rule pack");
        let text = "خطا خطاب خطا";

        let (matches, transitions) = rules.check_with_transition_count(text);

        assert_eq!(
            matches
                .iter()
                .map(|item| (item.rule_id.as_str(), item.offset, item.length))
                .collect::<Vec<_>>(),
            vec![("SHORT", 0, 3), ("SHORT", 9, 3), ("LONG", 4, 4)]
        );
        assert!(transitions <= 2 * text.chars().count());
    }
}
