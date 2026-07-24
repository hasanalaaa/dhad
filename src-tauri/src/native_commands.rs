use std::{
    collections::HashSet,
    sync::{LazyLock, OnceLock},
    time::Instant,
};

use dhad_core::{
    normalize, sentence_spans, tokenize, DocumentParse, NormalizationMode, SyntaxEngine,
};
use dhad_core::rules::{RuleMatch, RuleSet};
use regex::Regex;
use serde::{Deserialize, Serialize};

const RULES_JSON: &str = include_str!("../../web_demo/rules.json");
const SAFETY_NOTICE: &str =
    "أُنشئت البدائل محليًا من النص الأصلي فقط؛ راجع الأسماء والأرقام والمصطلحات قبل الاعتماد.";

static RULES: OnceLock<Result<RuleSet, String>> = OnceLock::new();
static MULTISPACE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[ \t]{2,}").expect("valid spacing regex"));
static SPACE_BEFORE_PUNCTUATION: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\s+([،؛:,.!?؟])").expect("valid punctuation spacing regex")
});
static SPACE_AFTER_PUNCTUATION: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"([،؛:])([^\s\n])").expect("valid punctuation spacing regex")
});

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AnalyzeTextRequest {
    text: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeAnalysisResponse {
    resolved: Vec<RuleMatch>,
    parsed: Option<DocumentParse>,
    elapsed_ms: f64,
    backend: &'static str,
    engine_version: &'static str,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DialectConversion {
    source: String,
    replacement: String,
    offset: usize,
    length: usize,
    #[serde(default)]
    explanation: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ParaphraseRequest {
    text: String,
    #[serde(default = "default_mode")]
    mode: String,
    #[serde(default = "default_alternatives")]
    alternatives: usize,
    #[serde(default)]
    dialect_conversions: Vec<DialectConversion>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RewriteChange {
    kind: &'static str,
    source: String,
    replacement: String,
    offset: usize,
    length: usize,
    explanation: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RewriteCandidate {
    id: String,
    mode: String,
    text: String,
    label: &'static str,
    explanation: &'static str,
    changes: Vec<RewriteChange>,
    confidence: f64,
    meaning_preservation: f64,
    brevity_delta: f64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeParaphraseResponse {
    source_text: String,
    mode: String,
    candidates: Vec<RewriteCandidate>,
    offline: bool,
    backend: &'static str,
    safety_notice: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SystemInfo {
    app_name: &'static str,
    app_version: &'static str,
    identifier: &'static str,
    engine_version: &'static str,
    os: &'static str,
    family: &'static str,
    architecture: &'static str,
    cpu_count: usize,
    hostname: Option<String>,
    native_ipc: bool,
}

fn default_mode() -> String {
    "formal".to_string()
}

fn default_alternatives() -> usize {
    3
}

fn rule_set() -> Result<&'static RuleSet, String> {
    RULES
        .get_or_init(|| RuleSet::from_json(RULES_JSON))
        .as_ref()
        .map_err(Clone::clone)
}

fn resolve_diagnostics(candidates: Vec<RuleMatch>) -> Vec<RuleMatch> {
    let mut unique = std::collections::HashMap::new();
    for item in candidates {
        unique.insert(
            (item.rule_id.clone(), item.offset, item.length),
            item,
        );
    }
    let mut ordered: Vec<_> = unique.into_values().collect();
    ordered.sort_by(|a, b| {
        b.priority
            .cmp(&a.priority)
            .then_with(|| b.length.cmp(&a.length))
            .then_with(|| a.offset.cmp(&b.offset))
    });

    let mut accepted: Vec<RuleMatch> = Vec::new();
    for item in ordered {
        let end = item.offset + item.length;
        let overlaps = accepted.iter().any(|other| {
            item.offset < other.offset + other.length && other.offset < end
        });
        if !overlaps {
            accepted.push(item);
        }
    }
    accepted.sort_by(|a, b| {
        a.offset
            .cmp(&b.offset)
            .then_with(|| b.length.cmp(&a.length))
    });
    accepted
}

fn analyze_text_native_blocking(
    request: AnalyzeTextRequest,
) -> Result<NativeAnalysisResponse, String> {
    if request.text.len() > 8 * 1024 * 1024 {
        return Err("text exceeds the native analysis safety limit".to_string());
    }

    let started = Instant::now();
    let mut matches = rule_set()?.check(&request.text);
    let syntax = SyntaxEngine::default();
    matches.extend(syntax.check_text(&request.text));
    let parsed = (!request.text.trim().is_empty()).then(|| syntax.parse(&request.text));

    Ok(NativeAnalysisResponse {
        resolved: resolve_diagnostics(matches),
        parsed,
        elapsed_ms: started.elapsed().as_secs_f64() * 1_000.0,
        backend: "tauri-rust-native",
        engine_version: env!("CARGO_PKG_VERSION"),
    })
}

#[tauri::command]
pub async fn analyze_text_native(
    request: AnalyzeTextRequest,
) -> Result<NativeAnalysisResponse, String> {
    tauri::async_runtime::spawn_blocking(move || analyze_text_native_blocking(request))
        .await
        .map_err(|error| format!("native analysis worker failed: {error}"))?
}

fn paraphrase_native_blocking(
    request: ParaphraseRequest,
) -> Result<NativeParaphraseResponse, String> {
    validate_mode(&request.mode)?;
    if !(1..=3).contains(&request.alternatives) {
        return Err("alternatives must be between one and three".to_string());
    }
    if request.text.len() > 2 * 1024 * 1024 {
        return Err("text exceeds the native paraphrase safety limit".to_string());
    }

    let source = request.text.trim().to_string();
    if source.is_empty() {
        return Ok(NativeParaphraseResponse {
            source_text: request.text,
            mode: request.mode,
            candidates: Vec::new(),
            offline: true,
            backend: "tauri-rust-native",
            safety_notice: SAFETY_NOTICE,
        });
    }

    // Exercise the shared core normalization policy before rewriting. The
    // original surface form remains authoritative for every emitted candidate.
    let _normalized_lookup = normalize(&source, NormalizationMode::Lookup);

    let mut candidates = Vec::new();
    let mut seen = HashSet::new();
    for variant in 1..=request.alternatives {
        let mut output = source.clone();
        let mut changes = Vec::new();
        let limit = variant * 3;

        if matches!(request.mode.as_str(), "formal" | "academic") {
            apply_dialect_conversions(
                &mut output,
                &request.dialect_conversions,
                limit,
                &mut changes,
            );
            replace_literals(&mut output, formal_entries(), limit, &mut changes);
        }

        match request.mode.as_str() {
            "concise" => {
                apply_concise_patterns(&mut output, limit, &mut changes);
                remove_duplicate_words(&mut output, limit, &mut changes);
            }
            "expand" => expand_structure(&mut output, variant, &mut changes),
            "creative" => {
                replace_literals(&mut output, creative_entries(), limit, &mut changes);
                if variant > 1 {
                    expand_structure(&mut output, variant - 1, &mut changes);
                }
            }
            "academic" => {
                replace_literals(&mut output, academic_entries(), limit, &mut changes);
                apply_concise_patterns(&mut output, variant, &mut changes);
            }
            "formal" => {}
            _ => unreachable!("validated rewrite mode"),
        }

        let output = normalize_spacing(&output);
        if !seen.insert(output.clone()) {
            continue;
        }
        candidates.push(build_candidate(
            &source,
            &request.mode,
            variant,
            output,
            changes,
        ));
    }

    if candidates.is_empty() {
        candidates.push(build_candidate(
            &source,
            &request.mode,
            1,
            source.clone(),
            Vec::new(),
        ));
    }

    Ok(NativeParaphraseResponse {
        source_text: request.text,
        mode: request.mode,
        candidates,
        offline: true,
        backend: "tauri-rust-native",
        safety_notice: SAFETY_NOTICE,
    })
}

#[tauri::command]
pub async fn paraphrase_native(
    request: ParaphraseRequest,
) -> Result<NativeParaphraseResponse, String> {
    tauri::async_runtime::spawn_blocking(move || paraphrase_native_blocking(request))
        .await
        .map_err(|error| format!("native rewrite worker failed: {error}"))?
}

#[tauri::command]
pub fn get_system_info() -> SystemInfo {
    let hostname = std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .ok()
        .filter(|value| !value.trim().is_empty());

    SystemInfo {
        app_name: "ضاد",
        app_version: env!("CARGO_PKG_VERSION"),
        identifier: "com.dhad.app",
        engine_version: env!("CARGO_PKG_VERSION"),
        os: std::env::consts::OS,
        family: std::env::consts::FAMILY,
        architecture: std::env::consts::ARCH,
        cpu_count: std::thread::available_parallelism()
            .map(|value| value.get())
            .unwrap_or(1),
        hostname,
        native_ipc: true,
    }
}

fn validate_mode(mode: &str) -> Result<(), String> {
    match mode {
        "formal" | "concise" | "expand" | "creative" | "academic" => Ok(()),
        _ => Err(format!("unsupported rewrite mode: {mode}")),
    }
}

fn formal_entries() -> &'static [(&'static str, &'static str, &'static str)] {
    &[
        ("بس", "لكن", "استبدال رابط محادثي برابط فصيح."),
        ("عشان", "لكي", "استبدال تعليل محادثي بصياغة فصيحة."),
        ("ليش", "لماذا", "استبدال أداة استفهام عامية بأداة فصيحة."),
        ("شلون", "كيف", "استبدال أداة استفهام عامية بأداة فصيحة."),
        ("هسه", "الآن", "استبدال ظرف عامي بظرف فصيح."),
        ("ماكو", "لا يوجد", "استبدال تركيب عامي بتركيب فصيح."),
        ("أريد", "أرغب في", "رفع درجة الرسمية من دون تغيير المقصود."),
    ]
}

fn academic_entries() -> &'static [(&'static str, &'static str, &'static str)] {
    &[
        (
            "أنا أعتقد أن",
            "يمكن القول إن",
            "تقليل الحضور الشخصي في الصياغة الأكاديمية.",
        ),
        (
            "أعتقد أن",
            "تشير المعطيات إلى أن",
            "تحويل الرأي المباشر إلى صياغة تحليلية.",
        ),
        (
            "من الواضح أن",
            "تشير النتائج إلى أن",
            "تجنب القطع غير المدعوم.",
        ),
        ("أكيد", "على الأرجح", "استبدال الجزم بتقدير احتمالي أكثر دقة."),
        ("شيء", "عنصر", "استخدام مفردة أكثر تحديدًا."),
        ("أشياء", "عناصر", "استخدام جمع أكثر تحديدًا."),
    ]
}

fn creative_entries() -> &'static [(&'static str, &'static str, &'static str)] {
    &[
        (
            "بالإضافة إلى ذلك",
            "وفوق ذلك",
            "تنويع الرابط الإضافي.",
        ),
        ("ولكن", "ومع ذلك", "تنويع رابط الاستدراك."),
        ("لذلك", "ومن هنا", "تنويع رابط النتيجة."),
        ("في النهاية", "وفي المحصلة", "تنويع خاتمة الفكرة."),
        ("مهم", "محوري", "اختيار مفردة أكثر حيوية."),
    ]
}

fn is_word_character(value: char) -> bool {
    value.is_alphanumeric() || value == '_' || value == 'ـ' || ('\u{064b}'..='\u{065f}').contains(&value)
}

fn bounded_occurrence(text: &str, source: &str, start_at: usize) -> Option<usize> {
    let mut cursor = start_at;
    while let Some(relative) = text.get(cursor..)?.find(source) {
        let index = cursor + relative;
        let before = text[..index].chars().next_back();
        let after_index = index + source.len();
        let after = text.get(after_index..)?.chars().next();
        if before.map_or(true, |character| !is_word_character(character))
            && after.map_or(true, |character| !is_word_character(character))
        {
            return Some(index);
        }
        cursor = index + source.len();
    }
    None
}

fn replace_literals(
    output: &mut String,
    entries: &[(&str, &str, &str)],
    limit: usize,
    changes: &mut Vec<RewriteChange>,
) {
    for (source, replacement, explanation) in entries {
        let mut cursor = 0;
        while changes.len() < limit {
            let Some(byte_index) = bounded_occurrence(output, source, cursor) else {
                break;
            };
            let offset = output[..byte_index].chars().count();
            output.replace_range(byte_index..byte_index + source.len(), replacement);
            changes.push(RewriteChange {
                kind: "lexical",
                source: (*source).to_string(),
                replacement: (*replacement).to_string(),
                offset,
                length: source.chars().count(),
                explanation: (*explanation).to_string(),
            });
            cursor = byte_index + replacement.len();
        }
        if changes.len() >= limit {
            break;
        }
    }
}

fn apply_concise_patterns(
    output: &mut String,
    limit: usize,
    changes: &mut Vec<RewriteChange>,
) {
    let entries = [
        ("في واقع الأمر", "", "حذف عبارة تمهيدية لا تضيف معنى."),
        ("في الحقيقة", "", "حذف عبارة تمهيدية لا تضيف معنى."),
        ("من الجدير بالذكر أن", "", "الوصول مباشرة إلى الفكرة."),
        ("لا بد من الإشارة إلى أن", "", "الوصول مباشرة إلى الفكرة."),
        ("في الوقت الحالي", "حاليًا", "اختصار تركيب زمني طويل."),
        ("بسبب حقيقة أن", "لأن", "اختصار تركيب سببي طويل."),
        ("من أجل أن", "لكي", "اختصار تركيب غائي طويل."),
    ];

    for (source, replacement, explanation) in entries {
        while changes.len() < limit {
            let Some(byte_index) = bounded_occurrence(output, source, 0) else {
                break;
            };
            let mut end = byte_index + source.len();
            if replacement.is_empty() {
                let tail = &output[end..];
                if let Some(first) = tail.chars().next() {
                    if matches!(first, '،' | ',') {
                        end += first.len_utf8();
                    }
                }
                loop {
                    let Some(next) = output[end..].chars().next() else {
                        break;
                    };
                    if !next.is_whitespace() {
                        break;
                    }
                    end += next.len_utf8();
                }
            }
            let original = output[byte_index..end].to_string();
            let offset = output[..byte_index].chars().count();
            let length = original.chars().count();
            output.replace_range(byte_index..end, replacement);
            changes.push(RewriteChange {
                kind: "structural",
                source: original,
                replacement: replacement.to_string(),
                offset,
                length,
                explanation: explanation.to_string(),
            });
        }
        if changes.len() >= limit {
            break;
        }
    }
}

fn remove_duplicate_words(
    output: &mut String,
    limit: usize,
    changes: &mut Vec<RewriteChange>,
) {
    loop {
        if changes.len() >= limit {
            break;
        }
        let words = tokenize(output);
        let mut duplicate = None;
        for pair in words.windows(2) {
            let first = &pair[0];
            let second = &pair[1];
            if first.text.chars().count() < 2 || first.text != second.text {
                continue;
            }
            let between = slice_chars(output, first.end, second.start).unwrap_or_default();
            if !between.is_empty() && between.chars().all(char::is_whitespace) {
                duplicate = Some((first.text.clone(), first.end, second.end));
                break;
            }
        }
        let Some((word, remove_start, remove_end)) = duplicate else {
            break;
        };
        let Some((byte_start, byte_end)) = char_range_to_byte(output, remove_start, remove_end) else {
            break;
        };
        let removed = output[byte_start..byte_end].to_string();
        output.replace_range(byte_start..byte_end, "");
        changes.push(RewriteChange {
            kind: "structural",
            source: removed,
            replacement: word,
            offset: remove_start,
            length: remove_end - remove_start,
            explanation: "حذف تكرار متجاور لا يضيف معنى.".to_string(),
        });
    }
}

fn apply_dialect_conversions(
    output: &mut String,
    conversions: &[DialectConversion],
    limit: usize,
    changes: &mut Vec<RewriteChange>,
) {
    let mut ordered = conversions.to_vec();
    ordered.sort_by(|a, b| b.offset.cmp(&a.offset));
    for item in ordered {
        if changes.len() >= limit {
            break;
        }
        let Some((byte_start, byte_end)) =
            char_range_to_byte(output, item.offset, item.offset + item.length)
        else {
            continue;
        };
        if &output[byte_start..byte_end] != item.source.as_str() {
            continue;
        }
        output.replace_range(byte_start..byte_end, &item.replacement);
        changes.push(RewriteChange {
            kind: "dialect",
            source: item.source,
            replacement: item.replacement,
            offset: item.offset,
            length: item.length,
            explanation: if item.explanation.is_empty() {
                "استبدال لفظ لهجي بمقابله الفصيح.".to_string()
            } else {
                item.explanation
            },
        });
    }
    changes.sort_by_key(|change| change.offset);
}

fn expand_structure(output: &mut String, intensity: usize, changes: &mut Vec<RewriteChange>) {
    let parts: Vec<String> = sentence_spans(output)
        .into_iter()
        .map(|sentence| format!("{}{}", sentence.text.trim(), sentence.terminator))
        .filter(|sentence| !sentence.is_empty())
        .collect();

    if parts.len() < 2 {
        if intensity >= 2 && !output.trim().is_empty() {
            *output = format!("بعبارة أوضح، {}", output.trim());
            changes.push(RewriteChange {
                kind: "discourse",
                source: String::new(),
                replacement: "بعبارة أوضح، ".to_string(),
                offset: 0,
                length: 0,
                explanation: "إضافة تمهيد يوضح أن الصياغة التالية تفصيل للفكرة نفسها."
                    .to_string(),
            });
        }
        return;
    }

    let connectors = ["إضافة إلى ذلك، ", "وفي هذا السياق، ", "وبناءً على ذلك، "];
    let mut rebuilt = Vec::with_capacity(parts.len());
    let mut char_offset = 0;
    for (index, part) in parts.into_iter().enumerate() {
        let starts_with_connector = part.starts_with('و') || part.starts_with('ف')
            || ["ثم", "لكن", "لذلك", "إضافة", "في هذا", "بناء"]
                .iter()
                .any(|prefix| part.starts_with(prefix));
        if index == 0 || index > intensity + 1 || starts_with_connector {
            char_offset += part.chars().count() + usize::from(index > 0);
            rebuilt.push(part);
            continue;
        }
        let connector = connectors[(index - 1) % connectors.len()];
        changes.push(RewriteChange {
            kind: "discourse",
            source: String::new(),
            replacement: connector.to_string(),
            offset: char_offset,
            length: 0,
            explanation: "إظهار العلاقة الخطابية بين الجمل من دون إضافة ادعاء جديد."
                .to_string(),
        });
        let expanded = format!("{connector}{part}");
        char_offset += expanded.chars().count() + 1;
        rebuilt.push(expanded);
    }
    *output = rebuilt.join(" ");
}

fn normalize_spacing(text: &str) -> String {
    let compact = MULTISPACE.replace_all(text, " ");
    let compact = SPACE_BEFORE_PUNCTUATION.replace_all(&compact, "$1");
    SPACE_AFTER_PUNCTUATION
        .replace_all(&compact, "$1 $2")
        .trim()
        .to_string()
}

fn build_candidate(
    source: &str,
    mode: &str,
    variant: usize,
    text: String,
    changes: Vec<RewriteChange>,
) -> RewriteCandidate {
    let source_len = source.chars().count() as f64;
    let text_len = text.chars().count() as f64;
    let changed_ratio = if source_len > 0.0 {
        ((source_len - text_len).abs() / source_len).min(1.0)
    } else {
        0.0
    };
    let confidence = (0.9 - changed_ratio * 0.15 + changes.len().min(8) as f64 * 0.005)
        .clamp(0.62, 0.97);
    let meaning_preservation =
        (0.99 - changed_ratio * 0.34 - changes.len() as f64 * 0.006).max(0.72);
    let brevity_delta = if source_len > 0.0 {
        ((source_len - text_len) / source_len).clamp(-1.0, 1.0)
    } else {
        0.0
    };

    RewriteCandidate {
        id: format!("{mode}:{variant}"),
        mode: mode.to_string(),
        text,
        label: candidate_label(mode, variant),
        explanation: mode_description(mode),
        changes,
        confidence,
        meaning_preservation,
        brevity_delta,
    }
}

fn candidate_label(mode: &str, variant: usize) -> &'static str {
    let labels = match mode {
        "formal" => ["رسمي محافظ", "رسمي متوازن", "رسمي مصقول"],
        "concise" => ["إيجاز آمن", "إيجاز متوازن", "إيجاز مكثف"],
        "expand" => ["توسيع خفيف", "توسيع مترابط", "توسيع منظم"],
        "creative" => ["تنويع خفيف", "تنويع متوازن", "تنويع تعبيري"],
        "academic" => ["أكاديمي محافظ", "أكاديمي متوازن", "أكاديمي محكم"],
        _ => ["بديل", "بديل", "بديل"],
    };
    labels[variant.saturating_sub(1).min(2)]
}

fn mode_description(mode: &str) -> &'static str {
    match mode {
        "formal" => "رفع السجل واستبدال الألفاظ المحادثية.",
        "concise" => "حذف الحشو والتكرار من دون إسقاط المعلومات.",
        "expand" => "إظهار الروابط بين الأفكار من دون اختلاق حقائق.",
        "creative" => "تنويع الروابط والمفردات مع حفظ المعنى.",
        "academic" => "تقليل الذاتية ورفع دقة السجل البحثي.",
        _ => "إعادة صياغة محلية.",
    }
}

fn char_range_to_byte(text: &str, start: usize, end: usize) -> Option<(usize, usize)> {
    if start > end {
        return None;
    }
    let char_count = text.chars().count();
    if end > char_count {
        return None;
    }
    let byte_start = if start == char_count {
        text.len()
    } else {
        text.char_indices().nth(start)?.0
    };
    let byte_end = if end == char_count {
        text.len()
    } else {
        text.char_indices().nth(end)?.0
    };
    Some((byte_start, byte_end))
}

fn slice_chars(text: &str, start: usize, end: usize) -> Option<&str> {
    let (byte_start, byte_end) = char_range_to_byte(text, start, end)?;
    text.get(byte_start..byte_end)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_analysis_returns_core_payload() {
        let result = analyze_text_native_blocking(AnalyzeTextRequest {
            text: "هاذا نص".to_string(),
        })
        .expect("native analysis succeeds");
        assert_eq!(result.backend, "tauri-rust-native");
        assert!(result.elapsed_ms >= 0.0);
    }

    #[test]
    fn native_paraphrase_preserves_non_empty_candidates() {
        let result = paraphrase_native_blocking(ParaphraseRequest {
            text: "هسه أريد أكتب نص مهم".to_string(),
            mode: "formal".to_string(),
            alternatives: 3,
            dialect_conversions: Vec::new(),
        })
        .expect("native paraphrase succeeds");
        assert!(!result.candidates.is_empty());
        assert!(result.candidates[0].text.contains("الآن"));
    }
}
