"""Deterministic Arabic syntax, candidate parsing, and visible grammar checks.

Phase 4 deliberately limits automatic diagnostics to morphosyntactic evidence
that is observable in unvocalized Arabic.  The parser still emits candidate
iʿrāb for less certain structures, but the checker follows Dhad's precision
contract: when competing parses remain plausible, it stays silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Iterable, Mapping, Sequence

from .match import Match
from .morphology import MorphologicalAnalysis, MorphologicalAnalyzer, default_analyzer
from .text import (
    NormalizationMode,
    Sentence,
    Token,
    TokenKind,
    iter_tokens,
    normalize,
    sentence_spans,
)

_NOMINAL_POS = frozenset({"noun", "proper_noun", "verbal_noun"})
_PREPOSITIONS = frozenset(
    {"في", "من", "إلى", "على", "عن", "مع", "لدى", "عند", "بين", "حول", "خلال", "دون", "قبل", "بعد"}
)
_SUBJUNCTIVE_PARTICLES = frozenset({"لن", "أن", "كي", "حتى"})
_JUSSIVE_PARTICLES = frozenset({"لم", "لما"})
_CONJUNCTIONS = frozenset({"و", "ف", "ثم", "أو", "بل", "لكن"})

# Gender and number are lexical properties of demonstratives and are not
# reliably supplied by the Phase-3 lexicon because those entries are closed
# class pronouns.  Keeping the table explicit is deterministic and auditable.
_DEMONSTRATIVES: Mapping[str, tuple[str, str]] = {
    "هذا": ("masculine", "singular"),
    "هذه": ("feminine", "singular"),
    "ذلك": ("masculine", "singular"),
    "تلك": ("feminine", "singular"),
    "هذان": ("masculine", "dual"),
    "هذين": ("masculine", "dual"),
    "هاتان": ("feminine", "dual"),
    "هاتين": ("feminine", "dual"),
    "هؤلاء": ("common", "plural"),
    "أولئك": ("common", "plural"),
}

_DEMONSTRATIVE_SURFACES: Mapping[tuple[str, str, str], str] = {
    ("near", "masculine", "singular"): "هذا",
    ("near", "feminine", "singular"): "هذه",
    ("far", "masculine", "singular"): "ذلك",
    ("far", "feminine", "singular"): "تلك",
    ("near", "masculine", "dual"): "هذان",
    ("near", "feminine", "dual"): "هاتان",
    ("near", "common", "plural"): "هؤلاء",
    ("far", "common", "plural"): "أولئك",
}

# VSO gender diagnostics are restricted to verbs whose immediately following
# nominal is overwhelmingly likely to be their subject rather than an object.
_INTRANSITIVE_VERBS = frozenset(
    {
        "جاء",
        "حضر",
        "ذهب",
        "وصل",
        "اكتمل",
        "انتهى",
        "استمر",
        "زال",
    }
)

# Human plurals preserve plural agreement; non-human plurals take feminine
# singular agreement in standard Arabic.  The list is intentionally small and
# high precision.  Unknown plural nouns do not trigger number diagnostics.
_HUMAN_LEMMAS = frozenset(
    {
        "إنسان",
        "أستاذ",
        "طالب",
        "كاتب",
        "مهندس",
        "موظف",
        "مستخدم",
        "رجل",
        "والي",
    }
)


class RelationType(str, Enum):
    """Relations produced by the lightweight deterministic parser."""

    DEMONSTRATIVE = "demonstrative"
    SUBJECT = "subject"
    NAAT = "naat"
    IDAFA = "idafa"
    PREPOSITION_OBJECT = "preposition_object"
    SUBJUNCTIVE_VERB = "subjunctive_verb"
    JUSSIVE_VERB = "jussive_verb"


@dataclass(frozen=True, slots=True)
class SyntaxToken:
    """One source token with a context-selected morphological reading."""

    text: str
    start: int
    end: int
    analysis: MorphologicalAnalysis | None
    alternatives: tuple[MorphologicalAnalysis, ...]
    confidence: float
    break_before: bool = False

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Syntax token span must be positive and ordered")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Syntax token confidence must be between 0 and 1")

    @property
    def pos(self) -> str:
        return self.analysis.pos if self.analysis is not None else "unknown"

    def feature(self, name: str, default: str | None = None) -> str | None:
        if self.analysis is None:
            return default
        return self.analysis.feature(name, default)


@dataclass(frozen=True, slots=True)
class SyntacticRelation:
    """A typed dependency candidate between source tokens."""

    relation: RelationType
    head_index: int | None
    dependent_index: int
    confidence: float
    governor: str = ""
    explanation: str = ""

    def __post_init__(self) -> None:
        if self.dependent_index < 0:
            raise ValueError("Dependent token index cannot be negative")
        if self.head_index is not None and self.head_index < 0:
            raise ValueError("Head token index cannot be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Relation confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class IrabCandidate:
    """Explainable candidate iʿrāb for one token."""

    token_index: int
    role: str
    case_or_mood: str
    marker: str
    governor_index: int | None
    governor: str
    confidence: float
    explanation: str

    def __post_init__(self) -> None:
        if self.token_index < 0:
            raise ValueError("I'rab token index cannot be negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("I'rab confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SentenceParse:
    """A candidate parse retaining exact source offsets."""

    text: str
    start: int
    end: int
    tokens: tuple[SyntaxToken, ...]
    relations: tuple[SyntacticRelation, ...]
    irab: tuple[IrabCandidate, ...]
    confidence: float

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("Sentence parse span is invalid")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Parse confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class DocumentParse:
    """All sentence parses for one document."""

    text: str
    sentences: tuple[SentenceParse, ...]

    @property
    def relations(self) -> tuple[SyntacticRelation, ...]:
        return tuple(relation for sentence in self.sentences for relation in sentence.relations)


@dataclass(frozen=True, slots=True)
class _RawWord:
    token: Token
    break_before: bool


def _surface(value: str) -> str:
    return normalize(value, NormalizationMode.LOOKUP)


def _is_nominal(token: SyntaxToken) -> bool:
    return token.pos in _NOMINAL_POS


def _is_adjective(token: SyntaxToken) -> bool:
    return token.pos == "adjective"


def _is_verb(token: SyntaxToken) -> bool:
    return token.pos == "verb"


def _is_definite(token: SyntaxToken) -> bool:
    if token.analysis is None:
        return False
    if token.pos == "proper_noun":
        return True
    if token.feature("definiteness") == "definite":
        return True
    return any(segment.feature == "definite" for segment in token.analysis.prefixes) or any(
        segment.feature.startswith("pronoun_") for segment in token.analysis.suffixes
    )


def _gender(token: SyntaxToken) -> str | None:
    value = token.feature("gender")
    if value in {"masculine", "feminine"}:
        return value
    surface = _surface(token.text)
    if surface.endswith(("ة", "ات", "تان", "تين")):
        return "feminine"
    return None


def _number(token: SyntaxToken) -> str:
    value = token.feature("number")
    if value in {"singular", "dual", "plural"}:
        return value
    return "singular"


def _aspect(token: SyntaxToken) -> str | None:
    return token.feature("aspect")


def _person(token: SyntaxToken) -> str | None:
    value = token.feature("person")
    if value is not None:
        return value
    if _aspect(token) == "imperfect":
        surface = _surface(token.text)
        if surface.startswith("ي"):
            return "3m"
        if surface.startswith("ت"):
            return "2_or_3f"
        if surface.startswith("ن"):
            return "1p"
        if surface.startswith("أ"):
            return "1s"
    return None


def _visible_case(token: SyntaxToken) -> str | None:
    value = token.feature("case")
    if value in {"nominative", "oblique"}:
        return value
    surface = _surface(token.text)
    if surface.endswith(("تان", "ان", "ون")):
        return "nominative"
    if surface.endswith(("تين", "ين")):
        return "oblique"
    return None


def _has_visible_tanween(value: str) -> bool:
    return any(mark in value for mark in "ًٌٍ")


def _strip_tanween(value: str) -> str:
    return value.translate(str.maketrans("", "", "ًٌٍ"))


def _demonstrative_distance(surface: str) -> str:
    return "far" if surface in {"ذلك", "تلك", "أولئك"} else "near"


def _governed_five_verb(surface: str) -> str | None:
    """Return the visible subjunctive/jussive form with deletion of nūn."""

    if surface.endswith("ون") and len(surface) > 3:
        return surface[:-2] + "وا"
    if surface.endswith(("ان", "ين")) and len(surface) > 3:
        return surface[:-1]
    return None


def _oblique_surface(surface: str) -> str | None:
    """Convert visible nominative dual/sound-plural endings to oblique."""

    if surface.endswith("تان") and len(surface) > 3:
        return surface[:-3] + "تين"
    if surface.endswith("ان") and len(surface) > 3:
        return surface[:-2] + "ين"
    if surface.endswith("ون") and len(surface) > 3:
        return surface[:-2] + "ين"
    return None


def _idafa_drop_nun(surface: str) -> str | None:
    if surface.endswith("ون") and len(surface) > 3:
        return surface[:-1]
    if surface.endswith(("ان", "ين")) and len(surface) > 3:
        return surface[:-1]
    return None


class SyntaxEngine:
    """Precision-gated parser and grammar checker over Phase-3 morphology."""

    def __init__(
        self,
        morphology: MorphologicalAnalyzer | None = None,
        *,
        min_token_confidence: float = 0.72,
        min_relation_confidence: float = 0.80,
    ):
        if not 0.0 <= min_token_confidence <= 1.0:
            raise ValueError("min_token_confidence must be between 0 and 1")
        if not 0.0 <= min_relation_confidence <= 1.0:
            raise ValueError("min_relation_confidence must be between 0 and 1")
        self.morphology = morphology or default_analyzer()
        self.min_token_confidence = min_token_confidence
        self.min_relation_confidence = min_relation_confidence
        self._parse_sentence_cached = lru_cache(maxsize=4096)(self._parse_sentence_uncached)

    @staticmethod
    def _raw_words(sentence: Sentence) -> tuple[_RawWord, ...]:
        words: list[_RawWord] = []
        barrier = False
        for token in iter_tokens(sentence.text):
            if token.kind == TokenKind.WHITESPACE:
                continue
            if token.kind == TokenKind.ARABIC_WORD:
                absolute = Token(
                    token.text,
                    sentence.start + token.start,
                    sentence.start + token.end,
                    token.kind,
                )
                words.append(_RawWord(absolute, barrier))
                barrier = False
                continue
            if token.kind in {
                TokenKind.PUNCTUATION,
                TokenKind.SYMBOL,
                TokenKind.CODE,
                TokenKind.URL,
                TokenKind.EMAIL,
            }:
                barrier = True
        return tuple(words)

    @staticmethod
    def _context_score(
        analysis: MorphologicalAnalysis,
        surface: str,
        previous: str | None,
        following: str | None,
    ) -> float:
        score = analysis.confidence
        if surface in _DEMONSTRATIVES:
            score += 0.25 if analysis.pos == "pronoun" else -0.25
        if surface in _PREPOSITIONS | _SUBJUNCTIVE_PARTICLES | _JUSSIVE_PARTICLES:
            score += 0.25 if analysis.pos == "particle" else -0.25
        if previous in _PREPOSITIONS:
            score += 0.14 if analysis.pos in _NOMINAL_POS | {"adjective", "pronoun"} else -0.12
        if previous in _SUBJUNCTIVE_PARTICLES | _JUSSIVE_PARTICLES:
            score += 0.18 if analysis.pos == "verb" else -0.14
            if analysis.feature("aspect") == "imperfect":
                score += 0.08
        if previous in _DEMONSTRATIVES:
            score += 0.16 if analysis.pos in _NOMINAL_POS else -0.10
        if following and following.startswith("ال") and analysis.pos in _NOMINAL_POS:
            score += 0.03
        if analysis.is_lexical:
            score += 0.04
        return score

    def _select_analysis(
        self,
        raw: _RawWord,
        previous: str | None,
        following: str | None,
    ) -> SyntaxToken:
        analyses = self.morphology.analyze(raw.token.text, min_confidence=0.55)
        if not analyses:
            return SyntaxToken(
                raw.token.text,
                raw.token.start,
                raw.token.end,
                None,
                (),
                0.0,
                raw.break_before,
            )
        surface = _surface(raw.token.text)
        ranked = sorted(
            analyses,
            key=lambda item: (
                -self._context_score(item, surface, previous, following),
                -item.confidence,
                -item.frequency,
                item.lemma,
            ),
        )
        best = ranked[0]
        best_score = self._context_score(best, surface, previous, following)
        second_score = (
            self._context_score(ranked[1], surface, previous, following)
            if len(ranked) > 1
            else best_score - 0.30
        )
        margin = max(0.0, best_score - second_score)
        confidence = min(0.999, best.confidence * 0.82 + min(0.18, margin * 0.6))
        return SyntaxToken(
            raw.token.text,
            raw.token.start,
            raw.token.end,
            best,
            tuple(ranked[1:]),
            confidence,
            raw.break_before,
        )

    @staticmethod
    def _adjacent(tokens: Sequence[SyntaxToken], left: int, right: int) -> bool:
        return right == left + 1 and not tokens[right].break_before

    @staticmethod
    def _relation_confidence(*tokens: SyntaxToken, structural: float = 0.90) -> float:
        lexical = min((token.confidence for token in tokens), default=0.0)
        return max(0.0, min(0.999, structural * 0.55 + lexical * 0.45))

    def _relations(self, tokens: Sequence[SyntaxToken]) -> tuple[SyntacticRelation, ...]:
        out: list[SyntacticRelation] = []
        for index, token in enumerate(tokens):
            surface = _surface(token.text)
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if following is not None and self._adjacent(tokens, index, index + 1):
                if surface in _DEMONSTRATIVES and _is_nominal(following):
                    out.append(
                        SyntacticRelation(
                            RelationType.DEMONSTRATIVE,
                            index,
                            index + 1,
                            self._relation_confidence(token, following, structural=0.98),
                            surface,
                            "اسم إشارة يحدد اسمًا ظاهرًا ملاصقًا له.",
                        )
                    )
                if surface in _PREPOSITIONS and (
                    _is_nominal(following) or following.pos in {"adjective", "pronoun"}
                ):
                    out.append(
                        SyntacticRelation(
                            RelationType.PREPOSITION_OBJECT,
                            index,
                            index + 1,
                            self._relation_confidence(token, following, structural=0.97),
                            surface,
                            "حرف الجر يعمل في الاسم الظاهر التالي له.",
                        )
                    )
                if surface in _SUBJUNCTIVE_PARTICLES and _is_verb(following):
                    out.append(
                        SyntacticRelation(
                            RelationType.SUBJUNCTIVE_VERB,
                            index,
                            index + 1,
                            self._relation_confidence(token, following, structural=0.96),
                            surface,
                            "حرف نصب يسبق فعلًا مضارعًا.",
                        )
                    )
                if surface in _JUSSIVE_PARTICLES and _is_verb(following):
                    out.append(
                        SyntacticRelation(
                            RelationType.JUSSIVE_VERB,
                            index,
                            index + 1,
                            self._relation_confidence(token, following, structural=0.97),
                            surface,
                            "حرف جزم يسبق فعلًا مضارعًا.",
                        )
                    )
                if _is_nominal(token) and _is_adjective(following):
                    # Matching definiteness strongly separates an attributive
                    # adjective from a nominal predicate in unvocalized text.
                    both_definite = _is_definite(token) and _is_definite(following)
                    if both_definite:
                        out.append(
                            SyntacticRelation(
                                RelationType.NAAT,
                                index,
                                index + 1,
                                self._relation_confidence(token, following, structural=0.94),
                                token.text,
                                "اسم معرف يتبعه نعت معرف مباشرة.",
                            )
                        )
                if _is_nominal(token) and _is_nominal(following):
                    first_is_open = not _is_definite(token)
                    second_is_closed = _is_definite(following)
                    if first_is_open and second_is_closed:
                        out.append(
                            SyntacticRelation(
                                RelationType.IDAFA,
                                index,
                                index + 1,
                                self._relation_confidence(token, following, structural=0.91),
                                token.text,
                                "اسمان متجاوران؛ الأول مضاف والثاني معرفة مرشحة للإضافة إليه.",
                            )
                        )
                if _is_verb(token) and _is_nominal(following):
                    lemma = token.analysis.lemma if token.analysis is not None else ""
                    if lemma in _INTRANSITIVE_VERBS:
                        out.append(
                            SyntacticRelation(
                                RelationType.SUBJECT,
                                index,
                                index + 1,
                                self._relation_confidence(token, following, structural=0.93),
                                token.text,
                                "فعل لازم يتبعه اسم ظاهر مرشح للفاعلية.",
                            )
                        )
                if _is_nominal(token) and _is_verb(following) and _is_definite(token):
                    out.append(
                        SyntacticRelation(
                            RelationType.SUBJECT,
                            index + 1,
                            index,
                            self._relation_confidence(token, following, structural=0.88),
                            following.text,
                            "اسم معرف متقدم يتبعه فعل مرشح للإسناد إليه.",
                        )
                    )
            if token.analysis is not None:
                preposition_prefix = next(
                    (
                        segment.surface
                        for segment in token.analysis.prefixes
                        if segment.feature == "preposition"
                    ),
                    None,
                )
                if preposition_prefix is not None and _is_nominal(token):
                    out.append(
                        SyntacticRelation(
                            RelationType.PREPOSITION_OBJECT,
                            None,
                            index,
                            min(0.97, token.confidence + 0.04),
                            preposition_prefix,
                            "حرف جر متصل بالاسم في الكلمة نفسها.",
                        )
                    )
        unique: dict[tuple[RelationType, int | None, int], SyntacticRelation] = {}
        for relation in out:
            key = (relation.relation, relation.head_index, relation.dependent_index)
            current = unique.get(key)
            if current is None or relation.confidence > current.confidence:
                unique[key] = relation
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.dependent_index,
                    item.head_index if item.head_index is not None else -1,
                    item.relation.value,
                ),
            )
        )

    @staticmethod
    def _base_irab(token: SyntaxToken, index: int) -> IrabCandidate:
        role_by_pos = {
            "verb": "فعل",
            "noun": "اسم",
            "proper_noun": "علم",
            "verbal_noun": "مصدر",
            "adjective": "صفة",
            "pronoun": "ضمير",
            "particle": "حرف",
            "adverb": "ظرف أو حال مرشح",
        }
        role = role_by_pos.get(token.pos, "غير محسوم")
        confidence = max(0.20, token.confidence * 0.72)
        return IrabCandidate(
            index,
            role,
            "غير ظاهر في النص غير المشكول",
            "علامة مقدرة أو غير محسومة",
            None,
            "",
            confidence,
            "قراءة أولية مبنية على نوع الكلمة الصرفي، قبل تطبيق علاقات الجملة.",
        )

    def _irab(
        self, tokens: Sequence[SyntaxToken], relations: Sequence[SyntacticRelation]
    ) -> tuple[IrabCandidate, ...]:
        candidates = [self._base_irab(token, index) for index, token in enumerate(tokens)]

        def update(index: int, candidate: IrabCandidate) -> None:
            if candidate.confidence >= candidates[index].confidence:
                candidates[index] = candidate

        for relation in relations:
            dependent = relation.dependent_index
            if relation.relation == RelationType.PREPOSITION_OBJECT:
                update(
                    dependent,
                    IrabCandidate(
                        dependent,
                        "اسم مجرور",
                        "genitive",
                        "الكسرة أو ما ينوب عنها",
                        relation.head_index,
                        relation.governor,
                        relation.confidence,
                        "الاسم مجرور لوقوعه بعد حرف جر ظاهر أو متصل.",
                    ),
                )
            elif relation.relation == RelationType.SUBJUNCTIVE_VERB:
                update(
                    dependent,
                    IrabCandidate(
                        dependent,
                        "فعل مضارع منصوب",
                        "subjunctive",
                        "الفتحة أو حذف النون في الأفعال الخمسة",
                        relation.head_index,
                        relation.governor,
                        relation.confidence,
                        "الفعل منصوب بحرف نصب سابق.",
                    ),
                )
            elif relation.relation == RelationType.JUSSIVE_VERB:
                update(
                    dependent,
                    IrabCandidate(
                        dependent,
                        "فعل مضارع مجزوم",
                        "jussive",
                        "السكون أو حذف حرف العلة أو حذف النون",
                        relation.head_index,
                        relation.governor,
                        relation.confidence,
                        "الفعل مجزوم بحرف جزم سابق.",
                    ),
                )
            elif relation.relation == RelationType.SUBJECT:
                update(
                    dependent,
                    IrabCandidate(
                        dependent,
                        "فاعل أو مسند إليه مرشح",
                        "nominative",
                        "الضمة أو ما ينوب عنها",
                        relation.head_index,
                        relation.governor,
                        relation.confidence,
                        "العلاقة الإسنادية مرجحة من ترتيب الفعل والاسم ونوع الفعل.",
                    ),
                )
            elif relation.relation == RelationType.NAAT:
                update(
                    dependent,
                    IrabCandidate(
                        dependent,
                        "نعت",
                        "يتبع المنعوت",
                        "يتبع المنعوت في علامة الإعراب",
                        relation.head_index,
                        relation.governor,
                        relation.confidence,
                        "النعت يتبع المنعوت في التعريف والجنس والعدد والإعراب.",
                    ),
                )
            elif relation.relation == RelationType.IDAFA:
                head = relation.head_index
                if head is not None:
                    update(
                        head,
                        IrabCandidate(
                            head,
                            "مضاف",
                            "بحسب موقعه في الجملة",
                            "لا يقبل التنوين ولا نون المثنى أو الجمع",
                            None,
                            "",
                            relation.confidence,
                            "الاسم الأول مرشح للإضافة إلى الاسم المعرفة التالي.",
                        ),
                    )
                update(
                    dependent,
                    IrabCandidate(
                        dependent,
                        "مضاف إليه",
                        "genitive",
                        "الكسرة أو ما ينوب عنها",
                        head,
                        relation.governor,
                        relation.confidence,
                        "الاسم الثاني مجرور بالإضافة.",
                    ),
                )
            elif relation.relation == RelationType.DEMONSTRATIVE:
                update(
                    dependent,
                    IrabCandidate(
                        dependent,
                        "مشار إليه؛ بدل أو عطف بيان مرشح",
                        "يتبع موقع اسم الإشارة",
                        "بحسب موقع التركيب",
                        relation.head_index,
                        relation.governor,
                        relation.confidence * 0.94,
                        "الاسم الظاهر يبين مرجع اسم الإشارة السابق.",
                    ),
                )
        return tuple(candidates)

    def rebuild_sentence(
        self, parse: SentenceParse, tokens: Sequence[SyntaxToken]
    ) -> SentenceParse:
        """Recompute relations and iʿrāb after a constrained candidate re-rank.

        Callers may only supply tokens anchored to the same source sentence.
        This is the integration boundary used by the Phase-7 hybrid layer; it
        prevents contextual classifiers from fabricating tokens or offsets.
        """

        values = tuple(tokens)
        if len(values) != len(parse.tokens):
            raise ValueError("Rebuilt sentence must preserve the token count")
        for original, candidate in zip(parse.tokens, values):
            if (original.text, original.start, original.end) != (
                candidate.text,
                candidate.start,
                candidate.end,
            ):
                raise ValueError("Rebuilt tokens must preserve source text and offsets")
        relations = self._relations(values)
        irab = self._irab(values, relations)
        confidence = sum(token.confidence for token in values) / len(values) if values else 1.0
        if relations:
            confidence = min(
                0.999,
                confidence * 0.72
                + (sum(item.confidence for item in relations) / len(relations)) * 0.28,
            )
        return SentenceParse(
            parse.text,
            parse.start,
            parse.end,
            values,
            relations,
            irab,
            confidence,
        )

    def _parse_sentence_uncached(self, sentence_text: str, start: int) -> SentenceParse:
        sentence = Sentence(sentence_text, start, start + len(sentence_text), "")
        raw_words = self._raw_words(sentence)
        surfaces = [_surface(item.token.text) for item in raw_words]
        tokens = tuple(
            self._select_analysis(
                raw,
                surfaces[index - 1] if index else None,
                surfaces[index + 1] if index + 1 < len(surfaces) else None,
            )
            for index, raw in enumerate(raw_words)
        )
        relations = self._relations(tokens)
        irab = self._irab(tokens, relations)
        parse_confidence = (
            sum(token.confidence for token in tokens) / len(tokens) if tokens else 1.0
        )
        if relations:
            parse_confidence = min(
                0.999,
                parse_confidence * 0.72
                + (sum(item.confidence for item in relations) / len(relations)) * 0.28,
            )
        return SentenceParse(
            sentence_text,
            start,
            start + len(sentence_text),
            tokens,
            relations,
            irab,
            parse_confidence,
        )

    def parse_sentence(self, sentence: Sentence | str, *, start: int = 0) -> SentenceParse:
        """Parse one sentence while preserving absolute offsets."""

        if isinstance(sentence, Sentence):
            return self._parse_sentence_cached(sentence.text, sentence.start)
        return self._parse_sentence_cached(sentence, start)

    def parse(self, text: str) -> DocumentParse:
        """Parse all sentence spans in a document."""

        return DocumentParse(
            text, tuple(self.parse_sentence(sentence) for sentence in sentence_spans(text))
        )

    def _matching_form(
        self,
        analysis: MorphologicalAnalysis,
        *,
        features: Mapping[str, str],
        definite: bool | None = None,
    ) -> str | None:
        required = dict(features)
        if definite is True:
            required["definiteness"] = "definite"
        records = self.morphology.lexicon.forms_for_lemma(
            analysis.lemma,
            pos=analysis.pos,
            features=required,
        )
        if definite is False:
            records = tuple(
                record
                for record in records
                if dict(record.features).get("definiteness") != "definite"
                and not any(feature == "definite" for _, feature in record.prefixes)
            )
        if not records:
            return None
        return records[0].form

    @staticmethod
    def _match(
        *,
        rule_id: str,
        message: str,
        token: SyntaxToken,
        replacements: Iterable[str],
        explanation: str,
        confidence: float,
        priority: int,
        autofix: bool,
        length: int | None = None,
        offset: int | None = None,
    ) -> Match:
        return Match(
            rule_id=rule_id,
            category="grammar",
            message=message,
            offset=token.start if offset is None else offset,
            length=(token.end - token.start) if length is None else length,
            replacements=list(dict.fromkeys(replacements)),
            severity="error",
            explanation=explanation,
            autofix=autofix,
            confidence=max(0.0, min(0.999, confidence)),
            priority=priority,
            tags=("syntax", "morphology-aware"),
            references=("Dhad deterministic syntax v1",),
            profiles=("default",),
        )

    def _check_demonstrative(
        self, parse: SentenceParse, relation: SyntacticRelation
    ) -> Match | None:
        if relation.head_index is None or relation.confidence < self.min_relation_confidence:
            return None
        demonstrative = parse.tokens[relation.head_index]
        noun = parse.tokens[relation.dependent_index]
        noun_gender = _gender(noun)
        noun_number = _number(noun)
        surface = _surface(demonstrative.text)
        demo_gender, demo_number = _DEMONSTRATIVES[surface]
        if noun_number == "plural":
            # Human/non-human demonstrative selection is semantically dependent;
            # only reject a visibly singular demonstrative when the noun is a
            # lexically known human plural.
            if noun.analysis is None or noun.analysis.lemma not in _HUMAN_LEMMAS:
                return None
            expected_gender = "common"
            expected_number = "plural"
        else:
            if noun_gender is None:
                return None
            expected_gender = noun_gender
            expected_number = noun_number
        gender_mismatch = demo_gender not in {"common", expected_gender}
        number_mismatch = demo_number != expected_number
        if not gender_mismatch and not number_mismatch:
            return None
        replacement_demo = _DEMONSTRATIVE_SURFACES.get(
            (_demonstrative_distance(surface), expected_gender, expected_number)
        )
        if replacement_demo is None:
            return None
        span_start = demonstrative.start
        span_end = noun.end
        original_tail = parse.text[noun.start - parse.start : noun.end - parse.start]
        replacement = f"{replacement_demo} {original_tail}"
        return self._match(
            rule_id="SYNTAX_DEMONSTRATIVE_AGREEMENT",
            message="اسم الإشارة لا يطابق الاسم المشار إليه في الجنس أو العدد.",
            token=demonstrative,
            replacements=(replacement,),
            explanation=(
                "يطابق اسم الإشارة الاسمَ المشار إليه في الجنس والعدد عندما يكون "
                "المرجع مفردًا أو مثنى، وتُراعى دلالة العاقل في الجمع."
            ),
            confidence=relation.confidence,
            priority=91,
            autofix=True,
            offset=span_start,
            length=span_end - span_start,
        )

    def _expected_adjective_features(self, noun: SyntaxToken) -> tuple[str | None, str | None]:
        gender = _gender(noun)
        number = _number(noun)
        if number == "plural" and noun.analysis is not None:
            if noun.analysis.lemma in _HUMAN_LEMMAS:
                return gender, "plural"
            return "feminine", "singular"
        return gender, number

    def _check_naat(self, parse: SentenceParse, relation: SyntacticRelation) -> Match | None:
        if relation.head_index is None or relation.confidence < self.min_relation_confidence:
            return None
        noun = parse.tokens[relation.head_index]
        adjective = parse.tokens[relation.dependent_index]
        if noun.analysis is None or adjective.analysis is None:
            return None
        expected_gender, expected_number = self._expected_adjective_features(noun)
        adjective_gender = _gender(adjective)
        adjective_number = _number(adjective)
        mismatched: dict[str, str] = {}
        if expected_gender is not None and adjective_gender is not None:
            if expected_gender != adjective_gender:
                mismatched["gender"] = expected_gender
        if expected_number is not None and adjective_number != expected_number:
            # Broken plural adjective generation is not complete in Phase 3;
            # only emit a number diagnostic when the required form exists.
            mismatched["number"] = expected_number
        if not mismatched:
            return None
        replacement = self._matching_form(
            adjective.analysis,
            features=mismatched,
            definite=_is_definite(adjective),
        )
        if replacement is None:
            return None
        return self._match(
            rule_id="SYNTAX_NAAT_AGREEMENT",
            message="النعت لا يطابق المنعوت في الجنس أو العدد.",
            token=adjective,
            replacements=(replacement,),
            explanation=(
                "يتبع النعت المنعوت في التعريف والتنكير والجنس والعدد والإعراب. "
                "ويعامل جمع غير العاقل معاملة المفردة المؤنثة."
            ),
            confidence=relation.confidence * 0.97,
            priority=88,
            autofix=False,
        )

    def _check_subject(self, parse: SentenceParse, relation: SyntacticRelation) -> Match | None:
        if relation.head_index is None or relation.confidence < self.min_relation_confidence:
            return None
        verb = parse.tokens[relation.head_index]
        subject = parse.tokens[relation.dependent_index]
        if verb.analysis is None or subject.analysis is None:
            return None
        subject_gender = _gender(subject)
        subject_number = _number(subject)
        if subject_gender is None or subject_number != "singular":
            return None
        verb_surface = _surface(verb.text)
        verb_aspect = _aspect(verb)
        # High-precision VSO rule: unmarked perfect intransitive verb followed by
        # an explicit singular feminine subject requires feminine agreement.
        if (
            verb.start < subject.start
            and subject_gender == "feminine"
            and verb_aspect in {None, "perfect"}
            and not verb_surface.endswith("ت")
            and verb.analysis.lemma in _INTRANSITIVE_VERBS
        ):
            replacement = self._matching_form(
                verb.analysis,
                features={"aspect": "perfect", "person": "1_or_2_or_3f"},
                definite=False,
            )
            if replacement is None:
                replacement = verb_surface + "ت"
            return self._match(
                rule_id="SYNTAX_VERB_SUBJECT_GENDER",
                message="الفعل لا يطابق الفاعل المؤنث الظاهر.",
                token=verb,
                replacements=(replacement,),
                explanation=(
                    "إذا تقدم الفعل الماضي على فاعل مؤنث حقيقي ظاهر، لزم تأنيث الفعل "
                    "في هذا السياق غير الملتبس."
                ),
                confidence=relation.confidence * 0.96,
                priority=87,
                autofix=False,
            )
        # SVO rule: a definite feminine subject immediately followed by a
        # third-person masculine imperfect is a visible prefix disagreement.
        if (
            subject.start < verb.start
            and subject_gender == "feminine"
            and verb_aspect == "imperfect"
            and _person(verb) == "3m"
            and verb_surface.startswith("ي")
        ):
            replacement = "ت" + verb_surface[1:]
            return self._match(
                rule_id="SYNTAX_SUBJECT_VERB_PREFIX",
                message="الفعل المضارع لا يطابق المسند إليه المؤنث المتقدم.",
                token=verb,
                replacements=(replacement,),
                explanation=(
                    "عند تقدم الفاعل أو المبتدأ المؤنث المفرد، يطابقه الفعل المضارع "
                    "في علامة التأنيث الظاهرة."
                ),
                confidence=relation.confidence * 0.93,
                priority=86,
                autofix=False,
            )
        return None

    def _check_idafa(self, parse: SentenceParse, relation: SyntacticRelation) -> Match | None:
        if relation.head_index is None or relation.confidence < self.min_relation_confidence:
            return None
        mudaf = parse.tokens[relation.head_index]
        surface = mudaf.text
        if _has_visible_tanween(surface):
            return self._match(
                rule_id="SYNTAX_IDAFA_TANWEEN",
                message="المضاف لا يقبل التنوين.",
                token=mudaf,
                replacements=(_strip_tanween(surface),),
                explanation="يحذف التنوين من الاسم الأول عند دخوله في تركيب الإضافة.",
                confidence=relation.confidence * 0.98,
                priority=90,
                autofix=True,
            )
        corrected = _idafa_drop_nun(_surface(surface))
        if corrected is None:
            return None
        case = _visible_case(mudaf)
        number = _number(mudaf)
        if number not in {"dual", "plural"} or case not in {"nominative", "oblique"}:
            return None
        return self._match(
            rule_id="SYNTAX_IDAFA_NUN_DROP",
            message="تحذف نون المثنى أو جمع المذكر السالم عند الإضافة.",
            token=mudaf,
            replacements=(corrected,),
            explanation=("نون المثنى وجمع المذكر السالم عوض عن التنوين؛ لذلك تحذف عند الإضافة."),
            confidence=relation.confidence * 0.96,
            priority=90,
            autofix=True,
        )

    def _check_preposition(self, parse: SentenceParse, relation: SyntacticRelation) -> Match | None:
        if relation.confidence < self.min_relation_confidence:
            return None
        noun = parse.tokens[relation.dependent_index]
        if (
            noun.analysis is None
            or _number(noun) not in {"dual", "plural"}
            or _visible_case(noun) != "nominative"
        ):
            return None
        replacement = _oblique_surface(_surface(noun.text))
        if replacement is None:
            return None
        return self._match(
            rule_id="SYNTAX_PREPOSITION_CASE",
            message="الاسم بعد حرف الجر يحتاج صيغة الجر الظاهرة.",
            token=noun,
            replacements=(replacement,),
            explanation=(
                "يجر حرف الجر الاسم بعده؛ وتظهر علامة الجر بالياء في المثنى وجمع المذكر السالم."
            ),
            confidence=relation.confidence * 0.98,
            priority=92,
            autofix=True,
        )

    def _check_governed_verb(
        self, parse: SentenceParse, relation: SyntacticRelation
    ) -> Match | None:
        if relation.confidence < self.min_relation_confidence:
            return None
        verb = parse.tokens[relation.dependent_index]
        if verb.analysis is None or _aspect(verb) != "imperfect":
            return None
        replacement = _governed_five_verb(_surface(verb.text))
        if replacement is None:
            return None
        if relation.relation == RelationType.SUBJUNCTIVE_VERB:
            rule_id = "SYNTAX_SUBJUNCTIVE_FIVE_VERBS"
            message = "الفعل المضارع المنصوب من الأفعال الخمسة يحذف منه حرف النون."
            mood = "النصب"
        else:
            rule_id = "SYNTAX_JUSSIVE_FIVE_VERBS"
            message = "الفعل المضارع المجزوم من الأفعال الخمسة يحذف منه حرف النون."
            mood = "الجزم"
        return self._match(
            rule_id=rule_id,
            message=message,
            token=verb,
            replacements=(replacement,),
            explanation=f"علامة {mood} في الأفعال الخمسة هي حذف النون.",
            confidence=relation.confidence * 0.99,
            priority=93,
            autofix=True,
        )

    def check_parse(self, parse: SentenceParse) -> list[Match]:
        """Produce grammar matches from one already-built sentence parse."""

        out: list[Match] = []
        for relation in parse.relations:
            match: Match | None = None
            if relation.relation == RelationType.DEMONSTRATIVE:
                match = self._check_demonstrative(parse, relation)
            elif relation.relation == RelationType.NAAT:
                match = self._check_naat(parse, relation)
            elif relation.relation == RelationType.SUBJECT:
                match = self._check_subject(parse, relation)
            elif relation.relation == RelationType.IDAFA:
                match = self._check_idafa(parse, relation)
            elif relation.relation == RelationType.PREPOSITION_OBJECT:
                match = self._check_preposition(parse, relation)
            elif relation.relation in {
                RelationType.SUBJUNCTIVE_VERB,
                RelationType.JUSSIVE_VERB,
            }:
                match = self._check_governed_verb(parse, relation)
            if match is not None:
                out.append(match)
        return out

    def check_text(self, text: str) -> list[Match]:
        """Parse and check a document, returning source-anchored matches."""

        out: list[Match] = []
        for sentence in self.parse(text).sentences:
            out.extend(self.check_parse(sentence))
        return out

    def cache_info(self):
        """Expose parser cache statistics for performance regression tests."""

        return self._parse_sentence_cached.cache_info()


@lru_cache(maxsize=1)
def default_syntax_engine() -> SyntaxEngine:
    """Return the process-wide syntax engine sharing the default morphology."""

    return SyntaxEngine(default_analyzer())
