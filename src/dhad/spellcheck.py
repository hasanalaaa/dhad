"""Morphology-aware lexical spelling validation for Arabic.

The spellchecker is intentionally precision-first.  A token is accepted when it
has a sufficiently confident lexicon-backed morphological analysis.  Unknown
forms are reported only when a close, lexically licensed candidate exists and
wins by a clear score margin.  This policy prevents a small lexicon from
misclassifying arbitrary proper nouns or valid derived forms.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

from .match import Match
from .morphology import MorphologicalAnalyzer, default_analyzer
from .text import NormalizationMode, Token, TokenKind, normalize, tokenize

_CONFUSION_GROUPS: tuple[frozenset[str], ...] = (
    frozenset("اأإآٱ"),
    frozenset("يىئ"),
    frozenset("ه ة".replace(" ", "")),
    frozenset("وؤ"),
    frozenset("ءئؤ"),
)
_CONFUSION_COST: dict[tuple[str, str], float] = {}
for group in _CONFUSION_GROUPS:
    for left in group:
        for right in group:
            if left != right:
                _CONFUSION_COST[(left, right)] = 0.18

# Conservative keyboard/visual confusions.  They are cheaper than an arbitrary
# substitution, but not cheap enough to trigger without lexical evidence.
for left, right in (
    ("ض", "ص"),
    ("ذ", "ز"),
    ("ث", "ت"),
    ("ظ", "ض"),
    ("د", "ذ"),
    ("ق", "ف"),
):
    _CONFUSION_COST[(left, right)] = 0.55
    _CONFUSION_COST[(right, left)] = 0.55

_PREPOSITIONS = frozenset({"في", "من", "إلى", "على", "عن", "ب", "ل", "ك", "مع", "بين", "لدى"})
_VERB_GOVERNORS = frozenset({"سوف", "لن", "لم", "أن", "كي", "قد"})
_DEMONSTRATIVES = frozenset({"هذا", "هذه", "ذلك", "تلك", "هؤلاء"})
_NAME_CUES = frozenset(
    {"الدكتور", "الدكتورة", "الأستاذ", "الأستاذة", "السيد", "السيدة", "المهندس", "المهندسة"}
)


@dataclass(frozen=True, slots=True)
class SpellingCandidate:
    """One ranked replacement candidate with explainable score components."""

    value: str
    distance: float
    score: float
    frequency: int
    morphology_confidence: float
    pos: str
    lemma: str

    def __post_init__(self) -> None:
        if self.distance < 0:
            raise ValueError("Candidate distance cannot be negative")
        if self.frequency < 1:
            raise ValueError("Candidate frequency must be positive")
        if not 0.0 <= self.morphology_confidence <= 1.0:
            raise ValueError("Morphology confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SpellingDecision:
    """Result of validating a token in context."""

    token: str
    valid: bool
    candidates: tuple[SpellingCandidate, ...] = ()
    reason: str = ""


def _substitution_cost(left: str, right: str) -> float:
    if left == right:
        return 0.0
    return _CONFUSION_COST.get((left, right), 1.0)


def _deletion_cost(value: str, index: int) -> float:
    char = value[index]
    if char in "ءأإآؤئ":
        return 0.35
    if (index > 0 and value[index - 1] == char) or (
        index + 1 < len(value) and value[index + 1] == char
    ):
        return 0.55
    return 1.0


def _insertion_cost(value: str, index: int) -> float:
    char = value[index]
    if char in "ءأإآؤئ":
        return 0.35
    if (index > 0 and value[index - 1] == char) or (
        index + 1 < len(value) and value[index + 1] == char
    ):
        return 0.55
    return 1.0


@lru_cache(maxsize=65536)
def arabic_edit_distance(left: str, right: str) -> float:
    """Weighted Damerau-Levenshtein distance for Arabic orthography.

    Hamza seats, alif maqsura/yaa, taa marbuta/haa, and waw/hamza-on-waw
    substitutions receive a low cost.  Adjacent transpositions cost 0.75.
    """

    left = normalize(left, NormalizationMode.LOOKUP)
    right = normalize(right, NormalizationMode.LOOKUP)
    if left == right:
        return 0.0
    if not left:
        return float(len(right))
    if not right:
        return float(len(left))
    rows = len(left) + 1
    cols = len(right) + 1
    matrix = [[0.0] * cols for _ in range(rows)]
    for row in range(rows):
        matrix[row][0] = float(row)
    for col in range(cols):
        matrix[0][col] = float(col)
    for row in range(1, rows):
        for col in range(1, cols):
            deletion = matrix[row - 1][col] + _deletion_cost(left, row - 1)
            insertion = matrix[row][col - 1] + _insertion_cost(right, col - 1)
            substitution = matrix[row - 1][col - 1] + _substitution_cost(
                left[row - 1], right[col - 1]
            )
            best = min(deletion, insertion, substitution)
            if (
                row > 1
                and col > 1
                and left[row - 1] == right[col - 2]
                and left[row - 2] == right[col - 1]
            ):
                best = min(best, matrix[row - 2][col - 2] + 0.75)
            matrix[row][col] = best
    return matrix[-1][-1]


def _confusion_skeleton(value: str) -> str:
    translation = str.maketrans(
        {
            "أ": "ا",
            "إ": "ا",
            "آ": "ا",
            "ٱ": "ا",
            "ى": "ي",
            "ئ": "ي",
            "ة": "ه",
            "ؤ": "و",
            "ء": "ا",
        }
    )
    return normalize(value, NormalizationMode.LOOKUP).translate(translation)


def _deletions(value: str) -> tuple[str, ...]:
    return tuple(value[:index] + value[index + 1 :] for index in range(len(value)))


class SpellChecker:
    """Precision-gated lexical spellchecker backed by morphology."""

    def __init__(
        self,
        analyzer: MorphologicalAnalyzer | None = None,
        *,
        max_distance: float = 1.05,
        min_margin: float = 0.28,
        max_candidates: int = 5,
    ):
        if max_distance <= 0:
            raise ValueError("max_distance must be positive")
        if min_margin < 0:
            raise ValueError("min_margin cannot be negative")
        if max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        self.analyzer = analyzer or default_analyzer()
        self.max_distance = max_distance
        self.min_margin = min_margin
        self.max_candidates = max_candidates
        self._forms = self.analyzer.lexicon.correction_forms
        self._skeleton_index: dict[str, set[str]] = defaultdict(set)
        self._deletion_index: dict[str, set[str]] = defaultdict(set)
        for form in self._forms:
            if len(form) < 2:
                continue
            self._skeleton_index[_confusion_skeleton(form)].add(form)
            for deletion in _deletions(form):
                self._deletion_index[deletion].add(form)
        self._suggest_cached = lru_cache(maxsize=16384)(self._suggest_uncached)

    def _candidate_pool(self, token: str) -> set[str]:
        pool = set(self._skeleton_index.get(_confusion_skeleton(token), ()))
        pool.update(self._deletion_index.get(token, ()))
        for deletion in _deletions(token):
            if deletion in self._forms:
                pool.add(deletion)
            pool.update(self._deletion_index.get(deletion, ()))
        pool.discard(token)
        return pool

    @staticmethod
    def _context_adjustment(pos: str, previous: str | None, following: str | None) -> float:
        adjustment = 0.0
        if previous in _PREPOSITIONS:
            adjustment += (
                -0.22 if pos in {"noun", "adjective", "verbal_noun", "proper_noun"} else 0.18
            )
        if previous in _VERB_GOVERNORS:
            adjustment += -0.20 if pos == "verb" else 0.12
        if previous in _DEMONSTRATIVES:
            adjustment += -0.18 if pos in {"noun", "adjective"} else 0.10
        if following and following.startswith("ال"):
            adjustment += -0.05 if pos in {"noun", "adjective"} else 0.03
        return adjustment

    def _rank_candidate(
        self, value: str, distance: float, previous: str | None, following: str | None
    ) -> SpellingCandidate | None:
        analyses = self.analyzer.analyze(value, min_confidence=0.72)
        lexical = next((item for item in analyses if item.is_lexical), None)
        if lexical is None or lexical.pos == "proper_noun":
            return None
        frequency = max(1, lexical.frequency)
        context = self._context_adjustment(lexical.pos, previous, following)
        score = distance * 2.9 - math.log1p(frequency) * 0.16 - lexical.confidence * 0.72 + context
        return SpellingCandidate(
            value=value,
            distance=distance,
            score=score,
            frequency=frequency,
            morphology_confidence=lexical.confidence,
            pos=lexical.pos,
            lemma=lexical.lemma,
        )

    def _suggest_uncached(
        self, token: str, previous: str | None, following: str | None
    ) -> tuple[SpellingCandidate, ...]:
        candidates: list[SpellingCandidate] = []
        for value in self._candidate_pool(token):
            distance = arabic_edit_distance(token, value)
            if distance > self.max_distance:
                continue
            ranked = self._rank_candidate(value, distance, previous, following)
            if ranked is not None:
                candidates.append(ranked)
        candidates.sort(
            key=lambda item: (
                item.score,
                item.distance,
                -item.frequency,
                -item.morphology_confidence,
                item.value,
            )
        )
        # Avoid presenting multiple inflectional surfaces of the same lemma
        # before candidates from distinct lexemes.
        diversified: list[SpellingCandidate] = []
        seen_values: set[str] = set()
        for candidate in candidates:
            if candidate.value in seen_values:
                continue
            seen_values.add(candidate.value)
            diversified.append(candidate)
            if len(diversified) >= self.max_candidates:
                break
        return tuple(diversified)

    def suggest(
        self, token: str, *, previous: str | None = None, following: str | None = None
    ) -> tuple[SpellingCandidate, ...]:
        normalized_token = normalize(token, NormalizationMode.LOOKUP)
        normalized_previous = normalize(previous) if previous else None
        normalized_following = normalize(following) if following else None
        return self._suggest_cached(normalized_token, normalized_previous, normalized_following)

    def validate(
        self, token: str, *, previous: str | None = None, following: str | None = None
    ) -> SpellingDecision:
        normalized_token = normalize(token, NormalizationMode.LOOKUP)
        if len(normalized_token) < 3:
            return SpellingDecision(token, True, reason="short_token")
        if any(char in normalized_token for char in "چگپژڤ"):
            return SpellingDecision(token, True, reason="dialect_letter")
        if token != normalized_token:
            # Vocalized text is outside lexical correction in Phase 3.  Its
            # consonantal skeleton can still be analyzed by morphology.
            return SpellingDecision(token, True, reason="vocalized_or_extended")
        if previous in _NAME_CUES:
            return SpellingDecision(token, True, reason="name_context")
        analyses = self.analyzer.analyze(token)
        if any(item.is_lexical and item.confidence >= 0.72 for item in analyses):
            return SpellingDecision(token, True, reason="lexical_analysis")
        # A derivation from a known root with high confidence is treated as a
        # plausible open-vocabulary form, even if not listed verbatim.
        if any(item.source == "segmented" and item.confidence >= 0.72 for item in analyses):
            return SpellingDecision(token, True, reason="known_root_derivation")
        candidates = self.suggest(token, previous=previous, following=following)
        if not candidates:
            return SpellingDecision(token, True, reason="no_reliable_candidate")
        best = candidates[0]
        if (
            len(candidates) > 1
            and best.distance > 0.25
            and abs(candidates[1].distance - best.distance) <= 0.30
        ):
            return SpellingDecision(token, True, candidates, "ambiguous_candidates")
        second_score = candidates[1].score if len(candidates) > 1 else math.inf
        margin = second_score - best.score
        # Confusion-class substitutions are allowed with a smaller margin;
        # arbitrary one-edit corrections require stronger separation.
        required_margin = 0.12 if best.distance <= 0.25 else self.min_margin
        if best.distance > self.max_distance or margin < required_margin:
            return SpellingDecision(token, True, candidates, "ambiguous_candidates")
        confidence = self._decision_confidence(best, margin)
        if confidence < 0.81:
            return SpellingDecision(token, True, candidates, "low_confidence")
        return SpellingDecision(token, False, candidates, "high_confidence_candidate")

    @staticmethod
    def _decision_confidence(best: SpellingCandidate, margin: float) -> float:
        distance_component = max(0.0, 1.0 - best.distance / 1.2)
        margin_component = min(1.0, margin / 1.2) if math.isfinite(margin) else 1.0
        frequency_component = min(1.0, math.log1p(best.frequency) / 11.0)
        return min(
            0.995,
            0.58
            + distance_component * 0.20
            + margin_component * 0.10
            + frequency_component * 0.06
            + best.morphology_confidence * 0.06,
        )

    @staticmethod
    def _arabic_word_tokens(text: str) -> list[Token]:
        return [token for token in tokenize(text) if token.kind == TokenKind.ARABIC_WORD]

    def check_text(self, text: str, *, tokens: Sequence[Token] | None = None) -> list[Match]:
        """Return non-overlapping lexical spelling matches for Arabic words."""

        words = (
            self._arabic_word_tokens(text)
            if tokens is None
            else [token for token in tokens if token.kind == TokenKind.ARABIC_WORD]
        )
        out: list[Match] = []
        for index, token in enumerate(words):
            previous = words[index - 1].text if index else None
            following = words[index + 1].text if index + 1 < len(words) else None
            decision = self.validate(token.text, previous=previous, following=following)
            if decision.valid or not decision.candidates:
                continue
            best = decision.candidates[0]
            second_score = (
                decision.candidates[1].score if len(decision.candidates) > 1 else math.inf
            )
            confidence = self._decision_confidence(best, second_score - best.score)
            replacements = [candidate.value for candidate in decision.candidates]
            out.append(
                Match(
                    rule_id="SPELL_LEXICAL_UNKNOWN",
                    category="spelling",
                    message=f"قد تكون «{token.text}» مكتوبة على نحو غير صحيح.",
                    offset=token.start,
                    length=token.end - token.start,
                    replacements=replacements,
                    severity="warning",
                    explanation=(
                        "قورنت الكلمة بالمعجم الصرفي بعد التحقق من السوابق واللواحق "
                        "والأوزان؛ الاقتراحات مرتبة بحسب المسافة الإملائية والسياق والتواتر."
                    ),
                    autofix=False,
                    confidence=confidence,
                    priority=76,
                    tags=("lexical", "morphology-aware"),
                    references=("Dhad core lexicon v1",),
                    profiles=("default",),
                )
            )
        return out

    def cache_info(self):
        return self._suggest_cached.cache_info()


@lru_cache(maxsize=1)
def default_spellchecker() -> SpellChecker:
    """Return the shared default lexical spellchecker."""

    return SpellChecker(default_analyzer())
