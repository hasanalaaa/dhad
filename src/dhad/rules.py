"""Dhad Rule Engine v2: schema-validated, contextual, and explainable rules."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

import yaml
from jsonschema import Draft202012Validator

from .automata import LiteralAutomaton
from .match import Match
from .spans import FrozenSpanIndex
from .text import B_LEFT, B_RIGHT, sentence_spans

if TYPE_CHECKING:
    from .analysis import AnalysisContext

RULES_DIR = Path(__file__).parent / "data" / "rules"
RULE_SCHEMA_PATH = Path(__file__).parent / "data" / "rule.schema.json"
AL_PREFIXES = ("وال", "فال", "بال", "كال", "لل", "ال")
RULE_TYPES = ("literal", "regex", "token_sequence", "context", "exception", "document")

_DEFAULT_CONFIDENCE = {
    "spelling": 0.99,
    "punctuation": 0.98,
    "grammar": 0.90,
    "style": 0.72,
    "dialect": 0.72,
}
_DEFAULT_PRIORITY = {
    "spelling": 80,
    "punctuation": 70,
    "grammar": 60,
    "dialect": 30,
    "style": 20,
}


@dataclass(frozen=True, slots=True)
class RuleException:
    compiled: re.Pattern[str]
    scope: str
    window: int = 60


@dataclass(slots=True)
class Rule:
    id: str
    type: str
    category: str
    message: str
    compiled: re.Pattern[str] | None = None
    suggestions: list[str] = field(default_factory=list)
    severity: str = "error"
    explanation: str = ""
    examples: dict[str, str] = field(default_factory=dict)
    has_prefix_group: bool = False
    autofix: bool = False
    confidence: float = 1.0
    priority: int = 0
    tags: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ("default",)
    context_before: re.Pattern[str] | None = None
    context_after: re.Pattern[str] | None = None
    context_window: int = 60
    exceptions: tuple[RuleException, ...] = ()
    target_rules: tuple[str, ...] = ()
    document: dict[str, Any] | None = None
    literal_pattern: str | None = None

    def is_enabled_for(self, active_profiles: frozenset[str]) -> bool:
        return "all" in self.profiles or bool(active_profiles.intersection(self.profiles))

    def _context_allows(self, text: str, match: re.Match[str]) -> bool:
        if self.context_before is not None:
            before = text[max(0, match.start() - self.context_window) : match.start()]
            if self.context_before.search(before) is None:
                return False
        if self.context_after is not None:
            after = text[match.end() : min(len(text), match.end() + self.context_window)]
            if self.context_after.search(after) is None:
                return False
        return True

    def _is_exception(
        self,
        text: str,
        match: re.Match[str],
        context: AnalysisContext | None = None,
    ) -> bool:
        for exception in self.exceptions:
            if exception.scope == "match":
                haystack = match.group()
            elif exception.scope == "window":
                haystack = text[
                    max(0, match.start() - exception.window) : min(
                        len(text), match.end() + exception.window
                    )
                ]
            else:
                if context is not None:
                    try:
                        haystack = context.sentence_at(match.start()).text
                    except (IndexError, LookupError):
                        haystack = match.group()
                else:
                    haystack = next(
                        (
                            sentence.text
                            for sentence in sentence_spans(text)
                            if sentence.start
                            <= match.start()
                            < max(sentence.end, sentence.start + 1)
                        ),
                        match.group(),
                    )
            if exception.compiled.search(haystack):
                return True
        return False

    def _build_match(self, source_match: re.Match[str], replacements: list[str]) -> Match:
        return Match(
            rule_id=self.id,
            category=self.category,
            message=self.message,
            offset=source_match.start(),
            length=source_match.end() - source_match.start(),
            replacements=replacements,
            severity=self.severity,
            explanation=self.explanation,
            autofix=self.autofix,
            confidence=self.confidence,
            priority=self.priority,
            tags=self.tags,
            references=self.references,
            profiles=self.profiles,
        )

    def _apply_standard(
        self, text: str, context: AnalysisContext | None = None
    ) -> list[Match]:
        if self.compiled is None:
            return []
        out: list[Match] = []
        for match in self.compiled.finditer(text):
            if not self._context_allows(text, match) or self._is_exception(text, match, context):
                continue
            prefix = match.groupdict().get("dhad_prefix", "") if self.has_prefix_group else ""
            replacements: list[str] = []
            for suggestion in self.suggestions:
                if self.has_prefix_group:
                    replacements.append(prefix + suggestion)
                    continue
                try:
                    replacements.append(match.expand(suggestion))
                except re.error:
                    replacements.append(suggestion)
            out.append(self._build_match(match, replacements))
        return out

    def apply_literal_hit(
        self,
        text: str,
        start: int,
        context: AnalysisContext | None = None,
    ) -> Match | None:
        """Build a match for a boundary-checked automaton occurrence."""

        if self.compiled is None:
            return None
        source_match = self.compiled.match(text, start)
        if source_match is None:
            return None
        if not self._context_allows(text, source_match) or self._is_exception(
            text, source_match, context
        ):
            return None
        return self._build_match(source_match, list(self.suggestions))

    def _apply_document(self, text: str) -> list[Match]:
        config = self.document or {}
        mode = config.get("mode")
        if mode == "consistency":
            preferred = config["preferred"]
            variants = config["variants"]
            seen = {
                variant
                for variant in variants
                if re.search(B_LEFT + re.escape(variant) + B_RIGHT, text)
            }
            if len(seen) < 2:
                return []
            out: list[Match] = []
            for variant in variants:
                if variant == preferred:
                    continue
                for match in re.finditer(B_LEFT + re.escape(variant) + B_RIGHT, text):
                    out.append(self._build_match(match, [preferred]))
            return out
        if mode == "occurrence":
            pattern = config.get("regex") or (B_LEFT + re.escape(config["pattern"]) + B_RIGHT)
            matches = list(re.finditer(pattern, text))
            if len(matches) < config.get("min_occurrences", 2):
                return []
            if config.get("report", "first") == "first":
                matches = matches[:1]
            return [self._build_match(match, self.suggestions) for match in matches]
        return []

    def apply(self, text: str, *, context: AnalysisContext | None = None) -> list[Match]:
        if self.type in {"exception"}:
            return []
        if self.type == "document":
            return self._apply_document(text)
        return self._apply_standard(text, context)

    def exception_spans(self, text: str) -> list[tuple[int, int]]:
        if self.type != "exception" or self.compiled is None:
            return []
        return [(match.start(), match.end()) for match in self.compiled.finditer(text)]


def _infer_type(raw: dict[str, Any]) -> str:
    if "type" in raw:
        return str(raw["type"])
    if "document" in raw:
        return "document"
    if "target_rules" in raw:
        return "exception"
    if "tokens" in raw:
        return "token_sequence"
    if "context" in raw:
        return "context"
    if "regex" in raw:
        return "regex"
    return "literal"


def canonicalize_rule(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade legacy v1 dictionaries into the explicit v2 schema."""

    if not isinstance(raw, dict):
        raise TypeError("Each rule must be a YAML mapping")
    data = dict(raw)
    category = data.get("category", "")
    severity = data.get("severity", "error")
    data.setdefault("schema_version", 2)
    data.setdefault("type", _infer_type(data))
    data.setdefault("severity", severity)
    data.setdefault("confidence", _DEFAULT_CONFIDENCE.get(category, 0.8))
    data.setdefault("priority", _DEFAULT_PRIORITY.get(category, 0))
    data.setdefault("autofix", category == "spelling" and severity == "error")
    data.setdefault("tags", [])
    data.setdefault("references", [])
    data.setdefault("profiles", ["default"])
    data.setdefault("exceptions", [])
    data.setdefault("explanation", "")
    if "suggestion" not in data and "suggestions" not in data:
        data["suggestions"] = []
    return data


def _load_schema() -> dict[str, Any]:
    return json.loads(RULE_SCHEMA_PATH.read_text(encoding="utf-8"))


_SCHEMA_VALIDATOR = Draft202012Validator(_load_schema())


def validate_rule_data(raw: dict[str, Any], *, source: str = "<memory>") -> dict[str, Any]:
    canonical = canonicalize_rule(raw)
    errors = sorted(_SCHEMA_VALIDATOR.iter_errors(canonical), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors
        )
        rid = canonical.get("id", "<unknown>")
        raise ValueError(f"{source}:{rid}: rule schema validation failed: {details}")
    return canonical


def _compile_pattern(data: dict[str, Any]) -> tuple[re.Pattern[str] | None, bool]:
    rule_type = data["type"]
    has_prefix_group = False
    if rule_type == "document":
        return None, False
    if rule_type == "token_sequence":
        sequence = ""
        for index, token in enumerate(data["tokens"]):
            optional = False
            if isinstance(token, str):
                piece = re.escape(token)
            else:
                optional = bool(token.get("optional", False))
                piece = re.escape(token["literal"]) if "literal" in token else token["regex"]
            wrapped = rf"(?:{piece})"
            if index == 0:
                sequence += rf"(?:{wrapped}\s+)?" if optional else wrapped
            else:
                sequence += rf"(?:\s+{wrapped})?" if optional else rf"\s+{wrapped}"
        pattern = B_LEFT + sequence + B_RIGHT
    elif "regex" in data:
        pattern = data["regex"]
    else:
        literal = data["pattern"]
        prefixes = data.get("prefixes")
        if prefixes:
            prefix_list = AL_PREFIXES if prefixes is True else tuple(prefixes)
            alternatives = "|".join(re.escape(prefix) for prefix in prefix_list)
            pattern = (
                B_LEFT + rf"(?P<dhad_prefix>(?:{alternatives})?)" + re.escape(literal) + B_RIGHT
            )
            has_prefix_group = True
        else:
            pattern = B_LEFT + re.escape(literal) + B_RIGHT
    try:
        return re.compile(pattern), has_prefix_group
    except re.error as exc:
        raise ValueError(f"Rule {data['id']}: invalid regex: {exc}") from exc


def _compile_exception(raw: dict[str, Any], rule_id: str) -> RuleException:
    pattern = raw.get("regex") or re.escape(raw["pattern"])
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Rule {rule_id}: invalid exception regex: {exc}") from exc
    return RuleException(compiled, raw["scope"], raw.get("window", 60))


def _compile(raw: dict[str, Any], *, source: str = "<memory>") -> Rule:
    data = validate_rule_data(raw, source=source)
    compiled, has_prefix_group = _compile_pattern(data)
    context = data.get("context", {})
    try:
        before = re.compile(context["before"] + r"\Z") if context.get("before") else None
        after = re.compile(r"\A" + context["after"]) if context.get("after") else None
    except re.error as exc:
        raise ValueError(f"Rule {data['id']}: invalid context regex: {exc}") from exc
    suggestions: list[str] = []
    if "suggestion" in data:
        suggestions.append(data["suggestion"])
    suggestions.extend(data.get("suggestions", []))
    return Rule(
        id=data["id"],
        type=data["type"],
        category=data["category"],
        message=data["message"],
        compiled=compiled,
        suggestions=suggestions,
        severity=data["severity"],
        explanation=data.get("explanation", ""),
        examples=data["examples"],
        has_prefix_group=has_prefix_group,
        autofix=data["autofix"],
        confidence=float(data["confidence"]),
        priority=int(data["priority"]),
        tags=tuple(data["tags"]),
        references=tuple(data["references"]),
        profiles=tuple(data["profiles"]),
        context_before=before,
        context_after=after,
        context_window=context.get("window", 60),
        exceptions=tuple(
            _compile_exception(item, data["id"]) for item in data.get("exceptions", [])
        ),
        target_rules=tuple(data.get("target_rules", [])),
        document=data.get("document"),
        literal_pattern=(
            str(data["pattern"])
            if data["type"] == "literal" and not data.get("prefixes")
            else None
        ),
    )


class RuleEngine:
    """Load, validate, profile-filter, and execute Rule Engine v2 rules."""

    def __init__(self, rules_dir: Path | str = RULES_DIR):
        self.rules: list[Rule] = []
        seen: set[str] = set()
        for path in sorted(Path(rules_dir).glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            if not isinstance(data, list):
                raise ValueError(f"{path.name}: top-level YAML value must be a list")
            for raw in data:
                rule = _compile(raw, source=path.name)
                if rule.id in seen:
                    raise ValueError(f"Duplicate rule id: {rule.id} in {path.name}")
                seen.add(rule.id)
                self.rules.append(rule)
        self._literal_matcher = LiteralAutomaton(
            [
                (index, rule.literal_pattern)
                for index, rule in enumerate(self.rules)
                if rule.literal_pattern is not None
            ]
        )

    def check(
        self,
        text: str,
        *,
        profiles: Iterable[str] = ("default",),
        context: AnalysisContext | None = None,
    ) -> list[Match]:
        if context is not None and context.text != text:
            raise ValueError("Analysis context must belong to the same source text")
        active_profiles = frozenset(profiles)
        enabled = [
            (index, rule)
            for index, rule in enumerate(self.rules)
            if rule.is_enabled_for(active_profiles)
        ]
        suppressors = [rule for _index, rule in enabled if rule.type == "exception"]
        ordinary = [(index, rule) for index, rule in enabled if rule.type != "exception"]

        blocked_spans: dict[str, list[tuple[int, int]]] = {}
        for suppressor in suppressors:
            spans = suppressor.exception_spans(text)
            for target in suppressor.target_rules:
                blocked_spans.setdefault(target, []).extend(spans)
        blocked = {
            rule_id: FrozenSpanIndex(spans) for rule_id, spans in blocked_spans.items()
        }

        literal_hits: dict[int, list[int]] = {}
        if len(self._literal_matcher):
            for hit in self._literal_matcher.finditer(text):
                literal_hits.setdefault(hit.rule_index, []).append(hit.start)

        out: list[Match] = []
        for index, rule in ordinary:
            if rule.literal_pattern is None:
                matches = rule.apply(text, context=context)
            else:
                matches = [
                    match
                    for start in literal_hits.get(index, ())
                    if (match := rule.apply_literal_hit(text, start, context)) is not None
                ]
            for match in matches:
                spans = blocked.get(rule.id)
                if spans is not None and spans.overlaps_match(match):
                    continue
                out.append(match)
        return out
