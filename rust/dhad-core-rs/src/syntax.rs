//! Precision-gated deterministic Arabic syntax ported from `dhad.syntax`.
//!
//! All public spans are Unicode-scalar offsets, exactly matching Python string
//! indexing.  The parser retains alternative morphological readings and emits
//! the same explainable relations, candidate i'rab, and conservative grammar
//! diagnostics as the Python oracle.

use std::cmp::Ordering;
use std::collections::{BTreeMap, HashMap};

use serde::{Deserialize, Serialize};

use crate::morphology::{Features, MorphologicalAnalysis, MorphologicalAnalyzer};
use crate::rules::RuleMatch;
use crate::text::{
    normalize, sentence_spans, tokenize_all, NormalizationMode, Sentence, TokenKind,
};

const NOMINAL_POS: &[&str] = &["noun", "proper_noun", "verbal_noun"];
const PREPOSITIONS: &[&str] = &[
    "في", "من", "إلى", "على", "عن", "مع", "لدى", "عند", "بين", "حول", "خلال", "دون", "قبل", "بعد",
];
const SUBJUNCTIVE_PARTICLES: &[&str] = &["لن", "أن", "كي", "حتى"];
const JUSSIVE_PARTICLES: &[&str] = &["لم", "لما"];
const DEMONSTRATIVES: &[(&str, &str, &str)] = &[
    ("هذا", "masculine", "singular"),
    ("هذه", "feminine", "singular"),
    ("ذلك", "masculine", "singular"),
    ("تلك", "feminine", "singular"),
    ("هذان", "masculine", "dual"),
    ("هذين", "masculine", "dual"),
    ("هاتان", "feminine", "dual"),
    ("هاتين", "feminine", "dual"),
    ("هؤلاء", "common", "plural"),
    ("أولئك", "common", "plural"),
];
const INTRANSITIVE_VERBS: &[&str] = &["جاء", "حضر", "ذهب", "وصل", "اكتمل", "انتهى", "استمر", "زال"];
const HUMAN_LEMMAS: &[&str] = &[
    "إنسان",
    "أستاذ",
    "طالب",
    "كاتب",
    "مهندس",
    "موظف",
    "مستخدم",
    "رجل",
    "والي",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RelationType {
    Demonstrative,
    Subject,
    Naat,
    Idafa,
    PrepositionObject,
    SubjunctiveVerb,
    JussiveVerb,
}

impl RelationType {
    fn as_str(self) -> &'static str {
        match self {
            Self::Demonstrative => "demonstrative",
            Self::Subject => "subject",
            Self::Naat => "naat",
            Self::Idafa => "idafa",
            Self::PrepositionObject => "preposition_object",
            Self::SubjunctiveVerb => "subjunctive_verb",
            Self::JussiveVerb => "jussive_verb",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SyntaxToken {
    pub text: String,
    pub start: usize,
    pub end: usize,
    pub analysis: Option<MorphologicalAnalysis>,
    pub alternatives: Vec<MorphologicalAnalysis>,
    pub confidence: f64,
    pub break_before: bool,
}

impl SyntaxToken {
    pub fn pos(&self) -> &str {
        self.analysis
            .as_ref()
            .map(|item| item.pos.as_str())
            .unwrap_or("unknown")
    }
    pub fn feature(&self, name: &str) -> Option<&str> {
        self.analysis.as_ref().and_then(|item| item.feature(name))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SyntacticRelation {
    pub relation: RelationType,
    pub head_index: Option<usize>,
    pub dependent_index: usize,
    pub confidence: f64,
    pub governor: String,
    pub explanation: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct IrabCandidate {
    pub token_index: usize,
    pub role: String,
    pub case_or_mood: String,
    pub marker: String,
    pub governor_index: Option<usize>,
    pub governor: String,
    pub confidence: f64,
    pub explanation: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SentenceParse {
    pub text: String,
    pub start: usize,
    pub end: usize,
    pub tokens: Vec<SyntaxToken>,
    pub relations: Vec<SyntacticRelation>,
    pub irab: Vec<IrabCandidate>,
    pub confidence: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentParse {
    pub text: String,
    pub sentences: Vec<SentenceParse>,
}

#[derive(Clone)]
struct RawWord {
    text: String,
    start: usize,
    end: usize,
    break_before: bool,
}

fn surface(value: &str) -> String {
    normalize(value, NormalizationMode::Lookup)
}
fn contains(values: &[&str], value: &str) -> bool {
    values.contains(&value)
}
fn is_nominal(token: &SyntaxToken) -> bool {
    contains(NOMINAL_POS, token.pos())
}
fn is_adjective(token: &SyntaxToken) -> bool {
    token.pos() == "adjective"
}
fn is_verb(token: &SyntaxToken) -> bool {
    token.pos() == "verb"
}
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

fn is_definite(token: &SyntaxToken) -> bool {
    let Some(analysis) = &token.analysis else {
        return false;
    };
    token.pos() == "proper_noun"
        || token.feature("definiteness") == Some("definite")
        || analysis
            .prefixes
            .iter()
            .any(|part| part.feature == "definite")
        || analysis
            .suffixes
            .iter()
            .any(|part| part.feature.starts_with("pronoun_"))
}

fn gender(token: &SyntaxToken) -> Option<&str> {
    if let Some(value @ ("masculine" | "feminine")) = token.feature("gender") {
        return Some(value);
    }
    let value = surface(&token.text);
    if ["ة", "ات", "تان", "تين"]
        .iter()
        .any(|ending| value.ends_with(ending))
    {
        Some("feminine")
    } else {
        None
    }
}

fn number(token: &SyntaxToken) -> &str {
    match token.feature("number") {
        Some(value @ ("singular" | "dual" | "plural")) => value,
        _ => "singular",
    }
}

fn aspect(token: &SyntaxToken) -> Option<&str> {
    token.feature("aspect")
}

fn person(token: &SyntaxToken) -> Option<&str> {
    if let Some(value) = token.feature("person") {
        return Some(value);
    }
    if aspect(token) == Some("imperfect") {
        let value = surface(&token.text);
        if value.starts_with('ي') {
            Some("3m")
        } else if value.starts_with('ت') {
            Some("2_or_3f")
        } else if value.starts_with('ن') {
            Some("1p")
        } else if value.starts_with('أ') {
            Some("1s")
        } else {
            None
        }
    } else {
        None
    }
}

fn visible_case(token: &SyntaxToken) -> Option<&str> {
    if let Some(value @ ("nominative" | "oblique")) = token.feature("case") {
        return Some(value);
    }
    let value = surface(&token.text);
    if ["تان", "ان", "ون"]
        .iter()
        .any(|ending| value.ends_with(ending))
    {
        Some("nominative")
    } else if ["تين", "ين"].iter().any(|ending| value.ends_with(ending)) {
        Some("oblique")
    } else {
        None
    }
}

fn governed_five_verb(value: &str) -> Option<String> {
    let length = char_len(value);
    if value.ends_with("ون") && length > 3 {
        Some(format!("{}وا", char_slice(value, 0, length - 2)))
    } else if (value.ends_with("ان") || value.ends_with("ين")) && length > 3 {
        Some(char_slice(value, 0, length - 1))
    } else {
        None
    }
}

fn oblique_surface(value: &str) -> Option<String> {
    let length = char_len(value);
    if value.ends_with("تان") && length > 3 {
        Some(format!("{}تين", char_slice(value, 0, length - 3)))
    } else if (value.ends_with("ان") || value.ends_with("ون")) && length > 3 {
        Some(format!("{}ين", char_slice(value, 0, length - 2)))
    } else {
        None
    }
}

fn idafa_drop_nun(value: &str) -> Option<String> {
    let length = char_len(value);
    if (value.ends_with("ون") || value.ends_with("ان") || value.ends_with("ين")) && length > 3
    {
        Some(char_slice(value, 0, length - 1))
    } else {
        None
    }
}

pub struct SyntaxEngine {
    morphology: MorphologicalAnalyzer,
    pub min_token_confidence: f64,
    pub min_relation_confidence: f64,
}

impl Default for SyntaxEngine {
    fn default() -> Self {
        Self {
            morphology: MorphologicalAnalyzer::default(),
            min_token_confidence: 0.72,
            min_relation_confidence: 0.80,
        }
    }
}

impl SyntaxEngine {
    fn raw_words(sentence: &Sentence) -> Vec<RawWord> {
        let mut words = Vec::new();
        let mut barrier = false;
        for token in tokenize_all(&sentence.text) {
            match token.kind {
                TokenKind::Whitespace => {}
                TokenKind::ArabicWord => {
                    words.push(RawWord {
                        text: token.text,
                        start: sentence.start + token.start,
                        end: sentence.start + token.end,
                        break_before: barrier,
                    });
                    barrier = false;
                }
                TokenKind::Punctuation
                | TokenKind::Symbol
                | TokenKind::Code
                | TokenKind::Url
                | TokenKind::Email => barrier = true,
                _ => {}
            }
        }
        words
    }

    fn context_score(
        analysis: &MorphologicalAnalysis,
        value: &str,
        previous: Option<&str>,
        following: Option<&str>,
    ) -> f64 {
        let mut score = analysis.confidence;
        if DEMONSTRATIVES.iter().any(|item| item.0 == value) {
            score += if analysis.pos == "pronoun" {
                0.25
            } else {
                -0.25
            };
        }
        if contains(PREPOSITIONS, value)
            || contains(SUBJUNCTIVE_PARTICLES, value)
            || contains(JUSSIVE_PARTICLES, value)
        {
            score += if analysis.pos == "particle" {
                0.25
            } else {
                -0.25
            };
        }
        if previous.is_some_and(|item| contains(PREPOSITIONS, item)) {
            score += if contains(NOMINAL_POS, &analysis.pos)
                || matches!(analysis.pos.as_str(), "adjective" | "pronoun")
            {
                0.14
            } else {
                -0.12
            };
        }
        if previous.is_some_and(|item| {
            contains(SUBJUNCTIVE_PARTICLES, item) || contains(JUSSIVE_PARTICLES, item)
        }) {
            score += if analysis.pos == "verb" { 0.18 } else { -0.14 };
            if analysis.feature("aspect") == Some("imperfect") {
                score += 0.08;
            }
        }
        if previous.is_some_and(|item| DEMONSTRATIVES.iter().any(|demo| demo.0 == item)) {
            score += if contains(NOMINAL_POS, &analysis.pos) {
                0.16
            } else {
                -0.10
            };
        }
        if following.is_some_and(|item| item.starts_with("ال"))
            && contains(NOMINAL_POS, &analysis.pos)
        {
            score += 0.03;
        }
        if analysis.is_lexical() {
            score += 0.04;
        }
        score
    }

    fn select_analysis(
        &self,
        word: &RawWord,
        previous: Option<&str>,
        following: Option<&str>,
    ) -> SyntaxToken {
        let mut analyses = self
            .morphology
            .analyze(&word.text, 0.55)
            .unwrap_or_default();
        if analyses.is_empty() {
            return SyntaxToken {
                text: word.text.clone(),
                start: word.start,
                end: word.end,
                analysis: None,
                alternatives: Vec::new(),
                confidence: 0.0,
                break_before: word.break_before,
            };
        }
        let value = surface(&word.text);
        analyses.sort_by(|a, b| {
            Self::context_score(b, &value, previous, following)
                .partial_cmp(&Self::context_score(a, &value, previous, following))
                .unwrap_or(Ordering::Equal)
                .then(
                    b.confidence
                        .partial_cmp(&a.confidence)
                        .unwrap_or(Ordering::Equal),
                )
                .then(b.frequency.cmp(&a.frequency))
                .then(a.lemma.cmp(&b.lemma))
        });
        let best = analyses.remove(0);
        let best_score = Self::context_score(&best, &value, previous, following);
        let second_score = analyses
            .first()
            .map(|item| Self::context_score(item, &value, previous, following))
            .unwrap_or(best_score - 0.30);
        let margin = (best_score - second_score).max(0.0);
        let confidence = (best.confidence * 0.82 + (margin * 0.6).min(0.18)).min(0.999);
        SyntaxToken {
            text: word.text.clone(),
            start: word.start,
            end: word.end,
            analysis: Some(best),
            alternatives: analyses,
            confidence,
            break_before: word.break_before,
        }
    }

    fn relation_confidence(tokens: &[&SyntaxToken], structural: f64) -> f64 {
        let lexical = tokens
            .iter()
            .map(|token| token.confidence)
            .fold(f64::INFINITY, f64::min);
        (structural * 0.55 + if lexical.is_infinite() { 0.0 } else { lexical } * 0.45)
            .clamp(0.0, 0.999)
    }

    fn relation(
        kind: RelationType,
        head: Option<usize>,
        dependent: usize,
        confidence: f64,
        governor: &str,
        explanation: &str,
    ) -> SyntacticRelation {
        SyntacticRelation {
            relation: kind,
            head_index: head,
            dependent_index: dependent,
            confidence,
            governor: governor.into(),
            explanation: explanation.into(),
        }
    }

    fn relations(&self, tokens: &[SyntaxToken]) -> Vec<SyntacticRelation> {
        let mut out = Vec::new();
        for (index, token) in tokens.iter().enumerate() {
            let value = surface(&token.text);
            if let Some(following) = tokens.get(index + 1).filter(|item| !item.break_before) {
                let confidence =
                    |structural| Self::relation_confidence(&[token, following], structural);
                if DEMONSTRATIVES.iter().any(|item| item.0 == value) && is_nominal(following) {
                    out.push(Self::relation(
                        RelationType::Demonstrative,
                        Some(index),
                        index + 1,
                        confidence(0.98),
                        &value,
                        "اسم إشارة يحدد اسمًا ظاهرًا ملاصقًا له.",
                    ));
                }
                if contains(PREPOSITIONS, &value)
                    && (is_nominal(following) || matches!(following.pos(), "adjective" | "pronoun"))
                {
                    out.push(Self::relation(
                        RelationType::PrepositionObject,
                        Some(index),
                        index + 1,
                        confidence(0.97),
                        &value,
                        "حرف الجر يعمل في الاسم الظاهر التالي له.",
                    ));
                }
                if contains(SUBJUNCTIVE_PARTICLES, &value) && is_verb(following) {
                    out.push(Self::relation(
                        RelationType::SubjunctiveVerb,
                        Some(index),
                        index + 1,
                        confidence(0.96),
                        &value,
                        "حرف نصب يسبق فعلًا مضارعًا.",
                    ));
                }
                if contains(JUSSIVE_PARTICLES, &value) && is_verb(following) {
                    out.push(Self::relation(
                        RelationType::JussiveVerb,
                        Some(index),
                        index + 1,
                        confidence(0.97),
                        &value,
                        "حرف جزم يسبق فعلًا مضارعًا.",
                    ));
                }
                if is_nominal(token)
                    && is_adjective(following)
                    && is_definite(token)
                    && is_definite(following)
                {
                    out.push(Self::relation(
                        RelationType::Naat,
                        Some(index),
                        index + 1,
                        confidence(0.94),
                        &token.text,
                        "اسم معرف يتبعه نعت معرف مباشرة.",
                    ));
                }
                if is_nominal(token)
                    && is_nominal(following)
                    && !is_definite(token)
                    && is_definite(following)
                {
                    out.push(Self::relation(
                        RelationType::Idafa,
                        Some(index),
                        index + 1,
                        confidence(0.91),
                        &token.text,
                        "اسمان متجاوران؛ الأول مضاف والثاني معرفة مرشحة للإضافة إليه.",
                    ));
                }
                if is_verb(token) && is_nominal(following) {
                    let lemma = token
                        .analysis
                        .as_ref()
                        .map(|item| item.lemma.as_str())
                        .unwrap_or("");
                    if contains(INTRANSITIVE_VERBS, lemma) {
                        out.push(Self::relation(
                            RelationType::Subject,
                            Some(index),
                            index + 1,
                            confidence(0.93),
                            &token.text,
                            "فعل لازم يتبعه اسم ظاهر مرشح للفاعلية.",
                        ));
                    }
                }
                if is_nominal(token) && is_verb(following) && is_definite(token) {
                    out.push(Self::relation(
                        RelationType::Subject,
                        Some(index + 1),
                        index,
                        confidence(0.88),
                        &following.text,
                        "اسم معرف متقدم يتبعه فعل مرشح للإسناد إليه.",
                    ));
                }
            }
            if let Some(analysis) = &token.analysis {
                if let Some(prefix) = analysis
                    .prefixes
                    .iter()
                    .find(|part| part.feature == "preposition")
                {
                    if is_nominal(token) {
                        out.push(Self::relation(
                            RelationType::PrepositionObject,
                            None,
                            index,
                            (token.confidence + 0.04).min(0.97),
                            &prefix.surface,
                            "حرف جر متصل بالاسم في الكلمة نفسها.",
                        ));
                    }
                }
            }
        }
        let mut unique: HashMap<(RelationType, Option<usize>, usize), SyntacticRelation> =
            HashMap::new();
        for relation in out {
            let key = (
                relation.relation,
                relation.head_index,
                relation.dependent_index,
            );
            match unique.get(&key) {
                Some(current) if current.confidence >= relation.confidence => {}
                _ => {
                    unique.insert(key, relation);
                }
            }
        }
        let mut values: Vec<_> = unique.into_values().collect();
        // Python sorts None heads as -1, before concrete heads.
        values.sort_by(|a, b| {
            a.dependent_index
                .cmp(&b.dependent_index)
                .then(
                    a.head_index
                        .map(|value| value as isize)
                        .unwrap_or(-1)
                        .cmp(&b.head_index.map(|value| value as isize).unwrap_or(-1)),
                )
                .then(a.relation.as_str().cmp(b.relation.as_str()))
        });
        values
    }

    fn base_irab(token: &SyntaxToken, index: usize) -> IrabCandidate {
        let role = match token.pos() {
            "verb" => "فعل",
            "noun" => "اسم",
            "proper_noun" => "علم",
            "verbal_noun" => "مصدر",
            "adjective" => "صفة",
            "pronoun" => "ضمير",
            "particle" => "حرف",
            "adverb" => "ظرف أو حال مرشح",
            _ => "غير محسوم",
        };
        IrabCandidate {
            token_index: index,
            role: role.into(),
            case_or_mood: "غير ظاهر في النص غير المشكول".into(),
            marker: "علامة مقدرة أو غير محسومة".into(),
            governor_index: None,
            governor: String::new(),
            confidence: (token.confidence * 0.72).max(0.20),
            explanation: "قراءة أولية مبنية على نوع الكلمة الصرفي، قبل تطبيق علاقات الجملة.".into(),
        }
    }

    fn irab(&self, tokens: &[SyntaxToken], relations: &[SyntacticRelation]) -> Vec<IrabCandidate> {
        let mut values: Vec<_> = tokens
            .iter()
            .enumerate()
            .map(|(index, token)| Self::base_irab(token, index))
            .collect();
        let mut update = |index: usize, candidate: IrabCandidate| {
            if candidate.confidence >= values[index].confidence {
                values[index] = candidate;
            }
        };
        for relation in relations {
            let dependent = relation.dependent_index;
            let candidate = |role: &str,
                             case_or_mood: &str,
                             marker: &str,
                             governor_index: Option<usize>,
                             confidence: f64,
                             explanation: &str| IrabCandidate {
                token_index: dependent,
                role: role.into(),
                case_or_mood: case_or_mood.into(),
                marker: marker.into(),
                governor_index,
                governor: relation.governor.clone(),
                confidence,
                explanation: explanation.into(),
            };
            match relation.relation {
                RelationType::PrepositionObject => update(
                    dependent,
                    candidate(
                        "اسم مجرور",
                        "genitive",
                        "الكسرة أو ما ينوب عنها",
                        relation.head_index,
                        relation.confidence,
                        "الاسم مجرور لوقوعه بعد حرف جر ظاهر أو متصل.",
                    ),
                ),
                RelationType::SubjunctiveVerb => update(
                    dependent,
                    candidate(
                        "فعل مضارع منصوب",
                        "subjunctive",
                        "الفتحة أو حذف النون في الأفعال الخمسة",
                        relation.head_index,
                        relation.confidence,
                        "الفعل منصوب بحرف نصب سابق.",
                    ),
                ),
                RelationType::JussiveVerb => update(
                    dependent,
                    candidate(
                        "فعل مضارع مجزوم",
                        "jussive",
                        "السكون أو حذف حرف العلة أو حذف النون",
                        relation.head_index,
                        relation.confidence,
                        "الفعل مجزوم بحرف جزم سابق.",
                    ),
                ),
                RelationType::Subject => update(
                    dependent,
                    candidate(
                        "فاعل أو مسند إليه مرشح",
                        "nominative",
                        "الضمة أو ما ينوب عنها",
                        relation.head_index,
                        relation.confidence,
                        "العلاقة الإسنادية مرجحة من ترتيب الفعل والاسم ونوع الفعل.",
                    ),
                ),
                RelationType::Naat => update(
                    dependent,
                    candidate(
                        "نعت",
                        "يتبع المنعوت",
                        "يتبع المنعوت في علامة الإعراب",
                        relation.head_index,
                        relation.confidence,
                        "النعت يتبع المنعوت في التعريف والجنس والعدد والإعراب.",
                    ),
                ),
                RelationType::Demonstrative => update(
                    dependent,
                    candidate(
                        "مشار إليه؛ بدل أو عطف بيان مرشح",
                        "يتبع موقع اسم الإشارة",
                        "بحسب موقع التركيب",
                        relation.head_index,
                        relation.confidence * 0.94,
                        "الاسم الظاهر يبين مرجع اسم الإشارة السابق.",
                    ),
                ),
                RelationType::Idafa => {
                    if let Some(head) = relation.head_index {
                        update(
                            head,
                            IrabCandidate {
                                token_index: head,
                                role: "مضاف".into(),
                                case_or_mood: "بحسب موقعه في الجملة".into(),
                                marker: "لا يقبل التنوين ولا نون المثنى أو الجمع".into(),
                                governor_index: None,
                                governor: String::new(),
                                confidence: relation.confidence,
                                explanation: "الاسم الأول مرشح للإضافة إلى الاسم المعرفة التالي."
                                    .into(),
                            },
                        );
                    }
                    update(
                        dependent,
                        candidate(
                            "مضاف إليه",
                            "genitive",
                            "الكسرة أو ما ينوب عنها",
                            relation.head_index,
                            relation.confidence,
                            "الاسم الثاني مجرور بالإضافة.",
                        ),
                    );
                }
            }
        }
        values
    }

    pub fn rebuild_sentence(
        &self,
        parse: &SentenceParse,
        tokens: Vec<SyntaxToken>,
    ) -> Result<SentenceParse, String> {
        if tokens.len() != parse.tokens.len() {
            return Err("Rebuilt sentence must preserve the token count".into());
        }
        if parse
            .tokens
            .iter()
            .zip(&tokens)
            .any(|(original, candidate)| {
                original.text != candidate.text
                    || original.start != candidate.start
                    || original.end != candidate.end
            })
        {
            return Err("Rebuilt tokens must preserve source text and offsets".into());
        }
        let relations = self.relations(&tokens);
        let irab = self.irab(&tokens, &relations);
        let mut confidence = if tokens.is_empty() {
            1.0
        } else {
            tokens.iter().map(|item| item.confidence).sum::<f64>() / tokens.len() as f64
        };
        if !relations.is_empty() {
            confidence = (confidence * 0.72
                + relations.iter().map(|item| item.confidence).sum::<f64>()
                    / relations.len() as f64
                    * 0.28)
                .min(0.999);
        }
        Ok(SentenceParse {
            text: parse.text.clone(),
            start: parse.start,
            end: parse.end,
            tokens,
            relations,
            irab,
            confidence,
        })
    }

    pub fn parse_sentence(&self, text: &str, start: usize) -> SentenceParse {
        let sentence = Sentence {
            text: text.into(),
            start,
            end: start + char_len(text),
            terminator: String::new(),
        };
        let words = Self::raw_words(&sentence);
        let surfaces: Vec<_> = words.iter().map(|item| surface(&item.text)).collect();
        let tokens: Vec<_> = words
            .iter()
            .enumerate()
            .map(|(index, item)| {
                self.select_analysis(
                    item,
                    index.checked_sub(1).map(|i| surfaces[i].as_str()),
                    surfaces.get(index + 1).map(String::as_str),
                )
            })
            .collect();
        let relations = self.relations(&tokens);
        let irab = self.irab(&tokens, &relations);
        let mut confidence = if tokens.is_empty() {
            1.0
        } else {
            tokens.iter().map(|item| item.confidence).sum::<f64>() / tokens.len() as f64
        };
        if !relations.is_empty() {
            confidence = (confidence * 0.72
                + relations.iter().map(|item| item.confidence).sum::<f64>()
                    / relations.len() as f64
                    * 0.28)
                .min(0.999);
        }
        SentenceParse {
            text: text.into(),
            start,
            end: start + char_len(text),
            tokens,
            relations,
            irab,
            confidence,
        }
    }

    pub fn parse(&self, text: &str) -> DocumentParse {
        DocumentParse {
            text: text.into(),
            sentences: sentence_spans(text)
                .into_iter()
                .map(|sentence| self.parse_sentence(&sentence.text, sentence.start))
                .collect(),
        }
    }

    fn matching_form(
        &self,
        analysis: &MorphologicalAnalysis,
        mut features: Features,
        definite: Option<bool>,
    ) -> Option<String> {
        if definite == Some(true) {
            features.insert("definiteness".into(), "definite".into());
        }
        let mut records = self.morphology.lexicon().forms_for_lemma(
            &analysis.lemma,
            Some(&analysis.pos),
            &features,
        );
        if definite == Some(false) {
            records.retain(|record| {
                record.features.get("definiteness").map(String::as_str) != Some("definite")
                    && !record
                        .prefixes
                        .iter()
                        .any(|(_, feature)| feature == "definite")
            });
        }
        records.first().map(|record| record.form.clone())
    }

    #[allow(clippy::too_many_arguments)]
    fn syntax_match(
        rule_id: &str,
        message: &str,
        token: &SyntaxToken,
        replacements: Vec<String>,
        explanation: &str,
        confidence: f64,
        priority: i32,
        autofix: bool,
        offset: Option<usize>,
        length: Option<usize>,
    ) -> RuleMatch {
        RuleMatch {
            rule_id: rule_id.into(),
            category: "grammar".into(),
            message: message.into(),
            offset: offset.unwrap_or(token.start),
            length: length.unwrap_or(token.end - token.start),
            replacements: replacements.into_iter().fold(Vec::new(), |mut out, item| {
                if !out.contains(&item) {
                    out.push(item);
                }
                out
            }),
            severity: "error".into(),
            explanation: explanation.into(),
            autofix,
            confidence: confidence.clamp(0.0, 0.999),
            priority,
            tags: vec!["syntax".into(), "morphology-aware".into()],
            references: vec!["Dhad deterministic syntax v1".into()],
            profiles: vec!["default".into()],
        }
    }

    fn check_demonstrative(
        &self,
        parse: &SentenceParse,
        relation: &SyntacticRelation,
    ) -> Option<RuleMatch> {
        let head = relation.head_index?;
        if relation.confidence < self.min_relation_confidence {
            return None;
        }
        let demonstrative = &parse.tokens[head];
        let noun = &parse.tokens[relation.dependent_index];
        let noun_number = number(noun);
        let value = surface(&demonstrative.text);
        let (_, demo_gender, demo_number) = DEMONSTRATIVES
            .iter()
            .find(|item| item.0 == value.as_str())?;
        let (expected_gender, expected_number) = if noun_number == "plural" {
            let lemma = noun.analysis.as_ref().map(|item| item.lemma.as_str())?;
            if !contains(HUMAN_LEMMAS, lemma) {
                return None;
            }
            ("common", "plural")
        } else {
            (gender(noun)?, noun_number)
        };
        if (*demo_gender == "common" || *demo_gender == expected_gender)
            && *demo_number == expected_number
        {
            return None;
        }
        let distance = if matches!(value.as_str(), "ذلك" | "تلك" | "أولئك") {
            "far"
        } else {
            "near"
        };
        let replacement_demo = match (distance, expected_gender, expected_number) {
            ("near", "masculine", "singular") => "هذا",
            ("near", "feminine", "singular") => "هذه",
            ("far", "masculine", "singular") => "ذلك",
            ("far", "feminine", "singular") => "تلك",
            ("near", "masculine", "dual") => "هذان",
            ("near", "feminine", "dual") => "هاتان",
            ("near", "common", "plural") => "هؤلاء",
            ("far", "common", "plural") => "أولئك",
            _ => return None,
        };
        let tail = char_slice(
            &parse.text,
            noun.start - parse.start,
            noun.end - parse.start,
        );
        Some(Self::syntax_match(
            "SYNTAX_DEMONSTRATIVE_AGREEMENT", "اسم الإشارة لا يطابق الاسم المشار إليه في الجنس أو العدد.", demonstrative,
            vec![format!("{replacement_demo} {tail}")],
            "يطابق اسم الإشارة الاسمَ المشار إليه في الجنس والعدد عندما يكون المرجع مفردًا أو مثنى، وتُراعى دلالة العاقل في الجمع.",
            relation.confidence, 91, true, Some(demonstrative.start), Some(noun.end - demonstrative.start),
        ))
    }

    fn expected_adjective_features(noun: &SyntaxToken) -> (Option<&str>, &str) {
        let noun_gender = gender(noun);
        let noun_number = number(noun);
        if noun_number == "plural"
            && noun
                .analysis
                .as_ref()
                .is_some_and(|item| !contains(HUMAN_LEMMAS, &item.lemma))
        {
            (Some("feminine"), "singular")
        } else {
            (noun_gender, noun_number)
        }
    }

    fn check_naat(&self, parse: &SentenceParse, relation: &SyntacticRelation) -> Option<RuleMatch> {
        let head = relation.head_index?;
        if relation.confidence < self.min_relation_confidence {
            return None;
        }
        let noun = &parse.tokens[head];
        let adjective = &parse.tokens[relation.dependent_index];
        let analysis = adjective.analysis.as_ref()?;
        noun.analysis.as_ref()?;
        let (expected_gender, expected_number) = Self::expected_adjective_features(noun);
        let adjective_gender = gender(adjective);
        let adjective_number = number(adjective);
        let mut mismatched = Features::new();
        if let (Some(expected), Some(actual)) = (expected_gender, adjective_gender) {
            if expected != actual {
                mismatched.insert("gender".into(), expected.into());
            }
        }
        if adjective_number != expected_number {
            mismatched.insert("number".into(), expected_number.into());
        }
        if mismatched.is_empty() {
            return None;
        }
        let replacement = self.matching_form(analysis, mismatched, Some(is_definite(adjective)))?;
        Some(Self::syntax_match(
            "SYNTAX_NAAT_AGREEMENT", "النعت لا يطابق المنعوت في الجنس أو العدد.", adjective, vec![replacement],
            "يتبع النعت المنعوت في التعريف والتنكير والجنس والعدد والإعراب. ويعامل جمع غير العاقل معاملة المفردة المؤنثة.",
            relation.confidence * 0.97, 88, false, None, None,
        ))
    }

    fn check_subject(
        &self,
        parse: &SentenceParse,
        relation: &SyntacticRelation,
    ) -> Option<RuleMatch> {
        let head = relation.head_index?;
        if relation.confidence < self.min_relation_confidence {
            return None;
        }
        let verb = &parse.tokens[head];
        let subject = &parse.tokens[relation.dependent_index];
        let verb_analysis = verb.analysis.as_ref()?;
        subject.analysis.as_ref()?;
        let subject_gender = gender(subject)?;
        if number(subject) != "singular" {
            return None;
        }
        let value = surface(&verb.text);
        if verb.start < subject.start
            && subject_gender == "feminine"
            && matches!(aspect(verb), None | Some("perfect"))
            && !value.ends_with('ت')
            && contains(INTRANSITIVE_VERBS, &verb_analysis.lemma)
        {
            let features: Features = BTreeMap::from([
                ("aspect".to_string(), "perfect".to_string()),
                ("person".to_string(), "1_or_2_or_3f".to_string()),
            ]);
            let replacement = self
                .matching_form(verb_analysis, features, Some(false))
                .unwrap_or_else(|| format!("{value}ت"));
            return Some(Self::syntax_match(
                "SYNTAX_VERB_SUBJECT_GENDER", "الفعل لا يطابق الفاعل المؤنث الظاهر.", verb, vec![replacement],
                "إذا تقدم الفعل الماضي على فاعل مؤنث حقيقي ظاهر، لزم تأنيث الفعل في هذا السياق غير الملتبس.",
                relation.confidence * 0.96, 87, false, None, None,
            ));
        }
        if subject.start < verb.start
            && subject_gender == "feminine"
            && aspect(verb) == Some("imperfect")
            && person(verb) == Some("3m")
            && value.starts_with('ي')
        {
            return Some(Self::syntax_match(
                "SYNTAX_SUBJECT_VERB_PREFIX", "الفعل المضارع لا يطابق المسند إليه المؤنث المتقدم.", verb,
                vec![format!("ت{}", char_slice(&value, 1, char_len(&value)))],
                "عند تقدم الفاعل أو المبتدأ المؤنث المفرد، يطابقه الفعل المضارع في علامة التأنيث الظاهرة.",
                relation.confidence * 0.93, 86, false, None, None,
            ));
        }
        None
    }

    fn check_idafa(
        &self,
        parse: &SentenceParse,
        relation: &SyntacticRelation,
    ) -> Option<RuleMatch> {
        let head = relation.head_index?;
        if relation.confidence < self.min_relation_confidence {
            return None;
        }
        let mudaf = &parse.tokens[head];
        if mudaf.text.chars().any(|mark| "ًٌٍ".contains(mark)) {
            let replacement: String = mudaf
                .text
                .chars()
                .filter(|mark| !"ًٌٍ".contains(*mark))
                .collect();
            return Some(Self::syntax_match(
                "SYNTAX_IDAFA_TANWEEN",
                "المضاف لا يقبل التنوين.",
                mudaf,
                vec![replacement],
                "يحذف التنوين من الاسم الأول عند دخوله في تركيب الإضافة.",
                relation.confidence * 0.98,
                90,
                true,
                None,
                None,
            ));
        }
        let corrected = idafa_drop_nun(&surface(&mudaf.text))?;
        if !matches!(number(mudaf), "dual" | "plural")
            || !matches!(visible_case(mudaf), Some("nominative" | "oblique"))
        {
            return None;
        }
        Some(Self::syntax_match(
            "SYNTAX_IDAFA_NUN_DROP",
            "تحذف نون المثنى أو جمع المذكر السالم عند الإضافة.",
            mudaf,
            vec![corrected],
            "نون المثنى وجمع المذكر السالم عوض عن التنوين؛ لذلك تحذف عند الإضافة.",
            relation.confidence * 0.96,
            90,
            true,
            None,
            None,
        ))
    }

    fn check_preposition(
        &self,
        parse: &SentenceParse,
        relation: &SyntacticRelation,
    ) -> Option<RuleMatch> {
        if relation.confidence < self.min_relation_confidence {
            return None;
        }
        let noun = &parse.tokens[relation.dependent_index];
        noun.analysis.as_ref()?;
        if !matches!(number(noun), "dual" | "plural") || visible_case(noun) != Some("nominative") {
            return None;
        }
        let replacement = oblique_surface(&surface(&noun.text))?;
        Some(Self::syntax_match(
            "SYNTAX_PREPOSITION_CASE",
            "الاسم بعد حرف الجر يحتاج صيغة الجر الظاهرة.",
            noun,
            vec![replacement],
            "يجر حرف الجر الاسم بعده؛ وتظهر علامة الجر بالياء في المثنى وجمع المذكر السالم.",
            relation.confidence * 0.98,
            92,
            true,
            None,
            None,
        ))
    }

    fn check_governed_verb(
        &self,
        parse: &SentenceParse,
        relation: &SyntacticRelation,
    ) -> Option<RuleMatch> {
        if relation.confidence < self.min_relation_confidence {
            return None;
        }
        let verb = &parse.tokens[relation.dependent_index];
        verb.analysis.as_ref()?;
        if aspect(verb) != Some("imperfect") {
            return None;
        }
        let replacement = governed_five_verb(&surface(&verb.text))?;
        let (rule_id, message, mood) = if relation.relation == RelationType::SubjunctiveVerb {
            (
                "SYNTAX_SUBJUNCTIVE_FIVE_VERBS",
                "الفعل المضارع المنصوب من الأفعال الخمسة يحذف منه حرف النون.",
                "النصب",
            )
        } else {
            (
                "SYNTAX_JUSSIVE_FIVE_VERBS",
                "الفعل المضارع المجزوم من الأفعال الخمسة يحذف منه حرف النون.",
                "الجزم",
            )
        };
        Some(Self::syntax_match(
            rule_id,
            message,
            verb,
            vec![replacement],
            &format!("علامة {mood} في الأفعال الخمسة هي حذف النون."),
            relation.confidence * 0.99,
            93,
            true,
            None,
            None,
        ))
    }

    pub fn check_parse(&self, parse: &SentenceParse) -> Vec<RuleMatch> {
        parse
            .relations
            .iter()
            .filter_map(|relation| match relation.relation {
                RelationType::Demonstrative => self.check_demonstrative(parse, relation),
                RelationType::Naat => self.check_naat(parse, relation),
                RelationType::Subject => self.check_subject(parse, relation),
                RelationType::Idafa => self.check_idafa(parse, relation),
                RelationType::PrepositionObject => self.check_preposition(parse, relation),
                RelationType::SubjunctiveVerb | RelationType::JussiveVerb => {
                    self.check_governed_verb(parse, relation)
                }
            })
            .collect()
    }

    pub fn check_text(&self, text: &str) -> Vec<RuleMatch> {
        self.parse(text)
            .sentences
            .iter()
            .flat_map(|sentence| self.check_parse(sentence))
            .collect()
    }
}
