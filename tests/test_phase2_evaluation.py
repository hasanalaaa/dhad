"""Phase 2 corpus, metrics, agreement, licensing, and CLI regression tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from dhad import Dhad
from dhad.cli import main as cli_main
from dhad.evaluation import (
    BENCHMARK_SCHEMA_PATH,
    DEFAULT_BENCHMARK_DIR,
    BenchmarkCase,
    GoldAnnotation,
    Review,
    compute_agreement,
    evaluate_cases,
    evaluate_split,
    load_cases,
)
from dhad.match import Match

ROOT = Path(__file__).parents[1]


class FakeChecker:
    def __init__(self, results: dict[str, list[Match]]):
        self.results = results

    def check(self, text: str) -> list[Match]:
        return self.results.get(text, [])


def _case(
    case_id: str,
    text: str,
    annotations: tuple[GoldAnnotation, ...],
    *,
    reviews: tuple[Review, ...] = (),
) -> BenchmarkCase:
    return BenchmarkCase(
        id=case_id,
        text=text,
        domain="educational",
        split="test",
        dialect="msa",
        annotations=annotations,
        dataset="unit-test",
        license_id="CC0-1.0",
        synthetic=True,
        reviews=reviews,
    )


def test_benchmark_schema_is_valid() -> None:
    schema = json.loads(BENCHMARK_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_official_corpus_counts_splits_domains_and_no_leakage() -> None:
    expected = {"train": 3500, "dev": 750, "test": 750}
    all_cases = []
    for split, count in expected.items():
        cases = load_cases(DEFAULT_BENCHMARK_DIR / f"{split}.jsonl")
        assert len(cases) == count
        assert {case.split for case in cases} == {split}
        all_cases.extend(cases)
    assert len(all_cases) == 5000
    assert len({case.id for case in all_cases}) == 5000
    assert len({case.text for case in all_cases}) == 5000
    assert {case.domain for case in all_cases} == {
        "journalism",
        "academic",
        "administrative",
        "educational",
        "social",
        "dialect",
    }
    assert {case.dialect for case in all_cases} == {
        "msa",
        "iraqi",
        "gulf",
        "levantine",
        "egyptian",
    }


def test_manifest_hashes_and_counts_match_files() -> None:
    manifest = json.loads((DEFAULT_BENCHMARK_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_cases"] == 5000
    assert manifest["double_review_cases"] == 1000
    for filename, metadata in manifest["files"].items():
        payload = (DEFAULT_BENCHMARK_DIR / filename).read_bytes()
        assert payload.count(b"\n") == metadata["cases"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]


def test_all_gold_offsets_and_replacements_are_semantically_valid() -> None:
    for split in ("train", "dev", "test"):
        for case in load_cases(DEFAULT_BENCHMARK_DIR / f"{split}.jsonl"):
            previous_end = -1
            for annotation in sorted(case.annotations, key=lambda item: item.offset):
                source = case.text[annotation.offset : annotation.end]
                assert source
                assert annotation.offset >= previous_end
                assert all(
                    replacement != source for replacement in annotation.accepted_replacements
                )
                previous_end = annotation.end


def test_double_review_set_has_exactly_1000_cases_and_full_agreement() -> None:
    reviewed = load_cases(DEFAULT_BENCHMARK_DIR / "double_review.jsonl")
    assert len(reviewed) == 1000
    assert all(len(case.reviews) == 2 for case in reviewed)
    report = compute_agreement(
        reviewed,
        "template-annotation-pass",
        "independent-span-validation-pass",
    )
    assert report.cases == 1000
    assert report.sentence_kappa == 1.0
    assert report.span_f1 == 1.0
    assert report.correction_agreement == 1.0
    assert report.exact_case_agreement == 1.0


def test_span_correction_sentence_and_mrr_metrics_are_distinct() -> None:
    gold = GoldAnnotation("spelling", 0, 3, ("إلى",), "hamza")
    error_case = _case("e1", "الى البيت", (gold,))
    clean_case = _case("c1", "النص سليم", ())
    checker = FakeChecker(
        {
            "الى البيت": [
                Match(
                    "PRED",
                    "spelling",
                    "m",
                    0,
                    3,
                    replacements=["إلي", "إلى"],
                )
            ],
            "النص سليم": [Match("FP", "style", "m", 0, 4)],
        }
    )
    report = evaluate_cases([error_case, clean_case], checker)
    assert report.span.true_positives == 1
    assert report.span.false_positives == 1
    assert report.span.false_negatives == 0
    assert report.correction.true_positives == 1
    assert report.mean_reciprocal_rank == 0.5
    assert report.sentence_exact_accuracy == 0.5
    assert report.sentence_error_detection.true_positives == 1
    assert report.sentence_error_detection.false_positives == 1


def test_wrong_correction_counts_as_correction_fp_and_fn() -> None:
    gold = GoldAnnotation("spelling", 0, 3, ("إلى",), "hamza")
    case = _case("e1", "الى", (gold,))
    checker = FakeChecker({"الى": [Match("PRED", "spelling", "m", 0, 3, replacements=["علي"])]})
    report = evaluate_cases([case], checker)
    assert report.span.to_dict()["f0.5"] == 1.0
    assert report.correction.true_positives == 0
    assert report.correction.false_positives == 1
    assert report.correction.false_negatives == 1
    assert report.mean_reciprocal_rank == 0.0


def test_dataset_registry_covers_every_bundled_dataset_and_license() -> None:
    registry = yaml.safe_load((ROOT / "benchmarks" / "datasets.yml").read_text(encoding="utf-8"))
    datasets = registry["datasets"]
    assert {item["id"] for item in datasets} == {
        "dhad-phase0-seed",
        "dhad-controlled-gold-v1",
    }
    for item in datasets:
        assert item["license"]
        assert item["path"]
        assert (ROOT / item["path"]).exists()
        assert isinstance(item["synthetic"], bool)


def test_saved_v040_baseline_is_reproducible() -> None:
    saved = json.loads(
        (ROOT / "reports" / "benchmark_v0.4.0_test.json").read_text(encoding="utf-8")
    )
    current = evaluate_split(
        Dhad(
            lexical_spellcheck=False, syntax_checks=False, dialect_checks=False, style_checks=False
        ),
        "test",
    ).to_dict()
    for key in (
        "cases",
        "words",
        "span",
        "correction",
        "sentence_exact_accuracy",
        "mean_reciprocal_rank",
        "false_positives_per_1000_words",
    ):
        assert current[key] == saved[key]


def test_saved_v050_baseline_is_reproducible() -> None:
    saved = json.loads(
        (ROOT / "reports" / "benchmark_v0.5.0_test.json").read_text(encoding="utf-8")
    )
    current = evaluate_split(
        Dhad(syntax_checks=False, dialect_checks=False, style_checks=False), "test"
    ).to_dict()
    for key in (
        "cases",
        "words",
        "span",
        "correction",
        "sentence_exact_accuracy",
        "mean_reciprocal_rank",
        "false_positives_per_1000_words",
    ):
        assert current[key] == saved[key]


def test_saved_v060_baseline_is_reproducible() -> None:
    saved = json.loads(
        (ROOT / "reports" / "benchmark_v0.6.0_test.json").read_text(encoding="utf-8")
    )
    current = evaluate_split(Dhad(dialect_checks=False, style_checks=False), "test").to_dict()
    for key in (
        "cases",
        "words",
        "span",
        "correction",
        "sentence_exact_accuracy",
        "mean_reciprocal_rank",
        "false_positives_per_1000_words",
    ):
        assert current[key] == saved[key]


def test_saved_v080_baseline_is_reproducible() -> None:
    saved = json.loads(
        (ROOT / "reports" / "benchmark_v0.8.0_test.json").read_text(encoding="utf-8")
    )
    current = evaluate_split(Dhad(neural_checks=False), "test").to_dict()
    for key in (
        "cases",
        "words",
        "span",
        "correction",
        "sentence_exact_accuracy",
        "mean_reciprocal_rank",
        "false_positives_per_1000_words",
    ):
        assert current[key] == saved[key]


def test_saved_v090_baseline_is_reproducible() -> None:
    saved = json.loads(
        (ROOT / "reports" / "benchmark_v0.9.0_test.json").read_text(encoding="utf-8")
    )
    current = evaluate_split(Dhad(), "test").to_dict()
    for key in (
        "cases",
        "words",
        "span",
        "correction",
        "sentence_exact_accuracy",
        "mean_reciprocal_rank",
        "false_positives_per_1000_words",
    ):
        assert current[key] == saved[key]


def test_saved_v010_baseline_is_reproducible() -> None:
    saved = json.loads(
        (ROOT / "reports" / "benchmark_v0.10.0_test.json").read_text(encoding="utf-8")
    )
    current = evaluate_split(Dhad(), "test").to_dict()
    for key in (
        "cases",
        "words",
        "span",
        "correction",
        "sentence_exact_accuracy",
        "mean_reciprocal_rank",
        "false_positives_per_1000_words",
    ):
        assert current[key] == saved[key]


def test_saved_v011_baseline_is_reproducible() -> None:
    saved = json.loads(
        (ROOT / "reports" / "benchmark_v0.11.0_test.json").read_text(encoding="utf-8")
    )
    current = evaluate_split(Dhad(), "test").to_dict()
    for key in (
        "cases",
        "words",
        "span",
        "correction",
        "sentence_exact_accuracy",
        "mean_reciprocal_rank",
        "false_positives_per_1000_words",
    ):
        assert current[key] == saved[key]


def test_benchmark_cli_runs_with_json_and_threshold(capsys) -> None:
    assert cli_main(["benchmark", "--split", "test", "--json", "--fail-under-f05", "0.80"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dataset"] == "dhad-controlled-gold-v1"
    assert payload["cases"] == 750
    assert payload["span"]["f0.5"] >= 0.80
    assert cli_main(["benchmark", "--split", "test", "--fail-under-f05", "0.99"]) == 1
