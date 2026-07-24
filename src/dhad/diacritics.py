"""Explainable Arabic diacritization over Dhad morphology and candidate syntax.

The engine never guesses silently.  It synthesizes a core vocalization from the
selected morphological reading, then applies an independently traceable case or
mood ending from :class:`dhad.syntax.IrabCandidate`.  Every token carries a
confidence and provenance so callers can decide how much generated tashkeel to
show.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Mapping, Sequence

from .match import Match
from .morphology import MorphologicalAnalysis, MorphologicalAnalyzer, default_analyzer
from .syntax import DocumentParse, IrabCandidate, SyntaxEngine, SyntaxToken, default_syntax_engine
from .text import NormalizationMode, normalize

FATHA = "َ"
DAMMA = "ُ"
KASRA = "ِ"
SUKUN = "ْ"
SHADDA = "ّ"
TANWEEN_FATH = "ً"
TANWEEN_DAMM = "ٌ"
TANWEEN_KASR = "ٍ"

_DIACRITICS = frozenset("ًٌٍَُِّْٰ")


class DiacritizationMode(str, Enum):
    """Supported output levels."""

    FULL = "full"
    ENDINGS = "endings"
    CORE = "core"


@dataclass(frozen=True, slots=True)
class DiacritizedToken:
    """One source token and its generated vocalization."""

    source: str
    output: str
    start: int
    end: int
    mode: DiacritizationMode
    confidence: float
    core_confidence: float
    ending_confidence: float
    lemma: str | None
    role: str
    case_or_mood: str
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Diacritized token span must be positive and ordered")
        for value in (self.confidence, self.core_confidence, self.ending_confidence):
            if not 0.0 <= value <= 1.0:
                raise ValueError("Diacritization confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class DiacritizationResult:
    """A complete, offset-preserving diacritization result."""

    source_text: str
    text: str
    mode: DiacritizationMode
    tokens: tuple[DiacritizedToken, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Result confidence must be between 0 and 1")


# Closed-class words and frequent lexical items where the consonantal skeleton
# alone is insufficient to recover vowels.  These are deterministic linguistic
# data, not model predictions.
_EXACT_VOCALIZATIONS: Mapping[tuple[str, str], str] = {
    ("هذا", "pronoun"): "هَذَا",
    ("هذه", "pronoun"): "هَذِهِ",
    ("هؤلاء", "pronoun"): "هَؤُلَاءِ",
    ("ذلك", "pronoun"): "ذَلِكَ",
    ("تلك", "pronoun"): "تِلْكَ",
    ("في", "particle"): "فِي",
    ("من", "particle"): "مِنْ",
    ("إلى", "particle"): "إِلَى",
    ("على", "particle"): "عَلَى",
    ("عن", "particle"): "عَنْ",
    ("أن", "particle"): "أَنْ",
    ("إن", "particle"): "إِنَّ",
    ("لن", "particle"): "لَنْ",
    ("لم", "particle"): "لَمْ",
    ("لا", "particle"): "لَا",
    ("ثم", "particle"): "ثُمَّ",
    ("أو", "particle"): "أَوْ",
    ("أنا", "pronoun"): "أَنَا",
    ("أنت", "pronoun"): "أَنْتَ",
    ("نحن", "pronoun"): "نَحْنُ",
    ("هو", "pronoun"): "هُوَ",
    ("هي", "pronoun"): "هِيَ",
    ("كتب", "verb"): "كَتَبَ",
    ("كتب", "noun"): "كُتُب",
    ("كتاب", "noun"): "كِتَاب",
    ("كاتب", "noun"): "كَاتِب",
    ("طالب", "noun"): "طَالِب",
    ("طلاب", "noun"): "طُلَّاب",
    ("درس", "noun"): "دَرْس",
    ("ذهب", "verb"): "ذَهَبَ",
    ("قال", "verb"): "قَالَ",
    ("عاد", "verb"): "عَادَ",
    ("مدرسة", "noun"): "مَدْرَسَة",
    ("مفيد", "adjective"): "مُفِيد",
    ("مفيدة", "adjective"): "مُفِيدَة",
    ("ثلاث", "noun"): "ثَلَاث",
    ("ثلاثة", "noun"): "ثَلَاثَة",
    ("مسؤول", "noun"): "مَسْؤُول",
    ("علم", "noun"): "عِلْم",
    ("عالم", "noun"): "عَالِم",
    ("لغة", "noun"): "لُغَة",
    ("عربية", "adjective"): "عَرَبِيَّة",
    ("بيت", "noun"): "بَيْت",
    ("كبير", "adjective"): "كَبِير",
}

# Imperfect stems exclude the person prefix.  They are only used when morphology
# explicitly marks an imperfect/future reading.
_IMPERFECT_STEMS: Mapping[str, str] = {
    "كتب": "كْتُب",
    "ذهب": "ذْهَب",
    "لعب": "لْعَب",
    "عمل": "عْمَل",
    "قرأ": "قْرَأ",
    "درس": "دْرُس",
    "استخدم": "سْتَخْدِم",
    "استمر": "سْتَمِرّ",
    "اكتمل": "كْتَمِل",
    "أعلن": "عْلِن",
}

_PATTERN_VOCALIZATIONS: Mapping[str, Mapping[str, str] | str] = {
    "فعل": {"verb": "فَعَلَ", "noun": "فِعْل", "default": "فَعْل"},
    "فاعل": "فَاعِل",
    "فعال": {"noun": "فِعَال", "default": "فَعَال"},
    "فعيل": "فَعِيل",
    "فعالة": "فَعَالَة",
    "فعيلة": "فَعِيلَة",
    "مفعل": {"adjective": "مُفْعِل", "default": "مَفْعَل"},
    "مفعلة": "مَفْعَلَة",
    "مفعول": "مَفْعُول",
    "مفعال": "مِفْعَال",
    "تفعيل": "تَفْعِيل",
    "افتعال": "اِفْتِعَال",
    "استفعال": "اِسْتِفْعَال",
    "انفعال": "اِنْفِعَال",
    "مفاعلة": "مُفَاعَلَة",
    "استفعل": "اِسْتَفْعَلَ",
    "افتعل": "اِفْتَعَلَ",
    "انفعل": "اِنْفَعَلَ",
    "تفاعل": "تَفَاعَلَ",
    "تفعل": "تَفَعَّلَ",
    "أفعل": "أَفْعَلَ",
    "فعلل": "فَعْلَلَ",
}

_PREFIX_VOCALIZATION: Mapping[str, str] = {
    "و": "وَ",
    "ف": "فَ",
    "ب": "بِ",
    "ك": "كَ",
    "ل": "لِ",
    "س": "سَ",
    "ال": "الْ",
}

_SUFFIX_VOCALIZATION: Mapping[str, str] = {
    "ها": "هَا",
    "هم": "هُمْ",
    "هن": "هُنَّ",
    "نا": "نَا",
    "ه": "هُ",
    "ك": "كَ",
    "ي": "ي",
    "ون": "ونَ",
    "ين": "ينَ",
    "ان": "انِ",
    "ات": "ات",
}


def _without_marks(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFC", value) if char not in _DIACRITICS)


def _append_mark(value: str, mark: str) -> str:
    """Replace a final short-vowel/sukun mark without disturbing shadda."""

    if not value or not mark:
        return value
    while value and value[-1] in {
        FATHA,
        DAMMA,
        KASRA,
        SUKUN,
        TANWEEN_FATH,
        TANWEEN_DAMM,
        TANWEEN_KASR,
    }:
        value = value[:-1]
    return value + mark


def _render_pattern(surface: str, vocalized_template: str) -> str | None:
    """Project a vocalized template onto an equally-sized surface skeleton."""

    skeleton = _without_marks(vocalized_template)
    if len(skeleton) != len(surface):
        return None
    output: list[str] = []
    source_index = 0
    for char in vocalized_template:
        if char in _DIACRITICS:
            output.append(char)
        else:
            output.append(surface[source_index])
            source_index += 1
    return "".join(output)


def _prefix_output(surface: str, feature: str) -> str:
    if feature == "imperfect_person":
        return surface + FATHA
    return _PREFIX_VOCALIZATION.get(surface, surface)


def _suffix_output(surface: str) -> str:
    return _SUFFIX_VOCALIZATION.get(surface, surface)


class DiacriticsEngine:
    """Synthesize Arabic harakat from selected morphology and candidate iʿrāb."""

    def __init__(
        self,
        morphology: MorphologicalAnalyzer | None = None,
        syntax: SyntaxEngine | None = None,
        *,
        min_core_confidence: float = 0.55,
        min_ending_confidence: float = 0.80,
    ) -> None:
        if not 0.0 <= min_core_confidence <= 1.0:
            raise ValueError("min_core_confidence must be between 0 and 1")
        if not 0.0 <= min_ending_confidence <= 1.0:
            raise ValueError("min_ending_confidence must be between 0 and 1")
        self.morphology = morphology or default_analyzer()
        self.syntax = syntax or SyntaxEngine(self.morphology)
        self.min_core_confidence = min_core_confidence
        self.min_ending_confidence = min_ending_confidence

    @staticmethod
    def _split_surface(
        token: SyntaxToken, analysis: MorphologicalAnalysis
    ) -> tuple[str, str, str, tuple[tuple[str, str], ...], tuple[str, ...]]:
        surface = normalize(token.text, NormalizationMode.LOOKUP)
        prefix_end = max((item.end for item in analysis.prefixes), default=0)
        suffix_start = min((item.start for item in analysis.suffixes), default=len(surface))
        prefix_segments = tuple((item.surface, item.feature) for item in analysis.prefixes)
        suffix_segments = tuple(item.surface for item in analysis.suffixes)
        return (
            surface[:prefix_end],
            surface[prefix_end:suffix_start],
            surface[suffix_start:],
            prefix_segments,
            suffix_segments,
        )

    def _core(self, token: SyntaxToken) -> tuple[str, float, tuple[str, ...]]:
        analysis = token.analysis
        raw = normalize(token.text, NormalizationMode.LOOKUP)
        if analysis is None:
            return raw, 0.0, ("no-morphology",)

        prefix_plain, core_plain, suffix_plain, prefixes, suffixes = self._split_surface(
            token, analysis
        )
        provenance: list[str] = []
        core_output: str | None = None
        core_confidence = 0.0

        aspect = analysis.feature("aspect")
        inferred_person_prefix = ""
        if (
            aspect in {"imperfect", "future"}
            and not prefixes
            and len(core_plain) > 1
            and core_plain[0] in {"أ", "ن", "ت", "ي"}
        ):
            inferred_person_prefix = core_plain[0] + FATHA
        if aspect in {"imperfect", "future"} and analysis.lemma in _IMPERFECT_STEMS:
            core_output = _IMPERFECT_STEMS[analysis.lemma]
            core_confidence = min(0.96, analysis.confidence)
            provenance.append("lexical-imperfect-stem")
        else:
            exact = _EXACT_VOCALIZATIONS.get((core_plain, analysis.pos))
            if exact is None and core_plain == analysis.lemma:
                exact = _EXACT_VOCALIZATIONS.get((analysis.lemma, analysis.pos))
            if exact is not None:
                core_output = exact
                core_confidence = min(0.98, analysis.confidence)
                provenance.append("exact-vocalization")

        if core_output is None and analysis.pattern:
            template_spec = _PATTERN_VOCALIZATIONS.get(analysis.pattern)
            if isinstance(template_spec, Mapping):
                template = template_spec.get(analysis.pos, template_spec.get("default"))
            else:
                template = template_spec
            if template:
                rendered = _render_pattern(core_plain, template)
                if rendered is not None:
                    core_output = rendered
                    core_confidence = min(0.82, analysis.confidence * 0.86)
                    provenance.append(f"pattern:{analysis.pattern}")

        if core_output is None:
            core_output = core_plain
            core_confidence = min(0.48, analysis.confidence * 0.55)
            provenance.append("consonantal-fallback")

        prefix_output = "".join(_prefix_output(surface, feature) for surface, feature in prefixes)
        if inferred_person_prefix:
            prefix_output = inferred_person_prefix
        elif not prefixes and prefix_plain:
            prefix_output = prefix_plain
        suffix_output = "".join(_suffix_output(surface) for surface in suffixes)
        if not suffixes and suffix_plain:
            suffix_output = suffix_plain
        return prefix_output + core_output + suffix_output, core_confidence, tuple(provenance)

    @staticmethod
    def _resolve_following_case(
        irab: Sequence[IrabCandidate], index: int, seen: frozenset[int] = frozenset()
    ) -> str | None:
        if index in seen or not 0 <= index < len(irab):
            return None
        candidate = irab[index]
        value = candidate.case_or_mood
        if value in {"nominative", "genitive", "subjunctive", "jussive"}:
            return value
        if value.startswith("يتبع") and candidate.governor_index is not None:
            return DiacriticsEngine._resolve_following_case(
                irab, candidate.governor_index, seen | {index}
            )
        return None

    def _ending(
        self,
        token: SyntaxToken,
        candidate: IrabCandidate,
        all_irab: Sequence[IrabCandidate],
    ) -> tuple[str, float, str]:
        case = self._resolve_following_case(all_irab, candidate.token_index)
        if case is None or candidate.confidence < self.min_ending_confidence:
            return "", 0.0, "no-confident-ending"

        surface = normalize(token.text, NormalizationMode.LOOKUP)
        analysis = token.analysis
        # Dual and sound masculine plural encode case in letters. Their final
        # nūn conventionally takes fatḥa/kasra independent of the syntactic case.
        if surface.endswith(("ون", "ين")):
            return FATHA, candidate.confidence, "visible-sound-plural-ending"
        if surface.endswith(("ان", "تان", "تين")):
            return KASRA, candidate.confidence, "visible-dual-ending"
        if analysis is not None and any(
            item.feature.startswith("pronoun_") for item in analysis.suffixes
        ):
            return "", 0.0, "attached-pronoun-blocks-case-ending"
        if surface.endswith(("ا", "ى", "ي", "و")) and case in {"nominative", "genitive"}:
            return "", candidate.confidence * 0.75, "estimated-ending"

        mark = {
            "nominative": DAMMA,
            "genitive": KASRA,
            "subjunctive": FATHA,
            "jussive": SUKUN,
        }[case]
        return mark, candidate.confidence, f"irab:{case}"

    def _token(
        self,
        token: SyntaxToken,
        irab: IrabCandidate,
        all_irab: Sequence[IrabCandidate],
        mode: DiacritizationMode,
    ) -> DiacritizedToken:
        core, core_confidence, provenance = self._core(token)
        ending, ending_confidence, ending_source = self._ending(token, irab, all_irab)
        source_plain = normalize(token.text, NormalizationMode.LOOKUP)

        if mode == DiacritizationMode.CORE:
            output = core if core_confidence >= self.min_core_confidence else source_plain
            confidence = core_confidence
            used = provenance
        elif mode == DiacritizationMode.ENDINGS:
            output = _append_mark(source_plain, ending) if ending else source_plain
            confidence = ending_confidence
            used = (ending_source,)
        else:
            base = core if core_confidence >= self.min_core_confidence else source_plain
            output = _append_mark(base, ending) if ending else base
            confidence_values = [
                value for value in (core_confidence, ending_confidence) if value > 0
            ]
            confidence = (
                sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
            )
            used = provenance + (ending_source,)

        return DiacritizedToken(
            source=token.text,
            output=unicodedata.normalize("NFC", output),
            start=token.start,
            end=token.end,
            mode=mode,
            confidence=max(0.0, min(1.0, confidence)),
            core_confidence=core_confidence,
            ending_confidence=ending_confidence,
            lemma=token.analysis.lemma if token.analysis is not None else None,
            role=irab.role,
            case_or_mood=irab.case_or_mood,
            provenance=used,
        )

    def diacritize(
        self,
        text: str,
        *,
        mode: DiacritizationMode | str = DiacritizationMode.FULL,
        parsed: DocumentParse | None = None,
    ) -> DiacritizationResult:
        """Return an explicit, non-mutating diacritization preview."""

        selected_mode = DiacritizationMode(mode)
        document = parsed or self.syntax.parse(text)
        if document.text != text:
            raise ValueError("Parsed document must belong to the same source text")

        generated: list[DiacritizedToken] = []
        for sentence in document.sentences:
            if len(sentence.tokens) != len(sentence.irab):
                raise ValueError("Every syntax token must have one i'rab candidate")
            generated.extend(
                self._token(token, sentence.irab[index], sentence.irab, selected_mode)
                for index, token in enumerate(sentence.tokens)
            )

        output = text
        for token in reversed(generated):
            output = output[: token.start] + token.output + output[token.end :]
        confidence = (
            sum(item.confidence for item in generated) / len(generated) if generated else 1.0
        )
        return DiacritizationResult(
            source_text=text,
            text=output,
            mode=selected_mode,
            tokens=tuple(generated),
            confidence=confidence,
        )

    def suggestions(
        self,
        text: str,
        *,
        mode: DiacritizationMode | str = DiacritizationMode.FULL,
        parsed: DocumentParse | None = None,
    ) -> tuple[Match, ...]:
        """Return opt-in per-token tashkeel suggestions for ``Dhad.check``."""

        result = self.diacritize(text, mode=mode, parsed=parsed)
        matches: list[Match] = []
        for token in result.tokens:
            if token.output == token.source or token.confidence < 0.55:
                continue
            matches.append(
                Match(
                    rule_id=f"DIACRITICS_{result.mode.value.upper()}",
                    category="diacritics",
                    message="تشكيل مقترح مبني على التحليل الصرفي والإعراب المرشح.",
                    offset=token.start,
                    length=token.end - token.start,
                    replacements=[token.output],
                    severity="hint",
                    explanation=(
                        f"الدور: {token.role}؛ الحالة: {token.case_or_mood}؛ "
                        f"المصدر: {', '.join(token.provenance)}."
                    ),
                    autofix=False,
                    confidence=token.confidence,
                    priority=12,
                    tags=("diacritization", result.mode.value, "requires-explicit-command"),
                    references=("Dhad morphology + candidate i'rab diacritization v1",),
                )
            )
        return tuple(matches)


@lru_cache(maxsize=1)
def default_diacritics_engine() -> DiacriticsEngine:
    """Return the shared default engine over the shared syntax stack."""

    morphology = default_analyzer()
    return DiacriticsEngine(morphology, default_syntax_engine())
