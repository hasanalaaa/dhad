"""Conservative document semantics and consistency tracking for Arabic text."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

from jsonschema import Draft202012Validator

from .match import Match
from .spans import DisjointSpanIndex
from .syntax import DocumentParse, SentenceParse, SyntaxEngine, default_syntax_engine
from .text import NormalizationMode, Token, TokenKind, iter_tokens, normalize, sentence_spans

if TYPE_CHECKING:
    from .analysis import AnalysisContext

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_SEMANTICS_PATH = DATA_DIR / "semantics.json"
SEMANTICS_SCHEMA_PATH = DATA_DIR / "semantics.schema.json"

_WESTERN_DIGITS = frozenset("0123456789")
_ARABIC_INDIC_DIGITS = frozenset("٠١٢٣٤٥٦٧٨٩")
_WESTERN_TO_ARABIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
_ARABIC_TO_WESTERN = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


@dataclass(frozen=True, slots=True)
class ConsistencyChoice:
    """The established document preference for one variant family."""

    group_id: str
    preferred: str
    first_offset: int
    occurrences: int


@dataclass(frozen=True, slots=True)
class SemanticReport:
    """Auditable document-level semantic and consistency result."""

    text: str
    matches: tuple[Match, ...]
    choices: tuple[ConsistencyChoice, ...]
    numeral_style: str | None
    sentences_examined: int


@dataclass(frozen=True, slots=True)
class _VariantGroup:
    id: str
    variants: tuple[str, ...]
    canonical: str
    message: str


@dataclass(frozen=True, slots=True)
class _PhraseRule:
    id: str
    pattern: re.Pattern[str]
    replacement: str
    message: str
    explanation: str
    kind: str


class SemanticResource:
    """Schema-validated semantic and consistency knowledge."""

    def __init__(self, path: Path | str = DEFAULT_SEMANTICS_PATH) -> None:
        self.path = Path(path)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        schema = json.loads(SEMANTICS_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(raw)
        self.version = str(raw["version"])
        self.variant_groups = tuple(
            _VariantGroup(
                id=str(item["id"]),
                variants=tuple(str(value) for value in item["variants"]),
                canonical=str(item["canonical"]),
                message=str(item["message"]),
            )
            for item in raw["variant_groups"]
        )
        self.phrase_rules = tuple(
            _PhraseRule(
                id=str(item["id"]),
                pattern=re.compile(str(item["pattern"])),
                replacement=str(item.get("replacement", "")),
                message=str(item["message"]),
                explanation=str(item["explanation"]),
                kind=str(item["kind"]),
            )
            for item in raw["phrase_rules"]
        )
        self.contradiction_verbs = frozenset(str(item) for item in raw["contradiction_verbs"])


class DocumentConsistencyTracker:
    """Stateful first-observed preference tracker for streaming documents."""

    def __init__(self, resource: SemanticResource | None = None) -> None:
        self.resource = resource or default_semantic_resource()
        self._choices: dict[str, tuple[str, int, int]] = {}
        self._numeral_style: tuple[str, int] | None = None
        self._processed_characters = 0

    @property
    def choices(self) -> tuple[ConsistencyChoice, ...]:
        return tuple(
            ConsistencyChoice(group_id, preferred, offset, count)
            for group_id, (preferred, offset, count) in sorted(self._choices.items())
        )

    @property
    def numeral_style(self) -> str | None:
        return self._numeral_style[0] if self._numeral_style is not None else None

    def reset(self) -> None:
        self._choices.clear()
        self._numeral_style = None
        self._processed_characters = 0

    @staticmethod
    def _digit_style(value: str) -> str | None:
        has_western = any(char in _WESTERN_DIGITS for char in value)
        has_arabic = any(char in _ARABIC_INDIC_DIGITS for char in value)
        if has_western and has_arabic:
            return "mixed"
        if has_western:
            return "western"
        if has_arabic:
            return "arabic_indic"
        return None

    @staticmethod
    def _convert_digits(value: str, style: str) -> str:
        return value.translate(
            _WESTERN_TO_ARABIC if style == "arabic_indic" else _ARABIC_TO_WESTERN
        )

    def observe(
        self,
        text: str,
        *,
        base_offset: int | None = None,
        tokens: Sequence[Token] | None = None,
    ) -> tuple[Match, ...]:
        """Observe a chunk and return inconsistencies relative to prior text."""

        origin = self._processed_characters if base_offset is None else base_offset
        matches: list[Match] = []
        variant_lookup = {
            normalize(value, NormalizationMode.LOOKUP): group
            for group in self.resource.variant_groups
            for value in group.variants
        }
        for token in iter_tokens(text) if tokens is None else tokens:
            absolute_offset = origin + token.start
            if token.kind == TokenKind.ARABIC_WORD:
                normalized = normalize(token.text, NormalizationMode.LOOKUP)
                group = variant_lookup.get(normalized)
                if group is None:
                    continue
                current = self._choices.get(group.id)
                if current is None:
                    self._choices[group.id] = (token.text, absolute_offset, 1)
                    continue
                preferred, first_offset, count = current
                self._choices[group.id] = (preferred, first_offset, count + 1)
                if token.text != preferred:
                    matches.append(
                        Match(
                            rule_id=f"CONSISTENCY_VARIANT_{group.id.upper()}",
                            category="consistency",
                            message=group.message,
                            offset=absolute_offset,
                            length=len(token.text),
                            replacements=[preferred],
                            severity="warning",
                            explanation=(
                                f"استُخدمت الصيغة «{preferred}» أولًا عند الموضع {first_offset}؛ "
                                "يوصى بتوحيد الصياغة داخل المستند."
                            ),
                            autofix=False,
                            confidence=0.995,
                            priority=88,
                            tags=("document-consistency", "requires-approval"),
                            references=(f"Dhad semantics resource {self.resource.version}",),
                        )
                    )
            elif token.kind == TokenKind.NUMBER:
                style = self._digit_style(token.text)
                if style is None:
                    continue
                if style == "mixed":
                    matches.append(
                        Match(
                            rule_id="CONSISTENCY_NUMERAL_MIXED_TOKEN",
                            category="consistency",
                            message="يمزج هذا العدد بين نمطين من الأرقام.",
                            offset=absolute_offset,
                            length=len(token.text),
                            replacements=[],
                            severity="warning",
                            explanation="استخدم أرقامًا عربية هندية أو غربية متجانسة داخل العدد الواحد.",
                            autofix=False,
                            confidence=0.999,
                            priority=89,
                            tags=("document-consistency", "numerals", "requires-approval"),
                        )
                    )
                    continue
                if self._numeral_style is None:
                    self._numeral_style = (style, absolute_offset)
                    continue
                preferred_style, first_offset = self._numeral_style
                if style != preferred_style:
                    replacement = self._convert_digits(token.text, preferred_style)
                    matches.append(
                        Match(
                            rule_id="CONSISTENCY_NUMERAL_STYLE",
                            category="consistency",
                            message="نمط الأرقام غير متسق داخل المستند.",
                            offset=absolute_offset,
                            length=len(token.text),
                            replacements=[replacement],
                            severity="warning",
                            explanation=(
                                f"اعتمد المستند نمط «{preferred_style}» أولًا عند الموضع {first_offset}."
                            ),
                            autofix=False,
                            confidence=0.995,
                            priority=87,
                            tags=("document-consistency", "numerals", "requires-approval"),
                        )
                    )
        if base_offset is None:
            self._processed_characters += len(text)
        return tuple(matches)


class SemanticEngine:
    """High-precision semantic redundancy, contradiction, and consistency checks."""

    def __init__(
        self,
        syntax: SyntaxEngine | None = None,
        resource: SemanticResource | None = None,
    ) -> None:
        self.syntax = syntax or default_syntax_engine()
        self.resource = resource or default_semantic_resource()

    @staticmethod
    def _phrase_match(rule: _PhraseRule, text: str, start: int) -> Iterable[Match]:
        for found in rule.pattern.finditer(text):
            category = "semantics"
            severity = "warning" if rule.kind == "contradiction" else "hint"
            confidence = 0.99 if rule.kind == "contradiction" else 0.97
            yield Match(
                rule_id=rule.id,
                category=category,
                message=rule.message,
                offset=start + found.start(),
                length=found.end() - found.start(),
                replacements=[found.expand(rule.replacement)] if rule.replacement else [],
                severity=severity,
                explanation=rule.explanation,
                autofix=False,
                confidence=confidence,
                priority=42 if rule.kind == "contradiction" else 30,
                tags=("semantics", rule.kind, "requires-approval"),
                references=(f"Dhad semantics resource {rule.id}",),
            )

    def _contradictions(self, sentence: SentenceParse) -> tuple[Match, ...]:
        """Detect an explicitly negated repeat of the same lexical verb."""

        temporal_markers = {"أمس", "اليوم", "غدًا", "لاحقًا", "سابقًا", "ثم", "بعد", "قبل", "الآن"}
        licensed_surfaces = self.resource.contradiction_verbs

        def verb_key(token) -> str | None:
            if token.analysis is not None and token.pos == "verb":
                return token.analysis.lemma
            surface = normalize(token.text, NormalizationMode.LOOKUP)
            if surface not in licensed_surfaces:
                return None
            for prefix in ("ي", "ت", "ن", "أ"):
                if surface.startswith(prefix) and surface[1:] in licensed_surfaces:
                    return surface[1:]
            return surface

        def negator(token) -> str | None:
            surface = normalize(token.text, NormalizationMode.LOOKUP)
            if surface in {"لم", "لن", "لا"}:
                return surface
            if len(surface) > 2 and surface[0] in {"و", "ف"} and surface[1:] in {"لم", "لن", "لا"}:
                return surface[1:]
            return None

        prior_verbs: list[tuple[int, str]] = []
        out: list[Match] = []
        tokens = sentence.tokens
        for index, token in enumerate(tokens):
            key = verb_key(token)
            if key is not None:
                prior_verbs.append((index, key))
                continue
            if negator(token) is None or index + 1 >= len(tokens):
                continue
            following = tokens[index + 1]
            key = verb_key(following)
            if key is None:
                continue
            previous = next(
                ((position, value) for position, value in reversed(prior_verbs) if value == key),
                None,
            )
            if previous is None:
                continue
            previous_index, _ = previous
            if index - previous_index > 8:
                continue
            intervening = {
                normalize(item.text, NormalizationMode.LOOKUP)
                for item in tokens[previous_index + 1 : index + 2]
            }
            if intervening & temporal_markers:
                continue
            confidence = following.confidence if following.confidence > 0 else 0.90
            out.append(
                Match(
                    rule_id="SEMANTIC_EXPLICIT_SELF_CONTRADICTION",
                    category="semantics",
                    message="تجمع الجملة بين إثبات الفعل نفسه ونفيه دون قيد يرفع التعارض.",
                    offset=token.start,
                    length=following.end - token.start,
                    replacements=[],
                    severity="warning",
                    explanation=(
                        f"تكرر الفعل «{key}» مثبتًا ثم منفيًا؛ "
                        "أضف قيدًا زمنيًا أو سببيًا إن كان الاختلاف مقصودًا."
                    ),
                    autofix=False,
                    confidence=min(0.985, confidence),
                    priority=86,
                    tags=("semantics", "contradiction", "morphology-aware", "requires-review"),
                    references=("Dhad conservative contradiction pattern v1",),
                )
            )
        return tuple(out)

    def analyze(
        self,
        text: str,
        *,
        parsed: DocumentParse | None = None,
        context: AnalysisContext | None = None,
    ) -> SemanticReport:
        if context is not None:
            if context.text != text:
                raise ValueError("Analysis context does not correspond to the supplied text")
            parsed = parsed or context.parsed
        document = parsed or self.syntax.parse(text)
        if document.text != text:
            raise ValueError("Parsed document must belong to the same source text")

        tracker = DocumentConsistencyTracker(self.resource)
        matches = list(
            tracker.observe(
                text,
                base_offset=0,
                tokens=context.tokens if context is not None else None,
            )
        )
        sentences = context.sentences if context is not None else sentence_spans(text)
        for sentence_span, sentence_parse in zip(sentences, document.sentences):
            for rule in self.resource.phrase_rules:
                matches.extend(self._phrase_match(rule, sentence_span.text, sentence_span.start))
            matches.extend(self._contradictions(sentence_parse))
        # Stable conflict resolution within the semantic subsystem: document
        # consistency outranks a broader semantic phrase at the same span.
        matches.sort(key=lambda item: (item.offset, -item.priority, item.rule_id))
        accepted: list[Match] = []
        accepted_spans = DisjointSpanIndex()
        for candidate in matches:
            if not accepted_spans.overlaps(candidate.offset, candidate.end):
                accepted_spans.add(candidate.offset, candidate.end)
                accepted.append(candidate)
        return SemanticReport(
            text=text,
            matches=tuple(sorted(accepted, key=lambda item: (item.offset, item.rule_id))),
            choices=tracker.choices,
            numeral_style=tracker.numeral_style,
            sentences_examined=len(document.sentences),
        )

    def check_text(
        self,
        text: str,
        *,
        parsed: DocumentParse | None = None,
        context: AnalysisContext | None = None,
    ) -> tuple[Match, ...]:
        return self.analyze(text, parsed=parsed, context=context).matches


@lru_cache(maxsize=1)
def default_semantic_resource() -> SemanticResource:
    return SemanticResource()


@lru_cache(maxsize=1)
def default_semantic_engine() -> SemanticEngine:
    return SemanticEngine(default_syntax_engine(), default_semantic_resource())
