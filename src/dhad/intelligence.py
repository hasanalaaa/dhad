"""Unified writing-intelligence reporting for Arabic documents.

This module composes Dhad's deterministic style, dialect, morphology, and
syntax layers into a single explainable report.  It does not introduce a
second grammar implementation: every explanation is grounded in an existing
``Match`` or validated dialect conversion, and all metrics are transparent,
local, and deterministic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .dialects import DialectReport
from .match import Match
from .style import StyleReport, ToneLabel
from .syntax import DocumentParse
from .text import NormalizationMode, normalize, tokenize


class WritingTarget(str, Enum):
    """User-selectable target registers exposed as instant suggestion chips."""

    ACADEMIC = "academic"
    FORMAL = "formal"
    CASUAL = "casual"
    PERSUASIVE = "persuasive"


@dataclass(frozen=True, slots=True)
class VocabularyMetrics:
    """Vocabulary richness and sentence-complexity measurements."""

    words: int
    unique_words: int
    unique_lemmas: int
    unique_roots: int
    type_token_ratio: float
    lemma_diversity: float
    root_diversity: float
    hapax_ratio: float
    average_word_length: float
    longest_sentence_words: int
    average_clauses_per_sentence: float
    complexity_score: float
    band: str

    def __post_init__(self) -> None:
        counts = (self.words, self.unique_words, self.unique_lemmas, self.unique_roots)
        if any(value < 0 for value in counts):
            raise ValueError("Vocabulary counts cannot be negative")
        ratios = (
            self.type_token_ratio,
            self.lemma_diversity,
            self.root_diversity,
            self.hapax_ratio,
        )
        if any(not 0.0 <= value <= 1.0 for value in ratios):
            raise ValueError("Vocabulary ratios must be between zero and one")
        if self.average_word_length < 0.0 or self.average_clauses_per_sentence < 0.0:
            raise ValueError("Vocabulary averages cannot be negative")
        if self.longest_sentence_words < 0:
            raise ValueError("Longest sentence length cannot be negative")
        if not 0.0 <= self.complexity_score <= 100.0:
            raise ValueError("Complexity score must be between zero and one hundred")


@dataclass(frozen=True, slots=True)
class SuggestionChip:
    """A compact, non-destructive recommendation for a target register."""

    id: str
    target: WritingTarget
    label: str
    rationale: str
    actions: tuple[str, ...]
    relevance: float

    def __post_init__(self) -> None:
        if not self.id or not self.label or not self.rationale:
            raise ValueError("Suggestion chip text cannot be empty")
        if not self.actions:
            raise ValueError("Suggestion chip must include at least one action")
        if not 0.0 <= self.relevance <= 1.0:
            raise ValueError("Suggestion-chip relevance must be between zero and one")


@dataclass(frozen=True, slots=True)
class LinguisticExplanation:
    """Structured, source-anchored reasoning for one emitted diagnostic."""

    rule_id: str
    category: str
    title: str
    reasoning: str
    why_it_matters: str
    source_text: str
    offset: int
    length: int
    replacements: tuple[str, ...]
    severity: str
    confidence: float
    decision: str
    references: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.offset < 0 or self.length <= 0:
            raise ValueError("Explanation spans must be positive and ordered")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Explanation confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class WritingIntelligenceReport:
    """One coherent snapshot of a document's writing characteristics."""

    text: str
    style: StyleReport
    dialect: DialectReport
    vocabulary: VocabularyMetrics
    suggestion_chips: tuple[SuggestionChip, ...]
    explanations: tuple[LinguisticExplanation, ...]
    matches: tuple[Match, ...]


_WHY_IT_MATTERS = {
    "spelling": "يحافظ الإملاء المعياري على وضوح الكلمة وإمكان البحث عنها وفهمها.",
    "grammar": "يضبط هذا الاقتراح العلاقة النحوية كي يبقى المعنى دقيقًا وغير ملتبس.",
    "punctuation": "يساعد الترقيم الصحيح القارئ على تقسيم المعنى والإيقاع البصري للجملة.",
    "style": "هذه ملاحظة أسلوبية اختيارية تهدف إلى الإيجاز والوضوح واتساق النبرة.",
    "dialect": "يعرض ضاد مقابلاً فصيحًا مع إبقاء التحويل خاضعًا لمراجعة الكاتب.",
    "semantics": "يقلل الاتساق الدلالي احتمال التناقض أو تغير المصطلح داخل المستند.",
    "consistency": "يوحد هذا الاقتراح الاختيارات المتكررة في المستند من دون تغيير المقصود.",
    "neural_suggestion": "اقتراح سياقي احتمالي؛ يظل القرار النهائي للكاتب ولا يطبق تلقائيًا.",
    "diacritics": "يساعد التشكيل المقترح على إزالة اللبس في القراءة مع الحفاظ على النص الأصلي.",
}

_CHIP_CONTENT = {
    WritingTarget.ACADEMIC: (
        "صياغة أكاديمية",
        "زد موضوعية النص واربط الادعاءات بالأدلة والنتائج.",
        (
            "استبدل الرأي الشخصي بوصف قابل للتحقق.",
            "استخدم روابط الاستدلال مثل «تشير النتائج» و«بناءً على البيانات».",
            "قسّم الجمل الكثيفة وعرّف المصطلح عند أول ظهور.",
        ),
    ),
    WritingTarget.FORMAL: (
        "صياغة رسمية",
        "وحّد السجل المهني وقلّل التعابير المحادثية المباشرة.",
        (
            "استخدم أفعالًا مباشرة وصيغ طلب مهذبة.",
            "استبدل الألفاظ العامية بمقابلات فصيحة.",
            "تجنب النداءات الشخصية والاختصارات غير المعرّفة.",
        ),
    ),
    WritingTarget.CASUAL: (
        "صياغة ودّية",
        "خفف كثافة النص مع الحفاظ على سلامته اللغوية.",
        (
            "قصّر الجمل واستخدم مفردات مألوفة.",
            "خاطب القارئ مباشرة عند ملاءمة السياق.",
            "أبقِ المصطلحات الضرورية واشرحها بكلمات بسيطة.",
        ),
    ),
    WritingTarget.PERSUASIVE: (
        "صياغة إقناعية",
        "حوّل الفكرة إلى حجة واضحة تنتهي بخطوة عملية.",
        (
            "ابدأ بالمشكلة ثم اربطها بالنتيجة المتوقعة.",
            "ادعم الدعوة بسبب أو دليل محدد.",
            "اختم بطلب أو إجراء واضح قابل للتنفيذ.",
        ),
    ),
}


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def vocabulary_metrics(text: str, parsed: DocumentParse, style: StyleReport) -> VocabularyMetrics:
    """Calculate transparent richness and complexity indicators in one pass."""

    words = [token for token in tokenize(text) if token.is_arabic]
    surfaces = [
        normalize(token.text, NormalizationMode.LOOKUP)
        for token in words
        if normalize(token.text, NormalizationMode.LOOKUP)
    ]
    counts = Counter(surfaces)

    analyses = [
        token.analysis
        for sentence in parsed.sentences
        for token in sentence.tokens
        if token.analysis is not None
    ]
    lemmas = {
        normalize(item.lemma, NormalizationMode.LOOKUP)
        for item in analyses
        if item.lemma
    }
    roots = {item.root for item in analyses if item.root}

    sentence_lengths = [
        sum(1 for token in sentence.tokens if token.text.strip())
        for sentence in parsed.sentences
    ]
    clause_counts = [
        1 + sum(sentence.text.count(mark) for mark in ("،", "؛", ":"))
        for sentence in parsed.sentences
        if sentence.text.strip()
    ]

    word_count = len(surfaces)
    unique_words = len(counts)
    unique_lemmas = len(lemmas)
    unique_roots = len(roots)
    average_length = sum(len(value) for value in surfaces) / word_count if word_count else 0.0
    average_clauses = sum(clause_counts) / len(clause_counts) if clause_counts else 0.0
    longest_sentence = max(sentence_lengths, default=0)

    readability = style.readability
    complexity = min(
        100.0,
        max(
            0.0,
            (100.0 - readability.clarity_score) * 0.62
            + max(0.0, readability.average_words_per_sentence - 12.0) * 1.25
            + max(0.0, average_clauses - 1.0) * 7.0
            + readability.nominalization_ratio * 18.0,
        ),
    )
    if complexity < 22:
        band = "accessible"
    elif complexity < 45:
        band = "balanced"
    elif complexity < 68:
        band = "complex"
    else:
        band = "very_complex"

    return VocabularyMetrics(
        words=word_count,
        unique_words=unique_words,
        unique_lemmas=unique_lemmas,
        unique_roots=unique_roots,
        type_token_ratio=_safe_ratio(unique_words, word_count),
        lemma_diversity=_safe_ratio(unique_lemmas, word_count),
        root_diversity=_safe_ratio(unique_roots, word_count),
        hapax_ratio=_safe_ratio(sum(value == 1 for value in counts.values()), unique_words),
        average_word_length=average_length,
        longest_sentence_words=longest_sentence,
        average_clauses_per_sentence=average_clauses,
        complexity_score=complexity,
        band=band,
    )


def suggestion_chips(style: StyleReport, dialect: DialectReport) -> tuple[SuggestionChip, ...]:
    """Rank compact target-register recommendations for the current document."""

    tone = style.tone.primary
    dialect_signal = dialect.identification.confidence if dialect.conversions else 0.0
    relevance = {
        WritingTarget.ACADEMIC: 0.92 if tone in {ToneLabel.CONVERSATIONAL, ToneLabel.NEUTRAL} else 0.70,
        WritingTarget.FORMAL: max(0.68, min(0.98, 0.72 + dialect_signal * 0.24)),
        WritingTarget.CASUAL: 0.82 if tone in {ToneLabel.FORMAL, ToneLabel.OBJECTIVE} else 0.64,
        WritingTarget.PERSUASIVE: 0.86 if tone != ToneLabel.PERSUASIVE else 0.55,
    }
    chips: list[SuggestionChip] = []
    for target, score in relevance.items():
        label, rationale, actions = _CHIP_CONTENT[target]
        chips.append(
            SuggestionChip(
                id=f"tone:{target.value}",
                target=target,
                label=label,
                rationale=rationale,
                actions=actions,
                relevance=score,
            )
        )
    return tuple(sorted(chips, key=lambda item: (-item.relevance, item.target.value)))


def linguistic_explanations(
    text: str, matches: Sequence[Match]
) -> tuple[LinguisticExplanation, ...]:
    """Convert diagnostics into consistent, accessible explanation objects."""

    out: list[LinguisticExplanation] = []
    for match in matches:
        source = text[match.offset : match.end]
        reasoning = match.explanation.strip() or match.message.strip()
        out.append(
            LinguisticExplanation(
                rule_id=match.rule_id,
                category=match.category,
                title=match.message,
                reasoning=reasoning,
                why_it_matters=_WHY_IT_MATTERS.get(
                    match.category,
                    "يوضح هذا التنبيه سبب الاقتراح حتى يبقى القرار النهائي بيد الكاتب.",
                ),
                source_text=source,
                offset=match.offset,
                length=match.length,
                replacements=tuple(match.replacements),
                severity=match.severity,
                confidence=match.confidence,
                decision="safe_autofix" if match.autofix else "review_required",
                references=tuple(match.references),
            )
        )
    return tuple(out)


def build_writing_intelligence_report(
    *,
    text: str,
    parsed: DocumentParse,
    style: StyleReport,
    dialect: DialectReport,
    matches: Sequence[Match],
) -> WritingIntelligenceReport:
    """Build a fully explainable report from already-computed engine outputs."""

    frozen_matches = tuple(matches)
    return WritingIntelligenceReport(
        text=text,
        style=style,
        dialect=dialect,
        vocabulary=vocabulary_metrics(text, parsed, style),
        suggestion_chips=suggestion_chips(style, dialect),
        explanations=linguistic_explanations(text, frozen_matches),
        matches=frozen_matches,
    )
