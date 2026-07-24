"""Deterministic authorial stylometry — foundation of the v2 personal voice.

The module learns an explainable numeric fingerprint of one writer's Arabic
style and measures how far any new text drifts from that fingerprint. It is
the measurement substrate every later "write in *my* voice" feature builds on:
before the engine can generate in a user's voice it must be able to quantify
that voice, deterministically and auditable per dimension.

Design guarantees, in line with the founding doctrine of the engine:

* **Privacy first** — when wired through :class:`dhad.Dhad`, learning and
  comparison operate on the PII-masked view of the text; raw e-mails, phones,
  and URLs never reach feature extraction.
* **Aggregates only** — a :class:`VoiceProfile` stores per-feature running
  statistics (count/mean/variance). The source text is not recoverable from a
  stored profile, so profiles are safe to sync or share.
* **Explainable** — every feature has a closed identifier and an Arabic
  explanation; every deviation reports observed value, expected range, and a
  bounded score. No opaque embeddings.
* **Never hides an error** — :func:`personalize_matches` may annotate and
  re-weight *style* matches against the author's own habits; it never touches
  spelling, grammar, or any other category, and never drops a match.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Iterable, Sequence

from .match import Match
from .text import (
    AR_DIACRITIC,
    TATWEEL,
    normalize,
    sentences,
    tokenize,
)

PROFILE_SCHEMA_VERSION = "1"

#: Sentences shorter than this many word tokens carry too little rhythm
#: signal and are ignored by the sentence-length statistics (titles, list
#: markers, greetings). They still count toward lexical features.
_MIN_SENTENCE_TOKENS = 2

#: Connectors whose relative frequency is a strong, stable authorial signal
#: in Arabic prose. Closed list; extending it is a schema-version change.
CONNECTORS: tuple[str, ...] = (
    "و",
    "ف",
    "ثم",
    "لكن",
    "بل",
    "كما",
    "حيث",
    "اذ",
    "لذلك",
    "غير",
)

#: High-frequency function words tracked per-mille. Closed list, normalized
#: (hamza/alef folded by :func:`dhad.text.normalize` lookup mode).
FUNCTION_WORDS: tuple[str, ...] = (
    "في",
    "من",
    "على",
    "الى",
    "عن",
    "ان",
    "قد",
    "لقد",
    "هذا",
    "هذه",
    "ذلك",
    "التي",
    "الذي",
    "كان",
    "ليس",
)

_DIACRITIC_RE = re.compile(f"[{AR_DIACRITIC}]")
_ARABIC_DIGIT_RE = re.compile(r"[٠-٩]")
_WESTERN_DIGIT_RE = re.compile(r"[0-9]")

#: Closed feature vocabulary: identifier → (Arabic explanation, weight).
#: Weights express how much a dimension contributes to the overall drift
#: score; rhythm and connector habits dominate because they are the most
#: stable authorial signals across topics.
FEATURES: dict[str, tuple[str, float]] = {
    "sentence_length_mean": ("متوسط طول الجملة بالكلمات", 3.0),
    "sentence_length_std": ("تذبذب طول الجمل", 2.0),
    "word_length_mean": ("متوسط طول الكلمة العربية بالحروف", 1.5),
    "type_token_ratio": ("الثراء المعجمي (تنوع المفردات)", 2.0),
    "hapax_ratio": ("نسبة المفردات المستعملة مرة واحدة", 1.0),
    "diacritics_density": ("كثافة التشكيل لكل حرف عربي", 1.5),
    "tatweel_rate": ("استعمال التطويل (الكشيدة)", 0.5),
    "punctuation_rate": ("كثافة الترقيم لكل كلمة", 1.5),
    "arabic_comma_share": ("تفضيل الفاصلة العربية «،» على اللاتينية", 1.0),
    "question_share": ("نسبة الجمل الاستفهامية", 1.0),
    "exclamation_share": ("نسبة الجمل التعجبية", 1.0),
    "connector_rate": ("كثافة أدوات الربط لكل جملة", 2.5),
    "function_word_rate": ("كثافة الكلمات الوظيفية لكل ألف كلمة", 2.0),
    "latin_share": ("نسبة الكلمات اللاتينية المقحمة", 1.0),
    "arabic_digit_share": ("تفضيل الأرقام العربية المشرقية ٠-٩", 0.5),
    **{
        f"connector_{item}": (f"تواتر أداة الربط «{item}» لكل ألف كلمة", 0.4)
        for item in CONNECTORS
    },
    **{
        f"funcword_{item}": (f"تواتر الكلمة الوظيفية «{item}» لكل ألف كلمة", 0.25)
        for item in FUNCTION_WORDS
    },
}


@dataclass(frozen=True, slots=True)
class StyleFingerprint:
    """Deterministic feature vector for one text sample."""

    token_count: int
    sentence_count: int
    features: tuple[tuple[str, float], ...]

    def as_dict(self) -> dict[str, float]:
        return dict(self.features)


@dataclass(frozen=True, slots=True)
class FeatureStat:
    """Welford running statistics for one feature across learned samples."""

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def push(self, value: float) -> "FeatureStat":
        count = self.count + 1
        delta = value - self.mean
        mean = self.mean + delta / count
        m2 = self.m2 + delta * (value - mean)
        return FeatureStat(count=count, mean=mean, m2=m2)

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)


@dataclass(frozen=True, slots=True)
class FeatureDeviation:
    """How far one observed feature sits from the learned habit."""

    feature: str
    observed: float
    expected_mean: float
    expected_std: float
    score: float
    weight: float
    explanation: str


@dataclass(frozen=True, slots=True)
class VoiceDeviationReport:
    """Bounded, per-dimension drift of a text from a learned voice."""

    drift_score: float
    alignment: float
    reliable: bool
    deviations: tuple[FeatureDeviation, ...]

    def top_deviations(self, limit: int = 5) -> tuple[FeatureDeviation, ...]:
        ranked = sorted(
            self.deviations, key=lambda item: (-item.score * item.weight, item.feature)
        )
        return tuple(ranked[:limit])


def _word_tokens(text: str) -> list:
    return [token for token in tokenize(text) if token.is_word]


def extract_fingerprint(text: str) -> StyleFingerprint:
    """Extract the closed deterministic feature vector from one sample."""

    words = _word_tokens(text)
    arabic_words = [token for token in words if token.is_arabic]
    sentence_list = sentences(text)
    values: dict[str, float] = {name: 0.0 for name in FEATURES}

    sentence_token_counts = []
    question_count = 0
    exclamation_count = 0
    for sentence_text, _start, end in sentence_list:
        count = len(_word_tokens(sentence_text))
        if count >= _MIN_SENTENCE_TOKENS:
            sentence_token_counts.append(count)
        # Sentence spans exclude their terminators, so examine the run of
        # closing punctuation that follows the span in the source string.
        terminator_run = text[end : end + 3]
        haystack = sentence_text + terminator_run
        if "؟" in haystack or "?" in haystack:
            question_count += 1
        if "!" in haystack or "﹗" in haystack:
            exclamation_count += 1
    if sentence_token_counts:
        mean = sum(sentence_token_counts) / len(sentence_token_counts)
        values["sentence_length_mean"] = mean
        values["sentence_length_std"] = math.sqrt(
            sum((count - mean) ** 2 for count in sentence_token_counts)
            / len(sentence_token_counts)
        )
    if sentence_list:
        values["question_share"] = question_count / len(sentence_list)
        values["exclamation_share"] = exclamation_count / len(sentence_list)

    if arabic_words:
        stripped = [_DIACRITIC_RE.sub("", token.text).replace(TATWEEL, "") for token in arabic_words]
        values["word_length_mean"] = sum(len(item) for item in stripped) / len(stripped)
        normalized = [normalize(token.text) for token in arabic_words]
        counts = Counter(normalized)
        values["type_token_ratio"] = len(counts) / len(normalized)
        values["hapax_ratio"] = sum(
            1 for _word, freq in counts.items() if freq == 1
        ) / len(normalized)
        arabic_char_count = sum(len(item) for item in stripped)
        diacritic_count = sum(len(_DIACRITIC_RE.findall(token.text)) for token in arabic_words)
        if arabic_char_count:
            values["diacritics_density"] = diacritic_count / arabic_char_count
            values["tatweel_rate"] = sum(
                token.text.count(TATWEEL) for token in arabic_words
            ) / arabic_char_count
        per_mille = 1000.0 / len(normalized)
        connector_hits = 0
        for connector in CONNECTORS:
            frequency = counts.get(connector, 0)
            values[f"connector_{connector}"] = frequency * per_mille
            connector_hits += frequency
        function_hits = 0
        for word in FUNCTION_WORDS:
            frequency = counts.get(word, 0)
            values[f"funcword_{word}"] = frequency * per_mille
            function_hits += frequency
        values["function_word_rate"] = function_hits * per_mille
        if sentence_list:
            values["connector_rate"] = connector_hits / len(sentence_list)

    if words:
        latin_count = sum(1 for token in words if not token.is_arabic and token.text.isascii())
        values["latin_share"] = latin_count / len(words)
        arabic_comma = text.count("،")
        latin_comma = text.count(",")
        if arabic_comma + latin_comma:
            values["arabic_comma_share"] = arabic_comma / (arabic_comma + latin_comma)
        punctuation_count = sum(text.count(mark) for mark in "،,؛;:.!؟?…«»\"'()-—")
        values["punctuation_rate"] = punctuation_count / len(words)
        arabic_digits = len(_ARABIC_DIGIT_RE.findall(text))
        western_digits = len(_WESTERN_DIGIT_RE.findall(text))
        if arabic_digits + western_digits:
            values["arabic_digit_share"] = arabic_digits / (arabic_digits + western_digits)

    return StyleFingerprint(
        token_count=len(words),
        sentence_count=len(sentence_list),
        features=tuple(sorted(values.items())),
    )


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """Aggregate, non-reversible model of one author's writing habits.

    Instances are immutable: :meth:`update` folds a new sample in and returns
    a new profile, which keeps concurrent readers safe and makes persistence
    an explicit act.
    """

    version: str = PROFILE_SCHEMA_VERSION
    sample_count: int = 0
    token_count: int = 0
    sentence_count: int = 0
    stats: tuple[tuple[str, FeatureStat], ...] = field(default_factory=tuple)

    # -- learning ---------------------------------------------------------

    @classmethod
    def fit(cls, texts: Iterable[str]) -> "VoiceProfile":
        profile = cls()
        for text in texts:
            profile = profile.update(text)
        return profile

    def update(self, text: str) -> "VoiceProfile":
        fingerprint = extract_fingerprint(text)
        if fingerprint.token_count == 0:
            return self
        current = dict(self.stats)
        for name, value in fingerprint.features:
            current[name] = current.get(name, FeatureStat()).push(value)
        return VoiceProfile(
            version=self.version,
            sample_count=self.sample_count + 1,
            token_count=self.token_count + fingerprint.token_count,
            sentence_count=self.sentence_count + fingerprint.sentence_count,
            stats=tuple(sorted(current.items())),
        )

    # -- reliability ------------------------------------------------------

    @property
    def is_reliable(self) -> bool:
        """Whether the profile has seen enough text to judge new samples."""

        return self.sample_count >= 3 and self.token_count >= 300

    # -- comparison -------------------------------------------------------

    def compare(self, text: str) -> VoiceDeviationReport:
        """Score how far ``text`` drifts from the learned voice.

        Every deviation is bounded: a robust z-like score is mapped through
        ``z / (z + 2)`` into ``[0, 1)`` so a single wild feature cannot
        dominate, and the overall drift is the weighted mean of the bounded
        scores.
        """

        fingerprint = extract_fingerprint(text)
        stats = dict(self.stats)
        deviations: list[FeatureDeviation] = []
        weighted_total = 0.0
        weight_total = 0.0
        for name, observed in fingerprint.features:
            stat = stats.get(name)
            explanation, weight = FEATURES.get(name, (name, 0.0))
            if stat is None or stat.count == 0 or weight == 0.0:
                continue
            # Robust floor keeps near-constant features from exploding the
            # score on tiny numeric noise.
            floor = max(abs(stat.mean) * 0.10, 0.02)
            spread = max(stat.std, floor)
            z = abs(observed - stat.mean) / spread
            score = z / (z + 2.0)
            deviations.append(
                FeatureDeviation(
                    feature=name,
                    observed=observed,
                    expected_mean=stat.mean,
                    expected_std=stat.std,
                    score=score,
                    weight=weight,
                    explanation=explanation,
                )
            )
            weighted_total += score * weight
            weight_total += weight
        drift = weighted_total / weight_total if weight_total else 0.0
        return VoiceDeviationReport(
            drift_score=drift,
            alignment=1.0 - drift,
            reliable=self.is_reliable and fingerprint.token_count >= 30,
            deviations=tuple(deviations),
        )

    # -- persistence ------------------------------------------------------

    def to_json(self) -> str:
        payload = {
            "version": self.version,
            "sample_count": self.sample_count,
            "token_count": self.token_count,
            "sentence_count": self.sentence_count,
            "stats": {
                name: {"count": stat.count, "mean": stat.mean, "m2": stat.m2}
                for name, stat in self.stats
            },
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "VoiceProfile":
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Voice profile payload must be a JSON object")
        if str(data.get("version")) != PROFILE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported voice profile version: {data.get('version')!r}"
            )
        raw_stats = data.get("stats", {})
        if not isinstance(raw_stats, dict):
            raise ValueError("Voice profile stats must be a JSON object")
        stats: list[tuple[str, FeatureStat]] = []
        for name, item in raw_stats.items():
            count = int(item["count"])
            mean = float(item["mean"])
            m2 = float(item["m2"])
            if count < 0 or m2 < -1e-9:
                raise ValueError(f"Corrupt statistics for feature {name!r}")
            stats.append((name, FeatureStat(count=count, mean=mean, m2=max(m2, 0.0))))
        profile = cls(
            version=str(data["version"]),
            sample_count=int(data.get("sample_count", 0)),
            token_count=int(data.get("token_count", 0)),
            sentence_count=int(data.get("sentence_count", 0)),
            stats=tuple(sorted(stats)),
        )
        if profile.sample_count < 0 or profile.token_count < 0:
            raise ValueError("Voice profile counters must be non-negative")
        return profile


#: Tag prefixes attached by :func:`personalize_matches`.
VOICE_ALIGNED_TAG = "voice:aligned"
VOICE_DIVERGENT_TAG = "voice:divergent"

_STYLE_ONLY = frozenset({"style"})


def personalize_matches(
    matches: Sequence[Match],
    profile: VoiceProfile,
    report: VoiceDeviationReport | None = None,
    *,
    text: str | None = None,
    divergence_threshold: float = 0.45,
) -> list[Match]:
    """Annotate style matches with the author's own habits.

    Only ``category == "style"`` matches are touched; every other category is
    returned byte-for-byte identical, and no match is ever removed. Style
    matches gain a ``voice:aligned`` or ``voice:divergent`` tag and a small
    priority nudge so that advice conflicting with a *consistent, learned*
    habit ranks below advice the author already tends to follow.
    """

    if report is None:
        if text is None:
            raise ValueError("personalize_matches requires either report or text")
        report = profile.compare(text)
    if not report.reliable:
        return list(matches)
    divergent = report.drift_score >= divergence_threshold
    personalized: list[Match] = []
    for match in matches:
        if match.category not in _STYLE_ONLY:
            personalized.append(match)
            continue
        tag = VOICE_DIVERGENT_TAG if divergent else VOICE_ALIGNED_TAG
        nudge = 1 if divergent else -1
        personalized.append(
            replace(
                match,
                tags=(*match.tags, tag),
                priority=match.priority + nudge,
            )
        )
    return personalized


def merge_profiles(first: VoiceProfile, second: VoiceProfile) -> VoiceProfile:
    """Merge two profiles learned separately (Chan et al. parallel Welford)."""

    if first.version != second.version:
        raise ValueError("Cannot merge voice profiles with different versions")
    if second.sample_count == 0:
        return first
    if first.sample_count == 0:
        return second
    merged: dict[str, FeatureStat] = dict(first.stats)
    for name, stat in second.stats:
        base = merged.get(name)
        if base is None or base.count == 0:
            merged[name] = stat
            continue
        count = base.count + stat.count
        delta = stat.mean - base.mean
        mean = base.mean + delta * stat.count / count
        m2 = base.m2 + stat.m2 + delta * delta * base.count * stat.count / count
        merged[name] = FeatureStat(count=count, mean=mean, m2=m2)
    return VoiceProfile(
        version=first.version,
        sample_count=first.sample_count + second.sample_count,
        token_count=first.token_count + second.token_count,
        sentence_count=first.sentence_count + second.sentence_count,
        stats=tuple(sorted(merged.items())),
    )
