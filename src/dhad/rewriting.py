"""Deterministic, privacy-preserving Arabic rewriting.

The rewriter is intentionally conservative: it never invents facts, citations,
people, dates, or numbers.  It transforms only wording and structure already
present in the source.  Neural ranking can be layered above these candidates,
but the baseline works fully offline and remains explainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from .dialects import DialectConversion
from .text import sentence_spans


class RewriteMode(str, Enum):
    FORMAL = "formal"
    CONCISE = "concise"
    EXPAND = "expand"
    CREATIVE = "creative"
    ACADEMIC = "academic"


@dataclass(frozen=True, slots=True)
class RewriteChange:
    kind: str
    source: str
    replacement: str
    offset: int
    length: int
    explanation: str


@dataclass(frozen=True, slots=True)
class RewriteCandidate:
    id: str
    mode: RewriteMode
    text: str
    label: str
    explanation: str
    changes: tuple[RewriteChange, ...]
    confidence: float
    meaning_preservation: float
    brevity_delta: float

    def __post_init__(self) -> None:
        if not self.id or not self.label or not self.explanation:
            raise ValueError("Rewrite candidate metadata cannot be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Rewrite confidence must be between zero and one")
        if not 0.0 <= self.meaning_preservation <= 1.0:
            raise ValueError("Meaning-preservation score must be between zero and one")
        if not -1.0 <= self.brevity_delta <= 1.0:
            raise ValueError("Brevity delta must be between minus one and one")


@dataclass(frozen=True, slots=True)
class RewriteReport:
    source_text: str
    mode: RewriteMode
    candidates: tuple[RewriteCandidate, ...]
    offline: bool = True
    safety_notice: str = (
        "أُنشئت البدائل محليًا من النص الأصلي فقط؛ راجع الأسماء والأرقام والمصطلحات قبل الاعتماد."
    )


_FORMAL_REPLACEMENTS: tuple[tuple[str, str, str], ...] = (
    ("بس", "لكن", "استبدال رابط محادثي برابط فصيح."),
    ("عشان", "لكي", "استبدال تعليل محادثي بصياغة فصيحة."),
    ("ليش", "لماذا", "استبدال أداة استفهام عامية بأداة فصيحة."),
    ("شلون", "كيف", "استبدال أداة استفهام عامية بأداة فصيحة."),
    ("هسه", "الآن", "استبدال ظرف عامي بظرف فصيح."),
    ("كتير", "كثيرًا", "استبدال لفظ محادثي بمقابله الفصيح."),
    ("جداً جداً", "جدًا", "إزالة التكرار غير الضروري."),
    ("ماكو", "لا يوجد", "استبدال تركيب عامي بتركيب فصيح."),
    ("أريد", "أرغب في", "رفع درجة الرسمية من دون تغيير المقصود."),
)

_ACADEMIC_REPLACEMENTS: tuple[tuple[str, str, str], ...] = (
    ("أنا أعتقد أن", "يمكن القول إن", "تقليل الحضور الشخصي في الصياغة الأكاديمية."),
    ("أعتقد أن", "تشير المعطيات إلى أن", "تحويل الرأي المباشر إلى صياغة تحليلية قابلة للمراجعة."),
    ("من الواضح أن", "تشير النتائج إلى أن", "تجنب القطع غير المدعوم وصياغة الاستنتاج بحذر."),
    ("أكيد", "على الأرجح", "استبدال الجزم بتقدير احتمالي أكثر دقة."),
    ("شيء", "عنصر", "استخدام مفردة أكثر تحديدًا في السجل الأكاديمي."),
    ("أشياء", "عناصر", "استخدام جمع أكثر تحديدًا في السجل الأكاديمي."),
)

_CONCISE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"\bفي واقع الأمر\b[،,]?\s*", "", "حذف عبارة تمهيدية لا تضيف معنى."),
    (r"\bفي الحقيقة\b[،,]?\s*", "", "حذف عبارة تمهيدية لا تضيف معنى."),
    (r"\bمن الجدير بالذكر أن\s*", "", "الوصول مباشرة إلى الفكرة."),
    (r"\bلا بد من الإشارة إلى أن\s*", "", "الوصول مباشرة إلى الفكرة."),
    (r"\bفي الوقت الحالي\b", "حاليًا", "اختصار تركيب زمني طويل."),
    (r"\bبسبب حقيقة أن\b", "لأن", "اختصار تركيب سببي طويل."),
    (r"\bمن أجل أن\b", "لكي", "اختصار تركيب غائي طويل."),
    (r"\bقام بعملية\s+", "", "حذف فعل مساعد اسمي زائد."),
)

_CREATIVE_REPLACEMENTS: tuple[tuple[str, str, str], ...] = (
    ("بالإضافة إلى ذلك", "وفوق ذلك", "تنويع الرابط مع الحفاظ على العلاقة الإضافية."),
    ("ولكن", "ومع ذلك", "تنويع رابط الاستدراك."),
    ("لذلك", "ومن هنا", "تنويع رابط النتيجة."),
    ("في النهاية", "وفي المحصلة", "تنويع خاتمة الفكرة."),
    ("مهم", "محوري", "اختيار مفردة أكثر حيوية مع بقاء الدلالة العامة."),
)


def _word_boundary_pattern(source: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w\u0600-\u06FF]){re.escape(source)}(?![\w\u0600-\u06FF])")


def _replace_literal(
    text: str,
    entries: Sequence[tuple[str, str, str]],
    *,
    limit: int | None = None,
) -> tuple[str, list[RewriteChange]]:
    changes: list[RewriteChange] = []
    current = text
    used = 0
    for source, replacement, explanation in entries:
        pattern = _word_boundary_pattern(source)
        while limit is None or used < limit:
            match = pattern.search(current)
            if match is None:
                break
            changes.append(
                RewriteChange(
                    kind="lexical",
                    source=match.group(0),
                    replacement=replacement,
                    offset=match.start(),
                    length=match.end() - match.start(),
                    explanation=explanation,
                )
            )
            current = current[: match.start()] + replacement + current[match.end() :]
            used += 1
        if limit is not None and used >= limit:
            break
    return current, changes


def _replace_patterns(
    text: str,
    entries: Sequence[tuple[str, str, str]],
    *,
    limit: int | None = None,
) -> tuple[str, list[RewriteChange]]:
    changes: list[RewriteChange] = []
    current = text
    used = 0
    for raw_pattern, replacement, explanation in entries:
        pattern = re.compile(raw_pattern)
        while limit is None or used < limit:
            match = pattern.search(current)
            if match is None:
                break
            source = match.group(0)
            changes.append(
                RewriteChange(
                    kind="structural",
                    source=source,
                    replacement=replacement,
                    offset=match.start(),
                    length=len(source),
                    explanation=explanation,
                )
            )
            current = current[: match.start()] + replacement + current[match.end() :]
            used += 1
        if limit is not None and used >= limit:
            break
    return current, changes


def _apply_dialect_conversions(
    text: str, conversions: Iterable[DialectConversion]
) -> tuple[str, list[RewriteChange]]:
    current = text
    changes: list[RewriteChange] = []
    ordered = sorted(conversions, key=lambda item: item.offset, reverse=True)
    for conversion in ordered:
        if conversion.offset < 0 or conversion.offset + conversion.length > len(current):
            continue
        source = current[conversion.offset : conversion.offset + conversion.length]
        if source != conversion.source:
            continue
        current = (
            current[: conversion.offset]
            + conversion.replacement
            + current[conversion.offset + conversion.length :]
        )
        changes.append(
            RewriteChange(
                kind="dialect",
                source=source,
                replacement=conversion.replacement,
                offset=conversion.offset,
                length=conversion.length,
                explanation=conversion.explanation,
            )
        )
    changes.reverse()
    return current, changes


def _remove_duplicate_words(text: str) -> tuple[str, list[RewriteChange]]:
    pattern = re.compile(r"(?<![\w\u0600-\u06FF])([\u0600-\u06FF]{2,})\s+\1(?![\w\u0600-\u06FF])")
    current = text
    changes: list[RewriteChange] = []
    while (match := pattern.search(current)) is not None:
        source = match.group(0)
        replacement = match.group(1)
        changes.append(
            RewriteChange(
                kind="structural",
                source=source,
                replacement=replacement,
                offset=match.start(),
                length=len(source),
                explanation="حذف تكرار متجاور لا يضيف معنى.",
            )
        )
        current = current[: match.start()] + replacement + current[match.end() :]
    return current, changes


def _expand_structure(text: str, intensity: int) -> tuple[str, list[RewriteChange]]:
    spans = [span for span in sentence_spans(text) if span.text.strip()]
    if len(spans) < 2:
        prefix = "بعبارة أوضح، " if intensity > 1 and text.strip() else ""
        if not prefix:
            return text, []
        return prefix + text.lstrip(), [
            RewriteChange(
                kind="discourse",
                source="",
                replacement=prefix,
                offset=0,
                length=0,
                explanation="إضافة تمهيد يوضح أن الصياغة التالية تفصيل للفكرة نفسها.",
            )
        ]

    connectors = ("إضافة إلى ذلك، ", "وفي هذا السياق، ", "وبناءً على ذلك، ")
    pieces: list[str] = []
    changes: list[RewriteChange] = []
    cursor = 0
    for index, span in enumerate(spans):
        pieces.append(text[cursor : span.start])
        sentence = span.text
        if index and index <= intensity + 1 and not re.match(
            r"\s*(?:و|ف|ثم|لكن|لذلك|إضافة|في هذا|بناء)", sentence
        ):
            connector = connectors[(index - 1) % len(connectors)]
            pieces.append(connector)
            changes.append(
                RewriteChange(
                    kind="discourse",
                    source="",
                    replacement=connector,
                    offset=span.start,
                    length=0,
                    explanation="إظهار العلاقة الخطابية بين الجمل من دون إضافة ادعاء جديد.",
                )
            )
        pieces.append(sentence)
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces), changes


def _normalize_spacing(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([،؛:,.!?؟])", r"\1", text)
    text = re.sub(r"([،؛:])(?=[^\s\n])", r"\1 ", text)
    return text.strip()


def _brevity_delta(source: str, output: str) -> float:
    if not source:
        return 0.0
    return max(-1.0, min(1.0, (len(source) - len(output)) / len(source)))


def _candidate(
    *,
    source: str,
    mode: RewriteMode,
    text: str,
    changes: Sequence[RewriteChange],
    variant: int,
) -> RewriteCandidate:
    normalized = _normalize_spacing(text)
    changed_ratio = 0.0 if not source else min(1.0, abs(len(source) - len(normalized)) / len(source))
    meaning = max(0.72, 0.99 - changed_ratio * 0.34 - len(changes) * 0.006)
    confidence = max(0.62, min(0.97, 0.90 - changed_ratio * 0.15 + min(len(changes), 8) * 0.005))
    labels = {
        RewriteMode.FORMAL: ("رسمي محافظ", "رسمي متوازن", "رسمي مصقول"),
        RewriteMode.CONCISE: ("إيجاز آمن", "إيجاز متوازن", "إيجاز مكثف"),
        RewriteMode.EXPAND: ("توسيع خفيف", "توسيع مترابط", "توسيع منظم"),
        RewriteMode.CREATIVE: ("تنويع خفيف", "تنويع متوازن", "تنويع تعبيري"),
        RewriteMode.ACADEMIC: ("أكاديمي محافظ", "أكاديمي متوازن", "أكاديمي محكم"),
    }
    explanations = {
        RewriteMode.FORMAL: "رفع مستوى الرسمية واستبدال الألفاظ المحادثية من دون تغيير الحقائق.",
        RewriteMode.CONCISE: "حذف الحشو والتكرار مع إبقاء المعلومات والأرقام والأسماء كما وردت.",
        RewriteMode.EXPAND: "إظهار العلاقات بين الأفكار وتوسيع البنية من دون اختلاق معلومات جديدة.",
        RewriteMode.CREATIVE: "تنويع الروابط والمفردات مع الحفاظ على المعنى العام للنص.",
        RewriteMode.ACADEMIC: "تقليل الذاتية ورفع دقة السجل الأكاديمي من دون إضافة مصادر أو نتائج.",
    }
    return RewriteCandidate(
        id=f"{mode.value}:{variant}",
        mode=mode,
        text=normalized,
        label=labels[mode][variant - 1],
        explanation=explanations[mode],
        changes=tuple(changes),
        confidence=confidence,
        meaning_preservation=meaning,
        brevity_delta=_brevity_delta(source, normalized),
    )


def rewrite_text(
    text: str,
    mode: RewriteMode | str,
    *,
    dialect_conversions: Iterable[DialectConversion] = (),
    alternatives: int = 3,
) -> RewriteReport:
    """Create bounded, deterministic rewrite alternatives for one source text."""

    selected_mode = RewriteMode(mode)
    if alternatives < 1 or alternatives > 3:
        raise ValueError("alternatives must be between one and three")
    source = text.strip()
    if not source:
        return RewriteReport(source_text=text, mode=selected_mode, candidates=())

    candidates: list[RewriteCandidate] = []
    seen: set[str] = set()
    for variant in range(1, alternatives + 1):
        current = source
        changes: list[RewriteChange] = []
        limit = variant * 3

        if selected_mode in {RewriteMode.FORMAL, RewriteMode.ACADEMIC}:
            current, dialect_changes = _apply_dialect_conversions(current, dialect_conversions)
            changes.extend(dialect_changes[:limit])
            current, formal_changes = _replace_literal(current, _FORMAL_REPLACEMENTS, limit=limit)
            changes.extend(formal_changes)

        if selected_mode is RewriteMode.CONCISE:
            current, concise_changes = _replace_patterns(current, _CONCISE_PATTERNS, limit=limit)
            changes.extend(concise_changes)
            current, duplicate_changes = _remove_duplicate_words(current)
            changes.extend(duplicate_changes[:limit])

        elif selected_mode is RewriteMode.EXPAND:
            current, expansion_changes = _expand_structure(current, variant)
            changes.extend(expansion_changes)

        elif selected_mode is RewriteMode.CREATIVE:
            current, creative_changes = _replace_literal(current, _CREATIVE_REPLACEMENTS, limit=limit)
            changes.extend(creative_changes)
            if variant > 1:
                current, expansion_changes = _expand_structure(current, variant - 1)
                changes.extend(expansion_changes)

        elif selected_mode is RewriteMode.ACADEMIC:
            current, academic_changes = _replace_literal(current, _ACADEMIC_REPLACEMENTS, limit=limit)
            changes.extend(academic_changes)
            current, concise_changes = _replace_patterns(current, _CONCISE_PATTERNS, limit=variant)
            changes.extend(concise_changes)

        normalized = _normalize_spacing(current)
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(
            _candidate(
                source=source,
                mode=selected_mode,
                text=normalized,
                changes=changes,
                variant=variant,
            )
        )

    if not candidates:
        candidates.append(
            _candidate(
                source=source,
                mode=selected_mode,
                text=source,
                changes=(),
                variant=1,
            )
        )
    return RewriteReport(source_text=text, mode=selected_mode, candidates=tuple(candidates))
