//! Deterministic Arabic morphology ported from `dhad.morphology`.
//!
//! The Python package remains the behavioral oracle.  Its versioned lexicon is
//! compiled at build time by `tools/export_wasm_morphology.py` and embedded in
//! the binary, while analysis, segmentation, pattern matching, ranking, and
//! feature handling execute natively in Rust/WASM.

use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::OnceLock;

use serde::{Deserialize, Serialize};

use crate::text::{normalize, NormalizationMode};

pub type Features = BTreeMap<String, String>;

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct AffixSegment {
    pub kind: String,
    pub surface: String,
    pub start: usize,
    pub end: usize,
    pub feature: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MorphologicalAnalysis {
    pub token: String,
    pub normalized: String,
    pub stem: String,
    pub lemma: String,
    pub root: Option<String>,
    pub pattern: Option<String>,
    pub pos: String,
    pub prefixes: Vec<AffixSegment>,
    pub suffixes: Vec<AffixSegment>,
    pub infixes: Vec<AffixSegment>,
    pub features: Features,
    pub confidence: f64,
    pub source: String,
    pub frequency: i64,
}

impl MorphologicalAnalysis {
    pub fn feature(&self, name: &str) -> Option<&str> {
        self.features.get(name).map(String::as_str)
    }

    pub fn is_lexical(&self) -> bool {
        matches!(self.source.as_str(), "lexicon" | "generated")
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct Lexeme {
    pub lemma: String,
    pub root: Option<String>,
    pub pattern: Option<String>,
    pub pos: String,
    pub frequency: i64,
    #[serde(default)]
    pub features: Features,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FormRecord {
    pub form: String,
    pub lexeme: usize,
    #[serde(default)]
    pub prefixes: Vec<(String, String)>,
    #[serde(default)]
    pub suffixes: Vec<(String, String)>,
    #[serde(default)]
    pub features: Features,
    pub source: String,
    pub confidence: f64,
}

#[derive(Deserialize)]
struct MorphologyPack {
    #[allow(dead_code)]
    format: u32,
    version: String,
    lexemes: Vec<Lexeme>,
    records: Vec<FormRecord>,
}

pub struct MorphologicalLexicon {
    pub version: String,
    pub lexemes: Vec<Lexeme>,
    records: Vec<FormRecord>,
    form_index: HashMap<String, Vec<usize>>,
    lemma_form_index: HashMap<String, Vec<usize>>,
    root_index: HashMap<String, Vec<usize>>,
}

impl MorphologicalLexicon {
    fn embedded() -> Self {
        let serialized = miniz_oxide::inflate::decompress_to_vec_zlib(include_bytes!(
            "../data/morphology.json.zlib"
        ))
        .expect("embedded morphology pack must decompress");
        let pack: MorphologyPack =
            serde_json::from_slice(&serialized).expect("embedded morphology pack must be valid");
        let mut form_index: HashMap<String, Vec<usize>> = HashMap::new();
        let mut lemma_form_index: HashMap<String, Vec<usize>> = HashMap::new();
        let mut root_index: HashMap<String, Vec<usize>> = HashMap::new();
        for (index, lexeme) in pack.lexemes.iter().enumerate() {
            if let Some(root) = &lexeme.root {
                root_index.entry(root.clone()).or_default().push(index);
            }
        }
        for (index, record) in pack.records.iter().enumerate() {
            form_index
                .entry(record.form.clone())
                .or_default()
                .push(index);
            let lemma = pack.lexemes[record.lexeme].lemma.clone();
            lemma_form_index.entry(lemma).or_default().push(index);
        }
        let compare = |left: &usize, right: &usize| {
            let a = &pack.records[*left];
            let b = &pack.records[*right];
            b.confidence
                .partial_cmp(&a.confidence)
                .unwrap_or(Ordering::Equal)
                .then(
                    pack.lexemes[b.lexeme]
                        .frequency
                        .cmp(&pack.lexemes[a.lexeme].frequency),
                )
                .then(a.form.cmp(&b.form))
        };
        for values in form_index.values_mut() {
            values.sort_by(compare);
        }
        for values in lemma_form_index.values_mut() {
            values.sort_by(compare);
        }
        Self {
            version: pack.version,
            lexemes: pack.lexemes,
            records: pack.records,
            form_index,
            lemma_form_index,
            root_index,
        }
    }

    pub fn lookup(&self, form: &str) -> Vec<&FormRecord> {
        let key = normalize(form, NormalizationMode::Lookup);
        self.form_index
            .get(&key)
            .map(|values| values.iter().map(|index| &self.records[*index]).collect())
            .unwrap_or_default()
    }

    pub fn by_root(&self, root: &str) -> Vec<&Lexeme> {
        let key = normalize(root, NormalizationMode::Lookup);
        self.root_index
            .get(&key)
            .map(|values| values.iter().map(|index| &self.lexemes[*index]).collect())
            .unwrap_or_default()
    }

    pub fn forms_for_lemma(
        &self,
        lemma: &str,
        pos: Option<&str>,
        features: &Features,
    ) -> Vec<&FormRecord> {
        let key = normalize(lemma, NormalizationMode::Lookup);
        self.lemma_form_index
            .get(&key)
            .into_iter()
            .flatten()
            .filter_map(|index| {
                let record = &self.records[*index];
                let lexeme = &self.lexemes[record.lexeme];
                let record_pos = record
                    .features
                    .get("pos")
                    .map(String::as_str)
                    .unwrap_or(&lexeme.pos);
                if pos.is_some_and(|expected| expected != record_pos) {
                    return None;
                }
                let available = |name: &str| {
                    record
                        .features
                        .get(name)
                        .or_else(|| lexeme.features.get(name))
                };
                if features
                    .iter()
                    .all(|(name, value)| available(name).is_some_and(|actual| actual == value))
                {
                    Some(record)
                } else {
                    None
                }
            })
            .collect()
    }

    pub fn roots_contains(&self, root: &str) -> bool {
        self.root_index.contains_key(root)
    }
}

static LEXICON: OnceLock<MorphologicalLexicon> = OnceLock::new();

pub fn default_lexicon() -> &'static MorphologicalLexicon {
    LEXICON.get_or_init(MorphologicalLexicon::embedded)
}

#[derive(Clone, Copy)]
struct PatternTemplate {
    name: &'static str,
    template: &'static str,
    pos: &'static str,
    confidence: f64,
}

const PATTERNS: &[PatternTemplate] = &[
    PatternTemplate {
        name: "استفعال",
        template: "استفعال",
        pos: "verbal_noun",
        confidence: 0.68,
    },
    PatternTemplate {
        name: "استفعل",
        template: "استفعل",
        pos: "verb",
        confidence: 0.66,
    },
    PatternTemplate {
        name: "انفعال",
        template: "انفعال",
        pos: "verbal_noun",
        confidence: 0.65,
    },
    PatternTemplate {
        name: "افتعال",
        template: "افتعال",
        pos: "verbal_noun",
        confidence: 0.68,
    },
    PatternTemplate {
        name: "مفاعلة",
        template: "مفاعلة",
        pos: "verbal_noun",
        confidence: 0.67,
    },
    PatternTemplate {
        name: "تفاعل",
        template: "تفاعل",
        pos: "verb",
        confidence: 0.62,
    },
    PatternTemplate {
        name: "افتعل",
        template: "افتعل",
        pos: "verb",
        confidence: 0.63,
    },
    PatternTemplate {
        name: "انفعل",
        template: "انفعل",
        pos: "verb",
        confidence: 0.62,
    },
    PatternTemplate {
        name: "تفعيل",
        template: "تفعيل",
        pos: "verbal_noun",
        confidence: 0.66,
    },
    PatternTemplate {
        name: "مفعول",
        template: "مفعول",
        pos: "adjective",
        confidence: 0.64,
    },
    PatternTemplate {
        name: "مفعال",
        template: "مفعال",
        pos: "noun",
        confidence: 0.58,
    },
    PatternTemplate {
        name: "فعالة",
        template: "فعالة",
        pos: "noun",
        confidence: 0.58,
    },
    PatternTemplate {
        name: "فعيلة",
        template: "فعيلة",
        pos: "noun",
        confidence: 0.58,
    },
    PatternTemplate {
        name: "فاعل",
        template: "فاعل",
        pos: "noun",
        confidence: 0.63,
    },
    PatternTemplate {
        name: "فعال",
        template: "فعال",
        pos: "noun",
        confidence: 0.57,
    },
    PatternTemplate {
        name: "فعيل",
        template: "فعيل",
        pos: "adjective",
        confidence: 0.57,
    },
    PatternTemplate {
        name: "أفعل",
        template: "أفعل",
        pos: "verb",
        confidence: 0.59,
    },
    PatternTemplate {
        name: "تفعل",
        template: "تفعل",
        pos: "verb",
        confidence: 0.56,
    },
    PatternTemplate {
        name: "مفعل",
        template: "مفعل",
        pos: "noun",
        confidence: 0.55,
    },
    PatternTemplate {
        name: "فعلل",
        template: "فعلل",
        pos: "verb",
        confidence: 0.50,
    },
    PatternTemplate {
        name: "فعل",
        template: "فعل",
        pos: "verb",
        confidence: 0.47,
    },
];

const PREFIX_FORMS: &[(&str, &[(&str, &str)])] = &[
    (
        "وبال",
        &[
            ("و", "conjunction"),
            ("ب", "preposition"),
            ("ال", "definite"),
        ],
    ),
    (
        "فبال",
        &[
            ("ف", "conjunction"),
            ("ب", "preposition"),
            ("ال", "definite"),
        ],
    ),
    (
        "ولل",
        &[
            ("و", "conjunction"),
            ("ل", "preposition"),
            ("ال", "definite"),
        ],
    ),
    (
        "فلل",
        &[
            ("ف", "conjunction"),
            ("ل", "preposition"),
            ("ال", "definite"),
        ],
    ),
    ("وال", &[("و", "conjunction"), ("ال", "definite")]),
    ("فال", &[("ف", "conjunction"), ("ال", "definite")]),
    ("بال", &[("ب", "preposition"), ("ال", "definite")]),
    ("كال", &[("ك", "preposition"), ("ال", "definite")]),
    ("لل", &[("ل", "preposition"), ("ال", "definite")]),
    ("وس", &[("و", "conjunction"), ("س", "future")]),
    ("فس", &[("ف", "conjunction"), ("س", "future")]),
    ("ال", &[("ال", "definite")]),
    ("و", &[("و", "conjunction")]),
    ("ف", &[("ف", "conjunction")]),
    ("ب", &[("ب", "preposition")]),
    ("ك", &[("ك", "preposition")]),
    ("ل", &[("ل", "preposition")]),
    ("س", &[("س", "future")]),
];

const SUFFIX_FORMS: &[(&str, &str)] = &[
    ("كما", "pronoun_dual"),
    ("هما", "pronoun_dual"),
    ("كن", "pronoun_feminine_plural"),
    ("هم", "pronoun_masculine_plural"),
    ("هن", "pronoun_feminine_plural"),
    ("نا", "pronoun_first_plural"),
    ("تان", "dual_feminine_nominative"),
    ("تين", "dual_feminine_oblique"),
    ("ون", "plural_masculine_nominative"),
    ("ين", "plural_masculine_oblique"),
    ("ان", "dual_nominative"),
    ("ات", "plural_feminine"),
    ("وا", "verb_past_plural"),
    ("تم", "verb_second_plural"),
    ("تن", "verb_second_feminine_plural"),
    ("ه", "pronoun_masculine"),
    ("ها", "pronoun_feminine"),
    ("ك", "pronoun_second"),
    ("ي", "pronoun_first"),
    ("ة", "feminine"),
];

fn char_len(value: &str) -> usize {
    value.chars().count()
}

fn char_slice(value: &str, start: usize, end: usize) -> String {
    value
        .chars()
        .skip(start)
        .take(end.saturating_sub(start))
        .collect()
}

fn surface_prefix(surface: &str, units: &[(String, String)]) -> Vec<AffixSegment> {
    let source: Vec<char> = surface.chars().collect();
    let mut cursor = 0usize;
    units
        .iter()
        .map(|(unit, feature)| {
            let written: Vec<char> = unit.chars().collect();
            let (start, end) = if surface == "لل" && unit == "ال" {
                (1, 2)
            } else if cursor + written.len() <= source.len()
                && source[cursor..cursor + written.len()] == written[..]
            {
                (cursor, cursor + written.len())
            } else {
                (cursor, source.len().min(cursor + 1))
            };
            cursor = end;
            AffixSegment {
                kind: "prefix".into(),
                surface: unit.clone(),
                start,
                end,
                feature: feature.clone(),
            }
        })
        .collect()
}

fn surface_suffix(token_length: usize, units: &[(String, String)]) -> Vec<AffixSegment> {
    let total: usize = units.iter().map(|(surface, _)| char_len(surface)).sum();
    let mut cursor = token_length.saturating_sub(total);
    units
        .iter()
        .map(|(surface, feature)| {
            let start = cursor;
            cursor += char_len(surface);
            AffixSegment {
                kind: "suffix".into(),
                surface: surface.clone(),
                start,
                end: cursor,
                feature: feature.clone(),
            }
        })
        .collect()
}

fn is_arabic_letter(value: char) -> bool {
    "ابتثجحخدذرزسشصضطظعغفقكلمنهويءأإآؤئىةٱپچژڤگ".contains(value)
}

fn match_pattern(stem: &str, template: PatternTemplate) -> Option<(String, Vec<AffixSegment>)> {
    let stem_chars: Vec<char> = stem.chars().collect();
    let template_chars: Vec<char> = template.template.chars().collect();
    if stem_chars.len() != template_chars.len() {
        return None;
    }
    let mut root = String::new();
    let mut infixes = Vec::new();
    for (index, (value, marker)) in stem_chars.iter().zip(template_chars).enumerate() {
        if "فعل".contains(marker) {
            root.push(*value);
        } else if *value != marker {
            return None;
        } else {
            infixes.push(AffixSegment {
                kind: "infix".into(),
                surface: value.to_string(),
                start: index,
                end: index + 1,
                feature: format!("pattern:{marker}"),
            });
        }
    }
    if !matches!(char_len(&root), 3 | 4) || !root.chars().all(is_arabic_letter) {
        return None;
    }
    Some((root, infixes))
}

pub struct MorphologicalAnalyzer {
    lexicon: &'static MorphologicalLexicon,
}

impl Default for MorphologicalAnalyzer {
    fn default() -> Self {
        Self {
            lexicon: default_lexicon(),
        }
    }
}

impl MorphologicalAnalyzer {
    pub fn lexicon(&self) -> &'static MorphologicalLexicon {
        self.lexicon
    }

    fn analysis_from_record(&self, token: &str, record: &FormRecord) -> MorphologicalAnalysis {
        let lexeme = &self.lexicon.lexemes[record.lexeme];
        let prefix_length: usize = record
            .prefixes
            .iter()
            .map(|(value, _)| char_len(value))
            .sum();
        let suffix_length: usize = record
            .suffixes
            .iter()
            .map(|(value, _)| char_len(value))
            .sum();
        let token_length = char_len(token);
        let stem_end = if suffix_length > 0 {
            token_length.saturating_sub(suffix_length)
        } else {
            token_length
        };
        let stem = char_slice(token, prefix_length, stem_end);
        let mut features = lexeme.features.clone();
        features.extend(record.features.clone());
        let mut infixes = Vec::new();
        if let Some(pattern_name) = &lexeme.pattern {
            if let Some(template) = PATTERNS.iter().find(|item| item.name == pattern_name) {
                if let Some((_, lemma_infixes)) = match_pattern(&lexeme.lemma, *template) {
                    for segment in lemma_infixes {
                        if prefix_length + segment.end <= token_length.saturating_sub(suffix_length)
                        {
                            infixes.push(AffixSegment {
                                kind: "infix".into(),
                                surface: segment.surface,
                                start: prefix_length + segment.start,
                                end: prefix_length + segment.end,
                                feature: segment.feature,
                            });
                        }
                    }
                }
            }
        }
        MorphologicalAnalysis {
            token: token.into(),
            normalized: token.into(),
            stem: if stem.is_empty() {
                lexeme.lemma.clone()
            } else {
                stem
            },
            lemma: lexeme.lemma.clone(),
            root: lexeme.root.clone(),
            pattern: lexeme.pattern.clone(),
            pos: record
                .features
                .get("pos")
                .cloned()
                .unwrap_or_else(|| lexeme.pos.clone()),
            prefixes: if record.prefixes.is_empty() {
                Vec::new()
            } else {
                surface_prefix(&char_slice(token, 0, prefix_length), &record.prefixes)
            },
            suffixes: if record.suffixes.is_empty() {
                Vec::new()
            } else {
                surface_suffix(token_length, &record.suffixes)
            },
            infixes,
            features,
            confidence: record.confidence,
            source: record.source.clone(),
            frequency: lexeme.frequency,
        }
    }

    fn pattern_candidates(&self, token: &str) -> Vec<MorphologicalAnalysis> {
        type Stem = (String, Vec<AffixSegment>, Vec<AffixSegment>, f64);
        let token_length = char_len(token);
        let mut stems: Vec<Stem> = vec![(token.into(), Vec::new(), Vec::new(), 0.0)];
        for (surface, units) in PREFIX_FORMS {
            let length = char_len(surface);
            if token.starts_with(surface) && token_length.saturating_sub(length) >= 3 {
                let owned: Vec<(String, String)> = units
                    .iter()
                    .map(|(a, b)| ((*a).into(), (*b).into()))
                    .collect();
                stems.push((
                    char_slice(token, length, token_length),
                    surface_prefix(surface, &owned),
                    Vec::new(),
                    0.05,
                ));
            }
        }
        for (suffix, feature) in SUFFIX_FORMS {
            let length = char_len(suffix);
            if token.ends_with(suffix) && token_length.saturating_sub(length) >= 3 {
                let stem = char_slice(token, 0, token_length - length);
                let units = vec![(String::from(*suffix), String::from(*feature))];
                let suffixes = surface_suffix(token_length, &units);
                stems.push((stem.clone(), Vec::new(), suffixes.clone(), 0.06));
                if matches!(*suffix, "ات" | "تان" | "تين") {
                    stems.push((format!("{stem}ة"), Vec::new(), suffixes.clone(), 0.09));
                }
                if matches!(*suffix, "ها" | "ه" | "هم" | "هن" | "نا" | "ك" | "ي")
                    && stem.ends_with('ت')
                {
                    let mut restored: String = stem.chars().take(char_len(&stem) - 1).collect();
                    restored.push('ة');
                    stems.push((restored, Vec::new(), suffixes, 0.08));
                }
            }
        }
        for (prefix, prefix_units) in PREFIX_FORMS {
            if !token.starts_with(prefix) {
                continue;
            }
            let prefix_length = char_len(prefix);
            let remainder = char_slice(token, prefix_length, token_length);
            let remainder_length = char_len(&remainder);
            for (suffix, feature) in SUFFIX_FORMS {
                let suffix_length = char_len(suffix);
                if remainder.ends_with(suffix)
                    && remainder_length.saturating_sub(suffix_length) >= 3
                {
                    let units: Vec<(String, String)> = prefix_units
                        .iter()
                        .map(|(a, b)| ((*a).into(), (*b).into()))
                        .collect();
                    let suffix_units = vec![(String::from(*suffix), String::from(*feature))];
                    stems.push((
                        char_slice(&remainder, 0, remainder_length - suffix_length),
                        surface_prefix(prefix, &units),
                        surface_suffix(token_length, &suffix_units),
                        0.10,
                    ));
                }
            }
        }
        let mut seen: HashSet<(String, String, Vec<AffixSegment>, Vec<AffixSegment>)> =
            HashSet::new();
        let mut out = Vec::new();
        for (stem, prefixes, suffixes, penalty) in stems {
            for template in PATTERNS {
                let Some((root, infixes)) = match_pattern(&stem, *template) else {
                    continue;
                };
                let known_root = self.lexicon.roots_contains(&root);
                let confidence = (template.confidence + if known_root { 0.17 } else { 0.0 }
                    - penalty)
                    .clamp(0.25, 0.86);
                let lemmas = self.lexicon.by_root(&root);
                let lemma = lemmas
                    .first()
                    .map(|item| item.lemma.clone())
                    .unwrap_or_else(|| stem.clone());
                let frequency = lemmas.iter().map(|item| item.frequency).max().unwrap_or(1);
                let key = (
                    lemma.clone(),
                    template.name.into(),
                    prefixes.clone(),
                    suffixes.clone(),
                );
                if !seen.insert(key) {
                    continue;
                }
                out.push(MorphologicalAnalysis {
                    token: token.into(),
                    normalized: token.into(),
                    stem: stem.clone(),
                    lemma,
                    root: Some(root),
                    pattern: Some(template.name.into()),
                    pos: lemmas
                        .first()
                        .map(|item| item.pos.clone())
                        .unwrap_or_else(|| template.pos.into()),
                    prefixes: prefixes.clone(),
                    suffixes: suffixes.clone(),
                    infixes,
                    features: Features::new(),
                    confidence,
                    source: if known_root {
                        "segmented".into()
                    } else {
                        "pattern".into()
                    },
                    frequency,
                });
            }
        }
        out
    }

    fn analyze_normalized(&self, token: &str) -> Vec<MorphologicalAnalysis> {
        if token.is_empty() || !token.chars().all(is_arabic_letter) {
            return Vec::new();
        }
        let mut analyses: Vec<_> = self
            .lexicon
            .lookup(token)
            .into_iter()
            .map(|record| self.analysis_from_record(token, record))
            .collect();
        analyses.extend(self.pattern_candidates(token));
        type AnalysisKey = (
            String,
            Option<String>,
            Option<String>,
            String,
            Vec<AffixSegment>,
            Vec<AffixSegment>,
        );
        let mut positions: HashMap<AnalysisKey, usize> = HashMap::new();
        let mut values: Vec<MorphologicalAnalysis> = Vec::new();
        for analysis in analyses {
            let key = (
                analysis.lemma.clone(),
                analysis.root.clone(),
                analysis.pattern.clone(),
                analysis.pos.clone(),
                analysis.prefixes.clone(),
                analysis.suffixes.clone(),
            );
            if let Some(index) = positions.get(&key).copied() {
                if analysis.confidence > values[index].confidence {
                    values[index] = analysis;
                }
            } else {
                positions.insert(key, values.len());
                values.push(analysis);
            }
        }
        values.sort_by(|a, b| {
            b.confidence
                .partial_cmp(&a.confidence)
                .unwrap_or(Ordering::Equal)
                .then(b.frequency.cmp(&a.frequency))
                .then(a.lemma.cmp(&b.lemma))
                .then(
                    a.pattern
                        .as_deref()
                        .unwrap_or("")
                        .cmp(b.pattern.as_deref().unwrap_or("")),
                )
        });
        values
    }

    pub fn analyze(
        &self,
        token: &str,
        min_confidence: f64,
    ) -> Result<Vec<MorphologicalAnalysis>, String> {
        if !(0.0..=1.0).contains(&min_confidence) {
            return Err("min_confidence must be between 0 and 1".into());
        }
        let normalized = normalize(token, NormalizationMode::Lookup);
        let mut values = self.analyze_normalized(&normalized);
        if token != normalized {
            for item in &mut values {
                item.token = token.into();
            }
        }
        values.retain(|item| item.confidence >= min_confidence);
        Ok(values)
    }

    pub fn best(&self, token: &str, min_confidence: f64) -> Option<MorphologicalAnalysis> {
        self.analyze(token, min_confidence).ok()?.into_iter().next()
    }
}
