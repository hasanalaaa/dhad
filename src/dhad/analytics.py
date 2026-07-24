"""Advanced, explainable writing analytics for Arabic documents."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .intelligence import VocabularyMetrics
from .style import StyleReport
from .syntax import DocumentParse


@dataclass(frozen=True, slots=True)
class SentenceInsight:
    index: int
    text: str
    start: int
    end: int
    words: int
    clarity_score: float
    complexity_score: float
    tone: str
    tone_confidence: float
    heat: str


@dataclass(frozen=True, slots=True)
class ToneBalance:
    scores: tuple[tuple[str, float], ...]
    dominant: str
    balance_score: float


@dataclass(frozen=True, slots=True)
class WritingAnalytics:
    words: int
    characters: int
    sentences: int
    paragraphs: int
    estimated_reading_seconds: int
    estimated_speaking_seconds: int
    engagement_score: float
    clarity_score: float
    complexity_score: float
    vocabulary_richness: float
    tone_balance: ToneBalance
    sentence_heatmap: tuple[SentenceInsight, ...]


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return min(upper, max(lower, value))


def _heat(complexity: float) -> str:
    if complexity < 28.0:
        return "cool"
    if complexity < 52.0:
        return "balanced"
    if complexity < 72.0:
        return "warm"
    return "hot"


def build_analytics(
    *,
    text: str,
    parsed: DocumentParse,
    style: StyleReport,
    vocabulary: VocabularyMetrics,
) -> WritingAnalytics:
    sentence_insights: list[SentenceInsight] = []
    for index, sentence in enumerate(parsed.sentences):
        leading = len(sentence.text) - len(sentence.text.lstrip())
        trailing = len(sentence.text) - len(sentence.text.rstrip())
        display_text = sentence.text.strip()
        display_start = sentence.start + leading
        display_end = sentence.end - trailing
        words = sum(1 for token in sentence.tokens if token.text.strip())
        punctuation_load = sum(sentence.text.count(mark) for mark in ("،", "؛", ":", "("))
        long_word_count = sum(1 for token in sentence.tokens if len(token.text) >= 8)
        complexity = _clamp(
            max(0, words - 12) * 2.8 + punctuation_load * 7.0 + long_word_count * 1.8
        )
        clarity = _clamp(100.0 - complexity * 0.72)
        tone = (
            style.sentence_tones[index]
            if index < len(style.sentence_tones)
            else style.tone
        )
        sentence_insights.append(
            SentenceInsight(
                index=index,
                text=display_text,
                start=display_start,
                end=display_end,
                words=words,
                clarity_score=clarity,
                complexity_score=complexity,
                tone=tone.primary.value,
                tone_confidence=tone.confidence,
                heat=_heat(complexity),
            )
        )

    score_pairs = tuple((label.value, score) for label, score in style.tone.scores)
    probabilities = [score for _, score in score_pairs if score > 0]
    if len(probabilities) <= 1:
        entropy = 0.0
    else:
        entropy = -sum(value * math.log(value, 2) for value in probabilities)
        entropy /= math.log(len(probabilities), 2)
    balance = ToneBalance(
        scores=score_pairs,
        dominant=style.tone.primary.value,
        balance_score=_clamp(entropy * 100.0),
    )

    words = vocabulary.words
    paragraphs = len([part for part in text.split("\n\n") if part.strip()]) if text.strip() else 0
    questions = text.count("؟") + text.count("?")
    direct_markers = sum(text.count(marker) for marker in ("لذلك", "لأن", "مثال", "النتيجة"))
    sentence_variety = 0.0
    lengths = [item.words for item in sentence_insights]
    if len(lengths) > 1 and sum(lengths):
        mean = sum(lengths) / len(lengths)
        sentence_variety = min(1.0, sum(abs(item - mean) for item in lengths) / (len(lengths) * max(mean, 1)))
    engagement = _clamp(
        style.readability.clarity_score * 0.52
        + min(15.0, questions * 3.0)
        + min(12.0, direct_markers * 2.0)
        + sentence_variety * 14.0
        + min(7.0, vocabulary.type_token_ratio * 10.0)
    )

    return WritingAnalytics(
        words=words,
        characters=len(text),
        sentences=len(parsed.sentences),
        paragraphs=paragraphs,
        estimated_reading_seconds=math.ceil(words / 180 * 60) if words else 0,
        estimated_speaking_seconds=math.ceil(words / 130 * 60) if words else 0,
        engagement_score=engagement,
        clarity_score=style.readability.clarity_score,
        complexity_score=vocabulary.complexity_score,
        vocabulary_richness=vocabulary.type_token_ratio * 100.0,
        tone_balance=balance,
        sentence_heatmap=tuple(sentence_insights),
    )
