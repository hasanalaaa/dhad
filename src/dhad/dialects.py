"""Dialect identification and context-aware conversion to Modern Standard Arabic.

The engine is deliberately deterministic and evidence-bearing.  It identifies
Egyptian, Levantine, Gulf, Iraqi, and Maghrebi Arabic from a versioned resource,
then proposes MSA conversions without silently modifying user text.  Structural
conversions are validated through the Phase-3 morphology and Phase-4 syntax
engines before they are exposed to callers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from .match import Match, dedupe
from .morphology import MorphologicalAnalyzer, default_analyzer
from .spans import DisjointSpanIndex
from .syntax import DocumentParse, SyntaxEngine, default_syntax_engine
from .text import NormalizationMode, Token, TokenKind, iter_tokens, normalize

if TYPE_CHECKING:
    from .analysis import AnalysisContext

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_DIALECT_RESOURCE_PATH = DATA_DIR / "dialects.json"
DIALECT_RESOURCE_SCHEMA_PATH = DATA_DIR / "dialects.schema.json"


class DialectLabel(str, Enum):
    """Dialect labels supported by the deterministic classifier."""

    MSA = "msa"
    EGYPTIAN = "egyptian"
    LEVANTINE = "levantine"
    GULF = "gulf"
    IRAQI = "iraqi"
    MAGHREBI = "maghrebi"
    MIXED = "mixed"


_DIALECT_LABELS = (
    DialectLabel.EGYPTIAN,
    DialectLabel.LEVANTINE,
    DialectLabel.GULF,
    DialectLabel.IRAQI,
    DialectLabel.MAGHREBI,
)


@dataclass(frozen=True, slots=True)
class DialectEntry:
    """One lexical or phrase-level dialect mapping."""

    id: str
    dialects: tuple[DialectLabel, ...]
    forms: tuple[str, ...]
    msa: str
    weight: float
    confidence: float
    kind: str
    explanation: str


@dataclass(frozen=True, slots=True)
class DesireForm:
    """A dialectal volitional form used in a desire + verb construction."""

    forms: tuple[str, ...]
    dialects: tuple[DialectLabel, ...]
    person: str


@dataclass(frozen=True, slots=True)
class VerbForm:
    """An explicit dialect-to-MSA imperfect verb mapping."""

    msa: str | None = None
    person: str | None = None
    msa_by_person: tuple[tuple[str, str], ...] = ()

    def for_person(self, person: str) -> str | None:
        mapping = dict(self.msa_by_person)
        return mapping.get(person) or mapping.get(_person_family(person)) or self.msa


@dataclass(frozen=True, slots=True)
class DialectEvidence:
    """One source-anchored clue contributing to dialect identification."""

    dialects: tuple[DialectLabel, ...]
    text: str
    offset: int
    length: int
    weight: float
    rule_id: str

    @property
    def end(self) -> int:
        return self.offset + self.length


@dataclass(frozen=True, slots=True)
class DialectIdentification:
    """Explainable document-level dialect classification."""

    primary: DialectLabel
    confidence: float
    scores: tuple[tuple[DialectLabel, float], ...]
    evidence: tuple[DialectEvidence, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Dialect confidence must be between zero and one")
        if self.scores:
            total = sum(score for _, score in self.scores)
            if not math.isclose(total, 1.0, abs_tol=1e-6):
                raise ValueError("Dialect scores must sum to one")

    def score(self, dialect: DialectLabel | str) -> float:
        """Return the normalized score for one supported dialect."""

        requested = DialectLabel(dialect)
        return dict(self.scores).get(requested, 0.0)


@dataclass(frozen=True, slots=True)
class DialectConversion:
    """One non-destructive dialect-to-MSA conversion candidate."""

    rule_id: str
    dialects: tuple[DialectLabel, ...]
    source: str
    replacement: str
    offset: int
    length: int
    confidence: float
    explanation: str
    contextual: bool
    morphology_validated: bool
    syntax_validated: bool

    def __post_init__(self) -> None:
        if self.offset < 0 or self.length <= 0:
            raise ValueError("Conversion span must be positive and ordered")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Conversion confidence must be between zero and one")
        if not self.replacement:
            raise ValueError("Conversion replacement cannot be empty")

    @property
    def end(self) -> int:
        return self.offset + self.length

    def overlaps(self, other: "DialectConversion") -> bool:
        return self.offset < other.end and other.offset < self.end


@dataclass(frozen=True, slots=True)
class DialectReport:
    """Complete dialect identification and conversion report."""

    text: str
    identification: DialectIdentification
    conversions: tuple[DialectConversion, ...]
    converted_text: str


@dataclass(frozen=True, slots=True)
class _DialectResource:
    version: str
    names: Mapping[DialectLabel, str]
    entries: tuple[DialectEntry, ...]
    desire_forms: tuple[DesireForm, ...]
    verb_forms: Mapping[str, VerbForm]


@dataclass(frozen=True, slots=True)
class _Word:
    token: Token
    break_before: bool


@dataclass(frozen=True, slots=True)
class _FormHit:
    entry: DialectEntry
    offset: int
    length: int
    source: str
    conjunction: str = ""

    @property
    def end(self) -> int:
        return self.offset + self.length


def _surface(value: str) -> str:
    return normalize(value, NormalizationMode.LOOKUP)


def _validate_resource(payload: Mapping[str, Any]) -> None:
    schema = json.loads(DIALECT_RESOURCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path)
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors
        )
        raise ValueError(f"Dialect resource schema validation failed: {details}")


def _person_family(person: str) -> str:
    if person == "2_or_3f":
        return "2s"
    return person


def _desire_verb(person: str) -> str:
    return {
        "1s": "أريد",
        "1p": "نريد",
        "2s": "تريد",
        "2p": "تريدون",
        "2_or_3f": "تريد",
        "3m": "يريد",
        "3f": "تريد",
        "3p": "يريدون",
    }.get(person, "أريد")


def _infer_surface_person(surface: str) -> str | None:
    value = _surface(surface)
    if value.endswith(("ون", "وا")):
        if value.startswith("ت"):
            return "2p"
        if value.startswith("ي"):
            return "3p"
    if value.startswith(("أ", "ا")):
        return "1s"
    if value.startswith("ن"):
        return "1p"
    if value.startswith("ي"):
        return "3m"
    if value.startswith("ت"):
        return "2_or_3f"
    return None


def _split_conjunction(surface: str, known_forms: Mapping[str, Any]) -> tuple[str, str]:
    if len(surface) > 2 and surface[0] in "وف" and surface[1:] in known_forms:
        return surface[0], surface[1:]
    return "", surface


@lru_cache(maxsize=4)
def load_dialect_resource(
    path: Path | str = DEFAULT_DIALECT_RESOURCE_PATH,
) -> _DialectResource:
    """Load and validate the packaged immutable dialect knowledge base."""

    resource_path = Path(path)
    payload = json.loads(resource_path.read_text(encoding="utf-8"))
    _validate_resource(payload)
    names = {DialectLabel(key): str(item["name_ar"]) for key, item in payload["dialects"].items()}
    entries = tuple(
        DialectEntry(
            id=str(item["id"]),
            dialects=tuple(DialectLabel(value) for value in item["dialects"]),
            forms=tuple(_surface(str(value)) for value in item["forms"]),
            msa=str(item["msa"]),
            weight=float(item["weight"]),
            confidence=float(item["confidence"]),
            kind=str(item["kind"]),
            explanation=str(item["explanation"]),
        )
        for item in payload["entries"]
    )
    if len({entry.id for entry in entries}) != len(entries):
        raise ValueError("Dialect resource contains duplicate entry ids")
    desire_forms = tuple(
        DesireForm(
            forms=tuple(_surface(str(value)) for value in item["forms"]),
            dialects=tuple(DialectLabel(value) for value in item["dialects"]),
            person=str(item["person"]),
        )
        for item in payload["desire_forms"]
    )
    verb_forms = {
        _surface(str(surface)): VerbForm(
            msa=str(item["msa"]) if item.get("msa") else None,
            person=str(item["person"]) if item.get("person") else None,
            msa_by_person=tuple(
                sorted(
                    (str(person), str(form))
                    for person, form in item.get("msa_by_person", {}).items()
                )
            ),
        )
        for surface, item in payload["verb_forms"].items()
    }
    return _DialectResource(str(payload["version"]), names, entries, desire_forms, verb_forms)


class DialectEngine:
    """Precision-gated dialect detector and context-aware MSA converter."""

    def __init__(
        self,
        morphology: MorphologicalAnalyzer | None = None,
        syntax: SyntaxEngine | None = None,
        *,
        min_conversion_confidence: float = 0.76,
    ):
        if not 0.0 <= min_conversion_confidence <= 1.0:
            raise ValueError("min_conversion_confidence must be between zero and one")
        self.morphology = morphology or default_analyzer()
        self.syntax = syntax or default_syntax_engine()
        self.resource = load_dialect_resource()
        self.min_conversion_confidence = min_conversion_confidence
        self._entry_by_form: dict[str, list[DialectEntry]] = {}
        for entry in self.resource.entries:
            for form in entry.forms:
                self._entry_by_form.setdefault(form, []).append(entry)
        self._desire_by_form: dict[str, DesireForm] = {}
        for item in self.resource.desire_forms:
            for form in item.forms:
                self._desire_by_form[form] = item
        self._phrase_entries = tuple(
            entry for entry in self.resource.entries if any(" " in form for form in entry.forms)
        )
        self._analyze_cached = lru_cache(maxsize=2048)(self._analyze_uncached)

    @staticmethod
    def _words(text: str, tokens: Sequence[Token] | None = None) -> tuple[_Word, ...]:
        words: list[_Word] = []
        barrier = False
        for token in iter_tokens(text) if tokens is None else tokens:
            if token.kind == TokenKind.WHITESPACE:
                continue
            if token.kind == TokenKind.ARABIC_WORD:
                words.append(_Word(token, barrier))
                barrier = False
            else:
                barrier = True
        return tuple(words)

    def _form_hits(self, text: str, words: Sequence[_Word]) -> tuple[_FormHit, ...]:
        hits: list[_FormHit] = []
        for entry in self._phrase_entries:
            for form in entry.forms:
                parts = form.split()
                for index in range(0, len(words) - len(parts) + 1):
                    window = words[index : index + len(parts)]
                    if any(item.break_before for item in window[1:]):
                        continue
                    surfaces = [_surface(item.token.text) for item in window]
                    conjunction = ""
                    if surfaces and len(surfaces[0]) > 2 and surfaces[0][0] in "وف":
                        conjunction = surfaces[0][0]
                        surfaces[0] = surfaces[0][1:]
                    if surfaces != parts:
                        continue
                    start = window[0].token.start
                    end = window[-1].token.end
                    hits.append(_FormHit(entry, start, end - start, text[start:end], conjunction))
        for word in words:
            surface = _surface(word.token.text)
            conjunction, base = _split_conjunction(surface, self._entry_by_form)
            for entry in self._entry_by_form.get(base, ()):  # exact normalized lexical match
                if any(" " in form for form in entry.forms):
                    continue
                hits.append(
                    _FormHit(
                        entry,
                        word.token.start,
                        word.token.end - word.token.start,
                        word.token.text,
                        conjunction,
                    )
                )
        unique: dict[tuple[str, int, int], _FormHit] = {}
        for hit in hits:
            key = (hit.entry.id, hit.offset, hit.length)
            current = unique.get(key)
            if current is None or hit.entry.confidence > current.entry.confidence:
                unique[key] = hit
        return tuple(
            sorted(unique.values(), key=lambda item: (item.offset, -item.length, item.entry.id))
        )

    @staticmethod
    def _filter_context_sensitive_hits(
        hits: Sequence[_FormHit], words: Sequence[_Word]
    ) -> tuple[_FormHit, ...]:
        by_start = {word.token.start: index for index, word in enumerate(words)}
        out: list[_FormHit] = []
        for hit in hits:
            index = by_start.get(hit.offset)
            previous = (
                _surface(words[index - 1].token.text) if index is not None and index > 0 else None
            )
            following = (
                _surface(words[index + 1].token.text)
                if index is not None and index + 1 < len(words)
                else None
            )
            if hit.entry.id == "GF_ALHEEN" and previous in {"ذلك", "هذا", "ذاك"}:
                continue
            if hit.entry.id == "GF_ABI":
                if following is None or not following.startswith(("أ", "ا", "ن", "ت", "ي")):
                    continue
            if hit.entry.id == "MG_MSHIT":
                continue
            out.append(hit)
        return tuple(out)

    def _identify(self, text: str, hits: Sequence[_FormHit]) -> DialectIdentification:
        if not text.strip():
            return DialectIdentification(DialectLabel.MSA, 1.0, ((DialectLabel.MSA, 1.0),), ())
        evidence = tuple(
            DialectEvidence(
                hit.entry.dialects,
                text[hit.offset : hit.end],
                hit.offset,
                hit.length,
                hit.entry.weight,
                hit.entry.id,
            )
            for hit in hits
        )
        raw = {label: 0.08 for label in _DIALECT_LABELS}
        for item in evidence:
            share = item.weight / len(item.dialects)
            for label in item.dialects:
                raw[label] += share
        if not evidence:
            return DialectIdentification(DialectLabel.MSA, 0.995, ((DialectLabel.MSA, 1.0),), ())
        ranked = sorted(raw.items(), key=lambda item: (-item[1], item[0].value))
        top_label, top_score = ranked[0]
        second_score = ranked[1][1]
        strong_total = sum(item.weight for item in evidence)
        ambiguous = top_score < 0.72 or (second_score >= 0.48 and top_score - second_score < 0.30)
        primary = DialectLabel.MIXED if ambiguous else top_label
        if ambiguous:
            raw_scores: list[tuple[DialectLabel, float]] = [(DialectLabel.MIXED, 0.35)]
            raw_scores.extend(ranked)
        else:
            raw_scores = ranked
        total = sum(value for _, value in raw_scores)
        scores = tuple((label, value / total) for label, value in raw_scores)
        margin = max(0.0, top_score - second_score)
        confidence = min(0.995, 0.48 + min(0.34, strong_total * 0.11) + min(0.17, margin * 0.22))
        if ambiguous:
            confidence = min(confidence, 0.69)
        return DialectIdentification(primary, confidence, scores, evidence)

    def _analyze_uncached(self, text: str) -> DialectIdentification:
        words = self._words(text)
        hits = self._filter_context_sensitive_hits(self._form_hits(text, words), words)
        return self._identify(text, hits)

    def identify(self, text: str) -> DialectIdentification:
        """Identify the dominant dialect while preserving every lexical clue."""

        return self._analyze_cached(text)

    def _validate_msa(self, replacement: str) -> tuple[bool, bool]:
        words = [word for word in self._words(replacement)]
        morphology_valid = bool(words)
        for word in words:
            readings = self.morphology.analyze(word.token.text, min_confidence=0.45)
            if not readings or not any(item.pos != "unknown" for item in readings):
                morphology_valid = False
                break
        parsed = self.syntax.parse(replacement)
        syntax_matches = [
            item
            for sentence in parsed.sentences
            for item in self.syntax.check_parse(sentence)
            if item.severity == "error"
        ]
        syntax_valid = bool(parsed.sentences) and not syntax_matches
        return morphology_valid, syntax_valid

    def _msa_verb(
        self,
        source: str,
        fallback_person: str,
        syntax_person: str | None = None,
    ) -> tuple[str | None, str]:
        surface = _surface(source)
        explicit = self.resource.verb_forms.get(surface)
        if explicit is not None and explicit.msa_by_person and explicit.person is None:
            person = syntax_person or fallback_person
        else:
            person = (
                syntax_person
                or (explicit.person if explicit and explicit.person else None)
                or _infer_surface_person(surface)
                or fallback_person
            )
        if explicit is not None:
            candidate = explicit.for_person(person)
            if candidate:
                return candidate, person
        candidate = surface
        if candidate.endswith("و") and person in {"1p", "2p", "3p"}:
            candidate = candidate[:-1]
        if person == "1s" and candidate.startswith("ا"):
            candidate = "أ" + candidate[1:]
        if explicit is None and not candidate.startswith(("أ", "ا", "ن", "ت", "ي")):
            return None, person
        readings = self.morphology.analyze(candidate, min_confidence=0.45)
        verbs = [item for item in readings if item.pos == "verb" and item.confidence >= 0.47]
        if not verbs:
            return None, person
        feature_person = next(
            (item.feature("person") for item in verbs if item.feature("person")), None
        )
        if feature_person and _person_family(feature_person) != _person_family(person):
            return None, person
        return candidate, person

    def _desire_conversions(
        self,
        text: str,
        words: Sequence[_Word],
        parsed: DocumentParse | None = None,
    ) -> tuple[DialectConversion, ...]:
        out: list[DialectConversion] = []
        syntax_people: dict[tuple[int, int], str] = {}
        if parsed is not None:
            for sentence in parsed.sentences:
                for token in sentence.tokens:
                    person = token.feature("person")
                    if person:
                        syntax_people[(token.start, token.end)] = person
        for index in range(len(words) - 1):
            desire_word = words[index]
            verb_word = words[index + 1]
            if verb_word.break_before:
                continue
            surface = _surface(desire_word.token.text)
            conjunction, base = _split_conjunction(surface, self._desire_by_form)
            desire = self._desire_by_form.get(base)
            if desire is None:
                continue
            syntax_person = syntax_people.get((verb_word.token.start, verb_word.token.end))
            msa_verb, person = self._msa_verb(
                verb_word.token.text,
                desire.person,
                syntax_person=syntax_person,
            )
            if msa_verb is None:
                continue
            replacement = f"{conjunction}{_desire_verb(person)} أن {msa_verb}"
            morphology_valid, syntax_valid = self._validate_msa(replacement)
            if not morphology_valid or not syntax_valid:
                continue
            start = desire_word.token.start
            end = verb_word.token.end
            source = text[start:end]
            out.append(
                DialectConversion(
                    "DIALECT_DESIRE_CONTEXT",
                    desire.dialects,
                    source,
                    replacement,
                    start,
                    end - start,
                    0.97,
                    "حوّل ضاد تركيب الرغبة اللهجي إلى فعل «أراد» متصرفًا بحسب شخص الفعل التالي، ثم أدخل «أن» على المضارع.",
                    True,
                    morphology_valid,
                    syntax_valid,
                )
            )
        return tuple(out)

    def _entry_conversion(self, hit: _FormHit) -> DialectConversion | None:
        replacement = hit.entry.msa
        if hit.conjunction and not replacement.startswith(hit.conjunction):
            replacement = hit.conjunction + replacement
        morphology_valid, syntax_valid = self._validate_msa(replacement)
        if not morphology_valid:
            return None
        confidence = hit.entry.confidence
        if not syntax_valid and " " in replacement:
            confidence -= 0.08
        if confidence < self.min_conversion_confidence:
            return None
        return DialectConversion(
            hit.entry.id,
            hit.entry.dialects,
            hit.source,
            replacement,
            hit.offset,
            hit.length,
            confidence,
            hit.entry.explanation,
            hit.entry.kind == "phrase",
            morphology_valid,
            syntax_valid,
        )

    @staticmethod
    def _resolve_conversions(
        conversions: Sequence[DialectConversion],
    ) -> tuple[DialectConversion, ...]:
        ranked = sorted(
            conversions,
            key=lambda item: (
                -int(item.contextual),
                -item.confidence,
                -item.length,
                item.offset,
                item.rule_id,
            ),
        )
        kept: list[DialectConversion] = []
        accepted = DisjointSpanIndex()
        for candidate in ranked:
            if not accepted.overlaps(candidate.offset, candidate.end):
                accepted.add(candidate.offset, candidate.end)
                kept.append(candidate)
        return tuple(sorted(kept, key=lambda item: (item.offset, item.end, item.rule_id)))

    def conversions(
        self,
        text: str,
        *,
        parsed: DocumentParse | None = None,
        context: AnalysisContext | None = None,
    ) -> tuple[DialectConversion, ...]:
        """Return validated conversion candidates without changing the source."""

        # ``parsed`` is accepted to make pipeline reuse explicit.  Contextual
        # validation uses the same SyntaxEngine instance, so no parallel grammar
        # implementation can drift from Phase 4.
        if context is not None:
            if context.text != text:
                raise ValueError("Analysis context does not correspond to the supplied text")
            parsed = parsed or context.parsed
        if parsed is not None and parsed.text != text:
            raise ValueError("Parsed document does not correspond to the supplied text")
        words = self._words(text, context.tokens if context is not None else None)
        hits = self._filter_context_sensitive_hits(self._form_hits(text, words), words)
        candidates: list[DialectConversion] = list(
            self._desire_conversions(text, words, parsed=parsed)
        )
        for hit in hits:
            conversion = self._entry_conversion(hit)
            if conversion is not None:
                candidates.append(conversion)
        return self._resolve_conversions(candidates)

    @staticmethod
    def apply(text: str, conversions: Sequence[DialectConversion]) -> str:
        """Apply an explicit conversion set using stable original offsets."""

        out = text
        for item in reversed(tuple(conversions)):
            out = out[: item.offset] + item.replacement + out[item.end :]
        return out

    def report(self, text: str, *, parsed: DocumentParse | None = None) -> DialectReport:
        """Return identification, validated suggestions, and an opt-in MSA preview."""

        conversions = self.conversions(text, parsed=parsed)
        return DialectReport(text, self.identify(text), conversions, self.apply(text, conversions))

    def check_text(
        self,
        text: str,
        *,
        parsed: DocumentParse | None = None,
        context: AnalysisContext | None = None,
    ) -> list[Match]:
        """Expose dialect conversions as non-autofix hint matches."""

        matches: list[Match] = []
        for item in self.conversions(text, parsed=parsed, context=context):
            dialect_names = "/".join(self.resource.names[label] for label in item.dialects)
            matches.append(
                Match(
                    item.rule_id,
                    "dialect",
                    f"تعبير من اللهجة {dialect_names}؛ بالفصحى: «{item.replacement}».",
                    item.offset,
                    item.length,
                    replacements=[item.replacement],
                    severity="hint",
                    explanation=item.explanation,
                    autofix=False,
                    confidence=item.confidence,
                    priority=60 if item.contextual else 45,
                    tags=(
                        "dialect-to-msa",
                        "requires-approval",
                        "morphology-validated",
                        "syntax-validated" if item.syntax_validated else "syntax-advisory",
                        *(f"dialect:{label.value}" for label in item.dialects),
                    ),
                )
            )
        return dedupe(matches)


@lru_cache(maxsize=1)
def default_dialect_engine() -> DialectEngine:
    """Return the shared immutable-resource dialect engine."""

    return DialectEngine()
