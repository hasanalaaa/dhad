"""Deterministic Arabic morphology primitives for Dhad.

The module provides a conservative, explainable analyzer.  It combines a
versioned lexical resource with productive clitic/inflection generation and a
small set of canonical Arabic derivational templates.  Lexical analyses have
higher confidence than template-only guesses; callers can therefore choose the
precision level appropriate for spelling, grammar, or educational views.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Protocol, Sequence, runtime_checkable

from jsonschema import Draft202012Validator

from .text import NormalizationMode, normalize

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_LEXICON_PATH = DATA_DIR / "lexicon" / "core_lexicon.json"
LEXICON_SCHEMA_PATH = DATA_DIR / "lexicon.schema.json"

ARABIC_LETTERS = frozenset("ابتثجحخدذرزسشصضطظعغفقكلمنهويءأإآؤئىةٱپچژڤگ")


@dataclass(frozen=True, slots=True)
class AffixSegment:
    """One surface affix anchored to the normalized token."""

    kind: str
    surface: str
    start: int
    end: int
    feature: str

    def __post_init__(self) -> None:
        if self.kind not in {"prefix", "suffix", "infix"}:
            raise ValueError(f"Unsupported affix kind: {self.kind}")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Affix span must be positive and ordered")


@dataclass(frozen=True, slots=True)
class MorphologicalAnalysis:
    """A ranked morphological interpretation of one Arabic token."""

    token: str
    normalized: str
    stem: str
    lemma: str
    root: str | None
    pattern: str | None
    pos: str
    prefixes: tuple[AffixSegment, ...] = ()
    suffixes: tuple[AffixSegment, ...] = ()
    infixes: tuple[AffixSegment, ...] = ()
    features: tuple[tuple[str, str], ...] = ()
    confidence: float = 0.0
    source: str = "pattern"
    frequency: int = 1

    def __post_init__(self) -> None:
        if not self.token or not self.normalized:
            raise ValueError("Analysis token cannot be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Analysis confidence must be between 0 and 1")
        if self.frequency < 1:
            raise ValueError("Analysis frequency must be positive")

    def feature(self, name: str, default: str | None = None) -> str | None:
        """Return one immutable feature value."""

        return dict(self.features).get(name, default)

    @property
    def is_lexical(self) -> bool:
        """Whether the reading is backed by the packaged lexicon."""

        return self.source in {"lexicon", "generated"}


@dataclass(frozen=True, slots=True)
class Lexeme:
    """A canonical lexicon entry."""

    lemma: str
    root: str | None
    pattern: str | None
    pos: str
    frequency: int
    features: tuple[tuple[str, str], ...] = ()
    forms: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class FormRecord:
    """A generated or explicit surface form associated with a lexeme."""

    form: str
    lexeme: Lexeme
    prefixes: tuple[tuple[str, str], ...] = ()
    suffixes: tuple[tuple[str, str], ...] = ()
    features: tuple[tuple[str, str], ...] = ()
    source: str = "lexicon"
    confidence: float = 0.99


@dataclass(frozen=True, slots=True)
class PatternTemplate:
    """A derivational template where ف/ع/ل mark root radicals."""

    name: str
    template: str
    pos: str = "unknown"
    confidence: float = 0.52

    @property
    def radical_positions(self) -> tuple[int, ...]:
        return tuple(index for index, char in enumerate(self.template) if char in "فعل")


PATTERNS: tuple[PatternTemplate, ...] = (
    PatternTemplate("استفعال", "استفعال", "verbal_noun", 0.68),
    PatternTemplate("استفعل", "استفعل", "verb", 0.66),
    PatternTemplate("انفعال", "انفعال", "verbal_noun", 0.65),
    PatternTemplate("افتعال", "افتعال", "verbal_noun", 0.68),
    PatternTemplate("مفاعلة", "مفاعلة", "verbal_noun", 0.67),
    PatternTemplate("تفاعل", "تفاعل", "verb", 0.62),
    PatternTemplate("افتعل", "افتعل", "verb", 0.63),
    PatternTemplate("انفعل", "انفعل", "verb", 0.62),
    PatternTemplate("تفعيل", "تفعيل", "verbal_noun", 0.66),
    PatternTemplate("مفعول", "مفعول", "adjective", 0.64),
    PatternTemplate("مفعال", "مفعال", "noun", 0.58),
    PatternTemplate("فعالة", "فعالة", "noun", 0.58),
    PatternTemplate("فعيلة", "فعيلة", "noun", 0.58),
    PatternTemplate("فاعل", "فاعل", "noun", 0.63),
    PatternTemplate("فعال", "فعال", "noun", 0.57),
    PatternTemplate("فعيل", "فعيل", "adjective", 0.57),
    PatternTemplate("أفعل", "أفعل", "verb", 0.59),
    PatternTemplate("تفعل", "تفعل", "verb", 0.56),
    PatternTemplate("مفعل", "مفعل", "noun", 0.55),
    PatternTemplate("فعلل", "فعلل", "verb", 0.50),
    PatternTemplate("فعل", "فعل", "verb", 0.47),
)

# Surface forms are deliberately explicit.  This prevents the segmenter from
# stripping ambiguous single letters unless the remaining form is lexically
# licensed.
_PREFIX_FORMS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("وبال", (("و", "conjunction"), ("ب", "preposition"), ("ال", "definite"))),
    ("فبال", (("ف", "conjunction"), ("ب", "preposition"), ("ال", "definite"))),
    ("ولل", (("و", "conjunction"), ("ل", "preposition"), ("ال", "definite"))),
    ("فلل", (("ف", "conjunction"), ("ل", "preposition"), ("ال", "definite"))),
    ("وال", (("و", "conjunction"), ("ال", "definite"))),
    ("فال", (("ف", "conjunction"), ("ال", "definite"))),
    ("بال", (("ب", "preposition"), ("ال", "definite"))),
    ("كال", (("ك", "preposition"), ("ال", "definite"))),
    ("لل", (("ل", "preposition"), ("ال", "definite"))),
    ("وس", (("و", "conjunction"), ("س", "future"))),
    ("فس", (("ف", "conjunction"), ("س", "future"))),
    ("ال", (("ال", "definite"),)),
    ("و", (("و", "conjunction"),)),
    ("ف", (("ف", "conjunction"),)),
    ("ب", (("ب", "preposition"),)),
    ("ك", (("ك", "preposition"),)),
    ("ل", (("ل", "preposition"),)),
    ("س", (("س", "future"),)),
)

_SUFFIX_FORMS: tuple[tuple[str, str], ...] = (
    ("كما", "pronoun_dual"),
    ("هما", "pronoun_dual"),
    ("كن", "pronoun_feminine_plural"),
    ("هم", "pronoun_masculine_plural"),
    ("هن", "pronoun_feminine_plural"),
    ("نا", "pronoun_first_plural"),
    ("تان", "dual_feminine_nominative"),
    ("تين", "dual_feminine_oblique"),
    ("ون", "plural_masculine_nominative"),
    ("ين", "plural_masculine_oblique"),
    ("ان", "dual_nominative"),
    ("ات", "plural_feminine"),
    ("وا", "verb_past_plural"),
    ("تم", "verb_second_plural"),
    ("تن", "verb_second_feminine_plural"),
    ("ه", "pronoun_masculine"),
    ("ها", "pronoun_feminine"),
    ("ك", "pronoun_second"),
    ("ي", "pronoun_first"),
    ("ة", "feminine"),
)


def _feature_tuple(
    values: Mapping[str, Any] | Iterable[tuple[str, Any]],
) -> tuple[tuple[str, str], ...]:
    items = values.items() if isinstance(values, Mapping) else values
    return tuple(sorted((str(key), str(value)) for key, value in items))


def _validate_lexicon(payload: Mapping[str, Any]) -> None:
    schema = json.loads(LEXICON_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.path)
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors
        )
        raise ValueError(f"Lexicon schema validation failed: {details}")


def _surface_prefix(surface: str, units: Sequence[tuple[str, str]]) -> tuple[AffixSegment, ...]:
    out: list[AffixSegment] = []
    cursor = 0
    # Assimilated لـ + ال appears as لل. Anchor the logical article to the
    # second lam while retaining non-overlapping source spans.
    for unit, feature in units:
        if surface == "لل" and unit == "ال":
            start, end = 1, 2
        else:
            written = unit
            if surface.startswith(written, cursor):
                start, end = cursor, cursor + len(written)
            else:
                start, end = cursor, min(len(surface), cursor + 1)
            cursor = end
        out.append(AffixSegment("prefix", unit, start, end, feature))
    return tuple(out)


def _surface_suffix(
    token_length: int, units: Sequence[tuple[str, str]]
) -> tuple[AffixSegment, ...]:
    out: list[AffixSegment] = []
    cursor = token_length - sum(len(surface) for surface, _ in units)
    for surface, feature in units:
        out.append(AffixSegment("suffix", surface, cursor, cursor + len(surface), feature))
        cursor += len(surface)
    return tuple(out)


def _match_pattern(
    stem: str, template: PatternTemplate
) -> tuple[str, tuple[AffixSegment, ...]] | None:
    if len(stem) != len(template.template):
        return None
    root_chars: list[str] = []
    infixes: list[AffixSegment] = []
    for index, (char, marker) in enumerate(zip(stem, template.template)):
        if marker in "فعل":
            root_chars.append(char)
            continue
        if char != marker:
            return None
        infixes.append(AffixSegment("infix", char, index, index + 1, f"pattern:{marker}"))
    root = "".join(root_chars)
    if len(root) not in {3, 4} or any(char not in ARABIC_LETTERS for char in root):
        return None
    return root, tuple(infixes)


class MorphologicalLexicon:
    """Versioned lexicon plus productive, traceable surface-form generation."""

    def __init__(self, path: Path | str = DEFAULT_LEXICON_PATH):
        self.path = Path(path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        _validate_lexicon(payload)
        self.version = str(payload["version"])
        self.lexemes = tuple(self._parse_lexeme(item) for item in payload["entries"])
        self._lemma_index = {item.lemma: item for item in self.lexemes}
        self._root_index: dict[str, list[Lexeme]] = {}
        self._form_index: dict[str, list[FormRecord]] = {}
        self._lemma_form_index: dict[str, list[FormRecord]] = {}
        for lexeme in self.lexemes:
            if lexeme.root:
                self._root_index.setdefault(lexeme.root, []).append(lexeme)
            for record in self._generate_records(lexeme):
                self._form_index.setdefault(record.form, []).append(record)
                self._lemma_form_index.setdefault(lexeme.lemma, []).append(record)
        for records in (*self._form_index.values(), *self._lemma_form_index.values()):
            records.sort(key=lambda item: (-item.confidence, -item.lexeme.frequency, item.form))

    @staticmethod
    def _parse_lexeme(raw: Mapping[str, Any]) -> Lexeme:
        forms = tuple(
            (
                normalize(str(item["form"]), NormalizationMode.LOOKUP),
                _feature_tuple(item.get("features", {})),
            )
            for item in raw.get("forms", ())
        )
        return Lexeme(
            lemma=normalize(str(raw["lemma"]), NormalizationMode.LOOKUP),
            root=normalize(str(raw["root"]), NormalizationMode.LOOKUP) if raw.get("root") else None,
            pattern=str(raw["pattern"]) if raw.get("pattern") else None,
            pos=str(raw["pos"]),
            frequency=int(raw["frequency"]),
            features=_feature_tuple(raw.get("features", {})),
            forms=forms,
        )

    @staticmethod
    def _record(
        form: str,
        lexeme: Lexeme,
        *,
        prefixes: Sequence[tuple[str, str]] = (),
        suffixes: Sequence[tuple[str, str]] = (),
        features: Mapping[str, Any] | Iterable[tuple[str, Any]] = (),
        source: str,
        confidence: float,
    ) -> FormRecord:
        return FormRecord(
            normalize(form, NormalizationMode.LOOKUP),
            lexeme,
            tuple(prefixes),
            tuple(suffixes),
            _feature_tuple(features),
            source,
            confidence,
        )

    def _base_records(self, lexeme: Lexeme) -> Iterator[FormRecord]:
        yield self._record(
            lexeme.lemma,
            lexeme,
            features=lexeme.features,
            source="lexicon",
            confidence=0.995,
        )
        for form, features in lexeme.forms:
            yield self._record(
                form,
                lexeme,
                features=features,
                source="lexicon",
                confidence=0.99,
            )

    def _noun_records(self, lexeme: Lexeme) -> Iterator[FormRecord]:
        lemma = lexeme.lemma
        if lexeme.pos not in {"noun", "adjective", "proper_noun", "verbal_noun"}:
            return
        if not lemma.startswith("ال"):
            yield self._record(
                "ال" + lemma,
                lexeme,
                prefixes=(("ال", "definite"),),
                features={"definiteness": "definite"},
                source="generated",
                confidence=0.965,
            )
        if lemma.endswith("ة") and len(lemma) > 2:
            stem = lemma[:-1]
            yield self._record(
                stem + "ات",
                lexeme,
                suffixes=(("ات", "plural_feminine"),),
                features={"number": "plural", "gender": "feminine"},
                source="generated",
                confidence=0.94,
            )
            for suffix, feature, case in (
                ("تان", "dual_feminine_nominative", "nominative"),
                ("تين", "dual_feminine_oblique", "oblique"),
            ):
                yield self._record(
                    stem + suffix,
                    lexeme,
                    suffixes=((suffix, feature),),
                    features={"number": "dual", "gender": "feminine", "case": case},
                    source="generated",
                    confidence=0.90,
                )
            for suffix, feature, case in (
                ("تا", "dual_feminine_construct_nominative", "nominative"),
                ("تي", "dual_feminine_construct_oblique", "oblique"),
            ):
                yield self._record(
                    stem + suffix,
                    lexeme,
                    suffixes=((suffix, feature),),
                    features={
                        "number": "dual",
                        "gender": "feminine",
                        "case": case,
                        "construct_state": "true",
                    },
                    source="generated",
                    confidence=0.86,
                )
        elif len(lemma) >= 3 and lexeme.pos != "proper_noun":
            for suffix, feature, case in (
                ("ان", "dual_nominative", "nominative"),
                ("ين", "dual_oblique", "oblique"),
            ):
                yield self._record(
                    lemma + suffix,
                    lexeme,
                    suffixes=((suffix, feature),),
                    features={"number": "dual", "case": case},
                    source="generated",
                    confidence=0.84,
                )
            for suffix, feature, case in (
                ("ا", "dual_construct_nominative", "nominative"),
                ("ي", "dual_construct_oblique", "oblique"),
            ):
                yield self._record(
                    lemma + suffix,
                    lexeme,
                    suffixes=((suffix, feature),),
                    features={"number": "dual", "case": case, "construct_state": "true"},
                    source="generated",
                    confidence=0.80,
                )
        gender = dict(lexeme.features).get("gender")
        if gender == "masculine" and lexeme.pos in {"noun", "adjective"}:
            for suffix, feature, case in (
                ("ون", "plural_masculine_nominative", "nominative"),
                ("ين", "plural_masculine_oblique", "oblique"),
            ):
                yield self._record(
                    lemma + suffix,
                    lexeme,
                    suffixes=((suffix, feature),),
                    features={"number": "plural", "gender": "masculine", "case": case},
                    source="generated",
                    confidence=0.93,
                )
            for suffix, feature, case in (
                ("و", "plural_masculine_construct_nominative", "nominative"),
                ("ي", "plural_masculine_construct_oblique", "oblique"),
            ):
                yield self._record(
                    lemma + suffix,
                    lexeme,
                    suffixes=((suffix, feature),),
                    features={
                        "number": "plural",
                        "gender": "masculine",
                        "case": case,
                        "construct_state": "true",
                    },
                    source="generated",
                    confidence=0.88,
                )

    def _verb_records(self, lexeme: Lexeme) -> Iterator[FormRecord]:
        if lexeme.pos != "verb" or len(lexeme.lemma) < 3:
            return
        lemma = lexeme.lemma
        for suffix, feature, person in (
            ("ت", "past_suffix", "1_or_2_or_3f"),
            ("نا", "past_suffix", "1p"),
            ("وا", "past_suffix", "3mp"),
            ("تم", "past_suffix", "2mp"),
            ("تن", "past_suffix", "2fp"),
        ):
            yield self._record(
                lemma + suffix,
                lexeme,
                suffixes=((suffix, feature),),
                features={"aspect": "perfect", "person": person},
                source="generated",
                confidence=0.82,
            )
        # For regular unvocalized triliteral verbs, the consonantal imperfect
        # stem is often recoverable as prefix + perfect lemma.  Lexicon entries
        # can override irregular verbs with explicit forms.
        if len(lemma) == 3:
            for prefix, person in (("ي", "3m"), ("ت", "2_or_3f"), ("ن", "1p"), ("أ", "1s")):
                form = prefix + lemma
                yield self._record(
                    form,
                    lexeme,
                    prefixes=((prefix, "imperfect_person"),),
                    features={"aspect": "imperfect", "person": person},
                    source="generated",
                    confidence=0.78,
                )
                if prefix in {"ي", "ت"}:
                    yield self._record(
                        form + "ون",
                        lexeme,
                        prefixes=((prefix, "imperfect_person"),),
                        suffixes=(("ون", "plural_masculine_nominative"),),
                        features={"aspect": "imperfect", "person": person, "number": "plural"},
                        source="generated",
                        confidence=0.76,
                    )
                    yield self._record(
                        "س" + form,
                        lexeme,
                        prefixes=(("س", "future"), (prefix, "imperfect_person")),
                        features={"aspect": "future", "person": person},
                        source="generated",
                        confidence=0.77,
                    )
                    yield self._record(
                        "س" + form + "ون",
                        lexeme,
                        prefixes=(("س", "future"), (prefix, "imperfect_person")),
                        suffixes=(("ون", "plural_masculine_nominative"),),
                        features={"aspect": "future", "person": person, "number": "plural"},
                        source="generated",
                        confidence=0.75,
                    )

    def _clitic_records(self, records: Sequence[FormRecord]) -> Iterator[FormRecord]:
        # Generate common proclitics around lexically licensed forms.  Article
        # combinations are generated from bare nominal forms only; this avoids
        # impossible double articles.
        for record in records:
            form = record.form
            if record.lexeme.pos in {"noun", "adjective", "verbal_noun", "proper_noun"}:
                if not form.startswith("ال"):
                    article_record = self._record(
                        "ال" + form,
                        record.lexeme,
                        prefixes=(("ال", "definite"),) + record.prefixes,
                        suffixes=record.suffixes,
                        features=dict(record.features) | {"definiteness": "definite"},
                        source="generated",
                        confidence=max(0.76, record.confidence - 0.025),
                    )
                    yield article_record
                    tail = form
                    for surface, units in (
                        ("وال", (("و", "conjunction"), ("ال", "definite"))),
                        ("فال", (("ف", "conjunction"), ("ال", "definite"))),
                        ("بال", (("ب", "preposition"), ("ال", "definite"))),
                        ("كال", (("ك", "preposition"), ("ال", "definite"))),
                        ("لل", (("ل", "preposition"), ("ال", "definite"))),
                        ("وبال", (("و", "conjunction"), ("ب", "preposition"), ("ال", "definite"))),
                    ):
                        yield self._record(
                            surface + tail,
                            record.lexeme,
                            prefixes=units + record.prefixes,
                            suffixes=record.suffixes,
                            features=dict(record.features) | {"definiteness": "definite"},
                            source="generated",
                            confidence=max(0.74, record.confidence - 0.04),
                        )
                combinations = (
                    ("و", (("و", "conjunction"),)),
                    ("ف", (("ف", "conjunction"),)),
                    ("ب", (("ب", "preposition"),)),
                    ("ل", (("ل", "preposition"),)),
                )
                for surface, units in combinations:
                    yield self._record(
                        surface + form,
                        record.lexeme,
                        prefixes=units + record.prefixes,
                        suffixes=record.suffixes,
                        features=record.features,
                        source="generated",
                        confidence=max(0.72, record.confidence - 0.025),
                    )
            elif record.lexeme.pos in {"particle", "pronoun", "adverb"}:
                for surface, feature in (("و", "conjunction"), ("ف", "conjunction")):
                    yield self._record(
                        surface + form,
                        record.lexeme,
                        prefixes=((surface, feature),) + record.prefixes,
                        suffixes=record.suffixes,
                        features=record.features,
                        source="generated",
                        confidence=max(0.80, record.confidence - 0.02),
                    )
            if form.startswith("ال"):
                tail = form[2:]
                for surface, units in (
                    ("وال", (("و", "conjunction"), ("ال", "definite"))),
                    ("فال", (("ف", "conjunction"), ("ال", "definite"))),
                    ("بال", (("ب", "preposition"), ("ال", "definite"))),
                    ("كال", (("ك", "preposition"), ("ال", "definite"))),
                    ("لل", (("ل", "preposition"), ("ال", "definite"))),
                    (
                        "وبال",
                        (("و", "conjunction"), ("ب", "preposition"), ("ال", "definite")),
                    ),
                ):
                    yield self._record(
                        surface + tail,
                        record.lexeme,
                        prefixes=units,
                        suffixes=record.suffixes,
                        features=record.features,
                        source="generated",
                        confidence=max(0.74, record.confidence - 0.02),
                    )

    def _possessive_records(self, records: Sequence[FormRecord]) -> Iterator[FormRecord]:
        for record in records:
            if record.lexeme.pos not in {"noun", "adjective", "verbal_noun"}:
                continue
            if record.prefixes or record.suffixes:
                continue
            base = record.form[:-1] + "ت" if record.form.endswith("ة") else record.form
            for suffix, feature in (
                ("ها", "pronoun_feminine"),
                ("ه", "pronoun_masculine"),
                ("هم", "pronoun_masculine_plural"),
                ("هن", "pronoun_feminine_plural"),
                ("نا", "pronoun_first_plural"),
                ("ك", "pronoun_second"),
                ("ي", "pronoun_first"),
            ):
                yield self._record(
                    base + suffix,
                    record.lexeme,
                    suffixes=((suffix, feature),),
                    features={"possessive": feature},
                    source="generated",
                    confidence=0.91,
                )

    def _generate_records(self, lexeme: Lexeme) -> tuple[FormRecord, ...]:
        base = list(self._base_records(lexeme))
        productive = list(self._noun_records(lexeme)) + list(self._verb_records(lexeme))
        seed = base + productive
        records = seed + list(self._clitic_records(seed)) + list(self._possessive_records(base))
        unique: dict[tuple[str, tuple, tuple, tuple], FormRecord] = {}
        for record in records:
            key = (record.form, record.prefixes, record.suffixes, record.features)
            current = unique.get(key)
            if current is None or record.confidence > current.confidence:
                unique[key] = record
        return tuple(unique.values())

    def lookup(self, form: str) -> tuple[FormRecord, ...]:
        """Return lexical records for a normalized surface form."""

        key = normalize(form, NormalizationMode.LOOKUP)
        return tuple(self._form_index.get(key, ()))

    def by_root(self, root: str) -> tuple[Lexeme, ...]:
        return tuple(self._root_index.get(normalize(root), ()))

    def lemma(self, lemma: str) -> Lexeme | None:
        return self._lemma_index.get(normalize(lemma))

    def forms_for_lemma(
        self,
        lemma: str,
        *,
        pos: str | None = None,
        features: Mapping[str, str] | None = None,
    ) -> tuple[FormRecord, ...]:
        """Return generated and explicit surface records for one lemma.

        The query is intentionally exact for requested features.  It is used by
        deterministic syntax corrections to inflect an already-disambiguated
        lexeme without guessing a different lemma.
        """

        key = normalize(lemma, NormalizationMode.LOOKUP)
        required = dict(features or {})
        out: list[FormRecord] = []
        for record in self._lemma_form_index.get(key, ()):
            record_pos = dict(record.features).get("pos", record.lexeme.pos)
            if pos is not None and record_pos != pos:
                continue
            available = dict(record.lexeme.features)
            available.update(dict(record.features))
            if all(available.get(name) == value for name, value in required.items()):
                out.append(record)
        return tuple(out)

    @property
    def known_forms(self) -> frozenset[str]:
        return frozenset(self._form_index)

    @property
    def correction_forms(self) -> frozenset[str]:
        """Forms eligible to be proposed as standalone spelling corrections.

        Construct-state surfaces such as ``مهندسو`` are valid only when a
        following genitive completes the phrase.  They remain morphologically
        licensed but are excluded from context-free spelling candidate pools.
        """

        return frozenset(
            form
            for form, records in self._form_index.items()
            if any(dict(record.features).get("construct_state") != "true" for record in records)
        )

    @property
    def roots(self) -> frozenset[str]:
        return frozenset(self._root_index)

    def frequency(self, form: str) -> int:
        records = self.lookup(form)
        return max((record.lexeme.frequency for record in records), default=1)


@runtime_checkable
class MorphologyBackend(Protocol):
    """Stable interface for local or externally supplied morphology backends."""

    lexicon: MorphologicalLexicon

    def analyze(
        self, token: str, *, min_confidence: float = 0.0
    ) -> tuple[MorphologicalAnalysis, ...]:
        """Return ranked analyses for one token."""

    def best(self, token: str, *, min_confidence: float = 0.0) -> MorphologicalAnalysis | None:
        """Return the highest-ranked analysis, if any."""


class MorphologicalAnalyzer:
    """Conservative lexical + derivational Arabic morphological analyzer."""

    def __init__(self, lexicon: MorphologicalLexicon | None = None, *, cache_size: int = 8192):
        self.lexicon = lexicon or default_lexicon()
        self._analyze_cached = lru_cache(maxsize=cache_size)(self._analyze_uncached)

    @staticmethod
    def _is_arabic_word(value: str) -> bool:
        return bool(value) and all(char in ARABIC_LETTERS for char in value)

    def _from_record(self, token: str, record: FormRecord) -> MorphologicalAnalysis:
        prefix_length = sum(len(surface) for surface, _ in record.prefixes)
        suffix_length = sum(len(surface) for surface, _ in record.suffixes)
        stem_end = len(token) - suffix_length if suffix_length else len(token)
        stem = token[prefix_length:stem_end]
        features = dict(record.lexeme.features)
        features.update(dict(record.features))
        infixes: tuple[AffixSegment, ...] = ()
        if record.lexeme.pattern:
            template = next((item for item in PATTERNS if item.name == record.lexeme.pattern), None)
            if template is not None:
                matched = _match_pattern(record.lexeme.lemma, template)
                if matched is not None:
                    _, lemma_infixes = matched
                    infixes = tuple(
                        AffixSegment(
                            "infix",
                            segment.surface,
                            prefix_length + segment.start,
                            prefix_length + segment.end,
                            segment.feature,
                        )
                        for segment in lemma_infixes
                        if prefix_length + segment.end <= len(token) - suffix_length
                    )
        return MorphologicalAnalysis(
            token=token,
            normalized=token,
            stem=stem or record.lexeme.lemma,
            lemma=record.lexeme.lemma,
            root=record.lexeme.root,
            pattern=record.lexeme.pattern,
            pos=dict(record.features).get("pos", record.lexeme.pos),
            prefixes=_surface_prefix(token[:prefix_length], record.prefixes)
            if record.prefixes
            else (),
            suffixes=_surface_suffix(len(token), record.suffixes) if record.suffixes else (),
            infixes=infixes,
            features=_feature_tuple(features),
            confidence=record.confidence,
            source=record.source,
            frequency=record.lexeme.frequency,
        )

    def _pattern_candidates(self, token: str) -> Iterator[MorphologicalAnalysis]:
        stems: list[tuple[str, tuple[AffixSegment, ...], tuple[AffixSegment, ...], float]] = [
            (token, (), (), 0.0)
        ]
        for surface, units in _PREFIX_FORMS:
            if token.startswith(surface) and len(token) - len(surface) >= 3:
                stems.append((token[len(surface) :], _surface_prefix(surface, units), (), 0.05))
        for suffix, feature in _SUFFIX_FORMS:
            if token.endswith(suffix) and len(token) - len(suffix) >= 3:
                stem = token[: -len(suffix)]
                suffixes = _surface_suffix(len(token), ((suffix, feature),))
                stems.append((stem, (), suffixes, 0.06))
                if suffix in {"ات", "تان", "تين"}:
                    restored = stem + "ة"
                    stems.append((restored, (), suffixes, 0.09))
                if suffix in {"ها", "ه", "هم", "هن", "نا", "ك", "ي"} and stem.endswith("ت"):
                    stems.append((stem[:-1] + "ة", (), suffixes, 0.08))
        for prefix_surface, prefix_units in _PREFIX_FORMS:
            if not token.startswith(prefix_surface):
                continue
            remainder = token[len(prefix_surface) :]
            for suffix, feature in _SUFFIX_FORMS:
                if remainder.endswith(suffix) and len(remainder) - len(suffix) >= 3:
                    stem = remainder[: -len(suffix)]
                    stems.append(
                        (
                            stem,
                            _surface_prefix(prefix_surface, prefix_units),
                            _surface_suffix(len(token), ((suffix, feature),)),
                            0.10,
                        )
                    )
        seen: set[tuple[str, str, tuple, tuple]] = set()
        for stem, prefixes, suffixes, penalty in stems:
            for template in PATTERNS:
                matched = _match_pattern(stem, template)
                if matched is None:
                    continue
                root, infixes = matched
                known_root = root in self.lexicon.roots
                confidence = template.confidence + (0.17 if known_root else 0.0) - penalty
                confidence = max(0.25, min(confidence, 0.86))
                lemmas = self.lexicon.by_root(root)
                lemma = lemmas[0].lemma if lemmas else stem
                frequency = max((item.frequency for item in lemmas), default=1)
                source = "segmented" if known_root else "pattern"
                key = (lemma, template.name, prefixes, suffixes)
                if key in seen:
                    continue
                seen.add(key)
                yield MorphologicalAnalysis(
                    token=token,
                    normalized=token,
                    stem=stem,
                    lemma=lemma,
                    root=root,
                    pattern=template.name,
                    pos=lemmas[0].pos if lemmas else template.pos,
                    prefixes=prefixes,
                    suffixes=suffixes,
                    infixes=infixes,
                    features=(),
                    confidence=confidence,
                    source=source,
                    frequency=frequency,
                )

    def _analyze_uncached(self, normalized_token: str) -> tuple[MorphologicalAnalysis, ...]:
        if not self._is_arabic_word(normalized_token):
            return ()
        analyses = [
            self._from_record(normalized_token, record)
            for record in self.lexicon.lookup(normalized_token)
        ]
        analyses.extend(self._pattern_candidates(normalized_token))
        unique: dict[tuple[Any, ...], MorphologicalAnalysis] = {}
        for analysis in analyses:
            key = (
                analysis.lemma,
                analysis.root,
                analysis.pattern,
                analysis.pos,
                analysis.prefixes,
                analysis.suffixes,
            )
            current = unique.get(key)
            if current is None or analysis.confidence > current.confidence:
                unique[key] = analysis
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    -item.confidence,
                    -math.log1p(item.frequency),
                    item.lemma,
                    item.pattern or "",
                ),
            )
        )

    def analyze(
        self, token: str, *, min_confidence: float = 0.0
    ) -> tuple[MorphologicalAnalysis, ...]:
        """Return ranked analyses while preserving the supplied token in output.

        Arabic diacritics and tatweel are removed for lookup, but source text is
        never mutated.  ``min_confidence`` lets precision-sensitive callers
        ignore low-confidence template-only readings.
        """

        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        normalized_token = normalize(token, NormalizationMode.LOOKUP)
        cached = self._analyze_cached(normalized_token)
        if token == normalized_token:
            return tuple(item for item in cached if item.confidence >= min_confidence)
        return tuple(
            MorphologicalAnalysis(
                token=token,
                normalized=item.normalized,
                stem=item.stem,
                lemma=item.lemma,
                root=item.root,
                pattern=item.pattern,
                pos=item.pos,
                prefixes=item.prefixes,
                suffixes=item.suffixes,
                infixes=item.infixes,
                features=item.features,
                confidence=item.confidence,
                source=item.source,
                frequency=item.frequency,
            )
            for item in cached
            if item.confidence >= min_confidence
        )

    def best(self, token: str, *, min_confidence: float = 0.0) -> MorphologicalAnalysis | None:
        analyses = self.analyze(token, min_confidence=min_confidence)
        return analyses[0] if analyses else None

    def is_lexically_valid(self, token: str, *, min_confidence: float = 0.72) -> bool:
        """Return true only for lexicon-backed or licensed generated forms."""

        return any(
            analysis.is_lexical and analysis.confidence >= min_confidence
            for analysis in self.analyze(token, min_confidence=min_confidence)
        )

    def cache_info(self):
        """Expose cache statistics for profiling and regression tests."""

        return self._analyze_cached.cache_info()


@lru_cache(maxsize=1)
def default_lexicon() -> MorphologicalLexicon:
    """Return the process-wide immutable packaged lexicon."""

    return MorphologicalLexicon()


@lru_cache(maxsize=1)
def default_analyzer() -> MorphologicalAnalyzer:
    """Return the shared default analyzer and its bounded token cache."""

    return MorphologicalAnalyzer(default_lexicon())
