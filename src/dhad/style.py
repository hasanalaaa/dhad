"""Explainable Arabic clarity, style, and tone analysis.

The Phase-5 engine treats style as preference-bearing evidence, not as a hard
linguistic error.  Every emitted :class:`~dhad.match.Match` is therefore in the
``style`` category, carries explicit provenance tags, and has ``autofix=False``.
Mechanical spelling and grammar remain owned by the earlier deterministic
layers.

The engine combines three sources of evidence:

* a schema-validated phrase resource for auditable redundancy, wordiness,
  cliché, archaic, and awkward-phrasing diagnostics;
* morphology-aware light-verb/nominalization rewrites;
* document-level readability and tone signals derived from the Phase-4 parse.

No probabilistic model or network service is required.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator

from .match import Match, dedupe
from .morphology import MorphologicalAnalyzer, default_analyzer
from .syntax import DocumentParse, SentenceParse, SyntaxEngine, SyntaxToken, default_syntax_engine
from .text import AR_DIACRITIC, B_LEFT, B_RIGHT, NormalizationMode, normalize, tokenize

if TYPE_CHECKING:
    from .analysis import AnalysisContext

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_STYLE_RESOURCE_PATH = DATA_DIR / "style_lexicon.json"
STYLE_RESOURCE_SCHEMA_PATH = DATA_DIR / "style_lexicon.schema.json"

_CONTENT_POS = frozenset({"noun", "proper_noun", "verbal_noun", "adjective", "verb"})
_CONNECTIVES = frozenset(
    {
        "و",
        "ف",
        "ثم",
        "لكن",
        "غير",
        "لذلك",
        "لأن",
        "إذ",
        "حيث",
        "بينما",
        "عندما",
        "كما",
        "بل",
    }
)


class StyleProfile(str, Enum):
    """Audience/register profiles used to suppress unsuitable preferences."""

    GENERAL = "general"
    ACADEMIC = "academic"
    ADMINISTRATIVE = "administrative"
    JOURNALISTIC = "journalistic"
    EDUCATIONAL = "educational"
    FRIENDLY = "friendly"
    LITERARY = "literary"


class PhraseKind(str, Enum):
    """Auditable classes of phrase-level style findings."""

    REDUNDANCY = "redundancy"
    WORDINESS = "wordiness"
    CLICHE = "cliche"
    ARCHAIC = "archaic"
    AWKWARD = "awkward"


class ToneLabel(str, Enum):
    """Interpretable tone dimensions rather than mutually exclusive genres."""

    FORMAL = "formal"
    OBJECTIVE = "objective"
    ASSERTIVE = "assertive"
    PERSUASIVE = "persuasive"
    CONVERSATIONAL = "conversational"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class PhraseRule:
    """One compiled phrase preference from the packaged style resource."""

    id: str
    kind: PhraseKind
    pattern: str
    compiled: re.Pattern[str]
    replacements: tuple[str, ...]
    message: str
    explanation: str
    confidence: float
    profiles: frozenset[StyleProfile]


@dataclass(frozen=True, slots=True)
class TonePattern:
    """One lexical tone signal with a stable explanation."""

    tone: ToneLabel
    pattern: str
    compiled: re.Pattern[str]
    weight: float
    reason: str


@dataclass(frozen=True, slots=True)
class ToneEvidence:
    """A source-anchored reason contributing to tone classification."""

    tone: ToneLabel
    text: str
    offset: int
    length: int
    weight: float
    reason: str

    def __post_init__(self) -> None:
        if self.offset < 0 or self.length <= 0:
            raise ValueError("Tone evidence span must be positive and ordered")
        if self.weight <= 0:
            raise ValueError("Tone evidence weight must be positive")


@dataclass(frozen=True, slots=True)
class ToneAnalysis:
    """Document or sentence tone scores with explainable evidence."""

    primary: ToneLabel
    confidence: float
    scores: tuple[tuple[ToneLabel, float], ...]
    evidence: tuple[ToneEvidence, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Tone confidence must be between 0 and 1")
        total = sum(score for _, score in self.scores)
        if self.scores and not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError("Tone scores must sum to one")

    def score(self, label: ToneLabel | str) -> float:
        """Return one normalized tone score."""

        requested = ToneLabel(label)
        return dict(self.scores).get(requested, 0.0)


@dataclass(frozen=True, slots=True)
class ReadabilityMetrics:
    """Transparent Dhad clarity indicators; not a claimed universal formula."""

    words: int
    sentences: int
    average_words_per_sentence: float
    average_characters_per_word: float
    long_word_ratio: float
    lexical_density: float
    nominalization_ratio: float
    repeated_word_ratio: float
    clarity_score: float
    band: str

    def __post_init__(self) -> None:
        if self.words < 0 or self.sentences < 0:
            raise ValueError("Readability counts cannot be negative")
        for value in (
            self.long_word_ratio,
            self.lexical_density,
            self.nominalization_ratio,
            self.repeated_word_ratio,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("Readability ratios must be between zero and one")
        if not 0.0 <= self.clarity_score <= 100.0:
            raise ValueError("Clarity score must be between zero and one hundred")


@dataclass(frozen=True, slots=True)
class StyleReport:
    """Complete non-mutating style analysis for one document."""

    text: str
    profile: StyleProfile
    matches: tuple[Match, ...]
    tone: ToneAnalysis
    sentence_tones: tuple[ToneAnalysis, ...]
    readability: ReadabilityMetrics


@dataclass(frozen=True, slots=True)
class _StyleResource:
    version: str
    phrases: tuple[PhraseRule, ...]
    tone_patterns: tuple[TonePattern, ...]
    nominalization_rewrites: Mapping[str, Mapping[str, str]]


def _validate_resource(payload: Mapping[str, Any]) -> None:
    schema = json.loads(STYLE_RESOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path)
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors
        )
        raise ValueError(f"Style resource schema validation failed: {details}")


def _literal_pattern(value: str) -> re.Pattern[str]:
    """Compile an Arabic literal with flexible whitespace and optional tashkeel."""

    words = value.split()
    if not words:
        raise ValueError("Style phrase pattern cannot be empty")
    diacritics = rf"[{AR_DIACRITIC}]*"
    rendered: list[str] = []
    for word in words:
        rendered.append("".join(re.escape(char) + diacritics for char in word))
    leading_conjunction = r"(?P<leading_conjunction>[وف])?"
    return re.compile(B_LEFT + leading_conjunction + r"\s+".join(rendered) + B_RIGHT)


@lru_cache(maxsize=4)
def load_style_resource(path: Path | str = DEFAULT_STYLE_RESOURCE_PATH) -> _StyleResource:
    """Load, validate, and compile the immutable packaged style knowledge base."""

    resource_path = Path(path)
    payload = json.loads(resource_path.read_text(encoding="utf-8"))
    _validate_resource(payload)
    phrases = tuple(
        PhraseRule(
            id=str(item["id"]),
            kind=PhraseKind(item["kind"]),
            pattern=str(item["pattern"]),
            compiled=_literal_pattern(str(item["pattern"])),
            replacements=tuple(str(value) for value in item["replacements"]),
            message=str(item["message"]),
            explanation=str(item["explanation"]),
            confidence=float(item["confidence"]),
            profiles=frozenset(StyleProfile(value) for value in item["profiles"]),
        )
        for item in payload["phrases"]
    )
    if len({item.id for item in phrases}) != len(phrases):
        raise ValueError("Style resource contains duplicate phrase rule ids")
    tone_patterns = tuple(
        TonePattern(
            tone=ToneLabel(item["tone"]),
            pattern=str(item["pattern"]),
            compiled=_literal_pattern(str(item["pattern"])),
            weight=float(item["weight"]),
            reason=str(item["reason"]),
        )
        for item in payload["tone_signals"]
    )
    rewrites = {
        normalize(str(lemma), NormalizationMode.LOOKUP): {
            str(key): str(value) for key, value in forms.items()
        }
        for lemma, forms in payload["nominalization_rewrites"].items()
    }
    return _StyleResource(str(payload["version"]), phrases, tone_patterns, rewrites)


def _surface(value: str) -> str:
    return normalize(value, NormalizationMode.LOOKUP)


def _arabic_tokens(text: str):
    return [token for token in tokenize(text) if token.is_arabic]


def _is_preposition_prefixed(token: SyntaxToken) -> bool:
    surface = _surface(token.text)
    if surface.startswith(("ب", "ل")) and len(surface) > 2:
        return True
    return bool(
        token.analysis
        and any(segment.feature == "preposition" for segment in token.analysis.prefixes)
    )


def _has_conjunction(token: SyntaxToken) -> bool:
    if token.analysis is not None and any(
        segment.feature == "conjunction" for segment in token.analysis.prefixes
    ):
        return True
    surface = _surface(token.text)
    return len(surface) > 2 and surface[0] in "وف"


def _leading_conjunction(token: SyntaxToken) -> str:
    if token.analysis is not None:
        value = "".join(
            segment.surface
            for segment in token.analysis.prefixes
            if segment.feature == "conjunction"
        )
        if value:
            return value
    surface = _surface(token.text)
    if len(surface) > 2 and surface[0] in "وف" and surface[1:] in {"قام", "قامت", "قاموا"}:
        return surface[0]
    return ""


def _auxiliary_form(token: SyntaxToken) -> str | None:
    surface = _surface(token.text)
    if surface.startswith(("و", "ف")) and surface[1:] in {"قام", "قامت", "قاموا"}:
        surface = surface[1:]
    if surface in {"قام", "قامت", "قاموا"}:
        return surface
    return None


def _replacement_person(auxiliary: str) -> str:
    if auxiliary == "قامت":
        return "feminine"
    if auxiliary == "قاموا":
        return "plural"
    return "masculine"


class ToneClassifier:
    """Deterministic, evidence-bearing Arabic tone classifier."""

    def __init__(self, resource: _StyleResource | None = None):
        self.resource = resource or load_style_resource()

    @staticmethod
    def _add_structural_evidence(
        text: str,
        parse: DocumentParse,
        raw_scores: dict[ToneLabel, float],
        evidence: list[ToneEvidence],
    ) -> None:
        syntax_tokens = [token for sentence in parse.sentences for token in sentence.tokens]
        if not syntax_tokens:
            return
        nominal = sum(
            token.pos in {"noun", "proper_noun", "verbal_noun"} for token in syntax_tokens
        )
        verbs = sum(token.pos == "verb" for token in syntax_tokens)
        if nominal >= 5 and nominal >= verbs * 2:
            raw_scores[ToneLabel.FORMAL] += 0.45
            raw_scores[ToneLabel.OBJECTIVE] += 0.30
        if any(char in text for char in "%٪") or any(
            token.kind.value == "number" for token in tokenize(text)
        ):
            raw_scores[ToneLabel.OBJECTIVE] += 0.50
        exclamation = text.count("!")
        if exclamation:
            weight = min(0.75, exclamation * 0.25)
            raw_scores[ToneLabel.ASSERTIVE] += weight
            raw_scores[ToneLabel.PERSUASIVE] += weight * 0.5
        first_person = 0
        second_person = 0
        for token in syntax_tokens:
            person = token.feature("person")
            if person and person.startswith("1"):
                first_person += 1
            elif person and person.startswith("2"):
                second_person += 1
        if first_person:
            raw_scores[ToneLabel.CONVERSATIONAL] += min(0.6, first_person * 0.15)
        if second_person:
            raw_scores[ToneLabel.PERSUASIVE] += min(0.5, second_person * 0.12)
        if not evidence and nominal == 0 and verbs == 0:
            raw_scores[ToneLabel.NEUTRAL] += 0.4

    def classify(self, text: str, parse: DocumentParse | None = None) -> ToneAnalysis:
        """Classify text while retaining every lexical reason and source offset."""

        if parse is None:
            parse = default_syntax_engine().parse(text)
        raw_scores = {label: 0.18 for label in ToneLabel}
        raw_scores[ToneLabel.NEUTRAL] = 1.0
        evidence: list[ToneEvidence] = []
        for signal in self.resource.tone_patterns:
            for match in signal.compiled.finditer(text):
                raw_scores[signal.tone] += signal.weight
                evidence.append(
                    ToneEvidence(
                        signal.tone,
                        match.group(),
                        match.start(),
                        match.end() - match.start(),
                        signal.weight,
                        signal.reason,
                    )
                )
        self._add_structural_evidence(text, parse, raw_scores, evidence)
        total = sum(raw_scores.values())
        scores = tuple(
            sorted(
                ((label, value / total) for label, value in raw_scores.items()),
                key=lambda item: (-item[1], item[0].value),
            )
        )
        primary, primary_score = scores[0]
        second_score = scores[1][1] if len(scores) > 1 else 0.0
        confidence = min(0.999, max(0.0, primary_score + (primary_score - second_score) * 0.5))
        return ToneAnalysis(primary, confidence, scores, tuple(evidence))


class StyleEngine:
    """Morphology- and syntax-aware style checker with opt-in rewrites only."""

    def __init__(
        self,
        morphology: MorphologicalAnalyzer | None = None,
        syntax: SyntaxEngine | None = None,
        *,
        profile: StyleProfile | str = StyleProfile.GENERAL,
        resource_path: Path | str = DEFAULT_STYLE_RESOURCE_PATH,
    ):
        self.morphology = morphology or default_analyzer()
        if syntax is not None:
            self.syntax = syntax
        elif morphology is None:
            self.syntax = default_syntax_engine()
        else:
            self.syntax = SyntaxEngine(self.morphology)
        self.profile = StyleProfile(profile)
        self.resource = load_style_resource(resource_path)
        self.tone_classifier = ToneClassifier(self.resource)

    @staticmethod
    def _style_match(
        *,
        rule_id: str,
        message: str,
        offset: int,
        length: int,
        replacements: Iterable[str] = (),
        explanation: str,
        confidence: float,
        severity: str = "hint",
        priority: int = 25,
        tags: Iterable[str] = (),
    ) -> Match:
        """Build a categorically subjective match that can never safe-autofix."""

        return Match(
            rule_id=rule_id,
            category="style",
            message=message,
            offset=offset,
            length=length,
            replacements=list(dict.fromkeys(replacements)),
            severity=severity,
            explanation=explanation,
            autofix=False,
            confidence=max(0.0, min(0.999, confidence)),
            priority=priority,
            tags=tuple(dict.fromkeys(("style", "requires-approval", *tags))),
            references=("Dhad deterministic style engine v1",),
            profiles=("default",),
        )

    def _phrase_matches(self, text: str) -> list[Match]:
        out: list[Match] = []
        for rule in self.resource.phrases:
            if self.profile not in rule.profiles:
                continue
            for found in rule.compiled.finditer(text):
                out.append(
                    self._style_match(
                        rule_id=rule.id,
                        message=rule.message,
                        offset=found.start(),
                        length=found.end() - found.start(),
                        replacements=(
                            tuple(
                                (found.groupdict().get("leading_conjunction") or "") + value
                                for value in rule.replacements
                            )
                        ),
                        explanation=rule.explanation,
                        confidence=rule.confidence,
                        severity="warning" if rule.kind == PhraseKind.AWKWARD else "hint",
                        priority=34 if rule.kind == PhraseKind.REDUNDANCY else 28,
                        tags=(rule.kind.value, "phrase-resource"),
                    )
                )
        return out

    def _nominalization_matches(self, parsed: DocumentParse) -> list[Match]:
        out: list[Match] = []
        for sentence in parsed.sentences:
            for left, right in zip(sentence.tokens, sentence.tokens[1:]):
                if right.break_before or left.end > right.start:
                    continue
                auxiliary = _auxiliary_form(left)
                if auxiliary is None or right.analysis is None:
                    continue
                lemma_candidates = []
                if right.pos == "verbal_noun":
                    lemma_candidates.append(_surface(right.analysis.lemma))
                surface = _surface(right.text)
                for prefix in ("بال", "ب", "لل", "ل"):
                    if surface.startswith(prefix) and len(surface) > len(prefix) + 1:
                        lemma_candidates.append(surface[len(prefix) :])
                        break
                lemma = next(
                    (
                        candidate
                        for candidate in lemma_candidates
                        if candidate in self.resource.nominalization_rewrites
                    ),
                    None,
                )
                if lemma is None or not _is_preposition_prefixed(right):
                    continue
                forms = self.resource.nominalization_rewrites[lemma]
                person = _replacement_person(auxiliary)
                replacement = _leading_conjunction(left) + forms[person]
                analyses = self.morphology.analyze(replacement, min_confidence=0.40)
                if not any(item.pos == "verb" for item in analyses):
                    continue
                out.append(
                    self._style_match(
                        rule_id="STYLE_LIGHT_VERB_NOMINALIZATION",
                        message="يمكن استبدال الفعل الخفيف والمصدر بفعل مباشر.",
                        offset=left.start,
                        length=right.end - left.start,
                        replacements=(replacement,),
                        explanation=(
                            "الصياغة بالفعل المباشر أقصر وأكثر حركة. اختيرت صيغة الفعل "
                            "وفق علامة التأنيث أو الجمع الظاهرة في «قام» ومشتقاتها، ثم "
                            "تحقق المحلل الصرفي من صلاحية الصيغة المقترحة."
                        ),
                        confidence=min(left.confidence or 0.85, right.confidence) * 0.90,
                        severity="hint",
                        priority=31,
                        tags=("wordiness", "morphology-aware", "nominalization"),
                    )
                )
        return out

    @staticmethod
    def _sentence_density_match(sentence: SentenceParse) -> Match | None:
        words = list(sentence.tokens)
        if len(words) < 24:
            return None
        verbal_nouns = sum(token.pos == "verbal_noun" for token in words)
        verbs = sum(token.pos == "verb" for token in words)
        connectives = sum(
            _surface(token.text) in _CONNECTIVES or _has_conjunction(token) for token in words
        )
        if verbal_nouns < 4 or verbal_nouns <= verbs * 2 or connectives < 2:
            return None
        first = words[0]
        length = min(48, sentence.end - first.start)
        return StyleEngine._style_match(
            rule_id="STYLE_NOMINALIZATION_DENSITY",
            message="تراكم المصادر والروابط يجعل الجملة كثيفة.",
            offset=first.start,
            length=length,
            explanation=(
                "رُصدت أربعة مصادر أو أكثر مع أفعال قليلة وروابط متعددة. جرّب تحويل "
                "بعض المصادر إلى أفعال وتقسيم الجملة، مع مراجعة المعنى يدويًا."
            ),
            confidence=min(0.90, 0.68 + verbal_nouns * 0.025 + connectives * 0.015),
            severity="hint",
            priority=18,
            tags=("clarity", "sentence-density", "syntax-aware"),
        )

    def _density_matches(self, parsed: DocumentParse) -> list[Match]:
        return [
            match
            for sentence in parsed.sentences
            if (match := self._sentence_density_match(sentence)) is not None
        ]

    def _tone_shift_matches(
        self,
        parsed: DocumentParse,
        document_tone: ToneAnalysis,
        sentence_tones: Sequence[ToneAnalysis],
    ) -> list[Match]:
        if len(parsed.sentences) < 3 or document_tone.primary not in {
            ToneLabel.FORMAL,
            ToneLabel.OBJECTIVE,
        }:
            return []
        dominant = sum(
            tone.primary == document_tone.primary and tone.confidence >= 0.38
            for tone in sentence_tones
        )
        if dominant < max(2, math.ceil(len(sentence_tones) * 0.60)):
            return []
        out: list[Match] = []
        for sentence, tone in zip(parsed.sentences, sentence_tones):
            if tone.primary != ToneLabel.CONVERSATIONAL or tone.confidence < 0.48:
                continue
            if not any(item.tone == ToneLabel.CONVERSATIONAL for item in tone.evidence):
                continue
            lead = len(sentence.text) - len(sentence.text.lstrip())
            offset = sentence.start + lead
            length = min(48, max(1, sentence.end - offset))
            out.append(
                self._style_match(
                    rule_id="STYLE_TONE_SHIFT",
                    message="تتحول هذه الجملة إلى نبرة محادثية داخل نص يغلب عليه طابع رسمي أو موضوعي.",
                    offset=offset,
                    length=length,
                    explanation=(
                        "هذا تنبيه اتساق لا خطأ لغوي. أبقِ التحول إن كان مقصودًا، أو "
                        "أعد صياغة النداء والرأي الشخصي ليتوافق مع نبرة المستند."
                    ),
                    confidence=min(document_tone.confidence, tone.confidence) * 0.90,
                    severity="hint",
                    priority=15,
                    tags=("tone", "document-consistency"),
                )
            )
        return out

    @staticmethod
    def _readability(text: str, parsed: DocumentParse) -> ReadabilityMetrics:
        words = _arabic_tokens(text)
        word_count = len(words)
        sentence_count = len(parsed.sentences)
        if word_count == 0:
            return ReadabilityMetrics(
                0, sentence_count, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 100.0, "clear"
            )
        normalized_words = [_surface(token.text) for token in words]
        average_words = word_count / max(1, sentence_count)
        average_chars = sum(len(value) for value in normalized_words) / word_count
        long_ratio = sum(len(value) >= 8 for value in normalized_words) / word_count
        syntax_tokens = [token for sentence in parsed.sentences for token in sentence.tokens]
        content = sum(token.pos in _CONTENT_POS for token in syntax_tokens)
        nominalizations = sum(token.pos == "verbal_noun" for token in syntax_tokens)
        lexical_density = content / max(1, len(syntax_tokens))
        nominalization_ratio = nominalizations / max(1, len(syntax_tokens))
        repeated = sum(a == b for a, b in zip(normalized_words, normalized_words[1:]))
        repeated_ratio = repeated / max(1, word_count - 1)
        # Dhad Clarity Index v1: a transparent engineering diagnostic.  It is
        # intentionally documented as an internal comparative score, not a
        # validated universal readability law for Arabic.
        penalty = (
            max(0.0, average_words - 14.0) * 1.35
            + max(0.0, average_chars - 5.5) * 4.0
            + long_ratio * 22.0
            + nominalization_ratio * 18.0
            + repeated_ratio * 35.0
        )
        score = max(0.0, min(100.0, 100.0 - penalty))
        if score >= 82:
            band = "clear"
        elif score >= 65:
            band = "moderate"
        elif score >= 45:
            band = "dense"
        else:
            band = "very_dense"
        return ReadabilityMetrics(
            word_count,
            sentence_count,
            average_words,
            average_chars,
            long_ratio,
            lexical_density,
            nominalization_ratio,
            repeated_ratio,
            score,
            band,
        )

    def analyze(self, text: str, parsed: DocumentParse | None = None) -> StyleReport:
        """Return matches, tone, sentence tones, and readability without mutation."""

        parsed = parsed or self.syntax.parse(text)
        document_tone = self.tone_classifier.classify(text, parsed)
        sentence_tones = tuple(
            self.tone_classifier.classify(
                text[sentence.start : sentence.end],
                DocumentParse(
                    text[sentence.start : sentence.end],
                    (
                        SentenceParse(
                            sentence.text,
                            0,
                            len(sentence.text),
                            tuple(
                                SyntaxToken(
                                    token.text,
                                    token.start - sentence.start,
                                    token.end - sentence.start,
                                    token.analysis,
                                    token.alternatives,
                                    token.confidence,
                                    token.break_before,
                                )
                                for token in sentence.tokens
                            ),
                            sentence.relations,
                            sentence.irab,
                            sentence.confidence,
                        ),
                    ),
                ),
            )
            for sentence in parsed.sentences
        )
        matches = self._phrase_matches(text)
        matches.extend(self._nominalization_matches(parsed))
        matches.extend(self._density_matches(parsed))
        matches.extend(self._tone_shift_matches(parsed, document_tone, sentence_tones))
        return StyleReport(
            text,
            self.profile,
            tuple(dedupe(matches)),
            document_tone,
            sentence_tones,
            self._readability(text, parsed),
        )

    def check_text(
        self,
        text: str,
        parsed: DocumentParse | None = None,
        *,
        context: AnalysisContext | None = None,
    ) -> list[Match]:
        """Return subjective matches without computing full reporting metrics.

        The core pipeline can pass its existing syntax parse, avoiding duplicate
        morphology and sentence work. Tone classification is only invoked for
        multi-sentence documents where a consistency diagnostic is possible.
        """

        if context is not None:
            if context.text != text:
                raise ValueError("Analysis context does not correspond to the supplied text")
            parsed = parsed or context.parsed
        document = parsed or self.syntax.parse(text)
        matches = self._phrase_matches(text)
        matches.extend(self._nominalization_matches(document))
        matches.extend(self._density_matches(document))
        if len(document.sentences) >= 3:
            document_tone = self.tone_classifier.classify(text, document)
            sentence_tones = tuple(
                self.tone_classifier.classify(sentence.text) for sentence in document.sentences
            )
            matches.extend(self._tone_shift_matches(document, document_tone, sentence_tones))
        return dedupe(matches)

    def classify_tone(self, text: str) -> ToneAnalysis:
        """Public convenience API for tone-only analysis."""

        parsed = self.syntax.parse(text)
        return self.tone_classifier.classify(text, parsed)


@lru_cache(maxsize=8)
def default_style_engine(profile: StyleProfile | str = StyleProfile.GENERAL) -> StyleEngine:
    """Return a shared deterministic engine for one style profile."""

    return StyleEngine(profile=StyleProfile(profile))
