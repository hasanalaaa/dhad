"""Automated neural → deterministic distillation — V2 Phase 5 groundwork.

Every correction a user accepts from the probabilistic layer is evidence.
This pipeline turns recurring evidence into ordinary Dhad YAML rules, so the
deterministic moat grows automatically: what the transformer had to infer
yesterday, a compiled literal rule catches tomorrow at zero latency.

The safety chain is strict and self-verifying:

1. **Diff extraction** — an accepted ``(original, corrected)`` pair must
   reduce to exactly one contiguous token-level replacement; anything more
   ambiguous is rejected rather than guessed at.
2. **Support threshold** — a candidate becomes a rule only after being
   accepted ``min_support`` independent times.
3. **Self-verification** — the generated rule is compiled through the real
   engine (`dhad.rules.validate_rule_data` + ``Rule.apply``) and must fire
   on the bad example and stay silent on the good one, or it is discarded.
4. **Quarantine** — emitted rules land in ``drafts/`` (outside the engine's
   non-recursive rule glob) with ``autofix: false``; promotion into the
   live rule set stays a deliberate human act.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..rules import _compile
from ..text import normalize, tokenize

#: Distilled rules never auto-fix and carry a deliberately modest confidence
#: until a human promotes them out of quarantine.
DISTILLED_CONFIDENCE = 0.72



@dataclass(frozen=True, slots=True)
class CandidateRule:
    """A single-token replacement distilled from accepted corrections."""

    pattern: str
    suggestion: str
    support: int
    bad_example: str
    good_example: str

    @property
    def rule_id(self) -> str:
        # Rule ids are constrained to ^[A-Z0-9_:-]+$ by the schema, so the
        # Arabic pattern is identified by a stable content hash instead:
        # the same (pattern → suggestion) always distills to the same id.
        digest = hashlib.sha256(
            f"{self.pattern}→{self.suggestion}".encode()
        ).hexdigest()[:10]
        return f"DISTILLED_{digest.upper()}"


@dataclass(frozen=True, slots=True)
class DistillationReport:
    """Outcome of one harvest run."""

    accepted: tuple[CandidateRule, ...]
    rejected_ambiguous: int
    rejected_below_support: int
    rejected_verification: int
    written_files: tuple[str, ...] = ()


def extract_replacement(original: str, corrected: str) -> tuple[str, str] | None:
    """Reduce an accepted correction to one contiguous token replacement.

    Returns ``(bad_token_text, good_token_text)`` or ``None`` when the edit
    is not expressible as a single contiguous word-level substitution —
    the only shape conservative enough to distill automatically.
    """

    old_tokens = [t.text for t in tokenize(original)]
    new_tokens = [t.text for t in tokenize(corrected)]
    if not old_tokens or not new_tokens or old_tokens == new_tokens:
        return None
    prefix = 0
    while (
        prefix < len(old_tokens)
        and prefix < len(new_tokens)
        and old_tokens[prefix] == new_tokens[prefix]
    ):
        prefix += 1
    suffix = 0
    while (
        suffix < len(old_tokens) - prefix
        and suffix < len(new_tokens) - prefix
        and old_tokens[len(old_tokens) - 1 - suffix] == new_tokens[len(new_tokens) - 1 - suffix]
    ):
        suffix += 1
    old_core = old_tokens[prefix : len(old_tokens) - suffix]
    new_core = new_tokens[prefix : len(new_tokens) - suffix]
    if not old_core or not new_core:
        return None  # pure insertion/deletion: too ambiguous to distill
    if len(old_core) > 3 or len(new_core) > 3:
        return None  # long rewrites are style, not mechanics
    bad = " ".join(old_core)
    good = " ".join(new_core)
    if normalize(bad) == normalize(good):
        return None  # differs only in diacritics/tatweel: not a spelling rule
    return bad, good


class DistillationPipeline:
    """Aggregate accepted corrections and emit self-verified draft rules."""

    def __init__(self, *, min_support: int = 3) -> None:
        if min_support < 1:
            raise ValueError("min_support must be positive")
        self.min_support = min_support
        self._counts: Counter[tuple[str, str]] = Counter()
        self._examples: dict[tuple[str, str], tuple[str, str]] = {}
        self._ambiguous = 0

    def record(self, original: str, corrected: str) -> bool:
        """Record one accepted correction; True when it was distillable."""

        replacement = extract_replacement(original, corrected)
        if replacement is None:
            self._ambiguous += 1
            return False
        self._counts[replacement] += 1
        self._examples.setdefault(replacement, (original, corrected))
        return True

    def _build_rule_data(self, candidate: CandidateRule) -> dict:
        return {
            "schema_version": 2,
            "id": candidate.rule_id,
            "type": "literal",
            "category": "spelling",
            "severity": "warning",
            "confidence": DISTILLED_CONFIDENCE,
            "priority": 10,
            "autofix": False,
            "profiles": ["default"],
            "tags": ["distilled", "quarantine"],
            "pattern": candidate.pattern,
            "suggestion": candidate.suggestion,
            "message": f"الصواب المرجح: «{candidate.suggestion}»",
            "explanation": (
                f"قاعدة مقطرة آليًا من {candidate.support} تصحيحًا مقبولًا "
                "من الطبقة السياقية؛ لا تُطبَّق تلقائيًا قبل مراجعة بشرية."
            ),
            "examples": {"bad": candidate.bad_example, "good": candidate.good_example},
        }

    def _verify(self, candidate: CandidateRule) -> bool:
        """Compile through the real engine and prove fire/no-fire behavior."""

        try:
            compiled = _compile(self._build_rule_data(candidate), source="<distillation>")
        except (ValueError, TypeError, KeyError):
            return False
        fired_on_bad = compiled.apply(candidate.bad_example)
        fired_on_good = compiled.apply(candidate.good_example)
        return bool(fired_on_bad) and not fired_on_good

    def harvest(self, output_dir: Path | str | None = None) -> DistillationReport:
        """Emit every candidate that clears support and self-verification."""

        accepted: list[CandidateRule] = []
        below_support = 0
        failed_verification = 0
        for (pattern, suggestion), support in sorted(self._counts.items()):
            if support < self.min_support:
                below_support += 1
                continue
            bad_example, good_example = self._examples[(pattern, suggestion)]
            candidate = CandidateRule(
                pattern=pattern,
                suggestion=suggestion,
                support=support,
                bad_example=bad_example,
                good_example=good_example,
            )
            if not self._verify(candidate):
                failed_verification += 1
                continue
            accepted.append(candidate)

        written: list[str] = []
        if output_dir is not None and accepted:
            directory = Path(output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            for candidate in accepted:
                path = directory / f"{candidate.rule_id.lower()}.yaml"
                payload = [self._build_rule_data(candidate)]
                path.write_text(
                    yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
                written.append(str(path))

        return DistillationReport(
            accepted=tuple(accepted),
            rejected_ambiguous=self._ambiguous,
            rejected_below_support=below_support,
            rejected_verification=failed_verification,
            written_files=tuple(written),
        )

    def to_json(self) -> str:
        """Persist the aggregation state between sessions."""

        return json.dumps(
            {
                "min_support": self.min_support,
                "ambiguous": self._ambiguous,
                "entries": [
                    {
                        "pattern": pattern,
                        "suggestion": suggestion,
                        "count": count,
                        "example": list(self._examples[(pattern, suggestion)]),
                    }
                    for (pattern, suggestion), count in sorted(self._counts.items())
                ],
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, payload: str) -> "DistillationPipeline":
        data = json.loads(payload)
        pipeline = cls(min_support=int(data["min_support"]))
        pipeline._ambiguous = int(data.get("ambiguous", 0))
        for entry in data.get("entries", []):
            key = (str(entry["pattern"]), str(entry["suggestion"]))
            pipeline._counts[key] = int(entry["count"])
            example = entry.get("example", ["", ""])
            pipeline._examples[key] = (str(example[0]), str(example[1]))
        return pipeline
