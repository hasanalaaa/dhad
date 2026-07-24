"""Independent benchmark loading, validation, scoring, and agreement metrics.

The evaluator intentionally knows nothing about YAML rule examples.  It consumes
versioned gold annotations and compares them with :class:`dhad.match.Match`
objects using stable source offsets.  This keeps product measurements independent
from the implementation being evaluated.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from jsonschema import Draft202012Validator

from .match import Match
from .text import tokenize

PACKAGE_DATA_DIR = Path(__file__).parent / "data"
BENCHMARK_SCHEMA_PATH = PACKAGE_DATA_DIR / "benchmark.schema.json"
DEFAULT_BENCHMARK_DIR = PACKAGE_DATA_DIR / "benchmarks" / "gold_v1"
VALID_SPLITS = frozenset({"train", "dev", "test"})
MECHANICAL_CATEGORIES = frozenset({"spelling", "grammar", "punctuation"})
STYLE_CATEGORIES = frozenset({"style"})
DIALECT_CATEGORIES = frozenset({"dialect"})
NEURAL_CATEGORIES = frozenset({"neural_suggestion"})
SEMANTIC_CATEGORIES = frozenset({"semantics", "consistency"})
DIACRITICS_CATEGORIES = frozenset({"diacritics"})
BENCHMARK_SCOPES: Mapping[str, frozenset[str] | None] = {
    "all": None,
    "mechanical": MECHANICAL_CATEGORIES,
    "style": STYLE_CATEGORIES,
    "dialect": DIALECT_CATEGORIES,
    "neural": NEURAL_CATEGORIES,
    "semantics": SEMANTIC_CATEGORIES,
    "diacritics": DIACRITICS_CATEGORIES,
}


@dataclass(frozen=True, slots=True)
class GoldAnnotation:
    """One gold issue anchored to the original text."""

    category: str
    offset: int
    length: int
    accepted_replacements: tuple[str, ...] = ()
    label: str = ""
    severity: str = "error"

    def __post_init__(self) -> None:
        if self.offset < 0 or self.length <= 0:
            raise ValueError("Gold annotation span must be positive and ordered")
        if not self.category:
            raise ValueError("Gold annotation category is required")

    @property
    def end(self) -> int:
        return self.offset + self.length

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GoldAnnotation":
        return cls(
            category=str(raw["category"]),
            offset=int(raw["offset"]),
            length=int(raw["length"]),
            accepted_replacements=tuple(str(x) for x in raw.get("accepted_replacements", ())),
            label=str(raw.get("label", "")),
            severity=str(raw.get("severity", "error")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "offset": self.offset,
            "length": self.length,
            "accepted_replacements": list(self.accepted_replacements),
            "label": self.label,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class Review:
    """An independent annotation pass for agreement measurement."""

    annotator: str
    annotations: tuple[GoldAnnotation, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Review":
        return cls(
            annotator=str(raw["annotator"]),
            annotations=tuple(GoldAnnotation.from_dict(item) for item in raw["annotations"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotator": self.annotator,
            "annotations": [annotation.to_dict() for annotation in self.annotations],
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """A versioned, provenance-bearing sentence-level benchmark case."""

    id: str
    text: str
    domain: str
    split: str
    dialect: str
    annotations: tuple[GoldAnnotation, ...]
    dataset: str
    license_id: str
    synthetic: bool
    reviews: tuple[Review, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.text:
            raise ValueError("Benchmark case id and text are required")
        if self.split not in VALID_SPLITS:
            raise ValueError(f"Unknown benchmark split: {self.split}")
        for annotation in self.annotations:
            if annotation.end > len(self.text):
                raise ValueError(f"{self.id}: annotation exceeds text length")
            if not self.text[annotation.offset : annotation.end]:
                raise ValueError(f"{self.id}: annotation points to an empty span")
        for review in self.reviews:
            for annotation in review.annotations:
                if annotation.end > len(self.text):
                    raise ValueError(f"{self.id}: review span exceeds text length")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BenchmarkCase":
        source = raw["source"]
        return cls(
            id=str(raw["id"]),
            text=str(raw["text"]),
            domain=str(raw["domain"]),
            split=str(raw["split"]),
            dialect=str(raw.get("dialect", "msa")),
            annotations=tuple(GoldAnnotation.from_dict(item) for item in raw["annotations"]),
            dataset=str(source["dataset"]),
            license_id=str(source["license"]),
            synthetic=bool(source.get("synthetic", False)),
            reviews=tuple(Review.from_dict(item) for item in raw.get("reviews", ())),
            metadata=dict(raw.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "id": self.id,
            "text": self.text,
            "domain": self.domain,
            "split": self.split,
            "dialect": self.dialect,
            "annotations": [annotation.to_dict() for annotation in self.annotations],
            "source": {
                "dataset": self.dataset,
                "license": self.license_id,
                "synthetic": self.synthetic,
            },
            "reviews": [review.to_dict() for review in self.reviews],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class Counts:
    """Confusion counts with derived precision/recall/F-beta metrics."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else 1.0

    def fbeta(self, beta: float = 0.5) -> float:
        if beta <= 0:
            raise ValueError("beta must be positive")
        precision = self.precision
        recall = self.recall
        if precision + recall == 0:
            return 0.0
        beta2 = beta * beta
        return (1 + beta2) * precision * recall / (beta2 * precision + recall)

    def add(self, other: "Counts") -> "Counts":
        return Counts(
            self.true_positives + other.true_positives,
            self.false_positives + other.false_positives,
            self.false_negatives + other.false_negatives,
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f0.5": self.fbeta(0.5),
        }


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Complete benchmark report with global and sliced metrics."""

    dataset: str
    split: str
    cases: int
    words: int
    span: Counts
    correction: Counts
    sentence_exact_accuracy: float
    sentence_error_detection: Counts
    mean_reciprocal_rank: float
    slices: Mapping[str, Mapping[str, Any]]
    failures: tuple[Mapping[str, Any], ...] = ()
    categories: tuple[str, ...] = ()

    @property
    def false_positives_per_1000_words(self) -> float:
        return self.span.false_positives * 1000 / self.words if self.words else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "split": self.split,
            "cases": self.cases,
            "words": self.words,
            "span": self.span.to_dict(),
            "correction": self.correction.to_dict(),
            "sentence_exact_accuracy": self.sentence_exact_accuracy,
            "sentence_error_detection": self.sentence_error_detection.to_dict(),
            "mean_reciprocal_rank": self.mean_reciprocal_rank,
            "false_positives_per_1000_words": self.false_positives_per_1000_words,
            "slices": dict(self.slices),
            "failures": [dict(item) for item in self.failures],
            "categories": list(self.categories),
        }


@dataclass(frozen=True, slots=True)
class AgreementReport:
    """Pairwise agreement for two independent annotation passes."""

    cases: int
    annotator_a: str
    annotator_b: str
    sentence_kappa: float
    span_f1: float
    correction_agreement: float
    exact_case_agreement: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validator() -> Draft202012Validator:
    schema = json.loads(BENCHMARK_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield non-empty JSON objects from a UTF-8 JSONL file."""

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{path}:{line_number}: case must be an object")
        yield raw


def load_cases(path: Path, *, validate_schema: bool = True) -> list[BenchmarkCase]:
    """Load and semantically validate a JSONL benchmark file."""

    validator = _validator() if validate_schema else None
    cases: list[BenchmarkCase] = []
    seen_ids: set[str] = set()
    for line_number, raw in enumerate(iter_jsonl(path), 1):
        if validator is not None:
            errors = sorted(validator.iter_errors(raw), key=lambda error: list(error.path))
            if errors:
                details = "; ".join(error.message for error in errors[:3])
                raise ValueError(f"{path}:{line_number}: schema validation failed: {details}")
        case = BenchmarkCase.from_dict(raw)
        if case.id in seen_ids:
            raise ValueError(f"{path}:{line_number}: duplicate case id {case.id}")
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def load_split(
    split: str = "test", *, benchmark_dir: Path = DEFAULT_BENCHMARK_DIR
) -> list[BenchmarkCase]:
    """Load one official split from the packaged Phase-2 benchmark."""

    if split not in VALID_SPLITS:
        raise ValueError(f"split must be one of {sorted(VALID_SPLITS)}")
    return load_cases(benchmark_dir / f"{split}.jsonl")


def _gold_key(annotation: GoldAnnotation) -> tuple[int, int, str]:
    return (annotation.offset, annotation.length, annotation.category)


def _prediction_key(match: Match) -> tuple[int, int, str]:
    return (match.offset, match.length, match.category)


def _case_counts(
    gold: Sequence[GoldAnnotation], predictions: Sequence[Match]
) -> tuple[Counts, Counts, list[float]]:
    gold_by_key = {_gold_key(annotation): annotation for annotation in gold}
    pred_by_key = {_prediction_key(match): match for match in predictions}
    gold_keys = set(gold_by_key)
    pred_keys = set(pred_by_key)
    span_tp = len(gold_keys & pred_keys)
    span_counts = Counts(span_tp, len(pred_keys - gold_keys), len(gold_keys - pred_keys))

    correction_tp = 0
    correction_fp = len(pred_keys - gold_keys)
    correction_fn = len(gold_keys - pred_keys)
    reciprocal_ranks: list[float] = []
    for key in gold_keys & pred_keys:
        annotation = gold_by_key[key]
        prediction = pred_by_key[key]
        if not annotation.accepted_replacements:
            correction_tp += 1
            continue
        rank = next(
            (
                index
                for index, replacement in enumerate(prediction.replacements, 1)
                if replacement in annotation.accepted_replacements
            ),
            None,
        )
        if rank is None:
            correction_fp += 1
            correction_fn += 1
            reciprocal_ranks.append(0.0)
        else:
            correction_tp += 1
            reciprocal_ranks.append(1.0 / rank)
    return span_counts, Counts(correction_tp, correction_fp, correction_fn), reciprocal_ranks


def _filter_gold(
    annotations: Sequence[GoldAnnotation], categories: frozenset[str] | None
) -> tuple[GoldAnnotation, ...]:
    if categories is None:
        return tuple(annotations)
    return tuple(item for item in annotations if item.category in categories)


def _filter_predictions(
    predictions: Sequence[Match], categories: frozenset[str] | None
) -> tuple[Match, ...]:
    if categories is None:
        return tuple(predictions)
    return tuple(item for item in predictions if item.category in categories)


def _slice_payload(
    cases: Sequence[BenchmarkCase], checker: Any, categories: frozenset[str] | None
) -> dict[str, Any]:
    span = Counts()
    correction = Counts()
    words = 0
    exact = 0
    for case in cases:
        predictions = _filter_predictions(checker.check(case.text), categories)
        annotations = _filter_gold(case.annotations, categories)
        case_span, case_correction, _ = _case_counts(annotations, predictions)
        span = span.add(case_span)
        correction = correction.add(case_correction)
        words += sum(1 for token in tokenize(case.text) if token.is_arabic)
        exact += int(
            {_gold_key(item) for item in annotations}
            == {_prediction_key(item) for item in predictions}
        )
    return {
        "cases": len(cases),
        "words": words,
        "span": span.to_dict(),
        "correction": correction.to_dict(),
        "sentence_exact_accuracy": exact / len(cases) if cases else 1.0,
        "false_positives_per_1000_words": span.false_positives * 1000 / words if words else 0.0,
    }


def evaluate_cases(
    cases: Sequence[BenchmarkCase],
    checker: Any,
    *,
    include_failures: bool = False,
    categories: Iterable[str] | None = None,
) -> EvaluationReport:
    """Evaluate a checker with exact span/category and correction metrics."""

    if not cases:
        raise ValueError("At least one benchmark case is required")
    category_filter = frozenset(categories) if categories is not None else None
    if category_filter is not None and not category_filter:
        raise ValueError("categories cannot be empty")
    span = Counts()
    correction = Counts()
    sentence_detection = Counts()
    reciprocal_ranks: list[float] = []
    exact_cases = 0
    words = 0
    failures: list[Mapping[str, Any]] = []
    by_domain: dict[str, list[BenchmarkCase]] = defaultdict(list)
    by_dialect: dict[str, list[BenchmarkCase]] = defaultdict(list)

    for case in cases:
        predictions = _filter_predictions(checker.check(case.text), category_filter)
        annotations = _filter_gold(case.annotations, category_filter)
        case_span, case_correction, case_rr = _case_counts(annotations, predictions)
        span = span.add(case_span)
        correction = correction.add(case_correction)
        reciprocal_ranks.extend(case_rr)
        words += sum(1 for token in tokenize(case.text) if token.is_arabic)
        gold_has_error = bool(annotations)
        predicted_has_error = bool(predictions)
        sentence_detection = sentence_detection.add(
            Counts(
                true_positives=int(gold_has_error and predicted_has_error),
                false_positives=int(not gold_has_error and predicted_has_error),
                false_negatives=int(gold_has_error and not predicted_has_error),
            )
        )
        gold_keys = {_gold_key(item) for item in annotations}
        pred_keys = {_prediction_key(item) for item in predictions}
        is_exact = gold_keys == pred_keys
        exact_cases += int(is_exact)
        if include_failures and not is_exact:
            failures.append(
                {
                    "id": case.id,
                    "domain": case.domain,
                    "dialect": case.dialect,
                    "text": case.text,
                    "gold": [item.to_dict() for item in annotations],
                    "predictions": [
                        {
                            "rule_id": item.rule_id,
                            "category": item.category,
                            "offset": item.offset,
                            "length": item.length,
                            "replacements": list(item.replacements),
                        }
                        for item in predictions
                    ],
                }
            )
        by_domain[case.domain].append(case)
        by_dialect[case.dialect].append(case)

    slices = {
        "domain": {
            name: _slice_payload(group, checker, category_filter)
            for name, group in sorted(by_domain.items())
        },
        "dialect": {
            name: _slice_payload(group, checker, category_filter)
            for name, group in sorted(by_dialect.items())
        },
    }
    return EvaluationReport(
        dataset=cases[0].dataset,
        split=cases[0].split if len({case.split for case in cases}) == 1 else "mixed",
        cases=len(cases),
        words=words,
        span=span,
        correction=correction,
        sentence_exact_accuracy=exact_cases / len(cases),
        sentence_error_detection=sentence_detection,
        mean_reciprocal_rank=(
            sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 1.0
        ),
        slices=slices,
        failures=tuple(failures),
        categories=tuple(sorted(category_filter)) if category_filter is not None else (),
    )


def evaluate_split(
    checker: Any,
    split: str = "test",
    *,
    benchmark_dir: Path = DEFAULT_BENCHMARK_DIR,
    include_failures: bool = False,
    categories: Iterable[str] | None = None,
) -> EvaluationReport:
    """Load and evaluate one official benchmark split."""

    return evaluate_cases(
        load_split(split, benchmark_dir=benchmark_dir),
        checker,
        include_failures=include_failures,
        categories=categories,
    )


def _annotation_set(annotations: Iterable[GoldAnnotation]) -> set[tuple[Any, ...]]:
    return {
        (
            annotation.offset,
            annotation.length,
            annotation.category,
            tuple(annotation.accepted_replacements),
        )
        for annotation in annotations
    }


def _cohen_kappa(labels_a: Sequence[bool], labels_b: Sequence[bool]) -> float:
    if len(labels_a) != len(labels_b) or not labels_a:
        raise ValueError("Kappa requires equally sized non-empty label sequences")
    observed = sum(a == b for a, b in zip(labels_a, labels_b)) / len(labels_a)
    p_a = sum(labels_a) / len(labels_a)
    p_b = sum(labels_b) / len(labels_b)
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    if math.isclose(expected, 1.0):
        return 1.0 if math.isclose(observed, 1.0) else 0.0
    return (observed - expected) / (1 - expected)


def compute_agreement(
    cases: Sequence[BenchmarkCase], annotator_a: str, annotator_b: str
) -> AgreementReport:
    """Compute sentence kappa, span F1, and correction agreement."""

    if not cases:
        raise ValueError("Agreement requires at least one reviewed case")
    sentence_a: list[bool] = []
    sentence_b: list[bool] = []
    span_tp = span_fp = span_fn = 0
    correction_matches = correction_total = exact = 0

    for case in cases:
        reviews = {review.annotator: review.annotations for review in case.reviews}
        if annotator_a not in reviews or annotator_b not in reviews:
            raise ValueError(f"{case.id}: missing requested annotator review")
        left = reviews[annotator_a]
        right = reviews[annotator_b]
        sentence_a.append(bool(left))
        sentence_b.append(bool(right))
        left_span = {_gold_key(item) for item in left}
        right_span = {_gold_key(item) for item in right}
        span_tp += len(left_span & right_span)
        span_fp += len(right_span - left_span)
        span_fn += len(left_span - right_span)
        exact += int(_annotation_set(left) == _annotation_set(right))
        left_by_span = {_gold_key(item): item for item in left}
        right_by_span = {_gold_key(item): item for item in right}
        for key in left_span & right_span:
            correction_total += 1
            correction_matches += int(
                bool(
                    set(left_by_span[key].accepted_replacements)
                    & set(right_by_span[key].accepted_replacements)
                )
                or (
                    not left_by_span[key].accepted_replacements
                    and not right_by_span[key].accepted_replacements
                )
            )

    span_counts = Counts(span_tp, span_fp, span_fn)
    return AgreementReport(
        cases=len(cases),
        annotator_a=annotator_a,
        annotator_b=annotator_b,
        sentence_kappa=_cohen_kappa(sentence_a, sentence_b),
        span_f1=span_counts.fbeta(1.0),
        correction_agreement=(correction_matches / correction_total if correction_total else 1.0),
        exact_case_agreement=exact / len(cases),
    )
